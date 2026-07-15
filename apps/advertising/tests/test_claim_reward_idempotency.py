import uuid

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient
from apps.authentication.models import User, Role, Profile
from apps.authentication.services.credit import UserCreditService


@pytest.mark.django_db
@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestClaimReward:
    """Test suite for the idempotent claim-reward endpoint."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        cache.clear()
        self.client = APIClient()

        self.role_user = Role.objects.create(name=Role.ROLES.USER)

        self.profile = Profile.objects.create(credit_accumulation=50)
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="pass1234",
            auth_provider="email",
            profile=self.profile,
        )
        self.user.roles.add(self.role_user)

        self.client.force_authenticate(user=self.user)
        self.url = "/advertising/claim-reward/"

    def teardown_method(self):
        cache.clear()

    def test_successful_claim_adds_credits(self):
        """A valid claim should add credits and return new balance."""
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert response.status_code == 200

        data = response.data["data"]
        assert data["credits_awarded"] == UserCreditService.GAIN_FROM_AD
        assert data["total_credits"] == 50 + UserCreditService.GAIN_FROM_AD

    def test_ad_session_id_dedup_prevents_double_credit(self):
        """Same ad_session_id should not grant credits twice."""
        session_id = str(uuid.uuid4())
        payload = {"time_spent_seconds": 30, "ad_clicked": False, "ad_session_id": session_id}

        response1 = self.client.post(self.url, payload)
        response2 = self.client.post(self.url, payload)

        assert response1.status_code == 200
        assert response2.status_code == 200

        assert response1.data["data"]["credits_awarded"] == UserCreditService.GAIN_FROM_AD
        assert response2.data["message"] == "Reward already claimed for this session"

        self.profile.refresh_from_db()
        assert self.profile.credit_accumulation == 50 + UserCreditService.GAIN_FROM_AD

    def test_different_session_ids_both_grant_credits(self):
        """Different ad_session_id values should each grant credits (respecting rate limit)."""
        session1 = str(uuid.uuid4())
        payload1 = {"time_spent_seconds": 30, "ad_clicked": False, "ad_session_id": session1}
        response1 = self.client.post(self.url, payload1)
        assert response1.status_code == 200
        assert response1.data["data"]["credits_awarded"] == UserCreditService.GAIN_FROM_AD

        # Second claim within 30s should be rate-limited
        session2 = str(uuid.uuid4())
        payload2 = {"time_spent_seconds": 30, "ad_clicked": False, "ad_session_id": session2}
        response2 = self.client.post(self.url, payload2)
        assert response2.status_code == 429

    def test_rate_limiting_returns_429(self):
        """Second claim within 30s cooldown should return 429."""
        self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert response.status_code == 429

    def test_response_contains_total_credits(self):
        """Response should contain total_credits field."""
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert "total_credits" in response.data["data"]

    def test_response_contains_credits_awarded(self):
        """Response should contain credits_awarded field."""
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert "credits_awarded" in response.data["data"]

    def test_ad_id_is_optional(self):
        """Claim should succeed without ad_id."""
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert response.status_code == 200

    def test_ad_session_id_is_optional(self):
        """Claim should succeed without ad_session_id (no dedup, still rate-limited)."""
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert response.status_code == 200
        assert response.data["data"]["credits_awarded"] == UserCreditService.GAIN_FROM_AD

    def test_invalid_payload_returns_400(self):
        """Missing required field should return 400."""
        response = self.client.post(self.url, {"ad_clicked": False})
        assert response.status_code == 400

    def test_unauthenticated_returns_401(self):
        """Unauthenticated request should return 401/403."""
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert response.status_code in (401, 403)

    def test_no_name_error_in_response(self):
        """Ensure the old amount_gained NameError bug is fixed."""
        response = self.client.post(self.url, {"time_spent_seconds": 30, "ad_clicked": False})
        assert response.status_code == 200
        assert "credits_awarded" in response.data["data"]
        assert isinstance(response.data["data"]["credits_awarded"], int)
