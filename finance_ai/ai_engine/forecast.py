import numpy as np
from datetime import date


def calculate_forecast(transactions):
    if not transactions:
        return {
            "daily_spend": 0,
            "predicted_month_spend": 0,
            "runway_days": 0
        }

    today = date.today()

    # Only current month transactions
    current_month_txns = [
        t for t in transactions
        if t.date.month == today.month and t.amount < 0
    ]

    if not current_month_txns:
        return {
            "daily_spend": 0,
            "predicted_month_spend": 0,
            "runway_days": 0
        }

    total_spent = sum(abs(t.amount) for t in current_month_txns)

    days_passed = today.day
    days_in_month = 30  # keep simple

    daily_spend = total_spent / max(days_passed, 1)

    predicted_month_spend = daily_spend * days_in_month

    # Assume starting balance (mock for now)
    starting_balance = 20000  

    remaining_balance = starting_balance - total_spent

    runway_days = remaining_balance / daily_spend if daily_spend > 0 else 0

    return {
        "daily_spend": round(daily_spend, 2),
        "predicted_month_spend": round(predicted_month_spend, 2),
        "remaining_balance": round(remaining_balance, 2),
        "runway_days": int(runway_days)
    }