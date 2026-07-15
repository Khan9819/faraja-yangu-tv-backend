# Advertising API

Base path: `/advertising/`

All endpoints respond with a consistent envelope via `core.response_wrapper`:
- Success: `{ "success": true, "message": "...", "data": <payload> }`
- Error: `{ "success": false, "message": <error> }`
  - For validation errors, `message` is a field-errors object from DRF.

Authentication:
- All endpoints are protected with `IsAuthenticated`.
- Send `Authorization: Bearer <access_token>`.

---

## Ad model summary
Fields commonly seen in payloads (Model: `apps.advertising.models.Ad`):
- `id` (int)
- `uid` (uuid)
- `created_at` (datetime), `updated_at` (datetime)
- `name` (string, optional)
- `description` (string, optional)
- `slug` (string, optional, unique)
- `type` (string; one of: `BANNER`, `VIDEO`, `CAROUSEL`)
- `ad_render_type` (string; one of: `CUSTOM`, `GOOGLE`)
- `thumbnail` (image URL or null)
- `video` (file URL or null)
- `duration` (string duration, e.g. `"00:00:30"`)
- `uploaded_by` (user id)
- `views_count` (int), `likes_count` (int), `dislikes_count` (int)
- `is_published` (bool)

Note:
- Carousel endpoints below force `type = CAROUSEL` on create.
- Files should be uploaded with `multipart/form-data`.

---

## GET get-carousel-ads
- Path: `GET /advertising/get-carousel-ads/`
- Auth: required
- Query params (optional):
  - `ad_render_type` = `CUSTOM` | `GOOGLE`
- Behavior: returns up to 4 most recent published carousel ads, optionally filtered by `ad_render_type`.

Example request:
```
GET /advertising/get-carousel-ads/?ad_render_type=CUSTOM
Authorization: Bearer <token>
```

Example 200 response:
```json
{
  "success": true,
  "message": "Success",
  "data": [
    {
      "id": 12,
      "uid": "0b2f7c2a-...",
      "name": "Promo Carousel #1",
      "description": "",
      "slug": "promo-carousel-1",
      "type": "CAROUSEL",
      "ad_render_type": "CUSTOM",
      "thumbnail": "https://.../ads/thumb.jpg",
      "video": null,
      "duration": "00:00:15",
      "uploaded_by": 3,
      "views_count": 1200,
      "likes_count": 45,
      "dislikes_count": 2,
      "is_published": true,
      "created_at": "2025-11-16T10:00:00Z",
      "updated_at": "2025-11-16T12:00:00Z"
    }
  ]
}
```

---

## POST create-carousel-ad
- Path: `POST /advertising/create-carousel-ad/`
- Auth: required
- Content-Type: `multipart/form-data` (recommended when sending `thumbnail`/`video`)
- Notes:
  - Server sets `type = CAROUSEL` and `uploaded_by = current_user.id`.
  - Send only fields you need; unspecified optional fields default to null/false.

Example request (multipart):
```
POST /advertising/create-carousel-ad/
Authorization: Bearer <token>
Content-Type: multipart/form-data

name=New Carousel Ad
ad_render_type=CUSTOM
is_published=true
thumbnail=@/path/to/thumb.jpg
video=@/path/to/clip.mp4
duration=00:00:30
```

Example 200 response:
```json
{
  "success": true,
  "message": "Carousel ad created successfully",
  "data": {
    "id": 25,
    "uid": "f8b1...",
    "name": "New Carousel Ad",
    "description": null,
    "slug": null,
    "type": "CAROUSEL",
    "ad_render_type": "CUSTOM",
    "thumbnail": "https://.../ads/25-thumb.jpg",
    "video": "https://.../ads/25.mp4",
    "duration": "00:00:30",
    "uploaded_by": 7,
    "views_count": 0,
    "likes_count": 0,
    "dislikes_count": 0,
    "is_published": true,
    "created_at": "2025-11-17T07:00:00Z",
    "updated_at": "2025-11-17T07:00:00Z"
  }
}
```

Example 400 response (validation errors):
```json
{
  "success": false,
  "message": {
    "name": ["This field may not be blank."],
    "ad_render_type": ["\"X\" is not a valid choice."]
  }
}
```

---

## PUT/PATCH update-carousel-ad
- Path: `PUT /advertising/update-carousel-ad/{id}/`
- Path: `PATCH /advertising/update-carousel-ad/{id}/`
- Auth: required
- Content-Type: `application/json` or `multipart/form-data`
- Notes:
  - Partial updates allowed with `PATCH`.
  - Resource must exist and be of type `CAROUSEL`.

Example request (PATCH):
```http
PATCH /advertising/update-carousel-ad/25/
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Updated Carousel Ad",
  "is_published": false
}
```

Example 200 response:
```json
{
  "success": true,
  "message": "Carousel ad updated successfully",
  "data": { /* updated Ad object */ }
}
```

Example 404 response:
```json
{
  "success": false,
  "message": "Carousel ad not found"
}
```

Example 400 response (validation):
```json
{
  "success": false,
  "message": { "name": ["Ensure this field has at least 3 characters."] }
}
```

---

## DELETE delete-carousel-ad
- Path: `DELETE /advertising/delete-carousel-ad/{id}/`
- Auth: required

Example 200 response:
```json
{
  "success": true,
  "message": "Carousel ad deleted successfully",
  "data": null
}
```

Example 404 response:
```json
{
  "success": false,
  "message": "Carousel ad not found"
}
```

---

## Curl examples

Get carousel ads (custom-rendered):
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/advertising/get-carousel-ads/?ad_render_type=CUSTOM"
```

Create a carousel ad (multipart):
```bash
curl -X POST "$BASE_URL/advertising/create-carousel-ad/" \
  -H "Authorization: Bearer $TOKEN" \
  -F name="Homepage Carousel" \
  -F ad_render_type="CUSTOM" \
  -F is_published=true \
  -F thumbnail=@thumb.jpg \
  -F video=@ad.mp4 \
  -F duration="00:00:30"
```

Update a carousel ad:
```bash
curl -X PATCH "$BASE_URL/advertising/update-carousel-ad/25/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_published": false}'
```

Delete a carousel ad:
```bash
curl -X DELETE "$BASE_URL/advertising/delete-carousel-ad/25/" \
  -H "Authorization: Bearer $TOKEN"
```
