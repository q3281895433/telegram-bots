#!/bin/bash
# zpbot 正确的 nohup 保活启动方式
# 用法：bash /root/zpbot/start.sh
cd /root/zpbot
nohup /root/zpbot/venv/bin/python -u /root/zpbot/Bot.py > /root/zpbot/bot.log 2>&1 &
echo "zpbot 已启动，PID: $!，日志: /root/zpbot/bot.log"
