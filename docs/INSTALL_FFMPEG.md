# Install FFmpeg - Required for Video Processing

## Error You're Seeing

```
[WinError 2] The system cannot find the file specified
Error creating HLS variant 1080p
```

This means **FFmpeg is not installed** on your system.

## Installation Instructions

### Windows (Choose One Method)

#### Method 1: Using Chocolatey (Recommended) ✅ INSTALLED
```bash
# Install Chocolatey if you don't have it
# Run PowerShell as Administrator and paste:
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install FFmpeg
choco install ffmpeg

# FFmpeg is installed at:
# C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin

# Add to PATH (if not already added):
# 1. Open System Properties → Environment Variables
# 2. Edit "Path" variable (System or User)
# 3. Add: C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin
# 4. Click OK and restart terminal

# Verify installation
ffmpeg -version
```

#### Method 2: Manual Installation
1. Download FFmpeg from: https://www.gyan.dev/ffmpeg/builds/
2. Download the **ffmpeg-release-essentials.zip**
3. Extract to `C:\ffmpeg`
4. Add to PATH:
   - Open System Properties → Environment Variables
   - Edit "Path" variable
   - Add: `C:\ffmpeg\bin`
   - Click OK
5. **Restart your terminal/IDE**
6. Verify: `ffmpeg -version`

#### Method 3: Using Scoop
```bash
# Install Scoop
iwr -useb get.scoop.sh | iex

# Install FFmpeg
scoop install ffmpeg

# Verify
ffmpeg -version
```

### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install ffmpeg

# Verify
ffmpeg -version
```

### macOS
```bash
# Using Homebrew
brew install ffmpeg

# Verify
ffmpeg -version
```

## After Installation

1. **Restart your terminal/command prompt**
2. **Restart your Celery worker**:
   ```bash
   celery -A farajayangu_be worker -l info --pool=solo
   ```
3. **Try uploading a video again**

## Verify FFmpeg is Working

Run this in your terminal:
```bash
ffmpeg -version
ffprobe -version
```

You should see version information. If you get "command not found", FFmpeg is not in your PATH.

## Test Video Processing

After installing FFmpeg, test the conversion:

```python
# In Django shell
python manage.py shell

from apps.streaming.services.video_processor import check_ffmpeg_installed
check_ffmpeg_installed()
# Should print: FFmpeg found at: C:\path\to\ffmpeg.exe
```

## Common Issues

### "ffmpeg is not recognized"
- FFmpeg is not in your PATH
- Restart your terminal after installation
- Check PATH: `echo %PATH%` (Windows) or `echo $PATH` (Linux/Mac)

### "Permission denied"
- Run terminal as Administrator (Windows)
- Use `sudo` on Linux/Mac

### Still not working?
- Completely close and reopen your IDE
- Restart your computer
- Verify FFmpeg is in PATH: `where ffmpeg` (Windows) or `which ffmpeg` (Linux/Mac)

## What FFmpeg Does

FFmpeg converts your uploaded MP4 videos into HLS format with multiple quality levels:
- **1080p** - High quality (5 Mbps)
- **720p** - Medium quality (2.8 Mbps)
- **480p** - Standard quality (1.4 Mbps)
- **360p** - Low quality (800 Kbps)

This enables adaptive streaming - the video player automatically switches quality based on the viewer's internet speed!
