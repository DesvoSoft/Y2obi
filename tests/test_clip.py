"""Tests for trimming a download to a section.

The failure worth preventing is silent: a mistyped time that parses anyway
downloads the wrong five minutes of a three-hour video, and nothing about the
result says so. Everything here is about refusing rather than guessing.

Run: python -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests  # noqa: E402,F401

from app import server as srv  # noqa: E402
from app.downloader import ClipError, clip_label, parse_clip, parse_timecode  # noqa: E402


class Timecodes(unittest.TestCase):
    def test_the_forms_people_actually_type(self):
        self.assertEqual(parse_timecode("90"), 90)
        self.assertEqual(parse_timecode("1:30"), 90)
        self.assertEqual(parse_timecode("01:30"), 90)
        self.assertEqual(parse_timecode("1:02:03"), 3723)

    def test_blank_means_unset_rather_than_zero(self):
        for text in (None, "", "   "):
            self.assertIsNone(parse_timecode(text))

    def test_an_overflowing_field_is_refused(self):
        """"1:75" is a typo, not 2m15s. Reading it as one shifts the whole clip."""
        for text in ("1:75", "1:60", "1:00:99"):
            with self.assertRaises(ClipError, msg=text):
                parse_timecode(text)

    def test_the_leading_field_may_be_large(self):
        """90 minutes into a long video is a normal thing to ask for."""
        self.assertEqual(parse_timecode("90:00"), 5400)

    def test_junk_is_refused(self):
        for text in ("abc", "1:2:3:4", "1.30", "-5", "1:ab"):
            with self.assertRaises(ClipError, msg=text):
                parse_timecode(text)


class Ranges(unittest.TestCase):
    def test_both_ends_given(self):
        self.assertEqual(parse_clip("12:30", "18:45"), (750, 1125))

    def test_neither_given_means_the_whole_video(self):
        self.assertIsNone(parse_clip("", ""))
        self.assertIsNone(parse_clip(None, None))

    def test_a_missing_start_means_the_beginning(self):
        start, end = parse_clip("", "30")
        self.assertEqual(start, 0)
        self.assertEqual(end, 30)

    def test_a_missing_end_means_the_rest_of_it(self):
        start, end = parse_clip("1:00", "")
        self.assertEqual(start, 60)
        self.assertEqual(end, float("inf"))

    def test_a_backwards_range_is_refused(self):
        for a, b in (("5:00", "1:00"), ("5:00", "5:00")):
            with self.assertRaises(ClipError):
                parse_clip(a, b)


class Labels(unittest.TestCase):
    """The clip must not overwrite the full download of the same video."""

    def test_no_clip_adds_nothing(self):
        self.assertEqual(clip_label(None), "")

    def test_a_clip_is_named_in_the_filename(self):
        self.assertEqual(clip_label((750, 1125)), " [12m30s-18m45s]")

    def test_an_open_end_says_so(self):
        self.assertEqual(clip_label((60, float("inf"))), " [1m00s-end]")

    def test_hours_are_included_when_there_are_any(self):
        self.assertEqual(clip_label((3723, 3800)), " [1h02m03s-1h03m20s]")

    def test_the_label_is_a_legal_windows_filename(self):
        """Colons are why this is 12m30s and not 12:30."""
        for ch in ':*?"<>|/\\':
            self.assertNotIn(ch, clip_label((750, 1125)))


class Route(unittest.TestCase):
    def setUp(self):
        self.c = srv.app.test_client()

    def test_a_bad_time_is_refused_before_the_job_starts(self):
        r = self.c.post("/api/download", json={
            "url": "https://youtu.be/x", "format": "mp4",
            "clip_start": "banana", "clip_end": "2:00"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a time", r.get_json()["error"])

    def test_a_backwards_range_is_refused(self):
        r = self.c.post("/api/download", json={
            "url": "https://youtu.be/x", "format": "mp4",
            "clip_start": "5:00", "clip_end": "1:00"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("after", r.get_json()["error"])

    def test_trimming_a_local_file_is_refused_rather_than_ignored(self):
        """Converter has no range support, so accepting it would silently
        produce the whole file and look like the trim did nothing."""
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "y2obi_clip_probe.mp4")
        with open(path, "wb") as f:
            f.write(b"\0" * 32)
        try:
            r = self.c.post("/api/download", json={
                "source": "file", "path": path, "format": "mp4",
                "clip_start": "0:10", "clip_end": "0:20"})
            # Either the media check or the clip check refuses it; both are 400,
            # and neither may start a job.
            self.assertEqual(r.status_code, 400)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
