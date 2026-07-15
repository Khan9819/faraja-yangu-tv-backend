import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from apps.authentication.models import User, Role, Profile
from apps.authentication.services.credit import UserCreditService
from apps.streaming.models import Video, Category


@pytest.mark.django_db
class TestMarkVideoDownloaded:
    """Test suite for the idempotent download endpoint."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.client = APIClient()

        self.role_user = Role.objects.create(name=Role.ROLES.USER)

        self.profile = Profile.objects.create(credit_accumulation=100)
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="pass1234",
            auth_provider="email",
            profile=self.profile,
        )
        self.user.roles.add(self.role_user)

        self.category = Category.objects.create(
            name="Entertainment",
            description="Entertainment videos",
            slug="entertainment",
        )
        self.video = Video.objects.create(
            title="Test Video",
            description="Test description",
            category=self.category,
            uploaded_by=self.user,
        )

        self.client.force_authenticate(user=self.user)
        self.url = f"/streaming/stream/{self.video.uid}/download/"

    def test_first_download_deducts_credits(self):
        """First download should deduct credits and return updated balance."""
        response = self.client.post(self.url)
        assert response.status_code == 200

        data = response.data["data"]
        assert data["credits_used"] == UserCreditService.DEDUCT_FROM_DOWNLOAD
        assert data["already_downloaded"] is False
        assert data["updated_credits"] == 100 - UserCreditService.DEDUCT_FROM_DOWNLOAD

    def test_second_download_is_idempotent(self):
        """Second download of the same video should not deduct credits again."""
        self.client.post(self.url)
        response = self.client.post(self.url)
        assert response.status_code == 200

        data = response.data["data"]
        assert data["credits_used"] == 0
        assert data["already_downloaded"] is True
        assert data["updated_credits"] == 100 - UserCreditService.DEDUCT_FROM_DOWNLOAD

    def test_insufficient_credits_returns_400(self):
        """Download with insufficient credits should return 400."""
        self.profile.credit_accumulation = 5
        self.profile.save()

        response = self.client.post(self.url)
        assert response.status_code == 400
        assert "Insufficient credits" in str(response.data["message"])

    def test_video_not_found_returns_400(self):
        """Download for a non-existent video should return 400."""
        response = self.client.post("/streaming/stream/00000000-0000-0000-0000-000000000000/download/")
        assert response.status_code == 400

    def test_credits_not_deducted_before_video_validation(self):
        """Credits should remain unchanged when video does not exist."""
        self.client.post("/streaming/stream/00000000-0000-0000-0000-000000000000/download/")
        self.profile.refresh_from_db()
        assert self.profile.credit_accumulation == 100

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    def test_idempotency_key_dedup(self):
        """Same Idempotency-Key should return cached response without re-processing."""
        headers = {"HTTP_IDEMPOTENCY_KEY": "unique-key-123"}
        response1 = self.client.post(self.url, **headers)
        response2 = self.client.post(self.url, **headers)

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response2.data["data"]["credits_used"] == response1.data["data"]["credits_used"]

        self.profile.refresh_from_db()
        assert self.profile.credit_accumulation == 100 - UserCreditService.DEDUCT_FROM_DOWNLOAD

    def test_unauthenticated_returns_401(self):
        """Unauthenticated request should return 401."""
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url)
        assert response.status_code in (401, 403)

    def test_download_adds_to_m2m(self):
        """Download should add the video to the user's downloaded_videos M2M."""
        self.client.post(self.url)
        assert self.profile.downloaded_videos.filter(pk=self.video.pk).exists()

    def test_response_contains_updated_credits(self):
        """Response should always contain updated_credits field."""
        response = self.client.post(self.url)
        assert "updated_credits" in response.data["data"]

    def test_concurrent_idempotency_via_m2m(self):
        """Even without Idempotency-Key, M2M check prevents double deduction."""
        self.client.post(self.url)
        self.client.post(self.url)
        self.client.post(self.url)

        self.profile.refresh_from_db()
        assert self.profile.credit_accumulation == 100 - UserCreditService.DEDUCT_FROM_DOWNLOAD


@pytest.mark.django_db
class TestGetDownloadStatus:
    """Test suite for the download-status endpoint."""

    def setup_method(self):
        self.client = APIClient()
        self.profile = Profile.objects.create(credit_accumulation=100)
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="pass1234",
            auth_provider="email",
            profile=self.profile,
        )
        self.category = Category.objects.create(
            name="Test", description="Test", slug="test"
        )
        self.video = Video.objects.create(
            title="Test Video",
            description="Test",
            category=self.category,
            uploaded_by=self.user,
        )
        self.client.force_authenticate(user=self.user)

    def test_not_downloaded(self):
        """Should return is_downloaded=False for a video not yet downloaded."""
        url = f"/streaming/stream/{self.video.uid}/download-status/"
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.data["data"]["is_downloaded"] is False

    def test_downloaded(self):
        """Should return is_downloaded=True after downloading."""
        self.profile.downloaded_videos.add(self.video)
        url = f"/streaming/stream/{self.video.uid}/download-status/"
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.data["data"]["is_downloaded"] is True

    def test_video_not_found(self):
        """Should return error for non-existent video."""
        url = "/streaming/stream/00000000-0000-0000-0000-000000000000/download-status/"
        response = self.client.get(url)
        assert response.status_code == 400


@pytest.mark.django_db
class TestGetUserDownloads:
    """Test suite for the user-downloads bulk endpoint."""

    def setup_method(self):
        self.client = APIClient()
        self.profile = Profile.objects.create(credit_accumulation=100)
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="pass1234",
            auth_provider="email",
            profile=self.profile,
        )
        self.category = Category.objects.create(
            name="Test", description="Test", slug="test"
        )
        self.video1 = Video.objects.create(
            title="Video 1", description="V1", category=self.category, uploaded_by=self.user
        )
        self.video2 = Video.objects.create(
            title="Video 2", description="V2", category=self.category, uploaded_by=self.user
        )
        self.client.force_authenticate(user=self.user)

    def test_empty_downloads(self):
        """Should return empty list when no videos downloaded."""
        response = self.client.get("/streaming/user-downloads/")
        assert response.status_code == 200
        assert response.data["data"]["downloaded_video_uids"] == []

    def test_returns_all_downloaded_uids(self):
        """Should return UIDs of all downloaded videos."""
        self.profile.downloaded_videos.add(self.video1, self.video2)
        response = self.client.get("/streaming/user-downloads/")
        assert response.status_code == 200
        uids = response.data["data"]["downloaded_video_uids"]
        assert str(self.video1.uid) in uids
        assert str(self.video2.uid) in uids
