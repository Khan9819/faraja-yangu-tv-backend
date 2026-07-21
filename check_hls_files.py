import boto3
from botocore.config import Config

s3 = boto3.client('s3',
    endpoint_url='https://1532b4de331061991157470aaabcc76d.r2.cloudflarestorage.com',
    aws_access_key_id='53bf3afba1e91ecd0c6eb5ff4acfb6dc',
    aws_secret_access_key='67308dcc7a36f2370125ff8cfe4e3fc6668e39b2ad861209b6afafdc4691adbe',
    region_name='auto',
    config=Config(signature_version='s3v4'))

uid = 'd9058d02-e48f-442a-bcbc-fb30f6ff9f73'
prefix = f'videos/hls/{uid}/'
resp = s3.list_objects_v2(Bucket='farajayangu-tv', Prefix=prefix, MaxKeys=20)
if 'Contents' in resp:
    count = len(resp['Contents'])
    total_size = sum(obj['Size'] for obj in resp['Contents'])
    print(f'Found {count} HLS files for {uid} (total: {total_size} bytes):')
    for obj in resp['Contents']:
        key = obj['Key']
        size = obj['Size']
        marker = ' MASTER' if 'master.m3u8' in key else ''
        print(f'  {key} ({size} bytes){marker}')
else:
    print(f'No HLS files found at {prefix}')
    # Check all objects under videos/hls/
    resp2 = s3.list_objects_v2(Bucket='farajayangu-tv', Prefix='videos/hls/', MaxKeys=5)
    if 'Contents' in resp2:
        print('\nOther HLS directories:')
        dirs = set()
        for obj in resp2['Contents']:
            parts = obj['Key'].split('/')
            if len(parts) >= 3:
                dirs.add(parts[2])
        for d in sorted(dirs):
            print(f'  {d}')
