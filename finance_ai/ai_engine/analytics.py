from collections import defaultdict
from datetime import date

# Allowed categories (single source of truth)
ALLOWED = {
    "food": "Food",
    "transport": "Transport",
    "bills": "Bills",
    "shopping": "Shopping",
    "entertainment": "Entertainment",
    "salary": "Salary",
    "other": "Other"
}


def normalize_category(raw):
    if not raw:
        return "Other"

    raw = raw.lower()

    for key in ALLOWED:
        if key in raw:
            return ALLOWED[key]

    return "Other"


def get_month_windows(today):
    current_month_start = today.replace(day=1)

    if current_month_start.month == 1:
        last_month_start = current_month_start.replace(
            year=current_month_start.year - 1,
            month=12,
        )
    else:
        last_month_start = current_month_start.replace(
            month=current_month_start.month - 1,
        )

    return current_month_start, last_month_start


def calculate_monthly_change(current_spend, last_month_spend):
    if last_month_spend == 0:
        if current_spend == 0:
            return 0
        return 100

    return round(((current_spend - last_month_spend) / last_month_spend) * 100)


def build_anomalies(current_month_categories, last_month_categories):
    anomalies = []
    all_categories = set(current_month_categories) | set(last_month_categories)

    for category in all_categories:
        current_amount = current_month_categories.get(category, 0)
        last_amount = last_month_categories.get(category, 0)

        if current_amount <= 0:
            continue

        if last_amount == 0:
            change_percent = 100
        else:
            change_percent = ((current_amount - last_amount) / last_amount) * 100

        if change_percent > 30:
            anomalies.append({
                "category": category,
                "current_spend": round(current_amount, 2),
                "last_month_spend": round(last_amount, 2),
                "change_percent": round(change_percent, 1),
            })

    anomalies.sort(key=lambda item: item["change_percent"], reverse=True)
    return anomalies


def detect_anomalies(transactions):
    from collections import defaultdict

    category_totals = defaultdict(float)

    for t in transactions:
        category_totals[t.category] += float(t.amount)

    total = sum(category_totals.values())

    anomalies = []

    for category, value in category_totals.items():
        percent = (value / total) * 100 if total else 0

        if percent > 30:
            anomalies.append(
                f"{category} spending is unusually high at {int(percent)}% of total"
            )

    return anomalies


def calculate_savings_opportunity(total_spent, category_data):
    if total_spent <= 0:
        return 0

    savings = 0

    for amount in category_data.values():
        share_percent = (amount / total_spent) * 100

        if share_percent >= 35:
            savings += amount * 0.20
        elif share_percent >= 20:
            savings += amount * 0.15
        elif share_percent >= 10:
            savings += amount * 0.10

    return round(savings)


def calculate_spending_trend(transactions):
    from collections import defaultdict

    daily_spend = defaultdict(float)

    for t in transactions:
        if t.amount < 0:
            date_str = t.date.strftime("%Y-%m-%d")
            daily_spend[date_str] += abs(float(t.amount))

    # sort by date
    sorted_trend = sorted(daily_spend.items())

    return [
        {"date": date, "spend": value}
        for date, value in sorted_trend
    ]


def calculate_dashboard(transactions):
    today = date.today()
    current_month_start, last_month_start = get_month_windows(today)

    total_spent = 0
    category_data = defaultdict(float)
    current_month_spent = 0
    last_month_spent = 0
    current_month_categories = defaultdict(float)
    last_month_categories = defaultdict(float)

    for t in transactions:
        if t.amount < 0:  # spending only
            amount = abs(t.amount)

            # Force clean category
            clean_cat = normalize_category(t.category)

            total_spent += amount
            category_data[clean_cat] += amount

            if t.date >= current_month_start:
                current_month_spent += amount
                current_month_categories[clean_cat] += amount
            elif last_month_start <= t.date < current_month_start:
                last_month_spent += amount
                last_month_categories[clean_cat] += amount

    data = {
        "total_spent": total_spent,
        "category_breakdown": dict(category_data),
        "monthly_change": calculate_monthly_change(current_month_spent, last_month_spent),
        "anomalies": detect_anomalies(transactions),
        "savings_opportunity": calculate_savings_opportunity(total_spent, category_data),
    }

    data["spending_trend"] = calculate_spending_trend(transactions)

    return data