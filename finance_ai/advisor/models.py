from django.db import models
from django.contrib.auth.models import User

# -------------------------------
# CHAT MESSAGE PERSISTENCE MODEL
# -------------------------------
class ChatMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20)  # 'user' or 'assistant'
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.username} | {self.role} | {self.content[:30]}"
