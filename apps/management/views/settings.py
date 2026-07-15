from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from core.response_wrapper import success_response, error_response

from apps.management.models import PlatformSettings
from apps.management.serializers import PlatformSettingsSerializer


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def settings_view(request):
    """GET: return platform settings. PATCH: update platform settings."""
    settings_obj = PlatformSettings.load()

    if request.method == 'PATCH':
        serializer = PlatformSettingsSerializer(settings_obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(serializer.errors, code=400)
        serializer.save()
        return success_response(serializer.data, message='Settings updated.')

    serializer = PlatformSettingsSerializer(settings_obj)
    return success_response(serializer.data)
