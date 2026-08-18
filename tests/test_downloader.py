"""Pure-function tests for app.downloader — no network, no yt-dlp calls.

Run: python -m unittest discover tests
"""
import http.cookiejar
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
# `unittest discover tests` imports these as top-level modules, so the
# package __init__ does not run on its own.
import tests  # noqa: E402,F401

from app import downloader as dl


class ParseFormats(unittest.TestCase):
    def test_heights_sorted_desc_and_labelled(self):
        info = {"formats": [
            {"height": 720, "vcodec": "avc1", "acodec": "none"},
            {"height": 1080, "vcodec": "avc1", "acodec": "none"},
            {"height": 360, "vcodec": "avc1", "acodec": "mp4a"},
        ]}
        qualities, has_audio = dl._parse_formats(info)
        self.assertEqual(qualities, ["1080p", "720p", "360p"])
        self.assertFalse(has_audio)

    def test_audio_only_detected(self):
        info = {"formats": [
            {"height": 720, "vcodec": "avc1", "acodec": "none"},
            {"height": None, "vcodec": "none", "acodec": "opus"},
        ]}
        qualities, has_audio = dl._parse_formats(info)
        self.assertEqual(qualities, ["720p"])
        self.assertTrue(has_audio)

    def test_duplicate_heights_collapse(self):
        info = {"formats": [{"height": 1080, "vcodec": "avc1"},
                            {"height": 1080, "vcodec": "vp9"}]}
        qualities, _ = dl._parse_formats(info)
        self.assertEqual(qualities, ["1080p"])

    def test_unlisted_height_gets_generic_label(self):
        info = {"formats": [{"height": 540, "vcodec": "avc1"}]}
        qualities, _ = dl._parse_formats(info)
        self.assertEqual(qualities, ["540p"])

    def test_no_video_formats_falls_back_to_best(self):
        self.assertEqual(dl._parse_formats({"formats": []})[0], ["Best"])
        self.assertEqual(dl._parse_formats({})[0], ["Best"])


class QualityMaps(unittest.TestCase):
    def test_both_maps_offer_the_same_labels(self):
        self.assertEqual(set(dl.QUALITY_MAP), set(dl.QUALITY_MAP_WEBM))

    def test_best_has_no_height_cap(self):
        self.assertEqual(dl.QUALITY_MAP["Best"], (None, None))

    def test_labels_match_their_height_cap(self):
        for label, (max_h, _) in dl.QUALITY_MAP.items():
            if max_h is None:
                continue
            self.assertEqual(f"{max_h}p", label)
            self.assertIn(f"height<={max_h}", dl.QUALITY_MAP_WEBM[label])


class PlayerClients(unittest.TestCase):
    def test_ladder_is_ordered_and_non_empty(self):
        self.assertTrue(dl.PLAYER_CLIENTS)
        for clients in dl.PLAYER_CLIENTS:
            self.assertTrue(clients)

    def test_base_opts_are_single_video_and_hooked(self):
        d = dl.Downloader("ffmpeg")
        opts = d._base_opts("%(title)s.%(ext)s")
        self.assertTrue(opts["noplaylist"])
        self.assertIn(d._hook, opts["progress_hooks"])
        self.assertIn(d._pp_hook, opts["postprocessor_hooks"])


class CookieApplication(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.jar = os.path.join(self.dir, "cookies.txt")

    def tearDown(self):
        for n in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, n))
        os.rmdir(self.dir)

    def test_existing_jar_is_passed_to_yt_dlp(self):
        http.cookiejar.MozillaCookieJar(self.jar).save()
        opts = {}
        dl.Downloader("ffmpeg", cookies=self.jar)._apply_cookies_file_only(opts)
        self.assertEqual(opts["cookiefile"], self.jar)

    def test_missing_jar_is_ignored(self):
        opts = {}
        dl.Downloader("ffmpeg", cookies=self.jar)._apply_cookies_file_only(opts)
        self.assertNotIn("cookiefile", opts)

    def test_no_cookies_never_reaches_the_browser(self):
        opts = {}
        dl.Downloader("ffmpeg")._apply_cookies_file_only(opts)
        self.assertNotIn("cookiefile", opts)
        self.assertNotIn("cookiesfrombrowser", opts)


class CancelPropagation(unittest.TestCase):
    def test_download_hook_raises_once_cancelled(self):
        d = dl.Downloader("ffmpeg")
        d.cancel()
        with self.assertRaises(Exception) as ctx:
            d._hook({"status": "downloading"})
        self.assertIn("Cancelled", str(ctx.exception))

    def test_postprocessor_hook_raises_once_cancelled(self):
        # Regression: postprocessing fires no download hooks, so a Cancel during
        # "Converting..." used to be ignored and the file completed anyway.
        d = dl.Downloader("ffmpeg")
        d.cancel()
        with self.assertRaises(Exception) as ctx:
            d._pp_hook({"status": "started"})
        self.assertIn("Cancelled", str(ctx.exception))

    def test_hooks_pass_through_when_not_cancelled(self):
        d = dl.Downloader("ffmpeg")
        seen = []
        d.set_callbacks(status=seen.append)
        d._pp_hook({"status": "started"})
        d._hook({"status": "finished"})
        self.assertEqual(seen, ["Converting...", "Processing..."])


class ResolvePath(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.file = os.path.join(self.dir, "video.mp4")
        open(self.file, "wb").close()

    def tearDown(self):
        for n in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, n))
        os.rmdir(self.dir)

    def test_requested_download_wins(self):
        d = dl.Downloader("ffmpeg")
        info = {"requested_downloads": [{"filepath": self.file}]}
        self.assertEqual(d._resolve_path(info, None, "t"), self.file)

    def test_filepath_fallback(self):
        d = dl.Downloader("ffmpeg")
        self.assertEqual(d._resolve_path({"filepath": self.file}, None, "t"), self.file)

    def test_missing_file_is_not_returned(self):
        d = dl.Downloader("ffmpeg")
        gone = os.path.join(self.dir, "gone.mp4")
        self.assertIsNone(d._resolve_path({"filepath": gone}, None, "t"))

    def test_no_info(self):
        self.assertIsNone(dl.Downloader("ffmpeg")._resolve_path(None, None, "t"))


if __name__ == "__main__":
    unittest.main()
