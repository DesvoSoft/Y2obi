"""Playlists: recognising them, listing them, and the transcription queue.

No network, no whisper: yt-dlp and the two job phases are replaced with fakes,
so what is under test is the bookkeeping -- which video ends up in which state,
under which name, and what the page is told.

Run: python -m unittest discover tests
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests  # noqa: E402,F401

from app import downloader as dl
from app import server as srv
from app import transcriber


class PlaylistRef(unittest.TestCase):
    def test_a_playlist_link_names_only_the_list(self):
        self.assertEqual(dl.playlist_ref("https://www.youtube.com/playlist?list=PL123abc_-"),
                         ("PL123abc_-", False))

    def test_a_watch_link_with_a_list_names_both(self):
        self.assertEqual(dl.playlist_ref("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLx1"),
                         ("PLx1", True))

    def test_short_links_and_shorts_count_as_a_video(self):
        self.assertEqual(dl.playlist_ref("https://youtu.be/dQw4w9WgXcQ?list=PLx1"), ("PLx1", True))
        self.assertTrue(dl.playlist_ref("https://www.youtube.com/shorts/dQw4w9WgXcQ")[1])

    def test_a_plain_video_has_no_list(self):
        self.assertEqual(dl.playlist_ref("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
                         (None, True))

    def test_a_malformed_list_id_is_ignored(self):
        self.assertIsNone(dl.playlist_ref("https://www.youtube.com/playlist?list=a/b<c>")[0])

    def test_mixes_are_recognised(self):
        self.assertTrue(dl.is_mix("RDdQw4w9WgXcQ"))
        self.assertFalse(dl.is_mix("PLx1"))


class PlaylistEntries(unittest.TestCase):
    def test_videos_are_numbered_in_order_and_the_rest_skipped(self):
        info = {"entries": [
            {"id": "aaaaaaaaaaa", "title": "One", "duration": 61.0, "channel": "C", "ie_key": "Youtube"},
            {"id": "UCchannel", "title": "A tab", "ie_key": "YoutubeTab"},
            None,
            {"id": "bbbbbbbbbbb", "title": "[Private video]", "duration": None, "ie_key": "Youtube"},
        ]}
        out = dl.playlist_entries(info)
        self.assertEqual([e["index"] for e in out], [1, 2])
        self.assertEqual(out[0]["duration"], 61)
        self.assertTrue(out[0]["available"])
        self.assertFalse(out[1]["available"])


class SafeFilename(unittest.TestCase):
    def test_path_separators_cannot_escape_the_folder(self):
        name = dl.safe_filename("../../evil\\x", "fb")
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)

    def test_trailing_dots_are_dropped(self):
        # Windows strips them on write, so the skip check would never match.
        self.assertEqual(dl.safe_filename("Part 1...", "fb"), "Part 1")

    def test_device_names_are_defused(self):
        self.assertEqual(dl.safe_filename("CON", "fb"), "_CON")

    def test_blank_falls_back(self):
        self.assertEqual(dl.safe_filename("  ", "fb"), "fb")
        self.assertEqual(dl.safe_filename(None, "fb"), "fb")


class FixedNames(unittest.TestCase):
    def test_a_percent_in_a_title_is_not_a_template_field(self):
        d = dl.Downloader()
        with mock.patch.object(d, "_run_download", return_value="x") as run:
            d.download_mp3("u", "out", name="01 - 100% legit")
        self.assertEqual(run.call_args.args[1], os.path.join("out", "01 - 100%% legit.%(ext)s"))

    def test_without_a_name_the_title_is_used(self):
        d = dl.Downloader()
        with mock.patch.object(d, "_run_download", return_value="x") as run:
            d.download_mp4("u", "out", "720p")
        self.assertEqual(run.call_args.args[1], os.path.join("out", "%(title)s [720p].%(ext)s"))


class TranscriptOutputs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_srt_can_be_left_out(self):
        cues = [{"start": 0, "end": 1000, "text": "hi"}]
        files = transcriber.write_outputs(cues, os.path.join(self.dir, "a"), srt=False)
        self.assertEqual(files, [os.path.join(self.dir, "a.txt")])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "a.srt")))

    def test_ranges_name_the_span_and_the_last_ends_with_the_speech(self):
        cues = [{"start": 1000, "end": 5000, "text": "one"},
                {"start": 31000, "end": 42000, "text": "two"}]
        out = transcriber.stamped_text(cues, 30, ranges=True)
        stamps = [ln for ln in out.split("\n") if ln.startswith("[")]
        self.assertEqual(stamps, ["[00:00:00 - 00:00:30]", "[00:00:30 - 00:00:42]"])

    def test_without_ranges_the_format_is_unchanged(self):
        cues = [{"start": 1000, "end": 5000, "text": "one"}]
        self.assertEqual(transcriber.stamped_text(cues, 60), "[00:00:00]\none\n")


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved = srv._session_token
        self._config = srv.CONFIG_PATH
        self._whisper = srv.get_whisper_cli
        self._make_dl = srv._make_dl
        srv._session_token = None
        srv.get_whisper_cli = lambda: "whisper-cli.exe"
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        srv.CONFIG_PATH = os.path.join(self.dir, "config.json")
        srv.tasks.clear()
        self.c = srv.app.test_client()

    def tearDown(self):
        srv._session_token = self._saved
        srv.CONFIG_PATH = self._config
        srv.get_whisper_cli = self._whisper
        srv._make_dl = self._make_dl
        srv.tasks.clear()
        shutil.rmtree(self.dir, ignore_errors=True)


class _FakeDl:
    def __init__(self, calls):
        self.calls = calls

    def get_playlist(self, url):
        self.calls.append(("playlist", url))
        return {"id": "PLx1", "title": "Course", "channel": "Chan", "entries": [
            {"index": 1, "id": "aaaaaaaaaaa", "title": "One", "duration": 60,
             "channel": "Chan", "available": True},
            {"index": 2, "id": "bbbbbbbbbbb", "title": "Two", "duration": 90,
             "channel": "Chan", "available": True},
        ]}

    def get_info(self, url):
        self.calls.append(("info", url))
        return {"title": "One", "duration": 60, "formats": []}


class AnalyzePlaylists(_Base):
    def setUp(self):
        super().setUp()
        self.calls = []
        srv._make_dl = lambda: _FakeDl(self.calls)

    def test_a_playlist_link_is_listed(self):
        body = self.c.post("/api/analyze", json={
            "url": "https://www.youtube.com/playlist?list=PLx1"}).get_json()
        self.assertEqual(body["kind"], "playlist")
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["duration"], "2m 30s")
        self.assertEqual(self.calls, [("playlist", "https://www.youtube.com/playlist?list=PLx1")])

    def test_a_watch_link_stays_one_video_and_offers_the_list(self):
        body = self.c.post("/api/analyze", json={
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLx1"}).get_json()
        self.assertNotIn("kind", body)
        self.assertEqual(body["list_id"], "PLx1")

    def test_a_mix_is_not_offered(self):
        body = self.c.post("/api/analyze", json={
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa&list=RDaaaaaaaaaaa"}).get_json()
        self.assertIsNone(body["list_id"])

    def test_a_list_yt_dlp_found_on_its_own_is_listed(self):
        # A channel's Videos tab carries no list= at all.
        class _Tab(_FakeDl):
            def get_info(self, url):
                raise dl.PlaylistError("Playlist detected")
        srv._make_dl = lambda: _Tab(self.calls)
        body = self.c.post("/api/analyze", json={
            "url": "https://www.youtube.com/@chan/videos"}).get_json()
        self.assertEqual(body["kind"], "playlist")

    def test_load_playlist_by_id(self):
        body = self.c.post("/api/playlist", json={"list_id": "PLx1"}).get_json()
        self.assertEqual(body["title"], "Course")

    def test_load_playlist_rejects_junk(self):
        self.assertEqual(self.c.post("/api/playlist", json={"list_id": "a&b=c"}).status_code, 400)
        self.assertEqual(self.c.post("/api/playlist", json={}).status_code, 400)


class BatchRoute(_Base):
    def test_needs_items(self):
        self.assertEqual(self.c.post("/api/batch", json={"items": []}).status_code, 400)

    def test_only_video_ids_are_accepted(self):
        r = self.c.post("/api/batch", json={"items": [{"id": "https://evil.example/x"}]})
        self.assertEqual(r.status_code, 400)

    def test_downloads_need_no_speech_engine(self):
        srv.get_whisper_cli = lambda: None
        with mock.patch("threading.Thread"):
            r = self.c.post("/api/batch", json={"items": [{"id": "aaaaaaaaaaa"}],
                                                "format": "mp3"})
        self.assertEqual(r.status_code, 200)

    def test_unknown_format_or_quality_is_refused(self):
        for body in ({"format": "exe"}, {"format": "mp4", "quality": "9000p"}):
            body["items"] = [{"id": "aaaaaaaaaaa"}]
            self.assertEqual(self.c.post("/api/batch", json=body).status_code, 400, body)

    def test_refused_while_another_job_runs(self):
        srv.tasks["running"] = {"done": False, "kind": "media"}
        r = self.c.post("/api/batch", json={"items": [{"id": "aaaaaaaaaaa"}]})
        self.assertEqual(r.status_code, 409)

    def test_names_are_padded_to_the_playlist_not_the_selection(self):
        with mock.patch.object(srv, "_run_batch") as run, \
                mock.patch("threading.Thread") as thread:
            thread.return_value.start = lambda: None
            r = self.c.post("/api/batch", json={
                "items": [{"id": "aaaaaaaaaaa", "title": "Intro", "index": 3}],
                "total": 120, "playlist_title": "My/Course"})
        self.assertEqual(r.status_code, 200)
        args = thread.call_args.kwargs["args"]
        self.assertEqual(args[1][0]["stem"], "003 - Intro")
        self.assertEqual(os.path.dirname(args[2]), srv.DOWNLOAD_DIR)
        run.assert_not_called()


class BatchRun(_Base):
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.dir, "Course")
        patches = [
            mock.patch.object(transcriber.Transcriber, "has_model", return_value=True),
            mock.patch.object(transcriber.Transcriber, "ensure_model", return_value="m.bin"),
            mock.patch.object(srv, "_device", return_value="cpu"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _items(self, *ids):
        return [{"id": i, "title": i, "index": n, "stem": f"{n:02d} - {i}"}
                for n, i in enumerate(ids, 1)]

    def _run(self, items, fetch, transcribe):
        srv.tasks["b"] = {"percent": 0, "speed": 0, "eta": 0, "rate": None,
                          "status": "", "done": False, "cancelled": False,
                          "path": None, "kind": "media", "_dl": None, "_tr": None,
                          "_cv": None, "index": 0,
                          "batch": [{"id": i["id"], "state": "pending", "error": None}
                                    for i in items]}
        with mock.patch.object(srv, "_fetch_audio", side_effect=fetch), \
                mock.patch.object(srv, "_transcribe_audio", side_effect=transcribe):
            srv._run_batch("b", items, self.out, "small", "auto", {"ts_interval": 0})
        return self.c.get("/api/progress/b").get_json()

    @staticmethod
    def _write(tr, cancel, audio, model, prefix, *a, **k):
        with open(prefix + ".txt", "w") as f:
            f.write("x")
        return [prefix + ".txt"]

    def test_one_failure_does_not_stop_the_rest(self):
        def fetch(task_id, url, *a):
            if "bbbbbbbbbbb" in url:
                raise dl.DownloadError("Video unavailable\nlong yt-dlp text")
            return "audio.m4a"
        body = self._run(self._items("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"),
                         fetch, self._write)
        states = [i["state"] for i in body["batch"]["items"]]
        self.assertEqual(states, ["done", "error", "done"])
        self.assertEqual(body["batch"]["items"][1]["error"], "Video unavailable")
        self.assertIsNone(body["error"])
        self.assertIn("2 transcribed", body["status"])
        self.assertIn("1 failed", body["status"])
        self.assertEqual(body["folder"], self.out)

    def test_a_video_already_transcribed_is_skipped(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "01 - aaaaaaaaaaa.txt"), "w") as f:
            f.write("done before")
        fetch = mock.Mock(return_value="audio.m4a")
        body = self._run(self._items("aaaaaaaaaaa", "bbbbbbbbbbb"), fetch, self._write)
        self.assertEqual([i["state"] for i in body["batch"]["items"]], ["skipped", "done"])
        self.assertEqual(fetch.call_count, 1)

    def test_all_failing_is_reported_as_an_error(self):
        def fetch(*a):
            raise dl.DownloadError("HTTP Error 403")
        body = self._run(self._items("aaaaaaaaaaa"), fetch, self._write)
        self.assertEqual(body["error"], "HTTP Error 403")

    def test_a_blocked_video_asks_for_sign_in_at_the_end(self):
        def fetch(*a):
            raise dl.AuthRequired("sign in")
        body = self._run(self._items("aaaaaaaaaaa"), fetch, self._write)
        self.assertTrue(body["needs_cookies"])

    def test_cancel_stops_the_queue_and_keeps_what_finished(self):
        items = self._items("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc")

        def transcribe(tr, cancel, audio, model, prefix, *a, **k):
            if prefix.endswith("bbbbbbbbbbb"):
                cancel.set()
                raise transcriber.Cancelled()
            return self._write(tr, cancel, audio, model, prefix)
        body = self._run(items, lambda *a: "audio.m4a", transcribe)
        self.assertTrue(body["cancelled"])
        self.assertEqual([i["state"] for i in body["batch"]["items"]],
                         ["done", "pending", "pending"])
        self.assertIn("1 transcribed", body["status"])

    def test_a_download_batch_saves_numbered_files_in_the_folder(self):
        seen = []

        def download(task_id, url, out_dir, name, fmt, quality, *a):
            seen.append((name, fmt, quality))
            open(os.path.join(out_dir, f"{name} [{quality}].mp4"), "w").close()
        items = self._items("aaaaaaaaaaa", "bbbbbbbbbbb")
        srv.tasks["b"] = {"percent": 0, "speed": 0, "eta": 0, "rate": None, "status": "",
                          "done": False, "cancelled": False, "path": None,
                          "kind": "media", "index": 0,
                          "batch": [{"id": i["id"], "state": "pending", "error": None}
                                    for i in items]}
        with mock.patch.object(srv, "_download_item", side_effect=download), \
                mock.patch.object(transcriber.Transcriber, "ensure_model") as em:
            srv._run_batch("b", items, self.out, "small", "auto", {}, "mp4", "720p")
            em.assert_not_called()  # no model for a plain download
        body = self.c.get("/api/progress/b").get_json()
        self.assertEqual(seen, [("01 - aaaaaaaaaaa", "mp4", "720p"),
                                ("02 - bbbbbbbbbbb", "mp4", "720p")])
        self.assertIn("2 downloaded", body["status"])
        # Run again: both are there under the same names, so both are skipped.
        srv.tasks["b"].update(done=False, batch=[{"id": i["id"], "state": "pending",
                                                  "error": None} for i in items])
        seen.clear()
        with mock.patch.object(srv, "_download_item", side_effect=download):
            srv._run_batch("b", items, self.out, "small", "auto", {}, "mp4", "720p")
        self.assertEqual(seen, [])

    def test_the_list_is_only_sent_when_it_changed(self):
        srv.tasks["b"] = {"percent": 0, "speed": 0, "eta": 0, "status": "",
                          "done": False, "cancelled": False, "path": None,
                          "batch": [{"id": "x", "state": "pending", "error": None}],
                          "batch_rev": 3, "index": 0}
        self.assertIn("items", self.c.get("/api/progress/b").get_json()["batch"])
        self.assertNotIn("items", self.c.get("/api/progress/b?rev=3").get_json()["batch"])
        self.assertIn("items", self.c.get("/api/progress/b?rev=2").get_json()["batch"])

    def test_progress_is_not_slowed_by_the_browser_check_mid_run(self):
        srv.tasks["b"] = {"percent": 0, "speed": 0, "eta": 0, "status": "",
                          "done": False, "cancelled": False, "path": None,
                          "needs_cookies": True, "batch": [], "index": 0}
        with mock.patch.object(srv, "installed_browsers") as ib:
            body = self.c.get("/api/progress/b").get_json()
        ib.assert_not_called()
        self.assertNotIn("needs_cookies", body)


class TranscriptConfig(_Base):
    def test_srt_and_ranges_roundtrip(self):
        self.assertTrue(self.c.get("/api/config").get_json()["srt"])
        self.c.post("/api/config", json={"srt": False, "ts_ranges": True})
        cfg = self.c.get("/api/config").get_json()
        self.assertFalse(cfg["srt"])
        self.assertTrue(cfg["ts_ranges"])

    def test_non_booleans_are_refused(self):
        self.assertEqual(self.c.post("/api/config", json={"srt": "no"}).status_code, 400)

    def test_new_intervals_are_accepted(self):
        for value in (30, 600):
            self.assertEqual(self.c.post("/api/config", json={"ts_interval": value}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
