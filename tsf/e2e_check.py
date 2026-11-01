"""エンドツーエンド確認: ルーターが TSF の状態で判断しているか（ログで確認）.

Edge の入力欄で
  1. 日本語入力をオンにして k, a（未確定の「か」）→ Enter
     → 期待: ログに tsf_state composing=1、Enter は飲み込まれない（確定に使われる）
  2. 確定後（未確定なし）に Enter
     → 期待: tsf_state composing=0、decision=HOLD（1回目=改行の保留）
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import re
import subprocess
import sys
import time

LOG = os.path.join(os.environ["APPDATA"], "enter-router", "logs",
                   "enter-router.log")

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
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    kernel32.GetCurrentThreadId.restype = wt.DWORD


def title(h) -> str:
    b = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, b, 512)
    return b.value


def find(part: str) -> int:
    hit = [0]

    def cb(h, _l):
        if part in title(h):
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


def key(vk: int, wait: float = 0.15) -> None:
    def one(flags: int):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = KEYBDINPUT(vk, 0, flags, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    one(0)
    time.sleep(0.05)
    one(KEYEVENTF_KEYUP)
    time.sleep(wait)


def log_lines(since: float) -> list[str]:
    try:
        with open(LOG, encoding="utf-8", errors="replace") as fh:
            rows = fh.readlines()
    except OSError:
        return []
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(since))
    out = []
    for row in rows[-400:]:
        if row[:16] < stamp:
            continue
        if re.search(r"tsf_state|decision=|inject |ime_passthrough|ime_commit", row):
            out.append(row.rstrip()[:150])
    return out


def main() -> int:
    proto()
    tmp = os.environ.get("TMPDIR") or os.environ.get("TEMP") or "."
    page = os.path.join(tmp, "er_e2e.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write("""<!doctype html><meta charset=utf-8><title>ERSTATE ready</title>
<body style='font:32px sans-serif;margin:30px'>
<textarea id=t rows=3 cols=20 autofocus></textarea>
<script>
const t=document.getElementById('t');
function r(s){document.title='ERSTATE '+s+' c='+(window.__c?1:0)+' v='+JSON.stringify(t.value);}
window.__c=false;
t.addEventListener('compositionstart',()=>{window.__c=true;r('COMPOSING');});
t.addEventListener('compositionend',()=>{window.__c=false;r('COMMITTED');});
t.addEventListener('input',()=>r('INPUT'));
t.focus();r('READY');
</script>""")
    profile = os.path.join(tmp, "er_e2e_profile")
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not os.path.exists(edge):
        edge = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    proc = subprocess.Popen([edge, f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-extensions",
                             "--disable-sync", f"file:///{page.replace(os.sep, '/')}"])
    hwnd = 0
    for _ in range(60):
        time.sleep(0.25)
        hwnd = find("ERSTATE")
        if hwnd:
            break
    if not hwnd:
        print("FAIL: 窓が見つかりません")
        proc.terminate()
        return 1
    print(f"target hwnd=0x{hwnd & 0xFFFFFFFF:X}  foreground={take_foreground(hwnd)}")
    time.sleep(1.0)
    started = time.time()

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "src"))
    from enter_router.platform import tsf_state

    def probe(tag: str) -> None:
        """ルーターが Enter の瞬間に呼ぶのと同じ関数を、同じ窓で呼ぶ."""
        print(f"  [{tag}] tsf_state.composing() = {tsf_state.composing(hwnd)}")

    probe("入力前")
    key(0x19)          # 半角/全角 = 日本語入力オン
    key(0x4B)          # k
    key(0x41)          # a  -> 未確定の「か」
    print(f"  正解(未確定中): {title(hwnd).split(' - ')[0]!r}")
    probe("未確定のか がある間")
    key(0x0D, wait=0.6)   # Enter: 日本語入力中なのでルーターは触らないはず
    print(f"  正解(確定後)  : {title(hwnd).split(' - ')[0]!r}")
    probe("確定後")

    key(0x0D, wait=0.6)   # Enter: 未確定なし → 1回目なので保留（改行）
    time.sleep(0.5)

    print("\n--- ルーターのログ ---")
    for line in log_lines(started):
        print("  " + line)
    try:
        proc.terminate()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
