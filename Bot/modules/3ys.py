# modules/three_factor.py
import requests
import re
from . import register


def run(user_input: str) -> str:
    """
    提取输入中的手机号、身份证号和姓名，调用三要素验证接口。
    返回一致/不一致结果及详细信息。
    """
    # 提取手机号（11位，1开头）
    phone_match = re.search(r'1[3-9]\d{9}', user_input)
    phone = phone_match.group(0) if phone_match else None

    # 提取身份证号（18位，最后可能是X）
    id_match = re.search(r'\d{17}[\dXx]', user_input)
    id_card = id_match.group(0) if id_match else None

    if not phone or not id_card:
        return "⚠️ 输入格式有误，请确保包含正确的手机号和身份证号（18位）"

    # 剩余部分作为姓名，移除手机号和身份证号后清理
    remaining = user_input.replace(phone, '', 1).replace(id_card, '', 1)
    name = re.sub(r'[\s,，;；、]+', '', remaining).strip()
    if not name:
        return "⚠️ 未识别到姓名，请重新输入"

    # 调用三要素验证接口
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
            f"━━━━━━━━━━━━━━"
        )
    except Exception as e:
        return f"⚠️ 查询失败：{e}"


register(
    key="three_factor",         # 唯一 key
    title="三要素",          # 按钮标题
    emoji="❄️",                 # 按钮图标
    tier="free",                # 免费模块
    cost=0,                     # 每次查询消耗 0 积分
    prompt="请输入姓名、身份证号、手机号（顺序不限，可用空格分隔）：",
    run=run,
)
