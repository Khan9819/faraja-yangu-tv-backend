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


@pytest.mark.django_db
class TestPublicVideosByCategory:
    """All R2-ready videos grouped by category → subcategory for the website.

    The website fetches this endpoint to render video sections by category,
    and new CMS uploads must appear automatically (cache invalidation).
    """

    def setup_method(self):
        from django.core.cache import cache
        cache.clear()  # avoid stale locmem cache leaking between tests
        self.client = APIClient()  # intentionally unauthenticated
        self.profile = Profile.objects.create(credit_accumulation=100)
        self.user = User.objects.create_user(
            username="catuser",
            email="cat@test.com",
            password="pass1234",
            auth_provider="email",
            profile=self.profile,
        )
        self.parent = Category.objects.create(name="Qaswida", slug="qaswida")
        self.child = Category.objects.create(
            name="Qaswida Zetu", slug="qaswida-zetu", parent=self.parent
        )

    def _make_video(self, title, category, **kwargs):
        defaults = dict(
            description="Test description",
            is_published=True,
            processing_status="completed",
            hls_master_playlist="videos/hls/x/master.m3u8",
            hls_path="videos/hls/x",
        )
        defaults.update(kwargs)
        return Video.objects.create(
            title=title, category=category, uploaded_by=self.user, **defaults
        )

    def test_endpoint_public_without_auth(self):
        """The website must be able to fetch videos anonymously."""
        self._make_video("A", self.child)
        response = self.client.get("/api/videos-by-category/?refresh=1")
        assert response.status_code == 200
        assert isinstance(response.data["data"], list)

    def test_groups_videos_under_subcategory(self):
        """Videos appear under parent → subcategory with a watch_url."""
        v = self._make_video("Qaswida Ya Kwanza", self.child)
        response = self.client.get("/api/videos-by-category/?refresh=1")
        data = response.data["data"]

        parent_block = next((c for c in data if c["slug"] == "qaswida"), None)
        assert parent_block is not None
        sub = next(
            (s for s in parent_block["subcategories"] if s["slug"] == "qaswida-zetu"),
            None,
        )
        assert sub is not None
        assert [x["uid"] for x in sub["videos"]] == [str(v.uid)]
        assert sub["videos"][0]["watch_url"].endswith(f"/watch/{v.uid}/")

    def test_excludes_unpublished_not_ready_and_ad_media(self):
        """Only streamable (R2-ready), published, non-ad videos are returned."""
        self._make_video("Ready", self.child)
        self._make_video("Draft", self.child, is_published=False)
        self._make_video("Processing", self.child, processing_status="processing")
        self._make_video("Ad Media", self.child, is_ad_media=True)

        response = self.client.get("/api/videos-by-category/?refresh=1")
        sub = next(
            s for c in response.data["data"] for s in c["subcategories"]
            if s["slug"] == "qaswida-zetu"
        )
        assert [v["title"] for v in sub["videos"]] == ["Ready"]

    def test_new_upload_invalidates_cache(self):
        """Uploading new content must appear on the next website fetch."""
        first = self.client.get("/api/videos-by-category/")
        assert first.status_code == 200

        # CMS uploads new content → post_save signal invalidates the cache
        self._make_video("Fresh Upload", self.child)

        second = self.client.get("/api/videos-by-category/")
        sub = next(
            s for c in second.data["data"] for s in c["subcategories"]
            if s["slug"] == "qaswida-zetu"
        )
        assert [v["title"] for v in sub["videos"]] == ["Fresh Upload"]

    def test_hls_completion_invalidates_cache(self):
        """New content appears once HLS conversion completes (CMS flow)."""
        # Cache inatengenezwa bila video yoyote ya ready.
        first = self.client.get("/api/videos-by-category/")
        assert first.status_code == 200

        # CMS inaunda video (pending) — bado haijatayarika, isionekane.
        pending = Video.objects.create(
            title="Converting Video",
            description="d",
            category=self.child,
            uploaded_by=self.user,
            is_published=True,
            processing_status="pending",
        )
        still_pending = self.client.get("/api/videos-by-category/")
        assert still_pending.status_code == 200

        # Conversion inakamilika: processing_status -> completed (processing
        # fields pekee — hii ndiyo branch maalum kwenye signals).
        pending.processing_status = "completed"
        pending.hls_master_playlist = "videos/hls/x/master.m3u8"
        pending.hls_path = "videos/hls/x"
        pending.save(update_fields=["processing_status", "hls_master_playlist", "hls_path"])

        # Website inafetch bila refresh — video mpya inaonekana.
        after = self.client.get("/api/videos-by-category/")
        sub = next(
            s for c in after.data["data"] for s in c["subcategories"]
            if s["slug"] == "qaswida-zetu"
        )
        assert [v["title"] for v in sub["videos"]] == ["Converting Video"]

    def test_limit_param_caps_videos(self):
        """?limit= caps videos per subcategory (scalability escape hatch)."""
        self._make_video("A1", self.child)
        self._make_video("A2", self.child)
        response = self.client.get("/api/videos-by-category/?refresh=1&limit=1")
        sub = next(
            s for c in response.data["data"] for s in c["subcategories"]
            if s["slug"] == "qaswida-zetu"
        )
        assert len(sub["videos"]) == 1

    def test_root_variant_works(self):
        """The non-API root variant must also resolve."""
        self._make_video("A", self.child)
        response = self.client.get("/videos-by-category/?refresh=1")
        assert response.status_code == 200
