"""Tests for app.cleanup — the sweep must be aggressive about our own leftovers
and completely inert about everyone else's.

Run: python -m unittest discover tests
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
# `unittest discover tests` imports these as top-level modules, so the
# package __init__ does not run on its own.
import tests  # noqa: E402,F401

from app import cleanup


class Sweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="y2obi_sweeproot_")
        self._real_gettempdir = tempfile.gettempdir
        tempfile.gettempdir = lambda: self.tmp

    def tearDown(self):
        tempfile.gettempdir = self._real_gettempdir
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mei(self, name, ours=True):
        d = os.path.join(self.tmp, name)
        if ours:
            for marker in cleanup._MEI_MARKERS:
                path = os.path.join(d, marker)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(b"x" * 32)
        else:
            os.makedirs(os.path.join(d, "some_other_app"), exist_ok=True)
        return d

    def test_our_own_payload_is_removed(self):
        d = self._mei("_MEI12345")
        removed, freed = cleanup.sweep_temp(min_age_s=0)
        self.assertEqual(removed, 1)
        self.assertGreater(freed, 0)
        self.assertFalse(os.path.exists(d))

    def test_another_frozen_app_is_never_touched(self):
        # The markers are what prove a payload is ours; without them, hands off.
        d = self._mei("_MEI99999", ours=False)
        cleanup.sweep_temp(min_age_s=0)
        self.assertTrue(os.path.exists(d))

    def test_unrelated_directories_are_never_touched(self):
        d = os.path.join(self.tmp, "important_user_data")
        os.makedirs(d)
        cleanup.sweep_temp(min_age_s=0)
        self.assertTrue(os.path.exists(d))

    def test_our_work_dirs_are_removed(self):
        d = os.path.join(self.tmp, "y2obi_src_abc")
        os.makedirs(d)
        cleanup.sweep_temp(min_age_s=0)
        self.assertFalse(os.path.exists(d))

    def test_recent_leftovers_are_left_alone(self):
        # A sibling instance that just started must not have its dir yanked.
        d = os.path.join(self.tmp, "y2obi_src_new")
        os.makedirs(d)
        removed, _ = cleanup.sweep_temp(min_age_s=3600)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.exists(d))

    def test_a_directory_in_use_survives(self):
        d = os.path.join(self.tmp, "y2obi_src_busy")
        os.makedirs(d)
        held = open(os.path.join(d, "open.bin"), "wb")
        try:
            cleanup.sweep_temp(min_age_s=0)
            self.assertTrue(os.path.exists(d))
        finally:
            held.close()

    def test_the_live_payload_is_skipped(self):
        d = self._mei("_MEI_live")
        sys._MEIPASS = d
        try:
            cleanup.sweep_temp(min_age_s=0)
            self.assertTrue(os.path.exists(d))
        finally:
            del sys._MEIPASS


class Partials(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reports_size_by_model_filename(self):
        with open(os.path.join(self.dir, "ggml-small.bin.part"), "wb") as f:
            f.write(b"x" * 4096)
        with open(os.path.join(self.dir, "ggml-tiny.bin"), "wb") as f:
            f.write(b"x" * 10)
        found = cleanup.partial_downloads(self.dir)
        self.assertEqual(found, {"ggml-small.bin": 4096})

    def test_missing_directory_is_not_an_error(self):
        self.assertEqual(cleanup.partial_downloads(os.path.join(self.dir, "nope")), {})


if __name__ == "__main__":
    unittest.main()
