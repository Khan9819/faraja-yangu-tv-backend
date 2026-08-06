from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from core.response_wrapper import success_response

PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=co.tz.farajayangutv.app'

@api_view(['GET'])
def public_website_posts(request):
    from apps.management.models import WebsitePost
    from apps.management.serializers import WebsitePostSerializer
    posts = WebsitePost.objects.all().order_by('-date', '-created_at')
    serializer = WebsitePostSerializer(posts, many=True)
    return success_response(serializer.data)


@api_view(['GET'])
def public_categories_with_cover(request):
    from apps.streaming.models import Category
    from apps.streaming.serializers import CategorySerializer
    # Show categories that have either a cover or a thumbnail so the website
    # coverflow always renders a visible image. Also exclude empty-string
    # values (older rows can store '' instead of NULL for ImageFields).
    categories = Category.objects.filter(
        (Q(cover__isnull=False) & ~Q(cover='')) |
        (Q(thumbnail__isnull=False) & ~Q(thumbnail=''))
    ).order_by('-created_at')
    serializer = CategorySerializer(categories, many=True)
    return success_response(serializer.data)


def video_og_page(request, uid):
    from apps.streaming.models import Video
    try:
        video = get_object_or_404(Video, uid=uid, is_published=True)
    except ValidationError:
        raise Http404('Invalid video UID')
    og_image = ''
    if video.thumbnail:
        try:
            og_image = video.thumbnail.url
        except Exception:
            og_image = ''
    description = (video.description[:280] + '…') if len(video.description) > 280 else video.description
    og_url = request.build_absolute_uri()
    return render(request, 'streaming/video_og.html', {
        'video': video,
        'og_image': og_image,
        'og_url': og_url,
        'description': description,
        'play_store_url': PLAY_STORE_URL,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def public_video_info(request, uid):
    """Public video metadata for the website's shared-video overlay.

    Returns lightweight, anonymous-friendly video info (no auth required) so
    the website landing page can render a video share card with cover, title,
    description and views without exposing streaming URLs.

    The cover falls back through the full chain (thumbnail -> portrait_cover ->
    tv_poster -> tv_landscape) so the website always shows a cover image.
    """
    from apps.streaming.models import Video

    try:
        video = Video.objects.get(uid=uid, is_published=True)
    except (Video.DoesNotExist, ValidationError, ValueError):
        return success_response(None, message='Video not found')

    cover = None
    # Guard each field so the endpoint stays safe on older DB schemas.
    for field in ('thumbnail', 'portrait_cover', 'tv_poster', 'tv_landscape'):
        if field not in {f.name for f in video._meta.fields}:
            continue
        value = getattr(video, field, None)
        if value:
            try:
                cover = value.url
            except Exception:
                cover = None
            if cover:
                break

    category_name = ''
    if video.category:
        category_name = video.category.name
        if video.category.parent:
            category_name = f'{video.category.parent.name} • {video.category.name}'

    return success_response({
        'uid': str(video.uid),
        'id': video.id,
        'title': video.title,
        'description': video.description,
        'cover': cover,
        'thumbnail': video.thumbnail.url if video.thumbnail else None,
        'views_count': video.views_count,
        'duration': str(video.duration) if video.duration else None,
        'created_at': video.created_at,
        'category_name': category_name,
        'play_store_url': PLAY_STORE_URL,
        'app_scheme': f'farajatv://video/{video.uid}',
    }, message='Video info loaded')

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
    path('video/<str:uid>/info/', public_video_info, name='public-video-info'),
    path('website-posts/', public_website_posts, name='public-website-posts'),
    path('categories-with-cover/', public_categories_with_cover, name='public-categories-with-cover'),

    # API variants get their own unique instance namespace so they don't
    # collide with the non-API includes above (fixes urls.W005).
    path('api/authentication/', include(('apps.authentication.urls', 'authentication'), namespace='api-authentication')),
    path('api/streaming/', include(('apps.streaming.urls', 'streaming'), namespace='api-streaming')),
    path('api/advertising/', include(('apps.advertising.urls', 'advertising'), namespace='api-advertising')),
    path('api/analytics/', include(('apps.analytics.urls', 'analytics'), namespace='api-analytics')),
    path('api/profile/', include(('apps.profile.urls', 'profile'), namespace='api-profile')),
    path('api/management/', include(('apps.management.urls', 'management'), namespace='api-management')),
    path('api/website-posts/', public_website_posts, name='api-public-website-posts'),
    path('api/categories-with-cover/', public_categories_with_cover, name='api-public-categories-with-cover'),
    path('api/video/<str:uid>/info/', public_video_info, name='api-public-video-info'),
]
