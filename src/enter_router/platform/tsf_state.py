"""er_tip の共有メモリを読む（Windows アダプタ）.

``core/tsf_state.py`` が解析、こちらが Win32 呼び出し。**例外を投げない**
（キーボードフックの中から呼ばれるため）。

er_tip が未登録・未起動・対象外アプリのときは ``None`` を返し、呼び側は従来の
安全側（日本語入力中とみなして素通し）にフォールバックする。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging

from enter_router.core import tsf_state

log = logging.getLogger("enter_router.tsf")

NAME = "Local\\enter-router-tsf"
FILE_MAP_READ = 0x0004
_protos_ready = False
_k32 = None
_u32 = None


def _init() -> bool:
    global _protos_ready, _k32, _u32
    if _protos_ready:
        return True
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenFileMappingW.restype = wt.HANDLE
        k32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD,
                                      ctypes.c_size_t]
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [wt.HANDLE]
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.GetWindowThreadProcessId.restype = wt.DWORD
        u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        _k32, _u32 = k32, u32      # 同じインスタンスを使い回す（prototype は
        _protos_ready = True       # DLL インスタンスごとに保持されるため）
        return True
    except BaseException:
        log.debug("tsf_state: prototype setup failed", exc_info=True)
        return False


def read_shared() -> bytes | None:
    """共有メモリの生バイト列（無ければ None）."""
    if not _init():
        return None
    try:
        k32 = _k32
        handle = k32.OpenFileMappingW(FILE_MAP_READ, False, NAME)
        if not handle:
            return None
        try:
            view = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, tsf_state.SIZE)
            if not view:
                return None
            try:
                return ctypes.string_at(view, tsf_state.SIZE)
            finally:
                k32.UnmapViewOfFile(view)
        finally:
            k32.CloseHandle(handle)
    except BaseException:
        log.debug("tsf_state: read failed", exc_info=True)
        return None


def composing(hwnd: int, max_age_ms: int = tsf_state.DEFAULT_MAX_AGE_MS) -> bool | None:
    """``hwnd`` のスレッドが日本語入力中なら True / 確定後・未入力なら False.

    読めない（er_tip 未登録・対象外アプリ・記録が古い）なら None。
    """
    if not hwnd:
        return None
    buf = read_shared()
    if buf is None:
        return None
    try:
        now = int(_k32.GetTickCount64())
        tid = int(_u32.GetWindowThreadProcessId(hwnd, None) or 0)
        if not tid:
            return None
        return tsf_state.composing_for(buf, tid, now, max_age_ms=max_age_ms)
    except BaseException:
        log.debug("tsf_state: query failed", exc_info=True)
        return None
