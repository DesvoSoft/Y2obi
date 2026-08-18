"""Tests for app.binaries — where the app looks for the binaries it ships.

Getting this order wrong does not crash; it quietly runs a *different* ffmpeg or
whisper from the one that was pinned and shipped, which is the exact class of
difference behind "works on my machine". Hence tests rather than trust.

Run: python -m unittest discover tests
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
# `unittest discover tests` imports these as top-level modules, so the
# package __init__ does not run on its own.
import tests  # noqa: E402,F401

from app import binaries  # noqa: E402


class ResolutionOrder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self._env = dict(os.environ)
        self._meipass = getattr(sys, "_MEIPASS", None)
        self._core = binaries._get_core_dir

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        binaries._get_core_dir = self._core
        if self._meipass is None:
            if hasattr(sys, "_MEIPASS"):
                del sys._MEIPASS
        else:
            sys._MEIPASS = self._meipass
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make(self, *parts):
        path = os.path.join(self.dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
        return path

    def _use_core(self, root):
        binaries._get_core_dir = lambda: os.path.join(root, "core")

    def test_env_override_wins(self):
        pinned = self._make("pinned", "ffmpeg.exe")
        self._make("payload", "core", "ffmpeg.exe")
        sys._MEIPASS = os.path.join(self.dir, "payload")
        os.environ["Y2OBI_FFMPEG"] = pinned
        self.assertEqual(binaries._get_bundled_ffmpeg(), pinned)

    def test_a_dangling_override_is_ignored(self):
        core = self._make("root", "core", "ffmpeg.exe")
        self._use_core(os.path.join(self.dir, "root"))
        os.environ["Y2OBI_FFMPEG"] = os.path.join(self.dir, "gone.exe")
        self.assertEqual(binaries._get_bundled_ffmpeg(), core)

    def test_payload_beats_core(self):
        payload = self._make("payload", "core", "ffmpeg.exe")
        self._make("root", "core", "ffmpeg.exe")
        self._use_core(os.path.join(self.dir, "root"))
        sys._MEIPASS = os.path.join(self.dir, "payload")
        os.environ.pop("Y2OBI_FFMPEG", None)
        self.assertEqual(binaries._get_bundled_ffmpeg(), payload)

    def test_core_beats_path(self):
        # The regression this guards: ffmpeg used to prefer PATH, so a machine
        # with its own ffmpeg ran a different binary from the shipped one.
        core = self._make("root", "core", "ffmpeg.exe")
        self._use_core(os.path.join(self.dir, "root"))
        os.environ.pop("Y2OBI_FFMPEG", None)
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
        self.assertEqual(binaries._get_bundled_ffmpeg(), core)

    def test_falls_back_to_path(self):
        self._use_core(os.path.join(self.dir, "empty"))
        os.environ.pop("Y2OBI_FFMPEG", None)
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
        found = binaries._get_bundled_ffmpeg()
        self.assertEqual(found, shutil.which("ffmpeg"))

    def test_nothing_anywhere_is_none_not_a_guess(self):
        self._use_core(os.path.join(self.dir, "empty"))
        os.environ.pop("Y2OBI_WHISPER", None)
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
        real_which = shutil.which
        shutil.which = lambda *_a, **_k: None
        try:
            self.assertIsNone(binaries.get_whisper_cli())
        finally:
            shutil.which = real_which

    def test_whisper_uses_the_same_order(self):
        name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
        pinned = self._make("pinned", name)
        os.environ["Y2OBI_WHISPER"] = pinned
        self.assertEqual(binaries.get_whisper_cli(), pinned)

    def test_whisper_is_looked_for_inside_core_whisper(self):
        name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
        core = self._make("root", "core", "whisper", name)
        self._use_core(os.path.join(self.dir, "root"))
        os.environ.pop("Y2OBI_WHISPER", None)
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
        self.assertEqual(binaries.get_whisper_cli(), core)


class CoreDir(unittest.TestCase):
    def test_frozen_looks_beside_the_executable(self):
        was = getattr(sys, "frozen", None)
        sys.frozen = True
        try:
            self.assertEqual(binaries._get_core_dir(),
                             os.path.join(os.path.dirname(sys.executable), "core"))
        finally:
            if was is None:
                del sys.frozen
            else:
                sys.frozen = was

    def test_from_source_looks_at_the_repo_root(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(binaries.__file__)))
        self.assertEqual(binaries._get_core_dir(), os.path.join(root, "core"))


class NonWindows(unittest.TestCase):
    def test_ffmpeg_is_never_downloaded_off_windows(self):
        # A Windows build would be useless there; the package manager owns it.
        real_name, real_bundled = os.name, binaries._get_bundled_ffmpeg
        os.name = "posix"
        binaries._get_bundled_ffmpeg = lambda: None
        called = []
        real_dl = binaries._download_ffmpeg
        binaries._download_ffmpeg = lambda *a, **k: called.append(a)
        try:
            self.assertEqual(binaries.ensure_ffmpeg(), "ffmpeg")
            self.assertEqual(called, [])
        finally:
            os.name = real_name
            binaries._get_bundled_ffmpeg = real_bundled
            binaries._download_ffmpeg = real_dl


if __name__ == "__main__":
    unittest.main()
