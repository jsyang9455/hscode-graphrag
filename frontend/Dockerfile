FROM nginx:1.27-alpine

COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/src /usr/share/nginx/html/src
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
