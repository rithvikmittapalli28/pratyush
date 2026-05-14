from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Transaction


class MultiUserIsolationTest(APITestCase):

    def setUp(self):
        # Create 2 users
        self.user1 = User.objects.create_user(username="user1", password="pass123")
        self.user2 = User.objects.create_user(username="user2", password="pass123")

        # Generate tokens
        self.token1 = str(RefreshToken.for_user(self.user1).access_token)
        self.token2 = str(RefreshToken.for_user(self.user2).access_token)

        # Create transaction ONLY for user1
        Transaction.objects.create(
            user=self.user1,
            amount=-100,
            merchant="Amazon",
            category="Shopping",
            date="2026-03-01"
        )

    def test_user1_sees_own_data(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token1}")

        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["total_spent"] > 0)

    def test_user2_cannot_see_user1_data(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token2}")

        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should NOT see user1 data
        self.assertEqual(response.data["total_spent"], 0)

    def test_user2_cannot_access_user1_audit(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token2}")

        response = self.client.get("/audit/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should be empty
        self.assertEqual(len(response.data), 0)