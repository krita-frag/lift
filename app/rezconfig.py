import os
from pathlib import Path


def get_packages_root() -> Path:
    if env_dir := os.environ.get("LIFT_PACKAGES_DIR"):
        return Path(env_dir)
    return Path(__file__).parent.parent.parent / "packages"


_packages_root = get_packages_root()

packages_path = [
    str(_packages_root / "app"),
    str(_packages_root / "ext"),
    str(_packages_root / "int"),
    str(_packages_root / "proj"),
]

local_packages_path = str(_packages_root)
