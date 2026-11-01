"""日本語変換オンの Enter は IME に渡す — その事実がログに残ること（v2-y）.

Why: 未確定文字列は Chromium/Electron では外から読めない（実測 42 回で 0 回）。
v2-h は「直前の Enter 以降に文字キーを打ったか」で確定か操作かを推測していたが、
それはオペレータの指示ではなく不具合対応で入れたもので、確定 Enter を奪って
変換を壊した（2026-11-01 04:46 に 1 分間で 5 回）。v2-y で推測を削除し、
**変換オンなら常に何もせず IME に渡す**（＝on_ime_commit）にした。

このファイルは「渡したこと」と「そのとき何が見えていたか」をログで確認する。
"""
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from enter_router.app import main as app_main  # noqa: E402
from enter_router.core.config import parse_config_text  # noqa: E402
from enter_router.core.events import ImeState, KeyEvent  # noqa: E402

SAMPLE = REPO / "config" / "sample.config.json"
LOGGER = "enter_router.app"
VK_A = 0x41
VK_RETURN = 0x0D


def enter(t_ms=1000):
    return KeyEvent(vk=VK_RETURN, kind="down", t_ms=t_ms,
                    ctrl=False, alt=False, shift=False, win=False,
                    injected=False, os_repeat=False)


def letter(t_ms=900):
    return KeyEvent(vk=VK_A, kind="down", t_ms=t_ms,
                    ctrl=False, alt=False, shift=False, win=False,
                    injected=False, os_repeat=False)


class ImePassthroughLogTests(unittest.TestCase):
    """変換オン → 常に素通し。設定値に左右されない（v2-y）."""

    def setUp(self):
        self.cfg = parse_config_text(SAMPLE.read_text(encoding="utf-8"))
        self.app = app_main.EnterRouterApp(self.cfg, str(SAMPLE))
        self.app._hook_thread = None
        self.patch = mock.patch(
            "enter_router.platform.ime.query_composition",
            return_value=ImeState(composing=None, source="ime_native",
                                  detail="ime_mode=(True, 9); tsf: composition=0"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_a_bare_enter_is_handed_to_the_ime(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(self.app._decide(enter()))
        line = next((l for l in logs.output if "ime_passthrough" in l), "")
        self.assertTrue(line, logs.output)
        self.assertIn("text_count=0", line)
        self.assertIn("source=ime_native", line)
        self.assertIn("profile=", line)

    def test_typing_before_the_enter_is_also_handed_over(self):
        self.app._decide(letter())
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(self.app._decide(enter(t_ms=1200)))
        line = next((l for l in logs.output if "ime_passthrough" in l), "")
        self.assertTrue(line, logs.output)
        self.assertIn("text_count=1", line)

    def test_the_old_policy_switch_cannot_bring_the_guessing_back(self):
        """v2-y: ime_unknown_policy が "process" でも変換オンの Enter は渡す."""
        cfg = replace(self.cfg, ime_unknown_policy="process")
        app = app_main.EnterRouterApp(cfg, str(SAMPLE))
        app._hook_thread = None
        try:
            self.assertFalse(app._decide(enter()))
            self.assertEqual(app._machine.pending_count, 0)
        finally:
            app._timer.stop()


if __name__ == "__main__":
    unittest.main()
