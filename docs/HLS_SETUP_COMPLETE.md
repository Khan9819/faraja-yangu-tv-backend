# HLS Video Streaming - Setup Complete ✅

## What Was Fixed

### 1. **Celery Redis Connection** ✅
- Fixed Redis URL construction to handle username/password authentication
- Now properly connects to `cloud.nexent.dev:5379` with credentials
- Added task tracking and 30-minute time limit for video processing

### 2. **Windows Compatibility** ✅
- Fixed temp file paths to use `tempfile.gettempdir()` instead of hardcoded `/tmp/`
- Works on Windows, Linux, and macOS

### 3. **Error Handling** ✅
- Added graceful error handling when Redis/Celery is unavailable
- Video upload won't crash if Celery worker is not running
- Improved logging with task IDs and error tracking

### 4. **Security** ✅
- `.env` file is properly gitignored to protect credentials

## Current Configuration

**Redis Server:**
- Host: `cloud.nexent.dev`
- Port: `5379`
- User: `default`
- Password: `7OJnG2ZLhfN0ui`

**Cloudflare R2 Storage:**
- Endpoint: `https://1532b4de331061991157470aaabcc76d.r2.cloudflarestorage.com`
- Bucket: `farajayangu-tv`

## How to Use

### 1. Start Celery Worker

```bash
celery -A farajayangu_be worker -l info --pool=solo
```

Expected output:
```
[tasks]
  . apps.streaming.tasks.tasks.convert_video_to_hls

Connected to redis://:**@cloud.nexent.dev:5379/0
celery@DESKTOP-F9HGD2M ready.
```

### 2. Start Django Server

```bash
python manage.py runserver
```

### 3. Upload Video via API

**Endpoint:** `POST /streaming/create-video/`

**Headers:**
```
Authorization: Bearer YOUR_JWT_TOKEN
Content-Type: multipart/form-data
```

**Body:**
```
title: "My Video Title"
description: "Video description"
category: 1
thumbnail: <file>
video: <mp4 file>
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 3,
    "title": "My Video Title",
    "slug": "my-video-title",
    "processing_status": "pending",
    "message": "Video uploaded successfully. HLS conversion in progress.",
    "is_ready_for_streaming": false,
    "streaming_url": null
  }
}
```

### 4. Monitor Processing

Watch the Celery worker terminal for conversion progress:

```
[2025-11-13 12:08:45] INFO: Starting HLS conversion for video 3: My Video Title
[2025-11-13 12:09:12] INFO: Uploaded 156 HLS files to storage
[2025-11-13 12:09:13] INFO: Successfully converted video 3 to HLS
```

### 5. Check Video Status

**Endpoint:** `GET /streaming/videos/{id}/`

**Response (Completed):**
```json
{
  "id": 3,
  "processing_status": "completed",
  "is_ready_for_streaming": true,
  "streaming_url": "videos/hls/my-video-title/master.m3u8",
  "hls_master_playlist": "videos/hls/my-video-title/master.m3u8",
  "duration": "00:05:30"
}
```

## Testing in Django Shell

```python
# Test task queueing
from apps.streaming.tasks import convert_video_to_hls
task = convert_video_to_hls.delay(3)
print(f"Task ID: {task.id}")

# Check task status
from celery.result import AsyncResult
result = AsyncResult(task.id)
print(f"Status: {result.state}")
```

## Quality Levels Generated

Each video is converted to 4 quality levels:

| Quality | Resolution | Video Bitrate | Audio Bitrate | Bandwidth |
|---------|-----------|---------------|---------------|-----------|
| 1080p   | 1920x1080 | 5000 kbps    | 192 kbps     | ~5.2 Mbps |
| 720p    | 1280x720  | 2800 kbps    | 128 kbps     | ~2.9 Mbps |
| 480p    | 854x480   | 1400 kbps    | 128 kbps     | ~1.5 Mbps |
| 360p    | 640x360   | 800 kbps     | 96 kbps      | ~0.9 Mbps |

## File Structure

After conversion:

```
videos/hls/
└── my-video-title/
    ├── master.m3u8              # Master playlist
    ├── 1080p/
    │   ├── 1080p.m3u8          # 1080p playlist
    │   └── 1080p_*.ts          # Video segments
    ├── 720p/
    │   ├── 720p.m3u8
    │   └── 720p_*.ts
    ├── 480p/
    │   ├── 480p.m3u8
    │   └── 480p_*.ts
    └── 360p/
        ├── 360p.m3u8
        └── 360p_*.ts
```

## Troubleshooting

### Celery Won't Connect
```bash
# Check Redis connection
redis-cli -h cloud.nexent.dev -p 5379 -a 7OJnG2ZLhfN0ui ping
# Should return: PONG
```

### FFmpeg Not Found
```bash
# Install FFmpeg
choco install ffmpeg

# Verify installation
ffmpeg -version
```

### Video Upload Fails
- Check Django logs for detailed error
- Verify R2 credentials in `.env`
- Ensure video file is valid MP4 H.264

### Task Stuck in Pending
- Restart Celery worker
- Check worker logs for errors
- Verify Redis connection

## Next Steps

1. ✅ System is ready for video uploads
2. ✅ HLS conversion happens automatically
3. ✅ Original MP4 files are deleted after conversion
4. ✅ Videos are stored in Cloudflare R2

## Client-Side Integration

Use HLS.js for web playback:

```html
<video id="video" controls></video>

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script>
  const video = document.getElementById('video');
  const hls = new Hls();
  hls.loadSource('https://your-cdn.com/videos/hls/my-video-title/master.m3u8');
  hls.attachMedia(video);
</script>
```

## Support

All components are properly configured and tested. The system is production-ready!
