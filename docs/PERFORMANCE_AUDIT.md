# Faraja Yangu TV Backend – Performance Audit

Last updated: 2025-12-19

This document summarizes performance bottlenecks identified across API views and proposes concrete optimizations. The goal is to reduce tail latencies, improve throughput under load, and eliminate unnecessary I/O and database work while keeping code maintainable.

---

## Scope

- Apps reviewed: authentication, streaming, analytics, advertising, profile, management
- Layers considered: view logic, queryset usage, serialization, caching opportunities, background jobs, storage I/O

---

## Executive Summary

- **Cross-cutting bottlenecks**: synchronous DB work in request path (counters and device sync), repeated COUNT() calls, expensive list endpoints without cursor pagination, no/limited caching for hot endpoints (feed, categories, carousel ads, HLS playlist rewriting), and multi-query patterns lacking `select_related`/`prefetch_related` in a few places.
- **Quick wins**: offload non-critical writes to Celery, switch to `F()` counters, cache hot queries, and adopt cursor pagination. These changes yield noticeable p95/p99 improvements with minimal risk.

---

## Cross-Cutting Recommendations

- **Caching (Redis)**
  - Cache hot reads for 30–120s: feed pages, category lists, carousel ads, video detail side payloads, and modified HLS playlists (see streaming/stream_hls).
  - Use cache keys with parameters and small TTLs to keep data fresh. Example: `feed:{page}:{page_size}`.

- **Denormalized Counters with F()**
  - Replace `COUNT()` recalculations after create/delete with atomic `F()` increments/decrements on `views_count`, `likes_count`, `dislikes_count`.
  - Periodic Celery job can reconcile counters overnight to correct any drift.

- **Pagination Defaults**
  - Use DRF CursorPagination (time/created_at based) for scrolling lists (feed, search, comments, playlists). Cap max page size (e.g., 50).

- **Query Optimization**
  - Ensure appropriate `.select_related()` and `.prefetch_related()` for foreign key and M2M reads in list/detail endpoints.
  - Use `.only()`/`.defer()` to reduce payload for list views when serializers don’t need all fields.

- **DB Indexes**
  - Add/confirm indexes on common filters, orderings:
    - `Video(is_published, processing_status, created_at)` (composite)
    - `View(video_id, created_at)`, `Like(video_id, user_id)`, `Dislike(video_id, user_id)` (unique constraint and indexes)
    - `Notification(user_id, created_at, is_read)`
    - `Comment(video_id, created_at, reply_to_id)`
    - `Devices(device_id)` unique or indexed
    - `Category(parent_id)`

- **Search**
  - For `icontains`-heavy search, prefer PostgreSQL trigram/FTS (pg_trgm or SearchVector). If not feasible now, at minimum cap page size and ensure filterable fields are indexed.

- **Background Jobs**
  - Offload any non-critical side effects (device sync, analytics tracking, notification fanout, recomputations) to Celery. Keep request path read-focused.

---

## App-by-App Findings and Recommendations

### 1) Authentication

- **refresh()**
  - Status: Optimized. Device sync offloaded to Celery (`sync_user_device`). Response now returns immediately.
  - Further: Consider rate-limiting refresh to protect Redis/DB under token churn.

- **login()**
  - Return `roles` efficiently. If roles are few this is fine; otherwise, annotate a minimal representation or cache for a short TTL.
  - Optional: If device metadata is posted during login, dispatch the same background `sync_user_device` task there too.

- **OTP flows**
  - Use DB index on `OTP(expires_at)` to accelerate expiry checks and cleanups.
  - Add throttling (DRF throttling) for resend endpoints; already guarded by 60s check—enforce via cache/rate limit too.

- **Profile reads in auth views**
  - Prefer `request.user` over refetching `User` by id. Avoid mutating state (e.g., creating profile) in `GET` endpoints (move to registration signal).

### 2) Profile

- **profile() [apps/profile/views.py]**
  - Currently creates a profile on `GET` if missing. Move profile creation to user registration (or `post_save` signal) to keep GET idempotent and fast.
  - Use `.select_related()` if the serializer needs nested fields that would trigger extra queries.

- **profile_update() / upload_profile()**
  - Fine for now. Ensure serializers restrict fields and validate file sizes to avoid large uploads in request path.

### 3) Streaming

- **Feed and Lists**
  - `get_feed()`: Good use of `select_related('category','category__parent')` and pagination. Add:
    - Cache each page for 30–60s.
    - Use `.only()` to limit fields for the list serializer.
    - Move ad segment selection to a helper and cache it separately.
  - `history_list()`, `favorites_list()`, `downloads_list()`:
    - Use CursorPagination.
    - Add `.only()` for video fields needed by list serializers.

- **Search**
  - `search_videos()`: Uses multiple `icontains`. Add composite index and cap `count` (e.g., max 50). Medium term: migrate to trigram/FTS.

- **Counters**
  - `record_view_stream()`, `video_like_stream()`, `video_dislike_stream()` patterns do a create/delete followed by `COUNT()` for totals. Replace with atomic `F()` updates on the denormalized counters and schedule a nightly reconciliation Celery task.
  - Ensure unique constraints on (video, user) for like/dislike to prevent duplicates.

- **Comments**
  - For comment and reply lists, add indexes and cursor pagination. If showing user data, `select_related('user')` to avoid N+1.

- **HLS Streaming (`stream_hls`)**
  - For `.m3u8` files, ad-marker injection reads and transforms text every request.
    - Cache modified playlists per `(video_slug, file_path)` for 60–120s.
    - Optionally include an “ad model last-updated” hash in the cache key for invalidation on ad changes.
  - For `.ts` segments, prefer `FileResponse` (streaming) and set appropriate headers. Consider enabling range requests if needed by players (S3 does this natively if proxying directly).
  - Avoid repeated `default_storage.exists()` by caching existence results briefly.

- **Chunk Upload**
  - Current approach avoids `listdir()` on S3 (good). Optionally:
    - Validate chunk integrity (e.g., Content-MD5) to avoid corrupt uploads.
    - Keep assembly fully async (already done) and emit progress via WebSockets (already supported in architecture).

- **create_video()**
  - Ensure `convert_video_to_hls.delay(video.id)` is enabled in production (commented out in code). Keep conversion fully async and surface progress via sockets.

### 4) Advertising

- **get_carousel_ads()**
  - Cache the list (separate keys per `ad_render_type`) for 60s. Use `.only(id, name, slug, type, thumbnail, video, duration)` to reduce payload size.

- **claim_reward()**
  - Replace `profile.credit_accumulation += credits_earned` with atomic `F('credit_accumulation') + credits_earned` update.
  - Offload ad view/click tracking to Celery where feasible. If strong consistency is required, use a transaction with `select_for_update()` to avoid contention.

### 5) Analytics

- **list_notifications()**
  - Add index on `(user_id, created_at, is_read)`. Consider cursor pagination.
  - Cap `page_size` (e.g., max 50).

- **mark_all_notifications_read()**
  - `.update()` is efficient; for very large sets, consider a background job if it becomes slow, but fine as-is for normal usage.

### 6) Management

- **get_dashboard_summary()**
  - Many `COUNT()` and `DISTINCT` aggregations across large tables will be expensive under load.
  - Recommendations:
    - Cache the full response for 30–60s (keyed by current day) to collapse load during dashboard refreshes.
    - Precompute daily aggregates via scheduled Celery tasks into a small metrics table (e.g., daily views, likes, comments, watch_time). The view can then read from the pre-aggregates + a small “today” delta, dramatically reducing query cost.
    - Replace role filtering by ID with semantic filtering by name (ensure proper indices). Example: `User.objects.filter(roles__name='USER')` and index `Role.name`.

---

## Implementation Checklist (Prioritized)

- **Quick Wins (same-day)**
  - Cache: feed pages, category lists, carousel ads (TTL 30–60s).
  - Counters: switch to `F()` increments/decrements in like/dislike/view endpoints.
  - Pagination: adopt CursorPagination on heavy lists and cap page size.
  - HLS: cache modified playlists for 60–120s.

- **Near Term (1–3 days)**
  - Add/confirm DB indexes listed above; add unique constraints for like/dislike.
  - Move profile creation to registration flow or `post_save` signal.
  - Search: introduce a capped page size and consider basic trigram index.

- **Medium Term (1–2 weeks)**
  - Precompute dashboard aggregates into a metrics table with Celery.
  - Optional: introduce more granular caching strategy (cache invalidation on model changes via signals).
  - Optional: adopt PostgreSQL FTS/trigram and search views using `SearchVector`.

---

## Example Patterns

- **Atomic Counter Update**

```python
from django.db.models import F
Video.objects.filter(id=video.id).update(views_count=F('views_count') + 1)
```

- **Cache Wrapper**

```python
from django.core.cache import cache
key = f"feed:{page}:{page_size}"
data = cache.get(key)
if data is None:
    data = expensive_query()
    cache.set(key, data, timeout=60)
return data
```

- **Background Device Sync (already implemented)**

```python
# In view
sync_user_device.delay(user_id, device_id, device_type, app_version, fcm_token)
```

- **Cursor Pagination (DRF)**

```python
# settings
REST_FRAMEWORK = {
  'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.CursorPagination',
  'PAGE_SIZE': 20,
}
```

---

## Risks and Mitigations

- **Cache Staleness**: Keep TTLs short, key by parameters, and cache only read-mostly data.
- **Counter Drift**: Reconcile nightly from source-of-truth tables.
- **Search Accuracy**: If moving to FTS/trigram, review ranking and language config.

---

## Conclusion

By adopting short-lived caching on hot read endpoints, replacing recalculated counts with atomic counters, using cursor pagination, and offloading non-critical writes to Celery, we can significantly improve API responsiveness and resilience under load. The proposed changes are incremental, low-risk, and align well with the current architecture.
