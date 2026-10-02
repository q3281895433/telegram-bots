import os
import re
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]

# ---------- 推广文案（每条结果都会带上） ----------
PROMO = (
    "\n━━━━━━━━━━━━━━\n"
    "源自 @SZAD1246 @iaoxue1246 @SZAD1246mini\n"
    "机器人免费，添加至群组搭建同款吧！"
)

def verify_three_elements(user_input: str):
    # 1. 优先提取身份证（避免数字串干扰）
    id_match = re.search(r'\d{17}[\dXx]', user_input)
    if not id_match:
        return None
    id_card = id_match.group(0)

    # 2. 从剩余内容提取手机号
    remaining_after_id = user_input.replace(id_card, '', 1)
    phone_match = re.search(r'1[3-9]\d{9}', remaining_after_id)
    if not phone_match:
        return None
    phone = phone_match.group(0)

    # 3. 提取姓名：移除身份证和手机号，取最长的连续中文片段
    remaining = remaining_after_id.replace(phone, '', 1)
    chinese_parts = re.findall(r'[\u4e00-\u9fa5]+', remaining)
    if not chinese_parts:
        return None
    name = max(chinese_parts, key=len)   # 选最长的中文名

    # 调用接口
    try:
        resp = requests.get(
            "http://38.246.253.149:5949/gougou446/yys3ys",
            params={"xm": name, "sfz": id_card, "sjh": phone},
            timeout=15,
        )
        resp_text = resp.text.lower()
        if 'true' in resp_text:
            result = "🟢 三要素一致"
        elif 'false' in resp_text:
            result = "🔴 三要素不一致"
        else:
            result = f"⚠️ 接口返回异常：{resp.text}"

        return (
            f"{result}\n"
            f"━━━━━━━━━━━━━━\n"
            f"姓名：{name}\n"
            f"身份证：{id_card}\n"
            f"手机号：{phone}\n"
            f"{PROMO}"
        )
    except Exception as e:
        return f"⚠️ 查询失败：{e}\n{PROMO}"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    if not user_input:
        return
    result = verify_three_elements(user_input)
    if result:
        await update.message.reply_text(result)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "👋 发送包含以下三要素的消息即可验证：\n"
        "• 姓名（中文）\n"
        "• 身份证号（18位）\n"
        "• 手机号（11位）\n\n"
        "顺序不限，可用空格、逗号等分隔。\n"
        "格式正确时我会自动回复结果，否则我不会回应。\n\n"
        "示例：姓名 身份证号 手机号"
    )
    await update.message.reply_text(help_text)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 机器人已启动（新逻辑：身份证优先，姓名取最长中文）...")
    application.run_polling()

if __name__ == "__main__":
    main()
