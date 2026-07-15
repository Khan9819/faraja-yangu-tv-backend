# Video Processing Progress WebSocket

Real-time progress updates for video assembly and HLS conversion via WebSocket.

## Overview

When a video is uploaded and processed, the backend sends real-time progress updates through a WebSocket connection. This allows the admin dashboard to show live progress bars and status messages.

---

## Connection

### Endpoint

```
wss://<your-domain>/socket/stream/progress/<video_id>/?token=<jwt_access_token>
```

### Authentication

The WebSocket requires a valid JWT access token passed as a query parameter.

```javascript
const videoId = 123;
const accessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...';

const ws = new WebSocket(
  `wss://api.example.com/socket/stream/progress/${videoId}/?token=${accessToken}`
);
```

### Connection Errors

| Close Code | Meaning |
|------------|---------|
| 4001 | Authentication failed (invalid/missing token) |
| 1000 | Normal closure |

---

## Message Types

All messages are JSON objects with a `type` field.

### 1. Connection Confirmation

Sent immediately after successful connection.

```json
{
  "type": "connection",
  "status": "connected",
  "message": "Connected to video progress stream",
  "video_id": 123
}
```

### 2. Progress Update

Sent during video processing with progress percentage.

```json
{
  "type": "progress",
  "stage": "assembling",
  "progress": 45,
  "message": "Reading chunk 5/10",
  "video_id": 123,
  "status": "processing"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `stage` | string | Current stage: `"assembling"` or `"converting"` |
| `progress` | number | Progress percentage (0-100) |
| `message` | string | Human-readable status message |
| `status` | string | Always `"processing"` during progress |

### 3. Completion

Sent when video processing is complete.

```json
{
  "type": "complete",
  "status": "completed",
  "message": "Video processing completed successfully",
  "video_id": 123,
  "hls_path": "videos/hls/abc123-uid"
}
```

### 4. Error

Sent if processing fails.

```json
{
  "type": "error",
  "status": "failed",
  "message": "HLS conversion failed",
  "video_id": 123,
  "error": "FFmpeg error: ..."
}
```

---

## Processing Stages

### Stage 1: Assembling (0-100%)

Combines uploaded chunks into a single video file.

| Progress | Activity |
|----------|----------|
| 0% | Starting chunk assembly |
| 5% | Found chunks, preparing |
| 10-50% | Reading and combining chunks |
| 55% | Saving assembled video |
| 70% | Cleaning up chunks |
| 100% | Assembly complete |

### Stage 2: Converting (0-100%)

Converts the video to HLS format with multiple quality levels.

| Progress | Activity |
|----------|----------|
| 0% | Starting HLS conversion |
| 5% | Downloading from storage |
| 15% | Download complete |
| 20% | FFmpeg conversion running |
| 70% | Conversion complete |
| 90% | Uploading HLS files to storage |
| 100% | Complete |

---

## Frontend Implementation

### React Example

```jsx
import { useEffect, useState, useRef } from 'react';

function VideoUploadProgress({ videoId, accessToken }) {
  const [stage, setStage] = useState('');
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('Waiting...');
  const [status, setStatus] = useState('pending');
  const wsRef = useRef(null);

  useEffect(() => {
    if (!videoId || !accessToken) return;

    const wsUrl = `wss://api.example.com/socket/stream/progress/${videoId}/?token=${accessToken}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'connection':
          setStatus('connected');
          setMessage(data.message);
          break;

        case 'progress':
          setStage(data.stage);
          setProgress(data.progress);
          setMessage(data.message);
          setStatus('processing');
          break;

        case 'complete':
          setStatus('completed');
          setProgress(100);
          setMessage(data.message);
          break;

        case 'error':
          setStatus('failed');
          setMessage(data.message);
          break;
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setStatus('error');
      setMessage('Connection error');
    };

    ws.onclose = (event) => {
      if (event.code === 4001) {
        setStatus('error');
        setMessage('Authentication failed');
      }
    };

    return () => {
      ws.close();
    };
  }, [videoId, accessToken]);

  return (
    <div className="video-progress">
      <div className="stage">{stage || 'Waiting'}</div>
      <div className="progress-bar">
        <div 
          className="progress-fill" 
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="progress-text">{progress}%</div>
      <div className="message">{message}</div>
      <div className={`status status-${status}`}>{status}</div>
    </div>
  );
}

export default VideoUploadProgress;
```

### Vanilla JavaScript Example

```javascript
class VideoProgressTracker {
  constructor(videoId, accessToken, callbacks = {}) {
    this.videoId = videoId;
    this.accessToken = accessToken;
    this.callbacks = callbacks;
    this.ws = null;
  }

  connect() {
    const url = `wss://api.example.com/socket/stream/progress/${this.videoId}/?token=${this.accessToken}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'progress' && this.callbacks.onProgress) {
        this.callbacks.onProgress(data.stage, data.progress, data.message);
      }
      
      if (data.type === 'complete' && this.callbacks.onComplete) {
        this.callbacks.onComplete(data.hls_path);
      }
      
      if (data.type === 'error' && this.callbacks.onError) {
        this.callbacks.onError(data.message, data.error);
      }
    };

    this.ws.onerror = (error) => {
      if (this.callbacks.onError) {
        this.callbacks.onError('Connection error', error);
      }
    };

    this.ws.onclose = (event) => {
      if (event.code === 4001 && this.callbacks.onError) {
        this.callbacks.onError('Authentication failed');
      }
    };
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

// Usage
const tracker = new VideoProgressTracker(123, 'jwt-token', {
  onProgress: (stage, progress, message) => {
    console.log(`${stage}: ${progress}% - ${message}`);
    document.getElementById('progress-bar').style.width = `${progress}%`;
    document.getElementById('status-text').textContent = message;
  },
  onComplete: (hlsPath) => {
    console.log('Video ready!', hlsPath);
    alert('Video processing complete!');
  },
  onError: (message, error) => {
    console.error('Error:', message, error);
    alert(`Error: ${message}`);
  }
});

tracker.connect();
```

---

## Complete Upload Flow

```javascript
async function uploadVideoWithProgress(file, videoData, accessToken) {
  // Step 1: Create video record
  const { data: video } = await api.post('/streaming/create-video/', videoData);
  const videoId = video.id;

  // Step 2: Connect to progress WebSocket
  const ws = new WebSocket(
    `wss://api.example.com/socket/stream/progress/${videoId}/?token=${accessToken}`
  );

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    updateProgressUI(data);
  };

  // Step 3: Upload chunks
  const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  for (let i = 0; i < totalChunks; i++) {
    const chunk = file.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);

    // Get presigned URL
    const { data: urlData } = await api.post('/streaming/get-chunk-upload-url/', {
      videoId,
      chunkIndex: i,
      totalChunks
    });

    // Upload directly to R2
    await fetch(urlData.upload_url, {
      method: 'PUT',
      body: chunk,
      headers: { 'Content-Type': 'application/octet-stream' }
    });

    console.log(`Uploaded chunk ${i + 1}/${totalChunks}`);
  }

  // Step 4: Trigger assembly (progress updates come via WebSocket)
  await api.post('/streaming/assemble-chunks/', {
    videoId,
    fileName: file.name
  });

  // WebSocket will receive progress updates for assembly and HLS conversion
  // Close WebSocket when 'complete' or 'error' message is received
}
```

---

## Error Handling

```javascript
ws.onclose = (event) => {
  switch (event.code) {
    case 4001:
      // Token invalid or expired - refresh token and reconnect
      refreshTokenAndReconnect();
      break;
    case 1000:
      // Normal closure
      break;
    default:
      // Unexpected closure - attempt reconnect
      setTimeout(() => reconnect(), 3000);
  }
};
```

---

## Notes

- WebSocket connection should be established **after** creating the video record but **before** calling assemble-chunks
- The connection will receive updates for both assembly and HLS conversion stages
- Close the WebSocket after receiving `complete` or `error` message
- Token expiry during long processing: consider using a long-lived token or implementing reconnection with token refresh
