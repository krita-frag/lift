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
    "icons": {
        "32x32": "{root}/resources/icon_32x32.png",
        "64x64": "{root}/resources/icon_64x64.png",
    },
}


def commands():
    global env
    env.PATH.prepend("{root}/bin")
