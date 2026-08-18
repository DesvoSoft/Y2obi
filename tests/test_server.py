"""Route-level tests for app.server — Flask test client, no network, no yt-dlp.

Run: python -m unittest discover tests
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede any app import: it redirects the data roots to a sandbox.
# `unittest discover tests` imports these as top-level modules, so the
# package __init__ does not run on its own.
import tests  # noqa: E402,F401

from app import server as srv
from app import transcriber
from app.downloader import has_session_cookies

TOKEN = "test-token-abcdefghijklmnop"


class TokenGate(unittest.TestCase):
    def setUp(self):
        self._saved = srv._session_token
        srv._session_token = TOKEN
        self.c = srv.app.test_client()

    def tearDown(self):
        srv._session_token = self._saved

    def test_page_itself_needs_no_token(self):
        # The token is handed over through the page URL, so / must stay open —
        # and it must not leak the token into the HTML it serves.
        srv._static_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop")
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(TOKEN.encode(), r.data)

    def test_api_rejected_without_token(self):
        self.assertEqual(self.c.get("/api/cookies/status").status_code, 403)

    def test_api_rejected_with_wrong_token(self):
        r = self.c.get("/api/cookies/status", headers={"X-Y2obi-Token": "nope"})
        self.assertEqual(r.status_code, 403)

    def test_api_accepted_with_header(self):
        r = self.c.get("/api/cookies/status", headers={"X-Y2obi-Token": TOKEN})
        self.assertEqual(r.status_code, 200)

    def test_api_accepted_with_query_arg(self):
        # /api/file is opened as a plain URL, so the query form has to work too.
        self.assertEqual(self.c.get(f"/api/cookies/status?t={TOKEN}").status_code, 200)

    def test_non_ascii_token_is_a_403_not_a_500(self):
        r = self.c.get("/api/cookies/status", headers={"X-Y2obi-Token": "ñandú"})
        self.assertEqual(r.status_code, 403)

    def test_destructive_route_is_gated(self):
        self.assertEqual(self.c.delete("/api/cookies").status_code, 403)

    def test_gate_is_off_when_no_token_was_minted(self):
        # Imported directly (tests, dev harness) the app stays open.
        srv._session_token = None
        self.assertEqual(self.c.get("/api/cookies/status").status_code, 200)


class OpenFile(unittest.TestCase):
    def setUp(self):
        self._saved = srv._session_token
        srv._session_token = None
        self.c = srv.app.test_client()
        srv.tasks.clear()

    def tearDown(self):
        srv._session_token = self._saved
        srv.tasks.clear()

    def test_unknown_task_is_404(self):
        self.assertEqual(self.c.post("/api/open_file/nope").status_code, 404)

    def test_task_without_a_path_is_404(self):
        srv.tasks["t1"] = {"path": None, "done": True}
        self.assertEqual(self.c.post("/api/open_file/t1").status_code, 404)

    def test_vanished_file_is_404(self):
        srv.tasks["t1"] = {"path": r"C:\definitely\not\here.mp4", "done": True}
        self.assertEqual(self.c.post("/api/open_file/t1").status_code, 404)


class LocalFileRoutes(unittest.TestCase):
    """The local-file paths must never accept a path that is not a real file."""

    def setUp(self):
        self._saved = srv._session_token
        srv._session_token = None
        self.c = srv.app.test_client()
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.txt = os.path.join(self.dir, "notes.txt")
        with open(self.txt, "w", encoding="utf-8") as f:
            f.write("not media")

    def tearDown(self):
        srv._session_token = self._saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_analyze_file_needs_a_path(self):
        self.assertEqual(self.c.post("/api/analyze_file", json={}).status_code, 400)

    def test_analyze_file_rejects_missing_file(self):
        r = self.c.post("/api/analyze_file", json={"path": os.path.join(self.dir, "no.mp4")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not found", r.get_json()["error"].lower())

    def test_analyze_file_rejects_non_media(self):
        r = self.c.post("/api/analyze_file", json={"path": self.txt})
        self.assertEqual(r.status_code, 400)

    def test_download_from_file_rejects_missing_file(self):
        r = self.c.post("/api/download", json={
            "source": "file", "path": os.path.join(self.dir, "no.mp4"), "format": "mp3"})
        self.assertEqual(r.status_code, 400)

    def test_download_from_file_rejects_webm(self):
        # VP9 re-encoding a local file takes hours for no gain over mp4.
        media = os.path.join(self.dir, "clip.mp4")
        open(media, "wb").close()
        r = self.c.post("/api/download", json={
            "source": "file", "path": media, "format": "webm"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("WEBM", r.get_json()["error"])

    def test_url_mode_still_requires_a_url(self):
        self.assertEqual(self.c.post("/api/download", json={"format": "mp4"}).status_code, 400)


class ModelRoutes(unittest.TestCase):
    def setUp(self):
        self._saved = srv._session_token
        self._models_dir = srv.MODELS_DIR
        self._config = srv.CONFIG_PATH
        srv._session_token = None
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        srv.MODELS_DIR = os.path.join(self.dir, "models")
        srv.CONFIG_PATH = os.path.join(self.dir, "config.json")
        os.makedirs(srv.MODELS_DIR)
        self.c = srv.app.test_client()

    def tearDown(self):
        srv._session_token = self._saved
        srv.MODELS_DIR = self._models_dir
        srv.CONFIG_PATH = self._config
        shutil.rmtree(self.dir, ignore_errors=True)

    def _fake_model(self, name):
        fname = transcriber.MODELS[name][0]
        path = os.path.join(srv.MODELS_DIR, fname)
        with open(path, "wb") as f:
            f.write(b"x" * 2048)
        return path

    def test_unknown_model_cannot_be_deleted(self):
        self.assertEqual(self.c.delete("/api/models/../../etc").status_code, 404)
        self.assertEqual(self.c.delete("/api/models/nope").status_code, 404)

    def test_unknown_model_cannot_be_downloaded(self):
        self.assertEqual(self.c.post("/api/models/nope/download").status_code, 404)

    def test_delete_removes_the_cached_file(self):
        path = self._fake_model("tiny")
        r = self.c.delete("/api/models/tiny")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.assertFalse(os.path.exists(path))
        self.assertFalse(r.get_json()["model"]["installed"])

    def test_delete_of_an_absent_model_is_not_an_error(self):
        self.assertEqual(self.c.delete("/api/models/tiny").status_code, 200)

    def test_config_roundtrip(self):
        r = self.c.post("/api/config", json={"model": "small", "lang": "es"})
        self.assertTrue(r.get_json()["ok"])
        got = self.c.get("/api/config").get_json()
        self.assertEqual((got["model"], got["lang"]), ("small", "es"))

    def test_config_rejects_an_unknown_model(self):
        self.assertEqual(self.c.post("/api/config", json={"model": "bogus"}).status_code, 400)

    def test_config_rejects_a_malformed_language(self):
        # Junk here would only surface as a whisper failure minutes into a run.
        for bad in ("english", "e", "es-AR", "../x", ""):
            self.assertEqual(self.c.post("/api/config", json={"lang": bad}).status_code,
                             400, bad)

    def test_config_accepts_auto_and_iso_codes(self):
        for good in ("auto", "es", "EN", " ja "):
            self.assertTrue(self.c.post("/api/config", json={"lang": good}).get_json()["ok"], good)

    def test_corrupt_config_falls_back_to_defaults(self):
        # A hand-edited or half-written file must never stop the app.
        with open(srv.CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write("{not json")
        got = self.c.get("/api/config").get_json()
        self.assertEqual(got["model"], transcriber.DEFAULT_MODEL)

    def test_every_catalogue_model_has_a_label(self):
        for name in transcriber.MODELS:
            self.assertIn(name, transcriber.MODEL_LABELS)

    def test_a_running_download_is_not_started_twice(self):
        # Closing and reopening the panel must re-attach, not start a second
        # writer on the same <model>.part file.
        srv.tasks["live"] = {"done": False}
        srv._model_downloads["tiny"] = "live"
        try:
            r = self.c.post("/api/models/tiny/download")
            self.assertEqual(r.status_code, 200)
            body = r.get_json()
            self.assertEqual(body["task_id"], "live")
            self.assertTrue(body["already_running"])
        finally:
            srv.tasks.pop("live", None)
            srv._model_downloads.pop("tiny", None)

    def test_a_finished_download_does_not_block_a_new_one(self):
        srv.tasks["old"] = {"done": True, "_done_at": time.time()}
        srv._model_downloads["tiny"] = "old"
        started = []
        real = srv._run_model_download
        srv._run_model_download = lambda task_id, name: started.append((task_id, name))
        try:
            body = self.c.post("/api/models/tiny/download").get_json()
            self.assertNotEqual(body["task_id"], "old")
            self.assertNotIn("already_running", body)
        finally:
            srv._run_model_download = real
            srv.tasks.pop("old", None)
            srv._model_downloads.pop("tiny", None)

    def test_in_flight_downloads_are_reported(self):
        srv.tasks["live"] = {"done": False}
        srv._model_downloads["tiny"] = "live"
        try:
            d = self.c.get("/api/transcribe/models").get_json()
            if d.get("available"):  # skipped on a build without whisper
                self.assertEqual(d["downloading"].get("tiny"), "live")
        finally:
            srv.tasks.pop("live", None)
            srv._model_downloads.pop("tiny", None)

    def test_the_same_model_lock_is_reused(self):
        self.assertIs(srv._model_lock("tiny"), srv._model_lock("tiny"))
        self.assertIsNot(srv._model_lock("tiny"), srv._model_lock("base"))


class OneJobAtATime(unittest.TestCase):
    """A second media job would be orphaned: the page tracks one task id, so
    nothing could cancel it while it kept burning CPU."""

    def setUp(self):
        self._saved = srv._session_token
        srv._session_token = None
        self.c = srv.app.test_client()
        srv.tasks.clear()
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        self.media = os.path.join(self.dir, "clip.mp4")
        open(self.media, "wb").close()

    def tearDown(self):
        srv._session_token = self._saved
        srv.tasks.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _busy(self, kind="media"):
        srv.tasks["running"] = {"done": False, "kind": kind}

    def test_second_media_job_is_refused(self):
        self._busy()
        r = self.c.post("/api/download", json={
            "source": "file", "path": self.media, "format": "mp3"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["busy_task_id"], "running")

    def test_a_finished_job_does_not_block(self):
        srv.tasks["old"] = {"done": True, "kind": "media", "_done_at": time.time()}
        r = self.c.post("/api/download", json={"url": "", "format": "mp4"})
        # Rejected for the empty URL, not for being busy.
        self.assertEqual(r.status_code, 400)

    def test_a_model_download_does_not_block_a_media_job(self):
        # Fetching a model is network-only; it does not compete for the CPU.
        self._busy(kind="model")
        self.assertIsNone(srv._active_job())

    def test_active_job_ignores_model_tasks(self):
        srv.tasks["m"] = {"done": False, "kind": "model"}
        srv.tasks["j"] = {"done": False, "kind": "media"}
        self.assertEqual(srv._active_job(), "j")


class DeviceAndOnboarding(unittest.TestCase):
    """The CPU/GPU choice must never outlive the backend that made it possible."""

    def setUp(self):
        self._saved = srv._session_token
        self._config = srv.CONFIG_PATH
        srv._session_token = None
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        srv.CONFIG_PATH = os.path.join(self.dir, "config.json")
        self.c = srv.app.test_client()

    def tearDown(self):
        srv._session_token = self._saved
        srv.CONFIG_PATH = self._config
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_fresh_install_is_not_onboarded(self):
        self.assertFalse(self.c.get("/api/config").get_json()["onboarded"])

    def test_default_device_follows_availability(self):
        # ~7x faster when it is there, so nobody should have to find a setting
        # to get it — but a build without a backend must default to CPU.
        real = transcriber.gpu_backend
        try:
            transcriber.gpu_backend = lambda cli: None
            self.assertEqual(self.c.get("/api/config").get_json()["device"], "cpu")
            transcriber.gpu_backend = lambda cli: {"name": "VULKAN", "devices": []}
            self.assertEqual(self.c.get("/api/config").get_json()["device"], "gpu")
        finally:
            transcriber.gpu_backend = real

    def test_gpu_index_falls_back_when_out_of_range(self):
        real = transcriber.gpu_backend
        transcriber.gpu_backend = lambda cli: {
            "name": "VULKAN", "devices": [{"index": 0, "name": "A"}, {"index": 1, "name": "B"}]}
        try:
            self.c.post("/api/config", json={"gpu_index": 1})
            self.assertEqual(self.c.get("/api/config").get_json()["gpu_index"], 1)
            self.c.post("/api/config", json={"gpu_index": 7})
            self.assertEqual(self.c.get("/api/config").get_json()["gpu_index"], 0)
        finally:
            transcriber.gpu_backend = real

    def test_onboarded_flag_persists(self):
        self.c.post("/api/config", json={"onboarded": True})
        self.assertTrue(self.c.get("/api/config").get_json()["onboarded"])

    def test_gpu_is_refused_without_a_gpu_backend(self):
        real = transcriber.gpu_backend
        transcriber.gpu_backend = lambda cli: None
        try:
            r = self.c.post("/api/config", json={"device": "gpu"})
            self.assertEqual(r.status_code, 400)
            self.assertIn("GPU", r.get_json()["reason"])
        finally:
            transcriber.gpu_backend = real

    def test_gpu_is_accepted_when_a_backend_exists(self):
        real = transcriber.gpu_backend
        transcriber.gpu_backend = lambda cli: {"name": "VULKAN", "device": "Test GPU"}
        try:
            self.assertTrue(self.c.post("/api/config", json={"device": "gpu"}).get_json()["ok"])
            self.assertEqual(self.c.get("/api/config").get_json()["device"], "gpu")
        finally:
            transcriber.gpu_backend = real

    def test_a_stale_gpu_preference_falls_back_to_cpu(self):
        # Saved on a build that had a GPU backend, then read on one that does not.
        real = transcriber.gpu_backend
        transcriber.gpu_backend = lambda cli: {"name": "VULKAN"}
        try:
            self.c.post("/api/config", json={"device": "gpu"})
        finally:
            transcriber.gpu_backend = real
        transcriber.gpu_backend = lambda cli: None
        try:
            self.assertEqual(self.c.get("/api/config").get_json()["device"], "cpu")
        finally:
            transcriber.gpu_backend = real

    def test_unknown_device_is_rejected(self):
        self.assertEqual(self.c.post("/api/config", json={"device": "tpu"}).status_code, 400)


class BackendProbe(unittest.TestCase):
    def test_probe_without_a_binary_is_empty(self):
        self.assertEqual(transcriber.probe_backends(None), [])
        self.assertIsNone(transcriber.gpu_backend(None))

    def test_parser_reads_the_loader_lines(self):
        out = (
            "load_backend: loaded CPU backend from /x/ggml-cpu-haswell.dll" + chr(10)
            + "load_backend: loaded Vulkan backend from /x/ggml-vulkan.dll" + chr(10)
        )
        found = transcriber._BACKEND_RE.findall(out)
        self.assertEqual([n for n, _ in found], ["CPU", "Vulkan"])

    def test_real_binary_reports_at_least_cpu(self):
        from app.binaries import get_whisper_cli
        cli = get_whisper_cli()
        if not cli:
            self.skipTest("this build has no whisper")
        names = [b["name"] for b in transcriber.probe_backends(cli)]
        self.assertIn("CPU", names)


class ReapTasks(unittest.TestCase):
    def setUp(self):
        srv.tasks.clear()

    def tearDown(self):
        srv.tasks.clear()

    def test_stale_finished_task_is_dropped(self):
        srv.tasks["old"] = {"done": True, "_done_at": time.time() - srv.TASK_TTL - 1}
        srv._reap_tasks()
        self.assertNotIn("old", srv.tasks)

    def test_recent_finished_task_is_kept(self):
        srv.tasks["new"] = {"done": True, "_done_at": time.time()}
        srv._reap_tasks()
        self.assertIn("new", srv.tasks)

    def test_running_task_is_never_dropped(self):
        srv.tasks["live"] = {"done": False}
        srv._reap_tasks()
        self.assertIn("live", srv.tasks)


if __name__ == "__main__":
    unittest.main()


class DataRootsAreSandboxed(unittest.TestCase):
    """If this fails, the rest of the suite is writing into the real profile."""

    def test_paths_point_at_the_sandbox(self):
        sandbox = os.path.join(tempfile.gettempdir(), "y2obi_tests")
        for path in (srv._APP_DATA, srv.DOWNLOAD_DIR, srv.MODELS_DIR, srv.CONFIG_PATH):
            self.assertTrue(os.path.normcase(path).startswith(os.path.normcase(sandbox)),
                            f"{path} escapes the sandbox")

    def test_the_real_profile_is_not_referenced(self):
        real = os.path.join(os.environ.get("APPDATA", "!none"), "Y2obi")
        self.assertNotEqual(os.path.normcase(srv._APP_DATA), os.path.normcase(real))


class ForceCpuFlag(unittest.TestCase):
    """`Y2obi.exe --cpu` has to win over the saved setting without changing it."""

    def setUp(self):
        self._saved = srv._session_token
        self._config = srv.CONFIG_PATH
        srv._session_token = None
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        srv.CONFIG_PATH = os.path.join(self.dir, "config.json")
        self.c = srv.app.test_client()
        self._gpu = transcriber.gpu_backend
        transcriber.gpu_backend = lambda cli: {"name": "VULKAN", "devices": []}

    def tearDown(self):
        transcriber.gpu_backend = self._gpu
        srv._session_token = self._saved
        srv.CONFIG_PATH = self._config
        os.environ.pop("Y2OBI_FORCE_CPU", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_without_the_flag_a_gpu_is_used(self):
        os.environ.pop("Y2OBI_FORCE_CPU", None)
        self.assertEqual(srv._device(), "gpu")

    def test_the_flag_forces_cpu(self):
        self.c.post("/api/config", json={"device": "gpu"})
        os.environ["Y2OBI_FORCE_CPU"] = "1"
        self.assertEqual(srv._device(), "cpu")

    def test_the_flag_does_not_rewrite_the_saved_setting(self):
        self.c.post("/api/config", json={"device": "gpu"})
        os.environ["Y2OBI_FORCE_CPU"] = "1"
        srv._device()
        import json as _json
        self.assertEqual(_json.load(open(srv.CONFIG_PATH))["device"], "gpu")


class AuthErrorSurfacing(unittest.TestCase):
    """"Sign in to confirm you're not a bot" has exactly one fix, so it must
    arrive at the page as something the page can act on."""

    def setUp(self):
        self._saved = srv._session_token
        srv._session_token = None
        self.c = srv.app.test_client()
        srv.tasks.clear()

    def tearDown(self):
        srv._session_token = self._saved
        srv.tasks.clear()

    def test_yt_dlp_phrasings_are_recognised(self):
        from app.downloader import looks_like_auth_error
        for text in (
            "ERROR: [youtube] abc: Sign in to confirm you're not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication.",
            "Sign in to confirm your age",
            "This video is private",
            "Join this channel to get access to members-only content",
        ):
            self.assertTrue(looks_like_auth_error(text), text[:40])

    def test_ordinary_failures_are_not_mistaken_for_it(self):
        from app.downloader import looks_like_auth_error
        for text in ("Video unavailable", "HTTP Error 404: Not Found",
                     "Unable to download webpage: timed out", ""):
            self.assertFalse(looks_like_auth_error(text), text[:40])

    def test_analyze_reports_the_fix_and_the_browsers(self):
        from app import downloader as dl
        real = srv._make_dl
        class _Boom:
            def get_info(self, url):
                raise dl.AuthRequired("YouTube wants to confirm you are signed in.")
        srv._make_dl = lambda: _Boom()
        try:
            r = self.c.post("/api/analyze", json={"url": "https://youtu.be/x"})
            body = r.get_json()
            self.assertEqual(r.status_code, 400)
            self.assertTrue(body["needs_cookies"])
            self.assertIsInstance(body["browsers"], list)
            self.assertNotIn("--cookies", body["error"])
        finally:
            srv._make_dl = real

    def test_a_failed_task_carries_the_flag(self):
        srv.tasks["t"] = {"percent": 0, "speed": 0, "eta": 0, "status": "Error",
                          "done": True, "cancelled": False, "path": None,
                          "error": "signed in", "needs_cookies": True}
        body = self.c.get("/api/progress/t").get_json()
        self.assertTrue(body["needs_cookies"])
        self.assertIn("browsers", body)

    def test_browser_list_only_reports_installed_ones(self):
        from app.downloader import installed_browsers
        for b in installed_browsers():
            self.assertIn(b["name"], ("firefox", "edge", "chrome", "brave"))
            self.assertIn("running", b)
            self.assertIn("needs_close", b)


class SessionSelfHealing(unittest.TestCase):
    """Sessions expire. The user approved a browser once; they should not have
    to repeat the ritual every time YouTube decides the cookies are stale."""

    def setUp(self):
        self._saved = srv._session_token
        self._config, self._cookies = srv.CONFIG_PATH, srv.COOKIES_PATH
        srv._session_token = None
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        srv.CONFIG_PATH = os.path.join(self.dir, "config.json")
        srv.COOKIES_PATH = os.path.join(self.dir, "cookies.txt")
        self.c = srv.app.test_client()
        self._export = srv.export_cookies_from_browser

    def tearDown(self):
        srv.export_cookies_from_browser = self._export
        srv._session_token = self._saved
        srv.CONFIG_PATH, srv.COOKIES_PATH = self._config, self._cookies
        shutil.rmtree(self.dir, ignore_errors=True)

    def _remember(self, browser):
        import json as _json
        with open(srv.CONFIG_PATH, "w", encoding="utf-8") as f:
            _json.dump({"cookie_browser": browser}, f)

    def test_no_remembered_browser_means_no_silent_retry(self):
        self.assertFalse(srv._refresh_cookies())

    def test_a_remembered_browser_is_re_read(self):
        self._remember("firefox")
        calls = []
        srv.export_cookies_from_browser = lambda b, p: calls.append((b, p))
        self.assertTrue(srv._refresh_cookies())
        self.assertEqual(calls[0][0], "firefox")

    def test_a_failing_export_does_not_explode(self):
        # Browser uninstalled, locked, or signed out: fall through to asking.
        self._remember("chrome")
        def boom(b, p):
            raise RuntimeError("locked")
        srv.export_cookies_from_browser = boom
        self.assertFalse(srv._refresh_cookies())

    @staticmethod
    def _write_session_jar(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File" + chr(10))
            f.write(chr(9).join([".youtube.com", "TRUE", "/", "TRUE", "0", "__Secure-1PSID", "abc123"]) + chr(10))

    def test_choosing_a_browser_remembers_it(self):
        srv.export_cookies_from_browser = self._write_session_jar and (
            lambda b, p: self._write_session_jar(p))
        r = self.c.post("/api/cookies/export", json={"browser": "firefox"})
        self.assertTrue(r.get_json()["ok"])
        import json as _json
        self.assertEqual(_json.load(open(srv.CONFIG_PATH))["cookie_browser"], "firefox")

    def test_analyze_retries_once_after_healing(self):
        from app import downloader as dl
        self._remember("firefox")
        srv.export_cookies_from_browser = lambda b, p: open(p, "w").close()
        state = {"n": 0}

        class _Flaky:
            def get_info(self, url):
                state["n"] += 1
                if state["n"] == 1:
                    raise dl.AuthRequired("signed in required")
                return {"title": "ok", "formats": [], "duration": 1}

        real = srv._make_dl
        srv._make_dl = lambda: _Flaky()
        try:
            r = self.c.post("/api/analyze", json={"url": "https://youtu.be/x"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(state["n"], 2)   # failed, healed, succeeded
        finally:
            srv._make_dl = real

    def test_it_gives_up_after_one_retry(self):
        from app import downloader as dl
        self._remember("firefox")
        srv.export_cookies_from_browser = lambda b, p: open(p, "w").close()

        class _Always:
            def get_info(self, url):
                raise dl.StreamsUnavailable("nothing usable")

        real = srv._make_dl
        srv._make_dl = lambda: _Always()
        try:
            r = self.c.post("/api/analyze", json={"url": "https://youtu.be/x"})
            self.assertEqual(r.status_code, 400)
            self.assertTrue(r.get_json()["needs_cookies"])
        finally:
            srv._make_dl = real


class JarValidation(unittest.TestCase):
    """A jar without a session is worse than no jar: sending a visitor id that
    YouTube has already throttled makes the block stick."""

    def setUp(self):
        self._saved = srv._session_token
        self._cookies, self._config = srv.COOKIES_PATH, srv.CONFIG_PATH
        srv._session_token = None
        self.dir = tempfile.mkdtemp(prefix="y2obi_t_")
        srv.COOKIES_PATH = os.path.join(self.dir, "cookies.txt")
        srv.CONFIG_PATH = os.path.join(self.dir, "config.json")
        self.c = srv.app.test_client()
        self._export = srv.export_cookies_from_browser

    def tearDown(self):
        srv.export_cookies_from_browser = self._export
        srv._session_token = self._saved
        srv.COOKIES_PATH, srv.CONFIG_PATH = self._cookies, self._config
        shutil.rmtree(self.dir, ignore_errors=True)

    def _jar(self, *names):
        with open(srv.COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File" + chr(10))
            for n in names:
                f.write(chr(9).join([".youtube.com", "TRUE", "/", "TRUE", "0", n, "v"]) + chr(10))

    def test_anonymous_cookies_are_not_a_session(self):
        # Exactly what a first visit leaves behind, and what a stale jar holds.
        self._jar("VISITOR_INFO1_LIVE", "YSC", "NID", "PREF")
        self.assertFalse(has_session_cookies(srv.COOKIES_PATH))

    def test_a_session_cookie_counts(self):
        self._jar("VISITOR_INFO1_LIVE", "__Secure-1PSID")
        self.assertTrue(has_session_cookies(srv.COOKIES_PATH))

    def test_a_missing_jar_is_not_a_session(self):
        self.assertFalse(has_session_cookies(srv.COOKIES_PATH))
        self.assertFalse(has_session_cookies(None))

    def test_status_reports_not_connected_for_an_anonymous_jar(self):
        self._jar("VISITOR_INFO1_LIVE", "YSC")
        self.assertFalse(self.c.get("/api/cookies/status").get_json()["loaded"])

    def test_an_anonymous_export_is_rejected_and_discarded(self):
        srv.export_cookies_from_browser = lambda b, p: self._jar("VISITOR_INFO1_LIVE")
        r = self.c.post("/api/cookies/export", json={"browser": "firefox"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no YouTube session", r.get_json()["reason"])
        self.assertFalse(os.path.exists(srv.COOKIES_PATH))

    def test_a_manual_jar_is_never_overwritten_by_the_heal(self):
        import json as _json
        with open(srv.CONFIG_PATH, "w", encoding="utf-8") as f:
            _json.dump({"cookie_browser": "file"}, f)
        called = []
        srv.export_cookies_from_browser = lambda b, p: called.append(b)
        self.assertFalse(srv._refresh_cookies())
        self.assertEqual(called, [])

    def test_the_downloader_gets_no_jar_when_there_is_no_session(self):
        self._jar("VISITOR_INFO1_LIVE", "YSC")
        self.assertIsNone(srv._make_dl().cookies)
        self._jar("__Secure-1PSID")
        self.assertEqual(srv._make_dl().cookies, srv.COOKIES_PATH)
