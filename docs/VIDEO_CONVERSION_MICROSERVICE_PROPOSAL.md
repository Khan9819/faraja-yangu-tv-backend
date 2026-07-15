# Video Conversion Microservice — Proposal & Technical Specification

> **Author:** Backend Team  
> **Date:** April 6, 2026  
> **Status:** Draft — Pending Review  
> **Scope:** Extract video conversion (FFmpeg/HLS) from the Django monolith into a standalone C++ microservice

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Deep-Dive](#2-current-architecture-deep-dive)
3. [Problems with the Current Approach](#3-problems-with-the-current-approach)
4. [Proposed C++ Microservice Architecture](#4-proposed-c-microservice-architecture)
5. [Separation Boundary — What Moves, What Stays](#5-separation-boundary--what-moves-what-stays)
6. [Communication Protocol](#6-communication-protocol)
7. [C++ Microservice Technical Design](#7-c-microservice-technical-design)
8. [Database & State Management](#8-database--state-management)
9. [Storage Interaction](#9-storage-interaction)
10. [Deployment Strategy](#10-deployment-strategy)
11. [Migration Plan](#11-migration-plan)
12. [Risk Assessment](#12-risk-assessment)
13. [Open Questions](#13-open-questions)

---

## 1. Executive Summary

Our Django backend currently handles the entire video lifecycle — upload, chunk assembly, FFmpeg-based HLS conversion (4 quality variants), R2 upload, and cleanup — inside Celery workers. This works, but FFmpeg is CPU-bound work running in a Python process with significant overhead. We propose extracting the conversion layer into a dedicated C++ microservice that:

- Receives conversion jobs via a message queue (Redis/RabbitMQ)
- Runs FFmpeg via `libav*` C APIs or subprocess for maximum performance
- Reports progress back via the same queue / WebSocket bridge
- Uploads HLS output directly to R2/S3
- Returns completion status to the Django backend

The Django backend retains ownership of: uploads, chunk assembly, video metadata, API endpoints, authentication, ad injection, WebSocket consumer routing, and all business logic.

---

## 2. Current Architecture Deep-Dive

### 2.1 End-to-End Video Pipeline

```
┌─────────────┐     Presigned URL      ┌──────────────────┐
│   Client     │ ────────────────────►  │  Cloudflare R2   │
│  (chunks)    │   Direct chunk upload  │  videos/chunks/  │
└──────┬──────┘                         └────────┬─────────┘
       │ POST /assemble-chunks/                  │
       ▼                                         │
┌──────────────┐   Celery task          ┌────────▼─────────┐
│  Django API  │ ──────────────────────► │ assemble_chunks  │
│  (DRF views) │                        │ (Celery worker)  │
└──────────────┘                        └────────┬─────────┘
                                                 │ chains to
                                        ┌────────▼──────────┐
                                        │ convert_video_to  │
                                        │ _hls (Celery)     │
                                        │                   │
                                        │ 1. Download MP4   │
                                        │ 2. FFmpeg encode  │
                                        │    4 variants     │
                                        │ 3. Upload HLS→R2  │
                                        │ 4. Cleanup        │
                                        └────────┬──────────┘
                                                 │
                                        ┌────────▼──────────┐
                                        │  WebSocket layer  │
                                        │  (Django Channels) │
                                        │  Progress updates │
                                        └───────────────────┘
```

### 2.2 Key Files & Their Responsibilities

| File | Responsibility |
|------|---------------|
| `apps/streaming/tasks/tasks.py` | Celery tasks: `assemble_chunks_task`, `convert_video_to_hls`, `delete_video_files_task`, `cleanup_stale_chunks`, `cleanup_orphaned_hls_files`, `import_video_from_google_drive` |
| `apps/streaming/services/video_processor.py` (~1200 lines) | Core conversion logic: hardware acceleration detection, FFmpeg command building, quality presets, parallel/sequential processing, progress tracking, master playlist generation |
| `apps/streaming/services/hls_service.py` | HLS playlist parsing, URL rewriting, presigned URL generation, starter segments |
| `apps/streaming/services/google_drive.py` | Google Drive import with chunked download |
| `apps/streaming/socket/utils.py` | WebSocket progress helpers: `send_video_progress()`, `send_video_complete()`, `send_video_error()`, `send_upload_progress()` |
| `apps/streaming/views.py` (~1500 lines) | All API endpoints: upload, streaming, feed, comments, ads, admin |
| `apps/streaming/models.py` | `Video` model with processing state fields |
| `socket_consumers/video_stream.py` | WebSocket consumer for progress channel |
| `farajayangu_be/settings/base.py` | HLS config, R2 credentials, Celery config |
| `docker-compose.yml` | `celery_video_worker` service (prefork, concurrency=1, 4GB RAM) |

### 2.3 Video Model — Processing State Fields

```python
class Video(BaseModel):
    # Processing pipeline state
    processing_status   = CharField  # pending | assembling | processing | completed | failed | killed
    processing_stage    = CharField  # idle | assembling | downloading | converting | uploading
    processing_progress = IntegerField  # 0-100
    processing_message  = CharField
    processing_error    = TextField
    processing_checkpoint = JSONField  # {"stage": "converting", "completed_variants": ["1080p", "720p"]}

    # Upload tracking
    upload_progress         = IntegerField
    upload_total_chunks     = IntegerField
    upload_completed_chunks = IntegerField

    # Output
    hls_master_playlist = CharField  # "videos/hls/{uid}/master.m3u8"
    hls_path            = CharField  # "videos/hls/{uid}"
    video               = FileField  # Original file (deleted after conversion)
```

### 2.4 FFmpeg Conversion Details

**Quality Presets (hardcoded in `video_processor.py`):**

| Variant | Resolution | Video Bitrate | Audio Bitrate |
|---------|-----------|--------------|--------------|
| 1080p | 1920×1080 | 5000 kbps | 192 kbps |
| 720p | 1280×720 | 2800 kbps | 128 kbps |
| 480p | 854×480 | 1400 kbps | 128 kbps |
| 360p | 640×360 | 800 kbps | 96 kbps |

**Hardware Acceleration (detected at runtime):**
- NVIDIA NVENC (`h264_nvenc`) — Windows/Linux with GPU
- Apple VideoToolbox (`h264_videotoolbox`) — macOS
- Intel Quick Sync (`h264_qsv`) — Intel iGPU
- AMD VAAPI (`h264_vaapi`) — Linux AMD
- Fallback: `libx264` (software)

**FFmpeg Command Pattern (per variant):**
```bash
ffmpeg -i input.mp4 \
  -c:v {encoder} -preset {preset} -b:v {bitrate} \
  -c:a aac -b:a {audio_bitrate} \
  -s {resolution} \
  -hls_time 6 -hls_list_size 0 \
  -hls_segment_filename "{variant}_%03d.ts" \
  -f hls {variant}.m3u8
```

**Processing Modes:**
- **Sequential** (default, production): One variant at a time, all CPU cores per FFmpeg process
- **Parallel** (optional): ThreadPoolExecutor with 1-4 workers, multiple FFmpeg processes

**Settings from `base.py`:**
```python
HLS_SEGMENT_DURATION = 6
HLS_ENCODER_PRESET = 'superfast'
HLS_FFMPEG_THREADS = 0  # auto
HLS_SKIP_UPSCALING = True
HLS_VARIANTS = ['1080p', '720p', '480p', '360p']
HLS_SINGLE_PASS = False
```

### 2.5 Progress Tracking Flow

```
video_processor.py                    socket/utils.py                  WebSocket Consumer
      │                                     │                               │
      │ progress_callback(variant, pct)     │                               │
      ├────────────────────────────────────► │                               │
      │                                     │ channel_layer.group_send()    │
      │                                     ├──────────────────────────────►│
      │                                     │                               │ → Client
      │                                     │                               │
      │                                     │ Video.objects.update()        │
      │                                     │ (DB persistence)             │
```

Progress is mapped to overall percentage:
- Assembly: 0–10%
- Download from R2: 0–15%
- Conversion: 15–70% (spread across variants)
- Upload to R2: 70–95%
- Finalize: 95–100%

### 2.6 Checkpoint & Resume

The `processing_checkpoint` JSONField enables retry resilience:

```json
{
  "stage": "converting",
  "completed_variants": ["1080p", "720p"],
  "local_video_path": "/tmp/video_123_original.mp4"
}
```

On retry, `convert_video_to_hls` reads the checkpoint and skips already-completed variants.

### 2.7 R2 Storage Layout

```
videos/
├── chunks/{video_id}/chunk_0000..chunk_N   # Temporary (deleted after assembly)
├── originals/{filename}.mp4                 # Temporary (deleted after conversion)
└── hls/{video_uid}/
    ├── master.m3u8
    ├── 1080p/1080p.m3u8, 1080p_000.ts, ...
    ├── 720p/...
    ├── 480p/...
    └── 360p/...
```

### 2.8 Current Celery Worker Configuration

```yaml
celery_video_worker:
  command: >
    celery -A farajayangu_be.celery worker -l info
    -Q video_processing --pool=prefork --concurrency=1
    --max-tasks-per-child=5 -n video_worker@%h
  deploy:
    resources:
      limits: { memory: 4G }
      reservations: { memory: 1G }
```

- **Concurrency 1**: Only one FFmpeg job at a time (CPU saturation)
- **Prefork pool**: Separate process per task
- **max-tasks-per-child=5**: Restart worker after 5 tasks (memory leak protection)
- **Soft time limit**: 14,400s (4 hours)
- **Hard time limit**: 18,000s (5 hours)
- **Redis lock**: Prevents duplicate conversion for same video

---

## 3. Problems with the Current Approach

| Problem | Impact |
|---------|--------|
| **Python overhead for CPU-bound work** | FFmpeg subprocess management, progress parsing, and file I/O all go through Python's GIL and interpreter overhead |
| **Monolithic coupling** | Video processing code (1200+ lines) lives inside Django app; scaling conversion means scaling the entire Django image |
| **Single worker bottleneck** | Concurrency=1 means one video at a time; queue backs up during high upload periods |
| **Memory pressure** | 4GB limit on Celery worker shared with Python runtime, boto3, Django ORM — less available for FFmpeg |
| **No independent scaling** | Cannot scale conversion workers independently from API servers |
| **Deployment coupling** | Deploying an API bugfix restarts conversion workers, potentially killing in-progress FFmpeg jobs |
| **Hardware acceleration fragility** | Python detection code for NVENC/VAAPI/QSV is brittle; C++ can link directly to hardware APIs |
| **Error handling in Python subprocess** | FFmpeg stderr parsing for progress is regex-based and fragile |

---

## 4. Proposed C++ Microservice Architecture

```
                          ┌─────────────────────────────────┐
                          │         Django Backend           │
                          │  (API, Auth, Business Logic)     │
                          │                                  │
                          │  ┌───────────────────────────┐   │
                          │  │ Celery: assemble_chunks   │   │
                          │  │ Celery: cleanup tasks     │   │
                          │  │ Celery: Google Drive imp. │   │
                          │  └───────────┬───────────────┘   │
                          │              │                    │
                          │  Publishes conversion job        │
                          │  to Redis/RabbitMQ               │
                          └──────────────┬───────────────────┘
                                         │
                    ┌────────────────────┐│┌────────────────────┐
                    │   Redis / RabbitMQ ││ │  Progress Channel  │
                    │   Job Queue        │││  (Redis PubSub)    │
                    └────────┬───────────┘│└────────┬───────────┘
                             │            │         │
                    ┌────────▼────────────▼─────────▼───────────┐
                    │        C++ Conversion Microservice         │
                    │                                            │
                    │  ┌──────────────┐  ┌───────────────────┐  │
                    │  │ Job Consumer │  │ FFmpeg/libav*     │  │
                    │  │ (queue poll) │  │ Encoding Engine   │  │
                    │  └──────┬───────┘  └───────────────────┘  │
                    │         │                                  │
                    │  ┌──────▼───────┐  ┌───────────────────┐  │
                    │  │ R2/S3 Client │  │ Progress Reporter │  │
                    │  │ (AWS SDK C++)│  │ (Redis publish)   │  │
                    │  └──────────────┘  └───────────────────┘  │
                    └────────────────────────────────────────────┘
                          (Scales horizontally: 1 instance = 1 concurrent job)
```

---

## 5. Separation Boundary — What Moves, What Stays

### Moves to C++ Microservice

| Component | Currently In | Notes |
|-----------|-------------|-------|
| FFmpeg encoding (all 4 variants) | `video_processor.py` | Core of the microservice |
| Hardware acceleration detection | `video_processor.py` → `HardwareAccelerationDetector` | Native C++ detection via libav* |
| Quality preset management | `video_processor.py` → `QUALITY_PRESETS` | Config file or CLI args |
| Master playlist generation | `video_processor.py` → `_create_master_playlist()` | Simple string generation |
| HLS segment creation | FFmpeg subprocess calls | Direct libav* or subprocess |
| Upload HLS output to R2 | `video_processor.py` → upload loop | AWS SDK for C++ |
| Download source MP4 from R2 | `convert_video_to_hls` task | AWS SDK for C++ |
| Progress reporting (per-variant) | `video_processor.py` progress callback | Redis PubSub |
| Local temp file management | Scattered across tasks | Microservice owns its temp dir |

### Stays in Django Backend

| Component | File | Reason |
|-----------|------|--------|
| Chunk upload API | `views.py` | Business logic, auth, presigned URLs |
| Chunk assembly | `tasks.py` → `assemble_chunks_task` | Light I/O work, triggers conversion job |
| Video model & metadata | `models.py` | ORM, business rules |
| Processing status updates | `socket/utils.py` | Django Channels integration |
| WebSocket consumer | `socket_consumers/video_stream.py` | Client-facing, auth-aware |
| HLS playlist proxy & ad injection | `views.py` → `serve_hls_file` | Business logic (ad markers) |
| HLS URL rewriting | `hls_service.py` | Presigned URL generation, backend URLs |
| Google Drive import (download phase) | `google_drive.py` | Auth, URL parsing, then hands off to conversion |
| Video deletion/cleanup | `tasks.py` → `delete_video_files_task` | Simple R2 delete, no FFmpeg |
| Stale chunk cleanup | `tasks.py` → `cleanup_stale_chunks` | Scheduled maintenance |
| All streaming/feed/comment APIs | `views.py` | Business logic |

### Shared Contract (Interface)

The **conversion job message** is the contract between Django and the C++ microservice:

```json
{
  "job_id": "uuid-v4",
  "video_id": 123,
  "video_uid": "abc-def-ghi",
  "source": {
    "type": "r2",
    "bucket": "farajatv-media",
    "key": "videos/originals/video_123.mp4",
    "endpoint": "https://xxx.r2.cloudflarestorage.com"
  },
  "output": {
    "bucket": "farajatv-media",
    "base_path": "videos/hls/abc-def-ghi",
    "endpoint": "https://xxx.r2.cloudflarestorage.com"
  },
  "variants": [
    {"name": "1080p", "resolution": "1920x1080", "video_bitrate": "5000k", "audio_bitrate": "192k"},
    {"name": "720p",  "resolution": "1280x720",  "video_bitrate": "2800k", "audio_bitrate": "128k"},
    {"name": "480p",  "resolution": "854x480",   "video_bitrate": "1400k", "audio_bitrate": "128k"},
    {"name": "360p",  "resolution": "640x360",   "video_bitrate": "800k",  "audio_bitrate": "96k"}
  },
  "options": {
    "segment_duration": 6,
    "encoder_preset": "superfast",
    "skip_upscaling": true,
    "threads": 0,
    "prefer_hardware": true
  },
  "credentials": {
    "r2_access_key_id": "...",
    "r2_secret_access_key": "..."
  },
  "checkpoint": {
    "completed_variants": ["1080p"]
  }
}
```

---

## 6. Communication Protocol

### 6.1 Job Submission (Django → Microservice)

**Option A: Redis Queue (recommended for simplicity)**
- Django pushes job JSON to a Redis list: `LPUSH conversion_jobs <json>`
- C++ microservice pops: `BRPOP conversion_jobs 0`
- Pros: Already have Redis infrastructure, simple, low latency
- Cons: No built-in retry/dead-letter; must implement manually

**Option B: RabbitMQ**
- Django publishes to `conversion_jobs` exchange
- C++ consumes from bound queue
- Pros: Acknowledgements, dead-letter queues, priority queues
- Cons: New infrastructure dependency

**Recommendation:** Start with Redis (Option A) since it's already in the stack. Add RabbitMQ later if reliability requirements increase.

### 6.2 Progress Reporting (Microservice → Django)

```
C++ Microservice                      Django Backend
      │                                     │
      │ PUBLISH conversion_progress:{id}    │
      │ {"variant":"720p","progress":45}    │
      ├────────────────────────────────────►│
      │                                     │ (Celery listener or
      │                                     │  async Redis subscriber)
      │                                     │
      │                                     │ send_video_progress()
      │                                     │ → Django Channels
      │                                     │ → WebSocket → Client
```

Progress message format:
```json
{
  "job_id": "uuid",
  "video_id": 123,
  "type": "progress|complete|error",
  "stage": "downloading|converting|uploading",
  "progress": 45,
  "message": "Converting 720p: 60%",
  "variants": {
    "1080p": {"status": "completed", "progress": 100},
    "720p": {"status": "processing", "progress": 60}
  },
  "error": null
}
```

### 6.3 Completion Callback (Microservice → Django)

On completion, the microservice publishes a final message:

```json
{
  "job_id": "uuid",
  "video_id": 123,
  "type": "complete",
  "hls_path": "videos/hls/abc-def-ghi",
  "master_playlist": "videos/hls/abc-def-ghi/master.m3u8",
  "variants_created": ["1080p", "720p", "480p", "360p"],
  "duration_seconds": 342.5,
  "source_deleted": true
}
```

Django listener updates the `Video` model:
```python
Video.objects.filter(id=msg['video_id']).update(
    processing_status='completed',
    processing_stage='idle',
    processing_progress=100,
    hls_path=msg['hls_path'],
    hls_master_playlist=msg['master_playlist'],
)
send_video_complete(msg['video_id'], "Processing complete", msg['hls_path'])
```

---

## 7. C++ Microservice Technical Design

### 7.1 Recommended Tech Stack

| Component | Library | Reason |
|-----------|---------|--------|
| **FFmpeg integration** | `libavformat`, `libavcodec`, `libswscale` (FFmpeg C API) or subprocess | Direct API = no process spawning overhead, better error handling |
| **HTTP/S3 client** | AWS SDK for C++ (`aws-sdk-cpp`) | Official, well-maintained, handles multipart upload |
| **Redis client** | `hiredis` + `redis-plus-plus` | Fast, widely used, supports PubSub |
| **JSON parsing** | `nlohmann/json` | Header-only, intuitive API |
| **Threading** | `std::thread` + `std::mutex` | Standard library, no external dependency |
| **Build system** | CMake | Industry standard for C++ |
| **Logging** | `spdlog` | Fast, header-only option |
| **Config** | Environment variables + JSON config file | 12-factor app compatible |

### 7.2 Module Structure

```
conversion-service/
├── CMakeLists.txt
├── Dockerfile
├── config/
│   └── default.json          # Default quality presets, timeouts
├── src/
│   ├── main.cpp              # Entry point, signal handling, graceful shutdown
│   ├── job_consumer.cpp      # Redis BRPOP loop, job deserialization
│   ├── job_consumer.h
│   ├── converter.cpp         # FFmpeg encoding pipeline
│   ├── converter.h
│   ├── hw_detect.cpp         # Hardware acceleration detection
│   ├── hw_detect.h
│   ├── s3_client.cpp         # R2/S3 download & upload
│   ├── s3_client.h
│   ├── progress_reporter.cpp # Redis PubSub progress publishing
│   ├── progress_reporter.h
│   ├── playlist.cpp          # HLS master playlist generation
│   ├── playlist.h
│   └── utils/
│       ├── temp_dir.cpp      # RAII temp directory management
│       └── config.cpp        # Config loader
└── tests/
    ├── test_converter.cpp
    ├── test_playlist.cpp
    └── test_hw_detect.cpp
```

### 7.3 Core Processing Loop (Pseudocode)

```cpp
int main() {
    auto config = Config::from_env();
    auto redis = RedisClient(config.redis_url);
    auto s3 = S3Client(config.r2_endpoint, config.r2_credentials);

    signal(SIGTERM, graceful_shutdown);
    signal(SIGINT, graceful_shutdown);

    while (!shutdown_requested) {
        // Block until job available (timeout 5s for shutdown check)
        auto job_json = redis.brpop("conversion_jobs", 5);
        if (!job_json) continue;

        auto job = Job::from_json(job_json);
        auto reporter = ProgressReporter(redis, job.video_id, job.job_id);

        try {
            // 1. Download source from R2
            reporter.report("downloading", 0, "Downloading source video");
            auto local_path = s3.download(job.source.bucket, job.source.key, temp_dir);
            reporter.report("downloading", 100, "Download complete");

            // 2. Detect hardware acceleration
            auto encoder = HWDetect::best_encoder();

            // 3. Convert each variant
            for (auto& variant : job.variants) {
                if (job.checkpoint.is_completed(variant.name)) continue;
                if (job.options.skip_upscaling && source_height < variant.height) continue;

                reporter.report("converting", variant_progress, "Converting " + variant.name);

                Converter::encode_variant(local_path, output_dir, variant, encoder, job.options,
                    [&](int pct) { reporter.report_variant(variant.name, pct); });

                reporter.mark_variant_complete(variant.name);
            }

            // 4. Generate master playlist
            Playlist::create_master(output_dir, job.variants);

            // 5. Upload HLS directory to R2
            reporter.report("uploading", 0, "Uploading HLS files");
            s3.upload_directory(output_dir, job.output.bucket, job.output.base_path,
                [&](int pct) { reporter.report("uploading", pct, "Uploading..."); });

            // 6. Delete source MP4 from R2
            s3.delete_object(job.source.bucket, job.source.key);

            // 7. Report completion
            reporter.complete(job.output.base_path);

        } catch (const std::exception& e) {
            reporter.error(e.what());
        }

        // Cleanup temp files (RAII handles this)
    }
}
```

### 7.4 FFmpeg Integration Approach

**Option A: libav* C API (recommended for production)**

```cpp
// Direct API usage — no subprocess, no stderr parsing
AVFormatContext* input_ctx = nullptr;
avformat_open_input(&input_ctx, input_path.c_str(), nullptr, nullptr);
avformat_find_stream_info(input_ctx, nullptr);

// Configure output per variant
AVFormatContext* output_ctx = nullptr;
avformat_alloc_output_context2(&output_ctx, nullptr, "hls", output_path.c_str());

// Set HLS options
av_opt_set(output_ctx->priv_data, "hls_time", "6", 0);
av_opt_set(output_ctx->priv_data, "hls_list_size", "0", 0);
av_opt_set(output_ctx->priv_data, "hls_segment_filename", pattern.c_str(), 0);

// Encode with progress callback via packet count / duration
```

Pros: No process spawning, direct error codes, accurate progress from packet timestamps, hardware codec enum via `avcodec_find_encoder_by_name()`.

**Option B: FFmpeg subprocess (simpler, faster to implement)**

```cpp
std::string cmd = fmt::format(
    "ffmpeg -i {} -c:v {} -preset {} -b:v {} -c:a aac -b:a {} "
    "-s {} -hls_time {} -hls_list_size 0 "
    "-hls_segment_filename {} -f hls {} -progress pipe:1",
    input, encoder, preset, vbitrate, abitrate, resolution, seg_dur, seg_pattern, output);

// Parse -progress pipe:1 output for frame/fps/speed
auto proc = Process::spawn(cmd);
while (auto line = proc.read_line()) {
    if (line.starts_with("out_time_ms=")) {
        int64_t us = std::stoll(line.substr(12));
        int pct = (us * 100) / (duration_us);
        progress_cb(pct);
    }
}
```

Pros: Simpler, mirrors current Python approach, easier to debug.  
Cons: Process overhead, stderr parsing.

**Recommendation:** Start with Option B (subprocess) for faster delivery, migrate to Option A for performance-critical deployments.

---

## 8. Database & State Management

The C++ microservice **does NOT access the database directly**. All state flows through messages:

```
Django (owns DB)  ◄─── messages ───►  C++ Microservice (stateless)
```

### State Update Flow

| Event | Who Updates DB | How |
|-------|---------------|-----|
| Job submitted | Django (before publishing) | `Video.processing_status = 'processing'` |
| Progress update | Django (listener) | `Video.processing_progress = X` |
| Variant completed | Django (listener) | `Video.processing_checkpoint['completed_variants'].append(...)` |
| Job completed | Django (listener) | `Video.processing_status = 'completed'`, `hls_path = ...` |
| Job failed | Django (listener) | `Video.processing_status = 'failed'`, `processing_error = ...` |

### Django-Side Listener

New Celery task or async subscriber that listens to `conversion_progress:*`:

```python
# apps/streaming/tasks/conversion_listener.py

@shared_task(queue='general')
def listen_conversion_progress():
    """Long-running task that subscribes to conversion progress channel."""
    redis = get_redis_connection()
    pubsub = redis.pubsub()
    pubsub.psubscribe('conversion_progress:*')

    for message in pubsub.listen():
        if message['type'] != 'pmessage':
            continue
        data = json.loads(message['data'])
        handle_conversion_event(data)

def handle_conversion_event(data):
    video_id = data['video_id']
    if data['type'] == 'progress':
        update_video_progress_db(video_id, data['stage'], data['progress'], data['message'])
        send_video_progress(video_id, data['stage'], data['progress'], data['message'], 'processing')
    elif data['type'] == 'complete':
        Video.objects.filter(id=video_id).update(
            processing_status='completed', hls_path=data['hls_path'],
            hls_master_playlist=data['master_playlist'], processing_progress=100)
        send_video_complete(video_id, "Processing complete", data['hls_path'])
    elif data['type'] == 'error':
        Video.objects.filter(id=video_id).update(
            processing_status='failed', processing_error=data['error'])
        send_video_error(video_id, "Processing failed", data['error'])
```

---

## 9. Storage Interaction

Both Django and the C++ microservice interact with the same R2 bucket:

```
                    Cloudflare R2 Bucket
                    ┌──────────────────────────────────┐
                    │                                    │
  Django writes:    │  videos/chunks/{id}/chunk_NNNN    │
  Django writes:    │  videos/originals/{filename}.mp4  │
                    │                                    │
  C++ reads:        │  videos/originals/{filename}.mp4  │  ← Download source
  C++ writes:       │  videos/hls/{uid}/master.m3u8     │  ← Upload output
  C++ writes:       │  videos/hls/{uid}/{variant}/*.ts  │
  C++ deletes:      │  videos/originals/{filename}.mp4  │  ← Cleanup source
                    │                                    │
  Django reads:     │  videos/hls/{uid}/*               │  ← Serve to clients
  Django deletes:   │  videos/hls/{uid}/*               │  ← Video deletion
                    └──────────────────────────────────┘
```

R2 credentials are passed in the job message (not hardcoded in the microservice), allowing multi-tenant or credential rotation without redeploying the microservice.

---

## 10. Deployment Strategy

### 10.1 Docker Image

```dockerfile
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavcodec-dev libavformat-dev libswscale-dev \
    libhiredis-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/conversion-service /usr/local/bin/conversion-service

ENV REDIS_URL=redis://redis:6379/0
ENV TEMP_DIR=/tmp/conversions
ENV LOG_LEVEL=info
ENV MAX_CONCURRENT_JOBS=1

RUN mkdir -p /tmp/conversions

ENTRYPOINT ["conversion-service"]
```

### 10.2 Docker Compose Addition

```yaml
  conversion_service:
    build:
      context: ./conversion-service
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      REDIS_URL: 'redis://redis:6379/0'
      TEMP_DIR: '/tmp/conversions'
      LOG_LEVEL: 'info'
    volumes:
      - conversion_temp:/tmp/conversions
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '4'
        reservations:
          memory: 1G
          cpus: '2'
    depends_on:
      redis:
        condition: service_healthy
```

### 10.3 Scaling

```yaml
  # Scale horizontally: each instance handles 1 job at a time
  conversion_service:
    deploy:
      replicas: 3  # 3 concurrent video conversions
```

Or with Kubernetes:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: conversion-service
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: converter
          resources:
            requests: { cpu: "2", memory: "2Gi" }
            limits: { cpu: "4", memory: "4Gi" }
```

---

## 11. Migration Plan

### Phase 1: Build & Test C++ Microservice (2-3 weeks)

1. Set up C++ project with CMake, dependencies (hiredis, aws-sdk-cpp, nlohmann/json, spdlog)
2. Implement job consumer (Redis BRPOP)
3. Implement FFmpeg subprocess wrapper with progress parsing
4. Implement R2 download/upload via AWS SDK
5. Implement master playlist generation
6. Implement progress reporting via Redis PubSub
7. Unit tests + integration tests with local MinIO

### Phase 2: Django Integration (1 week)

1. Add `conversion_listener` task/subscriber in Django
2. Modify `convert_video_to_hls` to publish job to Redis queue instead of running FFmpeg
3. Keep old code path behind a feature flag: `USE_CPP_CONVERTER=true/false`
4. Test end-to-end: upload → assembly → job publish → C++ converts → Django receives completion

### Phase 3: Shadow Mode (1 week)

1. Run both old Celery worker and C++ microservice in parallel
2. Route 10% of jobs to C++ microservice
3. Compare: processing time, output quality (segment counts, bitrates), error rates
4. Monitor memory/CPU usage on C++ service

### Phase 4: Full Cutover (1 week)

1. Route 100% of jobs to C++ microservice
2. Remove `celery_video_worker` service from docker-compose
3. Remove `video_processor.py` (1200+ lines) from Django codebase
4. Clean up feature flags

### Changes to Existing Django Code

**`apps/streaming/tasks/tasks.py` — `convert_video_to_hls`:**

```python
# BEFORE: Runs FFmpeg in-process
@shared_task(bind=True, queue='video_processing')
def convert_video_to_hls(self, video_id, local_video_path=None):
    processor = VideoProcessor(video)
    processor.process(local_video_path)

# AFTER: Publishes job to queue
@shared_task(bind=True, queue='general')
def convert_video_to_hls(self, video_id, local_video_path=None):
    video = Video.objects.get(id=video_id)
    if settings.USE_CPP_CONVERTER:
        publish_conversion_job(video, local_video_path)
    else:
        # Legacy path
        processor = VideoProcessor(video)
        processor.process(local_video_path)
```

**New: `apps/streaming/services/conversion_client.py`:**

```python
def publish_conversion_job(video, local_video_path=None):
    """Publish a conversion job to the C++ microservice queue."""
    source_key = local_video_path or video.video.name
    job = {
        "job_id": str(uuid.uuid4()),
        "video_id": video.id,
        "video_uid": str(video.uid),
        "source": {
            "type": "r2",
            "bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "key": source_key,
            "endpoint": settings.AWS_S3_ENDPOINT_URL,
        },
        "output": {
            "bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "base_path": f"videos/hls/{video.slug or video.uid}",
            "endpoint": settings.AWS_S3_ENDPOINT_URL,
        },
        "variants": [
            {"name": v["name"], "resolution": v["resolution"],
             "video_bitrate": v["video_bitrate"], "audio_bitrate": v["audio_bitrate"]}
            for v in QUALITY_PRESETS
            if v["name"] in settings.HLS_VARIANTS
        ],
        "options": {
            "segment_duration": settings.HLS_SEGMENT_DURATION,
            "encoder_preset": settings.HLS_ENCODER_PRESET,
            "skip_upscaling": settings.HLS_SKIP_UPSCALING,
            "threads": settings.HLS_FFMPEG_THREADS,
            "prefer_hardware": True,
        },
        "credentials": {
            "r2_access_key_id": settings.AWS_ACCESS_KEY_ID,
            "r2_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
        },
        "checkpoint": video.processing_checkpoint or {},
    }
    redis_client.lpush("conversion_jobs", json.dumps(job))
    Video.objects.filter(id=video.id).update(processing_status='processing', processing_stage='queued')
```

---

## 12. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| C++ development time longer than expected | Medium | Start with subprocess FFmpeg, not libav* API |
| Progress reporting latency | Low | Redis PubSub is sub-millisecond; same as current approach |
| Credential exposure in job messages | Medium | Use short-lived STS tokens or a secrets manager; encrypt Redis transport (TLS) |
| Orphaned jobs (microservice crashes mid-conversion) | Medium | Heartbeat mechanism: microservice publishes heartbeat every 30s; Django marks jobs as `failed` if no heartbeat for 5 minutes |
| R2 partial uploads on crash | Low | Use unique temp paths per job; cleanup cron deletes incomplete HLS dirs |
| Checkpoint compatibility | Low | Same JSON schema as current `processing_checkpoint` |
| Local disk space on C++ container | Medium | Pre-check disk space; limit temp dir size; alert on low space |
| Feature parity gaps | Medium | Shadow mode (Phase 3) catches differences before cutover |

---

## 13. Open Questions

1. **libav* API vs subprocess** — Do we want maximum performance (libav*) or faster development (subprocess)? Subprocess mirrors current approach and is lower risk.

2. **Redis vs RabbitMQ** — Redis is simpler and already in our stack. RabbitMQ adds reliability guarantees (ack, dead-letter, priority). Which do we prefer?

3. **GPU support** — Our current prod server has no GPU. Do we plan to add one? If yes, the C++ microservice should link against CUDA/NVENC from day one.

4. **Multi-tenancy** — Will this microservice serve only FarajaTV or multiple projects? This affects credential management and job isolation.

5. **Monitoring** — What metrics do we want? Suggestions:
   - Jobs processed / hour
   - Average conversion time per variant
   - Queue depth (backlog)
   - FFmpeg CPU/memory usage
   - Error rate by variant

6. **Alternative: Rust instead of C++?** — Rust offers similar performance with memory safety guarantees, better dependency management (Cargo), and excellent FFmpeg bindings (`ffmpeg-next` crate). Worth discussing.

7. **Alternative: Go with cgo?** — Simpler concurrency model, good S3 SDKs, but FFmpeg integration requires cgo which adds complexity.

8. **Chunk assembly** — Should chunk assembly also move to the microservice? Currently it's I/O-bound (download chunks, concatenate, upload) and fits well in Celery. Moving it would reduce one network round-trip (assembled MP4 doesn't need to go through R2 before conversion).

---

## Appendix A: Current Performance Baseline

Collect these metrics before starting migration to measure improvement:

```
- Average time: chunk assembly (per video size tier: <100MB, 100-500MB, 500MB-2GB, >2GB)
- Average time: FFmpeg conversion per variant per video size
- Average time: HLS upload to R2 per video size
- Peak memory usage during conversion
- CPU utilization during conversion
- Queue wait time (time from job submission to processing start)
- Error/retry rate
```

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| HLS | HTTP Live Streaming — Apple's adaptive bitrate protocol |
| R2 | Cloudflare R2 — S3-compatible object storage |
| Variant | A specific quality level (e.g., 720p) of the HLS output |
| Segment | A `.ts` file representing ~6 seconds of video |
| Master playlist | `master.m3u8` — lists all available variants with bandwidth info |
| Presigned URL | Time-limited URL granting temporary access to a private R2 object |
| NVENC | NVIDIA's hardware video encoder |
| VAAPI | Video Acceleration API — Linux hardware encoding interface |
| libav* | FFmpeg's C libraries for media processing |
