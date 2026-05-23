"""
Conversation Manager — Persistence via SQLite/PostgreSQL Database
========================================================================
Keyed by user ID. Thread-safe database operations.
"""

from advisor.models import ChatMessage

MAX_HISTORY = 20


class ConversationManager:
    """
    Database-backed conversation history manager.
    """

    def add_message(self, user_id, role, content):
        """
        Append a message to the user's conversation history in the database.
        System messages are NOT stored in the database (they are generated dynamically on every request).
        """
        if role not in {"user", "assistant"}:
            return

        ChatMessage.objects.create(
            user_id=user_id,
            role=role,
            content=content
        )

        # Trim old messages if over limit
        count = ChatMessage.objects.filter(user_id=user_id).count()
        if count > MAX_HISTORY:
            excess = count - MAX_HISTORY
            # Find the primary keys of the oldest items
            old_ids = ChatMessage.objects.filter(user_id=user_id).order_by("created_at")[:excess].values_list("id", flat=True)
            ChatMessage.objects.filter(id__in=list(old_ids)).delete()

    def get_history(self, user_id):
        """
        Get the full conversation history for a user from the database.
        """
        messages = ChatMessage.objects.filter(user_id=user_id).order_by("created_at")
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

    def clear(self, user_id):
        """Clear all conversation history for a user in the database."""
        ChatMessage.objects.filter(user_id=user_id).delete()

    def has_history(self, user_id):
        """Check if user has any conversation history in the database."""
        return ChatMessage.objects.filter(user_id=user_id).exists()


# ================================
# SINGLETON INSTANCE
# ================================
conversation_manager = ConversationManager()
