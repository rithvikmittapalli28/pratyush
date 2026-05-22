"""
AI Service Module — DeepSeek V4 Pro via AI Credits API
======================================================
Reusable, provider-agnostic AI service using OpenAI-compatible
chat completions endpoint. Designed for easy model swapping.

Usage:
    from ai_engine.ai_service import call_ai, call_ai_chat

    # Single-turn (replaces call_ollama)
    result = call_ai("Classify this transaction: Swiggy")

    # Multi-turn chat
    messages = [
        {"role": "system", "content": "You are a finance assistant."},
        {"role": "user", "content": "Where am I overspending?"},
    ]
    result = call_ai_chat(messages)
"""

import os
import time
import logging
import traceback
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from the Django project root (finance_ai/finance_ai/.env)
# This ensures the key loads regardless of the CWD used by gunicorn/Render.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

# ================================
# CONFIGURATION (from environment)
# ================================
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.aicredits.in/v1")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek/deepseek-chat")
AI_API_KEY = os.environ.get("AI_API_KEY", "")

# Retry & timeout settings
# NOTE: Render free tier has a 30-second HTTP request timeout.
# Market fetch uses a background cache (instant), so the full 30s is available.
MAX_RETRIES = 2               # one real retry for transient 429/500/timeout
RETRY_BACKOFF = 1.0           # seconds between retries
REQUEST_TIMEOUT = 25          # seconds — generous for cold LLM providers
MAX_TOKENS = 600              # concise but detailed financial advice

# ================================
# LOGGING
# ================================
logger = logging.getLogger("ai_service")
logger.setLevel(logging.DEBUG)

# Console handler (only add if none exist to avoid duplicates)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(_handler)

# ================================
# STARTUP VALIDATION
# ================================
if not AI_API_KEY:
    logger.critical(
        "AI_API_KEY is NOT set. The AI chatbot will return empty responses. "
        "Set AI_API_KEY in the environment or .env file at: %s",
        _ENV_PATH,
    )
else:
    logger.info(
        "AI service configured: model=%s  base_url=%s  key=sk-...%s",
        AI_MODEL, AI_BASE_URL, AI_API_KEY[-6:],
    )


# ================================
# INTERNAL: HTTP CALL WITH RETRIES
# ================================
def _call_completions(messages, temperature=0.3, max_tokens=MAX_TOKENS):
    """
    Send a chat completions request to the AI Credits API.
    Returns the assistant's reply as a plain string, or None on failure.

    Uses raw `requests` (no openai SDK dependency) for maximum compatibility.
    The API follows the OpenAI chat completions format.
    """

    if not AI_API_KEY:
        logger.error(
            "AI_API_KEY is not set — cannot call AI. "
            "Set it in Render env vars or .env at: %s", _ENV_PATH
        )
        return None

    url = f"{AI_BASE_URL.rstrip('/')}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AI_API_KEY}",
    }

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Log the user prompt (last user message, truncated) for debugging
            user_msgs = [m for m in messages if m.get("role") == "user"]
            last_prompt = user_msgs[-1]["content"][:120] if user_msgs else "(none)"
            logger.info(
                "AI request attempt %d/%d  model=%s  messages=%d  prompt=%r",
                attempt, MAX_RETRIES, AI_MODEL, len(messages), last_prompt,
            )

            res = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            # ---- Handle HTTP errors ----
            if res.status_code == 429:
                # Rate limited — wait and retry
                wait = RETRY_BACKOFF * attempt
                logger.warning("Rate limited (429). Retrying in %.1fs…", wait)
                time.sleep(wait)
                continue

            if res.status_code >= 500:
                # Server error — retry
                wait = RETRY_BACKOFF * attempt
                logger.warning(
                    "Server error %d. Retrying in %.1fs…", res.status_code, wait
                )
                time.sleep(wait)
                continue

            if res.status_code != 200:
                logger.error(
                    "AI API error %d: %s", res.status_code, res.text[:500]
                )
                return None

            # ---- Parse response ----
            data = res.json()
            choices = data.get("choices", [])

            if not choices:
                logger.error("AI API returned empty choices. Full response: %s", data)
                return None

            content = choices[0].get("message", {}).get("content", "").strip()
            logger.info("AI response received (%d chars): %r", len(content), content[:150])
            return content

        except requests.exceptions.Timeout:
            last_error = "timeout"
            wait = RETRY_BACKOFF * attempt
            logger.warning("Request timed out. Retrying in %.1fs…", wait)
            time.sleep(wait)

        except requests.exceptions.ConnectionError as exc:
            last_error = str(exc)
            wait = RETRY_BACKOFF * attempt
            logger.warning("Connection error: %s. Retrying in %.1fs…", exc, wait)
            time.sleep(wait)

        except Exception as exc:
            logger.error(
                "Unexpected AI error: %s\n%s", exc, traceback.format_exc()
            )
            return None

    logger.error("All %d AI attempts failed. Last error: %s", MAX_RETRIES, last_error)
    return None


# ================================
# PUBLIC API: SINGLE-TURN CALL
# ================================
def call_ai(prompt, system_prompt=None, temperature=0.3, max_tokens=MAX_TOKENS):
    """
    Simple single-turn AI call. Drop-in replacement for call_ollama().

    Args:
        prompt:        The user prompt string.
        system_prompt: Optional system instruction.
        temperature:   Sampling temperature (0.0 – 1.0).
        max_tokens:    Max tokens in the response.

    Returns:
        str or None — the AI's reply text, or None if the call failed.
    """
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": prompt})

    return _call_completions(messages, temperature=temperature, max_tokens=max_tokens)


# ================================
# PUBLIC API: MULTI-TURN CHAT
# ================================
def call_ai_chat(messages, temperature=0.5, max_tokens=MAX_TOKENS):
    """
    Multi-turn chat completions call (for CA / conversational assistant).

    Args:
        messages:    List of dicts with 'role' and 'content' keys.
                     Example: [{"role": "user", "content": "Hi"}]
        temperature: Sampling temperature.
        max_tokens:  Max tokens in the response.

    Returns:
        str or None — the assistant's reply text, or None on failure.
    """
    return _call_completions(messages, temperature=temperature, max_tokens=max_tokens)
