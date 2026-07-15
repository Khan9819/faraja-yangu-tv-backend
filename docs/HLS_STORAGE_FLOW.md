# HLS Video Processing & Storage Flow

## ✅ Current Implementation (All Files Stored in Cloudflare R2)

```
┌─────────────────────────────────────────────────────────────────┐
│                    1. VIDEO UPLOAD                               │
│  Admin uploads MP4 → Django API → Cloudflare R2                 │
│  Location: videos/originals/video_name.mp4                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    2. CELERY TASK TRIGGERED                      │
│  convert_video_to_hls.delay(video_id)                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    3. DOWNLOAD TO TEMP                           │
│  Download from R2 → Local temp directory                        │
│  Location: C:\Users\user\AppData\Local\Temp\video_X.mp4        │
│  Purpose: FFmpeg processing only                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    4. FFMPEG CONVERSION                          │
│  Convert MP4 → HLS (4 quality levels)                           │
│  Local temp: C:\Users\user\AppData\Local\Temp\hls_X\           │
│  ├── master.m3u8                                                │
│  ├── 1080p/                                                     │
│  │   ├── 1080p.m3u8                                            │
│  │   └── 1080p_*.ts (segments)                                 │
│  ├── 720p/                                                      │
│  ├── 480p/                                                      │
│  └── 360p/                                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    5. UPLOAD HLS TO R2                           │
│  Upload ALL HLS files → Cloudflare R2                           │
│  Location: videos/hls/video-slug/                               │
│  ├── master.m3u8                                                │
│  ├── 1080p/1080p.m3u8                                           │
│  ├── 1080p/1080p_*.ts                                           │
│  ├── 720p/720p.m3u8                                             │
│  ├── 720p/720p_*.ts                                             │
│  ├── 480p/480p.m3u8                                             │
│  ├── 480p/480p_*.ts                                             │
│  ├── 360p/360p.m3u8                                             │
│  └── 360p/360p_*.ts                                             │
│                                                                  │
│  ✅ ALL FILES STORED IN CLOUDFLARE R2                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    6. CLEANUP                                    │
│  ✅ Delete original MP4 from R2 (save storage costs)            │
│  ✅ Delete local temp video file                                │
│  ✅ Delete local temp HLS directory                             │
│                                                                  │
│  Result: ZERO files left on server                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    7. UPDATE DATABASE                            │
│  video.hls_master_playlist = "videos/hls/slug/master.m3u8"     │
│  video.processing_status = "completed"                          │
│  video.duration = "00:05:30"                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Storage Configuration

**Backend:** `storages.backends.s3boto3.S3Boto3Storage`

**Cloudflare R2 Settings:**
- **Endpoint:** `https://1532b4de331061991157470aaabcc76d.r2.cloudflarestorage.com`
- **Bucket:** `farajayangu-tv`
- **Access Key:** Configured in `.env`
- **Secret Key:** Configured in `.env`

## File Locations in R2

### Before Processing:
```
videos/originals/
└── my-video.mp4  (Original upload)
```

### After Processing:
```
videos/hls/
└── my-video-slug/
    ├── master.m3u8
    ├── 1080p/
    │   ├── 1080p.m3u8
    │   ├── 1080p_000.ts
    │   ├── 1080p_001.ts
    │   └── ...
    ├── 720p/
    │   ├── 720p.m3u8
    │   └── 720p_*.ts
    ├── 480p/
    │   ├── 480p.m3u8
    │   └── 480p_*.ts
    └── 360p/
        ├── 360p.m3u8
        └── 360p_*.ts

Original MP4 is DELETED after successful conversion ✅
```

## Code References

### Upload Function (Line 127-161 in tasks.py)
```python
def upload_hls_files_to_storage(local_dir: str, remote_dir: str) -> list:
    """Upload HLS files from local directory to remote storage."""
    for root, dirs, files in os.walk(local_dir):
        for file in files:
            local_file_path = os.path.join(root, file)
            rel_path = os.path.relpath(local_file_path, local_dir)
            remote_file_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
            
            # Upload to Cloudflare R2
            with open(local_file_path, 'rb') as f:
                default_storage.save(remote_file_path, f)  # ← Saves to R2
```

### Cleanup Function (Line 164-193 in tasks.py)
```python
def cleanup_local_files(video_file_path: str, hls_dir: str):
    """Clean up local temporary files after processing."""
    # Deletes temp video file
    # Deletes temp HLS directory
    # NOTHING left on server
```

## Verification

### Check Files in R2:
1. Log into Cloudflare dashboard
2. Navigate to R2 → `farajayangu-tv` bucket
3. Look for `videos/hls/` directory
4. Verify all `.m3u8` and `.ts` files are present

### Check Server (Should be empty):
```bash
# Check temp directory - should have no video files
ls C:\Users\user\AppData\Local\Temp\video_*
ls C:\Users\user\AppData\Local\Temp\hls_*

# Check media directory - should be empty or minimal
ls media/videos/
```

## Benefits

✅ **No server storage used** - All files in R2  
✅ **Fast CDN delivery** - Cloudflare edge network  
✅ **Cost efficient** - Original MP4 deleted after conversion  
✅ **Scalable** - No disk space concerns on server  
✅ **Reliable** - R2 handles redundancy and backups  

## Client Access

Videos are streamed directly from R2:
```
https://your-r2-domain.com/videos/hls/my-video-slug/master.m3u8
```

The HLS player automatically:
1. Fetches master playlist
2. Selects appropriate quality
3. Streams segments directly from R2
4. Adapts quality based on network speed

## Summary

✅ **ALL media files are stored in Cloudflare R2**  
✅ **Server is only used for temporary processing**  
✅ **Cleanup ensures zero files remain on server**  
✅ **System is production-ready and scalable**
