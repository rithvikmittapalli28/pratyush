"""
Conversation Manager — Session history for CA (Conversational Assistant)
========================================================================
Thread-safe, in-memory conversation history keyed by user ID.
Designed for multi-turn chat with DeepSeek / any LLM.

Usage:
    from advisor.conversation import conversation_manager

    conversation_manager.add_message(user_id=1, role="user", content="Hi")
    history = conversation_manager.get_history(user_id=1)
    conversation_manager.clear(user_id=1)
"""

import threading
from collections import defaultdict

# Maximum messages per user (system + user + assistant turns)
MAX_HISTORY = 20


class ConversationManager:
    """
    In-memory conversation history manager.
    Thread-safe via a simple lock.
    """

    def __init__(self, max_history=MAX_HISTORY):
        self._history = defaultdict(list)
        self._lock = threading.Lock()
        self._max_history = max_history

    def add_message(self, user_id, role, content):
        """
        Append a message to the user's conversation history.

        Args:
            user_id:  int — Django User.id
            role:     str — "system", "user", or "assistant"
            content:  str — message text
        """
        with self._lock:
            history = self._history[user_id]
            history.append({"role": role, "content": content})

            # Trim oldest non-system messages if over limit
            if len(history) > self._max_history:
                # Keep system messages, trim the rest
                system_msgs = [m for m in history if m["role"] == "system"]
                other_msgs = [m for m in history if m["role"] != "system"]

                # Keep only the latest messages
                keep_count = self._max_history - len(system_msgs)
                trimmed = system_msgs + other_msgs[-keep_count:]
                self._history[user_id] = trimmed

    def get_history(self, user_id):
        """
        Get the full conversation history for a user.

        Returns:
            list of dicts — [{"role": "...", "content": "..."}, ...]
        """
        with self._lock:
            return list(self._history.get(user_id, []))

    def clear(self, user_id):
        """Clear all conversation history for a user."""
        with self._lock:
            self._history.pop(user_id, None)

    def has_history(self, user_id):
        """Check if user has any conversation history."""
        with self._lock:
            return bool(self._history.get(user_id))


# ================================
# SINGLETON INSTANCE
# ================================
conversation_manager = ConversationManager()
