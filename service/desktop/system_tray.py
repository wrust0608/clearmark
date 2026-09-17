"""service.desktop.system_tray

Windows System Tray implementation for ClearMark desktop host.
Uses pure Win32 API via standard library ctypes — zero third-party C dependencies,
lightning-fast startup, native look and feel.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import sys
import threading
from typing import Callable, Optional

logger = logging.getLogger("clearmark.desktop.tray")

# Win32 Constants
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_NULL = 0x0000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_STATE = 0x00000008
NIF_INFO = 0x00000010

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_BYCOMMAND = 0x00000000
MF_GRAYED = 0x00000001
MF_DISABLED = 0x00000002

TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020

CW_USEDEFAULT = 0x80000000

# Command IDs for Context Menu
CMD_OPEN = 1001
CMD_STATUS = 1002
CMD_RESTART = 1003
CMD_OPEN_LOGS = 1004
CMD_STOP = 1005


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


LRESULT = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class SystemTrayIcon:
    """Native Windows System Tray Icon using pure ctypes / Win32 API."""

    def __init__(
        self,
        icon_path: Optional[str] = None,
        tooltip: str = "ClearMark",
        on_open: Optional[Callable[[], None]] = None,
        on_status: Optional[Callable[[], None]] = None,
        on_restart: Optional[Callable[[], None]] = None,
        on_open_logs: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
    ) -> None:
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.on_open = on_open
        self.on_status = on_status
        self.on_restart = on_restart
        self.on_open_logs = on_open_logs
        self.on_stop = on_stop

        self._hwnd: Optional[int] = None
        self._hicon: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._class_atom = 0
        self._wndproc_ref = None  # Prevent garbage collection of callback

    def start(self) -> None:
        """Start the system tray message loop in a dedicated background thread."""
        if os.name != "nt":
            logger.info("Non-Windows OS: running mock system tray")
            self._ready_event.set()
            return

        self._thread = threading.Thread(target=self._run_loop, name="ClearMarkSystemTray", daemon=True)
        self._thread.start()
        # Wait until window and tray icon are initialized (max 5s)
        self._ready_event.wait(timeout=5.0)

    def stop(self) -> None:
        """Remove icon and cleanly terminate tray window thread."""
        self._stop_event.set()
        if os.name != "nt" or not self._hwnd:
            return

        user32 = ctypes.windll.user32
        # Post a custom destroy / quit message to window
        try:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
        except Exception as e:
            logger.debug("Error posting WM_DESTROY to tray window: %s", e)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def update_tooltip(self, new_tooltip: str) -> None:
        """Update tray tooltip dynamically."""
        self.tooltip = new_tooltip
        if os.name != "nt" or not self._hwnd:
            return

        try:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._hwnd
            nid.uID = 1
            nid.uFlags = NIF_TIP
            nid.szTip = new_tooltip[:127]
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception as e:
            logger.debug("Failed to update tray tooltip: %s", e)

    def _run_loop(self) -> None:
        """Thread worker executing Win32 message pump."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32

        # Configure 64-bit function prototypes
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT

        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM

        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND

        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL

        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL

        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = LRESULT

        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostQuitMessage.restype = None

        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL

        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL

        user32.CreatePopupMenu.argtypes = []
        user32.CreatePopupMenu.restype = wintypes.HMENU

        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_uint64, wintypes.LPCWSTR]
        user32.AppendMenuW.restype = wintypes.BOOL

        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL

        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL

        user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, wintypes.LPVOID,
        ]
        user32.TrackPopupMenu.restype = wintypes.BOOL

        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyMenu.restype = wintypes.BOOL

        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"ClearMark_Tray_Window_{os.getpid()}"

        def wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_TRAYICON:
                # Left double-click or single-click -> Open ClearMark UI
                if lparam in (WM_LBUTTONDBLCLK, WM_LBUTTONUP):
                    if self.on_open:
                        try:
                            self.on_open()
                        except Exception as ex:
                            logger.error("Error in on_open callback: %s", ex)
                    return 0

                # Right-click -> Context Menu
                if lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_context_menu(hwnd)
                    return 0

            elif msg == WM_COMMAND:
                cmd_id = wintypes.LOWORD(wparam)
                self._handle_command(cmd_id)
                return 0

            elif msg == WM_DESTROY:
                # Clean up tray icon
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = hwnd
                nid.uID = 1
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                user32.PostQuitMessage(0)
                return 0

            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wndproc)

        # Register Window Class
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinstance
        wc.hIcon = 0
        wc.hCursor = 0
        wc.hbrBackground = 0
        wc.lpszMenuName = None
        wc.lpszClassName = class_name

        self._class_atom = user32.RegisterClassW(ctypes.byref(wc))
        if not self._class_atom:
            logger.error("Failed to register window class for system tray")
            self._ready_event.set()
            return

        # Create hidden message-only window
        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "ClearMark Tray Window",
            0,
            0, 0, 0, 0,
            0, 0, hinstance, None
        )
        if not hwnd:
            logger.error("Failed to create hidden window for system tray")
            self._ready_event.set()
            return

        self._hwnd = hwnd

        # Load Icon
        hicon = 0
        if self.icon_path and os.path.isfile(self.icon_path):
            hicon = user32.LoadImageW(
                0,
                self.icon_path,
                IMAGE_ICON,
                0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
        if not hicon:
            # Fallback to application default icon
            hicon = user32.LoadIconW(0, wintypes.LPCWSTR(32512))  # IDI_APPLICATION

        self._hicon = hicon

        # Add icon to notification area
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = hicon
        nid.szTip = self.tooltip[:127]

        res = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        if not res:
            logger.warning("Shell_NotifyIconW NIM_ADD returned False")

        self._ready_event.set()

        # Win32 Message Loop
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            b_ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if b_ret == 0 or b_ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup class registration
        try:
            user32.UnregisterClassW(class_name, hinstance)
        except Exception:
            pass

    def _show_context_menu(self, hwnd: int) -> None:
        """Create and track the Win32 popup context menu."""
        user32 = ctypes.windll.user32
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return

        try:
            # Menu items:
            # Open ClearMark (default)
            # Status
            # Restart Server
            # Open Logs
            # ----------------
            # Stop ClearMark
            user32.AppendMenuW(hmenu, MF_STRING, CMD_OPEN, "Open ClearMark")
            user32.AppendMenuW(hmenu, MF_STRING, CMD_STATUS, "Status")
            user32.AppendMenuW(hmenu, MF_STRING, CMD_RESTART, "Restart Server")
            user32.AppendMenuW(hmenu, MF_STRING, CMD_OPEN_LOGS, "Open Logs")
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(hmenu, MF_STRING, CMD_STOP, "Stop ClearMark")

            # Set default bold item
            user32.SetMenuDefaultItem(hmenu, CMD_OPEN, 0)

            # Must set foreground window before TrackPopupMenu
            user32.SetForegroundWindow(hwnd)
            user32.TrackPopupMenu(
                hmenu,
                TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_BOTTOMALIGN,
                pt.x,
                pt.y,
                0,
                hwnd,
                None,
            )
            user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(hmenu)

    def _handle_command(self, cmd_id: int) -> None:
        """Dispatch menu command to callback."""
        if cmd_id == CMD_OPEN and self.on_open:
            threading.Thread(target=self.on_open, name="TrayOpenCallback", daemon=True).start()
        elif cmd_id == CMD_STATUS and self.on_status:
            threading.Thread(target=self.on_status, name="TrayStatusCallback", daemon=True).start()
        elif cmd_id == CMD_RESTART and self.on_restart:
            threading.Thread(target=self.on_restart, name="TrayRestartCallback", daemon=True).start()
        elif cmd_id == CMD_OPEN_LOGS and self.on_open_logs:
            threading.Thread(target=self.on_open_logs, name="TrayLogsCallback", daemon=True).start()
        elif cmd_id == CMD_STOP and self.on_stop:
            threading.Thread(target=self.on_stop, name="TrayStopCallback", daemon=True).start()
