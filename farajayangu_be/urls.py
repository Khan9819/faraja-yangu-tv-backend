from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponseRedirect, JsonResponse

PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=co.tz.farajayangutv.app'

def video_redirect(request, uid):
    return HttpResponseRedirect(PLAY_STORE_URL)

def assetlinks(request):
    data = [{
        'relation': [
            'delegate_permission/common.handle_all_urls',
            'delegate_permission/common.get_login_creds'
        ],
        'target': {
            'namespace': 'android_app',
            'package_name': 'co.tz.farajayangutv.app',
            'sha256_cert_fingerprints': [
                '1C:47:BA:CE:EE:3F:4E:D5:F9:3E:15:65:2B:83:91:00:25:04:68:AE:53:96:BE:E7:DD:48:FF:02:AD:6E:B0:A2'
            ]
        }
    }]
    return JsonResponse(data, safe=False)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('authentication/', include('apps.authentication.urls')),
    path('streaming/', include('apps.streaming.urls')),
    path('advertising/', include('apps.advertising.urls')),
    path('analytics/', include('apps.analytics.urls')),
    path('profile/', include('apps.profile.urls')),
    path('management/', include('apps.management.urls')),
    path('.well-known/assetlinks.json', assetlinks),
    path('video/<str:uid>/', video_redirect),
]
