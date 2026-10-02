# modules/twoys_query.py
import requests
import json
from . import register


def single_query(name, id_card):
    """
    查询二要素（姓名+身份证）是否一致。
    返回格式化结果字符串。
    """
    url = "https://www.ws101.cn/api/information/apply"
    payload = {
        "name": name,
        "verifytime": 0,
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "userId": "31852",
        "productId": "191",
        "pincodes": id_card,
        "phone": "18888888888"
    }
    headers = {
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        'Accept': "application/json, text/plain, */*",
        'Accept-Encoding': "gzip, deflate, br, zstd",
        'Content-Type': "application/json",
        'sec-ch-ua-platform': "\"Windows\"",
        'bid': "",
        'sec-ch-ua': "\"Chromium\";v=\"149\", \"Not)A;Brand\";v=\"24\"",
        'sec-ch-ua-mobile': "?0",
        'Origin': "https://www.ws101.cn",
        'X-Requested-With': "mark.via",
        'Sec-Fetch-Site': "same-origin",
        'Sec-Fetch-Mode': "cors",
        'Sec-Fetch-Dest': "empty",
        'Referer': "https://www.ws101.cn/",
        'Accept-Language': "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        'Cookie': "SECKEY_ABVK=ijgFfLv0OwKF0JZN3AjYGFSZhfzUzwrQ0rR/rCbB6ElafRuPaISEAQkKS9gQZV4D9lSj38356x2QelD6VcTTvQ%3D%3D; BMAP_SECKEY=ijgFfLv0OwKF0JZN3AjYGFSZhfzUzwrQ0rR_rCbB6Enx48DFmEn9ErhOvtQevgUfy6YWOKjN0elPXuWrIe9bpLVDzjSGRVl9Z04VgxF_pShhR2w-9q013LEjQwyNf1k9EsIVIDH2Xl4WAaMKKAcaFH1phKvshSS8-qWqbEHhqzBsY4d2clVICnOLRnAkXnQd_rTRxgCZvC9h4mysOzyxcg"
    }

    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=15)
        result = response.json()
        status = result.get('status')
        if status == 1:
            return f"✅ {name}（{id_card}）一致"
        elif status == 0:
            return f"❌ {name}（{id_card}）不一致"
        elif status == 301:
            return f"⭕ {name}（{id_card}）无效身份证"
        else:
            return f"⚠️ 未知状态码 {status}：{result.get('msg', '')}"
    except Exception as e:
        return f"🌐 请求失败：{str(e)}"


def run(user_input: str) -> str:
    """
    处理用户输入，支持单条或多条记录。
    每行格式：姓名 身份证号（空格分隔）。
    """
    lines = [line.strip() for line in user_input.split('\n') if line.strip()]
    if not lines:
        return "❌ 输入为空，请提供数据。"

    results = []
    for idx, line in enumerate(lines, start=1):
        parts = line.split()
        if len(parts) != 2:
            results.append(f"第{idx}行格式错误（需要2个字段：姓名 身份证号）：{line}")
            continue
        name, id_card = parts
        res = single_query(name, id_card)
        result_block = f"━━━ 第 {idx} 条 ━━━\n{res}"
        results.append(result_block)

    return "\n\n".join(results)


register(
    key="twoys_query",          # 唯一 key
    title="二要素",          # 按钮标题
    emoji="❄️",                 # 按钮图标
    tier="free",                # 免费模块
    cost=0,                     # 每次查询消耗 0 积分
    prompt="请输入记录（每行一条，字段用空格分隔：姓名 身份证号）：",
    run=run,
)
