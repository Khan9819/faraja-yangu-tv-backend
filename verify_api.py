import urllib.request, json
r = urllib.request.urlopen('https://backend.farajayangutv.co.tz/streaming/feed/?page=1&page_size=3', timeout=10)
print(f'Status: {r.status}')
d = json.loads(r.read())
results = d['data']['results']
print(f'Videos returned: {len(results)}')
for v in results:
    print(f'  - {v["title"][:60]}')
    print(f'    thumbnail: {v.get("thumbnail","none")[:80]}')
