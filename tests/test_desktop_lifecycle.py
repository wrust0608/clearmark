"""tests.test_desktop_lifecycle

Automated acceptance tests for ClearMark Windows Desktop Host lifecycle,
single-instance mutex, local control channel, system tray, port fallback,
stale-state recovery, and process cleanup.

Targets: Section 20 Desktop Acceptance Tests for v2.2.0-rc1
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from service.desktop import DESKTOP_VERSION
from service.desktop.desktop_host import (
    DesktopHost,
    cmd_restart,
    cmd_status,
    cmd_stop,
    find_available_port,
    get_appdata_dir,
    get_log_file,
    get_state_file,
    is_port_available,
    is_process_running,
    send_control_command,
    signal_existing_instance_to_open,
)
from service.desktop.system_tray import SystemTrayIcon


@pytest.fixture
def sandbox_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox LOCALAPPDATA to an isolated temporary directory."""
    appdata = tmp_path / "AppData" / "Local"
    appdata.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    return appdata


def test_desktop_version() -> None:
    """Verify desktop subsystem version matches RC1 target."""
    assert DESKTOP_VERSION == "2.2.0-rc1"


def test_sandbox_paths(sandbox_appdata: Path) -> None:
    """Verify runtime paths are created inside sandboxed %LOCALAPPDATA%\\ClearMark."""
    root = get_appdata_dir()
    state_file = get_state_file()
    log_file = get_log_file()

    assert str(root).startswith(str(sandbox_appdata))
    assert state_file.parent.name == "state"
    assert log_file.parent.name == "logs"


def test_fresh_start_and_health_readiness(sandbox_appdata: Path) -> None:
    """Test fresh start, health readiness, runtime state persistence, and clean shutdown."""
    host = DesktopHost(
        port=None,
        no_browser=True,
        no_tray=True,
        mutex_name=f"Local\\ClearMark_Test_Mutex_{int(time.time())}_1",
    )

    # 1. Acquire mutex
    assert host.acquire_single_instance() is True

    try:
        # 2. Start control channel & HTTP server
        host.start_control_channel()
        host.start_http_server()

        # 3. Wait for health readiness
        assert host.wait_for_health(timeout_seconds=5.0) is True
        host.status = "RUNNING"
        host.write_runtime_state()

        # 4. Direct HTTP check to /health
        url = f"http://127.0.0.1:{host.actual_port}/health"
        req = urllib.request.Request(url, headers={"User-Agent": "TestClient"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("ok") is True
            assert "version" in data

        # 5. Verify runtime state file contents
        state_file = get_state_file()
        assert state_file.is_file()
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        assert state_data["pid"] == os.getpid()
        assert state_data["port"] == host.actual_port
        assert state_data["control_port"] == host._control_port
        assert state_data["version"] == "2.2.0-rc1"
        assert state_data["status"] == "RUNNING"

        # 6. Verify logging
        log_file = get_log_file()
        assert log_file.is_file()
        log_text = log_file.read_text(encoding="utf-8")
        assert f"Binding ClearMark server to 127.0.0.1:{host.actual_port}" in log_text

    finally:
        # 7. Graceful shutdown
        host.request_stop()

    # 8. Verify post-shutdown cleanup
    assert not get_state_file().is_file()
    assert is_port_available(host.actual_port) is True


def test_single_instance_and_second_launch_behavior(sandbox_appdata: Path) -> None:
    """Test Windows single-instance mutex and second-launch handoff."""
    test_mutex = f"Local\\ClearMark_Test_Mutex_{int(time.time())}_2"
    browser_opened = threading.Event()

    host1 = DesktopHost(
        no_browser=True,
        no_tray=True,
        mutex_name=test_mutex,
    )
    # Mock open_browser to verify signal reception
    host1.open_browser = lambda: browser_opened.set()  # type: ignore[assignment]

    assert host1.acquire_single_instance() is True
    host1.start_control_channel()
    host1.start_http_server()
    assert host1.wait_for_health(timeout_seconds=5.0) is True
    host1.status = "RUNNING"
    host1.write_runtime_state()

    try:
        # Second instance attempts to start with the same mutex
        host2 = DesktopHost(
            no_browser=True,
            no_tray=True,
            mutex_name=test_mutex,
        )

        # host2.acquire_single_instance() MUST fail because host1 holds it
        assert host2.acquire_single_instance() is False

        # host2.run() detects running instance, signals OPEN, and returns 0 immediately
        exit_code = host2.run()
        assert exit_code == 0

        # Verify host1 received the OPEN signal
        assert browser_opened.wait(timeout=3.0) is True

    finally:
        host1.request_stop()


def test_control_channel_commands(sandbox_appdata: Path, capsys: pytest.CaptureFixture) -> None:
    """Test authenticated control channel actions: STATUS, RESTART, STOP."""
    test_mutex = f"Local\\ClearMark_Test_Mutex_{int(time.time())}_3"
    host = DesktopHost(
        no_browser=True,
        no_tray=True,
        mutex_name=test_mutex,
    )
    assert host.acquire_single_instance() is True
    host.start_control_channel()
    host.start_http_server()
    assert host.wait_for_health(timeout_seconds=5.0) is True
    host.status = "RUNNING"
    host.write_runtime_state()

    try:
        # 1. STATUS command via direct IPC
        res_status = send_control_command("STATUS")
        assert res_status.get("ok") is True
        assert res_status.get("status") == "RUNNING"
        assert res_status.get("port") == host.actual_port

        # 2. STATUS command via CLI helper
        status_code = cmd_status()
        assert status_code == 0
        captured = capsys.readouterr()
        assert '"status": "RUNNING"' in captured.out

        # 3. RESTART command
        res_restart = send_control_command("RESTART")
        assert res_restart.get("ok") is True
        # Allow async restart thread to complete
        time.sleep(1.0)
        assert host.wait_for_health(timeout_seconds=5.0) is True

        # 4. STOP command via direct IPC
        res_stop = send_control_command("STOP")
        assert res_stop.get("ok") is True
        assert res_stop.get("action") == "STOP"

    finally:
        host.request_stop()


def test_cli_subprocess_lifecycle(sandbox_appdata: Path) -> None:
    """Test full external subprocess lifecycle with --status and --stop commands."""
    import subprocess
    import sys

    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(sandbox_appdata)

    # Launch desktop host as external background process
    proc = subprocess.Popen(
        [sys.executable, "-m", "service.desktop.desktop_host", "--no-browser", "--no-tray"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait up to 8 seconds for state file and health
        state_file = get_state_file()
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if state_file.is_file():
                break
            time.sleep(0.2)

        assert state_file.is_file(), "Desktop host failed to write runtime state in time"

        # Check --status via subprocess
        res_status = subprocess.run(
            [sys.executable, "-m", "service.desktop.desktop_host", "--status"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert res_status.returncode == 0
        status_json = json.loads(res_status.stdout)
        assert status_json.get("status") == "RUNNING"
        state_pid = status_json.get("pid")
        assert state_pid is not None and state_pid > 0
        assert is_process_running(state_pid) is True

        # Check --stop via subprocess
        res_stop = subprocess.run(
            [sys.executable, "-m", "service.desktop.desktop_host", "--stop"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert res_stop.returncode == 0
        assert "stopped cleanly" in res_stop.stdout

        # Verify host process exited
        proc.wait(timeout=5.0)
        assert not is_process_running(proc.pid)
        assert not state_file.is_file()

    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_port_fallback_when_8765_occupied(sandbox_appdata: Path) -> None:
    """Test bounded port fallback (8766-8799) when 8765 is occupied by another process."""
    # Occupy port 8765 with a dummy listening socket
    dummy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dummy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        dummy_sock.bind(("127.0.0.1", 8765))
        dummy_sock.listen(1)
        assert is_port_available(8765) is False

        # find_available_port should skip 8765 and pick 8766
        fallback_port = find_available_port(preferred=8765)
        assert fallback_port >= 8766
        assert fallback_port <= 8799

        # DesktopHost should automatically use the fallback port
        host = DesktopHost(
            port=None,
            no_browser=True,
            no_tray=True,
            mutex_name=f"Local\\ClearMark_Test_Mutex_{int(time.time())}_4",
        )
        assert host.acquire_single_instance() is True
        host.start_control_channel()
        host.start_http_server()

        assert host.actual_port == fallback_port
        assert host.wait_for_health(timeout_seconds=5.0) is True
        host.request_stop()

    finally:
        dummy_sock.close()


def test_stale_state_recovery(sandbox_appdata: Path) -> None:
    """Test that a stale runtime state file with a dead PID is automatically cleaned up."""
    state_file = get_state_file()
    stale_data = {
        "pid": 9999999,  # Non-existent PID
        "port": 8765,
        "control_port": 54321,
        "control_token": "abcdef0123456789",
        "version": "2.2.0-rc1",
        "status": "RUNNING",
    }
    state_file.write_text(json.dumps(stale_data), encoding="utf-8")
    assert state_file.is_file()

    # Attempting to send a control command should detect dead PID, purge stale state, and raise RuntimeError
    with pytest.raises(RuntimeError, match="stale runtime state was cleaned up"):
        send_control_command("STATUS")

    # Verify stale file was removed
    assert not state_file.is_file()


def test_system_tray_lifecycle() -> None:
    """Test SystemTrayIcon instantiation, start, and stop cleanly."""
    stopped = threading.Event()

    tray = SystemTrayIcon(
        icon_path=None,
        tooltip="ClearMark Test",
        on_stop=lambda: stopped.set(),
    )
    tray.start()
    tray.update_tooltip("ClearMark Test Updated")
    tray.stop()


def test_8765_occupied_by_clearmark(sandbox_appdata: Path) -> None:
    """Verify that when 8765 is occupied by ClearMark, subsequent launch connects rather than erroring."""
    test_mutex = f"Local\\ClearMark_Test_Mutex_{int(time.time())}_5"
    browser_signal = threading.Event()

    host1 = DesktopHost(
        port=8765,
        no_browser=True,
        no_tray=True,
        mutex_name=test_mutex,
    )
    host1.open_browser = lambda: browser_signal.set()  # type: ignore[assignment]

    assert host1.acquire_single_instance() is True
    host1.start_control_channel()
    host1.start_http_server()
    assert host1.wait_for_health(timeout_seconds=5.0) is True
    host1.status = "RUNNING"
    host1.write_runtime_state()

    try:
        # Launch second ClearMark host instance
        host2 = DesktopHost(
            port=8765,
            no_browser=True,
            no_tray=True,
            mutex_name=test_mutex,
        )
        code = host2.run()
        assert code == 0
        assert browser_signal.wait(timeout=3.0) is True

    finally:
        host1.request_stop()


def test_bad_resource_and_invalid_token_handling(sandbox_appdata: Path) -> None:
    """Test resilience against missing icons and unauthorized control channel access."""
    test_mutex = f"Local\\ClearMark_Test_Mutex_{int(time.time())}_6"
    host = DesktopHost(
        icon_path="C:\\NonExistent\\Path\\missing.ico",
        no_browser=True,
        no_tray=True,
        mutex_name=test_mutex,
    )
    assert host.acquire_single_instance() is True
    host.start_control_channel()
    host.start_http_server()
    assert host.wait_for_health(timeout_seconds=5.0) is True

    try:
        # Send request with invalid token -> 401 Unauthorized
        url = f"http://127.0.0.1:{host._control_port}/control"
        bad_req = urllib.request.Request(
            url,
            data=b'{"token": "invalid_token", "command": "STATUS"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req, timeout=2.0)
        assert exc_info.value.code == 401

        # Send request with bad JSON -> 400 Bad Request
        bad_json_req = urllib.request.Request(
            url,
            data=b'{not valid json',
            headers={"Content-Type": "application/json", "X-ClearMark-Token": host.control_token},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info2:
            urllib.request.urlopen(bad_json_req, timeout=2.0)
        assert exc_info2.value.code == 400

    finally:
        host.request_stop()


def test_zero_orphan_process_audit(sandbox_appdata: Path) -> None:
    """Test 3 sequential start/stop cycles, verifying zero orphan processes, sockets, or leaked states."""
    for i in range(3):
        host = DesktopHost(
            no_browser=True,
            no_tray=True,
            mutex_name=f"Local\\ClearMark_Test_Mutex_{int(time.time())}_cycle_{i}",
        )
        assert host.acquire_single_instance() is True
        host.start_control_channel()
        host.start_http_server()
        assert host.wait_for_health(timeout_seconds=5.0) is True
        port = host.actual_port
        host.request_stop()

        # Check port released
        time.sleep(0.5)
        assert is_port_available(port) is True
        assert not get_state_file().is_file()

