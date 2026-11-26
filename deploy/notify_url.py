#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cf-tunnel 起来后，把新的 trycloudflare 地址推到微信/邮箱。

配置文件：/etc/ctrl-notify.conf   （示例见 notify.conf.example）
用法：
    python3 notify_url.py                # 从 journal 里找地址再推送
    python3 notify_url.py --url <地址>    # 手动指定地址（测试用）
    python3 notify_url.py --dry-run      # 只打印，不真发
"""
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.text import MIMEText

CONF = "/etc/ctrl-notify.conf"
STATE_DIR = "/var/lib/ctrl-notify"
STATE = os.path.join(STATE_DIR, "last_url")
PAT = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


# ---------------------------------------------------------------- 配置
def load_conf():
    cfg = {}
    try:
        with open(CONF, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip().upper()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return cfg


# ---------------------------------------------------------------- 找地址
def find_url(cfg, wait=120):
    unit = cfg.get("UNIT", "cf-tunnel")
    logfile = cfg.get("LOG_FILE", "").strip()
    deadline = time.time() + wait
    while True:
        text = ""
        if logfile and os.path.exists(logfile):
            try:
                text = open(logfile, errors="ignore").read()
            except Exception:
                text = ""
        if not text:
            try:
                text = subprocess.run(
                    ["journalctl", "-u", unit, "-n", "600", "--no-pager", "-o", "cat"],
                    capture_output=True, text=True, timeout=25).stdout
            except Exception:
                text = ""
        hits = PAT.findall(text)
        if hits:
            return hits[-1]
        if time.time() > deadline:
            return None
        time.sleep(5)


# ---------------------------------------------------------------- 推送渠道
def _post(url, data, headers=None, timeout=20):
    req = urllib.request.Request(url, data=data,
                                 headers=headers or {"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()[:300]


def send_serverchan(cfg, title, body):
    key = cfg.get("SERVERCHAN_KEY")
    if not key:
        return None
    data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
    return _post("https://sctapi.ftqq.com/%s.send" % key, data)


def send_pushplus(cfg, title, body):
    token = cfg.get("PUSHPLUS_TOKEN")
    if not token:
        return None
    data = urllib.parse.urlencode(
        {"token": token, "title": title, "content": body,
         "template": "html"}).encode()
    return _post("https://www.pushplus.plus/send", data)


def send_webhook(cfg, title, body):
    url = cfg.get("WEBHOOK_URL")
    if not url:
        return None
    payload = json.dumps({"text": title + "\n" + body}, ensure_ascii=False).encode()
    return _post(url, payload, {"Content-Type": "application/json"})


def send_email(cfg, title, body):
    host = cfg.get("SMTP_HOST")
    user = cfg.get("SMTP_USER")
    pwd = cfg.get("SMTP_PASS")
    to = cfg.get("SMTP_TO") or user
    if not (host and user and pwd and to):
        return None
    port = int(cfg.get("SMTP_PORT", "465"))
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = user
    msg["To"] = to
    if port == 465:
        srv = smtplib.SMTP_SSL(host, port, timeout=25,
                               context=ssl.create_default_context())
    else:
        srv = smtplib.SMTP(host, port, timeout=25)
        srv.starttls(context=ssl.create_default_context())
    srv.login(user, pwd)
    srv.sendmail(user, [to], msg.as_string())
    srv.quit()
    return (250, b"sent")


SENDERS = [send_serverchan, send_pushplus, send_email, send_webhook]


# ---------------------------------------------------------------- 主流程
def main(argv):
    dry = "--dry-run" in argv
    url = None
    if "--url" in argv:
        i = argv.index("--url")
        if i + 1 < len(argv):
            url = argv[i + 1].strip()

    cfg = load_conf()
    if not url:
        url = find_url(cfg)
    if not url:
        print("没找到隧道地址（隧道没起来？）")
        return 1

    # 去重：和上次一样就不推
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        last = open(STATE, encoding="utf-8").read().strip()
    except Exception:
        last = ""
    if url == last and "--force" not in argv:
        print("地址未变，跳过：%s" % url)
        return 0

    host = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
    title = "控制校正验算器已启动"
    body = ("访问地址（手机/电脑都能开）：\n%s\n\n服务器：%s\n时间：%s\n\n"
            "提示：这是 Quick Tunnel 临时地址，重启后会变。"
            % (url, host, time.strftime("%Y-%m-%d %H:%M:%S")))

    if dry:
        print("[dry-run] 标题:", title)
        print("[dry-run] 正文:\n" + body)
        return 0

    sent = 0
    for fn in SENDERS:
        try:
            r = fn(cfg, title, body)
            if r is not None:
                print("%-14s -> %s" % (fn.__name__, r))
                sent += 1
        except Exception as e:
            print("%-14s -> 失败: %s" % (fn.__name__, e))
    if not sent:
        print("没有可用渠道，请先在 %s 里配一个" % CONF)
        return 0

    try:
        with open(STATE, "w", encoding="utf-8") as f:
            f.write(url)
    except Exception:
        pass
    print("已推送 %d 个渠道：%s" % (sent, url))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
