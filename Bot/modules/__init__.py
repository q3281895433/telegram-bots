"""
modules/__init__.py
====================
工具模块注册表，按 tier 分成"免费查询"和"付费查询"两套。

采用【自动扫描 modules/ 目录】，不需要手写任何 import。
新增一个模块，只要在 modules/ 下新建 .py 文件、文件末尾调用
register(...) 就行，完全不用碰这个文件，也就不存在"忘记 import"
或"import 被格式化工具删掉"的问题。

如果想手动控制加载顺序/临时禁用某个模块，把对应文件名
放进下面的 _EXCLUDE 集合即可（不需要删除文件）。
"""

import importlib
import pkgutil

FREE_MODULES = {}
PAID_MODULES = {}

# 不想被自动加载的模块文件名（不含 .py 后缀），临时禁用某个工具时用
_EXCLUDE = {"__init__"}


def register(key, title, run, emoji="🧩", tier="free", cost=0, prompt="请输入内容："):
    """
    key    : 唯一标识，比如 'converter'。
             必须在 FREE_MODULES / PAID_MODULES 范围内各自唯一，
             重复的 key 会在启动时直接报错（而不是静默覆盖）。
    title  : 按钮上显示的名字（会自动根据字数决定占大按钮还是小按钮）
    run    : 函数 (user_input: str) -> str，返回要展示给用户的结果文本
    emoji  : 按钮图标
    tier   : 'free' 或 'paid'，决定挂在哪个面板下
    cost   : 仅 paid 模块生效，这次调用消耗多少积分
    prompt : 点击按钮后，提示用户输入什么
    """
    target = PAID_MODULES if tier == "paid" else FREE_MODULES

    if key in target:
        raise RuntimeError(
            f"模块 key 冲突：'{key}' 在 tier='{tier}' 下已经被注册过一次了，"
            f"请检查 modules/ 目录下是否有两个文件用了相同的 key。"
        )

    target[key] = {
        "key": key, "title": title, "emoji": emoji, "tier": tier, "cost": cost,
        "prompt": prompt, "run": run,
    }


def get_module(tier, key):
    return (PAID_MODULES if tier == "paid" else FREE_MODULES).get(key)


def _autoload():
    """
    扫描 modules/ 目录下所有 .py 文件并逐个 import，
    触发各文件末尾的 register(...) 调用。
    按文件名排序，保证每次启动加载顺序一致。
    """
    package_path = __path__
    package_name = __name__

    names = sorted(
        name for _, name, is_pkg in pkgutil.iter_modules(package_path)
        if not is_pkg and name not in _EXCLUDE
    )
    for name in names:
        importlib.import_module(f"{package_name}.{name}")


_autoload()
