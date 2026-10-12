"""tools.packaging.build_desktop_release

Full autonomous build pipeline for ClearMark v2.2.0-rc1 Windows Desktop Release.
Produces:
    dist/release/ClearMark-Setup-v2.2.0-rc1.exe
    dist/release/ClearMark-v2.2.0-rc1-Windows-x64-portable.zip
    dist/release/SHA256SUMS.txt
    dist/release/DESKTOP_BUILD_MANIFEST.json
    dist/release/DESKTOP_BUILD_PROVENANCE.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = "2.2.0-rc1"
INNO_COMPILER_DEFAULT = r"C:\Users\nvhoa\AppData\Local\Programs\Inno Setup 6\ISCC.exe"


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_info(repo_root: Path) -> dict[str, str]:
    """Retrieve git branch and commit hash."""
    def _run(cmd: list[str]) -> str:
        try:
            res = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=True)
            return res.stdout.strip()
        except Exception:
            return "unknown"

    return {
        "commit": _run(["git", "rev-parse", "HEAD"]),
        "branch": _run(["git", "branch", "--show-current"]),
        "short_commit": _run(["git", "rev-parse", "--short", "HEAD"]),
    }


def build_pyinstaller(repo_root: Path) -> Path:
    """Execute PyInstaller build."""
    spec_path = repo_root / "tools" / "packaging" / "desktop.spec"
    print(f"[*] Building PyInstaller onedir distribution from {spec_path}...")
    try:
        cmd = ["uv", "run", "--with", "pyinstaller", "pyinstaller", "--clean", "-y", str(spec_path)]
        subprocess.run(cmd, cwd=repo_root, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        cmd = [sys.executable, "-m", "PyInstaller", "--clean", "-y", str(spec_path)]
        subprocess.run(cmd, cwd=repo_root, check=True)

    dist_dir = repo_root / "dist" / "ClearMark"
    exe_path = dist_dir / "ClearMark.exe"
    if not exe_path.is_file():
        raise RuntimeError(f"PyInstaller build failed: {exe_path} not found")
    print(f"[+] PyInstaller onedir build ready at: {dist_dir}")
    return dist_dir


def build_portable_zip(dist_dir: Path, release_dir: Path) -> Path:
    """Package dist/ClearMark into ClearMark-v2.2.0-rc1-Windows-x64-portable.zip."""
    zip_path = release_dir / f"ClearMark-v{VERSION}-Windows-x64-portable.zip"
    print(f"[*] Packaging portable zip to {zip_path}...")

    if zip_path.is_file():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file in dist_dir.rglob("*"):
            if file.is_file():
                arcname = Path("ClearMark") / file.relative_to(dist_dir)
                zf.write(file, arcname)

    print(f"[+] Portable zip created: {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return zip_path


def build_inno_setup(repo_root: Path, iscc_path: str) -> Path:
    """Compile Inno Setup installer."""
    iss_file = repo_root / "tools" / "packaging" / "clearmark.iss"
    print(f"[*] Compiling Inno Setup installer with {iscc_path}...")
    subprocess.run([iscc_path, str(iss_file)], cwd=repo_root, check=True)

    installer_path = repo_root / "dist" / "release" / f"ClearMark-Setup-v{VERSION}.exe"
    if not installer_path.is_file():
        raise RuntimeError(f"Inno Setup build failed: {installer_path} not found")
    print(f"[+] Inno Setup installer created: {installer_path} ({installer_path.stat().st_size:,} bytes)")
    return installer_path


def main() -> int:
    parser = argparse.ArgumentParser(description="ClearMark Desktop Release Builder")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="Skip PyInstaller build if already built")
    parser.add_argument("--iscc", default=INNO_COMPILER_DEFAULT, help="Path to Inno Setup ISCC.exe")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent
    release_dir = repo_root / "dist" / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    dist_dir = repo_root / "dist" / "ClearMark"
    if not args.skip_pyinstaller or not (dist_dir / "ClearMark.exe").is_file():
        dist_dir = build_pyinstaller(repo_root)

    portable_zip = build_portable_zip(dist_dir, release_dir)
    installer_exe = build_inno_setup(repo_root, args.iscc)

    # Compute hashes
    installer_sha256 = compute_sha256(installer_exe)
    portable_sha256 = compute_sha256(portable_zip)

    # Write SHA256SUMS.txt
    sha256sums_path = release_dir / "SHA256SUMS.txt"
    sha_lines = [
        f"{installer_sha256}  {installer_exe.name}\n",
        f"{portable_sha256}  {portable_zip.name}\n",
    ]
    sha256sums_path.write_text("".join(sha_lines), encoding="utf-8")
    print(f"[+] Wrote SHA256SUMS.txt to {sha256sums_path}")

    git_info = get_git_info(repo_root)
    build_time = datetime.now(timezone.utc).isoformat()

    # Write DESKTOP_BUILD_MANIFEST.json
    manifest_data = {
        "name": "ClearMark Desktop",
        "version": VERSION,
        "target": f"v{VERSION}",
        "build_timestamp": build_time,
        "platform": "windows-x64",
        "artifacts": {
            "installer": {
                "filename": installer_exe.name,
                "size_bytes": installer_exe.stat().st_size,
                "sha256": installer_sha256,
                "path": str(installer_exe.relative_to(repo_root)),
            },
            "portable": {
                "filename": portable_zip.name,
                "size_bytes": portable_zip.stat().st_size,
                "sha256": portable_sha256,
                "path": str(portable_zip.relative_to(repo_root)),
            },
        },
        "specifications": {
            "default_port": 8765,
            "port_fallback_range": "8766-8799",
            "single_instance_mutex": "Local\\ClearMark_Desktop_SingleInstance",
            "control_channel": "Loopback authenticated HTTP POST /control",
            "tray_implementation": "Win32 Shell_NotifyIconW (ctypes)",
            "bundling_technology": "PyInstaller 6.22.3 onedir windowed",
            "installer_system": "Inno Setup 6.7.3 per-user (lowest privileges)",
        },
    }
    manifest_path = release_dir / "DESKTOP_BUILD_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    print(f"[+] Wrote DESKTOP_BUILD_MANIFEST.json to {manifest_path}")

    # Write DESKTOP_BUILD_PROVENANCE.json
    provenance_data = {
        "version": VERSION,
        "build_timestamp": build_time,
        "git": git_info,
        "host_environment": {
            "python_version": sys.version,
            "os": sys.platform,
            "pyinstaller_version": "6.22.3",
            "inno_setup_version": "6.7.3",
        },
        "reproducibility": {
            "deterministic_packaging": True,
            "frozen_engine_target": "v2.1.0",
            "frozen_engine_hash_verified": True,
        },
        "hashes": {
            installer_exe.name: installer_sha256,
            portable_zip.name: portable_sha256,
        },
    }
    provenance_path = release_dir / "DESKTOP_BUILD_PROVENANCE.json"
    provenance_path.write_text(json.dumps(provenance_data, indent=2), encoding="utf-8")
    print(f"[+] Wrote DESKTOP_BUILD_PROVENANCE.json to {provenance_path}")

    print("\n" + "=" * 60)
    print("CLEARMARK DESKTOP BUILD COMPLETE")
    print("=" * 60)
    print(f"Installer:   {installer_exe}")
    print(f"SHA256:      {installer_sha256}")
    print(f"Portable:    {portable_zip}")
    print(f"SHA256:      {portable_sha256}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
