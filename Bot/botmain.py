"""
botmain.py
==========
主程序。核心功能全部挂在底部常驻键盘：📋 菜单 / 🎁 邀请 / 💰 充值 / 👤 我的
/start 仍然是唯一的"聊天框斜杠命令"入口（用来打开主菜单/处理邀请码）；
管理员额外拥有一组专属斜杠命令（/ban /unban /jf /kf /query），
在管理员自己的聊天里输入 "/" 会弹出这些命令的提示列表。
"""

import threading
import time

import telebot
from telebot import types

import config
import db
import logger
import payment
import ui
from modules import FREE_MODULES, PAID_MODULES, get_module

bot = telebot.TeleBot(config.BOT_TOKEN)

# 用户当前"正在等待输入什么"的状态机：
#   {"action": "tool", "tier": "paid", "key": "stock"}
#   {"action": "recharge_amount", "method": "usdt"}
#   {"action": "admin_broadcast"}
#   {"action": "admin_ban_reason", "target_uid": 123}
PENDING = {}


# =========================================================
# 通用小工具
# =========================================================

def _editor_source_from_message(message):
    """把管理员消息中的自定义 Emoji entity 序列化为可持久化的编辑器 token。"""
    text = message.text or ""
    entities = [e for e in (message.entities or []) if getattr(e, "type", "") == "custom_emoji" and getattr(e, "custom_emoji_id", None)]
    if not entities:
        return text

    # Telegram entity offset/length 使用 UTF-16 code units，转换为 Python 字符串索引。
    def py_index(utf16_offset):
        units = 0
        for i, ch in enumerate(text):
            if units >= utf16_offset:
                return i
            units += len(ch.encode("utf-16-le")) // 2
        return len(text)

    replacements = []
    for e in entities:
        start = py_index(e.offset)
        end = py_index(e.offset + e.length)
        fallback = text[start:end]
        replacements.append((start, end, f"[[tg_emoji:{e.custom_emoji_id}|{fallback}]]"))

    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _sync_user(tg_user, invite_code_used=None):
    return db.get_or_create_user(
        tg_user.id,
        tg_user.username,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        invite_code_used=invite_code_used,
    )


def _guard_banned(chat_id, user_row) -> bool:
    """封禁用户拦截：返回 True 表示已拦截（调用方应直接 return）。"""
    if user_row and user_row.get("banned"):
        reason = user_row.get("ban_reason") or "未说明原因"
        bot.send_message(chat_id, f"🚫 你已被封禁，原因：{reason}")
        return True
    return False


def _query_cost_hint():
    paid_titles = [m["title"] for m in PAID_MODULES.values()]
    if not paid_titles:
        return "暂无付费项目"
    first = list(PAID_MODULES.values())[0]
    return f"{first['title']} {first['cost']}积分/次 等"


# =========================================================
# 主菜单卡片
# =========================================================

def _send_home(chat_id, message_id=None):
    text = ui.intro_card_text(
        config.BOT_DISPLAY_NAME,
        config.BOT_SLOGAN,
        config.USDT_TO_POINTS,
        _query_cost_hint(),
        config.SUPPORT_USERNAME,
        config.CHANNEL_URL,
    )
    markup = ui.kb([
        [("🆓 免费查询", "menu:free"), ("💎 付费查询", "menu:paid")],
        [("🎁 邀请好友", "invite:show"), ("💰 充值积分", "recharge:home")],
        [("👤 我的信息", "profile:show")],
    ])
    if config.is_admin(chat_id):
        markup.row(types.InlineKeyboardButton("🛠 管理面板", callback_data="admin:home"))
    ui.render(bot, chat_id, message_id, text, markup, page_key="home")


# =========================================================
# /start —— 唯一的斜杠命令入口
# =========================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    parts = message.text.split(maxsplit=1)
    invite_code = parts[1].strip() if len(parts) > 1 else None

    user_row = _sync_user(message.from_user, invite_code_used=invite_code)
    if _guard_banned(message.chat.id, user_row):
        return

    bot.send_message(
        message.chat.id,
        "欢迎使用！核心功能都在下面的键盘上 👇",
        reply_markup=ui.main_reply_keyboard(),
    )
    _send_home(message.chat.id)

    if config.is_admin(message.from_user.id):
        _register_admin_commands(message.from_user.id)


def _register_admin_commands(admin_id):
    try:
        bot.set_my_commands(
            commands=[
                types.BotCommand("start", "打开主菜单"),
                types.BotCommand("ban", "封禁用户：/ban uid [原因]"),
                types.BotCommand("unban", "解封用户：/unban uid"),
                types.BotCommand("jf", "加积分：/jf uid 数量"),
                types.BotCommand("kf", "扣积分：/kf uid 数量"),
                types.BotCommand("query", "查用户：/query uid或关键字"),
            ],
            scope=types.BotCommandScopeChat(chat_id=admin_id),
        )
    except Exception:
        pass


# =========================================================
# 底部常驻键盘的四个入口（reply keyboard 按钮按普通文本消息处理）
# =========================================================

@bot.message_handler(func=lambda m: m.text in ("📋 菜单", "🎁 邀请", "💰 充值", "👤 我的"))
def reply_keyboard_router(message):
    user_row = _sync_user(message.from_user)
    if _guard_banned(message.chat.id, user_row):
        return
    PENDING.pop(message.from_user.id, None)

    if message.text == "📋 菜单":
        _send_home(message.chat.id)
    elif message.text == "🎁 邀请":
        _show_invite(message.chat.id, None, user_row)
    elif message.text == "💰 充值":
        _show_recharge_home(message.chat.id, None)
    elif message.text == "👤 我的":
        _show_profile(message.chat.id, None, user_row)


# =========================================================
# 免费 / 付费查询面板（自适应大小按钮）
# =========================================================

def _show_tool_panel(chat_id, message_id, tier):
    modules = FREE_MODULES if tier == "free" else PAID_MODULES
    title = "🆓 免费查询" if tier == "free" else "💎 付费查询"

    if not modules:
        text = ui.header(title) + "\n暂无可用功能"
        markup = ui.kb([[("⬅️ 返回", "back:home")]])
        ui.render(bot, chat_id, message_id, text, markup, page_key=tier)
        return

    items = sorted(modules.values(), key=lambda m: m["title"])
    markup = ui.adaptive_keyboard(items, lambda it: f"tool:{tier}:{it['key']}")
    markup.row(types.InlineKeyboardButton("⬅️ 返回", callback_data="back:home"))

    cost_note = "" if tier == "free" else "\n（点击后按提示输入内容，扣除对应积分）"
    text = ui.header(title) + cost_note
    # 无论当前有没有模块，都保留 page_key，这样管理员始终可以编辑
    # “免费查询 / 付费查询”面板；模块按钮仍由当前注册表实时生成。
    ui.render(bot, chat_id, message_id, text, markup, page_key=tier)


@bot.callback_query_handler(func=lambda c: c.data in ("menu:free", "menu:paid"))
def cb_menu(call):
    user_row = _sync_user(call.from_user)
    if _guard_banned(call.message.chat.id, user_row):
        return
    tier = "free" if call.data == "menu:free" else "paid"
    _show_tool_panel(call.message.chat.id, call.message.message_id, tier)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "back:home")
def cb_back_home(call):
    _send_home(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("tool:"))
def cb_tool_open(call):
    user_row = _sync_user(call.from_user)
    if _guard_banned(call.message.chat.id, user_row):
        return

    _, tier, key = call.data.split(":", 2)
    mod = get_module(tier, key)
    if not mod:
        bot.answer_callback_query(call.id, "功能不存在或已下线", show_alert=True)
        return

    if tier == "paid" and user_row["points"] < mod["cost"]:
        bot.answer_callback_query(
            call.id, f"积分不足，需要 {mod['cost']} 积分，当前 {user_row['points']} 积分", show_alert=True
        )
        return

    PENDING[call.from_user.id] = {"action": "tool", "tier": tier, "key": key}
    bot.send_message(call.message.chat.id, f"{mod['emoji']} {mod['prompt']}")
    bot.answer_callback_query(call.id)


def _run_tool_with_input(chat_id, user_id, tier, key, user_input):
    mod = get_module(tier, key)
    if not mod:
        bot.send_message(chat_id, "功能不存在或已下线")
        return

    if tier == "paid":
        user_row = db.get_user(user_id)
        if not user_row or user_row["points"] < mod["cost"]:
            bot.send_message(chat_id, "积分不足，请先充值。")
            return

    # 查询固定产生两条消息：先发送进行中提示，再发送最终反馈。
    bot.send_message(chat_id, f"🔎 正在查询 {mod['title']}，请稍候…")

    try:
        result = mod["run"](user_input)
    except Exception as e:
        result = f"执行出错：{e}"

    if tier == "paid":
        db.add_points(user_id, -mod["cost"], f"付费查询:{mod['title']}")
        logger.log_action(user_id, "query", mod["title"], -mod["cost"])
        result += f"\n\n💎 本次消耗 {mod['cost']} 积分"
    else:
        logger.log_action(user_id, "query", mod["title"], 0)

    sent = bot.send_message(chat_id, result)
    ui.react(bot, chat_id, sent.message_id, config.REACTION_ON_TOOL_RESULT, big=False)


# =========================================================
# 邀请面板
# =========================================================

def _show_invite(chat_id, message_id, user_row):
    me = bot.get_me()
    link = f"https://t.me/{me.username}?start={user_row['invite_code']}"
    count = db.get_invite_count(user_row["user_id"])
    text = (
        ui.header("🎁 邀请好友", "🎁")
        + f"\n每成功邀请 1 人，你获得 <b>{config.INVITE_REWARD_POINTS}</b> 积分\n"
        + f"已邀请：<b>{count}</b> 人\n\n"
        + f"你的专属邀请链接：\n{link}"
    )
    markup = ui.kb([[("⬅️ 返回", "back:home")]])
    ui.render(bot, chat_id, message_id, text, markup, page_key="invite")


@bot.callback_query_handler(func=lambda c: c.data == "invite:show")
def cb_invite(call):
    user_row = _sync_user(call.from_user)
    if _guard_banned(call.message.chat.id, user_row):
        return
    _show_invite(call.message.chat.id, call.message.message_id, user_row)
    bot.answer_callback_query(call.id)


# =========================================================
# 我的信息面板
# =========================================================

def _show_profile(chat_id, message_id, user_row):
    text = (
        ui.header("👤 我的信息", "👤")
        + f"\nUID：<code>{user_row['user_id']}</code>\n"
        + f"积分余额：<b>{user_row['points']}</b>\n"
        + f"邀请码：<code>{user_row['invite_code']}</code>\n"
        + f"注册时间：{user_row['created_at']}"
    )
    markup = ui.kb([
        [("💰 去充值", "recharge:home"), ("🎁 邀请好友", "invite:show")],
        [("⬅️ 返回", "back:home")],
    ])
    # 自定义 profile 模板中的动态变量必须每次从当前数据库记录重新注入，
    # 这样管理员编辑 UI 后，积分/UID/邀请码/注册时间仍然保持实时。
    profile_variables = {
        "uid": user_row["user_id"],
        "points": user_row["points"],
        "invite_code": user_row["invite_code"],
        "created_at": user_row["created_at"],
        "username": user_row.get("username") or "",
        "invite_count": db.get_invite_count(user_row["user_id"]),
    }
    ui.render(
        bot,
        chat_id,
        message_id,
        text,
        markup,
        page_key="profile",
        variables=profile_variables,
    )


@bot.callback_query_handler(func=lambda c: c.data == "profile:show")
def cb_profile(call):
    user_row = _sync_user(call.from_user)
    if _guard_banned(call.message.chat.id, user_row):
        return
    _show_profile(call.message.chat.id, call.message.message_id, user_row)
    bot.answer_callback_query(call.id)


# =========================================================
# 充值面板：USDT 链上自动到账 / OKPay 跳转支付
# =========================================================

def _show_recharge_home(chat_id, message_id):
    text = (
        ui.header("💰 充值积分", "💰")
        + f"\n1 USDT或者3TRX = {config.USDT_TO_POINTS} 积分\n\n选择充值方式："
    )
    markup = ui.kb([
        [("🔗 USDT/TRX 链上自动到账", "recharge:method:usdt")],
        [("⚡ OKPay 快捷支付", "recharge:method:okpay")],
        [("⬅️ 返回", "back:home")],
    ])
    ui.render(bot, chat_id, message_id, text, markup, page_key="recharge")


@bot.callback_query_handler(func=lambda c: c.data == "recharge:home")
def cb_recharge_home(call):
    user_row = _sync_user(call.from_user)
    if _guard_banned(call.message.chat.id, user_row):
        return
    _show_recharge_home(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("recharge:method:"))
def cb_recharge_method(call):
    user_row = _sync_user(call.from_user)
    if _guard_banned(call.message.chat.id, user_row):
        return
    method = call.data.split(":")[-1]
    PENDING[call.from_user.id] = {"action": "recharge_amount", "method": method}
    bot.send_message(
        call.message.chat.id,
        f"请输入充值金额（USDT，最低 {config.MIN_ORDER_AMOUNT}）："
    )
    bot.answer_callback_query(call.id)


def _handle_recharge_amount(message, method):
    try:
        amount = float(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "请输入有效的数字金额。")
        return

    user_id = message.from_user.id
    try:
        if method == "usdt":
            order_id, address = payment.create_usdt_order(user_id, amount)
            text = (
                f"📮 订单号：<code>{order_id}</code>\n"
                f"💰 金额：{amount} USDT\n"
                f"🏦 收款地址：<code>{address}</code>\n\n"
                f"转账完成后点击下方按钮检查到账（{config.PAYMENT_EXPIRE_MINUTES}分钟内有效，"
                f"系统也会自动扫描）。"
            )
            markup = ui.kb([[("🔍 检查到账", f"recharge:check:usdt:{order_id}")]])
            bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")

        elif method == "okpay":
            order_id, pay_url = payment.create_okpay_order(user_id, amount)
            text = (
                f"📮 订单号：<code>{order_id}</code>\n"
                f"💰 金额：{amount} USDT\n\n"
                f"点击下方按钮跳转完成支付，支付成功后点击“检查到账”。"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⚡ 前往支付", url=pay_url))
            markup.add(types.InlineKeyboardButton("🔍 检查到账", callback_data=f"recharge:check:okpay:{order_id}"))
            bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")

    except Exception as e:
        bot.send_message(message.chat.id, f"下单失败：{e}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("recharge:check:"))
def cb_recharge_check(call):
    user_row = _sync_user(call.from_user)
    if _guard_banned(call.message.chat.id, user_row):
        return

    _, _, method, order_id = call.data.split(":", 3)
    result = payment.check_usdt_payment(order_id) if method == "usdt" else payment.check_okpay_payment(order_id)

    if not result.get("success"):
        bot.answer_callback_query(call.id, result.get("message", "查询失败"), show_alert=True)
        return

    if result.get("confirmed"):
        bot.answer_callback_query(call.id, "✅ 到账成功！", show_alert=True)
        sent = bot.send_message(
            call.message.chat.id,
            f"🎉 充值成功！到账 {result.get('amount')} USDT，获得 {result.get('points_credit')} 积分。",
        )
        ui.react(bot, call.message.chat.id, sent.message_id, config.REACTION_ON_PAYMENT, big=True)
    else:
        bot.answer_callback_query(call.id, "尚未检测到到账，请稍后再试。", show_alert=True)


# =========================================================
# 管理面板
# =========================================================

def _admin_home_panel():
    text = ui.header("🛠 管理面板", "🛠")
    markup = ui.kb([
        [("👥 用户列表", "admin:users:0")],
        [("🏦 收款地址池", "admin:addr")],
        [("📢 广播消息", "admin:broadcast")],
        [("⬅️ 返回", "back:home")],
    ])
    return text, markup


@bot.callback_query_handler(func=lambda c: c.data == "admin:home")
def cb_admin_home(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    text, markup = _admin_home_panel()
    ui.render(bot, call.message.chat.id, call.message.message_id, text, markup, page_key="admin_home")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:editpage:"))
def cb_admin_edit_page(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return

    page_key = call.data.split(":", 2)[-1]
    current = db.get_page_content(page_key)
    if current is None:
        current = ""
    PENDING[call.from_user.id] = {
        "action": "admin_edit_page",
        "page_key": page_key,
    }
    bot.send_message(
        call.message.chat.id,
        "✏️ <b>编辑此页面</b>\n\n"
        "直接发送新的页面显示文本，原内容会被覆盖。\n"
        "支持 Emoji / 自定义 Emoji（直接粘贴即可）。\n"
        "需要引用效果时，把内容放在成对的 <code>%</code> 之间，例如：\n\n"
        "%我编辑的消息\n我编辑的换行消息%\n\n"
        "不在 <code>%...%</code> 中的内容会按普通文本显示。\n"
        "积分/用户信息页面支持动态变量，例如：<code>{{uid}}</code>、<code>{{points}}</code>、"
        "<code>{{invite_code}}</code>、<code>{{created_at}}</code>。\n\n"
        f"当前自定义内容：\n<code>{__import__('html').escape(current, quote=False) if current else '（尚未自定义，当前使用程序默认文本）'}</code>",
        parse_mode="HTML",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:users:"))
def cb_admin_users(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    offset = int(call.data.split(":")[-1])
    rows = db.list_users(limit=10, offset=offset)
    if not rows:
        text = ui.header("👥 用户列表") + "\n没有更多用户了"
        markup = ui.kb([[("⬅️ 返回", "admin:home")]])
        ui.render(bot, call.message.chat.id, call.message.message_id, text, markup)
        bot.answer_callback_query(call.id)
        return

    lines = [ui.header("👥 用户列表")]
    buttons = []
    for r in rows:
        name = db.display_name(r)
        status = "🚫" if r["banned"] else "✅"
        lines.append(f"{status} {name}（UID:{r['user_id']}）· {r['points']}积分")
        buttons.append([types.InlineKeyboardButton(f"{name} (UID:{r['user_id']})", callback_data=f"admin:user:{r['user_id']}")])

    markup = types.InlineKeyboardMarkup()
    for b in buttons:
        markup.row(*b)
    nav = []
    if offset > 0:
        nav.append(types.InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin:users:{max(0, offset-10)}"))
    nav.append(types.InlineKeyboardButton("下一页 ➡️", callback_data=f"admin:users:{offset+10}"))
    markup.row(*nav)
    markup.row(types.InlineKeyboardButton("⬅️ 返回", callback_data="admin:home"))

    ui.render(bot, call.message.chat.id, call.message.message_id, "\n".join(lines), markup)
    bot.answer_callback_query(call.id)


def _admin_user_detail_panel(target_uid):
    row = db.get_user(target_uid)
    if not row:
        return "用户不存在", ui.kb([[("⬅️ 返回", "admin:users:0")]])
    name = db.display_name(row)
    status = "🚫 已封禁" if row["banned"] else "✅ 正常"
    text = (
        ui.header(f"👤 {name}")
        + f"\nUID：<code>{row['user_id']}</code>\n"
        + f"用户名：@{row['username'] or '无'}\n"
        + f"积分：{row['points']}\n状态：{status}\n"
        + f"注册时间：{row['created_at']}"
    )
    ban_btn = ("✅ 解封", f"admin:unban:{target_uid}") if row["banned"] else ("🚫 封禁", f"admin:banreason:{target_uid}")
    markup = ui.kb([
        [("➕ 加积分", f"admin:addpts:{target_uid}"), ("➖ 扣积分", f"admin:subpts:{target_uid}")],
        [ban_btn],
        [("⬅️ 返回", "admin:users:0")],
    ])
    return text, markup


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:user:"))
def cb_admin_user_detail(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    target_uid = int(call.data.split(":")[-1])
    text, markup = _admin_user_detail_panel(target_uid)
    ui.render(bot, call.message.chat.id, call.message.message_id, text, markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:unban:"))
def cb_admin_unban(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    target_uid = int(call.data.split(":")[-1])
    db.set_ban(target_uid, False)
    logger.log_action(call.from_user.id, "admin", f"解封 UID:{target_uid}")
    bot.answer_callback_query(call.id, "已解封")
    text, markup = _admin_user_detail_panel(target_uid)
    ui.render(bot, call.message.chat.id, call.message.message_id, text, markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:banreason:"))
def cb_admin_ban_reason_prompt(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    target_uid = int(call.data.split(":")[-1])
    PENDING[call.from_user.id] = {"action": "admin_ban_reason", "target_uid": target_uid}
    bot.send_message(call.message.chat.id, f"请输入封禁 UID {target_uid} 的原因（直接发送文字）：")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:addpts:") or c.data.startswith("admin:subpts:"))
def cb_admin_points_prompt(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    action, target_uid = call.data.split(":")[1], int(call.data.split(":")[-1])
    sign = 1 if action == "addpts" else -1
    PENDING[call.from_user.id] = {"action": "admin_points", "target_uid": target_uid, "sign": sign}
    bot.send_message(call.message.chat.id, f"请输入要{'增加' if sign>0 else '扣除'}的积分数量：")
    bot.answer_callback_query(call.id)


def _apply_admin_points(admin_id, chat_id, target_uid, delta):
    new_balance = db.add_points(target_uid, delta, f"管理员操作(admin:{admin_id})")
    logger.log_action(admin_id, "admin", f"{'加' if delta>0 else '扣'}积分 UID:{target_uid} {delta}", delta)
    sent = bot.send_message(chat_id, f"操作成功。UID {target_uid} 当前积分：{new_balance}")
    ui.react(bot, chat_id, sent.message_id, config.REACTION_ON_ADMIN_ACTION, big=False)


# --- 收款地址池 ---

def _admin_addr_panel():
    addrs = payment.admin_list_addresses()
    lines = [ui.header("🏦 收款地址池")]
    buttons = []
    for i, a in enumerate(addrs):
        status = "✅" if a["enabled"] else "⏸"
        lines.append(f"{status} a{i}: <code>{a['address']}</code>（待处理 {a['pending_count']} 单）")
        buttons.append(types.InlineKeyboardButton(
            f"{'停用' if a['enabled'] else '启用'} a{i}",
            callback_data=f"admin:addrtoggle:{a['address']}",
        ))
    markup = types.InlineKeyboardMarkup()
    for b in buttons:
        markup.row(b)
    markup.row(types.InlineKeyboardButton("➕ 添加地址", callback_data="admin:addrnew"))
    markup.row(types.InlineKeyboardButton("⬅️ 返回", callback_data="admin:home"))
    return "\n".join(lines), markup


@bot.callback_query_handler(func=lambda c: c.data == "admin:addr")
def cb_admin_addr(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    text, markup = _admin_addr_panel()
    ui.render(bot, call.message.chat.id, call.message.message_id, text, markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:addrtoggle:"))
def cb_admin_addr_toggle(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    address = call.data.split(":", 2)[-1]
    addrs = {a["address"]: a for a in payment.admin_list_addresses()}
    row = addrs.get(address)
    if row and row["enabled"]:
        payment.admin_remove_address(address)
    else:
        payment.admin_add_address(address)
    text, markup = _admin_addr_panel()
    ui.render(bot, call.message.chat.id, call.message.message_id, text, markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "admin:addrnew")
def cb_admin_addr_new(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    PENDING[call.from_user.id] = {"action": "admin_addr_new"}
    bot.send_message(call.message.chat.id, "请输入要添加的 USDT 收款地址：")
    bot.answer_callback_query(call.id)


# --- 广播 ---

@bot.callback_query_handler(func=lambda c: c.data == "admin:broadcast")
def cb_admin_broadcast_prompt(call):
    if not config.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "无权限", show_alert=True)
        return
    PENDING[call.from_user.id] = {"action": "admin_broadcast"}
    bot.send_message(call.message.chat.id, "请输入要广播的内容：")
    bot.answer_callback_query(call.id)


def _run_broadcast(admin_id, text):
    ids = db.list_all_user_ids()
    ok, fail = 0, 0
    for uid in ids:
        try:
            bot.send_message(uid, text)
            ok += 1
        except Exception:
            fail += 1
        time.sleep(config.BROADCAST_INTERVAL_SECONDS)
    bot.send_message(admin_id, f"📢 广播完成：成功 {ok}，失败 {fail}")


# =========================================================
# 管理员斜杠命令：/ban /unban /jf /kf /query
# =========================================================

@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    if not config.is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(message.chat.id, "用法：/ban uid [原因]")
        return
    target_uid = int(parts[1])
    reason = parts[2] if len(parts) > 2 else "违规操作"
    db.set_ban(target_uid, True, reason)
    logger.log_action(message.from_user.id, "admin", f"封禁 UID:{target_uid} 原因:{reason}")
    bot.send_message(message.chat.id, f"已封禁 UID {target_uid}，原因：{reason}")


@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    if not config.is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(message.chat.id, "用法：/unban uid")
        return
    target_uid = int(parts[1])
    db.set_ban(target_uid, False)
    logger.log_action(message.from_user.id, "admin", f"解封 UID:{target_uid}")
    bot.send_message(message.chat.id, f"已解封 UID {target_uid}")


@bot.message_handler(commands=["jf", "kf"])
def cmd_points(message):
    if not config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3 or not parts[1].isdigit():
        bot.send_message(message.chat.id, "用法：/jf uid 数量  或  /kf uid 数量")
        return
    target_uid = int(parts[1])
    try:
        amount = int(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "数量必须是整数")
        return
    delta = amount if message.text.startswith("/jf") else -amount
    _apply_admin_points(message.from_user.id, message.chat.id, target_uid, delta)


@bot.message_handler(commands=["query"])
def cmd_query(message):
    if not config.is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "用法：/query uid或用户名关键字")
        return
    results = db.find_users(parts[1].strip())
    if not results:
        bot.send_message(message.chat.id, "没有找到匹配的用户")
        return
    lines = ["🔎 查询结果："]
    for r in results:
        name = db.display_name(r)
        status = "🚫" if r["banned"] else "✅"
        lines.append(f"{status} {name}（UID:{r['user_id']}）· {r['points']}积分")
    bot.send_message(message.chat.id, "\n".join(lines))


# =========================================================
# 统一文本消息处理：根据 PENDING 状态分发
# =========================================================

@bot.message_handler(func=lambda m: True, content_types=["text"])
def catch_all_text(message):
    user_id = message.from_user.id
    state = PENDING.get(user_id)
    if not state:
        return  # 没有待处理状态，忽略（reply keyboard 按钮已被上面的 handler 处理）

    user_row = _sync_user(message.from_user)
    if _guard_banned(message.chat.id, user_row):
        PENDING.pop(user_id, None)
        return

    action = state["action"]

    if action == "tool":
        PENDING.pop(user_id, None)
        _run_tool_with_input(message.chat.id, user_id, state["tier"], state["key"], message.text.strip())

    elif action == "recharge_amount":
        PENDING.pop(user_id, None)
        _handle_recharge_amount(message, state["method"])

    elif action == "admin_ban_reason":
        if not config.is_admin(user_id):
            PENDING.pop(user_id, None)
            return
        PENDING.pop(user_id, None)
        target_uid = state["target_uid"]
        db.set_ban(target_uid, True, message.text.strip())
        logger.log_action(user_id, "admin", f"封禁 UID:{target_uid} 原因:{message.text.strip()}")
        bot.send_message(message.chat.id, f"已封禁 UID {target_uid}")

    elif action == "admin_points":
        if not config.is_admin(user_id):
            PENDING.pop(user_id, None)
            return
        PENDING.pop(user_id, None)
        try:
            amount = int(message.text.strip())
        except ValueError:
            bot.send_message(message.chat.id, "请输入整数")
            return
        delta = amount * state["sign"]
        _apply_admin_points(user_id, message.chat.id, state["target_uid"], delta)

    elif action == "admin_addr_new":
        if not config.is_admin(user_id):
            PENDING.pop(user_id, None)
            return
        PENDING.pop(user_id, None)
        ok, msg = payment.admin_add_address(message.text.strip())
        bot.send_message(message.chat.id, msg)

    elif action == "admin_edit_page":
        if not config.is_admin(user_id):
            PENDING.pop(user_id, None)
            return
        PENDING.pop(user_id, None)
        page_key = state["page_key"]
        db.set_page_content(page_key, _editor_source_from_message(message), updated_by=user_id)
        logger.log_action(user_id, "admin", f"编辑页面:{page_key}")
        bot.send_message(message.chat.id, f"✅ 页面 <code>{page_key}</code> 已保存。", parse_mode="HTML")

        # 如果原消息仍在聊天里，则立即重新渲染；否则新发一条预览。
        preview_variables = None
        if page_key == "profile":
            preview_row = db.get_user(user_id) or _sync_user(message.from_user)
            preview_variables = {
                "uid": preview_row["user_id"],
                "points": preview_row["points"],
                "invite_code": preview_row["invite_code"],
                "created_at": preview_row["created_at"],
                "username": preview_row.get("username") or "",
                "invite_count": db.get_invite_count(preview_row["user_id"]),
            }
        preview_text = ui._render_editable_text(
            message.text,
            variables=preview_variables,
        )
        markup = ui.kb([[('⬅️ 返回', 'back:home')]])
        ui.render(
            bot,
            message.chat.id,
            None,
            preview_text,
            markup,
            page_key=page_key,
            variables=preview_variables,
        )

    elif action == "admin_broadcast":
        if not config.is_admin(user_id):
            PENDING.pop(user_id, None)
            return
        PENDING.pop(user_id, None)
        text = message.text
        threading.Thread(target=_run_broadcast, args=(user_id, text), daemon=True).start()
        bot.send_message(message.chat.id, "广播已开始，完成后会单独通知你结果。")


# =========================================================
# OKPay 回调通知服务器（轻量 HTTP，独立线程运行）
# =========================================================

def _run_okpay_callback_server():
    """
    简单的 webhook 接收服务：接收 OKPay 的异步到账通知。
    仅在配置了 OKPAY_NOTIFY_URL 时才需要启动；
    生产环境建议用 nginx/gunicorn 之类的正式方案部署，这里给一个可直接跑起来的最小实现。
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs
    import json

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {k: v[0] for k, v in parse_qs(raw).items()}

            ok, msg = payment.handle_okpay_callback(payload)
            self.send_response(200 if ok else 400)
            self.end_headers()
            self.wfile.write(msg.encode("utf-8"))

        def log_message(self, fmt, *args):
            pass  # 静默默认日志，避免刷屏

    port = int(__import__("os").getenv("OKPAY_CALLBACK_PORT", "8088"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


# =========================================================
# 后台定时任务：自动扫描 USDT 待支付订单
# =========================================================

def _auto_scan_loop():
    while True:
        try:
            result = payment.auto_scan_pending()
            for c in result.get("confirmed", []):
                try:
                    sent = bot.send_message(
                        c["user_id"],
                        f"🎉 检测到充值到账 {c['amount']} USDT，获得 {c['points_credit']} 积分！",
                    )
                    ui.react(bot, c["user_id"], sent.message_id, config.REACTION_ON_PAYMENT, big=True)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(config.AUTO_SCAN_INTERVAL_SECONDS)


# =========================================================
# 入口
# =========================================================

def main():
    db.init_db()
    if config.USDT_ADDRESS_POOL:
        payment.init_addresses()

    threading.Thread(target=_auto_scan_loop, daemon=True).start()

    if config.OKPAY_NOTIFY_URL:
        threading.Thread(target=_run_okpay_callback_server, daemon=True).start()

    for admin_id in config.ADMIN_IDS:
        _register_admin_commands(admin_id)

    print("Bot 正在运行...")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
