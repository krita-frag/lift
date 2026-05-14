from pathlib import Path
from app.profile import (
    copy_filtered,
    create_profile,
    find_dcc_user_app_dir,
    get_version_subdir,
    update_profile_plugins,
)


def _detect_maya_version() -> str | None:
    try:
        import maya.cmds as cmds
        version_str = cmds.about(version=True)
        return version_str[:4]
    except Exception:
        return None


def _get_maya_user_app_dir() -> Path | None:
    try:
        import maya.cmds as cmds
        app_dir = cmds.about(userAppDir=True)
        return Path(app_dir)
    except Exception:
        maya_version = _detect_maya_version() or "2024"
        return find_dcc_user_app_dir("maya", maya_version)


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


def export_maya_profile(
    profile_name: str,
    description: str = "",
) -> Path:
    maya_version = _detect_maya_version()
    if not maya_version:
        raise RuntimeError("Cannot detect Maya version. Run this inside Maya.")

    user_app_dir = _get_maya_user_app_dir()
    if not user_app_dir or not user_app_dir.exists():
        raise FileNotFoundError(f"Maya user app dir not found: {user_app_dir}")

    profile_dir = create_profile(
        name=profile_name,
        dcc="maya",
        dcc_version=maya_version,
        description=description,
    )

    version_subdir = get_version_subdir("maya", maya_version)
    version_dir = user_app_dir / version_subdir

    if version_dir.exists():
        copy_filtered(version_dir, profile_dir / version_subdir)
    else:
        copy_filtered(user_app_dir, profile_dir)

    plugins = _scan_maya_plugins()
    update_profile_plugins(profile_dir, plugins)

    return profile_dir
