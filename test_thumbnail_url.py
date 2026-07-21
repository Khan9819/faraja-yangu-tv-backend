"""Test: verify what video.thumbnail.url returns + check if it's publicly accessible"""
import os, sys, django
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farajayangu_be.settings')
django.setup()

from apps.streaming.models import Video
import urllib.request

# Get latest completed video with thumbnail
v = Video.objects.filter(processing_status='completed', thumbnail__isnull=False).order_by('-created_at').first()
if not v:
    print("No completed video with thumbnail found")
    exit()

raw_url = v.thumbnail.url
print(f"=== Video: {v.title} (UID: {v.uid}) ===")
print(f"thumbnail.name: {v.thumbnail.name}")
print(f"thumbnail.url:  {raw_url}")
print()

# Test with _normalize_media_url
from apps.streaming.tasks.tasks import _normalize_media_url
normalized = _normalize_media_url(raw_url)
print(f"normalized:     {normalized}")
print()

# Test if normalized URL is accessible
if normalized:
    try:
        req = urllib.request.urlopen(normalized, timeout=10)
        ct = req.headers.get('Content-Type', '?')
        cl = req.headers.get('Content-Length', '?')
        print(f"HTTP {req.status} | Content-Type: {ct} | Size: {cl} bytes")
        size_kb = int(cl) / 1024 if cl != '?' else 0
        print(f"Size: {size_kb:.1f}KB {'✓ OK' if size_kb < 300 else '⚠ OVER 300KB'}")
    except Exception as e:
        print(f"HTTP FAIL: {e}")

# Also test direct R2 URL
print(f"\nDirect R2 URL: {raw_url}")
try:
    req = urllib.request.urlopen(raw_url, timeout=10)
    print(f"HTTP {req.status}")
except Exception as e:
    print(f"HTTP FAIL: {type(e).__name__}: {str(e)[:100]}")
