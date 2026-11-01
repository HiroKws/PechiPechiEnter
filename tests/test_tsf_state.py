"""tsf_state の解析（純粋部分）と、ルーターが TSF の状態をどう使うかのテスト."""
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from enter_router.app import main as app_main                  # noqa: E402
from enter_router.core import tsf_state                        # noqa: E402
from enter_router.core.config import parse_config_text         # noqa: E402
from enter_router.core.events import (VK_RETURN, ForegroundInfo,  # noqa: E402
                                      ImeState, KeyEvent)
from enter_router.core.policy import State                     # noqa: E402

SAMPLE = REPO / "config" / "sample.config.json"
VK_A = 0x41
_SITE_A = ForegroundInfo(process_name="firefox.exe", window_title="Site A",
                         url="https://site-a.example.com/chat")


def make_buf(entries, magic: int = tsf_state.MAGIC) -> bytes:
    buf = bytearray(tsf_state.SIZE)
    tsf_state.HEAD.pack_into(buf, 0, magic, 0)
    for i, (tid, composing, tick, seq) in enumerate(entries):
        tsf_state.SLOT.pack_into(buf, tsf_state.HEAD.size + i * tsf_state.SLOT.size,
                                 tid, 1 if composing else 0, tick, seq)
    return bytes(buf)


class ParseTests(unittest.TestCase):
    def test_composing_true_and_false(self):
        buf = make_buf([(100, True, 5000, 1), (200, False, 5000, 1)])
        self.assertIs(tsf_state.composing_for(buf, 100, 5050), True)
        self.assertIs(tsf_state.composing_for(buf, 200, 5050), False)

    def test_unknown_thread_is_none(self):
        buf = make_buf([(100, True, 5000, 1)])
        self.assertIsNone(tsf_state.composing_for(buf, 999, 5050))

    def test_stale_record_is_none(self):
        buf = make_buf([(100, True, 5000, 1)])
        self.assertIsNone(tsf_state.composing_for(buf, 100, 5000 + 900))

    def test_clock_jump_backwards_is_none(self):
        buf = make_buf([(100, True, 5000, 1)])
        self.assertIsNone(tsf_state.composing_for(buf, 100, 1000))

    def test_bad_magic_is_none(self):
        buf = make_buf([(100, True, 5000, 1)], magic=0)
        self.assertIsNone(tsf_state.composing_for(buf, 100, 5000))

    def test_short_buffer_is_none(self):
        self.assertIsNone(tsf_state.composing_for(b"\x00" * 8, 100, 5000))

    def test_empty_slot_is_ignored(self):
        _updated, slots = tsf_state.parse(make_buf([(100, True, 5000, 1)]))
        self.assertEqual(sorted(slots), [100])


class _StaticFg:
    def __init__(self, info):
        self._info = info
        self.hwnd_value = 42

    def hwnd(self):
        return self.hwnd_value

    def snapshot(self):
        return self.hwnd_value, self._info

    def current(self):
        return self._info

    def start(self):
        return None

    def stop(self):
        return None


class RouterUsesTsfStateTest(unittest.TestCase):
    """TSF の状態が読めるときは、推測せずにそれで決める（v2-z）."""

    def setUp(self):
        self.cfg = parse_config_text(SAMPLE.read_text(encoding="utf-8"))
        self.app = app_main.EnterRouterApp(self.cfg, str(SAMPLE))
        self.app._hook_thread = None
        from enter_router.platform import hook as hook_mod
        from enter_router.platform import ime as ime_mod
        from enter_router.platform import inject
        self.sent = []
        self._saved = (ime_mod.query_composition, inject.send_combo,
                       inject.send_enter, hook_mod.wake, hook_mod.request_stop)
        # IMM 側は「読めない」にしておく（TSF の状態だけで決まることを見る）
        ime_mod.query_composition = lambda hwnd: ImeState(
            composing=None, source="ime_native", detail="ime_mode=(True, 9)")
        inject.send_combo = lambda combo, held=(): self.sent.append(("combo", combo)) or 4
        inject.send_enter = lambda n, held=(): self.sent.append(("enter", n)) or 2 * n
        hook_mod.wake = lambda: False
        hook_mod.request_stop = lambda reason="stop": None
        self.app._fg = _StaticFg(_SITE_A)
        self.state = None
        self.patch = mock.patch("enter_router.platform.tsf_state.composing",
                               side_effect=lambda hwnd, **kw: self.state)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        from enter_router.platform import hook as hook_mod
        from enter_router.platform import ime as ime_mod
        from enter_router.platform import inject
        (ime_mod.query_composition, inject.send_combo, inject.send_enter,
         hook_mod.wake, hook_mod.request_stop) = self._saved
        self.app._timer.stop()

    def _enter(self, t=1200):
        swallowed = self.app._decide(KeyEvent(vk=VK_RETURN, kind="down", t_ms=t))
        self.app._decide(KeyEvent(vk=VK_RETURN, kind="up", t_ms=t + 20))
        return swallowed

    def _text(self, t=1000):
        self.app._decide(KeyEvent(vk=VK_A, kind="down", t_ms=t))
        self.app._decide(KeyEvent(vk=VK_A, kind="up", t_ms=t + 20))

    def test_composing_passes_the_enter_through(self):
        """日本語入力中（composing=1）は何もせず IME に渡す."""
        self.state = True
        self._text()
        self.assertFalse(self._enter())
        self.assertEqual(self.app._machine.pending_count, 0)
        self.assertEqual(self.sent, [])

    def test_not_composing_routes_by_enter_count(self):
        """確定後・未入力（composing=0）は回数で振り分ける（ここでは1回=保留）."""
        self.state = False
        self._text()
        self.assertTrue(self._enter())                    # 飲み込んで保留
        self.assertEqual(self.app._machine.pending_count, 1)

    def test_two_presses_after_commit_are_a_send(self):
        self.state = False
        self._text()
        self.assertTrue(self._enter(1200))
        self.assertTrue(self._enter(1300))
        out = self.app._machine.on_deadline(1300 + self.cfg.policy.triple_enter_window_ms)
        self.app._execute(out, None)
        self.assertIn("combo", [s[0] for s in self.sent] or [""])

    def test_missing_tsf_state_falls_back_to_passing(self):
        """er_tip が無い/古い（None）ときは安全側: 何もせず渡す."""
        self.state = None
        self._text()
        self.assertFalse(self._enter())
        self.assertEqual(self.app._machine.pending_count, 0)
        self.assertEqual(self.sent, [])

    def test_alnum_without_tsf_state_still_counts(self):
        """日本語入力オフなら TSF が無くても従来どおり数える."""
        from enter_router.platform import ime as ime_mod
        ime_mod.query_composition = lambda hwnd: ImeState(composing=False,
                                                          source="ime_alnum")
        self.state = None
        self._text()
        self.assertTrue(self._enter())
        self.assertEqual(self.app._machine.pending_count, 1)


if __name__ == "__main__":
    unittest.main()
