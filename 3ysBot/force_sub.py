"""
1force_sub.py
============
通用"必须加入指定频道/群组才能使用机器人"模块。
不依赖本项目其他文件（db.py / ui.py 等），可以直接复制到别的
pyTelegramBotAPI (telebot) 机器人项目里使用。

依赖：
  pip install pyTelegramBotAPI

前提条件（很重要，漏了会导致误判"未加入"）：
  1. 机器人必须已经加到目标频道/群组里，并且是"管理员"身份，
     否则 get_chat_member 会报错（403 Forbidden 之类），
     本模块会把查询失败统一当成"未加入"处理，不会崩溃，
     但用户会被一直拦在门口，所以务必先把机器人设为管理员。
  2. 私有频道/群组没有 @username，本模块会退化成尝试用
     bot.export_chat_invite_link() 现取邀请链接（同样要求机器人是管理员，
     且有"邀请用户"权限），取不到的话按钮就不会显示跳转链接，
     只显示频道名字，需要你手动在文案里补充加入方式。

配置（两种方式任选一种）：

  方式一 · 环境变量（推荐，和本项目 config.py 的风格一致）：
      REQUIRED_CHANNELS=@channel1,@group1,-1001234567890
    然后：
      import os
      REQUIRED_CHANNELS = [c.strip() for c in os.getenv("REQUIRED_CHANNELS", "").split(",") if c.strip()]
      force_sub.configure(REQUIRED_CHANNELS)

  方式二 · 直接在代码里写死：
      force_sub.configure(["@my_channel", "@my_group", -1001234567890])

用法（三个接入点，缺一个就会有绕过入口）：
  1. /start 命令处理函数里，创建/校验完用户后：
        not_joined = force_sub.get_not_joined(bot, user_id)
        if not_joined:
            text, markup = force_sub.gate_panel(not_joined)
            bot.send_message(chat_id, text, reply_markup=markup,
                              parse_mode="HTML", disable_web_page_preview=True)
            return
  2. 所有 callback_query 的总入口最前面同样查一次；
     并且要单独处理 force_sub.CHECK_CALLBACK 这个 callback_data
     （用户点"我已加入，重新检查"按钮时触发）：
        if call.data == force_sub.CHECK_CALLBACK:
            not_joined = force_sub.get_not_joined(bot, user_id, use_cache=False)
            ...重新渲染面板或放行...
            return
  3. 所有文本消息的总入口最前面同样查一次。

三个点都要挂，否则用户可以绕开 /start 直接点按钮或发消息使用机器人。
"""

import time

from telebot import types

# ---------------------------------------------------------
# 配置
# ---------------------------------------------------------

# 每一项可以是 "@username" 或者数字 chat_id（int），必须加入才能使用机器人。
# 空列表 = 功能关闭，get_not_joined 永远返回 []，不影响原机器人任何逻辑。
REQUIRED_CHANNELS = ["@SZAD1246mini","@iaoxue1246"]

CHECK_CALLBACK = "fsub:check"

# 简单的按用户缓存，避免"每点一次按钮就打一次 Telegram API"，
# 对活跃用户 / 高频交互场景比较友好。用户主动点"重新检查"时会强制跳过缓存。
_CACHE_TTL_SECONDS = 60
_cache = {}  # user_id -> (checked_at_ts, result_list)


def configure(required_channels):
    """程序启动时调用一次，传入 @username 或 chat_id 组成的列表。"""
    global REQUIRED_CHANNELS
    REQUIRED_CHANNELS = list(required_channels or [])


# ---------------------------------------------------------
# 核心检查逻辑
# ---------------------------------------------------------

def _normalize_ref(raw):
    """字符串形式的数字 chat_id（比如 "-1001234567890"）转成 int，@username 保持原样。"""
    if isinstance(raw, int):
        return raw
    raw = str(raw).strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


def _is_member(bot, chat_ref, user_id):
    try:
        member = bot.get_chat_member(chat_ref, user_id)
        # left / kicked 都算未加入；member/administrator/creator 才算已加入
        return member.status in ("member", "administrator", "creator")
    except Exception:
        # 机器人不是该频道/群管理员、频道不存在、被限流等情况统一按"未加入"处理，
        # 避免因为查询异常而放行或者直接让机器人崩溃。
        return False


def _describe_chat(bot, chat_ref):
    """返回 (显示名称, 跳转链接或 None)，查询失败时给出兜底文案。"""
    try:
        chat = bot.get_chat(chat_ref)
        name = chat.title or (f"@{chat.username}" if chat.username else str(chat_ref))
        if chat.username:
            url = f"https://t.me/{chat.username}"
        else:
            try:
                url = bot.export_chat_invite_link(chat_ref)
            except Exception:
                url = None
        return name, url
    except Exception:
        ref_str = str(chat_ref)
        fallback_url = f"https://t.me/{ref_str.lstrip('@')}" if ref_str.startswith("@") else None
        return ref_str, fallback_url


def get_not_joined(bot, user_id, use_cache=True):
    """
    返回用户还未加入的频道/群列表：
        [{"ref": "@xxx", "name": "显示名", "url": "https://t.me/xxx 或 None"}, ...]
    REQUIRED_CHANNELS 为空时直接返回 []。
    """
    if not REQUIRED_CHANNELS:
        return []

    if use_cache:
        cached = _cache.get(user_id)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    result = []
    for raw in REQUIRED_CHANNELS:
        chat_ref = _normalize_ref(raw)
        if _is_member(bot, chat_ref, user_id):
            continue
        name, url = _describe_chat(bot, chat_ref)
        result.append({"ref": raw, "name": name, "url": url})

    _cache[user_id] = (time.time(), result)
    return result


def clear_cache(user_id=None):
    """放行后可选调用，清掉缓存（不调用也没关系，最多等 _CACHE_TTL_SECONDS 自然过期）。"""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


# ---------------------------------------------------------
# 面板渲染（原生 telebot 组件，不依赖本项目的 ui.py，方便单独复用）
# ---------------------------------------------------------

def gate_panel(not_joined):
    """
    组装"请先加入以下频道/群组"提示文本 + inline 按钮。
    返回 (text, markup)，直接传给 bot.send_message / bot.edit_message_text。
    """
    lines = ["🔒 <b>使用前请先加入以下频道/群组</b>", "━" * 16, ""]
    markup = types.InlineKeyboardMarkup(row_width=1)

    for i, item in enumerate(not_joined, 1):
        lines.append(f"{i}. {item['name']}")
        if item["url"]:
            markup.add(types.InlineKeyboardButton(f"➡️ 加入 {item['name']}", url=item["url"]))
        else:
            lines.append("   （暂无法自动获取加入链接，请联系管理员）")

    lines.append("")
    lines.append("全部加入后，点击下方按钮重新检查：")
    markup.add(types.InlineKeyboardButton("✅ 我已加入，重新检查", callback_data=CHECK_CALLBACK))

    return "\n".join(lines), markup
