# This configuration file is deprecated and replaced by default.conf
# Keeping for reference only - not loaded by nginx
#
# server {
#     listen 80;
#     server_name cms.farajayangutv.co.tz farajayangutv.co.tz backend.farajayangutv.co.tz;
# 
#     location /media/ {
#         # proxy_pass http://0.0.0.0:8000/media/;
#         alias /app/media/;
#         autoindex on;
#         autoindex_exact_size off;
#         autoindex_localtime on;
#         # sendfile on;
#         # try_files /$1 =404;
#         # autoindex on;
#         # root  /;
#     }
# 
#     location / {
#         proxy_pass http://0.0.0.0:8000;
#         proxy_set_header Host $host;
#         proxy_set_header X-Real-IP $remote_addr;
#         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#         proxy_set_header X-Forwarded-Proto $scheme;
#         client_max_body_size 5G;
#         proxy_connect_timeout 300s;
#         proxy_send_timeout 300s;
#         proxy_read_timeout 300s;
#     }
# }