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
from apps.streaming.views import watch_video

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
    backend_url = getattr(settings, 'BACKEND_URL', None) or getattr(settings, 'BASE_URL', '')
    return render(request, 'streaming/video_og.html', {
        'video': video,
        'og_image': og_image,
        'og_url': og_url,
        'description': description,
        'play_store_url': PLAY_STORE_URL,
        'watch_url': f"{backend_url}/watch/{video.uid}/",
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

def _resolve_media_url(field):
    """Return the storage URL of an ImageField/FileField, or None if unset/broken."""
    if not field:
        return None
    try:
        return field.url
    except Exception:
        return None


def _public_video_cover(video):
    """Cover fallback chain: thumbnail → portrait_cover → tv_poster → tv_landscape."""
    for name in ('thumbnail', 'portrait_cover', 'tv_poster', 'tv_landscape'):
        url = _resolve_media_url(getattr(video, name, None))
        if url:
            return url
    return None


def _public_category_cover(category):
    """Category cover fallback chain: cover → thumbnail."""
    for name in ('cover', 'thumbnail'):
        url = _resolve_media_url(getattr(category, name, None))
        if url:
            return url
    return None


def _public_video_payload(video, backend_url):
    """Lightweight, anonymous-friendly video payload for the website."""
    duration_seconds = int(video.duration.total_seconds()) if video.duration else 0
    description = video.description or ''
    if len(description) > 120:
        description = description[:120] + '…'
    return {
        'uid': str(video.uid),
        'title': video.title,
        'description': description,
        'cover': _public_video_cover(video),
        'views_count': video.views_count,
        'duration_seconds': duration_seconds,
        'created_at': video.created_at.isoformat() if video.created_at else None,
        'watch_url': f"{backend_url}/watch/{video.uid}/",
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def public_videos_by_category(request):
    """All R2-ready videos (published + HLS completed) grouped by category.

    Returns a hierarchical structure the website renders directly:
        parent category → subcategories → videos

    Videos that are not streamable yet (processing) or not published are
    excluded, so the website only shows content that actually exists on R2.
    The response is cached briefly (60s); the cache is invalidated by
    signals.py whenever new content is uploaded/completed/deleted, so the
    website picks up fresh uploads without a manual refresh.

    Pass ?refresh=1 to bypass the cache (used by tests / CMS previews).
    """
    from django.core.cache import cache
    from django.db.models import Prefetch
    from apps.streaming.models import Category, Video

    cache_key = 'videos_by_category:website'
    try:
        if request.GET.get('refresh') != '1':
            cached = cache.get(cache_key)
            if cached is not None:
                return success_response(cached)
    except Exception:
        # Redis down? Serve fresh data instead of failing the whole website.
        pass

    # Optional per-subcategory cap (default 0 = return ALL R2-ready videos).
    # Website haina limit kwa sasa ("video zote"); CMS/previews zinaweza
    # kupita ?limit=12 ili kupunguza payload kwenye catalog kubwa.
    try:
        limit = int(request.GET.get('limit', 0))
        limit = max(limit, 0)
    except (TypeError, ValueError):
        limit = 0

    def _base_videos_qs():
        """Fresh queryset per Prefetch (Django's nested prefetch re-filters
        the queryset, so we cannot slice here — slicing happens in Python
        below per subcategory).
        """
        return (
            Video.objects
            .filter(is_published=True, processing_status='completed', is_ad_media=False)
            .order_by('-created_at')
        )

    top_categories = (
        Category.objects
        .filter(parent__isnull=True)
        .order_by('name')
        .prefetch_related(
            Prefetch('videos', queryset=_base_videos_qs()),
            Prefetch('subcategories', queryset=Category.objects.order_by('name')),
            Prefetch('subcategories__videos', queryset=_base_videos_qs()),
        )
    )

    backend_url = getattr(settings, 'BACKEND_URL', None) or getattr(settings, 'BASE_URL', '')
    result = []

    for cat in top_categories:
        block = {
            'id': cat.id,
            'name': cat.name,
            'slug': cat.slug,
            'cover': _public_category_cover(cat),
            'subcategories': [],
        }

        # Subcategory groups (logic ile ile ya category → subcategory).
        for sub in cat.subcategories.all():
            sub_videos = list(sub.videos.all())
            if limit:
                sub_videos = sub_videos[:limit]
            videos = [_public_video_payload(v, backend_url) for v in sub_videos]
            if not videos:
                continue
            block['subcategories'].append({
                'id': sub.id,
                'name': sub.name,
                'slug': sub.slug,
                'cover': _public_category_cover(sub),
                'videos': videos,
            })

        # Videos pinned directly to this parent category (leaf category).
        direct_videos = list(cat.videos.all())
        if limit:
            direct_videos = direct_videos[:limit]
        direct = [_public_video_payload(v, backend_url) for v in direct_videos]
        if direct:
            block['subcategories'].append({
                'id': cat.id,
                'name': cat.name,
                'slug': cat.slug,
                'cover': _public_category_cover(cat),
                'videos': direct,
                'is_parent': True,
            })

        if block['subcategories']:
            result.append(block)

    try:
        cache.set(cache_key, result, timeout=60)
    except Exception:
        pass
    return success_response(result)


def assetlinks(request):
    """Android App Links verification file.

    Android inakubali file ikiwa YOYOTE kati ya fingerprints zilizoorodheshwa
    inalingana na certificate ya app kama ilivyosakinishwa. Tunaorodhesha:
      1. 1C:47:BA:CE:... — (uhifadhi: huenda ni Play App Signing certificate)
      2. DF:96:D4:AB:... — upload keystore (android/upload-keystore.jks)
      3. FD:9C:F6:FE:... — faraja keystore (android/faraja-keystore.jks)
    KAMA App inatumia Play App Signing (default), certificate halisi ya
    verification ni ile ya Play Console → Setup → App signing → "App signing
    key certificate" SHA-256. Kama haipo hapa, ongeza hapo (na kwenye
    website-repo/.well-known/assetlinks.json pia).
    """
    data = [{
        'relation': [
            'delegate_permission/common.handle_all_urls',
            'delegate_permission/common.get_login_creds'
        ],
        'target': {
            'namespace': 'android_app',
            'package_name': 'co.tz.farajayangutv.app',
            'sha256_cert_fingerprints': [
                '1C:47:BA:CE:EE:3F:4E:D5:F9:3E:15:65:2B:83:91:00:25:04:68:AE:53:96:BE:E7:DD:48:FF:02:AD:6E:B0:A2',
                'DF:96:D4:AB:EE:10:70:85:2D:70:92:32:27:24:B6:97:A6:D4:3E:E8:D4:A0:D9:BB:72:08:C7:0D:49:CA:73:98',
                'FD:9C:F6:FE:EF:0E:C1:4B:6F:6E:E1:54:45:DA:16:19:72:34:65:8A:72:0A:EA:74:70:DD:C5:C1:42:0F:D5:56',
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
    path('watch/<slug:video_id>/', watch_video, name='watch_video'),
    path('website-posts/', public_website_posts, name='public-website-posts'),
    path('categories-with-cover/', public_categories_with_cover, name='public-categories-with-cover'),
    path('videos-by-category/', public_videos_by_category, name='public-videos-by-category'),

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
    path('api/videos-by-category/', public_videos_by_category, name='api-public-videos-by-category'),
    path('api/video/<str:uid>/info/', public_video_info, name='api-public-video-info'),
]
