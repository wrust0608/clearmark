# ClearMark Windows Installation Guide

One-click provenance and watermark cleaning for Windows.
No Python installation required. No command prompt required.

---

## Standard Installation (Recommended)

1. Download and run **`ClearMark-Setup-v2.2.0-rc1.exe`**.
2. Double-click the **ClearMark** shortcut on your Desktop or Start Menu.
3. The ClearMark web interface will automatically open in your default browser.
4. To stop ClearMark: click the **ClearMark** icon in the Windows System Tray (near the clock) and select **Stop ClearMark**.

---

## Portable Edition (No Installation Required)

1. Download and extract **`ClearMark-v2.2.0-rc1-Windows-x64-portable.zip`**.
2. Double-click **`ClearMark.exe`**.
3. Use the browser interface at `http://127.0.0.1:8765/`.
4. Right-click the tray icon and select **Stop ClearMark** when finished.

---

## Stopping ClearMark

There are three ways to stop ClearMark cleanly:

1. **System Tray**: Right-click the ClearMark icon in the bottom-right taskbar tray and click **Stop ClearMark**.
2. **Start Menu**: Click **Start Menu -> ClearMark -> Stop ClearMark**.
3. **Command Line**: Open Command Prompt / PowerShell and run:
   ```cmd
   ClearMark.exe --stop
   ```

---

## Advanced CLI Controls

For administrators and automated workflows:

| Command | Action |
|---|---|
| `ClearMark.exe` | Launches the desktop lifecycle host (or focuses existing instance). |
| `ClearMark.exe --status` | Prints real-time server and process status JSON. |
| `ClearMark.exe --stop` | Signals running instance to shut down gracefully and wait for process exit. |
| `ClearMark.exe --restart` | Restarts the HTTP engine on the active port without stopping the tray host. |
| `ClearMark.exe --port 8770` | Overrides preferred port. |
| `ClearMark.exe --no-browser` | Launches server and tray icon without automatically launching a browser window. |
| `ClearMark.exe --no-tray` | Runs headless lifecycle host without creating a System Tray icon. |
| `ClearMark.exe --version` | Displays `ClearMark Desktop v2.2.0-rc1`. |

---

## Log Files and Troubleshooting

Technical diagnostic logs are automatically written to:
```
%LOCALAPPDATA%\ClearMark\logs\clearmark.log
```

If you encounter any startup difficulty, right-click the system tray icon and select **Open Logs**, or navigate to `%LOCALAPPDATA%\ClearMark\logs\` in File Explorer.
