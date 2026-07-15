from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from django.utils import timezone
from django.db.models import Count
from core.response_wrapper import success_response, error_response

from apps.authentication.models import User
from apps.streaming.models import Comment


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def comment_conversations(request):
    """Get comment conversations grouped by (user, video) pairs."""
    limit = int(request.query_params.get('limit', 100))
    search = request.query_params.get('search', '').strip().lower()

    from django.db.models import Window, F
    from django.db.models.functions import RowNumber

    latest_qs = (
        Comment.objects
        .annotate(
            rn=Window(
                expression=RowNumber(),
                partition_by=[F('user_id'), F('video_id')],
                order_by=F('created_at').desc()
            )
        )
        .filter(rn=1)
        .select_related('user', 'user__profile', 'video')
        .order_by('-created_at')
    )

    conversations = []
    for c in latest_qs:
        if search:
            user_name = (c.user.get_full_name() or c.user.username).lower()
            video_title = (c.video.title or '').lower() if c.video else ''
            if search not in user_name and search not in video_title:
                continue

        avatar = None
        if c.user.profile and c.user.profile.avatar:
            try:
                avatar = c.user.profile.avatar.url
            except ValueError:
                pass

        video_thumb = None
        if c.video and c.video.thumbnail:
            try:
                video_thumb = c.video.thumbnail.url
            except ValueError:
                pass

        conversations.append({
            'user_id': c.user_id,
            'user_name': c.user.get_full_name() or c.user.username,
            'user_avatar': avatar,
            'video_id': c.video_id,
            'video_title': c.video.title if c.video else None,
            'video_thumbnail': video_thumb,
            'latest_text': c.comment[:120],
            'latest_at': c.created_at,
            'message_count': 0,
            '_key': (c.user_id, c.video_id),
        })

        if len(conversations) >= limit:
            break

    if conversations:
        keys = [c['_key'] for c in conversations]
        user_ids = list({k[0] for k in keys})
        video_ids = list({k[1] for k in keys})

        counts = (
            Comment.objects
            .filter(user_id__in=user_ids, video_id__in=video_ids)
            .values('user_id', 'video_id')
            .annotate(
                comment_count=Count('id', distinct=True),
                reply_count=Count('replies__id', distinct=True),
            )
        )

        count_map = {}
        for row in counts:
            key = (row['user_id'], row['video_id'])
            count_map[key] = row['comment_count'] + row['reply_count']

        for c in conversations:
            c['message_count'] = count_map.get(c['_key'], 0)
            del c['_key']

    return success_response(conversations)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def comment_conversation_detail(request, user_id, video_id):
    """Get all messages in a conversation."""
    if not User.objects.filter(pk=user_id).exists():
        return error_response('User not found', code=404)

    user_comments = (
        Comment.objects
        .filter(user_id=user_id, video_id=video_id)
        .select_related('user', 'user__profile', 'video', 'reply_to')
    )

    reply_ids = list(user_comments.values_list('id', flat=True))
    replies = (
        Comment.objects
        .filter(reply_to__id__in=reply_ids)
        .select_related('user', 'user__profile', 'video', 'reply_to')
    )

    all_messages = list(user_comments) + list(replies)
    all_messages.sort(key=lambda x: x.created_at or timezone.now())

    def serialize_message(c):
        avatar = None
        if c.user.profile and c.user.profile.avatar:
            try:
                avatar = c.user.profile.avatar.url
            except ValueError:
                pass
        return {
            'id': c.id,
            'uid': str(c.uid),
            'text': c.comment,
            'author_name': c.user.get_full_name() or c.user.username,
            'author_avatar': avatar,
            'author_id': c.user_id,
            'created_at': c.created_at,
            'is_reply': c.reply_to_id is not None,
            'reply_to_id': c.reply_to_id,
            'is_me': c.user_id == user_id,
        }

    data = {
        'user_id': user_id,
        'video_id': video_id,
        'messages': [serialize_message(c) for c in all_messages],
    }

    return success_response(data)
