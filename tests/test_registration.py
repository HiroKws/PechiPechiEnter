"""Registration hotkeys (v2-g): Alt+F5 / Alt+F6 write a profile for the front app.

These run the real composition root (``app.main.EnterRouterApp``) against a real
config file in a temp dir, with the Windows effects replaced by recorders — the
same trick ``test_app_safety`` uses. What is proven here:

* the combo is recognised from the config (not hard-coded);
* a profile is appended to the LIVE config file and applied without a restart;
* "process only" stores just the exe, "process + title" also stores the window
  title as a LITERAL glob (metacharacters escaped);
* registering the same thing twice does not append a duplicate;
* a held Enter is delivered BEFORE the write (I6 ordering);
* the key itself is swallowed and never reaches the policy machine.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from enter_router.app import main as app_main  # noqa: E402
from enter_router.core.config import (ConfigError, parse_config,  # noqa: E402
                                      parse_config_text)
from enter_router.core.events import VK_RETURN, ForegroundInfo, KeyEvent  # noqa: E402

SAMPLE = REPO / "config" / "sample.config.json"
VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76


class _StaticFg:
    def __init__(self, info: ForegroundInfo) -> None:
        self._info = info

    def snapshot(self):
        return self._info.hwnd, self._info

    def hwnd(self) -> int:
        return self._info.hwnd

    def get(self) -> ForegroundInfo:
        return self._info


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        import logging
        logging.disable(logging.CRITICAL)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"
        self.path.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        self.cfg = parse_config_text(self.path.read_text(encoding="utf-8"))
        self.notes: list[tuple[str, str, str]] = []
        self.actions: list[str] = []
        self.injected: list[tuple] = []

        from enter_router.platform import hook as hook_mod
        from enter_router.platform import ime as ime_mod
        from enter_router.platform import inject
        from enter_router.core.events import ImeState
        self._saved = (hook_mod.request_stop, hook_mod.wake, inject.send_combo,
                       inject.send_enter, ime_mod.query_composition)
        hook_mod.request_stop = lambda reason="stop": None
        hook_mod.wake = lambda: False
        inject.send_combo = lambda combo, held=(): self.injected.append(("combo", combo)) or 4
        inject.send_enter = lambda copies, held=(): self.injected.append(("enter", copies)) or 2
        ime_mod.query_composition = lambda hwnd: ImeState(composing=False)

        self.app = app_main.EnterRouterApp(self.cfg, str(self.path))
        self.app._notify = lambda title, body, level="info", action="": (
            self.notes.append((title, body, level)), self.actions.append(action))
        self.app._fg = _StaticFg(ForegroundInfo(
            process_name=r"C:\Program Files\Mozilla Firefox\firefox.exe",
            window_title="Report [draft] * 2", url=None, hwnd=1234))

    def tearDown(self):
        import logging
        from enter_router.platform import hook as hook_mod
        from enter_router.platform import ime as ime_mod
        from enter_router.platform import inject
        (hook_mod.request_stop, hook_mod.wake, inject.send_combo,
         inject.send_enter, ime_mod.query_composition) = self._saved
        self.app._timer.stop()
        logging.disable(logging.NOTSET)
        self.tmp.cleanup()

    # -- helpers ----------------------------------------------------------
    def _doc(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _press(self, vk: int, alt: bool = True, t: int = 1000) -> bool:
        return self.app._decide(KeyEvent(vk=vk, kind="down", t_ms=t, alt=alt))

    # -- the two combos ---------------------------------------------------
    def test_process_only_registration_writes_and_applies_a_profile(self):
        swallowed = self._press(VK_F5)
        self.assertTrue(swallowed)                       # the hotkey is ours
        profiles = self._doc()["profiles"]
        self.assertEqual(len(profiles), 4)               # site-a, site-b, excel + new
        new = profiles[-1]
        self.assertEqual(new["match"], {"process": "firefox.exe"})
        self.assertEqual(new["keymap"], {"send": "enter", "newline": "shift+enter"})
        self.assertTrue(new["enabled"])
        # applied live: the file reloads to a config that contains it
        parsed = parse_config(self._doc())
        self.assertIn(new["id"], [p.id for p in parsed.profiles])
        self.assertTrue(any("登録しました" in body for _t, body, _l in self.notes))

    def test_process_and_title_registration_escapes_the_title(self):
        self._press(VK_F6)
        new = self._doc()["profiles"][-1]
        self.assertEqual(new["match"]["process"], "firefox.exe")
        # the title is DATA: glob metacharacters must not become wildcards
        self.assertEqual(new["match"]["title"], "Report [[]draft] [*] 2")

    def test_the_registered_profile_then_matches_that_window(self):
        self._press(VK_F6)
        cfg = parse_config(self._doc())
        from enter_router.core import routing
        same = ForegroundInfo(process_name="firefox.exe",
                              window_title="Report [draft] * 2")
        other = ForegroundInfo(process_name="firefox.exe", window_title="Other window")
        self.assertIsNotNone(routing.match_profile(cfg, same))
        self.assertIsNone(routing.match_profile(cfg, other))

    # -- v2-o: process + site (URL host) ----------------------------------
    def _browser(self, url: str | None) -> None:
        self.app._fg = _StaticFg(ForegroundInfo(
            process_name="firefox.exe", window_title="Greeting - Claude — Mozilla Firefox",
            url=url, hwnd=1234))

    def test_process_and_url_registration_stores_only_the_host(self):
        self._browser("https://claude.ai/chat/5f3c1a?model=x")
        self.assertTrue(self._press(VK_F7))
        new = self._doc()["profiles"][-1]
        # the host alone: an SPA's path changes on every conversation
        self.assertEqual(new["match"], {"process": "firefox.exe", "url": "*://claude.ai*"})
        self.assertEqual(new["id"], "claude-ai")     # named after the site, not the exe
        self.assertNotIn("title", new["match"])      # the window is not part of the rule
        self.assertTrue(any("登録しました" in body for _t, body, _l in self.notes))

    def test_the_site_profile_matches_every_path_of_that_site_only(self):
        self._browser("https://claude.ai/chat/5f3c1a")
        self._press(VK_F7)
        cfg = parse_config(self._doc())
        from enter_router.core import routing
        same_site = ForegroundInfo(process_name="firefox.exe", window_title="any",
                                   url="https://claude.ai/settings")
        other_site = ForegroundInfo(process_name="firefox.exe", window_title="any",
                                    url="https://example.com/chat")
        lookalike = ForegroundInfo(process_name="firefox.exe", window_title="any",
                                   url="https://notclaude.ai/chat")
        self.assertIsNotNone(routing.match_profile(cfg, same_site))
        self.assertIsNone(routing.match_profile(cfg, other_site))
        self.assertIsNone(routing.match_profile(cfg, lookalike))

    def test_url_registration_waits_for_the_poller_instead_of_guessing(self):
        """v2-r: URL not read yet -> finish in the background, not "press again"."""
        # the poller has not reached this window yet (fgcache reports None)
        self._browser(None)
        self.assertTrue(self._press(VK_F7))          # still swallowed
        self.assertEqual(len(self._doc()["profiles"]), 3)   # nothing written yet
        self.assertTrue(any("URL を読み直しています" in body for _t, body, _l in self.notes))
        # the poller catches up a moment later -> the worker registers the site
        self._browser("https://www.facebook.com")
        self.app._await_site_url("firefox.exe", timeout_s=1.0)
        new = self._doc()["profiles"][-1]
        self.assertEqual(new["match"], {"process": "firefox.exe",
                                        "url": "*://www.facebook.com*"})
        self.assertTrue(any("登録しました" in body for _t, body, _l in self.notes))

    def test_a_url_that_never_arrives_is_reported_not_invented(self):
        self._browser(None)
        self._press(VK_F7)
        self.app._await_site_url("firefox.exe", timeout_s=0.2)
        self.assertEqual(len(self._doc()["profiles"]), 3)
        self.assertTrue(any("URL を読めませんでした" in body for _t, body, _l in self.notes))

    def test_a_non_browser_cannot_register_a_site(self):
        self.app._fg = _StaticFg(ForegroundInfo(process_name="notepad.exe",
                                                window_title="Untitled", url=None))
        self._press(VK_F7)
        self.assertEqual(len(self._doc()["profiles"]), 3)
        self.assertTrue(any("ブラウザでのみ読めます" in body for _t, body, _l in self.notes))

    def test_url_registration_is_not_duplicated(self):
        self._browser("https://claude.ai/chat/one")
        self._press(VK_F7, t=1000)
        before = self._doc()["profiles"]
        self._browser("https://claude.ai/chat/two")   # another page, same site
        self._press(VK_F7, t=2000)
        self.assertEqual(self._doc()["profiles"], before)
        self.assertTrue(any("既に登録済み" in body for _t, body, _l in self.notes))

    def test_the_three_registration_keys_must_differ(self):
        doc = self._doc()
        doc["registration"]["process_url_key"] = "alt+f5"     # same as process_key
        with self.assertRaises(ConfigError):
            parse_config(doc)

    def test_an_empty_registration_key_is_accepted_and_means_unset(self):
        """v2-p: a cleared field switches the hotkey OFF instead of erroring."""
        doc = self._doc()
        doc["registration"]["process_url_key"] = ""
        cfg = parse_config(doc)
        self.assertEqual(cfg.registration.process_url_key, "")
        self.assertEqual(cfg.registration.process_key, "alt+f5")   # the others stay

    def test_two_empty_registration_keys_are_not_a_collision(self):
        doc = self._doc()
        doc["registration"]["process_title_key"] = ""
        doc["registration"]["process_url_key"] = "   "              # whitespace too
        cfg = parse_config(doc)
        self.assertEqual(cfg.registration.process_title_key, "")
        self.assertEqual(cfg.registration.process_url_key, "")

    def test_an_unset_key_is_an_ordinary_key(self):
        """The key that used to register now passes through to the app."""
        doc = self._doc()
        doc["registration"]["process_url_key"] = ""
        self.app._apply_config(parse_config(doc))
        self._browser("https://claude.ai/chat/one")
        self.assertFalse(self._press(VK_F7))         # NOT swallowed any more
        self.assertEqual(len(self._doc()["profiles"]), 3)

    def test_a_successful_registration_points_the_toast_at_the_profile_tab(self):
        """v2-s/v2-t: clicking the toast lands on タブB with THAT profile selected."""
        self._press(VK_F5)
        self.assertTrue(any("登録しました" in body for _t, body, _l in self.notes))
        self.assertIn("profiles:firefox", self.actions)

    def test_registration_is_not_duplicated(self):
        self._press(VK_F5, t=1000)
        before = self._doc()["profiles"]
        self._press(VK_F5, t=2000)
        self.assertEqual(self._doc()["profiles"], before)
        self.assertTrue(any("既に登録済み" in body for _t, body, _l in self.notes))

    def test_two_registrations_get_distinct_ids(self):
        self._press(VK_F5, t=1000)
        self._press(VK_F6, t=2000)
        ids = [p["id"] for p in self._doc()["profiles"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[-2:], ["firefox", "firefox-2"])

    # -- ordering + safety ------------------------------------------------
    def test_a_held_enter_is_delivered_before_the_write(self):
        # a site-a window, so the held Enter resolves to that profile's newline
        self.app._fg = _StaticFg(ForegroundInfo(
            process_name="firefox.exe", window_title="Site A",
            url="https://site-a.example.com/chat", hwnd=1234))
        self.app._decide(KeyEvent(vk=VK_RETURN, kind="down", t_ms=1000))
        self.assertEqual(self.injected, [])              # held, nothing sent yet
        self._press(VK_F5, t=1100)
        self.assertEqual(self.injected, [("combo", "shift+enter")])
        self.assertEqual(len(self._doc()["profiles"]), 4)

    def test_the_hotkey_never_reaches_the_policy_machine(self):
        before = self.app._machine.state
        self._press(VK_F5)
        self.assertIs(self.app._machine.state, before)
        self.assertEqual(self.injected, [])

    def test_a_plain_f5_is_not_a_registration(self):
        self.assertFalse(self._press(VK_F5, alt=False))
        self.assertEqual(len(self._doc()["profiles"]), 3)

    def test_an_unreadable_foreground_is_reported_not_written(self):
        self.app._fg = _StaticFg(ForegroundInfo(process_name="", window_title=""))
        self.assertTrue(self._press(VK_F5))              # still swallowed
        self.assertEqual(len(self._doc()["profiles"]), 3)
        self.assertTrue(any("登録できませんでした" in body for _t, body, _l in self.notes))

    def test_registration_does_not_resurrect_a_deleted_profile(self):
        """The write starts from the FILE, never from this process's snapshot.

        Reported on hardware: profiles deleted in the settings window came back
        the next time anything wrote the config — a registration hotkey rewrote
        the whole document from a stale in-memory copy. Only the file on disk is
        allowed to be the base document.
        """
        doc = self._doc()
        doc["profiles"] = [p for p in doc["profiles"] if p["id"] != "excel"]
        self.path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        # this process still holds the old document (excel included)
        self.assertEqual([p.id for p in self.cfg.profiles], ["site-a", "site-b", "excel"])

        self._press(VK_F5)

        ids = [p["id"] for p in self._doc()["profiles"]]
        self.assertEqual(ids, ["site-a", "site-b", "firefox"])   # excel stays deleted


if __name__ == "__main__":
    unittest.main()
