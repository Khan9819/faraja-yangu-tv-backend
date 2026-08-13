"""Tests za analytics collector (website/events) — user_agent override kwa mobile app."""
import pytest
from django.urls import reverse

from apps.analytics.models import WebsiteEvent


@pytest.mark.django_db
class TestWebsiteEventsCollector:
    def test_accepts_user_agent_override(self):
        """Flutter inatuma user_agent yake mwenyewe — inapaswa kuhifadhiwa
        (vinginevyo UA ya dart:io ingeonekana kama desktop kwenye devices)."""
        client = pytest.importorskip("rest_framework.test").APIClient()
        url = reverse("analytics:website-events")
        resp = client.post(url, {
            "event_type": "watch_seconds",
            "session_id": "sess-mobile-1",
            "video_uid": "vid-1",
            "video_title": "Clip",
            "value": 15,
            "user_agent": "FarajaTV App/1.1.1 (Android; mobile)",
        }, format="json")
        assert resp.status_code == 200

        ev = WebsiteEvent.objects.get(session_id="sess-mobile-1")
        assert ev.user_agent == "FarajaTV App/1.1.1 (Android; mobile)"
        assert ev.value == 15
        assert ev.event_type == "watch_seconds"

    def test_falls_back_to_request_user_agent(self):
        client = pytest.importorskip("rest_framework.test").APIClient()
        url = reverse("analytics:website-events")
        resp = client.post(
            url,
            {
                "event_type": "video_play",
                "session_id": "sess-browser-1",
                "video_uid": "vid-2",
            },
            format="json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
        )
        assert resp.status_code == 200
        ev = WebsiteEvent.objects.get(session_id="sess-browser-1")
        assert "iPhone" in ev.user_agent

    def test_batch_and_invalid_events(self):
        client = pytest.importorskip("rest_framework.test").APIClient()
        url = reverse("analytics:website-events")
        resp = client.post(url, [
            {"event_type": "video_play", "session_id": "s1", "video_uid": "a"},
            {"event_type": "watch_seconds", "session_id": "s1", "value": 30},
            {"event_type": "not_a_real_type", "session_id": "s1"},  # skipped
            {"session_id": "s1"},  # skipped (no event_type)
            "garbage",  # skipped
        ], format="json")
        assert resp.status_code == 200
        assert resp.json()["data"]["created"] == 2
        assert WebsiteEvent.objects.filter(session_id="s1").count() == 2
