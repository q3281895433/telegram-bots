"""
config.py
=========
统一读取环境变量。
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------
# Telegram
# ---------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("没有找到 BOT_TOKEN，请在 .env 中配置")

# 如需走本地代理，取消下面的注释并按需修改
# PROXY = {"https": "http://127.0.0.1:7877"}
PROXY = None

# ---------------------------------------------------------
# 管理员
# ---------------------------------------------------------

_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set()
for _item in _admin_raw.split(","):
    _item = _item.strip()
    if not _item:
        continue
    try:
        ADMIN_IDS.add(int(_item))
    except ValueError:
        pass


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------------------------------------------------------
# 数据库
# ---------------------------------------------------------

DB_PATH = os.getenv("DB_PATH", "bot_data.db")

# ---------------------------------------------------------
# 积分（只有"付费查询"消耗积分；免费查询永远不扣分）
# ---------------------------------------------------------

USDT_TO_POINTS = int(os.getenv("USDT_TO_POINTS", "7"))
OKPAY_TO_POINTS = int(os.getenv("OKPAY_TO_POINTS", "7"))
INVITE_REWARD_POINTS = int(os.getenv("INVITE_REWARD_POINTS", "2"))

# ---------------------------------------------------------
# 支付通用配置
# ---------------------------------------------------------

USDT_ADDRESS_POOL_RAW = os.getenv("USDT_RECEIVE_ADDRESS_POOL", "")
USDT_ADDRESS_POOL = [a.strip() for a in USDT_ADDRESS_POOL_RAW.split(",") if a.strip()]

USDT_JETTON_MASTER = os.getenv(
    "USDT_JETTON_MASTER",
    "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",
)

TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "")
TONCENTER_API_URL = "https://toncenter.com/api/v3/jetton/transfers"

MIN_ORDER_AMOUNT = float(os.getenv("MIN_ORDER_AMOUNT", "1"))
PAYMENT_EXPIRE_MINUTES = int(os.getenv("PAYMENT_EXPIRE_MINUTES", "30"))
AUTO_SCAN_INTERVAL_SECONDS = int(os.getenv("AUTO_SCAN_INTERVAL_SECONDS", "30"))

# ---------------------------------------------------------
# OKPay（HMAC-SHA256 新协议，文档：https://docs.okaypay.me/doc.html）
# ---------------------------------------------------------

OKPAY_APP_ID = os.getenv("OKPAY_APP_ID", "")
OKPAY_APP_TOKEN = os.getenv("OKPAY_APP_TOKEN", "")
OKPAY_API_ROOT = os.getenv("OKPAY_API_ROOT", "https://api.okaypay.me")
OKPAY_API_PREFIX = os.getenv("OKPAY_API_PREFIX", "/shop")
OKPAY_NOTIFY_URL = os.getenv("OKPAY_NOTIFY_URL", "")
OKPAY_REDIRECT_URL = os.getenv("OKPAY_REDIRECT_URL", "")

TIMEZONE_OFFSET_HOURS = int(os.getenv("TZ_OFFSET_HOURS", "8"))

# 广播：每发送一条消息之间的间隔秒数，避免触发 Telegram 限流
BROADCAST_INTERVAL_SECONDS = float(os.getenv("BROADCAST_INTERVAL_SECONDS", "0.05"))

# ---------------------------------------------------------
# 外部数据源（股票 / 天气），留空则使用免key的公共接口
# ---------------------------------------------------------

STOCK_API_KEY = os.getenv("STOCK_API_KEY", "")       # 可选：接入更专业的行情源时填
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")   # 可选：留空则用 wttr.in（免key）

# ---------------------------------------------------------
# 面板展示信息（主菜单卡片：客服 / 频道 / 底部推广位）
# ---------------------------------------------------------

BOT_DISPLAY_NAME = os.getenv("BOT_DISPLAY_NAME", "工具机器人")
BOT_SLOGAN = os.getenv("BOT_SLOGAN", "多功能查询 / 工具箱")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")   # 例如 sugelan91_bot（不含@）
CHANNEL_URL = os.getenv("CHANNEL_URL", "")             # 例如 https://t.me/xxx

# ---------------------------------------------------------
# Telegram Premium 动态表情回应（is_big=True 触发全屏大动画）
# 关闭：把 ENABLE_EMOJI_REACTIONS 设为 false
# ---------------------------------------------------------

ENABLE_EMOJI_REACTIONS = os.getenv("ENABLE_EMOJI_REACTIONS", "true").lower() == "true"
REACTION_ON_PAYMENT = os.getenv("REACTION_ON_PAYMENT", "🎉")
REACTION_ON_ADMIN_ACTION = os.getenv("REACTION_ON_ADMIN_ACTION", "👍")
REACTION_ON_TOOL_RESULT = os.getenv("REACTION_ON_TOOL_RESULT", "⚡")
