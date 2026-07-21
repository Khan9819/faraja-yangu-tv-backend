import urllib.request
try:
    req = urllib.request.urlopen('https://farajayangutv.co.tz/media/logo.png', timeout=10)
    print(f"Status: {req.status}")
    print(f"Size: {req.headers.get('Content-Length', 'unknown')} bytes")
    print(f"Type: {req.headers.get('Content-Type', 'unknown')}")
except Exception as e:
    print(f"FAIL: {e}")
