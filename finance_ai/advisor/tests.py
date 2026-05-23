from unittest.mock import patch

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from advisor.conversation import conversation_manager
from advisor.views import AI_UNAVAILABLE_REPLY
from transactions.models import Budget, Transaction


class CAChatTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="rithvik", password="password")
        self.client.force_authenticate(user=self.user)
        conversation_manager.clear(self.user.id)

        today = timezone.localdate()
        Transaction.objects.create(
            user=self.user,
            amount=50000,
            merchant="Salary",
            category="Income",
            date=today,
        )
        Transaction.objects.create(
            user=self.user,
            amount=-8000,
            merchant="Swiggy",
            category="Food",
            date=today,
        )
        Transaction.objects.create(
            user=self.user,
            amount=-4500,
            merchant="PVR",
            category="Entertainment",
            date=today,
        )
        Budget.objects.create(user=self.user, category="Food", limit=7000)

    def tearDown(self):
        conversation_manager.clear(self.user.id)

    @patch("advisor.views.get_market_context", return_value="MARKET CONTEXT TEST")
    @patch("advisor.views.call_ai_chat", return_value="Use a staged, diversified plan.")
    def test_custom_question_is_sent_to_llm_with_financial_context(self, mock_chat, _):
        response = self.client.post(
            "/advisor/chat/",
            {"message": "Where should I invest Rs 10,000 for best returns?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["reply"], "Use a staged, diversified plan.")
        self.assertEqual(response.data["response"], response.data["reply"])

        mock_chat.assert_called_once()
        messages = mock_chat.call_args.args[0]
        system_prompt = messages[0]["content"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Do not use keyword routing or canned answers", system_prompt)
        self.assertIn("Total spending for this month: Rs 12,500", system_prompt)
        self.assertIn("Food: Rs 8,000", system_prompt)
        self.assertIn("Entertainment: Rs 4,500", system_prompt)
        self.assertIn("Rs 7,000 budget", system_prompt)
        self.assertIn("MARKET CONTEXT TEST", system_prompt)
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(
            messages[-1]["content"],
            "Where should I invest Rs 10,000 for best returns?",
        )

    @patch("advisor.views.get_market_context", return_value="")
    @patch("advisor.views.call_ai_chat", return_value=None)
    def test_ai_failure_returns_meaningful_unavailable_reply(self, mock_chat, _):
        response = self.client.post(
            "/advisor/chat/",
            {"message": "Is Bitcoin good to buy now?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["reply"], AI_UNAVAILABLE_REPLY)
        self.assertEqual(response.data["response"], AI_UNAVAILABLE_REPLY)
        self.assertEqual(response.data["error"], "ai_unavailable")
        mock_chat.assert_called_once()
