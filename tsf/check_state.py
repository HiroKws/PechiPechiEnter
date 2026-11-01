"""er_tip が書いた「未確定あり／なし」を読む（動作確認用）.

    python tsf/check_state.py          # 1 回だけ表示
    python tsf/check_state.py --watch  # 0.5 秒ごとに更新（Ctrl+C で終了）

共有メモリのレイアウトは er_tip.cpp と同じ（固定幅・パック済み）:

    Shared { int32 magic; int64 updated; Slot[32] }
    Slot   { int32 tid; int32 composing; int64 tick; int32 seq; }

``tick`` は GetTickCount64（ミリ秒）。``composing=1`` なら日本語入力の未確定文字列がある。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time

SHARED_NAME = "Local\\enter-router-tsf"
MAGIC = 0x53545245              # 'ERTS'
SLOTS = 32
SLOT = struct.Struct("<iiqi")   # tid, composing, tick, seq
HEAD = struct.Struct("<iq")     # magic, updated
SIZE = HEAD.size + SLOT.size * SLOTS


def open_shared():
    """既存のマッピングを開く（TIP がまだ動いていなければ None）."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenFileMappingW.restype = wt.HANDLE
    kernel32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    handle = kernel32.OpenFileMappingW(0x0004, False, SHARED_NAME)  # FILE_MAP_READ
    if not handle:
        return None, None
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD,
                                       ctypes.c_size_t]
    view = kernel32.MapViewOfFile(handle, 0x0004, 0, 0, SIZE)
    if not view:
        return None, None
    buf = ctypes.string_at(view, SIZE)
    return handle, buf


def snapshot() -> tuple[int, list[tuple[int, int, int, int]]]:
    handle, buf = open_shared()
    if buf is None:
        return -1, []
    magic, updated = HEAD.unpack_from(buf, 0)
    slots = []
    for i in range(SLOTS):
        tid, composing, tick, seq = SLOT.unpack_from(buf, HEAD.size + i * SLOT.size)
        if tid:
            slots.append((tid, composing, tick, seq))
    try:
        ctypes.WinDLL("kernel32").CloseHandle(handle)
    except Exception:
        pass
    if magic != MAGIC:
        return -2, slots
    return updated, slots


def show(now_tick: int | None = None) -> int:
    updated, slots = snapshot()
    if updated == -1:
        print("共有メモリがありません（er_tip がまだ読み込まれていない）")
        return 1
    if updated == -2:
        print("magic が一致しません（別のプロセスが同じ名前を使っています）")
        return 2
    if now_tick is None:
        now_tick = int(time.monotonic() * 1000)   # 概算（厳密比較には使わない）
    print(f"slots={len(slots)}")
    for tid, composing, tick, seq in slots:
        state = "未確定あり(日本語入力中)" if composing else "未確定なし"
        print(f"  tid={tid:<7} {state:<22} age={now_tick - tick:>7}ms seq={seq}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watch", action="store_true", help="0.5 秒ごとに表示し続ける")
    args = ap.parse_args(argv)
    if not args.watch:
        return show()
    try:
        while True:
            print("\033[2J\033[H", end="")
            print(time.strftime("%H:%M:%S"))
            show()
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
