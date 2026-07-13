import csv
from collections import defaultdict
from io import TextIOWrapper

import pandas as pd
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.utils import timezone

from .models import Transaction, AIInsightLog, Budget, Alert
from ai_engine.utils import (
    categorize_transaction,
    clean_merchant,
    generate_ai_insights,
    extract_category
)
from ai_engine.analytics import calculate_dashboard
from .services import get_financial_summary


def clean_text(obj):
    if isinstance(obj, str):
        return obj.encode("ascii", "ignore").decode()
    if isinstance(obj, list):
        return [clean_text(x) for x in obj]
    if isinstance(obj, dict):
        return {k: clean_text(v) for k, v in obj.items()}
    return obj


def api_response(payload, status=200):
    return Response(clean_text(payload), status=status)


# -------------------------------
# INSIGHT CLASSIFIER
# -------------------------------
def classify_insight(insight):
    text = insight.lower()

    if "bill" in text:
        return "bills"
    elif "food" in text:
        return "food"
    elif "transport" in text:
        return "transport"
    elif "shop" in text:
        return "shopping"
    elif "daily" in text or "spend" in text:
        return "spending"
    else:
        return "other"


# -------------------------------
# CSV UPLOAD API
# -------------------------------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_csv(request):
    file = request.FILES.get("file")

    if not file:
        return api_response({"error": "No file provided"}, status=400)

    try:
        decoded_file = TextIOWrapper(file.file, encoding="utf-8")
        reader = csv.DictReader(decoded_file)

        required_cols = {"date", "description", "amount"}
        if not reader.fieldnames or not required_cols.issubset(
            {field.strip().lower() for field in reader.fieldnames if field}
        ):
            return api_response({"error": "CSV must include date, description, and amount"}, status=400)

        with db_transaction.atomic():
            for row in reader:
                description = str(row.get("description", "")).strip()
                amount = float(row["amount"])

                # Robust date parsing
                try:
                    parsed_date = pd.to_datetime(row["date"]).date()
                except Exception:
                    parsed_date = timezone.localdate()

                # Robust category normalization
                raw_cat = str(row.get("category", "") or "").strip()
                if not raw_cat or raw_cat.lower() == "other" or len(raw_cat) > 20:
                    category = categorize_transaction(description)
                else:
                    category = extract_category(raw_cat)

                Transaction.objects.create(
                    user=request.user,
                    date=parsed_date,
                    merchant=description,
                    amount=amount,
                    category=category,
                )

        return api_response({"message": "Upload successful"})

    except Exception as e:
        return api_response({"error": str(e)}, status=500)


# -------------------------------
# MANUAL ADD TRANSACTION
# -------------------------------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_transaction(request):
    try:
        user = request.user
        print("Current user:", request.user)

        merchant = clean_merchant(str(request.data.get('merchant', 'Unknown')).strip())
        amount = float(request.data.get('amount', 0))

        date = pd.to_datetime(request.data.get('date'), errors='coerce')
        if pd.isna(date):
            return api_response({"error": "Invalid date format"}, status=400)
        date = date.date()

        # Read and normalize category if provided, otherwise classify
        req_category = request.data.get('category')
        if req_category and str(req_category).strip():
            from ai_engine.utils import ALLOWED_CATEGORIES, extract_category
            normalized_categories = {c.lower(): c for c in ALLOWED_CATEGORIES}
            cat_lower = str(req_category).strip().lower()
            if cat_lower in normalized_categories:
                category = normalized_categories[cat_lower]
            else:
                category = extract_category(str(req_category))
        else:
            category = categorize_transaction(merchant)

        tx = Transaction.objects.create(
            user=user,
            amount=amount,
            merchant=merchant,
            category=category,
            date=date
        )

        return api_response({
            "status": "added",
            "transaction_id": tx.id,
            "category": category
        })

    except Exception as e:
        return api_response({"error": str(e)}, status=500)


# -------------------------------
# SET BUDGET API
# -------------------------------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_budget(request):
    try:
        user = request.user
        category = str(request.data.get('category', '')).strip()
        limit_value = request.data.get('limit')

        if not category:
            return api_response({"error": "Category is required"}, status=400)

        try:
            limit_value = float(limit_value)
        except (TypeError, ValueError):
            return api_response({"error": "Limit must be a valid number"}, status=400)

        if limit_value < 0:
            return api_response({"error": "Limit must be non-negative"}, status=400)

        budget, created = Budget.objects.update_or_create(
            user=user,
            category=category,
            defaults={"limit": limit_value},
        )

        return api_response({
            "status": "success",
            "message": "Budget created successfully" if created else "Budget updated successfully",
            "category": budget.category,
            "limit": budget.limit,
        })

    except Exception as e:
        return api_response({"error": str(e)}, status=500)


# -------------------------------
# SET ALERT API
# -------------------------------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_alert(request):
    try:
        user = request.user
        category = str(request.data.get('category', '')).strip()
        threshold = request.data.get('threshold')

        if not category:
            return api_response({"error": "Category is required"}, status=400)

        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return api_response({"error": "Threshold must be a valid number"}, status=400)

        if threshold < 0:
            return api_response({"error": "Threshold must be non-negative"}, status=400)

        Alert.objects.create(
            user=user,
            category=category,
            threshold=threshold,
        )

        return api_response({"message": "Alert created"})

    except Exception as e:
        return api_response({"error": str(e)}, status=500)


# -------------------------------
# WARNING ENGINE
# -------------------------------
def generate_warnings(data):
    warnings = []

    forecast = data.get("forecast", {})
    anomaly_warnings = data.get("anomaly_warnings", [])

    runway = forecast.get("runway_days", 999)

    if runway <= 3:
        warnings.append("Critical: funds may be exhausted within 3 days")
    elif runway <= 7:
        warnings.append(f"You may run out of money in {runway} days")

    warnings.extend(anomaly_warnings)

    return warnings


# -------------------------------
# FINAL AUDIT LOGGER (FIXED)
# -------------------------------
def save_ai_logs(user, insights):
    try:
        recent_logs = AIInsightLog.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timezone.timedelta(days=1)
        )

        # Use stored category (important fix)
        existing_categories = {log.source for log in recent_logs}

        new_categories_added = set()

        for item in insights:
            insight_text = item.get("insight", "")
            category = classify_insight(insight_text)

            # Skip duplicates (DB + current loop)
            if category in existing_categories or category in new_categories_added:
                continue

            AIInsightLog.objects.create(
                user=user,
                insight=insight_text,
                reason=item.get("reason", ""),
                confidence=float(item.get("confidence", 0.5)),
                source=category
            )

            new_categories_added.add(category)

    except Exception as e:
        print("Log save error:", e)


# -------------------------------
# DASHBOARD API
# -------------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard(request):
    try:
        user = request.user
        print("Current user:", request.user)

        transactions = Transaction.objects.filter(user=user)
        expenses = [t for t in transactions if t.amount < 0]
        summary = get_financial_summary(request.user)

        data = calculate_dashboard(transactions)

        data["forecast"] = {
            "remaining_balance": summary["remaining_balance"],
            "runway_days": summary["runway_days"],
        }

        total_spent = summary["total_spent"]

        category_totals = defaultdict(float)
        for tx in expenses:
            category = tx.category or "Other"
            if str(category).strip().lower() == "salary":
                continue
            category_totals[category] += abs(tx.amount)

        category_percent = {
            cat: (value / total_spent) * 100
            for cat, value in category_totals.items()
            if total_spent > 0
        }

        anomaly_warnings = []
        category_daily = defaultdict(lambda: defaultdict(float))

        for tx in expenses:
            category = tx.category or "Other"
            category_daily[category][tx.date] += abs(tx.amount)

        for category, daily_data in category_daily.items():
            dates = sorted(daily_data.keys())

            if len(dates) < 3:
                continue

            values = [daily_data[day] for day in dates]
            avg_spend = sum(values[:-1]) / (len(values) - 1)
            current_spend = values[-1]

            if avg_spend > 0 and current_spend > avg_spend * 1.3:
                percent = ((current_spend - avg_spend) / avg_spend) * 100
                anomaly_warnings.append(
                    f"{category} spending increased by {round(percent)}% compared to recent average"
                )

        data["total_spent"] = total_spent
        data["category_breakdown"] = dict(category_totals)
        data["category_percent"] = category_percent
        data["anomaly_warnings"] = anomaly_warnings
        data["anomalies"] = anomaly_warnings

        ai_insights = generate_ai_insights(data)

        # Fixed logging
        save_ai_logs(user, ai_insights)

        data["insights"] = [i.get("insight") for i in ai_insights]
        data["insight_details"] = ai_insights
        data["warnings"] = generate_warnings(data)
        data["total_transactions"] = transactions.count()

        data = clean_text(data)
        return Response(data)

    except Exception as e:
        return api_response({"error": str(e)}, status=500)


# -------------------------------
# AUDIT LOG API
# -------------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def audit_logs(request):
    try:
        user = request.user
        print("Current user:", request.user)

        logs = AIInsightLog.objects.filter(user=user)\
            .order_by('-created_at')[:20]

        return api_response([
            {
                "insight": log.insight,
                "reason": log.reason,
                "confidence": log.confidence,
                "time": log.created_at,
                "category": log.source   # Real category now
            }
            for log in logs
        ])

    except Exception as e:
        return api_response({"error": str(e)}, status=500)


# -------------------------------
# CATEGORY TRANSACTIONS API
# -------------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def category_transactions(request):
    try:
        user = request.user
        category = request.GET.get('category')

        if not category:
            return api_response({"error": "Category query parameter is required"}, status=400)

        transactions = Transaction.objects.filter(
            user=user,
            category=category
        ).order_by('-date', '-id')[:20]

        return api_response([
            {
                "amount": tx.amount,
                "category": tx.category,
                "date": tx.date,
                "description": tx.merchant
            }
            for tx in transactions
        ])

    except Exception as e:
        return api_response({"error": str(e)}, status=500)