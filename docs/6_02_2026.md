# FarajaYangu TV CMS — Backend API Requirements

This document describes **every API endpoint** the CMS frontend consumes. Endpoints are grouped by module. Each section states whether the endpoint **already exists** or **needs to be built**.

> **Base URL (dev):** `http://127.0.0.1:8000`
> **Base URL (prod):** `https://backend.farajayangutv.co.tz`
> **Auth:** JWT via httpOnly cookies (`withCredentials: true`). Access token sent as `Authorization: Bearer <token>`.

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Dashboard / Management](#2-dashboard--management)
3. [Streaming (Videos & Categories)](#3-streaming-videos--categories)
4. [Advertising (Carousel Ads)](#4-advertising-carousel-ads)
5. [Interceptor Ads](#5-interceptor-ads)
6. [App Users Management](#6-app-users-management) — NEW
7. [Admin Users Management](#7-admin-users-management) — NEW
8. [Profile](#8-profile) — NEW
9. [Notifications](#9-notifications) — NEW
10. [Reports / Analytics](#10-reports--analytics) — NEW
11. [Settings](#11-settings) — NEW
12. [Active Users Today](#12-active-users-today) — NEW
13. [Comments](#13-comments) — NEW
14. [Video Viewers & Interactions](#14-video-viewers--interactions) — NEW

---

## 1. Authentication

> **Status: ✅ ALL EXIST — No changes needed**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/authentication/login/` | Login with credentials, returns JWT tokens + profile |
| POST | `/authentication/logout/` | Logout, invalidate refresh token |
| POST | `/authentication/refresh/` | Refresh access token using httpOnly cookie |
| POST | `/authentication/request-password-reset/` | Request password reset email |
| POST | `/authentication/reset-password/` | Reset password with token |
| POST | `/authentication/finalize-account-setup/` | Finalize new account setup |

### Login Response Shape (already in use)

```json
{
  "success": true,
  "data": {
    "access_token": "...",
    "profile": {
      "user": {
        "id": 1,
        "first_name": "John",
        "last_name": "Doe",
        "username": "johndoe",
        "email": "john@example.com",
        "phone_number": "+255...",
        "last_seen": "2024-01-20T10:30:00Z",
        "active_workspace": 1,
        "avatar": "https://...",
        "permission": "super_admin",
        "country": "TZ",
        "notifications": [...]
      },
      "workspace": {
        "billing": {
          "id": 1,
          "currency": "TZS",
          "plan": "premium",
          "status": "active",
          "account": null
        }
      }
    }
  }
}
```

---

## 2. Dashboard / Management

> **Status: ✅ ALL EXIST — No changes needed**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/management/summary/` | Dashboard summary (clients, active_users, retention, engagement, views, watch_time, likes, comments, ads, notifications, devices) |
| GET | `/management/clients-stats/` | Client stats table (all clients) |
| GET | `/management/dashboard-analytics-chart/` | Analytics chart data. Optional `?month=1-12` |

### Summary Response Shape (already in use)

```json
{
  "success": true,
  "data": {
    "clients": { "total": 1200, "today": 5, "month": 120, "year": 800 },
    "active_users": { "total": 800, "today": 150, "month": 500, "year": 750 },
    "retention": { "active_last_7_days": 300, "active_last_30_days": 600, "active_last_30_days_pct": 75.0 },
    "engagement_rate": { "total": 0.65, "today": 0.45, "month": 0.6 },
    "views": { "total": 50000, "today": 200, "month": 8000, "year": 45000 },
    "watch_time": { "total": 2500, "today": 15, "month": 400 },
    "avg_watch_time_per_user": { "total": 3.1, "today": 0.1, "month": 0.8 },
    "likes": { "total": 12000, "today": 50, "month": 2000, "year": 10000 },
    "comments": { "total": 3000, "today": 10, "month": 500, "year": 2500 },
    "ads": { "total_ads": 15, "published_ads": 12, "types": { "carousel": 8, "video": 7 } },
    "analytics": { "notifications": { "total": 50, "unread": 5 } },
    "devices": { "total": 900, "androids": 700, "iOS": 200, "latest_version": "2.1.0", "uptodate_ratio": 85.0 }
  }
}
```

### Clients Stats Response Shape (already in use)

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "full_name": "Amina Rashid",
      "email": "amina@gmail.com",
      "provider": "email",
      "watched_video_count_today": 3,
      "is_registered_today": false,
      "date_joined": "2024-01-01T00:00:00Z",
      "last_login": "2024-01-20T10:30:00Z"
    }
  ]
}
```

---

## 3. Streaming (Videos & Categories)

> **Status: ✅ ALL EXIST — No changes needed**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/streaming/categories/` | List categories. Optional `?type=all\|parent\|children` |
| GET | `/streaming/categories/{id}/` | Get single category details |
| GET | `/streaming/subcategories/{id}/` | Get subcategories of a parent category |
| POST | `/streaming/create-category/` | Create category (multipart: `name`, `description`, `parent`, `thumbnail`, `cover`) |
| PUT | `/streaming/update-category/{id}/` | Update category (multipart) |
| DELETE | `/streaming/categories/{id}/` | Delete category |
| GET | `/streaming/get-all-videos/` | List videos. Supports `?category={id}` filter |
| GET | `/streaming/get-video/{id}/` | Get single video |
| GET | `/streaming/stream/{id}/` | Get HLS stream URL |
| POST | `/streaming/create-video/` | Create video (multipart) |
| PUT | `/streaming/update-video/{id}/` | Update video (multipart) |
| DELETE | `/streaming/delete-video/{id}/` | Delete video |
| POST | `/streaming/get-chunk-upload-url/` | Get presigned URL for chunk upload |
| POST | `/streaming/upload-chunk/` | Upload a video chunk (multipart) |
| GET | `/streaming/get-upload-status/` | Get upload status. `?videoId={id}&totalChunks={n}` |
| POST | `/streaming/assemble-chunks/` | Assemble uploaded chunks |
| POST | `/streaming/import-from-google-drive/` | Import video from Google Drive URL |
| GET | `/streaming/google-drive-import-status/` | Check import status. `?videoId={id}` |

### Important: Category response should include

The frontend reads these fields from category objects. Make sure they are present:

- `id`, `name`, `description`, `thumbnail`, `cover`
- `parent` (FK id or null)
- `parent_name` (string, for breadcrumbs in category-videos page)
- `children_count` (int, number of subcategories — used in parent category cards)
- `video_count` (int, number of videos — used in subcategory cards)

### Important: Videos list should support category filter

`GET /streaming/get-all-videos/?category={id}` — must return only videos belonging to that category.

---

## 4. Advertising (Carousel Ads)

> **Status: ✅ ALL EXIST — No changes needed**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/advertising/get-carousel-ads/` | List carousel ads. Optional `?ad_render_type=CUSTOM\|GOOGLE` |
| POST | `/advertising/create-carousel-ad/` | Create carousel ad (multipart: `name`, `description`, `ad_render_type`, `duration`, `is_published`, `thumbnail`) |
| PATCH | `/advertising/update-carousel-ad/{id}/` | Update carousel ad |
| DELETE | `/advertising/delete-carousel-ad/{id}/` | Delete carousel ad |

**Note:** The frontend now defaults `ad_render_type` to `"CUSTOM"` and no longer sends a `video` field. The backend may still accept video uploads but the CMS will not send them.

---

## 5. Interceptor Ads

> **Status: ✅ ALL EXIST — No changes needed**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/management/interceptor/ads/` | List interceptor ads |
| POST | `/management/interceptor/ads/create/` | Create interceptor ad (multipart) |
| GET | `/management/interceptor/ad/{id}/` | Get single interceptor ad |
| PUT | `/management/interceptor/ads/{id}/update/` | Update interceptor ad (multipart) |
| PATCH | `/management/interceptor/ads/{id}/toggle/` | Toggle active status. Body: `{ "is_active": true/false }` |
| DELETE | `/management/interceptor/ads/{id}/` | Delete interceptor ad |

---

## 6. App Users Management

> **Status: 🔴 NEEDS TO BE BUILT**

These endpoints manage the **mobile app users** (not CMS admin users).

### `GET /management/app-users/`

List all app users with pagination and filtering.

**Query Parameters:**
- `page` (int, optional) — page number
- `page_size` (int, optional, default 25) — results per page
- `search` (string, optional) — search by name, email, or phone
- `status` (string, optional) — filter by `active`, `suspended`, `inactive`
- `plan` (string, optional) — filter by `free`, `premium`

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "full_name": "Amina Rashid",
      "first_name": "Amina",
      "last_name": "Rashid",
      "username": "amina_r",
      "email": "amina@gmail.com",
      "phone_number": "+255712345678",
      "plan": "Premium",
      "is_active": true,
      "is_suspended": false,
      "last_active": "2024-01-20T10:30:00Z",
      "last_login": "2024-01-20T10:30:00Z",
      "date_joined": "2023-08-15T00:00:00Z"
    }
  ]
}
```

### `GET /management/app-users/{id}/`

Get details for a single app user.

### `PATCH /management/app-users/{id}/suspend/`

Suspend an app user. Sets `is_suspended = true`. Empty body `{}`.

**Response:** `{ "success": true, "message": "User suspended." }`

### `PATCH /management/app-users/{id}/unsuspend/`

Unsuspend an app user. Sets `is_suspended = false`. Empty body `{}`.

**Response:** `{ "success": true, "message": "User unsuspended." }`

---

## 7. Admin Users Management

> **Status: 🔴 NEEDS TO BE BUILT**

These endpoints manage **CMS admin/staff users** (displayed in Settings > Admin Users tab).

### `GET /management/admin-users/`

List all admin/staff users.

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "full_name": "Admin User",
      "first_name": "Admin",
      "last_name": "User",
      "username": "admin",
      "email": "admin@farajatv.co.tz",
      "permission": "super_admin",
      "role": "Super Admin",
      "is_active": true,
      "last_login": "2024-01-20T10:30:00Z"
    }
  ]
}
```

### `POST /management/admin-users/create/`

Create a new admin user.

**Request Body (JSON):**

```json
{
  "first_name": "John",
  "last_name": "Doe",
  "email": "john@farajatv.co.tz",
  "username": "john_doe",
  "role": "admin",
  "password": "secure_password"
}
```

**Valid roles:** `super_admin`, `admin`, `moderator`

**Response:** `{ "success": true, "data": { ...created_user }, "message": "Admin user created." }`

### `PATCH /management/admin-users/{id}/update/`

Update an existing admin user. All fields optional. If `password` is provided, update it; if omitted, keep existing password.

**Request Body (JSON):** Same fields as create, all optional.

### `DELETE /management/admin-users/{id}/`

Delete an admin user.

**Response:** `{ "success": true, "message": "Admin user deleted." }`

---

## 8. Profile

> **Status: 🔴 NEEDS TO BE BUILT**

The login response already returns profile data, but we need dedicated endpoints for viewing and updating profile.

### `GET /authentication/profile/`

Get the authenticated user's profile.

**Response:**

```json
{
  "success": true,
  "data": {
    "id": 1,
    "first_name": "John",
    "last_name": "Doe",
    "username": "johndoe",
    "email": "john@farajatv.co.tz",
    "phone_number": "+255...",
    "avatar": "https://...",
    "permission": "super_admin",
    "last_seen": "2024-01-20T10:30:00Z"
  }
}
```

### `PATCH /authentication/profile/update/`

Update the authenticated user's profile.

**Request Body (JSON):**

```json
{
  "first_name": "John",
  "last_name": "Doe",
  "email": "john@farajatv.co.tz",
  "username": "johndoe"
}
```

**Response:** `{ "success": true, "data": { ...updated_profile }, "message": "Profile updated." }`

### `POST /authentication/change-password/`

Change the authenticated user's password.

**Request Body (JSON):**

```json
{
  "current_password": "old_password",
  "new_password": "new_password",
  "confirm_password": "new_password"
}
```

**Response:**
- Success: `{ "success": true, "message": "Password changed successfully." }`
- Error: `{ "success": false, "message": "Current password is incorrect." }` (HTTP 400)

---

## 9. Notifications

> **Status: 🔴 NEEDS TO BE BUILT**

The frontend polls this every 30 seconds to show real-time notifications in the AppBar.

### `GET /management/notifications/`

List notifications for the authenticated admin user.

**Query Parameters:**
- `page` (int, optional)
- `page_size` (int, optional, default 10)

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "type": "video_processed",
      "title": "Video Processing Complete",
      "message": "Serengeti Wildlife has finished processing.",
      "read": false,
      "is_read": false,
      "created_at": "2024-01-20T10:30:00Z"
    }
  ]
}
```

**Notification types to support:**
- `video_processed` — A video finished processing
- `video_failed` — A video processing failed
- `new_user` — A new app user registered
- `comment` — A new comment on a video
- `system` — System announcements

### `PATCH /management/notifications/{id}/read/`

Mark a single notification as read. Empty body `{}`.

**Response:** `{ "success": true, "message": "Notification marked as read." }`

### `POST /management/notifications/read-all/`

Mark all notifications as read. Empty body `{}`.

**Response:** `{ "success": true, "message": "All notifications marked as read." }`

---

## 10. Reports / Analytics

> **Status: 🔴 NEEDS TO BE BUILT**

These provide aggregated analytics data for the Reports page. The existing `/management/summary/` endpoint serves the Dashboard page and should remain unchanged.

### `GET /management/reports/summary/`

High-level counts for the reports page.

**Response:**

```json
{
  "success": true,
  "data": {
    "total_videos": 156,
    "published_videos": 142,
    "draft_videos": 14,
    "total_views": 2400000,
    "total_likes": 185000,
    "active_users": 12500
  }
}
```

### `GET /management/reports/top-videos/`

Top performing videos, sorted by views descending.

**Query Parameters:**
- `limit` (int, optional, default 10)
- `period` (string, optional) — `week`, `month`, `year`, `all` (default `all`)

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 42,
      "title": "Serengeti Wildlife",
      "views_count": 285000,
      "likes_count": 15200,
      "thumbnail": "https://..."
    }
  ]
}
```

### `GET /management/reports/category-performance/`

Category performance data, sorted by total views descending.

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Documentary",
      "video_count": 45,
      "total_views": 892000
    }
  ]
}
```

---

## 11. Settings

> **Status: 🔴 NEEDS TO BE BUILT**

Platform-level settings. Currently read-only in the CMS but the update endpoint is prepared for future use.

### `GET /management/settings/`

Get platform settings.

**Response:**

```json
{
  "success": true,
  "data": {
    "platform_name": "FarajaYangu TV",
    "language": "English",
    "app_version": "2.1.0",
    "push_notifications_enabled": true,
    "email_notifications_enabled": true
  }
}
```

### `PATCH /management/settings/`

Update platform settings. All fields optional.

**Request Body (JSON):**

```json
{
  "platform_name": "FarajaYangu TV",
  "push_notifications_enabled": false
}
```

**Response:** `{ "success": true, "data": { ...updated_settings }, "message": "Settings updated." }`

---

## 12. Active Users Today

> **Status: 🔴 NEEDS TO BE BUILT**

This endpoint powers the **Dashboard table** which shows only users who have been active today (logged in or watched a video today).

### `GET /management/active-users-today/`

List app users who were active today.

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "full_name": "Amina Rashid",
      "email": "amina@gmail.com",
      "provider": "email",
      "watched_video_count_today": 3,
      "last_active": "2024-01-20T10:30:00Z",
      "last_login": "2024-01-20T08:00:00Z"
    }
  ]
}
```

**Definition of "active today":** User has either logged in or made any API request (video watch, like, comment) within the current day (server timezone).

**Note:** This is similar to the existing `/management/clients-stats/` but filtered to only today's active users and with a `last_active` field.

---

## 13. Comments

> **Status: 🔴 NEEDS TO BE BUILT**

These endpoints power the Dashboard's "Recent Comments" section and the Video Preview page comments panel.

### `GET /streaming/comments/recent/`

Get the most recent comments across all videos. Used on the Dashboard.

**Query Parameters:**
- `limit` (int, optional, default 10) — number of comments to return

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "user_name": "Amina Rashid",
      "username": "amina_r",
      "user_avatar": "https://...",
      "text": "Great documentary! Very informative.",
      "video_id": 42,
      "video_title": "Serengeti Wildlife",
      "created_at": "2024-01-20T10:30:00Z"
    }
  ]
}
```

**Important:** Each comment must include `video_id` and `video_title` so the Dashboard can link to the respective video preview page.

### `GET /streaming/videos/{videoId}/comments/`

Get all comments for a specific video. Used on the Video Preview page.

**Query Parameters:**
- `page` (int, optional)
- `page_size` (int, optional, default 50)

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "user_name": "Amina Rashid",
      "username": "amina_r",
      "user_avatar": "https://...",
      "text": "Amazing video quality!",
      "created_at": "2024-01-20T10:30:00Z"
    }
  ]
}
```

---

## 14. Video Viewers & Interactions

> **Status: 🔴 NEEDS TO BE BUILT**

These endpoints power the Video Preview page's viewers list and interaction statistics.

### `GET /streaming/videos/{videoId}/viewers/`

Get all users who have watched a specific video, including their individual interactions with it.

**Query Parameters:**
- `page` (int, optional)
- `page_size` (int, optional, default 50)

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "user_id": 10,
      "full_name": "Amina Rashid",
      "username": "amina_r",
      "avatar": "https://...",
      "watched_at": "2024-01-20T10:30:00Z",
      "last_watched": "2024-01-20T10:30:00Z",
      "liked": true,
      "disliked": false,
      "saved": true,
      "downloaded": false,
      "shared": false
    }
  ]
}
```

**Important:** Each viewer entry must include boolean flags for `liked`, `disliked`, `saved`, `downloaded`, `shared` so the CMS can show per-user interaction icons.

### `GET /streaming/videos/{videoId}/interactions/`

Get aggregated interaction counts for a specific video.

**Response:**

```json
{
  "success": true,
  "data": {
    "views_count": 15000,
    "likes_count": 850,
    "dislikes_count": 12,
    "comments_count": 45,
    "saves_count": 230,
    "downloads_count": 180,
    "shares_count": 95
  }
}
```

---

## Summary: What Exists vs. What Needs Building

### ✅ Already Built (No Changes Needed)

| Module | Endpoints |
|--------|-----------|
| Authentication | login, logout, refresh, password reset, finalize account |
| Dashboard | summary, clients-stats, analytics-chart |
| Streaming | categories CRUD, subcategories, videos CRUD, chunked upload, HLS streaming, Google Drive import |
| Carousel Ads | CRUD + filter by render type |
| Interceptor Ads | CRUD + toggle status |

### ⚠️ Already Built — Verify These Fields Exist

| Endpoint | Required Fields |
|----------|----------------|
| `GET /streaming/categories/` | `children_count` on parent categories |
| `GET /streaming/subcategories/{id}/` | `video_count` on each subcategory |
| `GET /streaming/categories/{id}/` | `parent`, `parent_name` for breadcrumb navigation |
| `GET /streaming/get-all-videos/?category={id}` | Must filter by category ID |

### 🔴 Needs to Be Built (New Endpoints)

| # | Module | Endpoints Count | Priority |
|---|--------|----------------|----------|
| 1 | Active Users Today | 1 endpoint | **HIGH** — Dashboard depends on it |
| 2 | App Users Management | 4 endpoints (list, detail, suspend, unsuspend) | **HIGH** — Users page depends on it |
| 3 | Admin Users Management | 4 endpoints (list, create, update, delete) | **HIGH** — Settings page depends on it |
| 4 | Profile | 3 endpoints (get, update, change password) | **HIGH** — Profile page depends on it |
| 5 | Notifications | 3 endpoints (list, mark read, mark all read) | **HIGH** — AppBar depends on it |
| 6 | Reports / Analytics | 3 endpoints (summary, top videos, category performance) | **MEDIUM** — Reports page depends on it |
| 7 | Settings | 2 endpoints (get, update) | **LOW** — Currently mostly display-only |
| 8 | Comments | 2 endpoints (recent, per-video) | **HIGH** — Dashboard + Video Preview depend on it |
| 9 | Video Viewers & Interactions | 2 endpoints (viewers, interactions) | **HIGH** — Video Preview depends on it |

**Total new endpoints to build: 24**

---

## General Response Contract

All responses should follow this pattern (already in use):

```json
{
  "success": true | false,
  "message": "Human-readable message",
  "data": { ... } | [ ... ]
}
```

- The Axios interceptor reads `response.data.success` and `response.data.message` for toast notifications.
- List endpoints should return `data` as an array.
- Detail/create/update endpoints should return `data` as an object.
- Error responses should use appropriate HTTP status codes (400, 401, 403, 404, 500) with `"success": false`.
