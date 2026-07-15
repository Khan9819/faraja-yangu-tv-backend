# Video Processing Performance Improvements

This document describes the performance improvements made to the video processing pipeline for HLS conversion.

## Overview

The video processor has been enhanced with three major improvements:

1. **Hardware Acceleration** - Auto-detection and use of GPU encoding
2. **Parallel Variant Processing** - Process multiple quality variants simultaneously
3. **Enhanced Progress Tracking** - Per-variant progress in consolidated WebSocket updates

---

## 1. Hardware Acceleration

### Supported Accelerators

| Accelerator | Encoder | Platform | Expected Speedup |
|-------------|---------|----------|------------------|
| **NVIDIA NVENC** | `h264_nvenc` | Windows/Linux with NVIDIA GPU | 3-10x |
| **Apple VideoToolbox** | `h264_videotoolbox` | macOS | 2-5x |
| **Intel Quick Sync** | `h264_qsv` | Windows/Linux with Intel CPU | 2-4x |
| **VAAPI** | `h264_vaapi` | Linux | 2-4x |

### How It Works

The `HardwareAccelerationDetector` class:

1. Detects the operating system
2. Tests available encoders in priority order
3. Validates encoder functionality with a quick test encode
4. Falls back to software encoding (`libx264`) if no hardware is available

```python
# Auto-detection happens during VideoProcessor initialization
processor = VideoProcessor(
    input_path="/path/to/video.mp4",
    output_dir="/path/to/output",
    use_hardware_acceleration=True  # Default: True
)

# Check what was detected
print(processor.hw_accel.name if processor.hw_accel else "Software encoding")
```

### Disabling Hardware Acceleration

```python
processor = VideoProcessor(
    input_path="/path/to/video.mp4",
    output_dir="/path/to/output",
    use_hardware_acceleration=False  # Force software encoding
)
```

---

## 2. Parallel Variant Processing

### The Problem

Previously, variants (1080p, 720p, 480p, 360p) were processed sequentially. For a 10-minute video:

- 1080p: ~5 min
- 720p: ~4 min
- 480p: ~3 min
- 360p: ~2 min
- **Total: ~14 minutes**

### The Solution

With parallel processing (2 workers):

- Batch 1: 1080p + 720p in parallel: ~5 min
- Batch 2: 480p + 360p in parallel: ~3 min
- **Total: ~8 minutes** (43% faster)

### Configuration

```python
# Get system-recommended workers (conservative: 1 per 4 CPU cores, max 2)
workers = VideoProcessor.get_recommended_parallel_workers()

processor = VideoProcessor(
    input_path="/path/to/video.mp4",
    output_dir="/path/to/output",
    parallel_variants=workers  # Default: 1 (sequential)
)
```

### Resource Considerations

| Workers | CPU Usage | Memory | Best For |
|---------|-----------|--------|----------|
| 1 | Low | ~2GB | Limited resources, shared servers |
| 2 | Medium | ~4GB | Dedicated encoding servers |
| 4 | High | ~8GB | High-end machines with 16+ cores |

**Note:** FFmpeg already uses multiple threads internally, so more workers doesn't always mean faster encoding. The recommended value is conservative to avoid resource exhaustion.

---

## 3. Enhanced Progress Tracking

### Per-Variant Progress

The new system tracks progress for each variant individually and sends consolidated updates via WebSocket.

### WebSocket Payload Structure

```json
{
    "type": "video_progress",
    "video_id": 123,
    "stage": "converting",
    "progress": 45,
    "message": "Converting 720p: 60%",
    "status": "processing",
    "variants": {
        "1080p": {
            "name": "1080p",
            "status": "completed",
            "progress": 100,
            "message": "1080p complete"
        },
        "720p": {
            "name": "720p",
            "status": "processing",
            "progress": 60,
            "message": "Converting 720p: 60%"
        },
        "480p": {
            "name": "480p",
            "status": "processing",
            "progress": 30,
            "message": "Converting 480p: 30%"
        },
        "360p": {
            "name": "360p",
            "status": "pending",
            "progress": 0,
            "message": ""
        }
    }
}
```

### Variant Status Values

- `pending` - Not started yet
- `processing` - Currently encoding
- `completed` - Successfully finished
- `failed` - Error occurred

### Using the Callback

```python
def my_variant_callback(overall_progress: int, message: str, variants_progress: dict):
    # overall_progress: 0-100 (maps to 20-70% of total pipeline)
    # message: Current status message
    # variants_progress: Dict of variant_name -> VariantProgress
    
    for name, vp in variants_progress.items():
        print(f"{name}: {vp.progress}% - {vp.status}")

processor = VideoProcessor(
    input_path="/path/to/video.mp4",
    output_dir="/path/to/output",
    variant_progress_callback=my_variant_callback
)
```

---

## API Changes

### VideoProcessor.__init__()

New parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `use_hardware_acceleration` | `bool` | `True` | Enable GPU acceleration detection |
| `parallel_variants` | `int` | `1` | Number of variants to process in parallel |
| `variant_progress_callback` | `Callable` | `None` | Callback for consolidated variant progress |

### send_video_progress()

New parameter:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `variants_progress` | `dict` | `None` | Per-variant progress data to include in WebSocket payload |

### New Classes

- `HardwareAccelerator` - Dataclass for accelerator configuration
- `HardwareAccelerationDetector` - Detects available hardware encoders
- `VariantProgress` - Dataclass for tracking individual variant progress

---

## Performance Benchmarks

Estimated improvements for a 10-minute 1080p source video:

| Configuration | Time | Speedup |
|---------------|------|---------|
| Sequential + Software | ~14 min | 1x (baseline) |
| Sequential + NVENC | ~3 min | 4.7x |
| Parallel (2) + Software | ~8 min | 1.75x |
| Parallel (2) + NVENC | ~2 min | 7x |

*Actual results vary based on hardware, video complexity, and system load.*

---

## Backward Compatibility

All changes are backward compatible:

- Default behavior unchanged (sequential processing, auto hardware detection)
- Legacy `progress_callback` still works alongside new `variant_progress_callback`
- WebSocket clients not expecting `variants` field will continue to work

---

## Files Modified

- `apps/streaming/services/video_processor.py` - Core processing improvements
- `apps/streaming/socket/utils.py` - Enhanced progress updates
- `apps/streaming/tasks/tasks.py` - Task integration with new features

---

## Future Improvements

1. **Adaptive parallelism** - Dynamically adjust workers based on system load
2. **Two-pass encoding** - Option for higher quality at cost of speed
3. **Segment-level parallelism** - Split video into chunks for distributed encoding
4. **Progress persistence** - Store variant progress in database for resume
