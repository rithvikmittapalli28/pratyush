import os
import time
import requests
from dotenv import load_dotenv

# Load env variables
load_dotenv()

print("AI_BASE_URL:", os.environ.get("AI_BASE_URL"))
print("AI_MODEL:", os.environ.get("AI_MODEL"))
print("AI_API_KEY:", os.environ.get("AI_API_KEY")[:10] + "..." if os.environ.get("AI_API_KEY") else "None")
print("MARKET_API_KEY:", os.environ.get("MARKET_API_KEY")[:10] + "..." if os.environ.get("MARKET_API_KEY") else "None")
print("MARKET_API_BASE:", os.environ.get("MARKET_API_BASE"))

# Let's import the services directly and test them
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from finance_ai.ai_engine.market_service import get_market_context
from finance_ai.ai_engine.ai_service import call_ai_chat

print("\n--- Testing Market Service ---")
start = time.time()
ctx = get_market_context()
print("Market Context Length:", len(ctx))
print("Market Service Time:", time.time() - start, "seconds")

print("\n--- Testing AI Service ---")
messages = [
    {"role": "system", "content": ctx},
    {"role": "user", "content": "Where should I invest 50000 rupees?"}
]
start = time.time()
reply = call_ai_chat(messages, max_tokens=600)
print("AI Reply:", reply)
print("AI Service Time:", time.time() - start, "seconds")
