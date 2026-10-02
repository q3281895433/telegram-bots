"""
ui.py
=====
统一管理所有"面板"（一条消息 + 一组按钮）+ 底部常驻键盘 + 动态表情回应。

【本次改动】
1. 新增底部常驻回复键盘（reply keyboard）：📋 菜单 / 🎁 邀请 / 💰 充值 / 👤 我的
   —— 核心功能常驻在输入框旁边，不用记指令。
2. 新增"卡片式"介绍面板 render_intro_card()，参考截图里那种
   "图标 + 一行说明"的排版（充值/查询/我的信息 + 客服 + 频道）。
3. 新增自适应按钮排布 adaptive_keyboard()：
   —— 按钮文字（emoji+标题）短就两个一排（小按钮），
      长就独占一排（大按钮），自动判断，不用手动配置。
4. 新增 react()：给 Telegram Premium 用户发送动态大表情回应
   （setMessageReaction, is_big=True），用于支付成功/管理员操作等关键节点。

设计原则：
  - 所有功能优先通过 inline 按钮触发；底部 reply keyboard 只放 4 个入口，
    点击后展开对应的 inline 面板。
  - 每次响应尽量"编辑"同一条消息来切换面板，减少一次删除+一次发送的
    API 调用，观感也更连贯。
  - Telegram 官方 Bot 消息不支持自定义文字颜色，这里统一用
    加粗 / 分隔线 / emoji 色块来模拟视觉层次。
"""

from telebot import types
from html import escape as html_escape
import re

# ---------------------------------------------------------
# 视觉样式帮助函数
# ---------------------------------------------------------

def header(title: str, emoji: str = "🔷") -> str:
    return f"{emoji} <b>{title}</b> {emoji}\n" + ("━" * 16)


def divider() -> str:
    return "─" * 16


# ---------------------------------------------------------
# 底部常驻键盘（reply keyboard）—— 核心功能入口
# ---------------------------------------------------------

def main_reply_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=4)
    markup.add(
        types.KeyboardButton("📋 菜单"),
        types.KeyboardButton("🎁 邀请"),
        types.KeyboardButton("💰 充值"),
        types.KeyboardButton("👤 我的"),
    )
    return markup


# ---------------------------------------------------------
# 卡片式介绍面板（参考截图排版）
# ---------------------------------------------------------

def intro_card_text(bot_name, slogan, usdt_to_points, query_cost_hint,
                     support_username="", channel_url=""):
    lines = [
        f"<b>{bot_name}</b>",
        slogan,
        "",
        f"💰 充值：1 USDT = {usdt_to_points} 积分",
        f"📋 常用：{query_cost_hint}",
        "👤 我的信息：查看积分",
        divider(),
    ]
    if support_username:
        lines.append(f"📞 客服：@{support_username}")
    if channel_url:
        lines.append(f"📢 频道：{channel_url}")
    return "\n".join(lines)


# ---------------------------------------------------------
# 通用按钮构建
# ---------------------------------------------------------

def kb(rows):
    """
    rows: list[list[(text, callback_data)]] 或 list[list[types.InlineKeyboardButton]]
    快速构建 InlineKeyboardMarkup。
    """
    markup = types.InlineKeyboardMarkup(row_width=2)
    for row in rows:
        buttons = []
        for item in row:
            if isinstance(item, types.InlineKeyboardButton):
                buttons.append(item)
            else:
                text, data = item
                buttons.append(types.InlineKeyboardButton(text, callback_data=data))
        markup.row(*buttons)
    return markup


def url_button_row(text, url):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text, url=url))
    return markup


# ---------------------------------------------------------
# 自适应按钮排布：按钮文字长就独占一行（大按钮），
# 短就两个一排（小按钮）。
# ---------------------------------------------------------

# 阈值：emoji + 标题的显示宽度超过这个字符数，就单独占一整行。
# 中文字符按 2 算宽度，比较接近 Telegram 按钮的实际视觉宽度。
# 典型的 3-4 字标题（如"天气查询"）+emoji 宽度在 10-11 左右，应保持两个一排；
# 5 个中文字以上（如"实时股票行情"）才会独占一整行变成"大按钮"。
_LONG_BUTTON_WIDTH = 12


def _display_width(text: str) -> int:
    width = 0
    for ch in text:
        width += 2 if ord(ch) > 0x2E80 else 1  # 粗略判断是否为中日韩字符
    return width


def adaptive_keyboard(items, make_callback_data, columns_for_short=2):
    """
    items: list[dict]，每个 dict 至少包含 'emoji' 和 'title'（比如模块信息）
    make_callback_data: 函数 (item) -> callback_data 字符串
    返回 InlineKeyboardMarkup：
      - 短标题的按钮，两个一排
      - 长标题的按钮，独占一排（视觉上更突出，像"大按钮"）
    """
    markup = types.InlineKeyboardMarkup()
    short_buffer = []

    def flush_short():
        nonlocal short_buffer
        while short_buffer:
            markup.row(*short_buffer[:columns_for_short])
            short_buffer = short_buffer[columns_for_short:]

    for item in items:
        label = f"{item.get('emoji', '')} {item['title']}".strip()
        btn = types.InlineKeyboardButton(label, callback_data=make_callback_data(item))
        if _display_width(label) > _LONG_BUTTON_WIDTH:
            flush_short()
            markup.row(btn)
        else:
            short_buffer.append(btn)
    flush_short()
    return markup


# ---------------------------------------------------------
# 面板渲染：优先编辑已有消息，编辑失败再发新的
# ---------------------------------------------------------

_TG_EMOJI_RE = re.compile(r"\[\[tg_emoji:(\d+)\|([^\]]*)\]\]")
# 管理员编辑的页面允许保留这些 Telegram HTML 标签。
# 动态变量的值本身会先进行 HTML escape，避免用户数据破坏 parse_mode。
_ALLOWED_HTML_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|blockquote)(?:\s[^>]*)?>",
    re.IGNORECASE,
)
_DYNAMIC_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _render_editable_text(raw_text: str, variables=None) -> str:
    """
    页面编辑器专用渲染。

    支持：
    - %...%：渲染为 Telegram 引用块。
    - [[tg_emoji:ID|占位字符]]：恢复 Telegram 自定义 Emoji。
    - {{uid}} / {{points}} / {{invite_code}} / {{created_at}} 等动态变量。
    - 管理员模板中的常用 Telegram HTML 标签（<b>、<code> 等）会保留。
    - 动态变量的实际值会 HTML escape，避免用户数据破坏 Telegram HTML。
    """
    if raw_text is None:
        return ""

    variables = variables or {}

    # 先保存自定义 Emoji，避免后面的 HTML escape 破坏 Telegram 标签。
    emoji_tokens = []

    def stash_emoji(match):
        idx = len(emoji_tokens)
        emoji_tokens.append((match.group(1), match.group(2)))
        return f"\x00TGEMOJI{idx}\x00"

    prepared = _TG_EMOJI_RE.sub(stash_emoji, raw_text)

    # 动态变量必须在 HTML escape 之前替换，并对真实值进行 escape。
    def replace_variable(match):
        name = match.group(1)
        if name not in variables:
            # 未提供的变量保持原样，方便管理员继续编辑模板。
            return match.group(0)
        value = variables.get(name)
        return html_escape("" if value is None else str(value), quote=False)

    prepared = _DYNAMIC_VAR_RE.sub(replace_variable, prepared)

    # 保存允许的 HTML 标签；普通文字仍然 escape，避免用户输入破坏 parse_mode。
    html_tokens = []

    def stash_html(match):
        idx = len(html_tokens)
        html_tokens.append(match.group(0))
        return f"\x00HTMLTAG{idx}\x00"

    prepared = _ALLOWED_HTML_TAG_RE.sub(stash_html, prepared)

    parts = re.split(r"%(.*?)%", prepared, flags=re.DOTALL)
    out = []
    for idx, part in enumerate(parts):
        safe = html_escape(part, quote=False)
        if idx % 2 == 1:
            out.append(f"<blockquote>{safe}</blockquote>")
        else:
            out.append(safe)

    rendered = "".join(out)

    # 恢复管理员允许使用的 HTML 标签。
    for idx, tag in enumerate(html_tokens):
        rendered = rendered.replace(f"\x00HTMLTAG{idx}\x00", tag)

    # 最后恢复 Telegram 自定义 Emoji。
    for idx, (emoji_id, fallback_char) in enumerate(emoji_tokens):
        rendered = rendered.replace(
            f"\x00TGEMOJI{idx}\x00",
            f'<tg-emoji emoji-id="{emoji_id}">{html_escape(fallback_char, quote=False)}</tg-emoji>',
        )

    return rendered


def render(
    bot,
    chat_id,
    message_id,
    text,
    markup,
    parse_mode="HTML",
    page_key=None,
    variables=None,
):
    """
    渲染面板。

    page_key：允许管理员持久化覆盖页面文字。
    variables：给自定义页面模板提供实时动态变量，例如：
        {"uid": 123, "points": 100, "invite_code": "ABC", "created_at": "..."}
    """
    if page_key:
        try:
            import config
            import db
            saved = db.get_page_content(page_key)
            if saved is not None:
                text = _render_editable_text(saved, variables=variables)
            if config.is_admin(chat_id):
                # 复制键盘，避免修改调用方持有的 markup 对象导致按钮重复
                extra = types.InlineKeyboardButton(
                    "✏️ 编辑此页面", callback_data=f"admin:editpage:{page_key}"
                )
                rows = [list(row) for row in (markup.keyboard or [])]
                rows.append([extra])
                markup = types.InlineKeyboardMarkup(keyboard=rows)
        except Exception:
            pass

    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            return message_id
        except Exception:
            pass  # 消息内容没变化 / 消息已过期，走下面发新消息兜底

    sent = bot.send_message(
        chat_id, text, reply_markup=markup, parse_mode=parse_mode,
        disable_web_page_preview=True,
    )
    return sent.message_id


# ---------------------------------------------------------
# Telegram Premium 动态大表情回应
# ---------------------------------------------------------

def react(bot, chat_id, message_id, emoji="🎉", big=True):
    """
    给一条消息发送表情回应。普通用户看到的是静态小表情；
    Telegram Premium 用户点开会看到动态效果，is_big=True 时触发全屏大动画
    （该效果本身由 Telegram 客户端渲染，机器人只需要正常调用这个接口）。
    静默失败：表情回应属于锦上添花，不应该影响主流程。
    """
    import config
    if not config.ENABLE_EMOJI_REACTIONS:
        return
    try:
        bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[types.ReactionTypeEmoji(emoji=emoji)],
            is_big=big,
        )
    except Exception:
        pass
