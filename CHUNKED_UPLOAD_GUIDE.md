# Chunked Video Upload — Backend Changes & Frontend Integration Guide

This document explains recent backend changes to the chunked video upload pipeline and what the frontend team needs to check and update.

---

## Background: What Was Happening

Uploads were failing at ~40% with no HTTP response from Cloudflare R2. The browser reported a generic `Failed` network error — no status code, no response body.

### Root Causes Identified

1. **Presigned URL signature mismatch** — The backend was generating presigned URLs without pinning `Content-Type`, but the browser sends `Content-Type: application/octet-stream`. If headers differ between the signed expectation and what the browser actually sends, R2 silently drops the connection.

2. **No upload resume capability** — When an upload failed mid-way, the client had no way to know which chunks succeeded. It had to restart from scratch.

3. **R2 CORS configuration** — Uploads go directly from the browser to R2 (not through Django). If R2's CORS policy doesn't allow `PUT` from the CMS origin with the correct headers, the browser's preflight fails silently.

---

## What Changed on the Backend

### 1. `Content-Type` is Now Pinned in Presigned URLs

The presigned URL is now signed with `ContentType: application/octet-stream`. This means:

> **The frontend MUST send `Content-Type: application/octet-stream` as a header on every chunk `PUT` request.**

If this header is missing or different, R2 will reject the request because the signature won't match.

### 2. Response From `get-chunk-upload-url` Now Includes `required_headers`

The response now looks like this:

```json
{
  "status": "success",
  "data": {
    "upload_url": "https://....r2.cloudflarestorage.com/...?X-Amz-...",
    "chunk_index": 0,
    "total_chunks": 50,
    "expires_in": 300,
    "required_headers": {
      "Content-Type": "application/octet-stream"
    }
  }
}
```

The `required_headers` object contains all headers that **must** be included in the `PUT` request to R2. Use these headers directly.

### 3. New Endpoint: `GET /streaming/get-upload-status/`

This endpoint allows the frontend to check which chunks have been successfully uploaded to R2, enabling **upload resume** after a failure.

**Request:**
```
GET /api/streaming/get-upload-status/?videoId=123&totalChunks=50
Authorization: Bearer <token>
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "video_id": "123",
    "total_chunks": 50,
    "uploaded_chunks": [0, 1, 2, 3, 4, 5],
    "missing_chunks": [6, 7, 8, 9, 10, ...],
    "uploaded_count": 6,
    "missing_count": 44,
    "progress": 12.0,
    "is_complete": false
  }
}
```

---

## What the Frontend Team Needs to Do

### 1. Set `Content-Type` Header on Every Chunk PUT (Critical)

When uploading a chunk to the presigned R2 URL, you **must** include:

```js
// Example using fetch
const response = await fetch(uploadUrl, {
  method: 'PUT',
  headers: {
    'Content-Type': 'application/octet-stream',
  },
  body: chunkBlob,
});
```

If you are using `axios`:

```js
await axios.put(uploadUrl, chunkBlob, {
  headers: {
    'Content-Type': 'application/octet-stream',
  },
});
```

**Do NOT use `multipart/form-data` or let the browser set `Content-Type` automatically.** The presigned URL signature expects exactly `application/octet-stream`.

### 2. Use `required_headers` From the Response

Instead of hardcoding the header, read it from the `get-chunk-upload-url` response:

```js
const { upload_url, required_headers } = response.data;

await fetch(upload_url, {
  method: 'PUT',
  headers: required_headers,  // { "Content-Type": "application/octet-stream" }
  body: chunkBlob,
});
```

This future-proofs the integration if the backend ever changes the required headers.

### 3. Implement Upload Resume on Failure

When an upload fails (network error, timeout, etc.), call the new status endpoint before restarting:

```js
async function getUploadStatus(videoId, totalChunks) {
  const response = await api.get('/streaming/get-upload-status/', {
    params: { videoId, totalChunks },
  });
  return response.data;
}

// On upload failure or page reload:
const status = await getUploadStatus(videoId, totalChunks);

if (status.is_complete) {
  // All chunks uploaded, proceed to assembly
  await assembleChunks(videoId, fileName);
} else {
  // Only upload missing chunks
  for (const chunkIndex of status.missing_chunks) {
    const url = await getChunkUploadUrl(videoId, chunkIndex, totalChunks);
    await uploadChunk(url, chunks[chunkIndex]);
  }
}
```

### 4. Do NOT Reuse Presigned URLs Across Retries

Each presigned URL is valid for the duration specified in `expires_in` (currently 300 seconds / 5 minutes). If a chunk upload fails:

- **Request a new presigned URL** from `get-chunk-upload-url` before retrying
- **Do not reuse** the old URL — it may have expired or be tied to a different signature context

```js
async function uploadChunkWithRetry(videoId, chunkIndex, totalChunks, chunkBlob, maxRetries = 3) {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      // Always get a FRESH presigned URL for each attempt
      const { upload_url, required_headers } = await getChunkUploadUrl(videoId, chunkIndex, totalChunks);

      await fetch(upload_url, {
        method: 'PUT',
        headers: required_headers,
        body: chunkBlob,
      });

      return; // Success
    } catch (error) {
      if (attempt < maxRetries - 1) {
        // Wait before retrying (exponential backoff)
        await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)));
      } else {
        throw error;
      }
    }
  }
}
```

### 5. Do NOT Set Extra Headers on the PUT Request

When uploading to the presigned R2 URL, only send the headers from `required_headers`. Do **not** add:

- `Authorization` header (the presigned URL already contains auth in query params)
- `X-Custom-*` headers
- Any other headers not in `required_headers`

Extra headers can invalidate the S3v4 signature and cause silent failures.

---

## Checklist

| # | Item | Status |
|---|------|--------|
| 1 | Set `Content-Type: application/octet-stream` on all chunk `PUT` requests | Required |
| 2 | Use `required_headers` from `get-chunk-upload-url` response | Recommended |
| 3 | Implement upload resume using `get-upload-status` endpoint | Recommended |
| 4 | Request fresh presigned URL on every retry (never reuse expired URLs) | Required |
| 5 | Do not add `Authorization` or extra headers to the R2 `PUT` request | Required |
| 6 | Verify no `multipart/form-data` wrapping on chunk body — send raw binary | Required |

---

## Upload Flow Summary

```
Frontend                          Backend                         Cloudflare R2
   │                                │                                │
   ├─ POST /create-video/ ─────────►│ (creates Video, returns ID)    │
   │◄─ { id: 123 }  ────────────────┤                                │
   │                                │                                │
   │  For each chunk:               │                                │
   ├─ POST /get-chunk-upload-url/ ─►│ (generates presigned URL)      │
   │◄─ { upload_url, headers }  ────┤                                │
   │                                │                                │
   ├─ PUT upload_url ───────────────┼───────────────────────────────►│
   │  Content-Type: application/    │                                │
   │  octet-stream                  │                                │
   │  Body: <raw chunk bytes>       │                                │
   │◄───────────────────────────────┼────────────── 200 OK ──────────┤
   │                                │                                │
   │  On failure / resume:          │                                │
   ├─ GET /get-upload-status/ ─────►│ (checks R2 for existing chunks)│
   │◄─ { missing_chunks: [...] }  ──┤                                │
   │  (retry only missing chunks)   │                                │
   │                                │                                │
   │  After all chunks uploaded:    │                                │
   ├─ POST /assemble-chunks/ ──────►│ (queues Celery task)           │
   │◄─ { task_id }  ────────────────┤                                │
   │                                │                                │
   │  WebSocket: progress updates   │◄── Celery worker  ────────────►│
```

---

## Questions?

If uploads still fail after these changes, check:

1. **Browser DevTools → Network tab**: Is the `Content-Type` header being sent correctly on the `PUT`?
2. **Is the presigned URL fresh?** Check the `X-Amz-Date` and `X-Amz-Expires` query params in the URL.
3. **R2 CORS**: Ask the ops team to verify R2 bucket CORS allows `PUT` from `https://cms.farajayangutv.co.tz` with `Content-Type` in `AllowedHeaders`. See the main `README.md` for the exact config.
