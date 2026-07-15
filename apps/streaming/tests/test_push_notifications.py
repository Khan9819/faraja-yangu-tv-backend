import pytest
from unittest.mock import patch, MagicMock, call
from apps.streaming.tasks.tasks import send_push_notification, UserGroupTypes, NotificationTypes
from apps.authentication.models import User, Role, Devices
from apps.analytics.models import Notification
from apps.streaming.models import Video, Category


@pytest.mark.django_db
class TestSendPushNotification:
    """Test suite for the send_push_notification Celery task."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.role_user = Role.objects.create(name=Role.ROLES.USER)
        self.role_admin = Role.objects.create(name=Role.ROLES.ADMIN)
        
        self.client_user1 = User.objects.create_user(
            username="client1",
            email="client1@test.com",
            password="pass1234"
        )
        self.client_user1.roles.add(self.role_user)
        
        self.client_user2 = User.objects.create_user(
            username="client2",
            email="client2@test.com",
            password="pass1234"
        )
        self.client_user2.roles.add(self.role_user)
        
        self.admin_user = User.objects.create_user(
            username="admin1",
            email="admin@test.com",
            password="pass1234"
        )
        self.admin_user.roles.add(self.role_admin)
        
        self.device1 = Devices.objects.create(
            device_os="Android",
            device_id="device1",
            device_type="mobile",
            app_version="1.0.0",
            fcm_token="fcm_token_client1",
            is_active=True
        )
        self.client_user1.devices.add(self.device1)
        
        self.device2 = Devices.objects.create(
            device_os="iOS",
            device_id="device2",
            device_type="mobile",
            app_version="1.0.0",
            fcm_token="fcm_token_client2",
            is_active=True
        )
        self.client_user2.devices.add(self.device2)
        
        self.admin_device = Devices.objects.create(
            device_os="Android",
            device_id="admin_device",
            device_type="mobile",
            app_version="1.0.0",
            fcm_token="fcm_token_admin",
            is_active=True
        )
        self.admin_user.devices.add(self.admin_device)
        
        self.category = Category.objects.create(
            name="Entertainment",
            description="Entertainment videos",
            slug="entertainment"
        )
        
        self.video = Video.objects.create(
            title="Test Video",
            description="Test description",
            category=self.category,
            uploaded_by=self.admin_user
        )
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_send_notification_to_clients_only(self, mock_send):
        """Test that notifications are sent only to users with CLIENT role."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="New Video",
            message="Check out this new video",
            metadata={"video_id": str(self.video.uid), "type": "video_upload"}
        )
        
        assert mock_send.call_count == 2
        
        mock_send.assert_any_call(
            "fcm_token_client1",
            "New Video",
            "Check out this new video",
            data={"video_id": str(self.video.uid), "type": "video_upload"}
        )
        mock_send.assert_any_call(
            "fcm_token_client2",
            "New Video",
            "Check out this new video",
            data={"video_id": str(self.video.uid), "type": "video_upload"}
        )
        
        assert Notification.objects.filter(user=self.client_user1).count() == 1
        assert Notification.objects.filter(user=self.client_user2).count() == 1
        assert Notification.objects.filter(user=self.admin_user).count() == 0
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_send_notification_to_admins_only(self, mock_send):
        """Test that notifications are sent only to users with ADMIN role."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.ADMINS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="Admin Alert",
            message="New video uploaded",
            metadata=None
        )
        
        assert mock_send.call_count == 1
        mock_send.assert_called_once_with(
            "fcm_token_admin",
            "Admin Alert",
            "New video uploaded",
            data=None
        )
        
        assert Notification.objects.filter(user=self.admin_user).count() == 1
        assert Notification.objects.filter(user=self.client_user1).count() == 0
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_send_notification_to_all_users(self, mock_send):
        """Test that notifications are sent to all users regardless of role."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.ALL,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="System Announcement",
            message="Important update",
            metadata=None
        )
        
        assert mock_send.call_count == 3
        assert Notification.objects.count() == 3
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_creates_in_app_notification_with_video_metadata(self, mock_send):
        """Test that in-app notification is created with correct video metadata."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title=f"{self.video.category.name} | {self.video.title}",
            message=f"new {self.video.category.name} Video | {self.video.title}",
            metadata={"video_id": str(self.video.uid), "type": "video_upload"}
        )
        
        notification = Notification.objects.get(user=self.client_user1)
        assert notification.title == f"{self.video.category.name} | {self.video.title}"
        assert notification.message == f"new {self.video.category.name} Video | {self.video.title}"
        assert notification.type == Notification.NOTIFICATION_TYPES.VIDEO
        assert notification.target_video_slug == str(self.video.uid)
        assert notification.target_url == f'/Player/{self.video.uid}'
        assert notification.is_read is False
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_creates_in_app_notification_without_video_metadata(self, mock_send):
        """Test that in-app notification is created without video fields when metadata is missing."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.COMMENT_REPLY,
            title="Comment Reply",
            message="Someone replied to your comment",
            metadata=None
        )
        
        notification = Notification.objects.get(user=self.client_user1)
        assert notification.title == "Comment Reply"
        assert notification.type == Notification.NOTIFICATION_TYPES.PROMO
        assert notification.target_video_slug is None
        assert notification.target_url is None
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_username_placeholder_replacement(self, mock_send):
        """Test that --username-- placeholder is replaced with actual username."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="Hello",
            message="Hello --username--, check out this video!",
            metadata=None
        )
        
        notification1 = Notification.objects.get(user=self.client_user1)
        notification2 = Notification.objects.get(user=self.client_user2)
        
        assert notification1.message == "Hello client1, check out this video!"
        assert notification2.message == "Hello client2, check out this video!"
        
        calls = mock_send.call_args_list
        assert calls[0][0][2] == "Hello client1, check out this video!"
        assert calls[1][0][2] == "Hello client2, check out this video!"
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_default_title_for_new_video(self, mock_send):
        """Test that default title is used when title is empty for NEW_VIDEO."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="",
            message="Check it out",
            metadata=None
        )
        
        notification = Notification.objects.get(user=self.client_user1)
        assert notification.title == "New Video Uploaded"
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_default_title_for_comment_reply(self, mock_send):
        """Test that default title is used when title is empty for COMMENT_REPLY."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.COMMENT_REPLY,
            title="",
            message="Someone replied",
            metadata=None
        )
        
        notification = Notification.objects.get(user=self.client_user1)
        assert notification.title == "You have a new comment reply"
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_skips_inactive_devices(self, mock_send):
        """Test that notifications are not sent to inactive devices."""
        mock_send.return_value = "message_id_123"
        
        self.device1.is_active = False
        self.device1.save()
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="Test",
            message="Test message",
            metadata=None
        )
        
        assert mock_send.call_count == 1
        mock_send.assert_called_once_with(
            "fcm_token_client2",
            "Test",
            "Test message",
            data=None
        )
        
        assert Notification.objects.count() == 2
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_skips_devices_without_fcm_token(self, mock_send):
        """Test that devices without FCM tokens are skipped."""
        mock_send.return_value = "message_id_123"
        
        self.device1.fcm_token = None
        self.device1.save()
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="Test",
            message="Test message",
            metadata=None
        )
        
        assert mock_send.call_count == 1
        mock_send.assert_called_once_with(
            "fcm_token_client2",
            "Test",
            "Test message",
            data=None
        )
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_handles_multiple_devices_per_user(self, mock_send):
        """Test that notifications are sent to all active devices of a user."""
        mock_send.return_value = "message_id_123"
        
        device3 = Devices.objects.create(
            device_os="iOS",
            device_id="device3",
            device_type="tablet",
            app_version="1.0.0",
            fcm_token="fcm_token_client1_device2",
            is_active=True
        )
        self.client_user1.devices.add(device3)
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="Test",
            message="Test message",
            metadata=None
        )
        
        assert mock_send.call_count == 3
        
        assert Notification.objects.filter(user=self.client_user1).count() == 1
        assert Notification.objects.filter(user=self.client_user2).count() == 1
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_handles_fcm_send_failure(self, mock_send):
        """Test that task continues when FCM send fails for some devices."""
        mock_send.side_effect = [None, "message_id_123"]
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="Test",
            message="Test message",
            metadata=None
        )
        
        assert mock_send.call_count == 2
        assert Notification.objects.count() == 2
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_metadata_is_passed_to_fcm(self, mock_send):
        """Test that metadata dictionary is correctly passed to FCM."""
        mock_send.return_value = "message_id_123"
        
        metadata = {
            "video_id": str(self.video.uid),
            "type": "video_upload",
            "category": "entertainment"
        }
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title="Test",
            message="Test message",
            metadata=metadata
        )
        
        calls = mock_send.call_args_list
        for call_item in calls:
            assert call_item[1]['data'] == metadata
    
    @patch('apps.streaming.tasks.tasks._send_notification')
    def test_real_world_scenario_video_upload_complete(self, mock_send):
        """Test the exact scenario from convert_video_to_hls task."""
        mock_send.return_value = "message_id_123"
        
        send_push_notification(
            target=UserGroupTypes.CLIENTS,
            notification_type=NotificationTypes.NEW_VIDEO,
            title=f"{self.video.category.name} | {self.video.title}",
            message=f"new {self.video.category.name} Video | {self.video.title}",
            metadata={"video_id": str(self.video.uid), "type": "video_upload"}
        )
        
        assert mock_send.call_count == 2
        
        notification = Notification.objects.get(user=self.client_user1)
        assert notification.title == "Entertainment | Test Video"
        assert notification.message == "new Entertainment Video | Test Video"
        assert notification.type == Notification.NOTIFICATION_TYPES.VIDEO
        assert notification.target_video_slug == str(self.video.uid)
        assert notification.target_url == f'/Player/{self.video.uid}'
        assert notification.is_read is False
        
        mock_send.assert_any_call(
            "fcm_token_client1",
            "Entertainment | Test Video",
            "new Entertainment Video | Test Video",
            data={"video_id": str(self.video.uid), "type": "video_upload"}
        )
