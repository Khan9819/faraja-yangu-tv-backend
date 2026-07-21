import urllib.request

urls = [
    "https://1532b4de331061991157470aaabcc76d.r2.cloudflarestorage.com/farajayangu-tv/videos/FATHU-VS-TAALIM.png",
    "https://farajayangutv.co.tz/media/videos/FATHU-VS-TAALIM.png",
]

for url in urls:
    try:
        req = urllib.request.urlopen(url, timeout=10)
        print(f"OK {req.status}: {url} ({req.headers.get('Content-Length', '?')} bytes)")
    except Exception as e:
        print(f"FAIL: {url} - {type(e).__name__}")
