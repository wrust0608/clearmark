# ClearMark Desktop Architecture (v2.2.0-rc1)

## 1. Executive Summary

ClearMark v2.2.0-rc1 introduces the Windows Desktop distribution: a standalone, zero-terminal, zero-Python one-click desktop application.
The underlying inspection and cleaning engine (`format_policy`, `docx`, `pptx`, `xlsx`, audio, video, text) remains 100% frozen, identical to the validated v2.1.0 release.

---

## 2. Core Architectural Pillars

### A. Lifecycle Host (`ClearMark.exe`)
The desktop distribution is owned by a single native Windows executable (`ClearMark.exe`) built via PyInstaller in `onedir + windowed` configuration.
- **Windowed Execution**: Subsystem Windows (`/SUBSYSTEM:WINDOWS`), preventing any command prompt or console window from flashing or staying open.
- **Bundled Runtime**: Bundles CPython 3.12 and all standard libraries into `_internal/`. The host machine requires no prior Python installation.
- **Sub-Second Launch**: The `onedir` layout avoids the startup penalty of unpacking temporary archives on each execution.

### B. Single-Instance Enforcement
To prevent conflicting instances or duplicate servers:
1. On startup, `DesktopHost` attempts to create a session-scoped Windows Named Mutex:
   ```
   Local\ClearMark_Desktop_SingleInstance
   ```
2. If `GetLastError() == ERROR_ALREADY_EXISTS`, the process knows another instance is active.
3. The new process does not start a second server or open a second tray icon.
4. It queries `%LOCALAPPDATA%\ClearMark\state\clearmark_state.json` for the running instance's control port and token, sends an authenticated `OPEN` command to bring the existing browser UI to focus, and immediately exits with code 0.

### C. Local Authenticated Control Channel
Inter-process communication (IPC) between CLI commands (`ClearMark.exe --status`, `ClearMark.exe --stop`, `ClearMark.exe --restart`) and the running desktop host is handled via a private loopback control channel:
- **Binding**: Strictly `127.0.0.1` on an OS-assigned ephemeral port (`server_port = 0`).
- **Authentication**: A cryptographically random 128-bit hex token (`secrets.token_hex(16)`) generated at startup and written to the user-scoped runtime state file.
- **Protocol**: HTTP POST `/control` with JSON payload.
- **Access Control**: Requests from any non-loopback IP or with an invalid token are rejected with `403 Forbidden` / `401 Unauthorized`.
- **Supported Actions**:
  - `OPEN`: Triggers browser open/focus to the active ClearMark UI.
  - `STATUS`: Returns real-time JSON metrics (`status`, `pid`, `port`, `control_port`, `version`, `start_time`).
  - `STOP`: Initiates asynchronous graceful shutdown.
  - `RESTART`: Shuts down and re-binds the HTTP engine while keeping the desktop lifecycle host alive.

### D. Windows System Tray
Implemented in pure Python using the Win32 API via `ctypes`:
- **Zero Third-Party C Dependencies**: Uses standard library `ctypes` (`user32.dll`, `kernel32.dll`, `shell32.dll`), avoiding heavy third-party wheels like Pillow/pystray and saving ~30MB.
- **Full 64-Bit Compatibility**: Strictly defines 64-bit Win32 prototypes (`LRESULT = ctypes.c_ssize_t`, `WNDPROC`, `CreateWindowExW`, `Shell_NotifyIconW`).
- **Dedicated Message Loop**: Runs the Win32 message pump in a daemon thread.
- **Context Menu Options**:
  - **Open ClearMark** (Default bold action on double-click / left-click)
  - **Status** (Displays native Windows info message box)
  - **Restart Server** (Restarts HTTP engine)
  - **Open Logs** (Opens `clearmark.log` in Notepad / default viewer)
  - **Stop ClearMark** (Triggers graceful shutdown and terminates process)

### E. Port Management & Bounded Fallback
- **Preferred Port**: `8765`
- **Fallback Range**: `8766–8799`
- If 8765 is occupied by ClearMark: second instance connects to existing ClearMark.
- If 8765 is occupied by an unrelated application: `DesktopHost` probes bounded ports using `SO_EXCLUSIVEADDRUSE` on Windows, automatically selects the next available port (e.g. 8766), records it in runtime state, and directs the browser to the fallback port.
- Never creates or requests Windows Firewall exceptions.

### F. Runtime State & Logging
- **Root Directory**: `%LOCALAPPDATA%\ClearMark\`
- **State File**: `%LOCALAPPDATA%\ClearMark\state\clearmark_state.json`
- **Log File**: `%LOCALAPPDATA%\ClearMark\logs\clearmark.log`
- **Cache**: `%LOCALAPPDATA%\ClearMark\cache\`
- **Stale State Recovery**: If a state file references a dead PID, subsequent launches and control commands automatically purge the stale file without crashing.
- **Zero Orphan Audit**: On normal shutdown (`request_stop()`), HTTP server threads, control server threads, tray message pumps, and mutex handles are cleanly closed, state file is unlinked, and process exits with 0 lingering threads or processes.

---

## 3. Installer Architecture (`Inno Setup 6`)

- **Scope**: Per-user installation (`PrivilegesRequired=lowest`). Does NOT require UAC administrator elevation.
- **Install Path**: `%LOCALAPPDATA%\Programs\ClearMark`
- **Shortcuts**:
  - `Start Menu -> ClearMark` (`ClearMark.exe`)
  - `Start Menu -> Stop ClearMark` (`ClearMark.exe --stop`)
  - `Desktop -> ClearMark` (Optional task)
- **Uninstall Safety**:
  - Pre-uninstall check detects running `ClearMark.exe` and calls `ClearMark.exe --stop` prior to removing files.
  - Prompts user whether to clean up `%LOCALAPPDATA%\ClearMark` runtime state/cache while preserving technical logs.
