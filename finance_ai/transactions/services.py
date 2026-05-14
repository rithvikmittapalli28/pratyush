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
    summary = get_financial_summary(user)

    return {
        "total_spent": summary["total_spent"],
        "category_breakdown": summary["category"],
        "forecast": {
            "remaining_balance": summary["remaining_balance"],
            "runway_days": summary["runway_days"],
        },
    }
