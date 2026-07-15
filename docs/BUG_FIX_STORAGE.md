# 🐛 Bug Fix: HLS Files Were Saving to Server Instead of R2

## The Problem

**Original Code (Line 53 in tasks.py):**
```python
if hasattr(settings, 'MEDIA_ROOT'):
    local_hls_dir = os.path.join(settings.MEDIA_ROOT, hls_output_dir)  # ❌ WRONG!
```

This was saving HLS files to the **server's media directory** instead of using temp storage.

## The Fix

**New Code:**
```python
# Define output directory for HLS files (use temp directory, NOT server storage)
hls_output_dir = f"videos/hls/{video.slug}"  # Remote path in R2
import tempfile
local_hls_dir = os.path.join(tempfile.gettempdir(), f"hls_{video_id}")  # ✅ Local temp only
```

Now FFmpeg writes to **temp directory only**, then files are uploaded to R2 and temp is cleaned up.

## What Changed

### Before (Bug):
```
1. Upload MP4 → R2 ✅
2. Download to temp → Process ✅
3. FFmpeg converts → Saves to media/videos/hls/ ❌ (Server storage!)
4. Upload to R2 ✅
5. Cleanup temp ✅
Result: Files in BOTH server AND R2 ❌
```

### After (Fixed):
```
1. Upload MP4 → R2 ✅
2. Download to temp → Process ✅
3. FFmpeg converts → Saves to C:\Users\...\Temp\hls_X\ ✅ (Temp only!)
4. Upload to R2 ✅
5. Cleanup temp ✅
Result: Files ONLY in R2 ✅
```

## Files Modified

1. **apps/streaming/tasks/tasks.py**
   - Line 50-53: Changed to always use temp directory
   - Line 68-69: Added logging for R2 upload
   - Line 85-95: Clarified cleanup comments

2. **.gitignore**
   - Added `media/` to prevent committing server files

3. **New Files Created**
   - `cleanup_server_media.py` - Script to remove existing server files
   - `BUG_FIX_STORAGE.md` - This document

## Cleanup Required

### Remove Existing Files from Server

Run the cleanup script:
```bash
python cleanup_server_media.py
```

This will:
- Show how many files are on the server
- Ask for confirmation
- Delete all files from `media/` directory

**Note:** Files are already in R2, so it's safe to delete from server.

## Verification

### Check Server (Should be empty):
```bash
# Windows
dir media\videos\hls\

# Linux/Mac
ls -la media/videos/hls/
```

Should show: **"File Not Found"** or empty directory

### Check R2 (Should have all files):
1. Log into Cloudflare dashboard
2. Navigate to R2 → `farajayangu-tv` bucket
3. Look for `videos/hls/` directory
4. Verify all `.m3u8` and `.ts` files are present

## Testing

After the fix, upload a new video:

```bash
# 1. Restart Celery worker
celery -A farajayangu_be worker -l info --pool=solo

# 2. Upload a video via API
# POST /streaming/create-video/

# 3. Check logs - should see:
[INFO] Video downloaded to: C:\Users\...\Temp\video_X.mp4
[INFO] FFmpeg found at: ...
[INFO] Uploaded 156 files to R2 storage
[INFO] Deleted original MP4 from R2 for video X
[INFO] Cleaned up local temp files for video X

# 4. Verify server media directory is still empty
dir media\videos\hls\
# Should be empty!

# 5. Verify files are in R2
# Check Cloudflare dashboard
```

## Impact

✅ **Server disk space saved** - No media files stored locally  
✅ **Consistent with architecture** - All media in R2  
✅ **Scalable** - No disk space concerns  
✅ **Cost efficient** - Only pay for R2 storage  
✅ **Deployment ready** - Works in containers with minimal disk  

## Summary

- **Bug:** HLS files were being saved to server's `media/` directory
- **Fix:** Now uses temp directory only, uploads to R2, then cleans up
- **Action:** Run `cleanup_server_media.py` to remove existing server files
- **Result:** All media files now stored exclusively in Cloudflare R2 ✅
