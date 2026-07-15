# Chunked Video Upload API

This document describes the chunked upload functionality for large video files.

## Overview

The chunked upload system allows clients to upload large video files in smaller pieces (chunks), which provides:
- **Resumable uploads**: If a chunk fails, only that chunk needs to be re-uploaded
- **Better reliability**: Smaller chunks are less likely to fail on unstable connections
- **Progress tracking**: Clients can track upload progress chunk by chunk
- **Memory efficiency**: Server processes one chunk at a time

## Workflow

### 1. Create Video Record (Optional)
First, create a video record in the database to get a `video_id`:

```http
POST /api/streaming/create-video/
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "My Video",
  "description": "Video description",
  "category": 1,
  "thumbnail": <file>,
  "processing_status": "pending"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 123,
    "title": "My Video",
    ...
  }
}
```

### 2. Upload Chunks
Split your video file into chunks (e.g., 5MB each) and upload them sequentially or in parallel:

```http
POST /api/streaming/upload-chunk/
Authorization: Bearer <token>
Content-Type: multipart/form-data

{
  "chunk": <file_chunk>,
  "videoId": 123,
  "chunkIndex": 0,
  "totalChunks": 10,
  "fileName": "my_video.mp4"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Chunk 1/10 uploaded successfully",
    "chunk_index": 0,
    "total_chunks": 10,
    "uploaded_chunks": 1,
    "is_complete": false
  }
}
```

Repeat for each chunk (chunkIndex: 0, 1, 2, ..., 9)

### 3. Assemble Chunks
Once all chunks are uploaded (`is_complete: true`), call the assemble endpoint:

```http
POST /api/streaming/assemble-chunks/
Authorization: Bearer <token>
Content-Type: application/json

{
  "videoId": 123,
  "fileName": "my_video.mp4"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Video assembled successfully. HLS conversion in progress.",
    "video_id": 123,
    "video_path": "videos/originals/123_my_video.mp4",
    "chunks_assembled": 10
  }
}
```

## Client Implementation Example (JavaScript)

```javascript
async function uploadVideoInChunks(file, videoId) {
  const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB chunks
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
  
  for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
    const start = chunkIndex * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);
    
    const formData = new FormData();
    formData.append('chunk', chunk);
    formData.append('videoId', videoId);
    formData.append('chunkIndex', chunkIndex);
    formData.append('totalChunks', totalChunks);
    formData.append('fileName', file.name);
    
    const response = await fetch('/api/streaming/upload-chunk/', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      },
      body: formData
    });
    
    const result = await response.json();
    console.log(`Uploaded chunk ${chunkIndex + 1}/${totalChunks}`);
    
    // Update progress bar
    const progress = ((chunkIndex + 1) / totalChunks) * 100;
    updateProgressBar(progress);
  }
  
  // All chunks uploaded, now assemble
  const assembleResponse = await fetch('/api/streaming/assemble-chunks/', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      videoId: videoId,
      fileName: file.name
    })
  });
  
  const result = await assembleResponse.json();
  console.log('Video assembled:', result);
}
```

## Error Handling

### Missing Fields
```json
{
  "success": false,
  "error": {
    "error": "Missing required fields",
    "required": ["chunk", "videoId", "chunkIndex", "totalChunks", "fileName"]
  }
}
```

### Invalid Video ID
```json
{
  "success": false,
  "error": {
    "error": "Video with id 123 not found"
  }
}
```

### No Chunks Found (Assembly)
```json
{
  "success": false,
  "error": {
    "error": "No chunks found for this video"
  }
}
```

## Storage Backend

The implementation uses Django's `default_storage` system, which means it works with:
- Local filesystem
- Amazon S3
- Cloudflare R2
- Google Cloud Storage
- Any Django-compatible storage backend

Chunks are stored temporarily at: `videos/chunks/{video_id}/chunk_XXXX`

After assembly, chunks are deleted and the final video is stored at: `videos/originals/{video_id}_{filename}`

## Security

- All endpoints require authentication (`@permission_classes([IsAuthenticated])`)
- Video ownership should be verified before allowing chunk uploads
- Consider adding rate limiting to prevent abuse
- Implement cleanup jobs to remove abandoned chunks after a timeout period

## Performance Considerations

- **Chunk Size**: 5-10MB is recommended for most use cases
- **Parallel Uploads**: Clients can upload multiple chunks in parallel (with caution)
- **Memory Usage**: Server loads one chunk at a time into memory
- **Storage**: Ensure sufficient storage space for temporary chunks

## Future Enhancements

- [ ] Add chunk checksum verification (MD5/SHA256)
- [ ] Implement chunk expiration/cleanup for abandoned uploads
- [ ] Add support for resuming interrupted uploads
- [ ] Implement parallel chunk assembly for faster processing
- [ ] Add upload session management with unique upload IDs
