# Interceptor Ads API

Interceptor ads (VideoAdSlots) define time slots within videos where ad breaks should occur. The frontend uses these slots to pause video playback and display ads at the configured times.

---

## Endpoints

### 1. GET `/management/interceptor/ads/`

**Purpose:** List all interceptor ads

#### Headers
| Header | Value | Required |
|--------|-------|----------|
| Authorization | Bearer `<token>` | Yes |

#### Response

```json
{
  "success": true,
  "message": "Success",
  "data": [
    {
      "id": 1,
      "video": {
        "id": 10,
        "title": "Sample Video",
        "thumbnail": "https://...",
        "duration": 3600
      },
      "start_time": "00:05:00",
      "end_time": "00:05:30",
      "created_at": "2025-12-01T10:00:00Z"
    }
  ]
}
```

---

### 2. POST `/management/interceptor/ads/create/`

**Purpose:** Create a new interceptor ad

#### Headers
| Header | Value | Required |
|--------|-------|----------|
| Authorization | Bearer `<token>` | Yes |
| Content-Type | application/json | Yes |

#### Payload

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| video | integer | No | ID of a specific video this ad is pinned to. **Omit for "All Videos" (global)** |
| categories | integer[] | No | Category IDs to target. **Omit / send empty for "All Videos" (global)**. Applies to videos in the selected categories (including their subcategories) |
| start_time | string | Yes | When ad slot starts (format: `HH:MM:SS`) |
| end_time | string | Yes | When ad slot ends (format: `HH:MM:SS`) |

**Targeting rules:**
- `video` set → ad shows only on that video.
- `video` empty + no `categories` → ad shows on **all videos** (global).
- `video` empty + `categories` set → ad shows on videos whose category (or parent category) is in the list.
- For multipart/form-data, send each category id as a repeated `categories` field (e.g. `categories=1&categories=2`), or a single empty `categories` value to clear targeting.

#### Example Request (global)

```json
{
  "start_time": "00:05:00",
  "end_time": "00:05:30"
}
```

#### Example Request (category targeted)

```json
{
  "categories": [3, 7],
  "start_time": "00:05:00",
  "end_time": "00:05:30"
}
```

#### Success Response

```json
{
  "success": true,
  "message": "Interceptor ad created successfully",
  "data": {
    "id": 1,
    "video": 10,
    "start_time": "00:05:00",
    "end_time": "00:05:30",
    "created_at": "2025-12-01T10:00:00Z"
  }
}
```

#### Error Response (Validation)

```json
{
  "success": false,
  "message": {
    "end_time": ["End time must be after start time."]
  }
}
```

---

### 3. DELETE `/management/interceptor/ads/{id}/`

**Purpose:** Delete an interceptor ad

#### Headers
| Header | Value | Required |
|--------|-------|----------|
| Authorization | Bearer `<token>` | Yes |

#### URL Parameters
- `id` - The interceptor ad ID to delete

#### Success Response

```json
{
  "success": true,
  "message": "Interceptor ad deleted successfully",
  "data": null
}
```

#### Error Response (Not Found)

```json
{
  "success": false,
  "message": "Interceptor ad not found"
}
```

---

## Validation Rules

The backend validates:
- **Video ID exists** - Returns error if video not found
- **Time format** - Must be valid `HH:MM:SS` format
- **End time > Start time** - End time must be after start time
- **Times within video duration** - If video has duration set, times cannot exceed it

---

## Frontend Flow

```
User opens Create Interceptor Ad page
           │
           ▼
    ┌──────────────────┐
    │ Choose video     │
    │ source           │
    └──────────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐ ┌─────────────┐
│ Upload  │ │ Select      │
│ new     │ │ existing    │
└─────────┘ └─────────────┘
     │           │
     ▼           │
POST /streaming/ │
create-video/    │
     │           │
     ▼           ▼
Get video ID ◄───┘
     │
     ▼
POST /management/interceptor/ads/create/
{
  "video": <video_id>,
  "start_time": "HH:MM:SS",
  "end_time": "HH:MM:SS"
}
     │
     ▼
Redirect to list page
```

---

## Model Structure

### VideoAdSlot

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| uid | UUIDField | Unique identifier (from BaseModel) |
| video | ForeignKey | Reference to a specific Video (nullable = global/All Videos) |
| ad | ForeignKey | Optional reference to Ad model |
| categories | ManyToManyField | Target categories (empty = All Videos). Matching includes subcategories of selected parents |
| start_time | TimeField | When the ad break should start |
| end_time | TimeField | When the ad break should end |
| created_at | DateTimeField | Creation timestamp |
| updated_at | DateTimeField | Last update timestamp |
