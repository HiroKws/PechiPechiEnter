"""Tray UI (``ui/tray.py``): state visibility, one-click panic, safe on Linux.

The Win32 calls themselves are exercised on Windows by ``scripts/win_ui_check.py``
(a real icon + a real message loop); here we test the pure parts that decide what
the user sees, plus the fact that importing the module touches no Windows API.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from enter_router.ui import tray  # noqa: E402


class MenuTests(unittest.TestCase):
    def test_panic_is_the_first_item_and_reachable_in_one_click(self):
        items = tray.menu_items("running")
        self.assertEqual(items[0].command, "panic")
        self.assertTrue(items[0].enabled)
        self.assertIn("パニック停止", items[0].label)

    def test_menu_contains_every_required_entry(self):
        commands = [item.command for item in tray.menu_items("running")]
        self.assertEqual(commands, ["panic", "settings", "toggle", "logs", "quit"])

    def test_panic_item_is_greyed_once_panicked_but_still_visible(self):
        items = {item.command: item for item in tray.menu_items("panic")}
        self.assertIn("panic", items)                  # never silently disappears
        self.assertFalse(items["panic"].enabled)

    def test_toggle_label_follows_the_state(self):
        self.assertEqual({i.command: i for i in tray.menu_items("running")}["toggle"].label,
                         "一時停止")
        self.assertEqual({i.command: i for i in tray.menu_items("busy")}["toggle"].label,
                         "一時停止")
        self.assertEqual({i.command: i for i in tray.menu_items("paused")}["toggle"].label,
                         "再開")
        self.assertEqual({i.command: i for i in tray.menu_items("panic")}["toggle"].label,
                         "再開")
        self.assertFalse({i.command: i for i in tray.menu_items("panic")}["toggle"].enabled)

    def test_menu_ids_map_back_to_commands(self):
        for index, item in enumerate(tray.menu_items("running"), start=1):
            self.assertEqual(tray.command_for_id(index), item.command)
        self.assertEqual(tray.command_for_id(0), "")
        self.assertEqual(tray.command_for_id(99), "")


class StatePresentationTests(unittest.TestCase):
    def test_every_state_has_a_japanese_text_and_a_distinct_colour(self):
        colours = set()
        for state in tray.STATE_ORDER:
            self.assertTrue(tray.state_text(state))
            colours.add(tray.state_color(state))
        self.assertEqual(len(colours), len(tray.STATE_ORDER))

    def test_state_texts_cover_the_controller_states(self):
        for state in ("running", "paused", "panic", "busy"):
            self.assertIn(state, tray.STATE_TEXTS)
        self.assertEqual(tray.state_text("running"), "有効")
        self.assertEqual(tray.state_text("paused"), "一時停止")
        self.assertEqual(tray.state_text("panic"), "パニック停止中")

    def test_tooltip_shows_state_warnings_and_last_error(self):
        text = tray.status_tooltip("paused", config_path=r"C:\cfg\config.json",
                                   warnings=2, last_error="sink: timeout")
        self.assertIn("一時停止", text)
        self.assertIn("config.json", text)
        self.assertIn("警告 2 件", text)
        self.assertIn("timeout", text)
        self.assertLessEqual(len(text), 127)

    def test_tooltip_is_truncated_to_the_shell_limit(self):
        text = tray.status_tooltip("running", config_path="C:\\" + "x" * 400)
        self.assertLessEqual(len(text), 127)


class PlatformSafetyTests(unittest.TestCase):
    def test_import_does_not_touch_win32(self):
        # Importing must be side-effect free; the API object is built lazily.
        self.assertIsNone(tray._api)
        self.assertIsNone(tray._instance)

    def test_tray_unavailable_off_windows_and_start_fails_softly(self):
        if sys.platform == "win32":
            self.skipTest("Windows: exercised for real by scripts/win_ui_check.py")
        self.assertFalse(tray.tray_available())
        icon = tray.TrayIcon(on_command=lambda _c: None)
        self.assertFalse(icon.start(timeout=0.1))
        self.assertIn("Windows", icon.error)
        self.assertEqual(icon.hwnd, 0)

    def test_post_open_settings_is_a_no_op_off_windows(self):
        if sys.platform == "win32":
            self.skipTest("Windows: covered by scripts/win_ui_check.py")
        self.assertFalse(tray.post_open_settings())
        self.assertIsNone(tray._api)          # still never touched Win32


class BalloonClickTests(unittest.TestCase):
    """v2-s: a clicked notification opens the place it refers to.

    The Win32 side (Shell_NotifyIcon -> NIN_BALLOONUSERCLICK) is exercised for
    real on Windows; what is asserted here is the routing that turns the click
    into "settings window, profile tab".
    """

    class _Controller:
        def __init__(self, action: str) -> None:
            self.action = action
            self.taken = 0

        def take_notification_action(self) -> str:
            self.taken += 1
            action, self.action = self.action, ""
            return action

        def get_status(self):
            return None

    def _runtime(self, action, controller=None):
        from enter_router.ui import runtime as runtime_mod
        controller = controller if controller is not None else self._Controller(action)
        rt = runtime_mod.UiRuntime(controller)
        calls: list = []
        rt.open_settings = lambda tab=None, focus=None: calls.append((tab, focus))  # type: ignore[assignment]
        return rt, controller, calls

    def test_a_clicked_registration_toast_opens_the_profile_tab(self):
        rt, controller, calls = self._runtime("profiles:claude-ai")
        rt.handle_command("balloon")
        self.assertEqual(calls, [("profiles", "claude-ai")])
        self.assertEqual(controller.taken, 1)

    def test_the_action_is_consumed_not_reused(self):
        rt, controller, calls = self._runtime("profiles:claude-ai")
        rt.handle_command("balloon")
        rt.handle_command("balloon")
        self.assertEqual(calls, [("profiles", "claude-ai"), (None, None)])

    def test_a_tab_without_a_focus_id_just_selects_the_tab(self):
        rt, _controller, calls = self._runtime("profiles")
        rt.handle_command("balloon")
        self.assertEqual(calls, [("profiles", None)])

    def test_a_clicked_toast_without_an_action_just_opens_settings(self):
        rt, _controller, calls = self._runtime("")
        rt.handle_command("balloon")
        self.assertEqual(calls, [(None, None)])

    def test_an_older_controller_without_the_method_still_opens_settings(self):
        rt, _controller, calls = self._runtime("", controller=object())
        rt.handle_command("balloon")
        self.assertEqual(calls, [(None, None)])

    def test_the_tab_names_resolve_to_real_tabs(self):
        from enter_router.ui import settings as ui_settings
        self.assertEqual(ui_settings.TAB_BY_NAME["profiles"], "tab_b")
        self.assertEqual(ui_settings.TAB_BY_NAME["operations"], "tab_a")
        self.assertEqual(ui_settings.TAB_BY_NAME["test"], "tab_c")


class IconAssetTests(unittest.TestCase):
    """v2-u: the icons are drawn by scripts/make_icon.py and committed."""

    def test_every_state_has_a_committed_icon(self):
        for state in tray.STATE_ORDER:
            path = tray.icon_path(state)
            self.assertTrue(path.exists(), path)
            self.assertGreater(path.stat().st_size, 500, path)

    def test_the_app_icon_is_committed(self):
        self.assertTrue((tray.ASSET_DIR / "enter-router.ico").exists())

    def test_the_files_are_real_windows_icons(self):
        for state in tray.STATE_ORDER:
            head = tray.icon_path(state).read_bytes()[:4]
            self.assertEqual(head, b"\x00\x00\x01\x00", state)   # ICO magic

    def test_the_state_colours_are_the_tray_colours(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "make_icon", tray.ASSET_DIR.parents[2] / "scripts" / "make_icon.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)          # type: ignore[union-attr]
        for state, rgb in module.STATE_RGB.items():
            colorref = tray.state_color(state)
            expected = (colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF)
            self.assertEqual(rgb, expected, state)

    def test_the_16px_stroke_stays_thin_enough(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "make_icon", tray.ASSET_DIR.parents[2] / "scripts" / "make_icon.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)          # type: ignore[union-attr]
        # 3 px of a 16 px canvas closed the elbow gap (measured) — keep it at 2
        self.assertEqual(module.stroke_width(16), 2)
        self.assertGreaterEqual(module.stroke_width(256), 20)


if __name__ == "__main__":
    unittest.main()
