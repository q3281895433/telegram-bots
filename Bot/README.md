# 工具机器人 v3

## 这次改了什么

1. **底部常驻键盘**：`📋 菜单` `🎁 邀请` `💰 充值` `👤 我的` 四个入口常驻在输入框旁边，
   点开后展开对应的 inline 面板（卡片式排版，参考你给的截图风格）。
2. **菜单自动分类**：点 `📋 菜单` 展开 `🆓 免费查询` / `💎 付费查询` 两个子面板。
3. **按钮自动排版**：`ui.adaptive_keyboard()` 会按 emoji+标题的显示宽度自动判断
   —— 短标题（如"天气查询"）两个一排（小按钮），长标题（5 个汉字以上）
   独占一整行（大按钮），不需要手动配置。
4. **OKPay 完整接入**：HMAC-SHA256 签名、`/shop/payLink` 下单、响应验签、
   `checkDeposit` 查单兜底、异步回调接收服务（`OKPAY_NOTIFY_URL` 配置后自动启动）。
5. **模块自动扫描保留**：`modules/__init__.py` 完全不变——新增模块只需要在
   `modules/` 下新建文件、文件末尾调用 `register(...)`，重启即可，不用碰任何其它文件。
6. **管理面板显示名字**：用户列表/详情页优先显示"名字"，其次 `@用户名`，
   最后才是 UID；名字会在用户每次互动时自动跟着改名同步更新
   （`db.get_or_create_user()` 里做的，不需要额外操作）。
7. **管理员斜杠命令**：管理员的聊天里输入 `/` 会弹出命令提示：
   - `/ban uid [原因]` —— 封禁
   - `/unban uid` —— 解封
   - `/jf uid 数量` —— 加积分
   - `/kf uid 数量` —— 扣积分
   - `/query uid或关键字` —— 按 UID / 用户名 / 名字模糊查询用户
   （封禁原因、加/扣积分也仍然可以在管理面板里点按钮走"提示输入"的老流程，两种方式都保留。）
8. **Telegram Premium 动态表情**：`ui.react()` 在充值到账成功（大动画）、
   管理员操作成功、查询出结果时会调用 `setMessageReaction`。普通用户看到静态小表情，
   Premium 用户会看到动效——这是 Telegram 客户端自己渲染的，机器人只需要正常调用接口。
   不想要的话在 `.env` 里把 `ENABLE_EMOJI_REACTIONS` 设为 `false` 就整体关闭。
9. **数据完全兼容**：`users` / `addresses` / `payments` 三张表字段一个没删没改类型，
   老的 `bot_data.db` 可以直接复用；新增的 `first_name`/`last_name` 两列会在启动时
   自动 `ALTER TABLE` 补上，不影响已有数据。

## 新增的 3 个查询模块（示例）

| 模块 | tier | 数据源 | 说明 |
|---|---|---|---|
| 🌤 天气查询 | 免费 | wttr.in（无需 key） | 输入城市名即可 |
| 📊 股票查询 | 付费 1 积分 | Yahoo Finance 公开行情接口（无需 key） | 支持美股/港股(`0700.HK`)/A股(`600519.SS`) |
| 💵 USDT价格 | 付费 1 积分 | CoinGecko 公共接口（无需 key） | 直接点击即可查询 |

如果之后想接更专业的数据源（比如需要 key 的行情 API），把 key 填进 `.env` 的
`STOCK_API_KEY` / `WEATHER_API_KEY`，再改一下对应模块文件里的请求逻辑就行，
不影响其它模块。

## 关于压缩包安全检查

已经审查过你上传的 `OkPay自动支付回调.zip`：只有 4 个文件（PHP/Python 的签名参考代码 +
示例调用代码），没有 `eval`/`exec`/`os.system`/编码混淆等可疑代码，唯一请求的外部地址是
`api.okaypay.me`，跟官方文档一致。**建议你部署前仍然自己用 VirusTotal 之类的工具再扫一遍**
——我这边只能做静态代码审查，没有实时杀毒引擎权限。

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 然后把 BOT_TOKEN / ADMIN_IDS / OKPay 信息等填进去
python botmain.py
```

## 目录结构

```
config.py       环境变量集中读取
db.py           SQLite：用户/积分/邀请关系/支付订单/收款地址池（新增姓名字段，向后兼容）
payment.py      USDT(TON链上自动核账) + OKPay(签名下单+回调) 通用支付
ui.py           面板渲染 + 底部常驻键盘 + 自适应按钮排布 + 动态表情回应
logger.py       操作日志
modules/        工具模块目录（自动扫描加载，新增模块不用改这里）
  __init__.py   FREE_MODULES / PAID_MODULES 注册表 + 自动扫描
  weather.py    示例：天气查询（免费）
  stock.py      示例：股票查询（付费）
  usdt_price.py 示例：USDT价格（付费）
botmain.py      主程序：底部键盘 + inline 面板 + 管理员斜杠命令 + 自动扫描/回调线程
```

## 怎么新增一个工具模块（不变）

```python
# modules/xxx.py
def run(user_input: str) -> str:
    return f"你发的是：{user_input}"

from . import register

register(
    key="xxx",
    title="我的新工具",
    emoji="🆕",
    tier="paid",        # 或 "free"
    cost=1,              # 仅 tier="paid" 生效
    prompt="请输入内容：",
    run=run,
)
```
新建文件保存、重启机器人即可，标题字数会被自动检测决定按钮大小，不用额外配置。


## 页面编辑器（仅管理员）

可编辑面板会在管理员账号下自动出现 **✏️ 编辑此页面**。点击后直接发送新的显示文本，内容会保存到 SQLite 的 `page_contents` 表，重启机器人不会丢失。

引用 UI 使用成对的 `%`：

```text
普通文字

%我编辑的消息
我编辑的换行消息%

继续普通文字
```

其中 `%...%` 会渲染为 Telegram 引用块；不在 `%...%` 中的内容照常显示。Emoji 可以直接在 Telegram 输入框里输入或粘贴。

## 查询消息流程

用户提交一次查询后，机器人会先发送 `🔎 正在查询……`，模块执行结束后再单独发送最终查询反馈；因此一次完整查询固定有“正在查询”和“查询反馈”两条消息。

## 新增模块模板

复制 `modules/module_template.py.example` 为新的 `.py` 文件，修改 `key/title/emoji/tier/cost/prompt/run` 即可。模块目录会自动扫描，不需要修改 `modules/__init__.py`。
