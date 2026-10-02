# Telegram Bots

保存桌面 VSCode Bot 目录中的三个独立 Python 机器人项目：`Bot`、`3ysBot`、`zpbot`。

源码 Token 改用 `BOT_TOKEN` 环境变量；`zpbot` 收款地址使用 `WALLET_ADDRESS`。原始本地凭据、用户数据库、运行日志不包含在仓库内。各目录独立安装 requirements.txt。

`Bot` 从同目录 .env 读取配置；其他两个项目启动前请设置环境变量。项目自带的外部服务配置保持原始功能，未运行机器人或调用外部查询接口。
