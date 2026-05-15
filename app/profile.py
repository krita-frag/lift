"""Profile 管理模块。

提供 Profile 的创建、读取、更新、删除、导入、导出和应用功能。
"""

from __future__ import annotations

import ast
import atexit
import json
import os
import platform
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.utils import get_packages_dir, get_profiles_dir

__all__ = [
    "MANIFEST_FILENAME",
    "current_platform_key",
    "load_dcc_config",
    "get_version_subdir",
    "find_dcc_user_app_dir",
    "find_subdir",
    "copy_filtered",
    "write_manifest",
    "load_manifest",
    "scan_profiles",
    "create_profile",
    "delete_profile",
    "import_profile",
    "pack_profile",
    "export_profile",
    "validate_profile_compatibility",
    "apply_profile",
    "list_backups",
    "restore_backup",
    "get_profiles_for_dcc",
    "detect_dcc_from_context",
    "scan_filesystem_plugins",
    "update_profile_plugins",
    "validate_profile_plugins",
]

MANIFEST_FILENAME = "manifest.json"

EXCLUDE_DIRS = {"cache", "log", "tmp", "__pycache__"}
EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".log", ".bak"}

_dcc_config_cache: dict[str, dict] = {}
_read_temp_dirs: list[Path] = []


def _cleanup_read_dirs() -> None:
    """清理临时目录。在程序退出时自动调用。"""
    for temp_dir in _read_temp_dirs:
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        except Exception:
            pass
    _read_temp_dirs.clear()


atexit.register(_cleanup_read_dirs)


def current_platform_key() -> str:
    """获取当前平台标识符。

    Returns:
        平台标识符: "darwin" | "win32" | "linux"
    """
    system = platform.system()
    if system == "Darwin":
        return "darwin"
    elif system == "Windows":
        return "win32"
    return "linux"


def load_dcc_config(dcc_name: str) -> dict | None:
    """加载 DCC 配置。

    使用 Rez 包管理 API 从 packages/app/<dcc_name>/<version>/package.py 中读取 _profile 配置。
    优先使用 Rez API（安全、结构化），回退到受限 exec 解析。

    Args:
        dcc_name: DCC 名称，如 "maya"

    Returns:
        DCC 配置字典，未找到则返回 None
    """
    if dcc_name in _dcc_config_cache:
        return _dcc_config_cache[dcc_name]

    packages_dir = get_packages_dir()
    app_dir = packages_dir / "app" / dcc_name
    if not app_dir.exists():
        return None

    for version_dir in sorted(app_dir.iterdir(), reverse=True):
        pkg_file = version_dir / "package.py"
        if not pkg_file.exists():
            continue

        profile = _load_profile_via_rez(dcc_name, version_dir)
        if profile is None:
            profile = _load_profile_via_exec(pkg_file, version_dir)

        if profile:
            _dcc_config_cache[dcc_name] = profile
            return profile

    return None


def _load_profile_via_rez(dcc_name: str, version_dir: Path) -> dict | None:
    """使用 Rez API 加载 _profile 配置。

    Args:
        dcc_name: DCC 名称
        version_dir: 包版本目录路径

    Returns:
        _profile 配置字典，未找到则返回 None
    """
    try:
        from rez.package_repository import package_repository_manager

        repo = package_repository_manager.get_repository(str(version_dir.parent.parent))
        packages = repo.get_packages()
        for pkg in packages:
            if pkg.name == dcc_name:
                profile_data = getattr(pkg, "_profile", None)
                if profile_data and isinstance(profile_data, dict):
                    profile_data["_package_root"] = str(version_dir)
                    return profile_data
    except Exception:
        pass
    return None


def _load_profile_via_exec(pkg_file: Path, version_dir: Path) -> dict | None:
    """使用 AST 白名单解析 package.py 中的 _profile 配置。

    仅提取 _profile 字面量赋值，不执行任何代码。

    Args:
        pkg_file: package.py 文件路径
        version_dir: 包版本目录路径

    Returns:
        _profile 配置字典，未找到则返回 None
    """
    try:
        source = pkg_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_profile":
                    try:
                        profile = ast.literal_eval(node.value)
                    except Exception:
                        return None
                    if isinstance(profile, dict):
                        profile["_package_root"] = str(version_dir)
                        return profile
    return None


def get_version_subdir(dcc_name: str, dcc_version: str) -> str:
    """获取版本子目录名称。

    Args:
        dcc_name: DCC 名称
        dcc_version: DCC 版本

    Returns:
        版本子目录名称
    """
    config = load_dcc_config(dcc_name)
    if config:
        fmt = config.get("version_subdir_format", "{version}")
        return fmt.format(version=dcc_version)
    return dcc_version


def find_dcc_user_app_dir(dcc_name: str, dcc_version: str) -> Path | None:
    """查找 DCC 用户应用目录。

    Args:
        dcc_name: DCC 名称
        dcc_version: DCC 版本

    Returns:
        用户应用目录路径，未找到则返回 None
    """
    config = load_dcc_config(dcc_name)
    if not config:
        return None

    env_var = config.get("env_var")
    if env_var and env_var in os.environ:
        return Path(os.environ[env_var])

    user_app_dirs = config.get("user_app_dirs")
    if not user_app_dirs:
        return None

    plat = current_platform_key()
    raw_path = user_app_dirs.get(plat)
    if not raw_path:
        return None

    expanded = os.path.expanduser(raw_path)
    return Path(expanded)


def find_subdir(profile_dir: Path, version_subdir: str, subdir_name: str) -> Path | None:
    """在 Profile 目录中查找子目录。

    优先查找 version_subdir/subdir_name，如果不存在则查找 subdir_name。

    Args:
        profile_dir: Profile 目录路径
        version_subdir: 版本子目录名称
        subdir_name: 目标子目录名称

    Returns:
        子目录路径，未找到则返回 None
    """
    if version_subdir:
        candidate = profile_dir / version_subdir / subdir_name
        if candidate.exists():
            return candidate

    candidate = profile_dir / subdir_name
    if candidate.exists():
        return candidate

    return None


def copy_filtered(
    src: Path, dst: Path, extra_exclude_dirs: set[str] | None = None
) -> None:
    """复制目录内容，过滤排除的文件和目录。

    Args:
        src: 源目录
        dst: 目标目录
        extra_exclude_dirs: 额外排除的目录名集合（如 DCC 特有的 renderData）
    """
    exclude = EXCLUDE_DIRS | (extra_exclude_dirs or set())

    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        if item.name.startswith("."):
            continue
        if item.name == MANIFEST_FILENAME and dst != src:
            continue
        if item.is_dir():
            if item.name in exclude:
                continue
            copy_filtered(item, dst / item.name, extra_exclude_dirs)
        elif item.is_file():
            if item.suffix in EXCLUDE_EXTENSIONS:
                continue
            target = dst / item.name
            if item.resolve() == target.resolve():
                continue
            shutil.copy2(item, target)


def write_manifest(profile_dir: Path, manifest: dict) -> None:
    """写入 Profile 清单文件。

    Args:
        profile_dir: Profile 目录路径
        manifest: 清单数据字典
    """
    manifest_path = profile_dir / MANIFEST_FILENAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def load_manifest(profile_dir: Path) -> dict:
    """加载 Profile 清单文件。

    Args:
        profile_dir: Profile 目录路径

    Returns:
        清单数据字典

    Raises:
        KeyError: 如果缺少必需字段
        json.JSONDecodeError: 如果 JSON 解析失败
    """
    manifest_path = Path(profile_dir) / MANIFEST_FILENAME
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    required_fields = {"name", "dcc", "dcc_version"}
    missing = required_fields - set(data.keys())
    if missing:
        raise KeyError(f"Missing required fields: {missing}")

    return data


def scan_profiles() -> dict[str, dict]:
    """扫描所有 Profile。

    Returns:
        Profile 信息字典: {name: {"path": str, "manifest": dict}}
    """
    profiles_dir = get_profiles_dir()
    if not profiles_dir.exists():
        return {}

    profiles = {}
    for profile_dir in sorted(profiles_dir.iterdir()):
        if not profile_dir.is_dir():
            continue
        if profile_dir.name.startswith("."):
            continue
        manifest_path = profile_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            continue
        try:
            manifest = load_manifest(profile_dir)
            profiles[profile_dir.name] = {
                "path": str(profile_dir),
                "manifest": manifest,
            }
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[PROFILE] Warning: Invalid manifest in {profile_dir.name}: {e}")

    return profiles


def create_profile(
    name: str,
    dcc: str,
    dcc_version: str,
    description: str = "",
) -> Path:
    """创建新的 Profile。

    Args:
        name: Profile 名称
        dcc: DCC 名称
        dcc_version: DCC 版本
        description: Profile 描述

    Returns:
        Profile 目录路径

    Raises:
        FileExistsError: 如果 Profile 已存在
    """
    profiles_dir = get_profiles_dir()
    profile_dir = profiles_dir / name

    if profile_dir.exists():
        raise FileExistsError(f"Profile '{name}' already exists")

    profile_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "dcc": dcc,
        "dcc_version": dcc_version,
        "platform": platform.system().lower(),
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "description": description,
        "plugins": [],
    }

    write_manifest(profile_dir, manifest)
    return profile_dir


def delete_profile(name: str) -> None:
    """删除 Profile。

    Args:
        name: Profile 名称

    Raises:
        FileNotFoundError: 如果 Profile 不存在
    """
    profiles_dir = get_profiles_dir()
    profile_dir = profiles_dir / name

    if not profile_dir.exists():
        raise FileNotFoundError(f"Profile '{name}' not found")

    shutil.rmtree(profile_dir)


def import_profile(source: str | Path, name: str | None = None) -> Path:
    """导入 Profile。

    Args:
        source: 源路径（目录或 .tar.gz 归档）
        name: 重命名（可选，留空使用原名）

    Returns:
        Profile 目录路径

    Raises:
        ValueError: 如果源路径无效
    """
    source_path = Path(source)

    if source_path.is_file() and tarfile.is_tarfile(source_path):
        return _import_from_archive(source_path, name)

    if source_path.is_dir():
        return _import_from_directory(source_path, name)

    raise ValueError(f"Source must be a directory or a .tar.gz archive, got: {source_path}")


def _import_from_directory(source_dir: Path, name: str | None) -> Path:
    """从目录导入 Profile。

    Args:
        source_dir: 源目录路径
        name: 重命名（可选）

    Returns:
        Profile 目录路径
    """
    manifest_path = source_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"No {MANIFEST_FILENAME} found in {source_dir}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    profile_name = name or manifest.get("name") or source_dir.name
    profiles_dir = get_profiles_dir()
    profile_dir = profiles_dir / profile_name

    if profile_dir.exists():
        raise FileExistsError(f"Profile '{profile_name}' already exists")

    copy_filtered(source_dir, profile_dir)

    manifest["name"] = profile_name
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    write_manifest(profile_dir, manifest)

    return profile_dir


def _import_from_archive(archive_path: Path, name: str | None) -> Path:
    """从归档导入 Profile。

    Args:
        archive_path: 归档文件路径
        name: 重命名（可选）

    Returns:
        Profile 目录路径
    """
    extract_dir = Path(archive_path).parent / f".lift_import_{archive_path.stem}"

    try:
        with tarfile.open(archive_path, "r:*") as tar:
            _safe_extract(tar, extract_dir)

        root_dir = _find_archive_root(extract_dir)
        result = _import_from_directory(root_dir, name)
    finally:
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

    return result


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """安全解压 tar 归档，防止路径穿越攻击。

    Args:
        tar: TarFile 对象
        dest: 目标目录

    Raises:
        ValueError: 如果检测到路径穿越
    """
    dest.mkdir(parents=True, exist_ok=True)
    for member in tar.getmembers():
        member_path = dest / member.name
        try:
            member_path.resolve().relative_to(dest.resolve())
        except ValueError as err:
            raise ValueError(f"Archive member escapes target directory: {member.name}") from err
        tar.extract(member, dest, filter="data")


def _find_archive_root(extract_dir: Path) -> Path:
    """查找归档的根目录。

    如果归档包含单个目录且该目录包含 manifest.json，则返回该目录。

    Args:
        extract_dir: 解压目录

    Returns:
        根目录路径
    """
    children = [p for p in extract_dir.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        child_manifest = children[0] / MANIFEST_FILENAME
        if child_manifest.exists():
            return children[0]
    return extract_dir


def pack_profile(profile_name: str, output_path: str | Path | None = None) -> Path:
    """打包 Profile 为 tar.gz 归档。

    Args:
        profile_name: Profile 名称
        output_path: 输出路径（可选，默认在 profiles 目录）

    Returns:
        归档文件路径

    Raises:
        FileNotFoundError: 如果 Profile 不存在
    """
    profiles_dir = get_profiles_dir()
    profile_dir = profiles_dir / profile_name

    if not profile_dir.exists():
        raise FileNotFoundError(f"Profile '{profile_name}' not found")

    if output_path is None:
        output_path = profiles_dir / f"{profile_name}.tar.gz"
    output_path = Path(output_path)

    with tarfile.open(output_path, "w:gz") as tar:
        for item in sorted(profile_dir.rglob("*")):
            if item.name.startswith("."):
                continue
            if item.suffix in EXCLUDE_EXTENSIONS:
                continue
            tar.add(item, arcname=f"{profile_name}/{item.relative_to(profile_dir)}")

    return output_path


def export_profile(
    profile_name: str,
    dcc: str,
    dcc_version: str,
    description: str = "",
) -> Path:
    """从 DCC 用户目录导出 Profile。

    执行通用的目录复制和文件系统插件扫描。DCC 特有的运行时状态
    （如插件的 auto_load）由各 DCC hook 在调用本函数后自行处理。

    Args:
        profile_name: Profile 名称
        dcc: DCC 名称
        dcc_version: DCC 版本
        description: Profile 描述

    Returns:
        Profile 目录路径

    Raises:
        FileNotFoundError: 如果用户目录不存在
    """
    user_app_dir = find_dcc_user_app_dir(dcc, dcc_version)
    if not user_app_dir or not user_app_dir.exists():
        raise FileNotFoundError(
            f"{dcc} {dcc_version} user data not found. Expected at: {user_app_dir}"
        )

    profile_dir = create_profile(
        name=profile_name,
        dcc=dcc,
        dcc_version=dcc_version,
        description=description,
    )

    version_subdir = get_version_subdir(dcc, dcc_version)
    src_dir = user_app_dir / version_subdir

    config = load_dcc_config(dcc)
    extra_exclude = set(config.get("exclude_dirs", [])) if config else set()

    if src_dir.exists():
        dst_dir = profile_dir / version_subdir
        copy_filtered(src_dir, dst_dir, extra_exclude)
    else:
        copy_filtered(user_app_dir, profile_dir, extra_exclude)

    scan_filesystem_plugins(profile_dir, dcc, dcc_version)

    return profile_dir


def validate_profile_compatibility(manifest: dict, dcc: str, dcc_version: str) -> None:
    """验证 Profile 与当前环境的兼容性。

    Args:
        manifest: Profile 清单
        dcc: 目标 DCC 名称
        dcc_version: 目标 DCC 版本

    Raises:
        RuntimeError: 如果平台、DCC 或版本不匹配
    """
    current_plat = current_platform_key()
    profile_plat = manifest.get("platform", "")

    if profile_plat and profile_plat != current_plat:
        raise RuntimeError(
            f"Platform mismatch: profile was created on '{profile_plat}', "
            f"but current platform is '{current_plat}'"
        )

    manifest_dcc = manifest.get("dcc", "")
    manifest_version = manifest.get("dcc_version", "")

    if manifest_dcc and manifest_dcc != dcc:
        raise RuntimeError(
            f"DCC mismatch: profile for '{manifest_dcc}', but resolved context has '{dcc}'"
        )

    if manifest_version and manifest_version != dcc_version:
        raise RuntimeError(
            f"Version mismatch: profile for '{manifest_dcc} {manifest_version}', "
            f"but resolved context has '{dcc} {dcc_version}'"
        )


def apply_profile(
    profile_name: str,
    env: dict[str, str],
    mode: str = "read",
    dcc: str | None = None,
    dcc_version: str | None = None,
) -> dict[str, str]:
    """应用 Profile 到环境。

    Args:
        profile_name: Profile 名称
        env: 环境变量字典
        mode: 应用模式：
            - "read": 临时目录，只读，安全
            - "write": 直接指向 Profile 目录，可读写，有污染风险
            - "override": 覆盖用户目录，自动备份
        dcc: DCC 名称（可选，用于验证）
        dcc_version: DCC 版本（可选，用于验证）

    Returns:
        更新后的环境变量字典

    Raises:
        RuntimeError: 如果验证失败或无法确定用户目录
        ValueError: 如果 mode 参数无效
    """
    if mode not in ("read", "write", "override"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'read', 'write', or 'override'")

    profiles_dir = get_profiles_dir()
    profile_dir = profiles_dir / profile_name
    manifest = load_manifest(profile_dir)

    manifest_dcc = manifest.get("dcc", dcc)
    manifest_version = manifest.get("dcc_version", dcc_version)

    if dcc is not None and dcc_version is not None:
        validate_profile_compatibility(manifest, dcc, dcc_version)

    effective_dcc = dcc or manifest_dcc
    effective_version = dcc_version or manifest_version

    config = load_dcc_config(effective_dcc)

    if not config:
        return env

    env_var = config.get("env_var")
    if not env_var:
        return env

    if mode == "override":
        # 覆盖模式：备份并替换用户目录
        user_app_dir = find_dcc_user_app_dir(effective_dcc, effective_version)
        if not user_app_dir:
            raise RuntimeError(
                f"Cannot determine user app dir for {effective_dcc} {effective_version}"
            )

        _backup_user_app_dir(user_app_dir)
        extra_exclude = set(config.get("exclude_dirs", []))
        copy_filtered(profile_dir, user_app_dir, extra_exclude)
        return env

    if mode == "write":
        # 读写模式：直接指向 Profile 目录，可读写
        env[env_var] = str(profile_dir)
        return env

    # 只读模式：复制到临时目录，只读
    temp_dir = Path(tempfile.mkdtemp(prefix="lift_profile_"))
    _read_temp_dirs.append(temp_dir)
    extra_exclude = set(config.get("exclude_dirs", []))
    copy_filtered(profile_dir, temp_dir, extra_exclude)
    env[env_var] = str(temp_dir)
    return env


def _backup_user_app_dir(user_app_dir: Path) -> Path:
    """备份用户应用目录。

    如果同一秒内已有同名备份，添加递增后缀避免冲突。
    备份失败时抛出 RuntimeError，避免后续覆盖操作导致数据丢失。

    Args:
        user_app_dir: 用户应用目录路径

    Returns:
        备份目录路径

    Raises:
        RuntimeError: 如果备份失败
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    base_name = f"{user_app_dir.name}.backup.{timestamp}"
    backup_dir = user_app_dir.parent / base_name

    if backup_dir.exists():
        seq = 1
        while seq < 1000:
            backup_dir = user_app_dir.parent / f"{base_name}.{seq}"
            if not backup_dir.exists():
                break
            seq += 1
        else:
            raise RuntimeError(f"无法生成唯一备份目录名: {base_name}")

    try:
        shutil.copytree(user_app_dir, backup_dir)
    except Exception as exc:
        raise RuntimeError(f"备份失败: {exc}") from exc

    return backup_dir


def list_backups(dcc_name: str, dcc_version: str) -> list[Path]:
    """列出备份目录。

    Args:
        dcc_name: DCC 名称
        dcc_version: DCC 版本

    Returns:
        备份目录路径列表
    """
    user_app_dir = find_dcc_user_app_dir(dcc_name, dcc_version)
    if not user_app_dir:
        return []

    backups = sorted(
        p
        for p in user_app_dir.parent.iterdir()
        if p.is_dir() and p.name.startswith(f"{user_app_dir.name}.backup.")
    )
    return backups


def restore_backup(backup_dir: Path, dcc_name: str, dcc_version: str) -> None:
    """恢复备份。

    Args:
        backup_dir: 备份目录路径
        dcc_name: DCC 名称
        dcc_version: DCC 版本

    Raises:
        FileNotFoundError: 如果备份目录不存在或无法确定用户目录
    """
    user_app_dir = find_dcc_user_app_dir(dcc_name, dcc_version)
    if not user_app_dir:
        raise FileNotFoundError(f"Cannot determine user app dir for {dcc_name} {dcc_version}")

    if not backup_dir.exists():
        raise FileNotFoundError(f"Backup not found: {backup_dir}")

    if user_app_dir.exists():
        shutil.rmtree(user_app_dir)
    shutil.copytree(backup_dir, user_app_dir)


def get_profiles_for_dcc(dcc: str, dcc_version: str) -> dict[str, dict]:
    """获取指定 DCC 和版本的 Profile。

    Args:
        dcc: DCC 名称
        dcc_version: DCC 版本

    Returns:
        Profile 信息字典
    """
    all_profiles = scan_profiles()
    return {
        name: info
        for name, info in all_profiles.items()
        if info["manifest"].get("dcc") == dcc and info["manifest"].get("dcc_version") == dcc_version
    }


def detect_dcc_from_context(context) -> list[dict]:
    """从 Rez 解析上下文中检测 DCC。

    优先使用 load_dcc_config 检测（可靠），_category 属性作为辅助。

    Args:
        context: Rez 解析上下文

    Returns:
        DCC 信息列表
    """
    dcc_list = []
    for pkg in context.resolved_packages:
        pkg_name = pkg.name.lower()
        is_dcc = load_dcc_config(pkg_name) is not None or getattr(pkg, "_category", None) == "app"
        if is_dcc:
            dcc_list.append(
                {
                    "name": pkg_name,
                    "version": str(pkg.version),
                }
            )
    return dcc_list


def scan_filesystem_plugins(profile_dir: Path, dcc: str, dcc_version: str) -> None:
    """扫描文件系统插件并更新清单。

    从 DCC 配置中读取 plugin_dirs 列表，扫描所有配置的插件目录。
    已存在于 manifest 中的插件数据（如 version、auto_load）会被保留，
    新发现的插件使用默认值。

    Args:
        profile_dir: Profile 目录路径
        dcc: DCC 名称
        dcc_version: DCC 版本
    """
    manifest = load_manifest(profile_dir)
    existing = {p["name"]: p for p in manifest.get("plugins", [])}

    config = load_dcc_config(dcc)
    plugin_dirs = config.get("plugin_dirs", []) if config else []

    version_subdir = get_version_subdir(dcc, dcc_version)
    plugins = []
    seen: set[str] = set()

    for dir_name in plugin_dirs:
        plugins_dir = find_subdir(profile_dir, version_subdir, dir_name)
        if not plugins_dir:
            continue
        for item in sorted(plugins_dir.iterdir()):
            if item.name.startswith("."):
                continue
            name = item.stem if item.is_file() else item.name
            if name in seen:
                continue
            seen.add(name)
            if name in existing:
                plugins.append(existing[name])
            else:
                plugins.append(
                    {
                        "name": name,
                        "version": "",
                        "auto_load": True,
                    }
                )

    manifest["plugins"] = plugins
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    write_manifest(profile_dir, manifest)


def update_profile_plugins(profile_dir: Path, plugins: list[dict]) -> None:
    """更新 Profile 插件列表。

    Args:
        profile_dir: Profile 目录路径
        plugins: 插件信息列表
    """
    manifest = load_manifest(profile_dir)
    manifest["plugins"] = plugins
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    write_manifest(profile_dir, manifest)


def validate_profile_plugins(profile_name: str, dcc: str, dcc_version: str) -> list[str]:
    """校验 Profile manifest 中的插件列表与磁盘文件的一致性。

    检查 manifest 中记录的每个插件是否在 Profile 目录的插件目录中
    存在对应的文件。适用于导入或迁移 Profile 后的可用性检查。

    Args:
        profile_name: Profile 名称
        dcc: DCC 名称
        dcc_version: DCC 版本

    Returns:
        警告消息列表，为空表示全部插件均可用
    """
    profiles_dir = get_profiles_dir()
    profile_dir = profiles_dir / profile_name

    if not profile_dir.exists():
        return [f"Profile '{profile_name}' not found"]

    manifest = load_manifest(profile_dir)
    plugins = manifest.get("plugins", [])
    if not plugins:
        return []

    config = load_dcc_config(dcc)
    plugin_dirs = config.get("plugin_dirs", []) if config else []
    version_subdir = get_version_subdir(dcc, dcc_version)

    available: set[str] = set()
    for dir_name in plugin_dirs:
        plugins_dir = find_subdir(profile_dir, version_subdir, dir_name)
        if not plugins_dir:
            continue
        for item in plugins_dir.iterdir():
            if item.name.startswith("."):
                continue
            available.add(item.stem if item.is_file() else item.name)

    warnings = []
    for plugin in plugins:
        if plugin["name"] not in available:
            warnings.append(f"Plugin '{plugin['name']}' listed in manifest but not found on disk")

    return warnings
