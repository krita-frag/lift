import os
import sys
from pathlib import Path, PureWindowsPath, PurePosixPath


def normalize_path(path_str: str) -> str:
    if sys.platform == "win32":
        return str(PureWindowsPath(path_str))
    return str(PurePosixPath(path_str))


def find_executable(name: str, search_paths: list[str]) -> str | None:
    extensions = [""]
    if sys.platform == "win32":
        extensions.extend([".exe", ".bat", ".cmd"])

    for directory in search_paths:
        for ext in extensions:
            candidate = os.path.join(directory, name + ext)
            if os.path.isfile(candidate):
                if sys.platform == "win32" or os.access(candidate, os.X_OK):
                    return candidate
    return None


def split_path_env(path_env: str | list[str]) -> list[str]:
    if isinstance(path_env, list):
        return path_env
    return path_env.split(os.pathsep) if path_env else []


def discover_tools(context) -> list[dict]:
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

def scan_packages():
    packages = {}
    if env_dir := os.environ.get("LIFT_PACKAGES_DIR"):
        packages_dir = Path(env_dir)
    else:
        packages_dir = Path(__file__).parent.parent.parent / "packages"

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
