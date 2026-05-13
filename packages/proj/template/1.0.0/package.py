name = "project_a"
version = "1.0.0"

requires = [
    "maya-2024",
]

# 项目特定的工具入口
tools = ["maya_project_a"]

_category = "proj"
_data = {
    "label": "Project A (Maya 2024)",
    "color": "#28A745",
}


def commands():
    import os
    import sys
    import tempfile
    global env
    global alias

    # Maya 安装路径发现（各平台默认位置）
    _maya_locations = {
        "darwin": [
            "/Applications/Autodesk/maya2024/Maya.app/Contents",
            "/Applications/Autodesk/maya2024",
        ],
        "linux": [
            "/usr/autodesk/maya2024",
            "/opt/autodesk/maya2024",
        ],
        "win32": [
            "C:/Program Files/Autodesk/Maya2024",
        ],
    }

    platform = sys.platform
    locations = _maya_locations.get(platform, [])

    maya_location = None
    for loc in locations:
        if os.path.exists(loc):
            maya_location = loc
            break

    # 允许通过环境变量覆盖
    if "MAYA_LOCATION" in os.environ:
        maya_location = os.environ["MAYA_LOCATION"]

    if not maya_location:
        raise RuntimeError(
            f"Maya 2024 not found.\n"
            f"Searched: {locations}\n"
            f"Set MAYA_LOCATION to override."
        )

    # 设置 Maya 环境
    env.MAYA_LOCATION.set(maya_location)
    env.PATH.prepend(f"{maya_location}/bin")

    if platform == "win32":
        env.PYTHONPATH.prepend(f"{maya_location}/Python/Lib/site-packages")
    else:
        env.PYTHONPATH.prepend(f"{maya_location}/lib/python3.11/site-packages")

    env.MAYA_PLUG_IN_PATH.prepend(f"{maya_location}/plug-ins")
    env.MAYA_SCRIPT_PATH.prepend(f"{maya_location}/scripts")
    env.MAYA_MODULE_PATH.prepend(f"{maya_location}/modules")

    # 项目特定的 Maya 用户目录
    maya_app_dir = tempfile.mkdtemp(prefix="maya_app_dir_")
    env.MAYA_APP_DIR.set(maya_app_dir)

    if platform == "darwin":
        env.DYLD_LIBRARY_PATH.prepend(f"{maya_location}/lib")
    elif platform == "linux":
        env.LD_LIBRARY_PATH.prepend(f"{maya_location}/lib")

    # 禁用 Autodesk 数据收集
    env.MAYA_DISABLE_CIP.set("1")
    env.MAYA_DISABLE_CER.set("1")

    # 项目特定的工具别名
    alias("maya_project_template", "maya")
