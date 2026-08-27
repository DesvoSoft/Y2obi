"""Tests for app.diagnostics — the always-on log.

The interesting property is not that it writes: it is that it never writes the
session token, and never grows without bound.

Run: python -m unittest discover tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
import tests  # noqa: E402,F401

from app import diagnostics  # noqa: E402


class Scrubbing(unittest.TestCase):
    """The log lives on disk for every run now, so what goes in it matters.

    Werkzeug logs the request line and the page is opened at /?t=<token>, which
    put the credential gating every /api/ route into a plaintext file.
    """

    def test_the_session_token_never_survives(self):
        token = "pkWSKEYFCTFH7jKTOhs4Bf2ie-BgzK6-g8ZlaLEtNdM"
        line = f'127.0.0.1 - - [26/Aug/2026 23:14:15] "GET /?t={token} HTTP/1.1" 200 -'
        out = diagnostics.scrub(line)
        self.assertNotIn(token, out)
        self.assertIn("t=<redacted>", out)

    def test_a_token_in_a_later_parameter_is_caught_too(self):
        out = diagnostics.scrub("GET /api/progress/1?foo=bar&t=" + "A" * 40)
        self.assertNotIn("A" * 40, out)

    def test_the_header_form_is_caught(self):
        out = diagnostics.scrub("X-Y2obi-Token: " + "b" * 43)
        self.assertNotIn("b" * 43, out)

    def test_scrubbing_by_pattern_not_by_value(self):
        """It must redact a token it was never told about.

        Matching the known value would miss anything minted by code that did not
        register it, which is the case the redaction exists for.
        """
        self.assertIn("<redacted>", diagnostics.scrub("/?t=" + "z" * 30))

    def test_ordinary_output_is_left_alone(self):
        for line in ("Downloading 42%", "GET /static/vitra/vitra.min.css",
                     "ffmpeg  C:/x/core/ffmpeg.exe", "t=short"):
            self.assertEqual(diagnostics.scrub(line), line)


class Rotation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_log_")
        self.path = os.path.join(self.dir, "y2obi.log")

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, name))
        os.rmdir(self.dir)

    def test_a_small_log_is_kept(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("keep me")
        diagnostics._rotate(self.path)
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.path + ".1"))

    def test_an_oversized_log_becomes_the_backup(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("x" * (diagnostics.MAX_BYTES + 1))
        diagnostics._rotate(self.path)
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.exists(self.path + ".1"))

    def test_only_one_backup_is_ever_kept(self):
        """Two files, not a directory that grows for the life of the install."""
        for _ in range(3):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("y" * (diagnostics.MAX_BYTES + 1))
            diagnostics._rotate(self.path)
        self.assertEqual(sorted(os.listdir(self.dir)), ["y2obi.log.1"])


class Location(unittest.TestCase):
    def test_the_override_wins(self):
        old = os.environ.get("Y2OBI_LOG_DIR")
        os.environ["Y2OBI_LOG_DIR"] = os.path.join(tempfile.gettempdir(), "y2obi_elsewhere")
        try:
            self.assertTrue(diagnostics.log_dir().endswith("y2obi_elsewhere"))
            self.assertTrue(diagnostics.log_path().endswith(diagnostics.LOG_NAME))
        finally:
            if old is None:
                del os.environ["Y2OBI_LOG_DIR"]
            else:
                os.environ["Y2OBI_LOG_DIR"] = old


if __name__ == "__main__":
    unittest.main()
