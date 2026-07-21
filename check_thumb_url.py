import urllib.request

urls = [
    "https://farajayangutv.co.tz/media/videos/FATHU-VS-TAALIM.png",
    "https://farajayangutv.co.tz/videos/FATHU-VS-TAALIM.png",
    "https://farajayangutv.co.tz/static/videos/FATHU-VS-TAALIM.png",
]

for url in urls:
    try:
        req = urllib.request.urlopen(url, timeout=5)
        print(f"OK {req.status}: {url} ({req.headers.get('Content-Length', '?')} bytes)")
    except Exception as e:
        print(f"FAIL: {url} - {e}")
