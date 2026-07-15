# Profile-Related API Endpoints

This document describes the endpoints used by the profile and related video features (history, favorites, downloads, playlists).

---

## 1. Watch History

### 1.1 List watch history

- **Method:** `GET`
- **Path:** `/streaming/history/`
- **Query params:**
  - `page` (int, default `1`)
  - `page_size` (int, default `20`)
- **Body:** none
- **Expected response:**

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "results": [
      {
        "id": 123,
        "uid": "abc123",
        "title": "Video title",
        "description": "Short description...",
        "thumbnail": "https://.../thumb.jpg",
        "duration": "00:12:34",
        "views_count": 1200,
        "likes_count": 50,
        "dislikes_count": 3,
        "slug": "video-title",
        "created_at": "2025-11-15T10:00:00Z",
        "parent_category_name": "Category",
        "category_name": "Subcategory",
        "last_watched_at": "2025-11-15T11:00:00Z"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "has_next": true,
      "total": 150
    }
  }
}
```

---

## 2. Favorites

### 2.1 List favorites

- **Method:** `GET`
- **Path:** `/streaming/favorites/`
- **Query params:**
  - `page` (int, default `1`)
  - `page_size` (int, default `20`)
- **Body:** none
- **Expected response:** (same structure as history)

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "results": [
      {
        "id": 123,
        "uid": "abc123",
        "title": "Video title",
        "description": "Short description...",
        "thumbnail": "https://.../thumb.jpg",
        "duration": "00:12:34",
        "views_count": 1200,
        "likes_count": 50,
        "dislikes_count": 3,
        "slug": "video-title",
        "created_at": "2025-11-15T10:00:00Z",
        "parent_category_name": "Category",
        "category_name": "Subcategory",
        "favorited_at": "2025-11-15T11:05:00Z"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "has_next": false,
      "total": 5
    }
  }
}
```

### 2.2 Favorite a video

- **Method:** `POST`
- **Path:** `/streaming/stream/{video_uid}/favorite/`
- **Body:** `{}`
- **Expected response:**

```json
{ "success": true, "message": "Favorited" }
```

### 2.3 Unfavorite a video

- **Method:** `DELETE`
- **Path:** `/streaming/stream/{video_uid}/favorite/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Unfavorited" }
```

---

## 3. Downloads (optional server tracking)

### 3.1 List downloads

- **Method:** `GET`
- **Path:** `/streaming/downloads/`
- **Query params:**
  - `page` (int, default `1`)
  - `page_size` (int, default `20`)
- **Body:** none
- **Expected response:** same shape as favorites/history.

### 3.2 Mark video as downloaded

- **Method:** `POST`
- **Path:** `/streaming/stream/{video_uid}/download/`
- **Body:** `{}`
- **Expected response:**

```json
{ "success": true, "message": "Marked as downloaded" }
```

### 3.3 Unmark video as downloaded

- **Method:** `DELETE`
- **Path:** `/streaming/stream/{video_uid}/download/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Removed from downloads" }
```

---

## 4. Playlists

### 4.1 List playlists

- **Method:** `GET`
- **Path:** `/streaming/playlists/`
- **Query params:**
  - `page` (int, default `1`)
  - `page_size` (int, default `20`)
- **Body:** none
- **Expected response:**

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "results": [
      {
        "id": 1,
        "uid": "pl_123",
        "name": "My Favorites",
        "description": "Playlist description",
        "thumbnail": "https://.../thumb.jpg",
        "videos_count": 12,
        "created_at": "2025-11-14T12:00:00Z",
        "updated_at": "2025-11-15T09:00:00Z"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "has_next": false,
      "total": 3
    }
  }
}
```

### 4.2 Create playlist

- **Method:** `POST`
- **Path:** `/streaming/playlists/`
- **Body:**

```json
{
  "name": "My Playlist",
  "description": "Optional description"
}
```

- **Expected response:**

```json
{
  "success": true,
  "message": "Playlist created",
  "data": {
    "id": 2,
    "uid": "pl_456",
    "name": "My Playlist",
    "description": "Optional description",
    "thumbnail": null,
    "videos_count": 0,
    "created_at": "2025-11-15T10:00:00Z",
    "updated_at": "2025-11-15T10:00:00Z"
  }
}
```

### 4.3 Get playlist details (with videos)

- **Method:** `GET`
- **Path:** `/streaming/playlists/{playlist_uid}/`
- **Body:** none
- **Expected response:**

```json
{
  "success": true,
  "message": "Success",
  "data": {
    "id": 2,
    "uid": "pl_456",
    "name": "My Playlist",
    "description": "Optional description",
    "thumbnail": null,
    "videos_count": 2,
    "created_at": "2025-11-15T10:00:00Z",
    "updated_at": "2025-11-15T10:05:00Z",
    "videos": [
      {
        "id": 123,
        "uid": "abc123",
        "title": "Video 1",
        "description": "Short description...",
        "thumbnail": "https://.../thumb1.jpg",
        "duration": "00:10:00",
        "views_count": 100,
        "likes_count": 5,
        "dislikes_count": 0,
        "slug": "video-1",
        "created_at": "2025-11-10T10:00:00Z",
        "parent_category_name": "Category",
        "category_name": "Subcategory"
      }
    ]
  }
}
```

### 4.4 Add video to playlist

- **Method:** `POST`
- **Path:** `/streaming/playlists/{playlist_uid}/videos/`
- **Body:**

```json
{
  "video_uid": "abc123"
}
```

- **Expected response:**

```json
{ "success": true, "message": "Video added to playlist" }
```

### 4.5 Remove video from playlist

- **Method:** `DELETE`
- **Path:** `/streaming/playlists/{playlist_uid}/videos/{video_uid}/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Video removed from playlist" }
```

### 4.6 Delete playlist

- **Method:** `DELETE`
- **Path:** `/streaming/playlists/{playlist_uid}/`
- **Body:** none
- **Expected response:**

```json
{ "success": true, "message": "Playlist deleted" }
```
