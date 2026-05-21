"""
Market Data Service — Live Indian market data via IndianAPI
===========================================================
Fetches real-time stock market data, trending stocks, commodities,
and market news from IndianAPI (stock.indianapi.in).

When MARKET_API_KEY is set, fetches live data for AI responses.
Otherwise, provides general market knowledge as context.

Usage:
    from ai_engine.market_service import get_market_context

    context = get_market_context()
    # Returns a string with current market data for the AI system prompt
"""

import os
import logging
import requests
import threading
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("market_service")

# ================================
# CONFIGURATION
# ================================
MARKET_API_KEY = os.environ.get("MARKET_API_KEY", "")
MARKET_API_BASE = os.environ.get(
    "MARKET_API_BASE", "https://stock.indianapi.in"
)

# Cache duration in seconds (5 minutes)
_CACHE_TTL = 300
_cache = {"data": None, "timestamp": 0}

# Request timeout (keep low — Render has 30s total limit)
_TIMEOUT = 5


# ================================
# INTERNAL: API REQUEST HELPER
# ================================
def _api_get(endpoint, params=None):
    """
    Make a GET request to IndianAPI with the API key header.
    Returns parsed JSON or None on failure.
    """
    if not MARKET_API_KEY:
        return None

    url = f"{MARKET_API_BASE.rstrip('/')}/{endpoint.lstrip('/')}"

    headers = {
        "x-api-key": MARKET_API_KEY,
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=_TIMEOUT)

        if res.status_code == 200:
            return res.json()
        else:
            logger.warning(
                "IndianAPI %s returned status %d: %s",
                endpoint, res.status_code, res.text[:200]
            )
            return None

    except requests.exceptions.Timeout:
        logger.warning("IndianAPI %s timed out", endpoint)
        return None
    except requests.exceptions.ConnectionError as exc:
        logger.warning("IndianAPI connection error: %s", exc)
        return None
    except Exception as exc:
        logger.error("IndianAPI unexpected error: %s", exc, exc_info=True)
        return None


# ================================
# LIVE MARKET DATA FETCHER (BACKGROUND THREAD)
# ================================
def _do_fetch():
    """
    Internal: actually fetch market data from IndianAPI.
    Called only by the background refresh thread.
    """
    if not MARKET_API_KEY:
        return None

    results = {}

    # ---- 1. Trending stocks (top gainers & losers) ----
    trending = _api_get("/trending")
    if trending:
        gainers = trending.get("top_gainers", [])
        if isinstance(gainers, list) and gainers:
            results["top_gainers"] = gainers[:5]

        losers = trending.get("top_losers", [])
        if isinstance(losers, list) and losers:
            results["top_losers"] = losers[:5]

        trending_list = trending.get("trending_stocks", trending.get("trending", []))
        if isinstance(trending_list, list) and trending_list:
            results["trending"] = trending_list[:5]

    # ---- 2. News for market sentiment ----
    news = _api_get("/news")
    if news:
        news_list = news if isinstance(news, list) else news.get("news", [])
        if isinstance(news_list, list) and news_list:
            results["recent_news"] = [
                {
                    "title": item.get("title", ""),
                    "description": item.get("description", item.get("summary", "")),
                }
                for item in news_list[:5]
                if item.get("title")
            ]

    return results if results else None


def _background_refresh():
    """
    Background thread: fetch market data immediately on startup,
    then refresh every _CACHE_TTL seconds.
    This keeps the cache warm so chat requests NEVER block on market I/O.
    """
    import time as _time

    while True:
        try:
            data = _do_fetch()
            if data:
                _cache["data"] = data
                _cache["timestamp"] = datetime.now().timestamp()
                logger.info("Market data cache refreshed (%d keys)", len(data))
            else:
                logger.info("Market data fetch returned nothing (API down or no key)")
        except Exception as exc:
            logger.error("Background market fetch error: %s", exc)

        _time.sleep(_CACHE_TTL)


_refresh_thread = None
_thread_lock = threading.Lock()


def ensure_background_refresh_started():
    """
    Lazily start the background refresh thread if it hasn't started yet.
    Avoids starting threads at module import time which can deadlock WSGI servers.
    """
    global _refresh_thread
    if _refresh_thread is None:
        with _thread_lock:
            if _refresh_thread is None:
                logger.info("Starting background market refresh thread (lazy initialization)")
                _refresh_thread = threading.Thread(target=_background_refresh, daemon=True)
                _refresh_thread.start()


def _fetch_live_market_data():
    """
    Returns cached market data (instant, no network I/O).
    The background thread keeps the cache warm.
    """
    ensure_background_refresh_started()
    return _cache.get("data")


# ================================
# FORMAT MARKET DATA FOR AI PROMPT
# ================================
def _format_market_data(market_data):
    """Format live market data into a readable string for the AI."""
    if not market_data:
        return ""

    lines = ["LIVE INDIAN MARKET DATA (fetched recently from IndianAPI):"]

    # Top Gainers
    gainers = market_data.get("top_gainers", [])
    if gainers:
        lines.append("\nTOP GAINERS TODAY:")
        for stock in gainers[:5]:
            name = stock.get("name", stock.get("stock_name", stock.get("symbol", "Unknown")))
            price = stock.get("price", stock.get("ltp", "N/A"))
            change = stock.get("change_percent", stock.get("percent_change", stock.get("change", "")))
            if change:
                lines.append(f"  - {name}: Rs {price} ({change})")
            else:
                lines.append(f"  - {name}: Rs {price}")

    # Top Losers
    losers = market_data.get("top_losers", [])
    if losers:
        lines.append("\nTOP LOSERS TODAY:")
        for stock in losers[:5]:
            name = stock.get("name", stock.get("stock_name", stock.get("symbol", "Unknown")))
            price = stock.get("price", stock.get("ltp", "N/A"))
            change = stock.get("change_percent", stock.get("percent_change", stock.get("change", "")))
            if change:
                lines.append(f"  - {name}: Rs {price} ({change})")
            else:
                lines.append(f"  - {name}: Rs {price}")

    # Trending stocks
    trending = market_data.get("trending", [])
    if trending:
        lines.append("\nTRENDING STOCKS:")
        for stock in trending[:5]:
            if isinstance(stock, dict):
                name = stock.get("name", stock.get("stock_name", stock.get("symbol", "Unknown")))
                price = stock.get("price", stock.get("ltp", ""))
                if price:
                    lines.append(f"  - {name}: Rs {price}")
                else:
                    lines.append(f"  - {name}")
            elif isinstance(stock, str):
                lines.append(f"  - {stock}")

    # Recent news headlines
    news = market_data.get("recent_news", [])
    if news:
        lines.append("\nRECENT MARKET NEWS:")
        for item in news[:3]:
            title = item.get("title", "")
            if title:
                lines.append(f"  - {title}")

    return "\n".join(lines)


# ================================
# PUBLIC API
# ================================
def get_market_context():
    """
    Returns a string with market context for the AI system prompt.
    If live data is available (API key set), includes real Indian market data.
    Otherwise, provides general market awareness instructions.
    """
    today = datetime.now()
    date_str = today.strftime("%A, %B %d, %Y")
    time_str = today.strftime("%I:%M %p IST")

    base_context = f"""
CURRENT DATE & TIME: {date_str}, {time_str}
"""

    # Try to get live market data
    live_data = _fetch_live_market_data()

    if live_data:
        market_str = _format_market_data(live_data)
        base_context += f"""
{market_str}

INVESTMENT ADVICE RULES (with live data):
- Use the live Indian market data above to give specific, data-backed advice.
- Reference today's top gainers/losers and trending stocks when relevant.
- Use recent news headlines to assess market sentiment.
- Suggest whether it's a good time to buy/hold/wait based on trends.
- Always mention the data is indicative and recommend consulting a SEBI-registered financial advisor for large investments.
"""
    else:
        base_context += """
INVESTMENT ADVICE RULES (general knowledge mode):
- You do NOT have live market prices right now.
- Provide general investment principles and asset allocation advice.
- Suggest diversified investment strategies based on the user's spending patterns and risk appetite.
- Cover asset classes: Gold, Silver, Mutual Funds (SIPs), Fixed Deposits, PPF, NPS, Stocks (Index Funds).
- For Indian investors, mention tax-saving instruments (ELSS, PPF, NPS) when relevant.
- Always recommend consulting a SEBI-registered financial advisor for specific investment decisions.
- When asked "where should I invest", analyze their spending data and suggest:
  * Emergency fund first (3-6 months of expenses)
  * SIP in index funds for long-term wealth building
  * Gold/Silver as a hedge (5-10% of portfolio)
  * FD/PPF for safe, guaranteed returns
"""

    return base_context
