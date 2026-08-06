import pytest
from rest_framework.test import APIClient
from apps.authentication.models import User, Profile
from apps.streaming.models import Video, Category


@pytest.mark.django_db
class TestPublicVideoInfo:
    """Public video metadata used by the website shared-video overlay."""

    def setup_method(self):
        self.client = APIClient()  # intentionally unauthenticated

        self.profile = Profile.objects.create(credit_accumulation=100)
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="pass1234",
            auth_provider="email",
            profile=self.profile,
        )
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
            is_published=True,
        )

    def test_returns_video_info_without_auth(self):
        """Website must be able to fetch video info anonymously."""
        response = self.client.get(f"/video/{self.video.uid}/info/")
        assert response.status_code == 200
        data = response.data["data"]
        assert data["uid"] == str(self.video.uid)
        assert data["title"] == "Test Video"
        assert data["description"] == "Test description"
        assert data["views_count"] == 0
        assert "farajatv://video/" in data["app_scheme"]
        assert "play.google.com" in data["play_store_url"]

    def test_api_variant_works(self):
        """The /api/video/<uid>/info/ variant must resolve too."""
        response = self.client.get(f"/api/video/{self.video.uid}/info/")
        assert response.status_code == 200

    def test_missing_video_returns_null_data(self):
        """Unknown UID should return success with null data (no 500)."""
        response = self.client.get("/video/00000000-0000-0000-0000-000000000000/info/")
        assert response.status_code == 200
        assert response.data["data"] is None

    def test_unpublished_video_is_hidden(self):
        """Draft videos must not leak through the public endpoint."""
        self.video.is_published = False
        self.video.save()
        response = self.client.get(f"/video/{self.video.uid}/info/")
        assert response.status_code == 200
        assert response.data["data"] is None


@pytest.mark.django_db
class TestPublicCategoriesWithCover:
    """Public category list for the website coverflow."""

    def setup_method(self):
        self.client = APIClient()  # intentionally unauthenticated

    def test_returns_only_categories_with_images(self):
        """Only categories having cover OR thumbnail should be returned."""
        with_img = Category.objects.create(name="With Cover", slug="with-cover")
        no_img = Category.objects.create(name="No Image", slug="no-image")

        # Set a thumbnail on one category (model allows blank/null images)
        from django.core.files.uploadedfile import SimpleUploadedFile
        with_img.thumbnail = SimpleUploadedFile("thumb.jpg", b"fake-image-data")
        with_img.save()

        response = self.client.get("/api/categories-with-cover/")
        assert response.status_code == 200
        data = response.data["data"]
        names = [c["name"] for c in data]
        assert "With Cover" in names
        assert "No Image" not in names

    def test_root_variant_works(self):
        """The non-API root variant must also resolve."""
        response = self.client.get("/categories-with-cover/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestPublicWebsitePosts:
    """Website posts feed used by the landing page updates carousel."""

    def setup_method(self):
        self.client = APIClient()

    def test_posts_endpoint_public(self):
        response = self.client.get("/api/website-posts/")
        assert response.status_code == 200
        assert isinstance(response.data["data"], list)
