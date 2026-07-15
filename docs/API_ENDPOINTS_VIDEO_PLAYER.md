# Video Player Screen API Endpoints

This document describes all backend endpoints used (or expected) by
`lib/features/videos/presentation/video_player_screen.dart` and its
supporting comment/video endpoints.

---

## 1. Video Details / Streaming

### 1.1 Get video details (including stream URL)

Used in `_initializePlayer()` to fetch the HLS URL (and metadata).

- **Method:** `GET`
- **Path:** `/streaming/stream/{video_uid}/`
- **Path params:**
  - `video_uid` – unique identifier of the video
- **Query params:** none
- **Body:** none
- **Expected response:**

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "id": 123,
    "uid": "abc123",
    "title": "Video title",
    "description": "Long description...",
    "thumbnail": "https://.../thumb.jpg",
    "duration": "00:12:34",
    "views_count": 1200,
    "likes_count": 50,
    "dislikes_count": 3,
    "slug": "video-title",
    "created_at": "2025-11-15T10:00:00Z",
    "parent_category_name": "Category",
    "category_name": "Subcategory",
    "stream_url": "https://.../video.m3u8"  // HLS URL used by the player
  }
}
```

The frontend uses `data.stream_url` as the authenticated HLS URL.

---

## 2. Related Videos

Used in `_loadRelatedVideos()` and `_loadMoreRelatedVideos()` to show
"Related Videos" under the player.

> NOTE: Currently `VideoEndpoints.getRelatedVideos(videoUid)` calls:
> `GET streaming/stream/{video_uid}/related/` with no query params.
> For pagination support you can extend this later with `page` / `page_size`.

- **Method:** `GET`
- **Path:** `/streaming/stream/{video_uid}/related/`
- **Path params:**
  - `video_uid` – reference video to base recommendations on
- **Query params:** (current implementation does not send any)
  - Optional future fields: `page`, `page_size`
- **Body:** none
- **Expected response:**

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "videos": [
      {
        "id": 456,
        "uid": "rel_1",
        "title": "Related video 1",
        "description": "Short description...",
        "thumbnail": "https://.../rel1.jpg",
        "duration": "00:05:00",
        "views": 500,
        "views_count": 500,
        "likes_count": 20,
        "dislikes_count": 1,
        "slug": "related-video-1",
        "created_at": "2025-11-14T09:00:00Z",
        "parent_category_name": "Category",
        "category_name": "Subcategory"
      }
    ],
    "has_more": false
  }
}
```

The UI expects `data.videos` as a list of objects with at least:
`id`, `uid`, `title`, `thumbnail`, `duration`, `views` or `views_count`, and
category names.

---

## 3. Video Interactions

These are called from `_toggleLike`, `_toggleDislike`, `_shareVideo`, and
view-tracking logic.

### 3.1 Like a video

- **Method:** `POST`
- **Path:** `/streaming/stream/{video_uid}/like/`
- **Body:**

```json
{}
```

- **Expected response:**

```json
{ "success": true, "message": "Liked" }
```

### 3.2 Remove like

- **Method:** `DELETE`
- **Path:** `/streaming/stream/{video_uid}/like/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Like removed" }
```

### 3.3 Dislike a video

- **Method:** `POST`
- **Path:** `/streaming/stream/{video_uid}/dislike/`
- **Body:** `{}`
- **Expected response:**

```json
{ "success": true, "message": "Disliked" }
```

### 3.4 Remove dislike

- **Method:** `DELETE`
- **Path:** `/streaming/stream/{video_uid}/dislike/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Dislike removed" }
```

### 3.5 Record a view

Used when the player starts/plays to increment views.

- **Method:** `POST`
- **Path:** `/streaming/stream/{video_uid}/view/`
- **Body:** `{}`
- **Expected response:**

```json
{ "success": true, "message": "View recorded" }
```

### 3.6 Share a video

Called from `_shareVideo()` to record a share action (sharing to external apps
uses `share_plus`, not the backend).

- **Method:** `POST`
- **Path:** `/streaming/stream/{video_uid}/share/`
- **Body:** `{}`
- **Expected response:**

```json
{ "success": true, "message": "Share recorded" }
```

### 3.7 (Future) Save / bookmark a video

The save button in the UI is currently disabled and only shows
"coming soon". If you want server-side save/bookmark support, you can
use the favorite endpoints already defined:

- `POST /streaming/stream/{video_uid}/favorite/`
- `DELETE /streaming/stream/{video_uid}/favorite/`

as documented in `API_ENDPOINTS_PROFILE_FEATURE.md`.

---

## 4. Comments API

Used extensively in `_loadComments`, `_loadMoreComments`, posting, replying,
liking, and deleting comments. Implemented via
`lib/services/endpoints/comment.endpoints.dart`.

### 4.1 Get comments for a video (paginated)

- **Method:** `GET`
- **Path:** `/streaming/stream/{video_uid}/comments/`
- **Path params:**
  - `video_uid`
- **Query params:**
  - `page` (int, default `1`)
  - `per_page` (int, default `4` in the UI)
- **Body:** none
- **Expected response:**

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "comments": [
      {
        "id": 1,
        "uid": "c_1",
        "author_name": "John Doe",
        "author_avatar": "https://.../avatar.png",
        "content": "Nice video!",
        "created_at": "2025-11-15T10:10:00Z",
        "likes_count": 3,
        "is_liked": false,
        "replies_count": 1
      }
    ],
    "has_more": true
  }
}
```

The UI expects `data.comments` (list) and `data.has_more` (bool).

### 4.2 Get replies for a comment

- **Method:** `GET`
- **Path:** `/streaming/comments/{comment_id}/replies/`
- **Path params:**
  - `comment_id`
- **Query params:**
  - `page` (int, default `1`)
  - `per_page` (int)
- **Body:** none
- **Expected response:**

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "replies": [
      {
        "id": 10,
        "uid": "r_10",
        "author_name": "Jane",
        "content": "Reply text...",
        "created_at": "2025-11-15T10:20:00Z",
        "likes_count": 0,
        "is_liked": false
      }
    ],
    "has_more": false
  }
}
```

### 4.3 Post a comment

- **Method:** `POST`
- **Path:** `/streaming/stream/{video_uid}/comments/`
- **Body:**

```json
{
  "content": "Comment text" 
}
```

- **Expected response:**

```json
{
  "success": true,
  "message": "Comment posted",
  "data": {
    "id": 1,
    "uid": "c_1",
    "author_name": "Current User",
    "author_avatar": "https://.../avatar.png",
    "content": "Comment text",
    "created_at": "2025-11-15T10:10:00Z",
    "likes_count": 0,
    "is_liked": false,
    "replies_count": 0
  }
}
```

### 4.4 Reply to a comment

- **Method:** `POST`
- **Path:** `/streaming/comments/{comment_id}/replies/`
- **Body:**

```json
{
  "content": "Reply text" 
}
```

- **Expected response:**

```json
{
  "success": true,
  "message": "Reply posted",
  "data": {
    "id": 10,
    "uid": "r_10",
    "author_name": "Current User",
    "author_avatar": "https://.../avatar.png",
    "content": "Reply text",
    "created_at": "2025-11-15T10:20:00Z",
    "likes_count": 0,
    "is_liked": false
  }
}
```

### 4.5 Like a comment

- **Method:** `POST`
- **Path:** `/streaming/comments/{comment_id}/like/`
- **Body:** `{}`
- **Expected response:**

```json
{ "success": true, "message": "Comment liked" }
```

### 4.6 Unlike a comment

- **Method:** `DELETE`
- **Path:** `/streaming/comments/{comment_id}/like/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Comment like removed" }
```

### 4.7 Delete a comment

- **Method:** `DELETE`
- **Path:** `/streaming/comments/{comment_id}/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Comment deleted" }
```