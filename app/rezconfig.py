"""Rez 配置文件。

定义 Rez 包搜索路径和本地包路径。
"""

from app.utils import get_packages_dir

_packages_root = get_packages_dir()

packages_path = [
    str(_packages_root / "app"),
    str(_packages_root / "ext"),
    str(_packages_root / "int"),
    str(_packages_root / "proj"),
]

local_packages_path = str(_packages_root)
