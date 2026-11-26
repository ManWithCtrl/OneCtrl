# 控制校正验算器 · 部署说明

三种部署方式，按省事程度排序。

---

## 方式 A：一键脚本（Ubuntu / Debian，推荐）

```bash
# 1) 本机打包（Windows 上执行）
scp -r ctrl_*.py deploy root@<服务器IP>:/root/app/

# 2) 服务器上
ssh root@<服务器IP>
cd /root/app
sudo bash deploy/install.sh
```

脚本会做：装 `python3-venv` + `fonts-noto-cjk` → 建 venv 装 numpy/matplotlib/sympy →
写 systemd 服务（开机自启、崩溃重启、内存上限 700M）→ 放行 ufw 端口 → 自检并打印访问地址。

改端口：`PORT=9000 sudo bash deploy/install.sh`。

---

## 方式 B：Docker

```bash
cd deploy
docker build -t ctrl-checker ..
docker run -d --name ctrl-checker --restart=always -p 8123:8000 ctrl-checker
```

---

## 方式 C：手动跑（临时试用）

```bash
apt-get update && apt-get install -y python3-venv fonts-noto-cjk
python3 -m venv venv && . venv/bin/activate
pip install numpy matplotlib sympy
python ctrl_web.py --port 8123 --no-open
```

---

## 必须知道的四件事

### 1. 内存

| 配置 | 能否跑 | 说明 |
|---|---|---|
| 1 GiB | 勉强 | 首次请求要 2–4 s（导入 numpy/matplotlib/sympy 约 200 MB），建议加 swap（见下） |
| 2 GiB | 舒服 | 推荐 |
| 512 MiB | 不行 | 装依赖时就 OOM |

1 GiB 加 swap：

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 2. 中文字体（最容易踩）

服务器上没有微软雅黑，不装字体图上全是方块。脚本里已装 `fonts-noto-cjk`，
代码里的字体回退链已包含 `Noto Sans CJK SC`，两边都对得上。

### 3. 云厂商防火墙要单独开

`ufw` 只是系统防火墙，云控制台还有一层「防火墙 / 安全组」，要在网页上再加一条：

```
协议 TCP · 端口 8123 · 来源 0.0.0.0/0
```

### 4. 备案

- 用 `http://IP:8123` 直接访问 → **不需要备案**
- 想绑域名、走 80/443 → **国内节点必须备案**，否则会被拦

---

## 安全（公网上必须做）

这个服务默认**没有任何鉴权**，端口一扫到谁都能用（最坏情况是被人刷 CPU）。三选一：

1. 只给自己用：安全组里把来源 IP 限制成你家/公司的出口 IP
2. 换一个长端口 + 不告诉别人（`PORT=38123`，安全性靠隐蔽，不推荐长期）
3. 最稳：套一层 Nginx + Basic Auth

```nginx
server {
    listen 8443 ssl;
    server_name _;
    ssl_certificate     /etc/ssl/ctrl.pem;
    ssl_certificate_key /etc/ssl/ctrl.key;

    location / {
        auth_basic           "ctrl";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass           http://127.0.0.1:8123;
        proxy_read_timeout   120s;
    }
}
```

```bash
apt-get install -y nginx apache2-utils
htpasswd -c /etc/nginx/.htpasswd yourname
```

---

## 七、公网访问：Cloudflare Quick Tunnel（无域名、无端口）

> 适用：临时分享给几个人用。不需要域名、不需要账号、不需要在防火墙开任何入站端口。

### 7.1 安装

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
cloudflared --version
```

### 7.2 先手动跑一次

```bash
cloudflared tunnel --url http://127.0.0.1:8123
```

日志里会出现：

```
Your quick Tunnel has been created! Visit it at:
https://random-words-here.trycloudflare.com
```

这个 `https://xxx.trycloudflare.com` 就是公网地址，自带 HTTPS。

### 7.3 做成系统服务（关终端也不断）

```bash
sudo tee /etc/systemd/system/cf-tunnel.service >/dev/null <<'EOF'
[Unit]
Description=Cloudflare Quick Tunnel for ctrl-checker
After=network-online.target ctrl-web.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8123 --logfile /var/log/cf-tunnel.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now cf-tunnel
sudo grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /var/log/cf-tunnel.log | tail -1
```

### 7.4 收尾

- 腾讯云控制台 → 防火墙 → **删除 8123 入站规则**（隧道是出站连接，不需要入站端口），保留 22。
- `22` 建议也限制来源 IP（只允许自己的宽带出口）。

### 7.5 注意事项

| 事项 | 说明 |
|---|---|
| 地址不固定 | `cf-tunnel` 重启就换域名，需重新分发 |
| 无 SLA | Cloudflare 免费实验性功能，偶发不稳定 |
| 不能加登录 | Access（邮箱验证码）需要自有域名 |
| 带宽 | 不限流量，国内访问多一跳约 +50~150 ms |
| 日志 | `/var/log/cf-tunnel.log` |
| 排查 | `sudo journalctl -u cf-tunnel -n 30 --no-pager` |

### 7.6 升级路径（有域名后）

买一个 `.top`/`.xyz`（20~30 元/年）托管到 Cloudflare，改用**命名隧道**：

```bash
cloudflared tunnel login
cloudflared tunnel create ctrl
cloudflared tunnel route dns ctrl ctrl.你的域名.top
cloudflared tunnel run --url http://127.0.0.1:8123 ctrl
```

好处：地址固定 + 可开 Cloudflare Access（邮箱验证码/Google 登录白名单）。

---

## 八、安全建议（公网暴露前务必看）

| 风险 | 措施 | 是否已内置 |
|---|---|---|
| 表达式炸弹（`s**99999`） | 输入长度 ≤ 300 字符、禁止 4 位以上数字 | ✅ 已内置 |
| 内存打爆 | systemd `MemoryMax=700M` | ✅ 已内置 |
| 陌生流量扫描 | 不开公网端口（走隧道）| 需手动 |
| 无鉴权 | 隧道随机域名保密 / Nginx Basic Auth / Cloudflare Access | 需手动 |
| 请求体过大 | Nginx `client_max_body_size 64k` | 需手动 |

自检命令：

```bash
sudo journalctl -u ctrl-web -f          # 看访问 IP 与异常
sudo systemctl status ctrl-web --no-pager
```
