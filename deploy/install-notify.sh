#!/usr/bin/env bash
# 安装「重启后自动把新隧道地址推到微信/邮箱」。
# 用法（在服务器上）：bash ~/up/deploy/install-notify.sh
set -e

APP_DIR=/opt/ctrl-checker
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> 1/4 复制脚本"
sudo mkdir -p "$APP_DIR/deploy"
sudo cp -f "$SRC_DIR/notify_url.py" "$APP_DIR/deploy/notify_url.py"

echo "==> 2/4 安装 systemd 单元"
sudo cp -f "$SRC_DIR/cf-notify.service" /etc/systemd/system/cf-notify.service
sudo cp -f "$SRC_DIR/cf-notify.timer"   /etc/systemd/system/cf-notify.timer
sudo systemctl daemon-reload

echo "==> 3/4 配置渠道（首次会生成 /etc/ctrl-notify.conf）"
if [ ! -f /etc/ctrl-notify.conf ]; then
    sudo cp -f "$SRC_DIR/notify.conf.example" /etc/ctrl-notify.conf
    echo "已生成 /etc/ctrl-notify.conf —— 先填一个渠道再继续。"
    echo "编辑命令：sudo nano /etc/ctrl-notify.conf"
    echo "填好后重新运行本脚本，或执行：sudo systemctl start cf-notify"
    exit 0
fi

echo "==> 4/4 立即试发一次"
sudo systemctl start cf-notify.service || true
sleep 2
sudo journalctl -u cf-notify.service -n 12 --no-pager -o cat || true

echo
echo "==> 启用定时检查（每 2 分钟一次，地址不变不会重复推）"
sudo systemctl enable --now cf-notify.timer
systemctl list-timers cf-notify.timer --no-pager || true
echo
echo "完成。以后重启/隧道重建，新地址会自动推到微信或邮箱。"
