"""Log retention: the folder must not grow forever (v2-m follow-up).

The rotating handler bounds ONE file (max_bytes x backup_count), but nothing ever
removed the generations themselves. These tests pin the rule: rotated files older
than KEEP_DAYS go, everything else stays, and the file the handler (or
faulthandler) is writing to is never touched.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from enter_router.app import logsetup  # noqa: E402
from enter_router.core.config import LoggingConfig  # noqa: E402

DAY = 86400.0


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, name, age_days):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))
        return path

    def test_old_rotated_generations_are_deleted_and_recent_ones_stay(self):
        old = self.touch("enter-router.log.1", 9)
        old_crash = self.touch("crash.log.1", 9)
        recent = self.touch("enter-router.log.2", 1)
        live = self.touch("enter-router.log", 30)      # live file: never deleted
        removed = logsetup.prune(self.dir, keep_days=7)
        self.assertIn(old, removed)
        self.assertIn(old_crash, removed)
        self.assertTrue(os.path.exists(recent))
        self.assertTrue(os.path.exists(live))

    def test_unrelated_files_are_left_alone(self):
        other = self.touch("ime_check_pids.json", 90)
        logsetup.prune(self.dir, keep_days=7)
        self.assertTrue(os.path.exists(other))

    def test_the_live_crash_log_is_not_removed_while_faulthandler_holds_it(self):
        crash = self.touch("crash.log", 30)
        previous = logsetup._crash_file
        logsetup._crash_file = object()                # pretend it is open
        try:
            logsetup.prune(self.dir, keep_days=7)
        finally:
            logsetup._crash_file = previous
        self.assertTrue(os.path.exists(crash))

    def test_relative_days_are_based_on_the_given_clock(self):
        old = self.touch("enter-router.log.3", 3)
        removed = logsetup.prune(self.dir, keep_days=7,
                                 now=time.time() + 10 * DAY)   # 10 days later
        self.assertIn(old, removed)

    def test_a_missing_folder_is_not_an_error(self):
        self.assertEqual(logsetup.prune(os.path.join(self.dir, "nope")), [])


class VerbosityTests(unittest.TestCase):
    """v3-a: a packaged build keeps lifecycle + failures, not one line per key."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        # a RotatingFileHandler holds the file open on Windows, so close it
        # before the temporary folder goes away, and leave the loggers clean.
        import logging
        root = logging.getLogger(logsetup.LOGGER_NAME)
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        logging.getLogger(logsetup.DECISION_LOGGER_NAME).setLevel(logging.NOTSET)
        # faulthandler keeps crash.log open for the process lifetime
        import faulthandler
        if logsetup._crash_file is not None:
            try:
                faulthandler.disable()
                logsetup._crash_file.close()
            except (OSError, ValueError):
                pass
            logsetup._crash_file = None
        self.tmp.cleanup()

    def read_log(self):
        with open(os.path.join(self.dir, "enter-router.log"), encoding="utf-8") as fh:
            return fh.read()

    def test_auto_is_quiet_in_a_packaged_build_and_full_from_source(self):
        try:
            logsetup.sys.frozen = True          # type: ignore[attr-defined]
            self.assertEqual(logsetup.resolve_verbosity("auto"), "quiet")
        finally:
            del logsetup.sys.frozen             # type: ignore[attr-defined]
        self.assertEqual(logsetup.resolve_verbosity("auto"), "full")

    def test_an_explicit_value_wins_over_the_build_type(self):
        try:
            logsetup.sys.frozen = True          # type: ignore[attr-defined]
            self.assertEqual(logsetup.resolve_verbosity("full"), "full")
        finally:
            del logsetup.sys.frozen             # type: ignore[attr-defined]
        self.assertEqual(logsetup.resolve_verbosity("quiet"), "quiet")

    def test_quiet_keeps_warnings_and_drops_the_per_key_lines(self):
        import logging
        logsetup.setup(LoggingConfig(verbosity="quiet", dir=self.dir), self.dir)
        decision = logging.getLogger(logsetup.DECISION_LOGGER_NAME)
        decision.info("decision=HOLD op=enter2 meaning=send state=HOLDING "
                      "swallow=1 resolved=key:enter count=2 reason=hold_window")
        decision.warning("sink_failed sink=hermes status=error failure=timeout")
        text = self.read_log()
        self.assertIn("sink_failed", text)
        self.assertNotIn("decision=HOLD", text)

    def test_full_keeps_the_per_key_lines(self):
        import logging
        logsetup.setup(LoggingConfig(verbosity="full", dir=self.dir), self.dir)
        logging.getLogger(logsetup.DECISION_LOGGER_NAME).info(
            "decision=DELIVER op=enter meaning=newline state=IDLE swallow=0 "
            "resolved=pass count=1 reason=deadline")
        self.assertIn("decision=DELIVER", self.read_log())


if __name__ == "__main__":
    unittest.main()
