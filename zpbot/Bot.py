import logging
import uuid
import os
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ========== 请替换为你自己的 Bot Token ==========
TOKEN = os.environ["BOT_TOKEN"]  # TODO: 从 BotFather 获取

# ========== 媒体文件路径（视频优先，图片备用） ==========
# 使用基于脚本所在目录的绝对路径，避免 nohup/systemd 启动时
# 工作目录(当前目录)不同导致找不到视频文件、静默降级成纯文字。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_PATH = os.path.join(BASE_DIR, "images", "telegram_premium.mp4")
IMAGE_PATH = os.path.join(BASE_DIR, "images", "telegram_premium.jpg")

# ========== 套餐信息（价格已修改） ==========
PLANS = {
    '3': ('3个月', '5 USDT'),
    '6': ('6个月', '10 USDT'),
    '12': ('1年', '16 USDT'),
}

# ========== 收款地址 ==========
WALLET_ADDRESS = os.environ["WALLET_ADDRESS"]
TRON_NETWORK = "TRC20"

# ========== 用户状态存储（内存） ==========
user_state = {}


async def send_media(chat_id, context, text, reply_markup=None):
    """
    优先发送视频，如果视频不存在则尝试发送图片，最后降级为纯文字。
    """
    # 1. 尝试发送视频
    if os.path.exists(VIDEO_PATH):
        try:
            with open(VIDEO_PATH, 'rb') as video:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            return
        except Exception as e:
            print(f"发送视频失败: {e}", flush=True)
    else:
        print(f"[WARN] 视频文件不存在，准备降级: {VIDEO_PATH}", flush=True)

    # 2. 尝试发送图片
    if os.path.exists(IMAGE_PATH):
        try:
            with open(IMAGE_PATH, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            return
        except Exception as e:
            print(f"发送图片失败: {e}")

    # 3. 降级为纯文字
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始命令：发送介绍和套餐选择按钮"""
    chat_id = update.effective_chat.id
    user_state[chat_id] = {'step': None}

    text = """
🌟 <b>星辰自助会员账号中心</b> 🌟
🎁 充值后会员账号将以 <b>+123456789-http://api.xinc?</b> 在 <b>1分钟内</b> 发送

💎 <b>全网最低价会员账号-源头商家</b>：
👑 3个月：5 USDT
✨ 6个月：10 USDT
🚀 1年：16 USDT

请选择你要充值的套餐👇
"""

    keyboard = [
        [InlineKeyboardButton("3个月账号", callback_data='plan_3')],
        [InlineKeyboardButton("6个月账号", callback_data='plan_6')],
        [InlineKeyboardButton("1年账号", callback_data='plan_12')],
    ]

    await send_media(chat_id, context, text, InlineKeyboardMarkup(keyboard))


async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户点击套餐按钮后，询问要充值的用户名"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith('plan_'):
        return

    plan = data.split('_')[1]
    chat_id = query.message.chat_id
    name, price = PLANS[plan]

    user_state[chat_id] = {'step': 'awaiting_username', 'plan': plan}

    text = f"""
📝 你选择了 <b>{name}</b>，价格 <b>{price}</b>

请发送你要充值的Telegram用户名（格式：<code>@username</code>）
例如：<code>@zhangsan</code>
"""

    await send_media(chat_id, context, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的 @用户名"""
    chat_id = update.effective_chat.id
    state = user_state.get(chat_id)

    if not state or state.get('step') != 'awaiting_username':
        return

    username = update.message.text.strip()

    if not username.startswith('@'):
        await send_media(chat_id, context, "⚠️ 用户名格式不正确，请以 @ 开头，例如 @zhangsan")
        return

    safe_username = escape(username)
    state['username'] = username
    state['step'] = 'awaiting_confirm'

    name, price = PLANS[state['plan']]

    text = f"""
🔍 正在搜索账号：<code>{safe_username}</code>

✅ 已找到该账号，请确认是否为以下账号充值？

👤 用户名：<code>{safe_username}</code>
💎 套餐：<b>{name}</b> - <b>{price}</b>

请点击下方按钮确认支付👇
"""

    keyboard = [
        [InlineKeyboardButton("✅ 确认支付", callback_data='confirm_payment')],
        [InlineKeyboardButton("❌ 取消", callback_data='cancel')],
    ]

    await send_media(chat_id, context, text, InlineKeyboardMarkup(keyboard))


async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认支付，创建订单并发送收款地址"""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    state = user_state.get(chat_id)
    if not state or state.get('step') != 'awaiting_confirm':
        await send_media(chat_id, context, "⚠️ 订单状态异常，请重新开始 /start")
        return

    username = state.get('username')
    safe_username = escape(username)
    name, price = PLANS[state['plan']]

    order_id = uuid.uuid4().hex[:8].upper()
    state['order_id'] = order_id
    state['step'] = 'awaiting_payment'

    text = f"""
🧾 <b>订单创建成功</b>

📋 订单号：<code>#{order_id}</code>
👤 充值账号：<code>{safe_username}</code>
💎 套餐：<b>{name}</b>
💰 金额：<b>{price}</b>

🔗 <b>请使用 {TRON_NETWORK} 网络转账到以下地址：</b>
<code>{WALLET_ADDRESS}</code>

⚠️ 请仔细确认地址无误后支付！
支付完成后，点击下方按钮查询到账状态👇
"""

    keyboard = [[InlineKeyboardButton("🔍 到款检测", callback_data='check_payment')]]
    await send_media(chat_id, context, text, InlineKeyboardMarkup(keyboard))


async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """到款检测：始终提示未查询到入账"""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    state = user_state.get(chat_id)
    if not state or state.get('step') != 'awaiting_payment':
        await send_media(chat_id, context, "⚠️ 当前没有待支付订单，请重新开始 /start")
        return

    text = f"""
🔍 <b>正在查询订单支付状态...</b>

❌ <b>未查询到入账</b>

请确认是否已向以下地址完成转账：
<code>{WALLET_ADDRESS}</code>

💡 支付成功后，会员将在 <b>2分钟内</b> 以礼物形式自动到账，无需其他操作。
"""

    keyboard = [[InlineKeyboardButton("🔍 再次检测", callback_data='check_payment')]]
    await send_media(chat_id, context, text, InlineKeyboardMarkup(keyboard))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消订单"""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_state[chat_id] = {'step': None}

    await send_media(chat_id, context, "已取消，欢迎重新开始 /start")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(plan_selected, pattern='^plan_'))
    app.add_handler(CallbackQueryHandler(confirm_payment, pattern='^confirm_payment$'))
    app.add_handler(CallbackQueryHandler(check_payment, pattern='^check_payment$'))
    app.add_handler(CallbackQueryHandler(cancel, pattern='^cancel$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"Bot is running... 视频路径: {VIDEO_PATH} 存在: {os.path.exists(VIDEO_PATH)}", flush=True)
    app.run_polling()


if __name__ == '__main__':
    main()
