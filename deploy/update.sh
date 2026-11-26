# -*- coding: utf-8 -*-
# 更新服务器上的应用
# 用法：在“服务器上”直接跑  bash ~/up/deploy/update.sh
# 前提：本机已把 deploy-package.zip 传到 ~/ ，见下面第 1 步
#
# 本机（PowerShell / CMD 都行，用全路径最稳）：
#   scp deploy-package.zip ubuntu@<your-server>:~/
#
# 服务器：
#   ssh ubuntu@<your-server>
#   bash ~/deploy/update.sh          # 第一次要手动解包一次，见下

set -e
APP=/opt/ctrl-checker
rm -rf ~/up
python3 -m zipfile -e ~/deploy-package.zip ~/up

sudo cp -f  ~/up/*.py "$APP"/
sudo mkdir -p "$APP"/templates "$APP"/static
sudo cp -rf ~/up/templates/. "$APP"/templates/
sudo cp -rf ~/up/static/.    "$APP"/static/

sudo systemctl restart ctrl-web
sleep 3
printf "本机自检: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8123/
curl -s http://127.0.0.1:8123/ | grep -c 'id="kind"' | sed 's/^/新前端标记数: /'
echo "完成。看日志: sudo journalctl -u ctrl-web -n 50 --no-pager"