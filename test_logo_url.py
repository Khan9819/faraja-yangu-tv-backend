import urllib.request

urls = [
    "https://farajayangutv.co.tz/media/notifications/brand_logo.png",
    "https://1532b4de331061991157470aaabcc76d.r2.cloudflarestorage.com/farajayangu-tv/notifications/brand_logo.png",
]

for url in urls:
    try:
        req = urllib.request.urlopen(url, timeout=10)
        print(f"OK {req.status}: {url}")
    except Exception as e:
        print(f"FAIL: {url} - {type(e).__name__}: {e}")
