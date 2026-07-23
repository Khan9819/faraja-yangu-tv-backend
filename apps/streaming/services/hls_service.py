"""
HLS Service for parsing playlists and generating segment URLs.
Provides centralized logic for HLS playlist manipulation and segment retrieval.
"""
import logging
from typing import List, Optional, Dict
import boto3
from botocore.config import Config
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.cache import cache

logger = logging.getLogger(__name__)


def generate_signed_segment_url(storage_key: str, expires_in: int = 3600) -> str:
    """
    Generate a presigned URL for a segment file in R2/S3 storage.

    Args:
        storage_key: The S3 object key (e.g., 'videos/hls/<uid>/720p/720p_001.ts')
        expires_in: URL expiration time in seconds (default 1 hour)

    Returns:
        Presigned URL string
    """
    s3_client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version='s3v4'),
    )
    return s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
            'Key': storage_key,
        },
        ExpiresIn=expires_in,
    )


class HLSService:
    """
    Service for HLS playlist parsing and URL generation.
    Handles master playlist parsing, variant selection, and segment URL generation.
    """
    
    def __init__(self, video_uid: str):
        """
        Initialize HLS service for a specific video.
        
        Args:
            video_uid: The video's unique identifier
        """
        self.video_uid = video_uid
        self.base_storage_path = f"videos/hls/{video_uid}"
        self.backend_url = getattr(settings, 'BACKEND_URL', getattr(settings, 'BASE_URL', 'http://127.0.0.1:8000'))
    
    def get_master_playlist_url(self) -> str:
        """Get the backend proxy URL for the master playlist."""
        return f"{self.backend_url}/streaming/hls/{self.video_uid}/master.m3u8"
    
    def get_available_variants(self) -> List[Dict]:
        """
        Parse master playlist and return available variants.
        
        Returns:
            List of variant info dicts with 'name', 'bandwidth', 'resolution', 'playlist_path'
        """
        master_path = f"{self.base_storage_path}/master.m3u8"
        
        try:
            if not default_storage.exists(master_path):
                logger.warning(f"Master playlist not found: {master_path}")
                return []
            
            with default_storage.open(master_path, 'rb') as f:
                content = f.read().decode('utf-8')
            
            variants = []
            lines = content.strip().split('\n')
            
            for i, line in enumerate(lines):
                if line.startswith('#EXT-X-STREAM-INF:'):
                    # Parse variant info
                    variant_info = self._parse_stream_inf(line)
                    
                    # Next line should be the playlist path
                    if i + 1 < len(lines):
                        playlist_ref = lines[i + 1].strip()
                        if playlist_ref and not playlist_ref.startswith('#'):
                            variant_info['playlist_path'] = playlist_ref
                            # Extract variant name from path (e.g., "360p/360p.m3u8" -> "360p", "720p.mp4" -> "720p")
                            if '/' in playlist_ref:
                                variant_info['name'] = playlist_ref.split('/')[0]
                            else:
                                variant_info['name'] = playlist_ref.rsplit('.', 1)[0]
                            variants.append(variant_info)
            
            # Sort by bandwidth (lowest first for starter segments)
            variants.sort(key=lambda v: v.get('bandwidth', 0))
            return variants
            
        except Exception as e:
            logger.error(f"Error parsing master playlist for {self.video_uid}: {e}")
            return []
    
    def _parse_stream_inf(self, line: str) -> Dict:
        """Parse #EXT-X-STREAM-INF line to extract variant metadata."""
        info = {}
        
        # Remove the tag prefix
        attrs = line.replace('#EXT-X-STREAM-INF:', '')
        
        # Parse BANDWIDTH
        if 'BANDWIDTH=' in attrs:
            try:
                bandwidth_str = attrs.split('BANDWIDTH=')[1].split(',')[0]
                info['bandwidth'] = int(bandwidth_str)
            except (IndexError, ValueError):
                info['bandwidth'] = 0
        
        # Parse RESOLUTION
        if 'RESOLUTION=' in attrs:
            try:
                resolution = attrs.split('RESOLUTION=')[1].split(',')[0]
                info['resolution'] = resolution
            except IndexError:
                info['resolution'] = None
        
        return info
    
    def get_variant_segments(self, variant_path: str, limit: Optional[int] = None) -> List[str]:
        """
        Parse a variant playlist and return segment filenames.
        
        Args:
            variant_path: Path to variant playlist (e.g., "360p/360p.m3u8")
            limit: Optional limit on number of segments to return
            
        Returns:
            List of segment filenames
        """
        full_path = f"{self.base_storage_path}/{variant_path}"
        
        try:
            if not default_storage.exists(full_path):
                logger.warning(f"Variant playlist not found: {full_path}")
                return []
            
            with default_storage.open(full_path, 'rb') as f:
                content = f.read().decode('utf-8')
            
            segments = []
            for line in content.strip().split('\n'):
                line = line.strip()
                # Segment lines are not comments and end with .ts
                if line and not line.startswith('#') and line.endswith('.ts'):
                    segments.append(line)
                    if limit and len(segments) >= limit:
                        break
            
            return segments
            
        except Exception as e:
            logger.error(f"Error parsing variant playlist {variant_path}: {e}")
            return []
    
    def get_starter_segments(self, count: int = 3, prefer_quality: str = 'lowest') -> List[str]:
        """
        Get the first N segment URLs for video preloading.
        Results are cached for 1 hour.
        
        Args:
            count: Number of segments to return (default 3)
            prefer_quality: 'lowest' for fastest load, 'highest' for best quality
            
        Returns:
            List of full backend proxy URLs for segments
        """
        # Check cache first
        cache_key = f"hls:starter:{self.video_uid}:{count}:{prefer_quality}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        variants = self.get_available_variants()
        
        if not variants:
            return []
        
        # Select variant based on preference
        if prefer_quality == 'highest':
            variant = variants[-1]  # Highest bandwidth
        else:
            variant = variants[0]   # Lowest bandwidth (fastest to load)
        
        variant_path = variant.get('playlist_path')
        if not variant_path:
            return []
        
        # New MP4 format: each variant is a single .mp4 file, not a playlist with .ts segments.
        # Return the MP4 URL directly as a starter "segment".
        if variant_path.endswith('.mp4'):
            url = f"{self.backend_url}/streaming/hls/{self.video_uid}/{variant_path}"
            cache.set(cache_key, [url], timeout=3600)
            return [url]
        
        # Legacy HLS format: parse variant playlist for .ts segments
        
        # Get variant directory (e.g., "360p" from "360p/360p.m3u8")
        variant_dir = variant_path.split('/')[0] if '/' in variant_path else ''
        
        # Get segment filenames
        segments = self.get_variant_segments(variant_path, limit=count)
        
        # Convert to full backend proxy URLs
        segment_urls = []
        for segment in segments:
            if variant_dir:
                url = f"{self.backend_url}/streaming/hls/{self.video_uid}/{variant_dir}/{segment}"
            else:
                url = f"{self.backend_url}/streaming/hls/{self.video_uid}/{segment}"
            segment_urls.append(url)
        
        # Cache for 1 hour (segments don't change)
        cache.set(cache_key, segment_urls, timeout=3600)
        
        return segment_urls
    
    def rewrite_playlist_urls(self, content: str, current_path: str = '') -> str:
        """
        Rewrite relative URLs in playlist content.

        - `.m3u8` playlist references → backend proxy URLs (needed for ad injection)
        - `.ts` segment references → presigned R2 URLs (served directly from storage)
        
        Args:
            content: Raw playlist content
            current_path: Current file path for resolving relative URLs
            
        Returns:
            Modified playlist content with rewritten URLs
        """
        import os
        
        lines = content.split('\n')
        new_lines = []
        
        for line in lines:
            # Skip comments and empty lines
            if line.startswith('#') or not line.strip():
                new_lines.append(line)
                continue
            
            stripped = line.strip()
            # If it's a file reference (not a URL), rewrite it
            if stripped and not stripped.startswith('http'):
                if stripped.endswith('.ts'):
                    # Segment reference -> proxy through Django (more reliable than R2 presigned URLs)
                    current_dir = os.path.dirname(current_path)
                    if current_dir:
                        new_line = f"{self.backend_url}/streaming/hls/{self.video_uid}/{current_dir}/{stripped}"
                    else:
                        new_line = f"{self.backend_url}/streaming/hls/{self.video_uid}/{stripped}"
                elif '/' in stripped:
                    # Variant playlist reference (e.g., "1080p/1080p.m3u8") → backend proxy
                    new_line = f"{self.backend_url}/streaming/hls/{self.video_uid}/{stripped}"
                else:
                    # Other file reference → backend proxy
                    current_dir = os.path.dirname(current_path)
                    if current_dir:
                        new_line = f"{self.backend_url}/streaming/hls/{self.video_uid}/{current_dir}/{stripped}"
                    else:
                        new_line = f"{self.backend_url}/streaming/hls/{self.video_uid}/{stripped}"
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        
        return '\n'.join(new_lines)


def get_starter_segments_for_video(video_uid: str, count: int = 3) -> List[str]:
    """
    Convenience function to get starter segments for a video.
    
    Args:
        video_uid: The video's unique identifier
        count: Number of segments to return
        
    Returns:
        List of segment URLs, empty list if video has no HLS content
    """
    service = HLSService(str(video_uid))
    return service.get_starter_segments(count=count, prefer_quality='lowest')
