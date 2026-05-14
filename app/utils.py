"""工具函数模块。

提供路径处理、可执行文件查找、环境变量序列化等通用工具函数。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = [
    "get_packages_dir",
    "get_profiles_dir",
    "normalize_path",
    "find_executable",
    "split_path_env",
    "discover_tools",
    "serialize_env",
    "scan_packages",
]


def get_packages_dir() -> Path:
    """获取 packages 目录路径。

    优先从 LIFT_PACKAGES_DIR 环境变量读取，否则使用默认路径。

    Returns:
        packages 目录的 Path 对象
    """
    if env_dir := os.environ.get("LIFT_PACKAGES_DIR"):
        return Path(env_dir)
    return Path(__file__).parent.parent.parent / "packages"


def get_profiles_dir() -> Path:
    """获取 profiles 目录路径。

    优先从 LIFT_PROFILES_DIR 环境变量读取，否则使用默认路径。

    Returns:
        profiles 目录的 Path 对象
    """
    if env_dir := os.environ.get("LIFT_PROFILES_DIR"):
        return Path(env_dir)
    return Path(__file__).parent.parent.parent / "profiles"


def normalize_path(path_str: str) -> str:
    """根据平台规范化路径字符串。

    Args:
        path_str: 原始路径字符串

    Returns:
        规范化后的路径字符串
    """
    if sys.platform == "win32":
        return str(PureWindowsPath(path_str))
    return str(PurePosixPath(path_str))


def find_executable(name: str, search_paths: list[str]) -> str | None:
    """在搜索路径中查找可执行文件。

    Args:
        name: 可执行文件名（不含扩展名）
        search_paths: 搜索路径列表

    Returns:
        可执行文件的完整路径，未找到则返回 None
    """
    extensions = [""]
    if sys.platform == "win32":
        extensions.extend([".exe", ".bat", ".cmd"])

    for directory in search_paths:
        for ext in extensions:
            candidate = os.path.join(directory, name + ext)
            if os.path.isfile(candidate) and (
                sys.platform == "win32" or os.access(candidate, os.X_OK)
            ):
                return candidate
    return None


def split_path_env(path_env: str | list[str]) -> list[str]:
    """将 PATH 环境变量分割为路径列表。

    Args:
        path_env: PATH 环境变量字符串或列表

    Returns:
        路径列表
    """
    if isinstance(path_env, list):
        return path_env
    return path_env.split(os.pathsep) if path_env else []


def discover_tools(context) -> list[dict]:
    """从解析上下文中发现可用工具。

    Args:
        context: Rez 解析上下文

    Returns:
        工具信息列表，每个工具包含 name、package、path
    """
    tools = []
    env = context.get_environ()
    path_dirs = split_path_env(env.get("PATH", ""))

    for pkg in context.resolved_packages:
        pkg_tools = getattr(pkg, "tools", None)
        if not pkg_tools:
            continue
        for tool in pkg_tools:
            tool_path = find_executable(tool, path_dirs)
            if tool_path:
                tools.append({
                    "name": tool,
                    "package": pkg.name,
                    "path": tool_path,
                })
    return tools


def serialize_env(env: dict) -> dict[str, str]:
    """将环境变量字典序列化为字符串值。

    将列表类型的值用 os.pathsep 连接为字符串。

    Args:
        env: 环境变量字典

    Returns:
        序列化后的字符串字典
    """
    serialized: dict[str, str] = {}
    for key, val in env.items():
        if isinstance(val, list):
            serialized[key] = os.pathsep.join(val)
        else:
            serialized[key] = str(val)
    return serialized


def scan_packages() -> dict[str, dict[str, dict[str, str]]]:
    """扫描 packages 目录，返回包信息字典。

    扫描结构: packages/<category>/<package>/<version>/package.py

    Returns:
        嵌套字典: {category: {package: {version: path}}}
    """
    packages: dict[str, dict[str, dict[str, str]]] = {}
    packages_dir = get_packages_dir()

    if not packages_dir.exists():
        return packages

    for category_dir in packages_dir.iterdir():
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        packages[category] = {}

        for pkg_dir in category_dir.iterdir():
            if not pkg_dir.is_dir():
                continue
            pkg_name = pkg_dir.name
            packages[category][pkg_name] = {}

            for ver_dir in pkg_dir.iterdir():
                if ver_dir.is_dir():
                    ver = ver_dir.name
                    pkg_file = ver_dir / "package.py"
                    if pkg_file.exists():
                        packages[category][pkg_name][ver] = str(ver_dir)

    return packages
