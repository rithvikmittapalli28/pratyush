from django.db import models
from django.contrib.auth.models import User


# -------------------------------
# TRANSACTION MODEL
# -------------------------------
class Transaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.FloatField()
    merchant = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)
    date = models.DateField()

    def __str__(self):
        return f"{self.merchant} - {self.amount}"


# -------------------------------
# BUDGET MODEL
# -------------------------------
class Budget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.CharField(max_length=100)
    limit = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "category"],
                name="unique_user_category_budget",
            )
        ]

    def __str__(self):
        return f"{self.user.username} | {self.category} | {self.limit}"


# -------------------------------
# ALERT MODEL
# -------------------------------
class Alert(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.CharField(max_length=100)
    threshold = models.FloatField()

    def __str__(self):
        return f"{self.user.username} | {self.category} | {self.threshold}"


# -------------------------------
# AI INSIGHT LOG (SELF-AUDITING SYSTEM)
# -------------------------------
class AIInsightLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # Core AI Output
    insight = models.TextField()
    reason = models.TextField()

    # Confidence score (0 to 1)
    confidence = models.FloatField()

    # Source of decision (insight / warning / forecast / chat)
    source = models.CharField(max_length=50, default="insight")

    # Optional: store raw AI output (for debugging / audit)
    raw_output = models.TextField(blank=True, null=True)

    # Optional: input snapshot (what data AI used)
    input_data = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.source.upper()} | {self.insight[:40]} ({self.confidence})"