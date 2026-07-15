from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from apps.authentication.services.credit import UserCreditService
from core.response_wrapper import success_response, error_response
from rest_framework.permissions import IsAuthenticated
from apps.advertising.models import Ad
from apps.advertising.serializers import AdSerializer, ClaimRewardSerializer
from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import F


def _invalidate_carousel_cache():
    """Invalidate all carousel ad caches."""
    cache.delete("carousel_ads:CUSTOM")
    cache.delete("carousel_ads:GOOGLE")
    cache.delete("carousel_ads:")

# Reward constants
CREDITS_PER_SECOND = 1  # Credits earned per second of ad viewing
AD_CLICK_BONUS = 10  # Bonus credits for clicking an ad

# Create your views here.

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_carousel_ads(request):
    """Return up to 4 published carousel ads, optionally filtered by ad_render_type.

    Query params:
    - ad_render_type: "CUSTOM" or "GOOGLE" (optional)
    """
    close_old_connections()
    
    ad_render_type = request.GET.get('ad_render_type', '')
    
    # Try cache first
    cache_key = f"carousel_ads:{ad_render_type}"
    cached_ads = cache.get(cache_key)
    if cached_ads:
        return success_response(cached_ads)

    qs = Ad.objects.filter(type=Ad.AD_TYPES.CAROUSEL, is_published=True)
    if ad_render_type in (Ad.AD_RENDER_TYPES.CUSTOM, Ad.AD_RENDER_TYPES.GOOGLE):
        qs = qs.filter(ad_render_type=ad_render_type)

    ads = qs.order_by('-created_at')[:4]

    serializer = AdSerializer(ads, many=True)
    
    # Cache for 60 seconds
    cache.set(cache_key, serializer.data, timeout=60)
    
    return success_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_carousel_ad(request, pk):
    """Get a single carousel ad by ID.

    URL Parameters:
    - pk: int (carousel ad ID)
    """
    try:
        ad = Ad.objects.get(pk=pk, type=Ad.AD_TYPES.CAROUSEL)
    except Ad.DoesNotExist:
        return error_response('Carousel ad not found', code=404)

    serializer = AdSerializer(ad, context={'request': request})
    return success_response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_carousel_ad(request):
    data = request.data.copy()
    data['type'] = Ad.AD_TYPES.CAROUSEL
    data['uploaded_by'] = request.user.id

    serializer = AdSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        _invalidate_carousel_cache()
        return success_response(serializer.data, message='Carousel ad created successfully')

    return error_response(serializer.errors, code=400)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_carousel_ad(request, pk):
    try:
        ad = Ad.objects.get(pk=pk, type=Ad.AD_TYPES.CAROUSEL)
    except Ad.DoesNotExist:
        return error_response('Carousel ad not found', code=404)

    partial = request.method == 'PATCH'
    serializer = AdSerializer(ad, data=request.data, partial=partial)
    if serializer.is_valid():
        serializer.save()
        _invalidate_carousel_cache()
        return success_response(serializer.data, message='Carousel ad updated successfully')

    return error_response(serializer.errors, code=400)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_carousel_ad(request, pk):
    try:
        ad = Ad.objects.get(pk=pk, type=Ad.AD_TYPES.CAROUSEL)
    except Ad.DoesNotExist:
        return error_response('Carousel ad not found', code=404)

    ad.delete()
    _invalidate_carousel_cache()
    return success_response(message='Carousel ad deleted successfully')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def claim_reward(request):
    """Claim reward credits for watching an ad.
    
    Idempotent via ``ad_session_id``: duplicate claims for the same session
    return success without granting additional credits.
    
    Rate-limited: max 1 successful claim per user per 30 seconds.
    
    Payload:
    - time_spent_seconds: int - seconds spent watching the ad
    - ad_clicked: bool - whether the user clicked the ad
    - ad_id: int (optional) - ID of the ad watched
    - ad_session_id: UUID (optional) - unique ID per ad view for dedup
    
    Returns:
    - credits_awarded: credits earned from this claim (0 if duplicate)
    - total_credits: user's new credit balance
    """
    close_old_connections()
    
    serializer = ClaimRewardSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(serializer.errors, code=400)
    
    time_spent_seconds = serializer.validated_data['time_spent_seconds']
    ad_clicked = serializer.validated_data['ad_clicked']
    ad_id = serializer.validated_data.get('ad_id')
    ad_session_id = serializer.validated_data.get('ad_session_id')
    
    # Get or create user profile
    user = request.user
    profile = user.profile
    if not profile:
        from apps.authentication.models import Profile
        profile = Profile.objects.create()
        user.profile = profile
        user.save()
    
    credit_service = UserCreditService(user)

    # ad_session_id deduplication
    if ad_session_id:
        session_cache_key = f"ad_session:{user.pk}:{ad_session_id}"
        cached = cache.get(session_cache_key)
        if cached is not None:
            return success_response(cached, message='Reward already claimed for this session')

    # Rate limiting: max 1 claim per user per 30 seconds
    cooldown_key = f"reward_cooldown:{user.pk}"
    if cache.get(cooldown_key):
        return error_response('Please wait before claiming another reward', code=429)
    
    # Update credit accumulation atomically
    credits_earned = credit_service.gain_from_ad()
    
    # Set rate-limit cooldown
    cache.set(cooldown_key, True, timeout=30)
    
    # Track ad interaction if ad_id provided
    if ad_id:
        try:
            ad = Ad.objects.get(pk=ad_id)
            profile.ads_viewed.add(ad)
            Ad.objects.filter(pk=ad_id).update(views_count=F('views_count') + 1)
            if ad_clicked:
                profile.ads_clicked.add(ad)
        except Ad.DoesNotExist:
            pass  # Silently ignore invalid ad_id
    
    data = {
        'credits_awarded': credits_earned,
        'total_credits': credit_service.get_balance(),
    }

    # Cache the response for session dedup (5 min TTL)
    if ad_session_id:
        cache.set(session_cache_key, data, timeout=300)

    return success_response(data, message='Reward claimed successfully')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_view(request, ad_id):
    """Record an ad impression (view). Increments views_count atomically."""
    try:
        Ad.objects.filter(pk=ad_id).update(views_count=F('views_count') + 1)
        return success_response(message='View recorded')
    except Exception:
        return error_response('Failed to record view', code=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_click(request, ad_id):
    """Record an ad click. Increments views_count and tracks click."""
    try:
        ad = Ad.objects.filter(pk=ad_id).first()
        if ad:
            Ad.objects.filter(pk=ad_id).update(views_count=F('views_count') + 1)
            request.user.profile.ads_clicked.add(ad)
        return success_response(message='Click recorded')
    except Exception:
        return error_response('Failed to record click', code=500)