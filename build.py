#!/usr/bin/env python3

import hashlib
import os
import sys
import shutil
import subprocess
import platform
import urllib.request
import zipfile
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
ZIG_OUT_DIR = PROJECT_ROOT / "zig-out"

# Windows embeddable Python versions
PYTHON_VERSIONS = {
    "3.8": "3.8.19", "3.9": "3.9.19", "3.10": "3.10.14",
    "3.11": "3.11.9", "3.12": "3.12.4", "3.13": "3.13.0",
}

def get_project_version() -> str:
    """Parse project version from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.MULTILINE)
        if match:
            return match.group(1)
    return "0.1.0"


def get_python_version() -> str:
    """Parse Python version from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        match = re.search(r'requires-python\s*=\s*["\'](>=?)?(\d+\.\d+)', pyproject.read_text())
        if match:
            return match.group(2)
    return "3.11"


def get_windows_python_url(version: str) -> tuple[str, str]:
    """Get Windows embeddable Python URL. Falls back to 3.12 if unavailable."""
    major_minor = re.match(r'(\d+\.\d+)', version)
    ver = major_minor.group(1) if major_minor else "3.11"
    if ver not in PYTHON_VERSIONS:
        print(f"[BUILD] WARNING: Python {ver} not available, using 3.12")
        ver = "3.12"
    full = PYTHON_VERSIONS[ver]
    return full, f"https://www.python.org/ftp/python/{full}/python-{full}-embed-amd64.zip"


PY_VER = get_python_version()
WIN_PY_VER, WIN_PY_URL = get_windows_python_url(PY_VER)
PROJECT_VERSION = get_project_version()


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"[BUILD] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0 and check:
        print(f"[BUILD] ERROR: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result


def clean() -> None:
    """Remove dist directory."""
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
        print(f"[BUILD] Cleaned {DIST_DIR}")


def build_zig() -> None:
    """Build Zig binary."""
    run(["zig", "build", "--prefix", str(ZIG_OUT_DIR)])


def get_system_python() -> Path:
    """Find system Python."""
    for cmd in ["python3", "python"]:
        result = subprocess.run(["which", cmd], capture_output=True, text=True)
        if result.returncode == 0:
            return Path(result.stdout.strip())
    print("[BUILD] ERROR: Python not found", file=sys.stderr)
    sys.exit(1)


def install_dependencies() -> Path:
    """使用 uv 安装依赖到 dist/lib/python3/site-packages/。"""
    python3_dir = DIST_DIR / "lib" / "python3"
    site_packages = python3_dir / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        bin_dir = python3_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

        zip_path = PROJECT_ROOT / f"python-{WIN_PY_VER}-embed-amd64.zip"
        if not zip_path.exists():
            print(f"[BUILD] Downloading Python {WIN_PY_VER}")
            urllib.request.urlretrieve(WIN_PY_URL, zip_path)

        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(bin_dir)

        python_exe = bin_dir / "python.exe"
    else:
        python_exe = get_system_python()

    # 安装 pyproject.toml 中声明的所有依赖（不包含当前项目）
    run([
        "uv", "pip", "install",
        "--python", str(python_exe),
        "--target", str(site_packages),
        "--requirement", str(PROJECT_ROOT / "pyproject.toml"),
    ])

    return site_packages


def install_app() -> None:
    """安装 app 包到 dist/lib/app/。

    直接复制 app/ 目录，比 wheel 更可靠。
    """
    src_dir = PROJECT_ROOT / "app"
    dst_dir = DIST_DIR / "lib" / "app"

    if not src_dir.exists():
        print(f"[BUILD] ERROR: {src_dir} not found", file=sys.stderr)
        sys.exit(1)

    # 复制 app 目录，过滤 pyc 和 __pycache__
    def ignore_pyc(dir: str, names: list[str]) -> set[str]:
        return {
            name for name in names
            if name == "__pycache__" or name.endswith(".pyc")
        }

    shutil.copytree(src_dir, dst_dir, ignore=ignore_pyc)
    print(f"[BUILD] App copied to: {dst_dir}")


def copy_binary() -> None:
    """Copy Zig binary to dist/bin/."""
    src_dir = ZIG_OUT_DIR / "bin"
    dst_dir = DIST_DIR / "bin"

    if not src_dir.exists():
        print(f"[BUILD] ERROR: {src_dir} not found. Run 'zig build' first.", file=sys.stderr)
        sys.exit(1)

    shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir)

def copy_packages() -> None:
    """Copy packages to dist/packages/."""
    packages_dir = PROJECT_ROOT / "packages"
    dst_dir = DIST_DIR / "packages"

    shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(packages_dir, dst_dir)


def verify() -> bool:
    """Verify distribution structure."""
    is_win = platform.system() == "Windows"
    required = [
        DIST_DIR / "bin" / ("lift.exe" if is_win else "lift"),
        DIST_DIR / "lib" / "app" / "__init__.py",
        DIST_DIR / "lib" / "app" / "main.py",
    ]

    ok = all(p.exists() for p in required)
    for p in required:
        print(f"[BUILD] {'OK' if p.exists() else 'MISSING'}: {p}")

    return ok


def build(skip_zig: bool = False) -> None:
    """Main build."""
    print("=" * 60)
    print(f"[BUILD] Lift Build (Python {PY_VER})")
    print("=" * 60)

    clean()
    if not skip_zig:
        build_zig()

    install_dependencies()
    install_app()
    copy_binary()
    copy_packages()

    if verify():
        print("=" * 60)
        print(f"[BUILD] SUCCESS: {DIST_DIR}")
        print("=" * 60)
    else:
        print("[BUILD] FAILED", file=sys.stderr)
        sys.exit(1)


def package_dist() -> Path:
    """将 dist 目录打包为平台特定的安装包。

    根据当前平台选择打包格式：
    - Linux: tar.gz
    - macOS: tar.gz
    - Windows: zip

    文件名格式: lift-<version>-<platform>-<arch>.<ext>
    """
    import tarfile

    version = PROJECT_VERSION
    system = platform.system().lower()
    machine = platform.machine().lower()

    # 统一平台名称
    plat_name = {"darwin": "macos"}.get(system, system)
    # 统一架构名称
    arch_name = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)

    if plat_name == "windows":
        ext = "zip"
        filename = f"lift-{version}-windows-{arch_name}.{ext}"
        output = PROJECT_ROOT / filename

        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in DIST_DIR.rglob("*"):
                if file.is_file():
                    arcname = file.relative_to(DIST_DIR)
                    zf.write(file, arcname)
    else:
        ext = "tar.gz"
        filename = f"lift-{version}-{plat_name}-{arch_name}.{ext}"
        output = PROJECT_ROOT / filename

        with tarfile.open(output, "w:gz") as tf:
            tf.add(DIST_DIR, arcname="lift")

    print(f"[BUILD] Packaged: {output}")
    print(f"[BUILD] Size: {output.stat().st_size / 1024 / 1024:.1f} MB")
    return output


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-zig", action="store_true", help="Skip Zig build")
    parser.add_argument("--clean", action="store_true", help="Clean and exit")
    parser.add_argument("--package", action="store_true", help="Package dist into archive after build")
    parser.add_argument("--package-only", action="store_true", help="Only package existing dist")
    args = parser.parse_args()

    if args.clean:
        clean()
        if ZIG_OUT_DIR.exists():
            shutil.rmtree(ZIG_OUT_DIR)
        return 0

    if args.package_only:
        if not DIST_DIR.exists():
            print("[BUILD] ERROR: dist/ not found. Run build first.", file=sys.stderr)
            return 1
        package_dist()
        return 0

    build(skip_zig=args.skip_zig)

    if args.package:
        package_dist()

    return 0


if __name__ == "__main__":
    sys.exit(main())
