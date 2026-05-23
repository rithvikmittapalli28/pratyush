from django.db.models import Sum

from transactions.models import Transaction


def get_financial_summary(user):
    transactions = Transaction.objects.filter(user=user)
    expenses = Transaction.objects.filter(user=user, amount__lt=0)

    category_data = expenses.values("category").annotate(total=Sum("amount"))

    category = {
        item["category"]: abs(item["total"])
        for item in category_data
    }

    total_spent = sum(category.values())

    income = Transaction.objects.filter(user=user, amount__gt=0).aggregate(
        total=Sum("amount")
    )["total"] or 0

    remaining_balance = income - total_spent

    dates = set(tx.date for tx in transactions if tx.amount < 0)
    active_days = len(dates)

    if active_days == 0:
        avg_daily = 0
    else:
        avg_daily = total_spent / active_days

    runway = int(remaining_balance / avg_daily) if avg_daily > 0 else 0

    if runway < 0:
        runway = 0

    return {
        "total_spent": total_spent,
        "category": category,
        "income": income,
        "remaining_balance": remaining_balance,
        "runway_days": runway,
    }


def get_dashboard_data(user):
    from collections import defaultdict
    from ai_engine.analytics import calculate_dashboard

    transactions = Transaction.objects.filter(user=user)
    expenses = [t for t in transactions if t.amount < 0]
    summary = get_financial_summary(user)
    data = calculate_dashboard(transactions)

    # Compute category totals excluding 'salary' (matching dashboard view exactly)
    category_totals = defaultdict(float)
    for tx in expenses:
        category = tx.category or "Other"
        if str(category).strip().lower() == "salary":
            continue
        category_totals[category] += abs(tx.amount)

    # Compute daily anomalies
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

    # Compile warnings exactly like the warning engine does
    from transactions.views import generate_warnings
    dashboard_data = {
        "forecast": {
            "runway_days": summary["runway_days"],
        },
        "anomaly_warnings": anomaly_warnings,
    }
    warnings = generate_warnings(dashboard_data)

    return {
        "total_spent": summary["total_spent"],
        "category_breakdown": dict(category_totals),
        "forecast": {
            "remaining_balance": summary["remaining_balance"],
            "runway_days": summary["runway_days"],
        },
        "savings_opportunity": data.get("savings_opportunity", 0),
        "anomalies": anomaly_warnings,
        "warnings": warnings,
    }
