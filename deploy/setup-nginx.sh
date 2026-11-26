#!/usr/bin/env bash
# 用 Nginx 把 http://<公网IP>:80 反代到本机 8123，并加 Basic Auth
# 用法：  sudo bash ~/up/deploy/setup-nginx.sh [用户名] [密码]
#        不给密码则随机生成并打印
set -euo pipefail

USER_NAME="${1:-ctrl}"
PASSWORD="${2:-$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 10)}"
UPSTREAM="127.0.0.1:8123"
PORT=80

echo "==> 1/5 安装 nginx 与 htpasswd"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx apache2-utils >/dev/null

echo "==> 2/5 生成账号 ${USER_NAME}"
htpasswd -bc /etc/nginx/.htpasswd "$USER_NAME" "$PASSWORD" >/dev/null
chmod 640 /etc/nginx/.htpasswd

echo "==> 3/5 写站点配置"
cat > /etc/nginx/sites-available/ctrl-checker <<EOF
server {
    listen ${PORT} default_server;
    server_name _;

    client_max_body_size 2m;
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1k;

    auth_basic           "Ctrl Checker";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass         http://${UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 15s;
        send_timeout          300s;
        proxy_send_timeout    300s;
        proxy_read_timeout    300s;
        proxy_buffering       off;
    }
}
EOF

ln -sf /etc/nginx/sites-available/ctrl-checker /etc/nginx/sites-enabled/ctrl-checker
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo "==> 4/5 启动 nginx"
systemctl enable --now nginx >/dev/null 2>&1 || true
systemctl restart nginx

echo "==> 5/5 自检"
sleep 1
CODE_NOAUTH=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/ || true)
CODE_AUTH=$(curl -s -o /dev/null -w '%{http_code}' -u "${USER_NAME}:${PASSWORD}" http://127.0.0.1/ || true)
IP=$(curl -s --max-time 5 https://api.ipify.org || echo "服务器公网IP")

echo
echo "  未带账号 -> HTTP ${CODE_NOAUTH}   (应为 401)"
echo "  带账号   -> HTTP ${CODE_AUTH}   (应为 200)"
echo
echo "  访问地址： http://${IP}/"
echo "  用户名  ： ${USER_NAME}"
echo "  密码    ： ${PASSWORD}"
echo
echo "  注意：还需在腾讯云控制台 -> 防火墙 -> 放行 TCP ${PORT}"
echo "  改密码： sudo htpasswd /etc/nginx/.htpasswd ${USER_NAME}"
echo "  关掉反代： sudo rm /etc/nginx/sites-enabled/ctrl-checker && sudo systemctl reload nginx"
