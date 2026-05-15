from pathlib import Path

from app.profile import (
    export_profile,
    load_manifest,
    update_profile_plugins,
)


def _detect_maya_version() -> str | None:
    try:
        import maya.cmds as cmds
        version_str = cmds.about(version=True)
        return version_str[:4]
    except Exception:
        return None


def _scan_maya_plugins() -> list[dict]:
    plugins = []
    try:
        import maya.cmds as cmds
        loaded = cmds.pluginInfo(query=True, listPlugins=True) or []
        for name in loaded:
            try:
                plugins.append({
                    "name": name,
                    "version": cmds.pluginInfo(name, query=True, version=True) or "",
                    "auto_load": bool(cmds.pluginInfo(name, query=True, autoload=True)),
                })
            except Exception:
                plugins.append({"name": name, "version": "", "auto_load": False})
    except Exception:
        pass
    return plugins


def _merge_runtime_plugins(profile_dir: Path, runtime_plugins: list[dict]) -> None:
    """合并运行时插件状态与文件系统扫描结果。

    export_profile 已完成文件系统插件扫描（auto_load 默认 True），
    此函数用运行时状态覆盖，确保 auto_load 准确反映 Maya 当前设置。

    合并策略：
    - 文件系统中存在 + 运行时报告 → 使用运行时状态（准确的 auto_load）
    - 文件系统中存在 + 运行时未报告 → auto_load=False（已卸载/未注册）
    - 运行时报告 + 文件系统无对应文件 → 保留（内置插件等）
    """
    manifest = load_manifest(profile_dir)
    fs_plugins = manifest.get("plugins", [])
    runtime_map = {p["name"]: p for p in runtime_plugins}
    fs_names = {p["name"] for p in fs_plugins}

    merged: list[dict] = []

    for plugin in fs_plugins:
        name = plugin["name"]
        if name in runtime_map:
            merged.append(runtime_map[name])
        else:
            merged.append({
                "name": name,
                "version": plugin.get("version", ""),
                "auto_load": False,
            })

    for plugin in runtime_plugins:
        if plugin["name"] not in fs_names:
            merged.append(plugin)

    update_profile_plugins(profile_dir, merged)


def export_maya_profile(
    profile_name: str,
    description: str = "",
) -> Path:
    maya_version = _detect_maya_version()
    if not maya_version:
        raise RuntimeError("Cannot detect Maya version. Run this inside Maya.")

    profile_dir = export_profile(
        profile_name=profile_name,
        dcc="maya",
        dcc_version=maya_version,
        description=description,
    )

    runtime_plugins = _scan_maya_plugins()
    if runtime_plugins:
        _merge_runtime_plugins(profile_dir, runtime_plugins)

    return profile_dir
