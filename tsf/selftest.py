"""er_tip の動作確認（メモ帳で日本語入力中→確定後の状態を読む）.

    python tsf/selftest.py

何をするか: メモ帳を開き、前面にして日本語入力をオン（半角/全角）にし、`k` `a` を送って
未確定の「か」を作り、そのときと確定後の共有メモリの状態を表示する。
読み取りだけで、何も設定しない。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from check_state import snapshot                     # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 2


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def proto() -> None:
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.AttachThreadInput.restype = wt.BOOL
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    kernel32.GetCurrentThreadId.restype = wt.DWORD


def title(h) -> str:
    b = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, b, 256)
    return b.value


def find_window(pid: int) -> int:
    hit = [0]

    def cb(h, _l):
        owner = wt.DWORD(0)
        user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
        if int(owner.value) == pid and title(h):
            hit[0] = h
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return hit[0]


def take_foreground(hwnd: int) -> bool:
    fg = user32.GetForegroundWindow()
    our = int(kernel32.GetCurrentThreadId())
    fg_tid = int(user32.GetWindowThreadProcessId(fg, None))
    target_tid = int(user32.GetWindowThreadProcessId(hwnd, None))
    for tid in {fg_tid, target_tid}:
        if tid and tid != our:
            user32.AttachThreadInput(our, tid, 1)
    user32.BringWindowToTop(hwnd)
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    ok = user32.GetForegroundWindow() == hwnd
    for tid in {fg_tid, target_tid}:
        if tid and tid != our:
            user32.AttachThreadInput(our, tid, 0)
    return ok


def key(vk: int) -> None:
    def one(flags: int):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = KEYBDINPUT(vk, 0, flags, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    one(0)
    time.sleep(0.05)
    one(KEYEVENTF_KEYUP)
    time.sleep(0.12)


TARGET = {"tid": 0, "hwnd": 0}


def show(tag: str) -> bool:
    _updated, slots = snapshot()
    mine = next((c for tid, c, _t, _s in slots if tid == TARGET["tid"]), None)
    truth = title(TARGET["hwnd"]).split(" - ")[0] if TARGET["hwnd"] else ""
    print(f"[{tag}]")
    print(f"   ページの正解 : {truth!r}")
    print(f"   TIP の状態   : tid={TARGET['tid']} composing={mine} "
          f"(全 {len(slots)} スレッド)")
    return bool(mine)


def main() -> int:
    proto()
    import os
    tmp = os.environ.get("TMPDIR") or os.environ.get("TEMP") or "."
    page = os.path.join(tmp, "er_selftest.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write("""<!doctype html><meta charset=utf-8><title>ERSTATE ready</title>
<body style='font:32px sans-serif;margin:30px'>
<textarea id=t rows=3 cols=20 autofocus></textarea>
<script>
const t = document.getElementById('t');
function report(s){document.title='ERSTATE '+s+' c='+(window.__c?1:0)
  +' v='+JSON.stringify(t.value);}
window.__c=false;
t.addEventListener('compositionstart',()=>{window.__c=true;report('COMPOSING');});
t.addEventListener('compositionupdate',()=>report('COMPOSING'));
t.addEventListener('compositionend',()=>{window.__c=false;report('COMMITTED');});
t.addEventListener('input',()=>report('INPUT'));
t.focus();report('READY');
</script>""")
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not os.path.exists(edge):
        edge = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    profile = os.path.join(tmp, "er_selftest_profile")
    proc = subprocess.Popen([edge, f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-extensions",
                             "--disable-sync",
                             f"file:///{page.replace(os.sep, '/')}"])
    hwnd = 0
    for _ in range(40):
        time.sleep(0.25)
        hwnd = find_window(proc.pid)
        if hwnd:
            break
    if not hwnd:
        print("対象の窓が見つかりません")
        return 1
    TARGET["hwnd"] = hwnd
    TARGET["tid"] = int(user32.GetWindowThreadProcessId(hwnd, None))
    print(f"target hwnd=0x{hwnd & 0xFFFFFFFF:X} pid={proc.pid} tid={TARGET['tid']}")
    print("foreground:", take_foreground(hwnd))
    time.sleep(1.0)

    show("起動直後")
    key(0x19)                 # 半角/全角 = 日本語入力オン
    time.sleep(0.2)
    key(0x4B)                 # k
    show("k の後（日本語入力中）")
    key(0x41)                 # a
    show("ka の後（未確定のか）")
    key(0x0D)                 # Enter = 確定
    time.sleep(0.3)
    ok_after = show("確定後")
    print()
    print("結果:", "未確定を検出できた" if ok_after is False else "未確定が残っている")
    try:
        proc.terminate()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
