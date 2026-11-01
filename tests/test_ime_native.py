"""日本語入力中（日本語変換オン）の Enter は **常に IME に渡す**（v2-y）.

オペレータの指示: 「日本語入力中は何もせず、日本語入力へ渡す。日本語変換が終わって
から、改行するか送信するかを決める」。

v2-h はこれに反して「直前の Enter 以降に文字キーを打ったか」で確定か操作かを推測し、
確定 Enter を奪っていた（実測 2026-11-01 04:46: 1 分間に 5 回）。v2-y で推測を削除。
未確定文字列は Hermes（Electron）では外から読めない（42 回の観測で 0 回）ので、
渡す以外に「日本語入力中に何も壊さない」方法はない。

v2-x で入れた `ime_unknown_policy` による分岐も、この判断からは外した
（"process" でも変換オンの Enter は渡す = NativeModeTest の最後のテスト）。
"""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from enter_router.app import main as app_main                      # noqa: E402
from enter_router.core.config import parse_config_text             # noqa: E402
from enter_router.core.events import (VK_RETURN, ForegroundInfo,    # noqa: E402
                                      ImeState, KeyEvent)
from enter_router.core.policy import State                          # noqa: E402

SAMPLE = REPO / "config" / "sample.config.json"
VK_A = 0x41
# The sample config carries a live "site-a" profile (firefox.exe + "Site A"); a
# foreground that matches nothing would leave the router switched off.
_SITE_A = ForegroundInfo(process_name="firefox.exe", window_title="Site A",
                         url="https://site-a.example.com/chat")
VK_SHIFT = 0x10


class _StaticFg:
    """Foreground cache stand-in with a settable hwnd (0 off Windows)."""

    def __init__(self, info: ForegroundInfo):
        self._info = info
        self.hwnd_value = 0

    def hwnd(self) -> int:
        return self.hwnd_value

    def snapshot(self):
        return self.hwnd_value, self._info

    def current(self) -> ForegroundInfo:
        return self._info

    def start(self):
        return None

    def stop(self):
        return None


class _ImeNativeBase(unittest.TestCase):
    policy = "pass"

    def setUp(self):
        self.cfg = replace(parse_config_text(SAMPLE.read_text(encoding="utf-8")),
                           ime_unknown_policy=self.policy)
        self.app = app_main.EnterRouterApp(self.cfg, str(SAMPLE))
        self.app._hook_thread = None
        from enter_router.platform import hook as hook_mod
        from enter_router.platform import ime as ime_mod
        from enter_router.platform import inject
        self.sent: list[tuple] = []
        self._saved = (ime_mod.query_composition, inject.send_combo,
                       inject.send_enter, hook_mod.wake, hook_mod.request_stop)
        # 日本語変換オン。未確定文字列の有無は観測できない。
        ime_mod.query_composition = lambda hwnd: ImeState(
            composing=None, source="ime_native", detail="ime_mode=(True, 9)")
        inject.send_combo = lambda combo, held=(): self.sent.append(("combo", combo)) or 4
        inject.send_enter = lambda n, held=(): self.sent.append(("enter", n)) or 2 * n
        hook_mod.wake = lambda: False
        hook_mod.request_stop = lambda reason="stop": None
        self.app._fg = _StaticFg(_SITE_A)

    def tearDown(self):
        from enter_router.platform import hook as hook_mod
        from enter_router.platform import ime as ime_mod
        from enter_router.platform import inject
        (ime_mod.query_composition, inject.send_combo, inject.send_enter,
         hook_mod.wake, hook_mod.request_stop) = self._saved
        self.app._timer.stop()

    def _text(self, t: int, vk: int = VK_A) -> None:
        """A text key down+up (goes through the hook, not decided as an Enter)."""
        self.app._decide(KeyEvent(vk=vk, kind="down", t_ms=t))
        self.app._decide(KeyEvent(vk=vk, kind="up", t_ms=t + 20))

    def _enter(self, t: int) -> bool:
        swallowed = self.app._decide(KeyEvent(vk=VK_RETURN, kind="down", t_ms=t))
        self.app._decide(KeyEvent(vk=VK_RETURN, kind="up", t_ms=t + 20))
        return swallowed


class NativeModeTest(_ImeNativeBase):
    """日本語変換オン: どの Enter もツールは取らない."""

    def test_enter_after_typing_is_handed_to_the_ime(self):
        self._text(1000)
        self.assertFalse(self._enter(1200))
        self.assertIs(self.app._machine.state, State.IDLE)
        self.assertEqual(self.app._machine.pending_count, 0)
        self.assertEqual(self.sent, [])

    def test_enter_without_typing_is_also_handed_to_the_ime(self):
        """未確定があるかは読めない＝渡す。ここで奪うと変換が壊れる（v2-y）."""
        self.assertFalse(self._enter(1200))
        self.assertIs(self.app._machine.state, State.IDLE)
        self.assertEqual(self.app._machine.pending_count, 0)
        self.assertEqual(self.sent, [])

    def test_two_enters_are_not_turned_into_a_newline_or_send(self):
        self._text(1000)
        self._enter(1200)
        self.assertFalse(self._enter(3000))
        self.assertFalse(self._enter(3120))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.app._machine.pending_count, 0)

    def test_a_long_burst_of_text_and_enters_never_injects(self):
        """実測 04:46 の再現: 1 分間に何度 Enter を押しても何も注入しない."""
        t = 1000
        for i in range(6):
            self._text(t, vk=VK_A + i)
            self.assertFalse(self._enter(t + 100))
            t += 300
        self.assertEqual(self.sent, [])
        self.assertEqual(self.app._machine.pending_count, 0)

    def test_modifiers_alone_change_nothing(self):
        self.app._decide(KeyEvent(vk=VK_SHIFT, kind="down", t_ms=1000))
        self.app._decide(KeyEvent(vk=VK_SHIFT, kind="up", t_ms=1010))
        self.assertFalse(self._enter(1200))
        self.assertEqual(self.app._machine.pending_count, 0)

    def test_moving_to_another_window_changes_nothing(self):
        self._text(1000)
        self.app._fg.hwnd_value = 777                      # focus moved
        self.assertFalse(self._enter(1200))
        self.assertEqual(self.app._machine.pending_count, 0)


class NativeModeProcessPolicyTest(NativeModeTest):
    """旧設定 "process" でも同じ: 推測で変換オンの Enter を奪わない（v2-y）."""

    policy = "process"


class NativeModeOffTest(_ImeNativeBase):
    """日本語変換オフ（英数）: 従来どおり Enter を数える（改行/送信が効く）."""

    def setUp(self):
        super().setUp()
        from enter_router.platform import ime as ime_mod
        ime_mod.query_composition = lambda hwnd: ImeState(
            composing=False, source="ime_alnum")

    def test_typing_does_not_prevent_the_router_from_counting(self):
        self._text(1000)
        self.assertTrue(self._enter(1200))                 # counted, as before
        self.assertEqual(self.app._machine.pending_count, 1)


if __name__ == "__main__":
    unittest.main()
