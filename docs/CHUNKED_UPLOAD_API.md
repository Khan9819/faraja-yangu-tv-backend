# Chunked Video Upload API

This document explains how to upload large video files using the chunked upload system with presigned URLs for direct-to-R2 uploads.

## Overview

The upload process has 3 steps:

1. **Get presigned URL** - Request a signed URL from the backend
2. **Upload chunk directly to R2** - PUT the chunk directly to cloud storage
3. **Assemble chunks** - Tell the backend to combine all chunks

This approach bypasses the server for file transfers, resulting in faster uploads.

---

## Endpoints

### 1. Get Presigned Upload URL

**POST** `/api/streaming/get-chunk-upload-url/`

Request a presigned URL for uploading a chunk directly to R2.

#### Request Body (JSON)

```json
{
  "videoId": 123,
  "chunkIndex": 0,
  "totalChunks": 10
}
```

| Field | Type | Description |
|-------|------|-------------|
| `videoId` | number | ID of the video (from create-video endpoint) |
| `chunkIndex` | number | 0-based index of the current chunk |
| `totalChunks` | number | Total number of chunks for this upload |

#### Response

```json
{
  "success": true,
  "data": {
    "upload_url": "https://....r2.cloudflarestorage.com/...",
    "chunk_index": 0,
    "total_chunks": 10,
    "expires_in": 300
  }
}
```

---

### 2. Upload Chunk to R2

**PUT** `{upload_url}` (from step 1)

Upload the chunk directly to R2 using the presigned URL.

#### Important Requirements

| Requirement | Value |
|-------------|-------|
| Method | `PUT` (not POST) |
| Body | Raw binary blob (NOT FormData) |
| Content-Type | `application/octet-stream` |

#### Example

```javascript
// CORRECT - Raw binary PUT
await fetch(uploadUrl, {
  method: 'PUT',
  body: chunkBlob,  // Raw Blob object
  headers: {
    'Content-Type': 'application/octet-stream'
  }
});
```

```javascript
// WRONG - Do NOT use FormData
const formData = new FormData();
formData.append('chunk', chunkBlob);
await fetch(uploadUrl, {
  method: 'PUT',
  body: formData  // This will fail!
});
```

#### Response

- **Success**: HTTP 200 with empty body
- **Failure**: HTTP 403 (signature mismatch) or HTTP 400

---

### 3. Assemble Chunks

**POST** `/api/streaming/assemble-chunks/`

After all chunks are uploaded, call this endpoint to combine them.

#### Request Body (JSON)

```json
{
  "videoId": 123,
  "fileName": "my-video.mp4"
}
```

#### Response

```json
{
  "success": true,
  "data": {
    "message": "Video assembly queued. Processing will begin shortly.",
    "video_id": 123,
    "task_id": "abc123-task-id"
  }
}
```

The assembly runs in the background. HLS conversion starts automatically after assembly completes.

---

## Complete Example

```javascript
async function uploadVideo(file, videoId) {
  const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB chunks
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
  
  // Upload each chunk
  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);
    
    // Step 1: Get presigned URL
    const { data } = await api.post('/streaming/get-chunk-upload-url/', {
      videoId: videoId,
      chunkIndex: i,
      totalChunks: totalChunks
    });
    
    // Step 2: Upload directly to R2
    const uploadResponse = await fetch(data.upload_url, {
      method: 'PUT',
      body: chunk,
      headers: {
        'Content-Type': 'application/octet-stream'
      }
    });
    
    if (!uploadResponse.ok) {
      throw new Error(`Chunk ${i} upload failed`);
    }
    
    console.log(`Uploaded chunk ${i + 1}/${totalChunks}`);
  }
  
  // Step 3: Assemble chunks
  await api.post('/streaming/assemble-chunks/', {
    videoId: videoId,
    fileName: file.name
  });
  
  console.log('Upload complete! Video is being processed.');
}
```

---

## Fallback: Server-Side Upload

If presigned URLs don't work (e.g., CORS issues), use the legacy endpoint:

**POST** `/api/streaming/upload-chunk/`

This uploads through the server but is slower (~1-2s per chunk vs ~200-400ms with presigned URLs).

#### Request (multipart/form-data)

| Field | Type | Description |
|-------|------|-------------|
| `chunk` | File | The chunk file |
| `videoId` | number | Video ID |
| `chunkIndex` | number | 0-based chunk index |
| `totalChunks` | number | Total chunks |
| `fileName` | string | Original filename |

---

## Troubleshooting

### 403 Forbidden on R2 Upload

- Ensure you're using `PUT` method, not `POST`
- Ensure body is raw `Blob`, not `FormData`
- Check that the presigned URL hasn't expired (5 min limit)

### CORS Errors

Your R2 bucket needs CORS configured to allow PUT requests from your frontend origin.

### Slow Uploads

- Increase chunk size (up to 5MB recommended)
- Use presigned URLs instead of server-side upload
- Check network conditions
