FROM nginx:alpine
COPY . /usr/share/nginx/html
RUN printf 'server{listen 8080;root /usr/share/nginx/html;index index.html;\n\
 location / { try_files $uri $uri.html $uri/ =404; }\n\
 location /fonts/ { expires 30d; }\n}\n' > /etc/nginx/conf.d/default.conf \
 && sed -i 's/listen       80;/listen 8080;/' /etc/nginx/conf.d/default.conf 2>/dev/null || true
EXPOSE 8080
