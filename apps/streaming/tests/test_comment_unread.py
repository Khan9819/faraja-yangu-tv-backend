"""Tests za unread-comments badge (is_read) + notify_user_of_reply original comment."""
import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse

from apps.authentication.models import User, Role, Devices
from apps.streaming.models import Video, Category, Comment


def _make_user(username, role_name):
    role, _ = Role.objects.get_or_create(name=role_name)
    user = User.objects.create_user(username=username, email=f"{username}@test.com", password="pass1234")
    user.roles.add(role)
    return user


@pytest.mark.django_db
class TestCommentUnread:
    def setup_method(self):
        self.user = _make_user("commenter", Role.ROLES.USER)
        self.admin = _make_user("adminx", Role.ROLES.ADMIN)
        self.category = Category.objects.create(name="Cat", description="d", slug="cat")
        self.video = Video.objects.create(
            title="Vid",
            category=self.category,
            uid="11111111-1111-1111-1111-111111111111",
            uploaded_by=self.admin,
        )
        # Commenter ana comment, admin anajibu
        self.comment = Comment.objects.create(video=self.video, user=self.user, comment="Asante kwa video")

    def _force_auth(self, user):
        client = pytest.importorskip("rest_framework.test").APIClient()
        client.force_authenticate(user=user)
        return client

    def test_unread_count_zero_and_marks_read(self):
        client = self._force_auth(self.user)
        url = reverse("streaming:comments-unread-count")
        resp = client.get(url)
        assert resp.status_code == 200
        assert resp.json()["data"]["unread_count"] == 0

        # Admin anajibu kupitia endpoint ya CMS
        reply_url = reverse("streaming:cms-comment-reply", args=[self.comment.id])
        client2 = self._force_auth(self.admin)
        resp = client2.post(reply_url, {"text": "Karibu sana!"}, format="json")
        assert resp.status_code == 200

        # Badge inaonyesha 1
        resp = client.get(url)
        assert resp.json()["data"]["unread_count"] == 1

        # Mark read kwenye video hiyo -> badge inafutika
        read_url = reverse("streaming:stream-comments-read", args=[self.video.uid])
        resp = client.post(read_url)
        assert resp.status_code == 200
        assert resp.json()["data"]["marked"] == 1

        resp = client.get(url)
        assert resp.json()["data"]["unread_count"] == 0

    def test_own_replies_do_not_count(self):
        client = self._force_auth(self.user)
        reply_url = reverse("streaming:cms-comment-reply", args=[self.comment.id])
        client.post(reply_url, {"text": "Nijibie mwenyewe"}, format="json")  # user anajibu comment yake
        url = reverse("streaming:comments-unread-count")
        resp = client.get(url)
        assert resp.json()["data"]["unread_count"] == 0

    @patch("apps.streaming.tasks.tasks._send_notification", return_value="ok")
    def test_notify_reply_includes_original_comment(self, mock_send):
        from apps.streaming.tasks.tasks import notify_user_of_reply

        dev = Devices.objects.create(
            device_os="Android", device_id="dev1", device_type="mobile",
            app_version="1.0.0", fcm_token="tok1", is_active=True,
        )
        self.user.devices.add(dev)
        notify_user_of_reply(
            commenter_user_id=self.user.id,
            replier_name="Faraja Yangu TV",
            comment_text="Karibu sana!",
            video_uid=str(self.video.uid),
            video_title="Vid",
            original_comment_text="Asante kwa video",
        )
        assert mock_send.called
        args, kwargs = mock_send.call_args
        body = args[2] if len(args) > 2 else kwargs.get("body", "")
        assert "Asante kwa video" in body
        assert kwargs["data"]["original_comment"] == "Asante kwa video"
        assert kwargs["data"]["reply_text"] == "Karibu sana!"
