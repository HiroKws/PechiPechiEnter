"""User notifications (balloon/toast via Shell_NotifyIcon NIF_INFO) and the
tray icon state. The frontend card owns the icon lifecycle; the backend calls
notify() for sink results and safety events.

Degradation ladder (never raises, bounded ~500ms):
  1. tray icon registered (ui called ``register_icon``) -> NIF_INFO balloon/toast
  2. no tray icon yet -> log line + MessageBeep for warning/error
Either way the event is in the log, so "the user was not told" is impossible to
confuse with "nothing happened".

``body`` must never contain captured text beyond a ``preview_chars`` preview
(research R9); callers build the preview, this module does not know the text.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from typing import Literal

from enter_router.platform import win32lib

log = logging.getLogger("enter_router.notify")

Level = Literal["info", "warning", "error"]

NIM_MODIFY = 0x00000001
NIF_INFO = 0x00000010
NIIF_INFO, NIIF_WARNING, NIIF_ERROR = 0x01, 0x02, 0x03
NIF_ICON = 0x00000002

_LEVEL_FLAGS: dict[str, int] = {"info": NIIF_INFO, "warning": NIIF_WARNING,
                                "error": NIIF_ERROR}

_tray_hwnd: int = 0
_tray_uid: int = 1
#: Where the LAST balloon wants the user to land when it is clicked (v2-s).
#: The tray window receives NIN_BALLOONUSERCLICK and asks the app for this; the
#: string is a UI tab name ("profiles"), never a widget handle (ui/ owns those).
_click_action: str = ""
_click_lock = threading.Lock()

_protos_ready = False


def take_click_action() -> str:
    """Return and clear the action attached to the most recent notification."""
    global _click_action
    with _click_lock:
        action, _click_action = _click_action, ""
    return action


def _init_win32() -> None:
    """Declare the Shell_NotifyIconW prototype (review round 1: pointers)."""
    global _protos_ready
    if _protos_ready or not win32lib.IS_WINDOWS:
        return
    _protos_ready = True
    win32lib.proto("shell32", "Shell_NotifyIconW", win32lib.BOOL,
                   (win32lib.DWORD, ctypes.POINTER(NOTIFYICONDATAW)))


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong), ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint), ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint), ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_ulong), ("dwStateMask", ctypes.c_ulong),
        ("szInfo", ctypes.c_wchar * 256), ("uVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64), ("dwInfoFlags", ctypes.c_ulong),
    ]


def register_icon(hwnd: int, uid: int = 1) -> None:
    """Called by the tray UI once its icon exists (enables balloon notifications)."""
    global _tray_hwnd, _tray_uid
    _tray_hwnd, _tray_uid = int(hwnd), int(uid)
    log.debug("tray icon registered (hwnd=%s uid=%s)", _tray_hwnd, _tray_uid)


def _beep(level: str) -> None:
    try:
        import winsound
        winsound.MessageBeep(-1 if level == "error" else 0)
    except BaseException:
        pass


def notify(title: str, body: str, level: Level = "info", action: str = "") -> None:
    """Best-effort, bounded. Never raises.

    ``action`` names the place a CLICK on the balloon should open (v2-s). It is
    set for every notification — including an empty one — so the action always
    belongs to the balloon the user actually clicked, never to an older one.
    """
    global _click_action
    log.log({"info": logging.INFO, "warning": logging.WARNING,
             "error": logging.ERROR}.get(level, logging.INFO),
            "NOTIFY [%s] %s — %s%s", level, title, body,
            f" (click -> {action})" if action else "")
    with _click_lock:
        _click_action = action or ""
    if level in ("warning", "error"):
        _beep(level)
    if not _tray_hwnd:
        return
    try:
        _init_win32()
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = ctypes.c_void_p(_tray_hwnd)
        data.uID = _tray_uid
        data.uFlags = NIF_INFO
        data.szInfo = body[:255]
        data.szInfoTitle = title[:63]
        data.dwInfoFlags = _LEVEL_FLAGS.get(level, NIIF_INFO)
        win32lib.dll("shell32").Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
    except BaseException:
        log.debug("balloon notification failed (log line kept)", exc_info=True)
