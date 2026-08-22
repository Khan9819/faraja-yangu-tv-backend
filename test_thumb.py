import os
import psycopg2, urllib.request

c = psycopg2.connect(host='farajayangutv.co.tz',port=5439,user='postgres',password=os.environ.get('DB_PASSWORD', ''),dbname='FarajaYanguTv',connect_timeout=15)
cur = c.cursor()
cur.execute("SELECT uid,title,thumbnail FROM streaming_video WHERE processing_status='completed' AND thumbnail IS NOT NULL AND thumbnail!='' ORDER BY created_at DESC LIMIT 1")
r = cur.fetchone()
print(f"VIDEO: {r[1]}")
print(f"THUMB_DB: {r[2]}")
print()

# Test via cms proxy (the backend uses this to normalize)
url = f"https://cms.farajayangutv.co.tz/media/{r[2]}"
print(f"CMS URL: {url}")
try:
    req = urllib.request.urlopen(url,timeout=10)
    sz = req.headers.get('Content-Length','?')
    ct = req.headers.get('Content-Type','?')
    kb = int(sz)/1024
    status = "OK" if kb < 300 else f"OVER 300KB ({kb:.0f}KB)"
    print(f"HTTP {req.status} | {ct} | {kb:.0f}KB | {status}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

c.close()
