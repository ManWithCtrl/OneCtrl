#!/usr/bin/env bash
# 控制校正验算器 · 一键部署脚本（Ubuntu 22.04 / 24.04、Debian 12）
# 用法：把整个目录 scp 到服务器，然后  sudo bash deploy/install.sh
set -euo pipefail

APP_DIR="/opt/ctrl-checker"
SVC="ctrl-web"
PORT="${PORT:-8123}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 1/6 安装系统依赖（python3-venv + 中文字体，字体不装图上会是豆腐块）"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip fonts-noto-cjk fontconfig >/dev/null
fc-cache -f >/dev/null 2>&1 || true

echo "==> 2/6 建立运行目录 $APP_DIR"
mkdir -p "$APP_DIR"
cp -f "$SRC"/ctrl_*.py "$SRC"/*.py "$APP_DIR"/ 2>/dev/null || true
cp -rf "$SRC"/templates "$SRC"/static "$APP_DIR"/ 2>/dev/null || true
rm -f "$APP_DIR"/ctrl_check_demo*.py

echo "==> 3/6 创建虚拟环境并装依赖（numpy / matplotlib / sympy）"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q numpy matplotlib sympy

echo "==> 4/6 生成 systemd 服务（开机自启、崩了自动重启）"
cat >"/etc/systemd/system/${SVC}.service" <<EOF
[Unit]
Description=Control Correction Checker (web)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=MPLBACKEND=Agg
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/ctrl_web.py --port ${PORT} --no-open
Restart=always
RestartSec=3
# 内存保护：跑飞了自动重启，别把整台机器拖死
MemoryMax=700M

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SVC}"

echo "==> 5/6 放行防火墙端口 ${PORT}"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "${PORT}/tcp" >/dev/null || true
fi
# 云厂商的安全组/防火墙在控制台另开一次（见 README）

sleep 2
echo "==> 6/6 自检"
if curl -fsS "http://127.0.0.1:${PORT}/" -o /dev/null; then
  IP=$(curl -fsS --max-time 3 https://api.ipify.org || echo "<服务器公网IP>")
  echo
  echo "  部署成功 ✔"
  echo "  访问地址 : http://${IP}:${PORT}/"
  echo "  手机访问 : 同上（手机浏览器直接打开）"
  echo "  看日志   : journalctl -u ${SVC} -f"
  echo "  重启     : systemctl restart ${SVC}"
  echo "  卸载     : systemctl disable --now ${SVC} && rm -rf ${APP_DIR}"
else
  echo "  ⚠ 服务没起来，看日志：journalctl -u ${SVC} -n 50 --no-pager"
  exit 1
fi
