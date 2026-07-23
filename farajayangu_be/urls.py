from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.conf import settings

PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=co.tz.farajayangutv.app'

def video_og_page(request, uid):
    from apps.streaming.models import Video
    video = get_object_or_404(Video, uid=uid, is_published=True)
    og_image = ''
    if video.thumbnail:
        og_image = video.thumbnail.url  # full R2 URL
    description = (video.description[:280] + '…') if len(video.description) > 280 else video.description
    og_url = request.build_absolute_uri()
    return render(request, 'streaming/video_og.html', {
        'video': video,
        'og_image': og_image,
        'og_url': og_url,
        'description': description,
        'play_store_url': PLAY_STORE_URL,
    })

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
    path('video/<str:uid>/', video_og_page, name='video-og'),

    path('api/authentication/', include('apps.authentication.urls')),
    path('api/streaming/', include('apps.streaming.urls')),
    path('api/advertising/', include('apps.advertising.urls')),
    path('api/analytics/', include('apps.analytics.urls')),
    path('api/profile/', include('apps.profile.urls')),
    path('api/management/', include('apps.management.urls')),
]
