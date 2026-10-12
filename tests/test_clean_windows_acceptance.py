"""tests.test_clean_windows_acceptance

Clean Windows Acceptance Test for ClearMark v2.2.0-rc1.
Verifies execution in an environment where:
- Python is NOT on PATH (scrubbed minimal Windows PATH: System32 and Windows only)
- Project source tree is NOT present (isolated scratch directory)
- Developer virtualenv is NOT present
- Only built application package is present

Target: Section 21 Clean Windows Acceptance
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path


def test_clean_windows_acceptance(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    portable_zip = repo_root / "dist" / "release" / "ClearMark-v2.2.0-rc1-Windows-x64-portable.zip"
    assert portable_zip.is_file(), f"Portable zip not found at {portable_zip}"

    clean_root = tmp_path / "clean_env"
    clean_root.mkdir(parents=True, exist_ok=True)
    extract_dir = clean_root / "extracted"

    # 1. Extract portable package into isolated location
    with zipfile.ZipFile(portable_zip, "r") as zf:
        zf.extractall(extract_dir)

    app_dir = extract_dir / "ClearMark"
    exe_path = app_dir / "ClearMark.exe"
    assert exe_path.is_file(), f"ClearMark.exe not found in {app_dir}"

    # 2. Prepare scrubbed environment (no Python on PATH, isolated LOCALAPPDATA)
    clean_appdata = clean_root / "AppData" / "Local"
    clean_appdata.mkdir(parents=True, exist_ok=True)

    scrubbed_env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
        "PATH": r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem",
        "LOCALAPPDATA": str(clean_appdata),
        "TEMP": str(clean_root / "temp"),
        "TMP": str(clean_root / "temp"),
    }
    Path(scrubbed_env["TEMP"]).mkdir(parents=True, exist_ok=True)

    # Verify python is NOT on PATH in this environment
    res_py = subprocess.run(
        ["where", "python"],
        env=scrubbed_env,
        capture_output=True,
        text=True,
    )
    assert res_py.returncode != 0, "Python was unexpectedly found on scrubbed PATH"

    # 3. Launch ClearMark.exe from isolated directory
    proc = subprocess.Popen(
        [str(exe_path), "--no-browser", "--no-tray"],
        cwd=str(app_dir),
        env=scrubbed_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait up to 10 seconds for state file
        state_file = clean_appdata / "ClearMark" / "state" / "clearmark_state.json"
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if state_file.is_file():
                break
            time.sleep(0.2)

        assert state_file.is_file(), "ClearMark failed to start and write state file in clean environment"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        port = state["port"]
        pid = state["pid"]
        assert state["status"] == "RUNNING"

        # 4. Verify /health
        health_url = f"http://127.0.0.1:{port}/health"
        req = urllib.request.Request(health_url)
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("ok") is True

        # 5. Verify UI (/) returns HTML
        ui_url = f"http://127.0.0.1:{port}/"
        req_ui = urllib.request.Request(ui_url)
        with urllib.request.urlopen(req_ui, timeout=3.0) as resp_ui:
            assert resp_ui.status == 200
            html = resp_ui.read().decode("utf-8")
            assert "<!DOCTYPE html>" in html or "<html" in html

        # 6. Inspect representative file via POST /inspect
        test_content = b"Confidential document. Draft copy."
        inspect_body = json.dumps({
            "file": base64.b64encode(test_content).decode("ascii"),
            "name": "sample.txt",
        }).encode("utf-8")
        req_inspect = urllib.request.Request(
            f"http://127.0.0.1:{port}/inspect",
            data=inspect_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_inspect, timeout=5.0) as resp_insp:
            assert resp_insp.status == 200
            insp_data = json.loads(resp_insp.read().decode("utf-8"))
            assert insp_data.get("ok") is True

        # 7. Clean representative file via POST /clean
        clean_body = json.dumps({
            "file": base64.b64encode(test_content).decode("ascii"),
            "name": "sample.txt",
            "options": {},
        }).encode("utf-8")
        req_clean = urllib.request.Request(
            f"http://127.0.0.1:{port}/clean",
            data=clean_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_clean, timeout=5.0) as resp_cln:
            assert resp_cln.status == 200
            cln_data = json.loads(resp_cln.read().decode("utf-8"))
            assert cln_data.get("ok") is True
            assert "cleaned" in cln_data

        # 8. Query status using ClearMark.exe --status in scrubbed env
        res_status = subprocess.run(
            [str(exe_path), "--status"],
            cwd=str(app_dir),
            env=scrubbed_env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert res_status.returncode == 0
        status_info = json.loads(res_status.stdout)
        assert status_info.get("status") == "RUNNING"

        # 9. Stop server using ClearMark.exe --stop in scrubbed env
        res_stop = subprocess.run(
            [str(exe_path), "--stop"],
            cwd=str(app_dir),
            env=scrubbed_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert res_stop.returncode == 0
        assert "stopped cleanly" in res_stop.stdout

        # Verify host process terminated
        proc.wait(timeout=5.0)
        assert not state_file.is_file()

        # 10. Verify second launch cycle
        proc2 = subprocess.Popen(
            [str(exe_path), "--no-browser", "--no-tray"],
            cwd=str(app_dir),
            env=scrubbed_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if state_file.is_file():
                    break
                time.sleep(0.2)
            assert state_file.is_file()

            # Stop again via --stop
            res_stop2 = subprocess.run(
                [str(exe_path), "--stop"],
                cwd=str(app_dir),
                env=scrubbed_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert res_stop2.returncode == 0
            proc2.wait(timeout=5.0)
            assert not state_file.is_file()

        finally:
            if proc2.poll() is None:
                proc2.kill()
                proc2.wait()

    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
