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
        # The 360p one is muxed, and audio can be extracted from it.
        self.assertTrue(has_audio)

    def test_muxed_only_still_has_audio(self):
        # A signed-in web_safari session offers HLS with video and audio and no
        # audio-only stream at all. Reporting "no audio" there made the page
        # refuse MP3 and transcripts for a video the download path handles fine.
        info = {"formats": [
            {"height": 360, "vcodec": "avc1", "acodec": "mp4a", "protocol": "m3u8_native"},
            {"height": 1080, "vcodec": "avc1", "acodec": "mp4a", "protocol": "m3u8_native"},
        ]}
        self.assertTrue(dl._parse_formats(info)[1])

    def test_silent_video_only_has_no_audio(self):
        info = {"formats": [
            {"height": 720, "vcodec": "avc1", "acodec": "none"},
            {"height": None, "vcodec": "none", "acodec": "none", "format_id": "sb0"},
        ]}
        self.assertFalse(dl._parse_formats(info)[1])

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
    def test_every_client_exists_in_the_installed_yt_dlp(self):
        """yt-dlp removes player clients between releases and merely warns.

        A name that no longer exists is not an error: yt-dlp drops it and falls
        back to its defaults, so the rung silently becomes a wasted attempt.
        tv_embedded had already disappeared that way before anyone noticed.
        """
        try:
            from yt_dlp.extractor.youtube._base import INNERTUBE_CLIENTS
        except ImportError:
            self.skipTest("yt-dlp moved INNERTUBE_CLIENTS")
        for clients in dl.PLAYER_CLIENTS:
            for name in clients:
                self.assertIn(name, INNERTUBE_CLIENTS,
                              f"{name} is not a client in the installed yt-dlp")

    def test_authed_clients_accept_cookies(self):
        """yt-dlp drops a cookie-refusing client from a signed-in request and
        then fails the empty rung, so every authed rung must take cookies."""
        try:
            from yt_dlp.extractor.youtube._base import INNERTUBE_CLIENTS
        except ImportError:
            self.skipTest("yt-dlp moved INNERTUBE_CLIENTS")
        for clients in dl.AUTHED_CLIENTS:
            for name in clients:
                self.assertIn(name, INNERTUBE_CLIENTS)
                self.assertTrue(INNERTUBE_CLIENTS[name].get("SUPPORTS_COOKIES"),
                                f"{name} refuses cookies")

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


class SessionLadder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.jar = os.path.join(self.dir, "cookies.txt")
        http.cookiejar.MozillaCookieJar(self.jar).save()

    def tearDown(self):
        os.unlink(self.jar)
        os.rmdir(self.dir)

    def test_anonymous_ladder_sends_no_cookies(self):
        ladder = dl.Downloader("ffmpeg")._ladder()
        self.assertEqual([c for c, _ in ladder], list(dl.PLAYER_CLIENTS))
        self.assertFalse(any(use for _, use in ladder))

    def test_session_goes_first_then_falls_back_anonymous(self):
        ladder = dl.Downloader("ffmpeg", cookies=self.jar)._ladder()
        n = len(dl.AUTHED_CLIENTS)
        self.assertEqual([c for c, _ in ladder[:n]], list(dl.AUTHED_CLIENTS))
        self.assertTrue(all(use for _, use in ladder[:n]))
        self.assertFalse(any(use for _, use in ladder[n:]))

    def test_anonymous_rung_strips_the_cookiefile(self):
        d = dl.Downloader("ffmpeg", cookies=self.jar)
        opts = d._base_opts("%(title)s.%(ext)s")
        self.assertIn("cookiefile", opts)
        d._rung_opts(opts, ["android_vr"], False)
        self.assertNotIn("cookiefile", opts)
        d._rung_opts(opts, ["web_safari"], True)
        self.assertEqual(opts["cookiefile"], self.jar)

    def test_deno_is_handed_to_yt_dlp(self):
        opts = dl.Downloader("ffmpeg", deno=r"C:\x\deno.exe")._rung_opts({}, ["web"], False)
        self.assertEqual(opts["js_runtimes"], {"deno": {"path": r"C:\x\deno.exe"}})
        self.assertNotIn("js_runtimes", dl.Downloader("ffmpeg")._rung_opts({}, ["web"], False))


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


class TruncatedStream(unittest.TestCase):
    """YouTube can answer a throttled anonymous fetch with the first few hundred
    KB of a stream and a Content-Length to match, so yt-dlp calls it finished.
    Measured on aXRImge9EH4 via the android client: format 18 advertised
    127,886,035 bytes and delivered 623,163, which surfaced three steps later
    as "Could not read the extracted audio"."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.file = os.path.join(self.dir, "video.mp4")
        with open(self.file, "wb") as f:
            f.write(b"\0" * 623163)

    def tearDown(self):
        for n in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, n))
        os.rmdir(self.dir)

    def _finished(self, expected, key="filesize"):
        return {"status": "finished", "filename": self.file,
                "downloaded_bytes": 623163, "info_dict": {key: expected}}

    def test_short_file_is_refused_and_deleted(self):
        with self.assertRaises(dl.yt_dlp.utils.DownloadError) as ctx:
            dl.Downloader("ffmpeg")._hook(self._finished(127886035))
        self.assertTrue(dl.looks_like_no_streams(ctx.exception))
        self.assertFalse(os.path.exists(self.file))

    def test_approximate_size_also_counts(self):
        with self.assertRaises(dl.yt_dlp.utils.DownloadError):
            dl.Downloader("ffmpeg")._hook(self._finished(127886035, "filesize_approx"))

    def test_complete_file_passes(self):
        dl.Downloader("ffmpeg")._hook(self._finished(640000))
        self.assertTrue(os.path.exists(self.file))

    def test_unknown_size_passes(self):
        dl.Downloader("ffmpeg")._hook(self._finished(None))
        self.assertTrue(os.path.exists(self.file))

    def test_clip_is_exempt(self):
        # A partial download is meant to be smaller than the advertised size.
        d = dl.Downloader("ffmpeg")
        d._clipping = True
        d._hook(self._finished(127886035))
        self.assertTrue(os.path.exists(self.file))


class LadderClassification(unittest.TestCase):
    """A block anywhere in the ladder must reach the user as a block, even
    though the first error is the one whose text is kept."""

    def _run(self, errors):
        errs = iter(errors)

        class FakeYDL:
            def __init__(self, opts):
                pass

            def extract_info(self, url, download=True):
                raise dl.yt_dlp.utils.DownloadError(next(errs))

            def close(self):
                pass

        real = dl.yt_dlp.YoutubeDL
        dl.yt_dlp.YoutubeDL = FakeYDL
        try:
            dl.Downloader("ffmpeg")._run_download("u", "%(title)s.%(ext)s", {})
        finally:
            dl.yt_dlp.YoutubeDL = real

    def test_later_truncation_after_a_403_is_a_block(self):
        errors = ["ERROR: unable to download video data: HTTP Error 403: Forbidden",
                  "ERROR: " + dl.TRUNCATED_MSG] + ["ERROR: other"] * 10
        with self.assertRaises(dl.StreamsUnavailable):
            self._run(errors)

    def test_later_auth_error_wins(self):
        errors = ["ERROR: HTTP Error 403: Forbidden",
                  "ERROR: Sign in to confirm you're not a bot"] + ["ERROR: x"] * 10
        with self.assertRaises(dl.AuthRequired):
            self._run(errors)

    def test_plain_failure_keeps_first_message(self):
        with self.assertRaises(dl.DownloadError) as ctx:
            self._run(["ERROR: first", "ERROR: second"] + ["ERROR: x"] * 10)
        self.assertNotIsInstance(ctx.exception, dl.StreamsUnavailable)
        self.assertIn("first", str(ctx.exception))


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
