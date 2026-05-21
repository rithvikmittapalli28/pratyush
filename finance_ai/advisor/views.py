from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from transactions.services import get_dashboard_data
from ai_engine.ai_service import call_ai_chat
from ai_engine.market_service import get_market_context
from advisor.conversation import conversation_manager

import logging

logger = logging.getLogger("advisor")


# -------------------------------
# SIGNUP
# -------------------------------
@api_view(['POST'])
@permission_classes([])
def signup(request):
    username = request.data.get("username")
    password = request.data.get("password")

    if not username or not password:
        return Response({"error": "Username and password required"}, status=400)

    if User.objects.filter(username=username).exists():
        return Response({"error": "User already exists"}, status=400)

    User.objects.create_user(username=username, password=password)
    return Response({"message": "User created successfully"})


# -------------------------------
# LOGIN
# -------------------------------
@api_view(['POST'])
@permission_classes([])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")

    user = authenticate(username=username, password=password)

    if user is None:
        return Response({"error": "Invalid credentials"}, status=401)

    refresh = RefreshToken.for_user(user)

    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh)
    })


# -------------------------------
# CURRENT USER
# -------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_me(request):
    user = request.user

    return Response({
        "id": user.id,
        "username": user.username,
    })


# -------------------------------
# INTENT DETECTION (EXPANDED)
# -------------------------------
def detect_intent(msg: str):
    """
    Detect user intent from message text.
    Expanded beyond the original 3 intents to cover investment,
    budgeting, income, tax, and general financial queries.
    """
    msg = msg.lower()

    if any(w in msg for w in ["runway", "how long", "last", "survive", "days left"]):
        return "runway"

    if any(w in msg for w in ["overspend", "overspending", "too much", "where am i overspending"]):
        return "overspending"

    if any(w in msg for w in ["cut", "reduce", "improve savings", "what should i cut"]):
        return "savings"

    if any(w in msg for w in [
        "invest", "investment", "returns", "stock", "mutual fund",
        "gold", "silver", "sip", "nifty", "sensex", "share",
        "portfolio", "fd", "fixed deposit", "ppf", "nps",
        "where should i put", "better returns", "grow my money"
    ]):
        return "invest"

    if any(w in msg for w in ["budget", "allocat", "50 30 20", "split", "divide income"]):
        return "budget"

    if any(w in msg for w in ["income", "salary", "earn", "earning"]):
        return "income"

    if any(w in msg for w in ["tax", "80c", "elss", "deduction", "itr"]):
        return "tax"

    if any(w in msg for w in ["emergency", "insurance", "protect", "safety net"]):
        return "safety"

    if any(w in msg for w in ["save", "saving"]):
        return "savings"

    if any(w in msg for w in ["spend", "spending", "where money", "breakdown", "expense"]):
        return "spending"

    # General financial questions get a helpful response
    return "general"


# -------------------------------
# BUILD FINANCIAL CONTEXT FOR AI
# -------------------------------
def _build_system_prompt(data):
    """
    Build a comprehensive system prompt that gives the AI full financial
    context AND market awareness so it can provide personalized,
    data-driven responses for any financial question.
    """
    forecast = data.get("forecast", {})
    category = data.get("category_breakdown", {})
    total_spent = data.get("total_spent", 0)
    runway = forecast.get("runway_days", 0)
    remaining = forecast.get("remaining_balance", 0)

    # Format category breakdown for the AI
    cat_lines = "\n".join(
        f"  - {cat}: Rs {amt}" for cat, amt in category.items()
    ) if category else "  No spending data yet."

    # Get market context (live data if API key is set, else general knowledge)
    market_context = get_market_context()

    return f"""You are "Finance AI" — a smart, expert-level personal finance assistant and investment advisor.
You help users with ALL aspects of personal finance: spending analysis, budgeting, saving strategies,
investment advice, tax planning, insurance, retirement planning, and wealth building.

CURRENT USER FINANCIAL DATA:
- Total spent: Rs {total_spent}
- Remaining balance: Rs {remaining}
- Runway (days until funds run out): {runway} days
- Spending by category:
{cat_lines}

{market_context}

CORE RULES:
- Always use the real user financial data above — never fabricate numbers about their spending.
- Use INR (Rs) for all currency amounts.
- Be actionable: give specific, numbered steps when possible.
- Be encouraging but honest about spending habits and investment risks.
- Use bullet points and clear formatting for readability.
- Keep responses focused and useful (3-8 sentences for simple questions, longer for complex analysis).

SPENDING & SAVINGS QUESTIONS:
- Reference their actual spending categories and amounts.
- Suggest specific categories to cut and by how much.
- Calculate potential savings with concrete numbers.

INVESTMENT QUESTIONS:
- Provide asset allocation suggestions based on their spending patterns and remaining balance.
- Cover relevant asset classes: Gold, Silver, Mutual Funds (SIPs), Index Funds, Fixed Deposits, PPF, NPS, Stocks.
- Always mention risk levels (low/medium/high) for each suggestion.
- Recommend an emergency fund (3-6 months of expenses) before aggressive investing.
- For Indian investors, mention tax-saving options (ELSS, PPF, NPS under 80C) when relevant.
- If you don't have live market data, give directional advice based on general market principles.
- Always add a disclaimer to consult a certified financial advisor for large investment decisions.

BUDGETING QUESTIONS:
- Suggest the 50/30/20 rule or similar frameworks adapted to their data.
- Calculate ideal budget splits based on their income if available.

SCOPE:
- Answer ANY finance, money, or investment related question.
- For non-financial questions, politely redirect: "I specialize in financial advice. Can I help you with your spending, investments, or budgeting instead?"
"""


# -------------------------------
# RULE-BASED FALLBACK RESPONSE
# -------------------------------
def _get_rule_based_reply(intent, data):
    """
    Expanded rule-based fallback responses when DeepSeek is unavailable.
    Covers all detected intents with helpful, data-driven answers.
    """
    forecast = data.get("forecast", {})
    category = data.get("category_breakdown", {})
    total_spent = data.get("total_spent", 0)
    remaining = forecast.get("remaining_balance", 0)

    if intent == "runway":
        runway = forecast.get("runway_days", 0)
        return f"At your current spending rate, your money will last approximately **{runway} days**. Consider reducing your highest expense categories to extend this."

    elif intent == "overspending":
        if category:
            top = max(category, key=category.get)
            amount = category[top]
            return f"You're spending the most on **{top}** (Rs {amount}), which is your biggest expense area. Try setting a budget cap for this category."
        return "I couldn't find enough data to detect overspending yet. Upload your transactions to get started!"

    elif intent == "savings":
        if category:
            top = max(category, key=category.get)
            amount = category[top]
            potential = round(amount * 0.2)
            return f"To improve savings, start by reducing **{top}** (currently Rs {amount}). A 20% cut could save you Rs {potential}/month. That's the highest-impact change."
        return "I need more spending data before suggesting savings improvements. Upload your transactions first!"

    elif intent == "spending":
        if category:
            breakdown = ", ".join(f"{cat}: Rs {amt}" for cat, amt in sorted(category.items(), key=lambda x: x[1], reverse=True))
            return f"You've spent a total of **Rs {total_spent}** so far. Breakdown: {breakdown}."
        return f"You have spent a total of Rs {total_spent} so far across all categories."

    elif intent == "invest":
        if remaining > 0:
            emergency_fund = round(total_spent * 0.5) if total_spent > 0 else 5000
            return (
                f"With Rs {remaining} remaining balance, here's a starting plan:\n"
                f"• **Emergency Fund**: Keep Rs {emergency_fund} in a savings account (3-6 months of expenses)\n"
                f"• **SIP in Index Funds**: Start with Rs {round(remaining * 0.3)} in Nifty 50 index fund\n"
                f"• **Gold/Silver**: Allocate 5-10% as a hedge\n"
                f"• **PPF/FD**: For guaranteed returns\n"
                f"_Note: This is general guidance. Please consult a financial advisor for personalized advice._"
            )
        return "Build up some savings first by reducing expenses, then we can discuss investment strategies! Check your spending breakdown to find areas to cut."

    elif intent == "budget":
        if total_spent > 0:
            return (
                f"Based on your spending of Rs {total_spent}, try the **50/30/20 rule**:\n"
                f"• **50% Needs**: Bills, rent, groceries\n"
                f"• **30% Wants**: Shopping, entertainment, dining out\n"
                f"• **20% Savings/Investment**: Emergency fund, SIPs, FDs"
            )
        return "Upload your transactions first, and I'll create a personalized budget plan for you!"

    elif intent == "income":
        return "I can see your spending data. To give better income-based advice, try asking about budget allocation or where to invest your surplus."

    elif intent == "tax":
        return (
            "For tax savings under Section 80C (up to Rs 1.5 lakh), consider:\n"
            "• **ELSS Mutual Funds**: Best returns with 3-year lock-in\n"
            "• **PPF**: Safe, 15-year tenure, tax-free returns\n"
            "• **NPS**: Additional Rs 50,000 deduction under 80CCD(1B)\n"
            "_Consult a CA for personalized tax planning._"
        )

    elif intent == "safety":
        monthly_expense = round(total_spent / 6) if total_spent > 0 else 0
        target = monthly_expense * 6
        return (
            f"An emergency fund should cover 3-6 months of expenses. "
            f"Based on your data, aim for **Rs {target}** in a liquid savings account. "
            f"Also consider term life insurance and health insurance if you haven't already."
        )

    # General — friendly, helpful response
    return (
        "I'm your AI financial advisor! I can help you with:\n"
        "• **Spending analysis** — where is your money going?\n"
        "• **Investment advice** — where to invest for better returns\n"
        "• **Budgeting** — how to split your income smartly\n"
        "• **Savings** — how to save more each month\n"
        "• **Tax planning** — maximize your deductions\n"
        "Try asking something like _\"Where should I invest?\"_ or _\"How can I reduce spending?\"_"
    )


# -------------------------------
# CA CHAT (SECURED + AI-POWERED)
# -------------------------------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ca_chat(request):
    """
    AI-powered conversational assistant with multi-turn history.
    Uses DeepSeek V4 Pro for intelligent responses with full financial context.
    Falls back to rule-based responses if the AI service is unavailable.
    """
    try:
        message = request.data.get("message", "").strip()

        if not message:
            return Response({"reply": "Please ask a valid question."})

        user = request.user
        user_id = user.id

        # Handle special commands
        if message.lower() in ["clear", "reset", "new chat"]:
            conversation_manager.clear(user_id)
            return Response({"reply": "Conversation history cleared. How can I help you?"})

        # 1. Gather financial data
        data = get_dashboard_data(user)

        # 2. Build system prompt with real financial + market context
        system_prompt = _build_system_prompt(data)

        # 3. Initialize conversation if first message
        if not conversation_manager.has_history(user_id):
            conversation_manager.add_message(user_id, "system", system_prompt)

        # 4. Add user message to history
        conversation_manager.add_message(user_id, "user", message)

        # 5. Try AI-powered response via DeepSeek
        history = conversation_manager.get_history(user_id)
        ai_reply = call_ai_chat(history, max_tokens=800)

        if ai_reply:
            reply = ai_reply
            # Save assistant response to history for multi-turn
            conversation_manager.add_message(user_id, "assistant", reply)
        else:
            # Fallback to rule-based response
            logger.warning("DeepSeek unavailable for user %s, using rule-based fallback", user_id)
            intent = detect_intent(message)
            reply = _get_rule_based_reply(intent, data)

        # SAFETY (NEVER EMPTY)
        if not reply:
            reply = "Something went wrong while generating a response."

        logger.debug("CA reply for user %s: %s", user_id, reply[:100])

        return Response({
            "reply": reply
        })

    except Exception as e:
        logger.error("ERROR IN CA_CHAT: %s", str(e), exc_info=True)
        return Response({
            "reply": "Something went wrong on the server."
        })


# -------------------------------
# CLEAR CHAT HISTORY
# -------------------------------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clear_chat(request):
    """Clear conversation history for the current user."""
    conversation_manager.clear(request.user.id)
    return Response({"message": "Chat history cleared."})