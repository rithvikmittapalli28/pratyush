import logging
import traceback

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from advisor.conversation import conversation_manager
from ai_engine.ai_service import call_ai_chat
from ai_engine.market_service import get_market_context
from transactions.models import Budget, Transaction
from transactions.services import get_dashboard_data

logger = logging.getLogger("advisor")

AI_UNAVAILABLE_REPLY = "AI advisor is temporarily unavailable. Please try again."


# -------------------------------
# SIGNUP
# -------------------------------
@api_view(["POST"])
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
@api_view(["POST"])
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
        "refresh": str(refresh),
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
# BUILD FINANCIAL CONTEXT FOR AI
# -------------------------------
def _format_money(value):
    try:
        return f"Rs {float(value):,.0f}"
    except (TypeError, ValueError):
        return "Rs 0"


def _get_monthly_snapshot(user):
    today = timezone.localdate()
    month_txs = Transaction.objects.filter(
        user=user,
        date__year=today.year,
        date__month=today.month,
    )
    month_expenses = month_txs.filter(amount__lt=0)

    category_rows = month_expenses.values("category").annotate(total=Sum("amount"))
    monthly_categories = {
        row["category"] or "Other": abs(row["total"] or 0)
        for row in category_rows
    }

    monthly_income = month_txs.filter(amount__gt=0).aggregate(total=Sum("amount"))["total"] or 0
    monthly_spending = sum(monthly_categories.values())

    return {
        "month": today.strftime("%B %Y"),
        "income": monthly_income,
        "spending": monthly_spending,
        "categories": monthly_categories,
    }


def _get_budget_snapshot(user):
    budgets = Budget.objects.filter(user=user).order_by("category")
    return {budget.category: budget.limit for budget in budgets}


def _get_recent_transactions(user, limit=12):
    transactions = Transaction.objects.filter(user=user).order_by("-date", "-id")[:limit]
    return [
        {
            "date": tx.date.isoformat(),
            "merchant": tx.merchant,
            "category": tx.category or "Other",
            "amount": tx.amount,
        }
        for tx in transactions
    ]


def _format_mapping(mapping, empty_message):
    if not mapping:
        return f"  - {empty_message}"

    return "\n".join(
        f"  - {key}: {_format_money(value)}"
        for key, value in sorted(mapping.items(), key=lambda item: item[1], reverse=True)
    )


def _format_recent_transactions(transactions):
    if not transactions:
        return "  - No uploaded or manually added transactions yet."

    lines = []
    for tx in transactions:
        direction = "income" if tx["amount"] > 0 else "expense"
        lines.append(
            f"  - {tx['date']} | {tx['merchant']} | {tx['category']} | "
            f"{_format_money(abs(tx['amount']))} {direction}"
        )
    return "\n".join(lines)


def _build_system_prompt(user, data):
    """
    Build the system prompt on every request so new uploads, budgets, and
    spending changes are immediately available to the LLM.
    """
    forecast = data.get("forecast", {})
    lifetime_categories = data.get("category_breakdown", {})
    total_spent = data.get("total_spent", 0)
    runway = forecast.get("runway_days", 0)
    remaining = forecast.get("remaining_balance", 0)
    monthly = _get_monthly_snapshot(user)
    budgets = _get_budget_snapshot(user)
    recent_transactions = _get_recent_transactions(user)
    market_context = get_market_context()

    return f"""You are Finance AI, a conversational personal finance assistant for Indian users.
Respond like a smart, practical finance advisor: warm, concise, specific, and willing to reason through tradeoffs.

You can answer any money-related question, including budgeting, spending analysis, saving strategies, debt, taxes,
insurance, financial planning, mutual funds, stocks, crypto, gold, fixed deposits, PPF, NPS, and market trends.
Do not use keyword routing or canned answers. Treat every user message as a fresh conversational request.

CURRENT USER FINANCIAL DATA:
- Lifetime uploaded/manual spending: {_format_money(total_spent)}
- Remaining balance from known transactions: {_format_money(remaining)}
- Runway (days until funds run out): {runway} days
- Current month: {monthly["month"]}
- Current-month income: {_format_money(monthly["income"])}
- Current-month spending: {_format_money(monthly["spending"])}
- Current-month spending by category:
{_format_mapping(monthly["categories"], "No current-month spending data yet.")}
- Overall spending by category:
{_format_mapping(lifetime_categories, "No spending data yet.")}
- User budgets:
{_format_mapping(budgets, "No budgets set yet.")}
- Recent transactions:
{_format_recent_transactions(recent_transactions)}

{market_context}

RESPONSE RULES:
- Use the real financial data above when relevant. If data is missing, say what is missing and answer generally.
- Use INR and "Rs" for currency amounts.
- Keep simple answers concise; use clear bullets or numbered steps for planning questions.
- Explain risk levels for investments and crypto. Never guarantee profits or returns.
- Before aggressive investing, check emergency fund, debt, runway, monthly spending, and diversification.
- If discussing current market timing, be balanced: valuation, risk, time horizon, liquidity, and staged investing.
- For tax questions, give general education and recommend a qualified CA for personal tax decisions.
- For large or regulated investment decisions, suggest consulting a SEBI-registered investment advisor.
- If the question is not about finance, politely redirect to finance topics.
"""


def _response_payload(reply, **extra):
    # "response" is kept as a compatibility alias for older frontends.
    return {"reply": reply, "response": reply, **extra}


# -------------------------------
# CA CHAT (SECURED + AI-POWERED)
# -------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ca_chat(request):
    """
    Fully conversational finance assistant.
    Every normal user message is sent to the configured LLM with fresh
    financial context and conversation history.
    """
    try:
        message = request.data.get("message", "").strip()

        if not message:
            return Response(_response_payload("Please ask a valid question."), status=400)

        user = request.user
        user_id = user.id

        if message.lower() in ["clear", "reset", "new chat"]:
            conversation_manager.clear(user_id)
            reply = "Conversation history cleared. How can I help you?"
            return Response(_response_payload(reply))

        data = get_dashboard_data(user)
        system_prompt = _build_system_prompt(user, data)

        conversation_manager.add_message(user_id, "user", message)
        conversation_history = [
            item
            for item in conversation_manager.get_history(user_id)
            if item.get("role") in {"user", "assistant"}
        ]
        llm_messages = [{"role": "system", "content": system_prompt}] + conversation_history

        logger.info(
            "CA_CHAT user=%s  prompt=%r  history_len=%d",
            user_id, message[:120], len(conversation_history),
        )

        ai_reply = call_ai_chat(llm_messages, max_tokens=700)

        if not ai_reply or not ai_reply.strip():
            logger.warning("AI returned empty for user %s — returning fallback", user_id)
            return Response(
                _response_payload(AI_UNAVAILABLE_REPLY, error="ai_unavailable"),
                status=200,  # 200 so axios doesn't throw; frontend checks 'error' flag
            )

        reply = ai_reply.strip()
        conversation_manager.add_message(user_id, "assistant", reply)

        logger.debug("CA reply for user %s: %s", user_id, reply[:100])
        return Response(_response_payload(reply))

    except Exception as exc:
        logger.error(
            "ERROR IN CA_CHAT for user %s: %s\n%s",
            request.user.id if hasattr(request, 'user') else '?',
            str(exc),
            traceback.format_exc(),
        )
        return Response(
            _response_payload(AI_UNAVAILABLE_REPLY, error="server_error"),
            status=200,  # 200 so frontend can read the message body
        )


# -------------------------------
# CLEAR CHAT HISTORY
# -------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def clear_chat(request):
    """Clear conversation history for the current user."""
    conversation_manager.clear(request.user.id)
    return Response({"message": "Chat history cleared."})
