name = "lift_profile"
version = "1.0.0"

requires = []

tools = ["lift_export"]

_category = "ext"
_data = {
    "label": "Lift Profile Export",
    "color": "#6C757D",
}


def commands():
    global env

    env.PYTHONPATH.prepend("{root}/hooks")
