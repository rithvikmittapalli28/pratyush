from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from transactions.services import get_dashboard_data
from ai_engine.ai_service import call_ai_chat
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
# INTENT DETECTION (STRONG)
# -------------------------------
def detect_intent(msg: str):
    msg = msg.lower()

    if any(w in msg for w in ["runway", "how long", "last", "survive", "days left"]):
        return "runway"

    if any(w in msg for w in ["overspend", "overspending", "too much", "where am i overspending"]):
        return "overspending"

    if any(w in msg for w in ["cut", "reduce", "save", "improve savings", "what should i cut"]):
        return "savings"

    if any(w in msg for w in ["spend", "spending", "where money", "breakdown"]):
        return "spending"

    return "unknown"


# -------------------------------
# BUILD FINANCIAL CONTEXT FOR AI
# -------------------------------
def _build_system_prompt(data):
    """
    Build a system prompt that gives the AI full financial context
    so it can provide personalized, data-driven responses.
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

    return f"""You are a smart, friendly personal finance assistant called "Finance AI".
You help users understand their spending, find savings, and make better financial decisions.

CURRENT USER FINANCIAL DATA:
- Total spent: Rs {total_spent}
- Remaining balance: Rs {remaining}
- Runway (days until funds run out): {runway} days
- Spending by category:
{cat_lines}

RULES:
- Always use the real data above — never make up numbers.
- Keep responses concise (2-4 sentences max).
- Use INR (Rs) for all currency amounts.
- Be actionable: suggest specific categories to cut.
- Be encouraging but honest about spending habits.
- If asked about something outside finance, politely redirect to finance topics.
"""


# -------------------------------
# RULE-BASED FALLBACK RESPONSE
# -------------------------------
def _get_rule_based_reply(intent, data):
    """
    Fast, deterministic fallback responses when DeepSeek is unavailable.
    This is the original logic preserved as a safety net.
    """
    forecast = data.get("forecast", {})
    category = data.get("category_breakdown", {})
    total_spent = data.get("total_spent", 0)

    if intent == "runway":
        runway = forecast.get("runway_days", 0)
        return f"At your current spending rate, your money will last approximately {runway} days."

    elif intent == "overspending":
        if category:
            top = max(category, key=category.get)
            amount = category[top]
            return f"You are spending the most in {top} (Rs {amount}). That's your biggest expense area."
        return "I couldn't find enough data to detect overspending yet."

    elif intent == "savings":
        if category:
            top = max(category, key=category.get)
            amount = category[top]
            return f"To improve savings, start by reducing {top} (currently Rs {amount}). It will have the biggest impact."
        return "I need more spending data before suggesting savings improvements."

    elif intent == "spending":
        return f"You have spent a total of Rs {total_spent} so far across all categories."

    return "Ask me things like: runway, overspending, or how to save money — I'll give precise answers."


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

        # 2. Build system prompt with real financial context
        system_prompt = _build_system_prompt(data)

        # 3. Initialize conversation if first message
        if not conversation_manager.has_history(user_id):
            conversation_manager.add_message(user_id, "system", system_prompt)

        # 4. Add user message to history
        conversation_manager.add_message(user_id, "user", message)

        # 5. Try AI-powered response via DeepSeek
        history = conversation_manager.get_history(user_id)
        ai_reply = call_ai_chat(history)

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