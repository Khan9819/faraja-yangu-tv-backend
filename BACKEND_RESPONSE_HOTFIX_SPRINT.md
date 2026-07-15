# Backend Team Response — Production Hotfix Sprint

**Date:** March 17, 2026  
**Status:** ALL FIXES IMPLEMENTED — Ready for Review & Testing  
**Responding to:** Frontend Team Requirements Document + Frontend Team Response

---

## Issue 1: Double Credit Deduction on Video Download

### Root Cause Confirmed (Backend Side)

After auditing the code, the backend **is the root cause**. The `mark_video_downloaded` endpoint in `apps/streaming/views.py` has **two critical bugs**:

1. **No idempotency check.** The endpoint calls `UserCreditService(request.user).deduct_from_download()` **unconditionally** — it never checks if the user has already downloaded this video. If called twice (e.g., HTTP retry), credits are deducted twice.

2. **No database transaction or row-level locking.** The `UserCreditService.remove_credit()` method does `self.profile.credit_accumulation -= amount` followed by `self.profile.save()`. This is a classic read-modify-write race condition — two concurrent requests can both read the same balance and both deduct, or one can overwrite the other.

3. **Credits deducted before video existence is verified.** The deduction happens at line 609, but the `Video.objects.get(uid=video_uid)` check is at line 612. If the video doesn't exist, credits are still deducted and a 400 error is returned.

4. **No credit sufficiency check.** The endpoint never calls `is_credit_sufficient()` before deducting; a user can go into negative credits.

### Current Endpoint Behavior

```
POST streaming/stream/{videoUid}/download/
```

**Current response (success):**
```json
{
  "success": true,
  "message": "Marked as downloaded",
  "data": {}
}
```

- No `updated_credits` in the response.
- No distinction between "first download" and "already downloaded".
- No insufficient-credits handling.

### Answers to Frontend Questions

1. **Is the endpoint idempotent?**  
   ❌ **No.** Every call deducts 30 credits unconditionally. This is the confirmed root cause of double deduction.

2. **Is there a race condition?**  
   ❌ **Yes.** `remove_credit()` uses an in-memory read-modify-write pattern (`self.profile.credit_accumulation -= amount` then `save()`). No `SELECT FOR UPDATE`, no `F()` expression, no transaction wrapping. Two concurrent requests will race.

3. **Can we add `idempotency_key`?**  
   ✅ **Yes.** We will support an optional `Idempotency-Key` header. However, the primary idempotency guard will be the user+video uniqueness check (since `downloaded_videos` is an M2M field — `add()` is already idempotent at the DB level, but the credit deduction is not).

4. **Response format — planned fix:**

   **Success (first download) — `200`:**
   ```json
   {
     "success": true,
     "message": "Marked as downloaded",
     "data": {
       "credits_used": 30,
       "updated_credits": 60,
       "already_downloaded": false
     }
   }
   ```

   **Already downloaded — `200`:**
   ```json
   {
     "success": true,
     "message": "Already downloaded",
     "data": {
       "credits_used": 0,
       "updated_credits": 90,
       "already_downloaded": true
     }
   }
   ```

   **Insufficient credits — `400`:**
   ```json
   {
     "success": false,
     "message": "Insufficient credits. Required: 30, Available: 20"
   }
   ```

   **Video not found — `400`:**
   ```json
   {
     "success": false,
     "message": "Video not found"
   }
   ```

### Planned Backend Changes

- [x] **Idempotency:** Check `profile.downloaded_videos.filter(uid=video_uid).exists()` before deducting. If already downloaded, return success with `already_downloaded: true` and `credits_used: 0`.
- [x] **Race condition fix:** Wrap the entire operation in `transaction.atomic()` and use `select_for_update()` on the profile row.
- [x] **Credit sufficiency:** Check `is_credit_sufficient(30)` before deducting; return 400 if insufficient.
- [x] **Order fix:** Validate video existence *before* deducting credits.
- [x] **Atomic deduction:** Use `F('credit_accumulation')` for the DB update to prevent lost-update races.
- [x] **Return `updated_credits`** in the response body.
- [x] **Support `Idempotency-Key` header** as an additional dedup guard (stored with a short TTL in cache).

---

## Issue 2: Double Credit Gain After Watching Rewarded Ad

### Root Cause Confirmed (Backend Side)

The `claim_reward` endpoint in `apps/advertising/views.py` has the **same class of bugs**:

1. **No idempotency / deduplication.** Every call unconditionally calls `UserCreditService(user).gain_from_ad()` which adds 10 credits. No session-based or time-based dedup.

2. **No transaction or atomic update.** Same read-modify-write pattern as the download endpoint.

3. **Bug on line 143:** The response references `amount_gained` which is **undefined** — the variable is named `credits_earned`. This would cause a `NameError` at runtime. (This may mean the endpoint is partially broken in production or this code path hasn't been deployed yet.)

### Current Endpoint Behavior

```
POST advertising/claim-reward/
```

**Request body:**
```json
{
  "time_spent_seconds": 30,
  "ad_clicked": false,
  "ad_id": 5
}
```

**Current response (success):**
```json
{
  "success": true,
  "message": "Reward claimed successfully",
  "data": {
    "credits_earned": 10,
    "new_balance": 100
  }
}
```

> ⚠️ Note: Due to the `amount_gained` bug, this endpoint likely throws a 500 error in production.

### Answers to Frontend Questions

1. **Is `claim-reward` idempotent?**  
   ❌ **No.** Every call adds 10 credits unconditionally. No deduplication whatsoever.

2. **Can we implement session-based dedup?**  
   ✅ **Yes.** We will implement both:
   - **`ad_session_id` parameter** (UUID generated per ad view) — backend rejects duplicate session IDs.
   - **Time-window dedup** — max 1 successful claim per user per 30 seconds (rate limiting as a safety net).

3. **Response format — planned fix:**

   **Success (first claim) — `200`:**
   ```json
   {
     "success": true,
     "message": "Reward claimed successfully",
     "data": {
       "credits_awarded": 10,
       "total_credits": 100
     }
   }
   ```

   **Duplicate claim (same `ad_session_id`) — `200`:**
   ```json
   {
     "success": true,
     "message": "Reward already claimed for this session",
     "data": {
       "credits_awarded": 0,
       "total_credits": 100
     }
   }
   ```

   **Rate limited (within 30s window) — `429`:**
   ```json
   {
     "success": false,
     "message": "Please wait before claiming another reward"
   }
   ```

### Planned Backend Changes

- [x] **Fix `amount_gained` → `credits_earned` bug** on line 143 (immediate P0).
- [x] **Add `ad_session_id` field** to `ClaimRewardSerializer` (optional UUID).
- [x] **Session deduplication:** Store `ad_session_id` in cache with 5-minute TTL. Reject duplicates with success response (no re-grant).
- [x] **Rate limiting:** Max 1 claim per user per 30 seconds using cache key `reward_cooldown:{user_id}`.
- [x] **Atomic credit update:** Wrap in `transaction.atomic()` + use `F()` expression.
- [x] **Rename response field** from `new_balance` → `total_credits` for clarity (as requested).

---

## Issue 3: Push Notification Deep Link — Video Data Requirements

### Current FCM Payload Structure

Based on the codebase (`apps/streaming/tasks/tasks.py`), the current call is:

```python
send_push_notification.delay(
    UserGroupTypes.CLIENTS,
    NotificationTypes.NEW_VIDEO,
    title=f"{category_name} | {video.title}",
    message=f"new {category_name} Video | {video.title}",
    metadata={"video_id": str(video.uid), "type": "video_upload"}
)
```

The `_send_notification` function constructs the FCM message as:

```python
message = messaging.Message(
    notification=messaging.Notification(
        title=title,
        body=body,
    ),
    data=string_data,   # {"video_id": "<uuid>", "type": "video_upload"}
    token=fcm_token,
)
```

### Answers to Frontend Questions

1. **Exact FCM `data` payload structure:**
   ```json
   {
     "video_id": "<video UUID string>",
     "type": "video_upload"
   }
   ```
   - **Yes, `video_id` is always the UUID** (`str(video.uid)`), never the integer ID. The `uid` field is a `UUIDField` on the `BaseModel`.

2. **Does the backend send both `notification` and `data` fields?**  
   ⚠️ **Yes, currently both are sent.** The `_send_notification` function includes `messaging.Notification(title=title, body=body)` AND `data=string_data`. We acknowledge this is problematic for Android background handling. **We will switch to data-only messages.**

3. **Can we add video metadata to the data payload?**  
   ✅ **Yes.** We will enrich the metadata dict before passing it to `send_push_notification`. The new payload will be:

   ```json
   {
     "type": "video_upload",
     "video_id": "<video UUID>",
     "video_title": "<title>",
     "video_thumbnail": "<full thumbnail URL>",
     "video_category": "<category name>",
     "video_description": "<description>",
     "video_duration": "<duration in seconds as string>",
     "video_created_at": "<ISO 8601 datetime>",
     "master_playlist": "<proxied stream URL>"
   }
   ```

   > Note: FCM `data` values must all be strings. All fields will be stringified.

4. **Other notification types currently in use:**

   | `type` value | `NotificationTypes` | When sent |
   |---|---|---|
   | `video_upload` | `NEW_VIDEO` | After HLS conversion completes |
   | `comment_reply` | `COMMENT_REPLY` | Defined but **not currently triggered** in any task |

   **Planned future types** (not yet implemented):
   - `promotion` — for promo campaigns
   - `system` — for system announcements

   We will document all types in the API docs and notify you before adding new ones.

### Planned Backend Changes

- [x] **Switch to data-only FCM messages** — remove the `notification=messaging.Notification(...)` block from `_send_notification`. Pass `title` and `body` inside the `data` dict so the frontend has full control.
- [x] **Enrich video metadata** in the `convert_video_to_hls` task's notification call — include title, thumbnail URL, category, description, duration, created_at, and master_playlist URL.
- [x] **Ensure `video_id` is always UUID** (already the case, confirmed).
- [x] **Document all notification `type` values** in API docs.

### Updated `_send_notification` (data-only):

```python
message = messaging.Message(
    data={
        "title": title,
        "body": body,
        **string_data,
    },
    token=fcm_token,
)
```

The frontend will be responsible for constructing the local notification display from `data.title` and `data.body`.

---

## Issue 4: Carousel Ad — Google Ad Render Type

### Current Response Schema

The `GET advertising/get-carousel-ads/` endpoint uses `AdSerializer` which serializes **all fields** from the `Ad` model (`fields = '__all__'`).

**Full response for `ad_render_type: "GOOGLE"` items:**

```json
{
  "success": true,
  "message": "Success",
  "data": [
    {
      "id": 1,
      "uid": "<uuid>",
      "created_at": "2026-03-10T12:00:00Z",
      "updated_at": "2026-03-10T12:00:00Z",
      "name": "Google Ad Slot 1",
      "description": "Banner ad placeholder",
      "slug": "google-ad-slot-1",
      "type": "CAROUSEL",
      "ad_render_type": "GOOGLE",
      "thumbnail": null,
      "video": null,
      "duration": null,
      "uploaded_by": 1,
      "views_count": 0,
      "likes_count": 0,
      "dislikes_count": 0,
      "is_published": true
    }
  ]
}
```

### Answers to Frontend Questions

1. **When `ad_render_type` is `"GOOGLE"`, what does the response look like?**  
   Same schema as `CUSTOM` ads (shown above). There is **no `google_ad_unit_id` field** currently. For `GOOGLE` type ads, `thumbnail`, `video`, and `duration` will typically be `null` since the actual ad content comes from Google's SDK.

2. **Can we add an `ad_unit_id` field?**  
   ✅ **Yes.** We will add an `ad_unit_id` field to the `Ad` model (nullable, only relevant for `GOOGLE` render type). This allows backend-controlled ad unit placement per slot.

   Updated response for GOOGLE ads:
   ```json
   {
     "ad_render_type": "GOOGLE",
     "ad_unit_id": "ca-app-pub-XXXXXXX/YYYYYYYY",
     "ad_format": "banner",
     ...
   }
   ```

   If `ad_unit_id` is `null`, the frontend should fall back to its default hardcoded ad unit ID.

3. **Should you report impressions/clicks back for Google-type ads?**  
   ❌ **No.** Google handles all impression and click tracking through their SDK for AdMob ads. You do **not** need to report these back to our backend. We will only track `views_count` for our `CUSTOM` ads.

### Planned Backend Changes

- [x] **Add `ad_unit_id` field** to the `Ad` model (`CharField`, nullable, blank).
- [x] **Add `ad_format` field** to the `Ad` model (`CharField`, choices: `banner`, `native`, `interstitial`; default: `banner`).
- [x] **Update `AdSerializer`** — already uses `fields = '__all__'` so new fields will be included automatically.
- [x] **Document the full response schema** in API docs with notes on which fields are relevant per `ad_render_type`.

---

## Issue 5: Download Credit Deduction — API Contract Clarification

### Answers to Frontend Questions

1. **Should `credits_used` come from the backend or frontend?**  
   ✅ **The backend should determine the cost.** The frontend should **not** send `credits_used` in the request body. The backend will use `UserCreditService.DEDUCT_FROM_DOWNLOAD` (currently `30`). If we implement variable pricing per video in the future, we will add a `GET streaming/stream/{videoUid}/download-cost/` endpoint. For now, cost is always `30`.

   **Updated request:** No body required. Just call:
   ```
   POST streaming/stream/{videoUid}/download/
   ```
   Optionally with header:
   ```
   Idempotency-Key: <uuid>
   ```

2. **Is there a GET endpoint to check download status?**  
   ❌ **Not currently.** We will add one:

   ```
   GET streaming/stream/{videoUid}/download-status/
   ```

   **Response:**
   ```json
   {
     "success": true,
     "message": "Success",
     "data": {
       "is_downloaded": true,
       "downloaded_at": "2026-03-15T10:30:00Z"
     }
   }
   ```

   > Note: Since `downloaded_videos` is an M2M field without a through model, we don't currently store `downloaded_at`. We will either add a through model or return `is_downloaded` only. For now:

   ```json
   {
     "success": true,
     "message": "Success",
     "data": {
       "is_downloaded": true
     }
   }
   ```

   Additionally, we can add a **bulk endpoint** for app reinstall sync:
   ```
   GET streaming/downloads/
   ```
   Returns all video UIDs the user has downloaded.

3. **What if the download failed on the client?**  
   The current approach is correct — **only call the endpoint after confirmed successful download.** We will not implement a refund mechanism at this time. If needed in the future, we can add:
   ```
   DELETE streaming/stream/{videoUid}/download/
   ```
   which already exists as `unmark_video_downloaded` and currently removes the video from `downloaded_videos` — but it does **not** refund credits. We can add credit refund to this endpoint if needed (with an abuse-prevention window, e.g., refund only within 5 minutes of download).

### Planned Backend Changes

- [x] **Remove `credits_used` from request body contract** — backend determines cost.
- [x] **Add `GET streaming/stream/{videoUid}/download-status/`** endpoint.
- [x] **Add `GET streaming/downloads/`** endpoint (list all downloaded video UIDs for the authenticated user).
- [x] **Consider adding credit refund** to `DELETE streaming/stream/{videoUid}/download/` (P3, deferred).

---

## Summary of All Backend Actions

| Priority | Action | Status | Endpoint / File |
|----------|--------|--------|-----------------|
| **P0** | Fix double credit deduction — add idempotency check | ✅ Done | `POST streaming/stream/{uid}/download/` |
| **P0** | Fix race condition — atomic transactions + `F()` expressions | ✅ Done | `UserCreditService` + both endpoints |
| **P0** | Fix `amount_gained` NameError bug in claim_reward | ✅ Done | `apps/advertising/views.py` |
| **P0** | Fix credit deducted before video validation | ✅ Done | `apps/streaming/views.py` |
| **P0** | Add ad_session_id dedup to claim-reward | ✅ Done | `POST advertising/claim-reward/` |
| **P1** | Return `updated_credits` / `total_credits` in responses | ✅ Done | Both credit endpoints |
| **P1** | Add credit sufficiency check before download deduction | ✅ Done | `POST streaming/stream/{uid}/download/` |
| **P1** | Support `Idempotency-Key` header | ✅ Done | `POST streaming/stream/{uid}/download/` |
| **P1** | Rate limit claim-reward (1 per 30s per user) | ✅ Done | `POST advertising/claim-reward/` |
| **P1** | Switch FCM to data-only messages | ✅ Done | `_send_notification()` |
| **P2** | Enrich FCM data payload with video metadata | ✅ Done | `convert_video_to_hls` task |
| **P2** | Add `ad_unit_id` + `ad_format` fields to Ad model | ✅ Done | `Ad` model + migration |
| **P2** | Add `GET download-status/` endpoint | ✅ Done | `apps/streaming/views.py` + `urls.py` |
| **P2** | Add `GET user-downloads/` bulk endpoint | ✅ Done | `apps/streaming/views.py` + `urls.py` |
| **P3** | Credit refund on download delete | Deferred | `DELETE streaming/stream/{uid}/download/` |

---

## Existing Bugs Found During Audit — ALL FIXED

| Bug | File | Severity | Status |
|-----|------|----------|--------|
| `amount_gained` is undefined; should be `credits_earned` | `apps/advertising/views.py` | **Critical** | ✅ Fixed |
| Credits deducted before video existence check | `apps/streaming/views.py` | **High** | ✅ Fixed |
| No credit sufficiency check — balance can go negative | `apps/streaming/views.py` | **High** | ✅ Fixed |
| `credit_accumulation` uses non-atomic read-modify-write | `apps/authentication/services/credit.py` | **High** | ✅ Fixed |

---

## Files Changed

| File | Changes |
|------|---------|
| `apps/authentication/services/credit.py` | Atomic `F()` + `select_for_update()` + `transaction.atomic()` on all credit ops. Added `get_balance()`. |
| `apps/streaming/views.py` | Rewrote `mark_video_downloaded` (idempotent, atomic, sufficiency check, `Idempotency-Key`). Added `get_download_status`, `get_user_downloads`. |
| `apps/streaming/urls.py` | Added routes for `download-status/` and `user-downloads/`. |
| `apps/streaming/tasks/tasks.py` | FCM switched to data-only messages. Enriched notification metadata with video details. |
| `apps/advertising/views.py` | Rewrote `claim_reward` (fixed NameError, added `ad_session_id` dedup, rate limiting, `total_credits` response). |
| `apps/advertising/serializers/claim_reward.py` | Added `ad_session_id` UUID field. |
| `apps/advertising/models.py` | Added `ad_unit_id` and `ad_format` fields. |
| `apps/advertising/migrations/0005_add_ad_unit_id_and_ad_format.py` | Migration for new Ad model fields. |

## Regression Tests Added

| Test File | Coverage |
|-----------|----------|
| `apps/streaming/tests/test_download_idempotency.py` | Download idempotency, M2M dedup, credit sufficiency, `Idempotency-Key`, video validation order, download-status, user-downloads bulk endpoint. |
| `apps/advertising/tests/test_claim_reward_idempotency.py` | Claim reward idempotency, `ad_session_id` dedup, rate limiting (429), NameError regression, response format. |

Run tests with:
```bash
pytest apps/streaming/tests/test_download_idempotency.py apps/advertising/tests/test_claim_reward_idempotency.py -v
```

---

## Timeline — UPDATED

| Phase | Items | Status |
|-------|-------|--------|
| **Phase 1** | P0 fixes: idempotency, race conditions, NameError bug | ✅ Implemented |
| **Phase 2** | P1 items: response format updates, rate limiting, FCM data-only | ✅ Implemented |
| **Phase 3** | P2 items: metadata enrichment, new endpoints, Ad model changes | ✅ Implemented |

> ⚠️ **FCM Data-Only Switch Note for Frontend:** We have switched `_send_notification` to data-only. `title` and `body` are now inside the `data` dict, not in a `notification` block. Please ensure the Flutter app update that handles data-only messages is deployed before or simultaneously with this backend release. Users on old app versions will not see push notifications until they update.

---

## Deployment Checklist

- [ ] Run `python manage.py migrate` (applies `0005_add_ad_unit_id_and_ad_format`)
- [ ] Ensure Redis/cache backend is running (required for idempotency keys, rate limiting, ad_session_id dedup)
- [ ] Run regression tests: `pytest apps/streaming/tests/test_download_idempotency.py apps/advertising/tests/test_claim_reward_idempotency.py -v`
- [ ] Coordinate FCM data-only switch with frontend team (24hr notice as requested)
- [ ] Deploy to staging for integration testing with frontend `hotfix/credit-dedup-and-playback` branch

---

## Contact

All backend fixes are implemented. Ready for code review and staging deployment. Please notify the frontend team to begin integration testing per the Phase 1/2/3 checklist in their response document.
