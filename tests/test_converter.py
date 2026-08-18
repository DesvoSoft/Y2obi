"""Pure-function tests for app.converter — no ffmpeg, no files converted.

The conversion paths themselves need a real ffmpeg and are exercised by hand;
what is tested here is everything that decides *what* ffmpeg gets asked to do,
plus the parsing of its output, which is where silent mistakes hide.

Run: python -m unittest discover tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
# `unittest discover tests` imports these as top-level modules, so the
# package __init__ does not run on its own.
import tests  # noqa: E402,F401

from app import converter as cv


class IsMedia(unittest.TestCase):
    def test_common_containers_are_accepted(self):
        for name in ("a.mp4", "b.MKV", "c.webm", "d.mp3", "e.M4A", "f.flac"):
            self.assertTrue(cv.is_media(name), name)

    def test_everything_else_is_rejected(self):
        for name in ("notes.txt", "archive.zip", "script.py", "noext"):
            self.assertFalse(cv.is_media(name), name)

    def test_audio_and_video_lists_do_not_overlap(self):
        self.assertEqual(set(cv.VIDEO_EXTS) & set(cv.AUDIO_EXTS), set())


class UniquePath(unittest.TestCase):
    """Converting an mp4 to mp4 can land on the name of the source file, and
    silently overwriting the user's own input would be unforgivable."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _touch(self, name):
        path = os.path.join(self.dir, name)
        open(path, "wb").close()
        return path

    def test_free_name_is_returned_unchanged(self):
        p = os.path.join(self.dir, "clip.mp3")
        self.assertEqual(cv.unique_path(p), p)

    def test_taken_name_gets_a_suffix(self):
        p = self._touch("clip.mp3")
        self.assertEqual(cv.unique_path(p), os.path.join(self.dir, "clip (2).mp3"))

    def test_suffix_increments_past_existing_copies(self):
        self._touch("clip.mp3")
        self._touch("clip (2).mp3")
        self._touch("clip (3).mp3")
        self.assertEqual(cv.unique_path(os.path.join(self.dir, "clip.mp3")),
                         os.path.join(self.dir, "clip (4).mp3"))

    def test_the_extension_is_preserved(self):
        self._touch("a name with spaces.mp4")
        out = cv.unique_path(os.path.join(self.dir, "a name with spaces.mp4"))
        self.assertTrue(out.endswith(".mp4"))
        self.assertIn("(2)", out)


class FmtDuration(unittest.TestCase):
    def test_minutes_and_seconds_are_zero_padded(self):
        self.assertEqual(cv.fmt_duration(63), "1m 03s")

    def test_hours_appear_only_when_present(self):
        self.assertEqual(cv.fmt_duration(3723), "1h 2m 03s")
        self.assertNotIn("h", cv.fmt_duration(59))

    def test_zero_is_blank_rather_than_zero(self):
        self.assertEqual(cv.fmt_duration(0), "")


class ParsesFfmpegOutput(unittest.TestCase):
    """The build has no ffprobe, so probe() reads ffmpeg's own banner."""

    BANNER = (
        "  Duration: 00:12:04.53, start: 0.000000, bitrate: 9310 kb/s\n"
        "  Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, "
        "1920x1080 [SAR 1:1 DAR 16:9], 9174 kb/s, 30 fps\n"
        "  Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo\n"
    )

    def test_duration_is_read(self):
        m = cv._DURATION_RE.search(self.BANNER)
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        self.assertAlmostEqual(secs, 724.53, places=2)

    def test_video_codec_and_size_are_read(self):
        m = cv._VIDEO_RE.search(self.BANNER)
        self.assertEqual((m.group(1), m.group(2), m.group(3)), ("h264", "1920", "1080"))

    def test_audio_codec_is_read(self):
        self.assertEqual(cv._AUDIO_RE.search(self.BANNER).group(1), "aac")

    def test_progress_and_speed_lines_are_read(self):
        self.assertEqual(cv._OUT_TIME_RE.search("out_time_us=5933333").group(1), "5933333")
        self.assertEqual(cv._SPEED_RE.search("speed=  66.2x").group(1), "66.2")

    def test_cover_art_is_not_mistaken_for_video(self):
        # An mp3 with embedded art shows a video stream; treating it as a video
        # would offer MP4 conversion for a file that has no moving picture.
        art = ("  Stream #0:1: Video: mjpeg (Baseline), yuvj420p(pc), 600x600 "
               "[SAR 1:1 DAR 1:1], 90k tbr\n")
        m = cv._VIDEO_RE.search(art)
        self.assertIn(m.group(1).lower(), ("mjpeg", "png", "bmp", "gif"))


class Cancellation(unittest.TestCase):
    def test_cancel_message_is_what_the_server_keys_on(self):
        # server.py decides "cancelled" vs "error" by looking for this word.
        self.assertIn("Cancelled", str(cv.Cancelled()))
        self.assertIsInstance(cv.Cancelled(), cv.ConvertError)

    def test_a_converter_without_an_event_is_never_cancelled(self):
        self.assertFalse(cv.Converter("ffmpeg")._cancelled())

    def test_setting_the_event_cancels(self):
        import threading
        ev = threading.Event()
        c = cv.Converter("ffmpeg", cancel_event=ev)
        self.assertFalse(c._cancelled())
        c.cancel()
        self.assertTrue(c._cancelled())
        with self.assertRaises(cv.Cancelled):
            c._check_cancel()


class Probe(unittest.TestCase):
    def test_a_missing_file_is_rejected_before_ffmpeg_runs(self):
        with self.assertRaises(cv.ConvertError):
            cv.Converter("ffmpeg-does-not-exist").probe(
                os.path.join(tempfile.gettempdir(), "y2obi_no_such_file.mp4"))


if __name__ == "__main__":
    unittest.main()
