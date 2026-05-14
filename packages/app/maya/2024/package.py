name = "maya"
version = "2024"

requires = [
    "python-3.11",
]

tools = ["maya", "mayapy", "render", "mayabatch"]

_category = "app"
_data = {
    "label": "Autodesk Maya 2024",
    "color": "#1E5DB5",
}
_profile = {
    "user_app_dirs": {
        "darwin": "~/Library/Preferences/Autodesk/maya",
        "linux": "~/maya",
        "win32": "~/Documents/maya",
    },
    "env_var": "MAYA_APP_DIR",
    "version_subdir_format": "{version}",
}



def commands():
    import os
    import sys
    global env

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

    if "MAYA_LOCATION" in os.environ:
        maya_location = os.environ["MAYA_LOCATION"]

    if not maya_location:
        raise RuntimeError(
            f"Maya 2024 not found.\n"
            f"Searched: {locations}\n"
            f"Set MAYA_LOCATION to override."
        )

    env.MAYA_LOCATION.set(maya_location)
    env.PATH.prepend(f"{maya_location}/bin")

    if platform == "win32":
        env.PYTHONPATH.prepend(f"{maya_location}/Python/Lib/site-packages")
    else:
        env.PYTHONPATH.prepend(f"{maya_location}/lib/python3.11/site-packages")

    env.MAYA_PLUG_IN_PATH.prepend(f"{maya_location}/plug-ins")
    env.MAYA_SCRIPT_PATH.prepend(f"{maya_location}/scripts")
    env.MAYA_MODULE_PATH.prepend(f"{maya_location}/modules")

    if platform == "darwin":
        env.DYLD_LIBRARY_PATH.prepend(f"{maya_location}/lib")
    elif platform == "linux":
        env.LD_LIBRARY_PATH.prepend(f"{maya_location}/lib")

    env.MAYA_DISABLE_CIP.set("1")
    env.MAYA_DISABLE_CER.set("1")
