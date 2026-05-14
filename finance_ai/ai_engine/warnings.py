def generate_warnings(data):
    warnings = []

    forecast = data.get("forecast", {})
    breakdown = data.get("category_breakdown", {})
    total_spent = data.get("total_spent", 0)

    runway = forecast.get("runway_days", 999)

    # 1. Low runway warning
    if runway < 15:
        warnings.append(f"You may run out of money in {runway} days")

    # 2. High spending warning
    if total_spent > 10000:
        warnings.append("Your total spending is very high this month")

    # 3. Category dominance warning (FIXED GRAMMAR)
    for category, value in breakdown.items():
        if total_spent > 0:
            percent = (value / total_spent) * 100

            if percent > 50:
                verb = "accounts" if not category.endswith("s") else "account"
                warnings.append(
                    f"{category} {verb} for {int(percent)}% of your spending"
                )

    return warnings