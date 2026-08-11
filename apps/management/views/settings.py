from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from core.response_wrapper import success_response, error_response

from apps.management.models import PlatformSettings
from apps.management.serializers import PlatformSettingsSerializer


@api_view(['GET'])
@permission_classes([AllowAny])
def app_version(request):
    """Public in-app update check (hutumiwa na App kwenye splash/home).

    App inalinganisha latest_version na version yake; ikiwa backend iko juu,
    inaonyesha "update card" kwa mtumiaji. Inasomwa kutoka PlatformSettings
    (CMS Settings inaweza kubadilisha values bila kuredeploy).
    """
    settings_obj = PlatformSettings.load()
    return success_response({
        'latest_version': settings_obj.app_version,
        'minimum_version': settings_obj.minimum_version,
        'release_notes': settings_obj.release_notes or [],
        'update_url': settings_obj.update_url,
        'is_force_update': settings_obj.is_force_update,
    }, message='OK')


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
