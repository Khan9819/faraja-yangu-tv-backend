from django.urls import path, re_path
from . import views

app_name = 'streaming'

urlpatterns = [
    # Add your URL patterns here
    path('create-category/', views.create_category, name='create-category'),
    path('update-category/<int:pk>/', views.update_category, name='update-category'),
    path('categories/', views.get_categories, name='category-list'),
    path('categories/<int:pk>/', views.get_category, name='category-detail'),
    path('categories/<int:pk>/videos/', views.get_category_videos, name='category-videos'),
    path('subcategories/<int:category_id>/', views.get_subcategories, name='subcategory-list'),
    # path('subcategories/<int:pk>/', views.get_subcategory, name='subcategory-detail'),
    
    path('feed/', views.get_feed, name='feed-list'),
    path('history/', views.history_list, name='history-list'),
    path('history/clear/', views.clear_history_list, name='history-clear'),
    path('favorites/', views.favorites_list, name='favorites-list'),
    path('favorites/clear/', views.clear_favorites_list, name='favorites-clear'),
    path('downloads/', views.downloads_list, name='downloads-list'),
    path('q/', views.search_videos, name='search-videos'),
    path('get-all-videos/', views.get_all_videos, name='get-all-video-list'),
    path('get-video/<int:pk>/', views.get_video, name='get-video-detail'),
    path('get-video-comments/<int:pk>/', views.get_video_comments, name='get-video-comments-list'),
    path('get-video-related/<int:video_id>/', views.get_video_related, name='get-video-related-list'),
    
    path('create-video/', views.create_video, name='create-video'),
    path('update-video/<int:pk>/', views.update_video, name='update-video'),
    path('delete-video/<int:pk>/', views.delete_video, name='delete-video'),
    
    # Chunked upload endpoints
    path('get-chunk-upload-url/', views.get_chunk_upload_url, name='get-chunk-upload-url'),
    path('get-upload-status/', views.get_upload_status, name='get-upload-status'),
    path('upload-chunk/', views.upload_chunk, name='upload-chunk'),
    path('assemble-chunks/', views.assemble_chunks, name='assemble-chunks'),
    
    # Google Drive import endpoints
    path('import-from-google-drive/', views.import_from_google_drive, name='import-from-google-drive'),
    path('google-drive-import-status/', views.google_drive_import_status, name='google-drive-import-status'),
    
    path('like-video/<int:video_id>/', views.like_video, name='like-video'),
    path('dislike-video/<int:video_id>/', views.dislike_video, name='dislike-video'),
    path('like-comment/<int:comment_id>/', views.like_comment, name='like-comment'),
    path('dislike-comment/<int:comment_id>/', views.dislike_comment, name='dislike-comment'),
    path('comment/<int:video_id>/', views.comment, name='comment'),
    path('reply/<int:comment_id>/', views.reply, name='reply'),
    path('view/<int:video_id>/', views.view, name='view'),
    
    # Video player related / interaction endpoints (additive)
    path('stream/<str:video_uid>/related/', views.get_related_videos, name='stream-related'),
    path('stream/<str:video_uid>/like/', views.video_like_stream, name='stream-like'),
    path('stream/<str:video_uid>/dislike/', views.video_dislike_stream, name='stream-dislike'),
    path('stream/<str:video_uid>/view/', views.record_view_stream, name='stream-view'),
    path('stream/<str:video_uid>/share/', views.record_share_stream, name='stream-share'),
    path('stream/<str:video_uid>/comments/', views.video_comments_stream, name='stream-comments'),
    path('stream/<str:video_uid>/interceptor-ads/', views.interceptor_ads, name='stream-interceptor-ads'),
    path('comments/<int:comment_id>/replies/', views.comment_replies_stream, name='comment-replies'),
    path('comments/<int:comment_id>/like/', views.comment_like_stream, name='comment-like'),
    path('comments/<int:comment_id>/', views.delete_comment_stream, name='comment-delete'),
    
    path('playlists/', views.playlist_list, name='playlist-list'),
    path('playlists/create/', views.playlist_create, name='playlist-create'),
    path('playlists/<str:playlist_uid>/', views.playlist_detail, name='playlist-detail'),
    path('playlists/<str:playlist_id>/videos/', views.playlist_add_video, name='playlist-add-video'),
    path('playlists/<str:playlist_id>/videos/clear/', views.playlist_clear_video, name='playlist-clear-videos'),
    path('playlists/<str:playlist_uid>/videos/<str:video_uid>/', views.playlist_remove_video, name='playlist-remove-video'),
    path('playlists/<str:playlist_uid>/delete/', views.playlist_delete, name='playlist-delete'),
    
    # HLS Streaming endpoints
    path('stream/<str:uid>/', views.get_video_stream_url, name='get-stream-url'),
    path('stream/<str:video_uid>/favorite/', views.favorite_video, name='favorite-video'),
    path('stream/<str:video_uid>/unfavorite/', views.unfavorite_video, name='unfavorite-video'),
    path('stream/<str:video_uid>/download/', views.mark_video_downloaded, name='download-video'),
    path('stream/<str:video_uid>/undownload/', views.unmark_video_downloaded, name='undownload-video'),
    path('stream/<str:video_uid>/download-status/', views.get_download_status, name='download-status'),
    path('user-downloads/', views.get_user_downloads, name='user-downloads'),
    re_path(r'^hls/(?P<video_slug>[\w-]+)/(?P<file_path>.+)$', views.stream_hls, name='stream-hls'),

    # CMS: Comments
    path('comments/recent/', views.recent_comments, name='recent-comments'),
    path('videos/<int:video_id>/comments/', views.video_comments_list, name='video-comments-list'),
    path('cms/comments/<int:comment_id>/reply/', views.cms_comment_reply, name='cms-comment-reply'),
    path('cms/comments/<int:comment_id>/replies/', views.cms_comment_replies, name='cms-comment-replies'),
    path('cms/comments/<int:comment_id>/', views.cms_comment_delete, name='cms-comment-delete'),

    # CMS: Video Viewers & Interactions
    path('videos/<int:video_id>/viewers/', views.video_viewers, name='video-viewers'),
    path('videos/<int:video_id>/interactions/', views.video_interactions, name='video-interactions'),
]
