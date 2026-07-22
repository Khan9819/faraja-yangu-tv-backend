"""
Video processing service for HLS conversion with adaptive bitrate streaming.
Converts uploaded MP4 videos to HLS format with multiple quality levels.

Features:
- Hardware acceleration detection (NVENC, VideoToolbox, VAAPI, QSV)
- Parallel variant processing with configurable concurrency
- Per-variant progress tracking
- Resume capability from checkpoints
"""
import os
import subprocess
import logging
import shutil
import re
import gc
import platform
from pathlib import Path
from typing import Dict, List, Tuple, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class HardwareAccelerator:
    """Hardware acceleration configuration."""
    name: str
    encoder: str
    decoder: str = ""
    extra_input_args: List[str] = field(default_factory=list)
    extra_output_args: List[str] = field(default_factory=list)
    supported: bool = False


class HardwareAccelerationDetector:
    """
    Detects available hardware acceleration for video encoding.
    Supports NVIDIA NVENC, Apple VideoToolbox, Intel QSV, and AMD VAAPI.
    """
    
    ACCELERATORS = {
        'nvenc': HardwareAccelerator(
            name='NVIDIA NVENC',
            encoder='h264_nvenc',
            decoder='h264_cuvid',
            extra_input_args=['-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda'],
            extra_output_args=['-preset', 'p4', '-tune', 'hq', '-rc', 'vbr']
        ),
        'videotoolbox': HardwareAccelerator(
            name='Apple VideoToolbox',
            encoder='h264_videotoolbox',
            decoder='',
            extra_input_args=[],
            extra_output_args=['-allow_sw', '1', '-realtime', '0']
        ),
        'qsv': HardwareAccelerator(
            name='Intel Quick Sync',
            encoder='h264_qsv',
            decoder='h264_qsv',
            extra_input_args=['-hwaccel', 'qsv'],
            extra_output_args=['-preset', 'faster']
        ),
        'vaapi': HardwareAccelerator(
            name='VAAPI (Linux)',
            encoder='h264_vaapi',
            decoder='',
            extra_input_args=['-hwaccel', 'vaapi', '-hwaccel_device', '/dev/dri/renderD128', '-hwaccel_output_format', 'vaapi'],
            extra_output_args=['-vf', 'format=nv12|vaapi,hwupload']
        ),
    }
    
    def __init__(self, ffmpeg_path: str):
        self.ffmpeg_path = ffmpeg_path
        self._detected_accelerator: Optional[HardwareAccelerator] = None
        self._detection_done = False
    
    def detect(self) -> Optional[HardwareAccelerator]:
        """
        Detect the best available hardware accelerator.
        Returns None if no hardware acceleration is available.
        """
        if self._detection_done:
            return self._detected_accelerator
        
        self._detection_done = True
        system = platform.system()
        
        # Priority order based on OS
        if system == 'Darwin':  # macOS
            priority = ['videotoolbox']
        elif system == 'Windows':
            priority = ['nvenc', 'qsv']
        else:  # Linux
            priority = ['nvenc', 'vaapi', 'qsv']
        
        for accel_name in priority:
            accel = self.ACCELERATORS.get(accel_name)
            if accel and self._test_encoder(accel.encoder):
                accel.supported = True
                self._detected_accelerator = accel
                logger.info(f"Hardware acceleration detected: {accel.name} ({accel.encoder})")
                return accel
        
        logger.info("No hardware acceleration available, using software encoding (libx264)")
        return None
    
    def _test_encoder(self, encoder: str) -> bool:
        """Test if an encoder is available and working."""
        try:
            cmd = [
                self.ffmpeg_path,
                '-f', 'lavfi',
                '-i', 'nullsrc=s=256x256:d=1',
                '-c:v', encoder,
                '-f', 'null',
                '-t', '0.1',
                '-'
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Encoder {encoder} test failed: {e}")
            return False


@dataclass
class VariantProgress:
    """Progress tracking for a single variant."""
    name: str
    status: str = 'pending'  # pending, processing, completed, failed
    progress: int = 0
    message: str = ''


def check_ffmpeg_installed() -> str:
    """Check if FFmpeg is installed and accessible."""
    ffmpeg_path = shutil.which('ffmpeg')
    
    # If not in PATH, try common Windows Chocolatey location
    if not ffmpeg_path:
        choco_ffmpeg = r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe"
        if os.path.exists(choco_ffmpeg):
            ffmpeg_path = choco_ffmpeg
        else:
            raise RuntimeError(
                "FFmpeg is not installed or not in PATH. "
                "Please install FFmpeg:\n"
                "Windows: choco install ffmpeg OR download from https://ffmpeg.org/download.html\n"
                "Linux: sudo apt-get install ffmpeg\n"
                "macOS: brew install ffmpeg"
            )
    
    logger.info(f"FFmpeg found at: {ffmpeg_path}")
    return ffmpeg_path


class VideoProcessor:
    """
    Handles video conversion to HLS format with multiple quality levels.
    
    Features:
    - Hardware acceleration (NVENC, VideoToolbox, VAAPI, QSV) with auto-detection
    - Parallel variant processing for faster encoding
    - Per-variant progress tracking with consolidated updates
    - Resume capability from checkpoints
    """
    
    # Quality presets for adaptive bitrate streaming
    QUALITY_PRESETS = [
        {
            'name': '1080p',
            'resolution': '1920x1080',
            'video_bitrate': '5000k',
            'audio_bitrate': '192k',
            'maxrate': '5350k',
            'bufsize': '7500k'
        },
        {
            'name': '720p',
            'resolution': '1280x720',
            'video_bitrate': '2800k',
            'audio_bitrate': '128k',
            'maxrate': '2996k',
            'bufsize': '4200k'
        },
        {
            'name': '480p',
            'resolution': '854x480',
            'video_bitrate': '1400k',
            'audio_bitrate': '128k',
            'maxrate': '1498k',
            'bufsize': '2100k'
        },
        {
            'name': '360p',
            'resolution': '640x360',
            'video_bitrate': '800k',
            'audio_bitrate': '96k',
            'maxrate': '856k',
            'bufsize': '1200k'
        },
    ]
    
    # CRF (Constant Rate Factor) for quality - lower = better quality, 23 is default
    CRF_VALUE = '23'
    
    # Resolution height mapping for skip-upscaling logic
    RESOLUTION_HEIGHT_MAP = {
        '1080p': 1080,
        '720p': 720,
        '480p': 480,
        '360p': 360,
    }
    
    def __init__(
        self, 
        input_path: str, 
        output_dir: str, 
        progress_callback: Optional[Callable] = None,
        use_hardware_acceleration: bool = True,
        parallel_variants: int = 1,
        variant_progress_callback: Optional[Callable] = None
    ):
        """
        Initialize the video processor.
        
        Args:
            input_path: Path to the input MP4 file
            output_dir: Directory where HLS files will be saved
            progress_callback: Optional callback function(variant_name, progress_percent, message)
            use_hardware_acceleration: Whether to use GPU acceleration if available (default True)
            parallel_variants: Number of variants to process in parallel (default 1 for sequential)
                              Set to 2 for moderate parallelism, higher values need more resources
            variant_progress_callback: Optional callback for consolidated variant progress updates
                                       Signature: (overall_progress: int, message: str, variants_progress: Dict[str, VariantProgress])
        """
        self.input_path = input_path
        self.output_dir = output_dir
        self.segment_duration = getattr(settings, 'HLS_SEGMENT_DURATION', 6)
        self.progress_callback = progress_callback
        self.variant_progress_callback = variant_progress_callback
        self.parallel_variants = max(1, min(parallel_variants, len(self.QUALITY_PRESETS)))
        
        # Load configurable settings from Django settings
        self.encoding_preset = getattr(settings, 'HLS_ENCODER_PRESET', 'superfast')
        self.ffmpeg_threads = getattr(settings, 'HLS_FFMPEG_THREADS', 3)
        self.skip_upscaling = getattr(settings, 'HLS_SKIP_UPSCALING', True)
        self.enabled_variants = getattr(settings, 'HLS_VARIANTS', ['1080p', '720p', '480p', '360p'])
        self.use_single_pass = getattr(settings, 'HLS_SINGLE_PASS', False)
        
        # Source video resolution (populated during conversion)
        self._source_height: int = 0
        self._source_width: int = 0
        
        # Check FFmpeg availability
        self.ffmpeg_path = check_ffmpeg_installed()
        
        # Hardware acceleration
        self.use_hardware_acceleration = use_hardware_acceleration
        self.hw_accel: Optional[HardwareAccelerator] = None
        if use_hardware_acceleration:
            detector = HardwareAccelerationDetector(self.ffmpeg_path)
            self.hw_accel = detector.detect()
        
        # Filter presets based on enabled variants
        self._active_presets = [
            preset for preset in self.QUALITY_PRESETS 
            if preset['name'] in self.enabled_variants
        ]
        
        # Per-variant progress tracking
        self._variant_progress: Dict[str, VariantProgress] = {
            preset['name']: VariantProgress(name=preset['name'])
            for preset in self._active_presets
        }
        self._video_duration: float = 0.0
        
    def convert_to_hls(self, resume_from_variant: Optional[str] = None) -> Dict[str, any]:
        """
        Convert video to HLS format with multiple quality levels.
        Supports parallel processing and hardware acceleration.
        
        Args:
            resume_from_variant: Optional variant name to resume from (e.g., '720p')
        
        Returns:
            Dictionary containing conversion results and file paths
        """
        try:
            # Create output directory if it doesn't exist
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
            
            # Validate disk space before processing
            self._validate_disk_space()
            
            # Get video metadata
            self._video_duration = self._get_video_duration()
            self._source_width, self._source_height = self._get_video_resolution()
            
            logger.info(f"Source video: {self._source_width}x{self._source_height}, duration: {self._video_duration}s")
            
            # Determine which variants to process
            presets_to_process = []
            completed_variants = []
            skip_until_resume = resume_from_variant is not None
            skipped_variants = []
            
            for preset in self._active_presets:
                variant_name = preset['name']
                variant_dir = os.path.join(self.output_dir, variant_name)
                playlist_path = os.path.join(variant_dir, f"{variant_name}.m3u8")
                
                # Skip upscaling: don't encode variants higher than source resolution
                if self.skip_upscaling and self._source_height > 0:
                    variant_height = self.RESOLUTION_HEIGHT_MAP.get(variant_name, 0)
                    if variant_height > self._source_height:
                        logger.info(f"Skipping {variant_name} (source is {self._source_height}p, skip-upscaling enabled)")
                        skipped_variants.append(variant_name)
                        continue
                
                # Check if variant already exists
                if os.path.exists(playlist_path):
                    logger.info(f"Skipping already completed variant: {variant_name}")
                    if variant_name in self._variant_progress:
                        self._variant_progress[variant_name].status = 'completed'
                        self._variant_progress[variant_name].progress = 100
                    completed_variants.append({
                        'name': variant_name,
                        'resolution': preset['resolution'],
                        'bandwidth': self._calculate_bandwidth(preset),
                        'playlist': os.path.join(variant_name, f"{variant_name}.m3u8"),
                        'playlist_path': playlist_path
                    })
                    continue
                
                # Handle resume logic
                if skip_until_resume:
                    if variant_name == resume_from_variant:
                        skip_until_resume = False
                    else:
                        continue
                
                presets_to_process.append(preset)
            
            # Process variants based on configuration
            # Single-pass mode: decode once, encode all variants simultaneously (fastest)
            # Parallel mode: multiple FFmpeg processes (moderate)
            # Sequential mode: one variant at a time (slowest but lowest memory)
            if self.use_single_pass and len(presets_to_process) > 1:
                logger.info("Using single-pass multi-variant encoding (fastest)")
                new_variants = self._process_variants_single_pass(presets_to_process)
            elif self.parallel_variants > 1 and len(presets_to_process) > 1:
                new_variants = self._process_variants_parallel(presets_to_process)
            else:
                new_variants = self._process_variants_sequential(presets_to_process)
            
            # Combine completed and new variants
            all_variants = completed_variants + new_variants
            
            # Create master playlist
            master_playlist_path = self._create_master_playlist(all_variants)
            
            return {
                'success': True,
                'master_playlist': master_playlist_path,
                'variants': all_variants,
                'duration': self._video_duration,
                'output_dir': self.output_dir,
                'hardware_acceleration': self.hw_accel.name if self.hw_accel else 'software (libx264)',
                'parallel_workers': self.parallel_variants
            }
            
        except Exception as e:
            logger.error(f"Error converting video to HLS: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _process_variants_sequential(self, presets: List[Dict]) -> List[Dict]:
        """Process variants one at a time with optimized CPU utilization."""
        variants = []
        total = len(presets)
        
        for idx, preset in enumerate(presets):
            variant_info = self._create_hls_variant(preset, idx, total, self._video_duration)
            if variant_info:
                variants.append(variant_info)
            # Removed gc.collect() to prevent CPU gaps between variants
        
        return variants
    
    def _process_variants_single_pass(self, presets: List[Dict]) -> List[Dict]:
        """
        Process all variants in a single FFmpeg pass using filter_complex.
        This decodes the video only once and encodes all variants simultaneously,
        which is significantly faster than sequential processing.
        
        Args:
            presets: List of quality presets to process
            
        Returns:
            List of variant information dictionaries
        """
        if not presets:
            return []
        
        logger.info(f"Processing {len(presets)} variants in single-pass mode")
        
        # Mark all variants as processing
        for preset in presets:
            self._update_variant_progress(preset['name'], 0, f"Starting {preset['name']}...", 'processing')
        
        # Create output directories
        for preset in presets:
            variant_dir = os.path.join(self.output_dir, preset['name'])
            Path(variant_dir).mkdir(parents=True, exist_ok=True)
        
        # Build single-pass FFmpeg command
        cmd = self._build_single_pass_command(presets)
        
        # If single-pass returns None, fall back to sequential processing
        if cmd is None:
            logger.info("Falling back to sequential processing for HLS output")
            return self._process_variants_sequential(presets)
        
        logger.info(f"Single-pass FFmpeg command: {' '.join(cmd[:20])}...")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Monitor progress
            self._monitor_single_pass_progress(process, presets, self._video_duration)
            
            # Wait for completion
            _, stderr = process.communicate(timeout=14400)  # 4 hour timeout for all variants
            
            if process.returncode != 0:
                logger.error(f"Single-pass FFmpeg error: {stderr[-2000:] if len(stderr) > 2000 else stderr}")
                for preset in presets:
                    self._update_variant_progress(preset['name'], 0, f"{preset['name']} failed", 'failed')
                return []
            
            # Verify outputs and build variant info
            variants = []
            for preset in presets:
                variant_name = preset['name']
                variant_dir = os.path.join(self.output_dir, variant_name)
                playlist_path = os.path.join(variant_dir, f"{variant_name}.m3u8")
                
                if os.path.exists(playlist_path):
                    self._update_variant_progress(variant_name, 100, f"{variant_name} complete", 'completed')
                    variants.append({
                        'name': variant_name,
                        'resolution': preset['resolution'],
                        'bandwidth': self._calculate_bandwidth(preset),
                        'playlist': os.path.join(variant_name, f"{variant_name}.m3u8"),
                        'playlist_path': playlist_path
                    })
                    logger.info(f"Successfully created variant: {variant_name}")
                else:
                    logger.error(f"Playlist not created for {variant_name}")
                    self._update_variant_progress(variant_name, 0, f"{variant_name} failed - no playlist", 'failed')
            
            return variants
            
        except subprocess.TimeoutExpired:
            logger.error("Single-pass FFmpeg timed out")
            if 'process' in locals():
                process.kill()
            for preset in presets:
                self._update_variant_progress(preset['name'], 0, f"{preset['name']} timed out", 'failed')
            return []
        except Exception as e:
            logger.error(f"Error in single-pass processing: {str(e)}")
            for preset in presets:
                self._update_variant_progress(preset['name'], 0, f"{preset['name']} error: {str(e)}", 'failed')
            return []
    
    def _build_single_pass_command(self, presets: List[Dict]) -> List[str]:
        """
        Build FFmpeg command for single-pass multi-variant encoding.
        Uses filter_complex to split input and encode all variants at once.
        
        IMPORTANT: Uses stream specifiers (-c:v:0, -c:a:0, etc.) to correctly
        assign codec options to each output stream.
        
        Args:
            presets: List of quality presets to encode
            
        Returns:
            List of command arguments
        """
        cmd = [self.ffmpeg_path, '-y']
        
        # Hardware acceleration input args
        if self.hw_accel:
            cmd.extend(self.hw_accel.extra_input_args)
        
        cmd.extend(['-i', self.input_path])
        
        # Limit total threads for the entire process
        cmd.extend(['-threads', str(self.ffmpeg_threads)])
        
        # Build filter_complex for splitting video stream
        num_variants = len(presets)
        filter_parts = []
        
        # Split video stream to multiple outputs
        filter_parts.append(f"[0:v]split={num_variants}" + "".join(f"[v{i}]" for i in range(num_variants)))
        
        # Scale each output to target resolution (use fast_bilinear for speed)
        for i, preset in enumerate(presets):
            resolution = preset['resolution']
            width, height = resolution.split('x')
            filter_parts.append(f"[v{i}]scale={width}:{height}:flags=fast_bilinear[vout{i}]")
        
        filter_complex = ";".join(filter_parts)
        cmd.extend(['-filter_complex', filter_complex])
        
        # Map all outputs first
        for i in range(num_variants):
            cmd.extend(['-map', f'[vout{i}]', '-map', '0:a?'])  # 0:a? = audio if exists
        
        # Now add codec options with stream specifiers for each output
        for i, preset in enumerate(presets):
            variant_name = preset['name']
            variant_dir = os.path.join(self.output_dir, variant_name)
            segment_pattern = os.path.join(variant_dir, f"{variant_name}_%03d.ts")
            playlist_path = os.path.join(variant_dir, f"{variant_name}.m3u8")
            
            # Video stream index is i*2 (video, audio, video, audio, ...)
            v_idx = i * 2
            a_idx = i * 2 + 1
            
            # Video encoder with stream specifier
            if self.hw_accel:
                cmd.extend([f'-c:v:{i}', self.hw_accel.encoder])
            else:
                cmd.extend([
                    f'-c:v:{i}', 'libx264',
                    f'-preset:v:{i}', self.encoding_preset,
                    f'-crf:v:{i}', self.CRF_VALUE,
                ])
            
            # Video encoding parameters with stream specifiers
            cmd.extend([
                f'-b:v:{i}', preset['video_bitrate'],
                f'-maxrate:v:{i}', preset['maxrate'],
                f'-bufsize:v:{i}', preset['bufsize'],
                f'-profile:v:{i}', 'main',
            ])
            
            # Audio encoder with stream specifier
            cmd.extend([
                f'-c:a:{i}', 'aac',
                f'-b:a:{i}', preset['audio_bitrate'],
            ])
        
        # HLS output options - one output file per variant
        # Using tee muxer approach won't work well, so we fall back to sequential for HLS
        # Actually, for proper multi-output HLS, we need separate outputs
        # FFmpeg doesn't support multiple HLS outputs in one command cleanly
        # Let's use a simpler approach: sequential processing is more reliable for HLS
        
        # For now, return a command that processes variants sequentially
        # This is more reliable than trying to do multi-output HLS
        logger.warning("Single-pass HLS encoding is complex; falling back to sequential for reliability")
        return None  # Signal to use sequential processing
    
    def _monitor_single_pass_progress(self, process: subprocess.Popen, presets: List[Dict], video_duration: float):
        """
        Monitor FFmpeg progress for single-pass encoding.
        
        Args:
            process: FFmpeg subprocess
            presets: List of presets being processed
            video_duration: Total video duration in seconds
        """
        last_progress = 0
        
        try:
            for line in process.stdout:
                if 'out_time_ms=' in line:
                    match = re.search(r'out_time_ms=(\d+)', line)
                    if match and video_duration > 0:
                        time_ms = int(match.group(1))
                        time_sec = time_ms / 1_000_000
                        progress = min(100, int((time_sec / video_duration) * 100))
                        
                        if progress - last_progress >= 5:
                            # Update all variants with same progress
                            for preset in presets:
                                self._update_variant_progress(
                                    preset['name'],
                                    progress,
                                    f"Converting all variants: {progress}%"
                                )
                            last_progress = progress
        except Exception as e:
            logger.warning(f"Error monitoring single-pass progress: {str(e)}")
    
    def _process_variants_parallel(self, presets: List[Dict]) -> List[Dict]:
        """
        Process multiple variants in parallel using ThreadPoolExecutor.
        Each FFmpeg process runs in its own thread.
        """
        variants = []
        total = len(presets)
        
        logger.info(f"Processing {total} variants in parallel with {self.parallel_variants} workers")
        
        with ThreadPoolExecutor(max_workers=self.parallel_variants) as executor:
            future_to_preset = {
                executor.submit(
                    self._create_hls_variant, 
                    preset, 
                    idx, 
                    total, 
                    self._video_duration
                ): preset
                for idx, preset in enumerate(presets)
            }
            
            for future in as_completed(future_to_preset):
                preset = future_to_preset[future]
                try:
                    variant_info = future.result()
                    if variant_info:
                        variants.append(variant_info)
                except Exception as e:
                    logger.error(f"Error processing variant {preset['name']}: {e}")
                    self._variant_progress[preset['name']].status = 'failed'
                    self._variant_progress[preset['name']].message = str(e)
                # Removed gc.collect() to prevent CPU gaps
        
        # Sort variants by resolution (highest first)
        resolution_order = ['1080p', '720p', '480p', '360p']
        variants.sort(key=lambda v: resolution_order.index(v['name']) if v['name'] in resolution_order else 999)
        
        return variants
    
    def _update_variant_progress(self, variant_name: str, progress: int, message: str, status: str = 'processing'):
        """
        Update progress for a specific variant and send consolidated update.
        """
        self._variant_progress[variant_name].progress = progress
        self._variant_progress[variant_name].message = message
        self._variant_progress[variant_name].status = status
        
        # Calculate overall progress (20-70% range for conversion)
        total_progress = sum(vp.progress for vp in self._variant_progress.values())
        avg_progress = total_progress / len(self._variant_progress)
        overall_progress = int(20 + (avg_progress * 0.5))  # Map 0-100 to 20-70
        
        # Send consolidated update via variant_progress_callback
        if self.variant_progress_callback:
            self.variant_progress_callback(
                overall_progress,
                message,
                {name: vp for name, vp in self._variant_progress.items()}
            )
        
        # Also send via legacy callback for backward compatibility
        if self.progress_callback:
            self.progress_callback(variant_name, overall_progress, message)
    
    def get_variant_progress(self) -> Dict[str, VariantProgress]:
        """Get current progress for all variants."""
        return self._variant_progress.copy()
    
    def _create_hls_variant(self, preset: Dict, variant_idx: int, total_variants: int, video_duration: float) -> Dict:
        """
        Create HLS variant for a specific quality preset with progress monitoring.
        Supports hardware acceleration when available.
        
        Args:
            preset: Quality preset configuration
            variant_idx: Index of current variant (0-based)
            total_variants: Total number of variants to process
            video_duration: Total video duration in seconds
            
        Returns:
            Dictionary with variant information
        """
        variant_name = preset['name']
        
        try:
            self._update_variant_progress(variant_name, 0, f"Starting {variant_name}...", 'processing')
            
            variant_dir = os.path.join(self.output_dir, variant_name)
            Path(variant_dir).mkdir(parents=True, exist_ok=True)
            
            playlist_filename = f"{variant_name}.m3u8"
            playlist_path = os.path.join(variant_dir, playlist_filename)
            segment_pattern = os.path.join(variant_dir, f"{variant_name}_%03d.ts")
            
            # Check if variant already fully completed (resume scenario)
            if os.path.exists(playlist_path):
                with open(playlist_path, 'r') as f:
                    content = f.read()
                if '#EXT-X-ENDLIST' in content:
                    logger.info(f"Variant {variant_name} already completed (ENDLIST verified), skipping")
                    self._update_variant_progress(variant_name, 100, f"{variant_name} complete", 'completed')
                    relative_playlist = os.path.join(variant_name, playlist_filename)
                    return {
                        'name': variant_name,
                        'resolution': preset['resolution'],
                        'bandwidth': self._calculate_bandwidth(preset),
                        'playlist': relative_playlist,
                        'playlist_path': playlist_path
                    }
                else:
                    # Variant exists but incomplete — re-process
                    logger.warning(f"Variant {variant_name} playlist exists but incomplete (no ENDLIST), re-processing")
            
            # Build FFmpeg command with optional hardware acceleration
            cmd = self._build_ffmpeg_command(preset, segment_pattern, playlist_path)
            
            # Execute FFmpeg with real-time progress monitoring
            # Use line buffering for immediate progress updates
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered for immediate progress
                universal_newlines=True
            )

            # Safety timeout per variant (prevents ffmpeg hang from blocking forever)
            import threading
            variant_timeout = getattr(settings, 'FFMPEG_VARIANT_TIMEOUT', 1800)
            dead = threading.Event()

            def kill_on_timeout():
                if process.poll() is None:
                    dead.set()
                    process.kill()
                    logger.error(f"FFmpeg variant {variant_name} timed out after {variant_timeout}s, killed")

            timer = threading.Timer(variant_timeout, kill_on_timeout)
            timer.daemon = True
            timer.start()

            try:
                # Monitor progress (reads stdout until EOF)
                self._monitor_ffmpeg_progress(process, variant_name, variant_idx, total_variants, video_duration, dead)

                # Wait for process to complete and capture stderr
                _, stderr = process.communicate(timeout=900)  # 15 min grace after stdout closes
            finally:
                timer.cancel()

            if dead.is_set():
                self._update_variant_progress(variant_name, 0, f"{variant_name} timed out", 'failed')
                return None

            if process.returncode != 0:
                logger.error(f"FFmpeg error for {variant_name}: {stderr}")
                self._update_variant_progress(variant_name, 0, f"{variant_name} failed", 'failed')
                return None
            
            # Validate output
            if not os.path.exists(playlist_path):
                logger.error(f"Playlist not created for {variant_name}")
                self._update_variant_progress(variant_name, 0, f"{variant_name} failed - no playlist", 'failed')
                return None
            
            # Get relative path for playlist
            relative_playlist = os.path.join(variant_name, playlist_filename)
            
            self._update_variant_progress(variant_name, 100, f"{variant_name} complete", 'completed')
            logger.info(f"Successfully created variant: {variant_name}")
            
            return {
                'name': variant_name,
                'resolution': preset['resolution'],
                'bandwidth': self._calculate_bandwidth(preset),
                'playlist': relative_playlist,
                'playlist_path': playlist_path
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout creating HLS variant {variant_name}")
            self._update_variant_progress(variant_name, 0, f"{variant_name} timed out", 'failed')
            if 'process' in locals():
                process.kill()
            return None
        except Exception as e:
            logger.error(f"Error creating HLS variant {variant_name}: {str(e)}")
            self._update_variant_progress(variant_name, 0, f"{variant_name} error: {str(e)}", 'failed')
            return None
    
    def _build_ffmpeg_command(self, preset: Dict, segment_pattern: str, playlist_path: str) -> List[str]:
        """
        Build FFmpeg command with optional hardware acceleration.
        
        Args:
            preset: Quality preset configuration
            segment_pattern: Pattern for segment filenames
            playlist_path: Output playlist path
            
        Returns:
            List of command arguments
        """
        cmd = [self.ffmpeg_path]
        
        # Add hardware acceleration input args if available
        if self.hw_accel:
            cmd.extend(self.hw_accel.extra_input_args)
        
        cmd.extend(['-i', self.input_path])
        
        # Video encoder (hardware or software)
        if self.hw_accel:
            cmd.extend(['-c:v', self.hw_accel.encoder])
            cmd.extend(self.hw_accel.extra_output_args)
        else:
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', self.encoding_preset,
                '-crf', self.CRF_VALUE,
            ])
        
        # Common encoding parameters optimized for CPU utilization
        cmd.extend([
            '-c:a', 'aac',
            '-b:v', preset['video_bitrate'],
            '-b:a', preset['audio_bitrate'],
            '-maxrate', preset['maxrate'],
            '-bufsize', preset['bufsize'],
            '-s', preset['resolution'],
            '-sws_flags', 'fast_bilinear',
            '-profile:v', 'main',
            '-level', '4.0',
            '-movflags', '+faststart',
            '-threads', str(self.ffmpeg_threads),
            # Optimize for continuous processing
            '-max_muxing_queue_size', '1024',  # Prevent muxing bottlenecks
            '-start_number', '0',
            '-hls_time', str(self.segment_duration),
            '-hls_list_size', '0',
            '-hls_segment_filename', segment_pattern,
            '-hls_flags', 'independent_segments',  # Better for streaming
            '-f', 'hls',
            '-progress', 'pipe:1',
            playlist_path
        ])
        
        return cmd
    
    def _create_master_playlist(self, variants: List[Dict]) -> str:
        """
        Create HLS master playlist that references all quality variants.
        
        Args:
            variants: List of variant information dictionaries
            
        Returns:
            Path to the master playlist file
        """
        master_playlist_path = os.path.join(self.output_dir, 'master.m3u8')
        Path(os.path.dirname(master_playlist_path)).mkdir(parents=True, exist_ok=True)
        
        with open(master_playlist_path, 'w') as f:
            f.write('#EXTM3U\n')
            f.write('#EXT-X-VERSION:3\n\n')
            
            for variant in variants:
                # Write stream info
                f.write(f'#EXT-X-STREAM-INF:BANDWIDTH={variant["bandwidth"]},'
                       f'RESOLUTION={variant["resolution"]}\n')
                f.write(f'{variant["playlist"]}\n\n')
        
        return master_playlist_path
    
    def _get_video_duration(self) -> float:
        """
        Get video duration using ffprobe.
        
        Returns:
            Duration in seconds
        """
        try:
            # Use ffprobe from the same directory as ffmpeg
            if self.ffmpeg_path.endswith('.exe'):
                ffprobe_path = self.ffmpeg_path.replace('ffmpeg.exe', 'ffprobe.exe')
            else:
                ffprobe_path = self.ffmpeg_path.replace('ffmpeg', 'ffprobe')
            
            if not os.path.exists(ffprobe_path):
                ffprobe_path = shutil.which('ffprobe')
                if not ffprobe_path:
                    # Try Chocolatey location
                    choco_ffprobe = r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffprobe.exe"
                    if os.path.exists(choco_ffprobe):
                        ffprobe_path = choco_ffprobe
                    else:
                        ffprobe_path = 'ffprobe'
            
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                self.input_path
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
            logger.error(f"ffprobe failed (exit {result.returncode}): stderr={result.stderr.strip()}, stdout={result.stdout.strip()}")
            return 0.0
            
        except Exception as e:
            logger.error(f"Error getting video duration: {str(e)}")
            return 0.0
    
    def _get_video_resolution(self) -> Tuple[int, int]:
        """
        Get video resolution (width, height) using ffprobe.
        
        Returns:
            Tuple of (width, height) in pixels, or (0, 0) if detection fails
        """
        try:
            # Use ffprobe from the same directory as ffmpeg
            if self.ffmpeg_path.endswith('.exe'):
                ffprobe_path = self.ffmpeg_path.replace('ffmpeg.exe', 'ffprobe.exe')
            else:
                ffprobe_path = self.ffmpeg_path.replace('ffmpeg', 'ffprobe')
            
            if not os.path.exists(ffprobe_path):
                ffprobe_path = shutil.which('ffprobe')
                if not ffprobe_path:
                    choco_ffprobe = r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffprobe.exe"
                    if os.path.exists(choco_ffprobe):
                        ffprobe_path = choco_ffprobe
                    else:
                        ffprobe_path = 'ffprobe'
            
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=s=x:p=0',
                self.input_path
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode == 0 and 'x' in result.stdout:
                width, height = result.stdout.strip().split('x')
                return int(width), int(height)
            return 0, 0
            
        except Exception as e:
            logger.error(f"Error getting video resolution: {str(e)}")
            return 0, 0
    
    def _monitor_ffmpeg_progress(self, process: subprocess.Popen, variant_name: str, 
                                   variant_idx: int, total_variants: int, video_duration: float,
                                   dead_event: threading.Event = None):
        """
        Monitor FFmpeg progress and send updates via callback.
        Optimized to minimize blocking and ensure smooth progress updates.
        
        Args:
            process: FFmpeg subprocess
            variant_name: Name of the variant being processed
            variant_idx: Index of current variant
            total_variants: Total number of variants
            video_duration: Total video duration in seconds
        """
        last_variant_progress = 0
        
        try:
            # Use non-blocking iteration to prevent CPU stalls
            for line in process.stdout:
                # Check if timeout killed the process
                if dead_event and dead_event.is_set():
                    logger.warning(f"Variant {variant_name} timeout detected in monitor loop")
                    break
                # Parse FFmpeg progress output
                if 'out_time_ms=' in line:
                    match = re.search(r'out_time_ms=(\d+)', line)
                    if match and video_duration > 0:
                        time_ms = int(match.group(1))
                        time_sec = time_ms / 1_000_000
                        variant_progress = min(100, int((time_sec / video_duration) * 100))
                        
                        # Send update every 3% change for smoother progress (reduced from 5%)
                        if variant_progress - last_variant_progress >= 3:
                            self._update_variant_progress(
                                variant_name,
                                variant_progress,
                                f"Converting {variant_name}: {variant_progress}%"
                            )
                            last_variant_progress = variant_progress
        except Exception as e:
            logger.warning(f"Error monitoring FFmpeg progress: {str(e)}")
    
    def _validate_disk_space(self):
        """
        Validate sufficient disk space is available for HLS conversion.
        Raises exception if insufficient space.
        """
        try:
            video_size = os.path.getsize(self.input_path)
            # HLS files typically 3-5x original size (multiple qualities + segments)
            estimated_size = video_size * 5
            
            # Get free space in output directory
            stat = shutil.disk_usage(os.path.dirname(self.output_dir))
            free_space = stat.free
            
            # Require 10% buffer
            required_space = estimated_size * 1.1
            
            if free_space < required_space:
                raise RuntimeError(
                    f"Insufficient disk space. Required: {required_space / (1024**3):.2f}GB, "
                    f"Available: {free_space / (1024**3):.2f}GB"
                )
            
            logger.info(f"Disk space check passed. Required: {required_space / (1024**3):.2f}GB, "
                       f"Available: {free_space / (1024**3):.2f}GB")
        except Exception as e:
            logger.warning(f"Could not validate disk space: {str(e)}")
    
    def _calculate_bandwidth(self, preset: Dict) -> int:
        """
        Calculate bandwidth for a quality preset.
        
        Args:
            preset: Quality preset configuration
            
        Returns:
            Bandwidth in bits per second
        """
        # Convert bitrates to bps and sum video + audio
        video_bps = int(preset['video_bitrate'].replace('k', '')) * 1000
        audio_bps = int(preset['audio_bitrate'].replace('k', '')) * 1000
        return video_bps + audio_bps
    
    @staticmethod
    def cleanup_original_file(file_path: str) -> bool:
        """
        Delete the original uploaded video file after successful conversion.
        
        Args:
            file_path: Path to the file to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted original file: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting original file: {str(e)}")
            return False
    
    @classmethod
    def get_recommended_parallel_workers(cls) -> int:
        """
        Get recommended number of parallel workers based on system resources.
        Always returns 1 for sequential processing with all CPU cores per variant.
        
        Returns:
            Always 1 for sequential-only processing
        """
        import multiprocessing
        cpu_count = multiprocessing.cpu_count()
        
        # Sequential processing: 1 variant at a time, all CPU cores dedicated to it
        # With threads=0 (auto), FFmpeg will use ALL available cores for each variant
        # This ensures maximum efficiency: all hands on deck for each preset
        recommended = 1
        
        logger.info(f"Sequential processing mode: 1 worker using all {cpu_count} CPU cores per variant")
        return recommended
