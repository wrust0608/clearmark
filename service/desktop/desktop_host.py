"""service.desktop.desktop_host

Unified Windows desktop lifecycle host and launcher for ClearMark.
Owns server lifecycle, single-instance mutex, local authenticated control channel,
port fallback, health polling, browser launching, and graceful shutdown.

Target: ClearMark v2.2.0-rc1
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from service.desktop import DESKTOP_VERSION
from service.desktop.system_tray import SystemTrayIcon

# Default Ports & Limits
PREFERRED_PORT = 8765
PORT_SCAN_START = 8766
PORT_SCAN_END = 8799
MUTEX_NAME = "Local\\ClearMark_Desktop_SingleInstance"
ERROR_ALREADY_EXISTS = 183


def get_appdata_dir() -> Path:
    """Return canonical %LOCALAPPDATA%\\ClearMark root directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    base_dir = Path(local_app_data) / "ClearMark"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_state_file() -> Path:
    """Return path to clearmark_state.json."""
    state_dir = get_appdata_dir() / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "clearmark_state.json"


def get_log_file() -> Path:
    """Return path to clearmark.log."""
    logs_dir = get_appdata_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "clearmark.log"


def get_cache_dir() -> Path:
    """Return path to cache directory."""
    cache_dir = get_appdata_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def setup_desktop_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure technical logging to %LOCALAPPDATA%\\ClearMark\\logs\\clearmark.log."""
    log_path = get_log_file()
    logger = logging.getLogger("clearmark.desktop")
    logger.setLevel(level)

    # Avoid duplicate handlers on reload
    if not logger.handlers:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if host:port can be bound exclusively."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except (OSError, socket.error):
                pass
        try:
            s.bind((host, port))
            return True
        except (OSError, socket.error):
            return False


def find_available_port(preferred: int = PREFERRED_PORT, host: str = "127.0.0.1") -> int:
    """Return preferred port if free, else scan bounded range 8766-8799."""
    if is_port_available(preferred, host):
        return preferred
    for p in range(PORT_SCAN_START, PORT_SCAN_END + 1):
        if is_port_available(p, host):
            return p
    raise RuntimeError(f"No available ports found in range {preferred}, {PORT_SCAN_START}-{PORT_SCAN_END}")


def is_process_running(pid: int) -> bool:
    """Check if process with PID is currently alive."""
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not h_process:
            return False
        WAIT_TIMEOUT = 0x00000102
        res = kernel32.WaitForSingleObject(h_process, 0)
        kernel32.CloseHandle(h_process)
        return res == WAIT_TIMEOUT
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


# ============================================================================
# Local Authenticated Control Channel
# ============================================================================

class ControlRequestHandler(BaseHTTPRequestHandler):
    """Loopback-only authenticated HTTP handler for desktop control."""

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress default stderr logging

    def do_POST(self) -> None:
        host: DesktopHost = self.server.desktop_host  # type: ignore[attr-defined]

        # Verify loopback
        client_ip = self.client_address[0]
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            self.send_error(HTTPStatus.FORBIDDEN, "Access forbidden from non-loopback clients")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON body")
            return

        # Token authentication (header or body)
        auth_token = self.headers.get("X-ClearMark-Token") or payload.get("token")
        if not isinstance(auth_token, str) or not secrets.compare_digest(auth_token, host.control_token):
            self.send_error(HTTPStatus.UNAUTHORIZED, "Invalid or missing control token")
            return

        command = payload.get("command", "").upper()
        if command == "OPEN":
            host.open_browser()
            self._send_json({"ok": True, "action": "OPEN", "message": "Browser opened"})
        elif command == "STATUS":
            status_data = host.get_status_dict()
            self._send_json({"ok": True, "action": "STATUS", **status_data})
        elif command == "STOP":
            self._send_json({"ok": True, "action": "STOP", "message": "Shutdown scheduled"})
            threading.Thread(target=host.request_stop, name="AsyncStopThread", daemon=True).start()
        elif command == "RESTART":
            self._send_json({"ok": True, "action": "RESTART", "message": "Restart scheduled"})
            threading.Thread(target=host.restart_server, name="AsyncRestartThread", daemon=True).start()
        else:
            self.send_error(HTTPStatus.BAD_REQUEST, f"Unknown command: {command}")

    def _send_json(self, data: dict[str, Any]) -> None:
        out = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def find_default_icon_path() -> Optional[str]:
    """Resolve ClearMark.ico across source and PyInstaller bundled runtime environments."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "assets" / "ClearMark.ico",
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(getattr(sys, "_MEIPASS")) / "assets" / "ClearMark.ico")
    if hasattr(sys, "executable"):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "assets" / "ClearMark.ico")
        candidates.append(exe_dir / "_internal" / "assets" / "ClearMark.ico")

    for c in candidates:
        if c.is_file():
            return str(c)
    return None


# ============================================================================
# Desktop Lifecycle Host
# ============================================================================

class DesktopHost:
    """Coordinates the ClearMark server lifecycle, tray icon, and control channel."""

    def __init__(
        self,
        port: Optional[int] = None,
        no_browser: bool = False,
        no_tray: bool = False,
        icon_path: Optional[str] = None,
        mutex_name: Optional[str] = None,
    ) -> None:
        self.requested_port = port
        self.actual_port = 0
        self.no_browser = no_browser
        self.no_tray = no_tray
        self.icon_path = icon_path or find_default_icon_path()
        self.mutex_name = mutex_name or MUTEX_NAME

        self.logger = setup_desktop_logging()
        self.control_token = secrets.token_hex(16)
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.status = "INITIALIZING"

        self._mutex_handle: Optional[int] = None
        self._server = None
        self._server_thread: Optional[threading.Thread] = None
        self._control_server: Optional[ThreadingHTTPServer] = None
        self._control_thread: Optional[threading.Thread] = None
        self._control_port = 0

        self._tray: Optional[SystemTrayIcon] = None
        self._stop_event = threading.Event()

    def acquire_single_instance(self) -> bool:
        """Acquire Windows named mutex. Return True if first instance, False if already running."""
        if os.name != "nt":
            return True  # Fallback on non-Windows

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        last_error = kernel32.GetLastError()
        if last_error == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)
            return False

        self._mutex_handle = handle
        return True

    def release_single_instance(self) -> None:
        """Release mutex handle."""
        if os.name == "nt" and self._mutex_handle:
            ctypes.windll.kernel32.ReleaseMutex(self._mutex_handle)
            ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            self._mutex_handle = None

    def start_control_channel(self) -> None:
        """Start authenticated control server on 127.0.0.1 with ephemeral port."""
        server = ThreadingHTTPServer(("127.0.0.1", 0), ControlRequestHandler)
        server.desktop_host = self  # type: ignore[attr-defined]
        self._control_port = server.server_port
        self._control_server = server

        thread = threading.Thread(target=server.serve_forever, name="DesktopControlServer", daemon=True)
        thread.start()
        self._control_thread = thread
        self.logger.info("Control channel started on 127.0.0.1:%d", self._control_port)

    def write_runtime_state(self) -> None:
        """Persist current runtime state to %LOCALAPPDATA%\\ClearMark\\state\\clearmark_state.json."""
        state_file = get_state_file()
        state_data = {
            "pid": os.getpid(),
            "port": self.actual_port,
            "control_port": self._control_port,
            "control_token": self.control_token,
            "version": DESKTOP_VERSION,
            "start_time": self.start_time,
            "status": self.status,
        }
        state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")
        self.logger.info("Runtime state saved to %s", state_file)

    def clean_runtime_state(self) -> None:
        """Remove state file on shutdown."""
        state_file = get_state_file()
        try:
            if state_file.is_file():
                state_file.unlink()
                self.logger.info("Runtime state removed")
        except Exception as ex:
            self.logger.warning("Failed to remove runtime state file: %s", ex)

    def start_http_server(self) -> None:
        """Start the ClearMark HTTP cleaning engine server."""
        # Ensure service/scripts is in sys.path in both source and PyInstaller environments
        scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        if scripts_dir.is_dir() and str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        if hasattr(sys, "_MEIPASS"):
            meipass_scripts = Path(getattr(sys, "_MEIPASS")) / "service" / "scripts"
            if meipass_scripts.is_dir() and str(meipass_scripts) not in sys.path:
                sys.path.insert(0, str(meipass_scripts))
            elif str(getattr(sys, "_MEIPASS")) not in sys.path:
                sys.path.insert(0, str(getattr(sys, "_MEIPASS")))

        from service.scripts.server import create_server

        if self.requested_port:
            self.actual_port = self.requested_port
        else:
            self.actual_port = find_available_port(PREFERRED_PORT)

        self.logger.info("Binding ClearMark server to 127.0.0.1:%d", self.actual_port)
        self._server = create_server(host="127.0.0.1", port=self.actual_port)

        thread = threading.Thread(target=self._server.serve_forever, name="ClearMarkEngineServer", daemon=True)
        thread.start()
        self._server_thread = thread

    def wait_for_health(self, timeout_seconds: float = 10.0) -> bool:
        """Poll /health endpoint until 200 OK is returned."""
        deadline = time.monotonic() + timeout_seconds
        url = f"http://127.0.0.1:{self.actual_port}/health"

        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ClearMark-Desktop-Launcher"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("ok"):
                            self.logger.info("Health check passed: %s", data)
                            return True
            except Exception:
                time.sleep(0.1)

        return False

    def open_browser(self) -> None:
        """Open default browser to the running ClearMark UI."""
        url = f"http://127.0.0.1:{self.actual_port}/"
        self.logger.info("Opening browser to %s", url)
        try:
            webbrowser.open(url)
        except Exception as ex:
            self.logger.error("Failed to open browser: %s", ex)

    def show_status_dialog(self) -> None:
        """Display native Windows status dialog from tray."""
        if os.name != "nt":
            return
        status = self.get_status_dict()
        msg = (
            f"ClearMark Desktop v{DESKTOP_VERSION}\n"
            f"Status: {status['status']}\n"
            f"HTTP Port: {status['port']}\n"
            f"Process ID: {status['pid']}\n"
            f"Control Port: {status['control_port']}\n"
            f"Started: {status['start_time']}\n"
        )
        ctypes.windll.user32.MessageBoxW(0, msg, "ClearMark Status", 0x00000040)  # MB_ICONINFORMATION

    def open_logs(self) -> None:
        """Open log file in default text viewer / Notepad."""
        log_file = get_log_file()
        if os.name == "nt":
            try:
                os.startfile(str(log_file))
            except Exception:
                subprocess.Popen(["notepad.exe", str(log_file)])
        else:
            self.logger.info("Logs located at: %s", log_file)

    def restart_server(self) -> None:
        """Gracefully restart the HTTP server instance."""
        self.logger.info("Restarting server on port %d...", self.actual_port)
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception as ex:
                self.logger.warning("Error stopping server during restart: %s", ex)

        self.start_http_server()
        if self.wait_for_health(timeout_seconds=5.0):
            self.logger.info("Server restarted successfully")
            if self._tray:
                self._tray.update_tooltip(f"ClearMark (Port {self.actual_port})")
        else:
            self.logger.error("Server failed to become healthy after restart")

    def request_stop(self) -> None:
        """Initiate graceful shutdown."""
        self.logger.info("Shutdown requested")
        self.status = "STOPPING"
        self._stop_event.set()

        # Stop System Tray
        if self._tray:
            try:
                self._tray.stop()
            except Exception as ex:
                self.logger.debug("Error stopping tray: %s", ex)

        # Stop HTTP Server
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception as ex:
                self.logger.debug("Error stopping server: %s", ex)

        # Stop Control Server
        if self._control_server:
            try:
                self._control_server.shutdown()
                self._control_server.server_close()
            except Exception as ex:
                self.logger.debug("Error stopping control server: %s", ex)

        self.clean_runtime_state()
        self.release_single_instance()
        self.logger.info("Graceful shutdown complete")

    def run(self) -> int:
        """Main lifecycle entrypoint."""
        self.logger.info("=== ClearMark Desktop Host Starting (PID %d) ===", os.getpid())

        # 1. Single Instance Check
        if not self.acquire_single_instance():
            self.logger.info("Another instance is running. Signaling to open UI and exiting.")
            return signal_existing_instance_to_open()

        try:
            # 2. Start Control Channel
            self.start_control_channel()

            # 3. Start HTTP Server
            self.start_http_server()

            # 4. Wait for health
            if not self.wait_for_health(timeout_seconds=10.0):
                raise RuntimeError(f"Server at 127.0.0.1:{self.actual_port} failed to become healthy within 10s")

            self.status = "RUNNING"
            self.write_runtime_state()

            # 5. Open Browser (unless suppressed)
            if not self.no_browser:
                self.open_browser()

            # 6. Start System Tray (unless suppressed)
            if not self.no_tray:
                self._tray = SystemTrayIcon(
                    icon_path=self.icon_path,
                    tooltip=f"ClearMark (Port {self.actual_port})",
                    on_open=self.open_browser,
                    on_status=self.show_status_dialog,
                    on_restart=self.restart_server,
                    on_open_logs=self.open_logs,
                    on_stop=self.request_stop,
                )
                self._tray.start()

            # 7. Block main thread until stop requested
            while not self._stop_event.is_set():
                time.sleep(0.5)

            return 0

        except Exception as ex:
            self.logger.exception("Fatal error in desktop lifecycle: %s", ex)
            self.request_stop()
            self._show_fatal_error_dialog(str(ex))
            return 1

    def get_status_dict(self) -> dict[str, Any]:
        """Return status dictionary."""
        return {
            "status": self.status,
            "pid": os.getpid(),
            "port": self.actual_port,
            "control_port": self._control_port,
            "version": DESKTOP_VERSION,
            "start_time": self.start_time,
        }

    def _show_fatal_error_dialog(self, error_message: str) -> None:
        """Display Windows-friendly error dialog on startup failure."""
        if os.name == "nt" and not self.no_tray and not os.environ.get("CLEARMARK_NO_DIALOG"):
            user32 = ctypes.windll.user32
            msg = (
                f"ClearMark could not start.\n\n"
                f"Details: {error_message}\n\n"
                f"Do you want to view the log file for more information?"
            )
            # MB_ICONERROR | MB_YESNO
            res = user32.MessageBoxW(0, msg, "ClearMark Startup Failure", 0x00000010 | 0x00000004)
            if res == 6:  # IDYES
                self.open_logs()


# ============================================================================
# Client IPC Commands (--open, --status, --stop, --restart)
# ============================================================================

def send_control_command(command: str) -> dict[str, Any]:
    """Send authenticated command to running ClearMark desktop instance."""
    state_file = get_state_file()
    if not state_file.is_file():
        raise RuntimeError("ClearMark is not currently running (no runtime state file found).")

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as ex:
        raise RuntimeError(f"Corrupt runtime state file: {ex}")

    pid = state.get("pid")
    control_port = state.get("control_port")
    control_token = state.get("control_token")

    if not pid or not is_process_running(pid):
        # Stale state cleanup
        try:
            state_file.unlink()
        except Exception:
            pass
        raise RuntimeError("ClearMark is not running (stale runtime state was cleaned up).")

    url = f"http://127.0.0.1:{control_port}/control"
    req_body = json.dumps({"token": control_token, "command": command}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_body,
        headers={"Content-Type": "application/json", "X-ClearMark-Token": control_token},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def signal_existing_instance_to_open() -> int:
    """Signal existing running instance to open UI and focus browser."""
    logger = logging.getLogger("clearmark.desktop")
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            res = send_control_command("OPEN")
            if res.get("ok"):
                return 0
        except Exception as ex:
            time.sleep(0.2)
    logger.warning("Failed to signal existing instance within deadline.")
    return 0


def cmd_status() -> int:
    """Execute ClearMark.exe --status."""
    try:
        res = send_control_command("STATUS")
        print(json.dumps(res, indent=2))
        return 0
    except Exception as ex:
        print(f"ClearMark status: NOT RUNNING ({ex})", file=sys.stderr)
        return 1


def cmd_stop() -> int:
    """Execute ClearMark.exe --stop."""
    state_file = get_state_file()
    if not state_file.is_file():
        print("ClearMark is not running.")
        return 0

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        pid = state.get("pid")
    except Exception:
        pid = None

    if pid and not is_process_running(pid):
        # Stale state
        try:
            state_file.unlink()
        except Exception:
            pass
        print("ClearMark is not running (cleaned up stale state).")
        return 0

    try:
        res = send_control_command("STOP")
        print("Shutdown signal sent successfully.")
    except Exception as ex:
        print(f"Notice: {ex}")

    # Wait for process exit up to 5 seconds
    if pid:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not is_process_running(pid):
                print(f"ClearMark (PID {pid}) stopped cleanly.")
                try:
                    if state_file.is_file():
                        state_file.unlink()
                except Exception:
                    pass
                return 0
            time.sleep(0.2)

        print(f"Warning: Process {pid} did not exit within timeout.", file=sys.stderr)
        return 1

    return 0


def cmd_restart() -> int:
    """Execute ClearMark.exe --restart."""
    try:
        res = send_control_command("RESTART")
        print("ClearMark server restarted successfully.")
        return 0
    except Exception as ex:
        print(f"Failed to restart ClearMark: {ex}", file=sys.stderr)
        return 1


# ============================================================================
# Main Entry Point
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=f"ClearMark Desktop Host v{DESKTOP_VERSION}")
    parser.add_argument("-V", "--version", action="store_true", help="Print version and exit")
    parser.add_argument("--status", action="store_true", help="Query running ClearMark status")
    parser.add_argument("--stop", action="store_true", help="Stop running ClearMark instance")
    parser.add_argument("--restart", action="store_true", help="Restart running ClearMark server")
    parser.add_argument("--port", type=int, help="Override HTTP server port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser on launch")
    parser.add_argument("--no-tray", action="store_true", help="Do not create system tray icon")

    args = parser.parse_args()

    if args.version:
        print(f"ClearMark Desktop v{DESKTOP_VERSION}")
        return 0

    if args.status:
        return cmd_status()

    if args.stop:
        return cmd_stop()

    if args.restart:
        return cmd_restart()

    # Normal application launch
    host = DesktopHost(
        port=args.port,
        no_browser=args.no_browser,
        no_tray=args.no_tray,
    )
    return host.run()


if __name__ == "__main__":
    sys.exit(main())
