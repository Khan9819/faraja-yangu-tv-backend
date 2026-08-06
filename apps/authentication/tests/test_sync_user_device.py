import pytest
from apps.authentication.models import User, Role, Devices
from apps.authentication.tasks.main import sync_user_device


@pytest.mark.django_db
class TestSyncUserDevice:
    """Verify sync_user_device keeps ONE canonical device row per device."""

    def setup_method(self):
        self.role_user = Role.objects.create(name=Role.ROLES.USER)
        self.user = User.objects.create_user(
            username="client1",
            email="client1@test.com",
            password="pass1234"
        )
        self.user.roles.add(self.role_user)

    def _sync(self, device_id="dev-1", fcm_token="token-1"):
        return sync_user_device(
            user_id=self.user.id,
            device_id=device_id,
            device_type="mobile",
            app_version="1.0.0",
            fcm_token=fcm_token,
        )

    def test_creates_device_and_links_user(self):
        self._sync()
        assert Devices.objects.count() == 1
        device = Devices.objects.get(device_id="dev-1")
        assert device.fcm_token == "token-1"
        assert device.is_active is True
        assert self.user.devices.filter(id=device.id).exists()

    def test_token_rotation_updates_in_place_not_duplicates(self):
        self._sync(fcm_token="token-1")
        self._sync(fcm_token="token-2")

        assert Devices.objects.count() == 1
        device = Devices.objects.get()
        assert device.fcm_token == "token-2"
        assert device.is_active is True

    def test_stale_row_updated_in_place_on_token_rotation(self):
        # Simulate the pre-fix state: an old row exists for this device with a
        # different token. Syncing with the rotated token must reuse the same
        # row (update in place), never creating a second duplicate.
        Devices.objects.create(
            device_id="dev-1", fcm_token="old-token",
            device_type="mobile", device_os="Android", app_version="1.0.0", is_active=True,
        )

        self._sync(device_id="dev-1", fcm_token="new-token")

        rows = Devices.objects.filter(device_id="dev-1")
        assert rows.count() == 1
        assert rows.first().fcm_token == "new-token"
        assert rows.first().is_active is True

    def test_same_token_reused_deactivates_old_row(self):
        # Another device row already holds the token; syncing the same token
        # should reuse that canonical row and deactivate the duplicate.
        self._sync(device_id="dev-1", fcm_token="token-1")
        self._sync(device_id="dev-2", fcm_token="token-1")

        active_rows = Devices.objects.filter(is_active=True)
        assert active_rows.count() == 1
        assert active_rows.first().device_id == "dev-2"  # most recent row wins
        assert self.user.devices.filter(is_active=True).count() == 1
