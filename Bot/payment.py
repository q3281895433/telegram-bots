"""
payment.py
==========
通用支付网关，支持两种方式：

1. usdt  —— TON 链上 USDT(jetton) 自动到账检测
2. okpay —— 签名下单（HMAC-SHA256），调用 /shop/payLink 生成支付链接，
            用户点击后跳转 Telegram 机器人 @okpay 完成支付

两种方式共用同一张 payments 表和同一套订单状态机（pending/confirmed/expired/cancelled），
上层 bot 代码不需要关心具体支付方式的差异。

按官方文档《OKPay 商户对接文档(完整版·HMAC-SHA256新协议)》第 2 节实现签名，
创建订单固定使用 POST /shop/payLink（文档 6.1 节），并对 OKPay 的响应做验签
（防止响应被篡改）。
"""

import time
import uuid
import hmac
import hashlib
import requests
from datetime import datetime, timedelta, timezone

import config
import db

TZ = timezone(timedelta(hours=config.TIMEZONE_OFFSET_HOURS))


def init_addresses():
    if not config.USDT_ADDRESS_POOL:
        raise RuntimeError("USDT_RECEIVE_ADDRESS_POOL 未配置任何收款地址")
    db.init_address_pool(config.USDT_ADDRESS_POOL)


def _new_order_id(prefix, user_id):
    return f"{prefix}-{user_id}-{uuid.uuid4().hex[:10].upper()}"


# =========================================================
# 下单：由业务模块调用，amount 的含义（多少额度/次数）由模块自己算
# =========================================================

def create_usdt_order(user_id, usdt_amount):
    if usdt_amount <= 0:
        raise ValueError("充值金额必须大于0")
    if usdt_amount < config.MIN_ORDER_AMOUNT:
        raise ValueError(f"充值金额不能低于 {config.MIN_ORDER_AMOUNT} USDT")

    address = db.get_available_address()
    if not address:
        raise RuntimeError("没有可用的收款地址，请联系管理员添加。")

    order_id = _new_order_id("USDT", user_id)
    db.create_payment(order_id, user_id, "usdt", address, usdt_amount)
    return order_id, address


# =========================================================
# OKPay 签名（HMAC-SHA256，按官方文档第 2 节实现）
# =========================================================

def _flatten(params, prefix=""):
    """嵌套对象用点号展开：{"data": {"order_id": "x"}} -> {"data.order_id": "x"}"""
    items = {}
    for k, v in params.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten(v, key))
        else:
            items[key] = v
    return items


def _okpay_build_base(params: dict) -> str:
    """
    构造签名原文 base，严格按文档 2.1 节六步执行：
      1. 去掉 sign 字段
      2. 去掉值为 null 或空字符串的字段（但保留 0 / "0" / false）
      3. 嵌套对象用点号展开
      4. 布尔值转字符串 true/false，其余值原样转字符串（数字不重新格式化）
      5. 按键名 ASCII 升序排序
      6. 以 key=value 用 & 直接拼接，值不做任何 URL 编码
    """
    flat = _flatten(params)
    parts = []
    for k, v in sorted(flat.items()):
        if k == "sign":
            continue
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        else:
            v = str(v)
        parts.append(f"{k}={v}")
    return "&".join(parts)


def _okpay_sign(params: dict) -> str:
    """sign = UPPER( HMAC_SHA256(base, token) )，64 位大写十六进制"""
    base = _okpay_build_base(params)
    return hmac.new(
        config.OKPAY_APP_TOKEN.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()


def verify_okpay_notify(payload: dict) -> bool:
    """
    验证 OKPay 响应 / 异步回调的签名是否合法（恒定时间比较）。
    用于：
      1) 创建订单接口的返回值验签
      2) 收到 callback_url 回调时的验签（充值/出款通知）
    """
    if "sign" not in payload:
        return False
    incoming_sign = str(payload["sign"]).upper()
    expected_sign = _okpay_sign(payload)
    return hmac.compare_digest(incoming_sign, expected_sign)


def _okpay_common_params():
    """每个请求必须携带的公共字段：id / timestamp / nonce"""
    return {
        "id": config.OKPAY_APP_ID,
        "timestamp": int(time.time()),
        "nonce": uuid.uuid4().hex,  # 32 位随机字符串，满足 8-128 位要求
    }


def _okpay_request(path: str, business_params: dict) -> dict:
    """
    统一的 OKPay 签名请求封装。
    path 例如 "/payLink"、"/checkDeposit"、"/balance" 等（相对于接口前缀 /shop）。
    """
    url = config.OKPAY_API_ROOT.rstrip("/") + config.OKPAY_API_PREFIX + path

    params = _okpay_common_params()
    params.update(business_params)
    params["sign"] = _okpay_sign(params)

    resp = requests.post(url, data=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    status = data.get("status")
    if status != "success":
        raise RuntimeError(f"OKPay 请求失败：{data.get('msg', data)}")

    if not verify_okpay_notify(data):
        raise RuntimeError("OKPay 响应签名校验失败，可能被篡改或 token 配置错误")

    return data.get("data", {})


# =========================================================
# OKPay：6.1 创建支付链接 payLink
# =========================================================

def _okpay_create_order_request(unique_id, amount, coin="USDT",
                                 name=None, callback_url=None, return_url=None):
    """
    调用 OKPay 创建支付链接接口（POST /shop/payLink），
    返回 (order_id, pay_url)。
    pay_url 形如 https://t.me/okpay?start=shop_deposit_xxx，
    用户点击后会跳进 Telegram 机器人 @okpay 完成支付，全程无需再手动输入金额。
    """
    business_params = {
        "amount": str(amount),
        "coin": coin,
        "unique_id": unique_id,
    }
    if name:
        business_params["name"] = name
    if callback_url:
        business_params["callback_url"] = callback_url
    if return_url:
        business_params["return_url"] = return_url

    data = _okpay_request("/payLink", business_params)

    order_id = data.get("order_id")
    pay_url = data.get("pay_url")
    if not pay_url:
        raise RuntimeError(f"OKPay 响应里没有找到支付链接，原始返回：{data}")
    return order_id, pay_url


def create_okpay_order(user_id, amount):
    """
    业务层入口：给某个用户创建一笔 OKPay 充值订单。
    返回 (order_id, pay_url)：
      order_id 是 OKPay 平台订单号（用于后续查单/对账，写入本地 payments 表）
      pay_url  是要发给用户点击跳转的支付链接
    """
    if amount <= 0:
        raise ValueError("支付金额必须大于0")
    if not config.OKPAY_APP_ID or not config.OKPAY_APP_TOKEN:
        raise RuntimeError("OKPay 未配置 APP_ID / APP_TOKEN，请先在 .env 里填写。")

    unique_id = _new_order_id("OKPAY", user_id)  # 商户侧唯一订单号，用于幂等去重

    platform_order_id, pay_url = _okpay_create_order_request(
        unique_id,
        amount,
        coin="USDT",
        callback_url=(config.OKPAY_NOTIFY_URL or None),
        return_url=(config.OKPAY_REDIRECT_URL or None),
    )

    db.create_payment(unique_id, user_id, "okpay", platform_order_id or config.OKPAY_APP_ID, amount)

    return platform_order_id, pay_url


# =========================================================
# OKPay：6.2 查询充值订单 checkDeposit（按商户侧 unique_id 查询）
# =========================================================

def check_okpay_deposit(unique_id):
    """查单兜底：如果异步回调没收到，可以用这个按 unique_id 轮询充值订单状态。"""
    return _okpay_request("/checkDeposit", {"unique_id": unique_id})


# =========================================================
# OKPay：6.3 按平台订单号查询 checkTransferByTxid
# =========================================================

def check_okpay_by_txid(order_id):
    """用平台订单号（order_id / txid）查询，仅能查询属于本商户的订单。"""
    return _okpay_request("/checkTransferByTxid", {"txid": order_id})


# =========================================================
# OKPay：6.6 查询商户余额 balance
# =========================================================

def okpay_balance():
    """查询商户主账户余额，返回 {"usdt": ..., "trx": ..., "cny": ...}"""
    return _okpay_request("/balance", {})


# =========================================================
# TON / toncenter 查询（USDT 专用）
# =========================================================

def _toncenter_get(params):
    headers = {}
    if config.TONCENTER_API_KEY:
        headers["X-API-Key"] = config.TONCENTER_API_KEY
    resp = requests.get(config.TONCENTER_API_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _get_transfers(destination):
    params = {
        "jetton_master": config.USDT_JETTON_MASTER,
        "destination": destination,
        "limit": 100,
    }
    return _toncenter_get(params)


def _parse_amount(raw_amount):
    return int(raw_amount) / 1_000_000  # USDT on TON uses 6 decimals


def _extract_tx_hash(tx):
    return tx.get("transaction_hash") or tx.get("tx_hash") or tx.get("hash")


def _amount_to_points(amount):
    """USDT 金额 -> 积分，汇率取 config.USDT_TO_POINTS（默认 1 USDT = 7 积分）。"""
    return int(amount * config.USDT_TO_POINTS)


def _match_and_confirm(payment_row, transfers):
    order_id = payment_row["order_id"]
    expected = float(payment_row["expected_amount"])
    order_created = datetime.strptime(
        payment_row["created_at"], "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=TZ)

    for tx in transfers:
        tx_time = tx.get("transaction_time") or tx.get("created_at") or tx.get("timestamp")
        if not tx_time:
            continue
        try:
            if isinstance(tx_time, (int, float)):
                tx_dt = datetime.fromtimestamp(tx_time, TZ)
            else:
                if tx_time.endswith("Z"):
                    tx_time = tx_time[:-1] + "+00:00"
                tx_dt = datetime.fromisoformat(tx_time).astimezone(TZ)
            if tx_dt < order_created:
                continue
        except Exception:
            continue

        tx_hash = _extract_tx_hash(tx)
        if not tx_hash:
            continue

        raw_amount = tx.get("amount")
        if raw_amount is None:
            continue
        try:
            amount = _parse_amount(raw_amount)
        except Exception:
            continue

        if amount < expected:
            continue

        credit = _amount_to_points(amount)
        if credit <= 0:
            continue

        success = db.confirm_payment(order_id, amount, credit, tx_hash)
        if not success:
            continue

        db.add_points(payment_row["user_id"], credit, f"USDT充值 {amount} USDT ({tx_hash[:12]}...)")

        return {
            "success": True,
            "confirmed": True,
            "order_id": order_id,
            "user_id": payment_row["user_id"],
            "amount": amount,
            "points_credit": credit,
            "tx_hash": tx_hash,
        }

    return {"success": True, "confirmed": False}


def check_usdt_payment(order_id):
    """用户点击"检查到账"按钮时调用（手动触发一次核账）"""
    payment_row = db.get_payment(order_id)
    if not payment_row:
        return {"success": False, "message": "订单不存在。"}

    if payment_row["status"] == "confirmed":
        return {
            "success": True,
            "confirmed": True,
            "amount": payment_row["paid_amount"],
            "points_credit": payment_row["points_credit"],
        }

    if payment_row["status"] in ("expired", "cancelled"):
        return {"success": False, "message": f"订单已{payment_row['status']}，请重新发起支付。"}

    try:
        data = _get_transfers(payment_row["receive_target"])
    except Exception as e:
        return {"success": False, "message": f"区块链查询失败：{e}"}

    transfers = data.get("jetton_transfers", [])
    return _match_and_confirm(payment_row, transfers)


def check_okpay_payment(order_id):
    """用户点击"检查到账"按钮时调用（OKPay 版本，查单兜底回调）"""
    payment_row = db.get_payment(order_id)
    if not payment_row:
        return {"success": False, "message": "订单不存在。"}

    if payment_row["status"] == "confirmed":
        return {
            "success": True,
            "confirmed": True,
            "amount": payment_row["paid_amount"],
            "points_credit": payment_row["points_credit"],
        }

    if payment_row["status"] in ("expired", "cancelled"):
        return {"success": False, "message": f"订单已{payment_row['status']}，请重新发起支付。"}

    try:
        data = check_okpay_deposit(order_id)
    except Exception as e:
        return {"success": False, "message": f"查单失败：{e}"}

    if int(data.get("status", 0)) != 1:
        return {"success": True, "confirmed": False}

    paid_amount = float(data.get("amount", payment_row["expected_amount"]))
    credit = int(paid_amount * config.OKPAY_TO_POINTS)
    tx_hash = data.get("txid") or data.get("order_id") or order_id

    success = db.confirm_payment(order_id, paid_amount, credit, tx_hash)
    if success:
        db.add_points(payment_row["user_id"], credit, f"OKPay充值 {paid_amount} USDT ({order_id})")

    return {
        "success": True,
        "confirmed": True,
        "amount": paid_amount,
        "points_credit": credit,
    }


def handle_okpay_callback(payload: dict):
    """
    供 webhook 服务器调用：OKPay 异步回调到账通知。
    payload 需先验签（verify_okpay_notify），此函数假定已验签通过。
    返回 (ok: bool, message: str)。
    """
    if not verify_okpay_notify(payload):
        return False, "签名校验失败"

    unique_id = payload.get("unique_id") or payload.get("order_id")
    payment_row = db.get_payment(unique_id) if unique_id else None
    if not payment_row:
        return False, "订单不存在"

    if payment_row["status"] == "confirmed":
        return True, "订单已处理"

    if int(payload.get("status", 0)) != 1:
        return True, "非成功状态，忽略"

    paid_amount = float(payload.get("amount", payment_row["expected_amount"]))
    credit = int(paid_amount * config.OKPAY_TO_POINTS)
    tx_hash = payload.get("txid") or unique_id

    success = db.confirm_payment(unique_id, paid_amount, credit, tx_hash)
    if success:
        db.add_points(payment_row["user_id"], credit, f"OKPay回调充值 {paid_amount} USDT ({unique_id})")
        return True, "已到账"
    return True, "订单已处理（并发）"


def cancel_order(order_id):
    return db.cancel_payment(order_id)


# =========================================================
# 后台定时任务：自动扫描所有待支付 USDT 订单
# （OKPay 走回调 + 手动查单兜底，不需要轮询扫描）
# =========================================================

def auto_scan_pending():
    expired = db.expire_pending_payments()
    pending = [p for p in db.get_all_pending_payments() if p["method"] == "usdt"]

    if not pending:
        return {"confirmed": [], "expired": expired}

    by_address = {}
    for row in pending:
        by_address.setdefault(row["receive_target"], []).append(row)

    confirmed_results = []
    for address, rows in by_address.items():
        try:
            data = _get_transfers(address)
        except Exception:
            continue
        transfers = data.get("jetton_transfers", [])

        for row in rows:
            fresh = db.get_payment(row["order_id"])
            if not fresh or fresh["status"] != "pending":
                continue
            result = _match_and_confirm(fresh, transfers)
            if result.get("confirmed"):
                confirmed_results.append(result)

    return {"confirmed": confirmed_results, "expired": expired}


# =========================================================
# 管理员：收款地址管理
# =========================================================

def admin_add_address(address):
    return db.add_address(address)


def admin_remove_address(address):
    return db.remove_address(address)


def admin_list_addresses():
    return db.list_addresses()
