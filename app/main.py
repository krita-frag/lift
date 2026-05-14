#!/usr/bin/env python3
"""Lift DCC 启动器入口模块。

负责初始化 Rez 环境并启动 GUI 应用程序。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def setup_rez() -> None:
    """初始化 Rez 环境。

    设置 REZ_CONFIG_FILE 环境变量，并确保 rez 可执行文件在 PATH 中。
    """
    base_dir = Path(__file__).parent.resolve()

    # 设置 Rez 配置文件路径
    rez_config = base_dir / "rezconfig.py"
    if rez_config.exists():
        os.environ["REZ_CONFIG_FILE"] = str(rez_config)

    # 确保 rez 在路径中
    for site_pkg in sys.path:
        if "site-packages" in site_pkg:
            rez_bin = Path(site_pkg).parent / "bin"
            if rez_bin.exists():
                os.environ["PATH"] = str(rez_bin) + os.pathsep + os.environ.get("PATH", "")
                break


def main() -> int:
    """DCC 启动器入口。

    Returns:
        程序退出码，0 表示成功
    """
    print("[LIFT] DCC Launcher starting...")
    print(f"[LIFT] Python {sys.version}")

    setup_rez()

    from app.gui import LiftLauncher

    app = LiftLauncher()
    app.mainloop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
