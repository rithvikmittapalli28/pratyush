from ai_engine.ai_service import call_ai

# Allowed categories (single source of truth)
ALLOWED_CATEGORIES = [
    "Food", "Transport", "Bills",
    "Shopping", "Entertainment", "Salary", "Other"
]


# -------------------------------
# SAFE CATEGORY EXTRACTION (VERY STRICT)
# -------------------------------
def extract_category(text):
    if not text:
        return "Other"

    text = text.lower().strip()

    mapping = {
        "food": "Food",
        "restaurant": "Food",
        "swiggy": "Food",
        "zomato": "Food",

        "transport": "Transport",
        "travel": "Transport",
        "uber": "Transport",
        "ola": "Transport",

        "bills": "Bills",
        "electricity": "Bills",
        "rent": "Bills",
        "utilities": "Bills",

        "shopping": "Shopping",
        "amazon": "Shopping",
        "flipkart": "Shopping",

        "entertainment": "Entertainment",
        "movie": "Entertainment",
        "netflix": "Entertainment",

        "salary": "Salary",
        "income": "Salary"
    }

    for key, value in mapping.items():
        if key in text:
            return value

    return "Other"


# -------------------------------
# 1. CATEGORIZATION (AI + RULE HYBRID)
# -------------------------------
def categorize_transaction(merchant):
    prompt = f"""
Classify this transaction into ONE category.

Transaction: "{merchant}"

Categories:
Food, Transport, Bills, Shopping, Entertainment, Salary, Other

Rules:
- Return ONLY one word
- No explanation

Answer:
"""

    result = call_ai(prompt)

    # Fallback safety
    if not result:
        return extract_category(merchant)

    category = extract_category(result)

    # Final safety check
    if category not in ALLOWED_CATEGORIES:
        return "Other"

    return category


# -------------------------------
# 2. MERCHANT CLEANING (STRICT + SAFE)
# -------------------------------
def clean_merchant(name):
    if not name:
        return "Unknown"

    name = name.strip()

    prompt = f"""
Clean this merchant name:

"{name}"

Rules:
- Return ONLY clean name
- Max 2 words
- No explanation
- No symbols

Examples:
AMZN MKTPLACE -> Amazon
SWIGGY LTD -> Swiggy
UBER INDIA -> Uber

Answer:
"""

    result = call_ai(prompt)

    if not result:
        return name

    cleaned = result.strip().split("\n")[0]

    # Safety filters
    if len(cleaned) > 40:
        return name

    if any(x in cleaned.lower() for x in ["transaction", "category", "this", "falls"]):
        return name

    return cleaned


# -------------------------------
# 3. AI INSIGHT HELPERS
# -------------------------------
def format_inr(amount):
    amount = round(float(amount), 2)

    if amount.is_integer():
        return f"Rs {int(amount):,}"

    return f"Rs {amount:,.2f}"


def get_reduction_target(share_percent):
    if share_percent >= 35:
        return 20
    if share_percent >= 20:
        return 15
    return 10


def get_action_type(category):
    category_key = str(category).strip().lower()

    mapping = {
        "bills": "view",
        "shopping": "budget",
        "food": "alert",
    }

    return mapping.get(category_key, "view")


def build_category_insight(category, amount, total_spent):
    if total_spent <= 0 or amount <= 0:
        return None

    normalized_category = str(category).strip().lower()
    share_percent = (amount / total_spent) * 100
    reduction_percent = get_reduction_target(share_percent)
    monthly_savings = round(amount * (reduction_percent / 100.0), 2)
    total_impact_percent = (monthly_savings / total_spent) * 100

    impact_score = round(min(100, (share_percent * 1.2) + (total_impact_percent * 2.5)))

    return {
        "insight": (
            f"You can save {format_inr(monthly_savings)}/month by reducing "
            f"{category} spend by {reduction_percent}%"
        ),
        "reason": (
            f"{category} is {format_inr(amount)} or {share_percent:.1f}% of your "
            f"total spend, so this change can lower monthly spending by "
            f"{total_impact_percent:.1f}%"
        ),
        "confidence": round(min(0.95, max(0.65, 0.7 + (share_percent / 100))), 2),
        "impact_score": impact_score,
        "action_type": get_action_type(normalized_category),
        "category": normalized_category,
    }


# -------------------------------
# 3. AI INSIGHT GENERATOR (ACTIONABLE VERSION)
# -------------------------------
def generate_ai_insights(summary_data):
    total_spent = float(summary_data.get("total_spent", 0) or 0)
    category_breakdown = summary_data.get("category_breakdown", {}) or {}

    if total_spent <= 0 or not category_breakdown:
        return [
            {
                "insight": "Your tracked spending is Rs 0, so keep monitoring new expenses",
                "reason": "There is no spend data available yet, so no savings opportunity can be quantified",
                "confidence": 0.95,
                "impact_score": 0,
                "action_type": "view",
                "category": "other",
            }
        ]

    insights = []

    for category, amount in category_breakdown.items():
        try:
            amount = float(amount or 0)
        except (TypeError, ValueError):
            amount = 0

        insight = build_category_insight(category, amount, total_spent)
        if insight:
            insights.append(insight)

    insights.sort(key=lambda item: item["impact_score"], reverse=True)

    return insights[:3]

# -------------------------------
# 4. REFINE INSIGHTS (OPTIONAL)
# -------------------------------
def refine_insights(insights_list):
    prompt = f"""
Improve these insights:

{insights_list}

Make them:
- Clear
- Short
- Professional
"""

    result = call_ai(prompt)

    if not result:
        return insights_list

    lines = [
        line.strip("- ").strip()
        for line in result.split("\n")
        if line.strip()
    ]

    return lines[:3]