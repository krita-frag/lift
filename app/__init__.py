"""Lift DCC 启动器应用模块。

提供 GUI 界面、Profile 管理和 Rez 环境解析功能。
"""

try:
    from importlib.metadata import version as _get_version

    __version__ = _get_version("lift")
except Exception:
    __version__ = "0.1.0"
