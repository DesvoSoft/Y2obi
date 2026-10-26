import hmac
import json
import os
import re
import secrets
import subprocess
import shutil
import sys
import tempfile
import threading
import time
import uuid

from flask import Flask, request, jsonify, send_file, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.downloader import (Downloader, DownloadError, AuthRequired,
                            StreamsUnavailable, PlaylistError,
                            export_cookies_from_browser, installed_browsers,
                            _parse_formats, QUALITY_MAP)
from app.downloader import has_session_cookies, parse_clip, ClipError
from app.downloader import playlist_ref, is_mix, is_video_id, safe_filename
from app import cleanup
from app import converter
from app import transcriber
from app.binaries import get_whisper_cli, get_deno
from app import diagnostics
from app import updates
from app.version import VERSION

_lock = threading.Lock()
tasks = {}
_model_locks = {}      # model name -> Lock, serialising downloads of that model
_model_downloads = {}  # model name -> task_id of the in-flight panel download

# How long a finished task stays pollable. The dict lives as long as the
# process, so without a sweep a long session leaks one entry per download.
TASK_TTL = 900

# Both roots can be redirected, which is what keeps a test run from writing into
# the real profile: point Y2OBI_HOME and Y2OBI_OUTPUT at a temp directory and the
# app touches nothing of the user's. tools/devserver.py does exactly that.
DOWNLOAD_DIR = os.environ.get("Y2OBI_OUTPUT") or os.path.join(
    os.path.expanduser("~"), "Downloads", "Y2obi")
_APP_DATA = os.environ.get("Y2OBI_HOME") or os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "Y2obi")
COOKIES_PATH = os.path.join(_APP_DATA, "cookies.txt")
MODELS_DIR = os.path.join(_APP_DATA, "models")
CONFIG_PATH = os.path.join(_APP_DATA, "config.json")

app = Flask(__name__, static_folder=None)

_ffmpeg_path = "ffmpeg"
_static_dir = None  # set by start_server()
_session_token = None  # minted by start_server(); None disables the check


@app.before_request
def _require_token():
    """Gate every /api/ route behind the per-session token.

    The server listens on loopback, but loopback is not a security boundary:
    any process on the machine can scan the random port and then drive
    downloads or DELETE /api/cookies. main.py opens the window at
    /?t=<token> and the page echoes the token back on every call. The token
    never appears in the served HTML, so a process that can only GET / still
    cannot reach the API.
    """
    if not request.path.startswith("/api/") or not _session_token:
        return None
    sent = request.headers.get("X-Y2obi-Token") or request.args.get("t", "")
    # compare_digest rejects str with non-ASCII, so compare bytes — otherwise a
    # header full of accents turns a 403 into a 500.
    if not hmac.compare_digest(sent.encode("utf-8", "ignore"),
                               _session_token.encode("ascii")):
        return jsonify({"error": "Unauthorized"}), 403
    return None


# Both mean the same thing in practice: YouTube wants a signed-in session.
BLOCKED = (AuthRequired, StreamsUnavailable)


def _refresh_cookies():
    """Re-read cookies from the browser the user already approved.

    Cookies expire, and when they do the app would otherwise fail with the same
    scary message it showed the first time and ask the user to do the same
    ritual again. Consent is given once; after that this heals it quietly.
    Returns True if a fresh jar was written.
    """
    browser = _config().get("cookie_browser")
    if not browser:
        return False
    if browser == "file":
        # A jar the user supplied by hand must never be overwritten by a browser
        # export they chose weeks earlier.
        return False
    if browser == "signin":
        # The sign-in window is not silent, so this cannot re-open it. Re-reading
        # the profile is still worth a try: the session there often outlives the
        # copy we exported.
        try:
            return bool(_harvest_signin_cookies())
        except Exception:
            return False
    try:
        os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)
        export_cookies_from_browser(browser, COOKIES_PATH)
        return True
    except Exception:
        # Browser uninstalled, running and locked, or the user signed out.
        # Falling through to the visible prompt is the honest outcome.
        return False


def _make_dl():
    # Only send a jar that proves a signed-in account. Anything else is a
    # visitor id, and handing YouTube one that has already been throttled makes
    # the block stick instead of lifting it.
    cookies = COOKIES_PATH if has_session_cookies(COOKIES_PATH) else None
    return Downloader(_ffmpeg_path, cookies=cookies, deno=get_deno())


def _progress_cb(task_id):
    def cb(pct, speed, eta):
        with _lock:
            s = tasks.get(task_id)
            if s:
                s["percent"] = pct
                s["speed"] = speed
                s["eta"] = eta
    return cb


def _status_cb(task_id):
    def cb(msg):
        with _lock:
            s = tasks.get(task_id)
            if s:
                if msg == "__already_exists__":
                    s.update(status="Already in ~/Downloads/Y2obi/ — skipped", done=True,
                             percent=100, already_exists=True, _done_at=time.time())
                else:
                    s["status"] = msg
    return cb


@app.route("/")
def index():
    return send_from_directory(_static_dir, "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(_static_dir, "static"), filename)


def _fmt_duration(dur):
    if not dur:
        return ""
    h, r = divmod(int(dur), 3600)
    m, s = divmod(r, 60)
    return (f"{h}h " if h else "") + f"{m}m {s:02d}s"


def _playlist_url(list_id):
    return f"https://www.youtube.com/playlist?list={list_id}"


def _playlist_response(url):
    """The JSON for a listed playlist, or the same error shapes analyze uses."""
    try:
        try:
            pl = _make_dl().get_playlist(url)
        except BLOCKED:
            if not _refresh_cookies():
                raise
            pl = _make_dl().get_playlist(url)
    except BLOCKED as e:
        return jsonify({"error": str(e), "needs_cookies": True,
                        "browsers": installed_browsers()}), 400
    except DownloadError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    entries = pl["entries"]
    first = next((e for e in entries if e["available"]), entries[0])
    return jsonify({
        "kind": "playlist",
        "id": pl["id"],
        "title": pl["title"],
        "channel": pl["channel"],
        "count": len(entries),
        "duration": _fmt_duration(sum(e["duration"] or 0 for e in entries)),
        # i.ytimg.com serves these by id, so there is no need to carry
        # yt-dlp's signed thumbnail URLs for every row.
        "thumbnail": f"https://i.ytimg.com/vi/{first['id']}/hqdefault.jpg",
        "entries": entries,
    })


@app.route("/api/playlist", methods=["POST"])
def playlist():
    """List a playlist by id: the "load the whole playlist" button on a video
    whose URL carried &list=."""
    list_id = str((request.json or {}).get("list_id", "")).strip()
    if not list_id or playlist_ref(_playlist_url(list_id))[0] != list_id:
        return jsonify({"error": "Playlist id required"}), 400
    return _playlist_response(_playlist_url(list_id))


@app.route("/api/analyze", methods=["POST"])
def analyze():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    list_id, has_video = playlist_ref(url)
    if list_id and not has_video:
        return _playlist_response(_playlist_url(list_id))
    try:
        try:
            info = _make_dl().get_info(url)
        except BLOCKED:
            # One silent self-heal first: the session the user already approved
            # has probably just expired, and re-reading it costs a second.
            if not _refresh_cookies():
                raise
            info = _make_dl().get_info(url)
    except PlaylistError:
        # yt-dlp saw a list where the URL named none we recognise: a channel's
        # Videos tab, say. That is still a list of videos.
        return _playlist_response(url)
    except BLOCKED as e:
        # The page turns this into one-click buttons for the browsers actually
        # installed, rather than sending the user hunting through settings.
        return jsonify({"error": str(e), "needs_cookies": True,
                        "browsers": installed_browsers()}), 400
    except DownloadError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    dstr = _fmt_duration(info.get("duration", 0))

    thumb = info.get("thumbnail", "")
    thumbnails = info.get("thumbnails") or []
    for t in reversed(thumbnails):
        u = t.get("url", "")
        if u.startswith("http") and t.get("width", 0) >= 320:
            thumb = u
            break

    qualities, has_audio = _parse_formats(info)

    return jsonify({
        "title": info.get("title", "Unknown"),
        "channel": info.get("channel", info.get("uploader", "")),
        "duration": dstr,
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "thumbnail": thumb,
        "qualities": qualities,
        "has_audio": has_audio,
        # A watch link that carries &list= is still that one video; the page
        # offers the list beside it rather than deciding for the user.
        "list_id": list_id if list_id and not is_mix(list_id) else None,
    })


@app.route("/api/cookies/status", methods=["GET"])
def cookies_status():
    # "Connected" has to mean the session works, not that a file exists.
    valid = has_session_cookies(COOKIES_PATH)
    return jsonify({
        "loaded": valid,
        "method": (_config().get("cookie_browser") or "uploaded") if valid else None,
    })


# Cookie names YouTube only sets once you are actually signed in.
SESSION_COOKIES = frozenset({
    "SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO",
    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PSIDTS", "__Secure-3PSIDTS",
})


def _signin_profile():
    """The Chromium profile the sign-in window writes.

    pywebview is given the parent directory as storage_path and WebView2 creates
    its profile in an EBWebView subdirectory of it, which is the level yt-dlp
    expects: Local State beside Default/Network/Cookies.
    """
    return os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
                        "Y2obi", "ytsession", "EBWebView")


def _harvest_signin_cookies():
    """Read the YouTube session out of the sign-in window's own profile.

    That profile is an ordinary Chromium one, so yt-dlp can read it, and
    crucially it is *ours*: it carries none of the App-Bound Encryption that has
    made Edge, Chrome and Brave impossible to decrypt from outside since v127,
    which is the "Failed to decrypt with DPAPI" wall users hit. The window runs
    in a separate process precisely so nothing holds the database open by now.
    """
    import http.cookiejar
    import yt_dlp.cookies

    profile = _signin_profile()
    if not os.path.isdir(profile):
        return 0
    jar = yt_dlp.cookies.extract_cookies_from_browser("chrome", profile=profile)
    # Merely visiting YouTube leaves cookies (VISITOR_INFO and friends), so
    # counting those would report success for someone who never signed in and
    # then fail on the very next video. Only a session cookie means anything.
    signed_in = [c for c in jar
                 if "youtube.com" in (c.domain or "") and c.name in SESSION_COOKIES]
    if not signed_in:
        return 0
    os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)
    moz = http.cookiejar.MozillaCookieJar(COOKIES_PATH)
    for cookie in jar:
        moz.set_cookie(cookie)
    moz.save(ignore_discard=True, ignore_expires=True)
    return len(signed_in)


@app.route("/api/cookies/signin", methods=["POST"])
def cookies_signin():
    """Open a sign-in window, wait for it, then take the session from it."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--signin"]
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, os.path.join(root, "main.py"), "--signin"]
    try:
        subprocess.run(cmd, timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False,
                        "reason": "The sign-in window was left open too long."}), 400
    except OSError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500

    try:
        found = _harvest_signin_cookies()
    except Exception as e:
        return jsonify({"ok": False, "reason": f"Could not read the session: {e}"}), 500
    if not found:
        return jsonify({"ok": False,
                        "reason": "No YouTube session found. Sign in to YouTube in "
                                  "the window, then close it."}), 400

    cfg = _config()
    cfg["cookie_browser"] = "signin"
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass
    return jsonify({"ok": True, "method": "signin", "cookies": found})


@app.route("/api/cookies/browsers", methods=["GET"])
def cookie_browsers():
    """Which browsers are installed, and which are holding their cookie DB open."""
    return jsonify({"browsers": installed_browsers()})


@app.route("/api/cookies/export", methods=["POST"])
def export_cookies():
    data = request.json or {}
    browser = data.get("browser", "").strip().lower()
    allowed = {"firefox", "edge", "brave", "chrome", "chromium", "opera", "vivaldi"}
    if browser not in allowed:
        return jsonify({"ok": False, "reason": f"Unknown browser: {browser}"}), 400
    try:
        os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)
        export_cookies_from_browser(browser, COOKIES_PATH)
        if not has_session_cookies(COOKIES_PATH):
            os.remove(COOKIES_PATH)
            return jsonify({"ok": False,
                            "reason": f"{browser.capitalize()} has no YouTube session. "
                                      "Sign in to YouTube there first, or use the "
                                      "sign-in window."}), 400
        # Remembering the choice is what lets _refresh_cookies heal an expiry
        # later without asking again.
        cfg = _config()
        cfg["cookie_browser"] = browser
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except OSError:
            pass
        return jsonify({"ok": True, "method": browser})
    except DownloadError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500


@app.route("/api/cookies", methods=["POST"])
def upload_cookies():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "reason": "No file"}), 400
    os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)
    f.save(COOKIES_PATH)
    if not has_session_cookies(COOKIES_PATH):
        os.remove(COOKIES_PATH)
        return jsonify({"ok": False,
                        "reason": "That file has no YouTube session in it. Export it "
                                  "while signed in to YouTube."}), 400
    cfg = _config()
    cfg["cookie_browser"] = "file"
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass
    return jsonify({"ok": True})


@app.route("/api/cookies", methods=["DELETE"])
def delete_cookies():
    if os.path.exists(COOKIES_PATH):
        os.remove(COOKIES_PATH)
    return jsonify({"ok": True})


def _model_entry(name, partials=None):
    fname, _url, size_mb = transcriber.MODELS[name]
    meta = transcriber.MODEL_LABELS[name]
    path = os.path.join(MODELS_DIR, fname)
    installed = os.path.isfile(path)
    return {
        "name": name,
        "label": meta["label"],
        "note": meta["note"],
        "size_mb": size_mb,
        "installed": installed,
        # What it actually takes on disk, which is what matters when deciding
        # whether to delete it.
        "disk_mb": round(os.path.getsize(path) / 1048576) if installed else 0,
        "offered": name in transcriber.UI_MODELS,
        # A cancelled download leaves a resumable .part; the user should be able
        # to see it and decide, not discover the disk usage by accident.
        "partial_mb": round((partials or {}).get(fname, 0) / 1048576),
    }


@app.route("/api/transcribe/models", methods=["GET"])
def transcribe_models():
    """The whole whisper catalogue, with what is cached and what is preferred.

    Every model is listed so the models panel can offer them; the page decides
    which ones become accuracy chips (the offered ones plus anything already
    downloaded).
    """
    if not get_whisper_cli():
        return jsonify({"available": False, "models": []})
    partials = cleanup.partial_downloads(MODELS_DIR)
    with _lock:
        # So a panel that was closed mid-download can re-attach to the task
        # instead of offering a second Download button.
        running = {n: tid for n, tid in _model_downloads.items()
                   if not tasks.get(tid, {}).get("done", True)}
    return jsonify({
        "available": True,
        "models": [_model_entry(n, partials) for n in transcriber.MODELS],
        "default": _config().get("model") or transcriber.DEFAULT_MODEL,
        "lang": _config().get("lang") or "auto",
        **_transcript_opts(),
        "dir": MODELS_DIR,
        "downloading": running,
        # Asked of whisper itself, not guessed from the hardware — see
        # transcriber.probe_backends.
        "backends": transcriber.probe_backends(get_whisper_cli()),
        "gpu": transcriber.gpu_backend(get_whisper_cli()),
        "device": _device(),
        "gpu_index": _gpu_index(),
        "onboarded": bool(_config().get("onboarded")),
    })


@app.route("/api/models/<name>", methods=["DELETE"])
def delete_model(name):
    """Drop a cached model. The catalogue is a fixed dict, so `name` can only
    ever select one of ours — a path never comes from the client."""
    entry = transcriber.MODELS.get(name)
    if not entry:
        return jsonify({"ok": False, "reason": "Unknown model"}), 404
    try:
        for path in (os.path.join(MODELS_DIR, entry[0]),
                     os.path.join(MODELS_DIR, entry[0] + ".part")):
            if os.path.exists(path):
                os.remove(path)
    except OSError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500
    return jsonify({"ok": True,
                    "model": _model_entry(name, cleanup.partial_downloads(MODELS_DIR))})


def _model_lock(name):
    """One lock per model, so two callers never append to the same `.part`.

    `ensure_model` resumes with an HTTP Range request onto `<model>.part`. Two
    of them at once — the models panel and a transcription that needs the same
    model, say — interleave their writes and cache a corrupt file that passes
    the short-file check and then fails every run afterwards.
    """
    with _lock:
        return _model_locks.setdefault(name, threading.Lock())


def _run_model_download(task_id, name):
    """Pull a model ahead of time, so the first transcription does not stall."""
    cancel = threading.Event()
    tr = transcriber.Transcriber(get_whisper_cli(), _ffmpeg_path, MODELS_DIR,
                                 cancel_event=cancel)
    _set(task_id, _tr=tr)
    try:
        with _model_lock(name):
            tr.ensure_model(
                name,
                progress_cb=lambda p: _set(task_id, percent=p),
                status_cb=lambda m: _set(task_id, status=m),
            )
        _set(task_id, done=True, percent=100, status="Model ready",
             _done_at=time.time())
    except Exception as e:
        msg = str(e)
        if "Cancelled" in msg:
            _set(task_id, cancelled=True, status="Cancelled", done=True,
                 _done_at=time.time())
        else:
            _set(task_id, error=msg, status="Error", done=True, _done_at=time.time())
    finally:
        _set(task_id, _tr=None)


@app.route("/api/models/<name>/download", methods=["POST"])
def download_model(name):
    if not transcriber.MODELS.get(name):
        return jsonify({"error": "Unknown model"}), 404
    if not get_whisper_cli():
        return jsonify({"error": "Transcription engine not available in this build"}), 400

    task_id = uuid.uuid4().hex
    with _lock:
        # Closing and reopening the panel must not start a second download of
        # the same model — hand back the one already running instead.
        running = _model_downloads.get(name)
        if running and not tasks.get(running, {}).get("done", True):
            return jsonify({"task_id": running, "already_running": True})
        _model_downloads[name] = task_id
        _reap_tasks()
        tasks[task_id] = {
            "percent": 0, "speed": 0, "eta": 0, "rate": None,
            "status": "Starting...", "done": False,
            "cancelled": False, "path": None, "kind": "model",
            "_dl": None, "_tr": None, "_cv": None,
        }
    threading.Thread(target=_run_model_download, args=(task_id, name),
                     daemon=True).start()
    return jsonify({"task_id": task_id})


def _config():
    """User preferences from %APPDATA%/Y2obi/config.json.

    Kept server-side rather than in localStorage because the server needs the
    default model too, and a corrupt or hand-edited file must never stop the
    app from starting.
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _device():
    """"cpu" or "gpu", never a preference the engine cannot honour.

    Defaults to the GPU when one is there: it is ~7x faster and nobody should
    have to find a setting to get that. A config left on "gpu" from a build that
    had a backend must not survive the backend going away, so that degrades to
    CPU rather than producing a broken run.
    """
    # `Y2obi.exe --cpu` overrides the saved setting for one run, which is how
    # you tell "the GPU is misbehaving" apart from "something else is wrong"
    # without touching the user's configuration.
    if os.environ.get("Y2OBI_FORCE_CPU"):
        return "cpu"
    gpu = transcriber.gpu_backend(get_whisper_cli())
    want = (_config().get("device") or ("gpu" if gpu else "cpu")).lower()
    return "gpu" if (want == "gpu" and gpu) else "cpu"


def _gpu_index():
    """Which adapter to use. A machine with a discrete and an integrated GPU
    would otherwise be at the mercy of enumeration order."""
    gpu = transcriber.gpu_backend(get_whisper_cli()) or {}
    devices = gpu.get("devices") or []
    try:
        idx = int(_config().get("gpu_index", 0))
    except (TypeError, ValueError):
        idx = 0
    return idx if any(d["index"] == idx for d in devices) else 0


def _save_config_key(key, value):
    """Persist one key without disturbing the rest of the file."""
    cfg = _config()
    cfg[key] = value
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


def _ts_interval():
    """Seconds between timestamps in the .txt, or 0 for none.

    A value saved by a build that offered a different set degrades to 0 rather
    than failing the transcription that is about to be written.
    """
    try:
        value = int(_config().get("ts_interval", 0))
    except (TypeError, ValueError):
        return 0
    return value if value in transcriber.TS_INTERVALS else 0


def _transcript_opts():
    """How the transcript files are written, read once when a job starts so a
    setting changed mid-playlist does not leave half the files one way."""
    cfg = _config()
    return {
        "ts_interval": _ts_interval(),
        # On unless turned off: every build before this one wrote the .srt.
        "srt": cfg.get("srt", True) is not False,
        "ts_ranges": bool(cfg.get("ts_ranges", False)),
    }


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = _config()
    return jsonify({
        "model": cfg.get("model") or transcriber.DEFAULT_MODEL,
        "lang": cfg.get("lang") or "auto",
        **_transcript_opts(),
        "device": _device(),
        "gpu_index": _gpu_index(),
        "onboarded": bool(cfg.get("onboarded")),
        "log_dir": diagnostics.log_dir(),
        "update_check": bool(cfg.get("update_check", True)),
        "version": VERSION,
    })


@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json or {}
    cfg = _config()
    if "model" in data:
        if not transcriber.MODELS.get(data["model"]):
            return jsonify({"ok": False, "reason": "Unknown model"}), 400
        cfg["model"] = data["model"]
    if "lang" in data:
        # whisper takes any ISO-639-1 code, so the list stays open — but junk
        # would only surface as a whisper failure minutes into a transcription.
        lang = str(data["lang"]).strip().lower()
        if lang != "auto" and not re.fullmatch(r"[a-z]{2}", lang):
            return jsonify({"ok": False, "reason": f"Unknown language: {lang}"}), 400
        cfg["lang"] = lang
    if "ts_interval" in data:
        # A closed set rather than any number: the transcript is written once and
        # kept, so a typo here would quietly produce a file stamped every second.
        try:
            ts = int(data["ts_interval"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "reason": "ts_interval must be a number"}), 400
        if ts not in transcriber.TS_INTERVALS:
            return jsonify({"ok": False,
                            "reason": f"Unsupported timestamp interval: {ts}"}), 400
        cfg["ts_interval"] = ts
    for key in ("srt", "ts_ranges"):
        if key in data:
            if not isinstance(data[key], bool):
                return jsonify({"ok": False, "reason": f"{key} must be true or false"}), 400
            cfg[key] = data[key]
    if "device" in data:
        device = str(data["device"]).strip().lower()
        if device not in ("cpu", "gpu"):
            return jsonify({"ok": False, "reason": f"Unknown device: {device}"}), 400
        if device == "gpu" and not transcriber.gpu_backend(get_whisper_cli()):
            return jsonify({"ok": False,
                            "reason": "This build has no GPU backend"}), 400
        cfg["device"] = device
    if "gpu_index" in data:
        try:
            cfg["gpu_index"] = int(data["gpu_index"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "reason": "gpu_index must be a number"}), 400
    if "update_check" in data:
        cfg["update_check"] = bool(data["update_check"])
    if "onboarded" in data:
        cfg["onboarded"] = bool(data["onboarded"])
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500
    return jsonify({"ok": True, "config": cfg})


def _active_job():
    """Task id of the running media job, or None. Caller must hold _lock.

    Downloads, conversions and transcriptions all saturate the machine — two
    whisper runs at once give each half the cores and finish no sooner. The page
    only ever tracks one task id too, so a second job would be orphaned: still
    burning CPU, with no way left to cancel it. Model downloads are excluded;
    they are network-only and already deduped per model.
    """
    for tid, t in tasks.items():
        if not t.get("done") and t.get("kind") != "model":
            return tid
    return None


def _reap_tasks():
    """Drop tasks that finished over TASK_TTL ago. Caller must hold _lock."""
    now = time.time()
    stale = [tid for tid, s in tasks.items()
             if s.get("done") and now - s.get("_done_at", now) > TASK_TTL]
    for tid in stale:
        del tasks[tid]


def _set(task_id, **kw):
    with _lock:
        t = tasks.get(task_id)
        if t:
            t.update(kw)


def _fetch_audio(task_id, url, tmp_dir, clip, cancel, report, say):
    """Download the audio of `url` into `tmp_dir`, ready for whisper."""
    say("Downloading audio...")
    return _with_downloader(task_id, cancel, report, lambda _msg: say("Downloading audio..."),
                            say, lambda dl: dl.download_audio_raw(url, tmp_dir, clip))


def _with_downloader(task_id, cancel, report, on_status, say, run):
    """Run `run(downloader)` with progress, cancel and a fresh session wired in.

    Retries once on a refreshed session, same as a plain download: the browser
    the user approved has probably just expired.
    """
    def attempt():
        dl = _make_dl()
        _set(task_id, _dl=dl)

        def on_progress(pct, speed, eta):
            # A Downloader clears its own cancel flag when a download starts, so
            # a Cancel landing between two videos of a playlist would be lost
            # without re-applying it here.
            if cancel.is_set():
                dl.cancel()
            report(pct, eta)
            _set(task_id, speed=speed)

        dl.set_callbacks(progress=on_progress, status=on_status)
        if cancel.is_set():
            raise transcriber.Cancelled()
        return run(dl)

    try:
        try:
            return attempt()
        except BLOCKED:
            if cancel.is_set() or not _refresh_cookies():
                raise
            say("Reconnecting to YouTube...")
            return attempt()
    finally:
        _set(task_id, _dl=None, speed=0)


def _download_item(task_id, url, out_dir, name, fmt, quality, cancel, report, say):
    """One video of a playlist download, saved as `name` in `out_dir`."""
    def on_status(msg):
        # The batch does its own skip-if-present check and reports it per row.
        if msg != "__already_exists__":
            say(msg)

    def run(dl):
        if fmt == "mp4":
            return dl.download_mp4(url, out_dir, quality, name=name)
        if fmt == "webm":
            return dl.download_webm(url, out_dir, quality, name=name)
        return dl.download_mp3(url, out_dir, name=name)

    say("Downloading...")
    return _with_downloader(task_id, cancel, report, on_status, say, run)


def _transcribe_audio(tr, cancel, audio_path, model_path, out_prefix, lang, opts,
                      report, say, gpu):
    """Whisper over one audio file. `gpu` is {"use": bool}, shared across a
    playlist so a GPU that failed once is not retried on every video."""
    started = [time.time()]

    def on_text_pct(p):
        elapsed = time.time() - started[0]
        eta = int(elapsed * (100.0 - p) / p) if p > 1 else 0
        report(p, eta)

    say("Transcribing...")
    kw = dict(lang=lang or "auto", progress_cb=on_text_pct, status_cb=say, **opts)
    if not gpu["use"]:
        return tr.transcribe(audio_path, model_path, out_prefix, use_gpu=False, **kw)
    try:
        return tr.transcribe(audio_path, model_path, out_prefix,
                             use_gpu=True, gpu_index=_gpu_index(), **kw)
    except Exception as e:
        # A GPU that initialises but then fails mid-run (old driver, VRAM
        # pressure) must not cost the user the whole job.
        if "Cancelled" in str(e) or cancel.is_set():
            raise
        gpu["use"] = False
        say("GPU failed — retrying on CPU...")
        started[0] = time.time()
        return tr.transcribe(audio_path, model_path, out_prefix, use_gpu=False, **kw)


def _run_transcribe(task_id, src, model, lang, is_file=False, opts=None,
                    clip=None):
    """Run whisper over `src` and write .txt (+ .srt) to DOWNLOAD_DIR.

    `src` is a YouTube URL, or a local path when `is_file` — a local file needs
    no download, so that phase drops out of the progress split entirely.

    One progress bar covers the phases, so each is mapped onto its own slice of
    0-100 instead of resetting the bar. The model download only happens once
    ever, so it gets a slice only when it is actually needed.
    """
    if not transcriber.MODELS.get(model):
        model = transcriber.DEFAULT_MODEL

    cancel = threading.Event()
    tr = transcriber.Transcriber(get_whisper_cli(), _ffmpeg_path, MODELS_DIR,
                                 cancel_event=cancel)
    _set(task_id, _tr=tr)

    have_model = tr.has_model(model)
    if is_file:
        spans = {"model": (0, 0), "audio": (0, 0), "text": (0, 100)} if have_model \
            else {"model": (0, 40), "audio": (40, 40), "text": (40, 100)}
    elif have_model:
        spans = {"model": (0, 0), "audio": (0, 10), "text": (10, 100)}
    else:
        spans = {"model": (0, 40), "audio": (40, 50), "text": (50, 100)}

    def report(phase, pct, eta=0):
        lo, hi = spans[phase]
        _set(task_id, percent=lo + (hi - lo) * max(0.0, min(100.0, pct)) / 100.0, eta=eta)

    tmp_dir = tempfile.mkdtemp(prefix="y2obi_src_")
    try:
        with _model_lock(model):
            model_path = tr.ensure_model(
                model,
                progress_cb=lambda p: report("model", p),
                status_cb=lambda m: _set(task_id, status=m),
            )
        if cancel.is_set():
            raise transcriber.Cancelled()

        say = lambda m: _set(task_id, status=m)  # noqa: E731
        if is_file:
            # ffmpeg reads the user's file directly; Transcriber.to_wav does the
            # decode, so there is nothing to fetch and nothing to clean up.
            audio_path = src
        else:
            audio_path = _fetch_audio(task_id, src, tmp_dir, clip, cancel,
                                      lambda pct, eta: report("audio", pct, eta), say)
        if cancel.is_set():
            raise transcriber.Cancelled()

        stem = os.path.splitext(os.path.basename(audio_path))[0]
        out_prefix = os.path.join(DOWNLOAD_DIR, stem)
        files = _transcribe_audio(tr, cancel, audio_path, model_path, out_prefix,
                                  lang, opts or {}, lambda p, eta: report("text", p, eta),
                                  say, {"use": _device() == "gpu"})
        _set(task_id, path=files[0], extra_files=files[1:], done=True, percent=100,
             eta=0, status="Complete", _done_at=time.time())
    except Exception as e:
        msg = str(e)
        if "Cancelled" in msg:
            _set(task_id, cancelled=True, status="Cancelled", done=True,
                 _done_at=time.time())
        else:
            _set(task_id, error=msg, status="Error", done=True,
                 needs_cookies=isinstance(e, BLOCKED), _done_at=time.time())
    finally:
        _set(task_id, _tr=None, _dl=None)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# A playlist can run to thousands of videos, which is fine; past this a broken
# client is likelier than a real request.
BATCH_MAX = 5000


def _short_error(e):
    """First line of an error, capped. yt-dlp's are walls of text, and a list of
    forty failures needs one line each, not forty tracebacks."""
    line = (str(e).strip().splitlines() or [""])[0]
    return line[:300] or e.__class__.__name__


# What a finished download of each format leaves behind. mkv is where yt-dlp
# lands when the streams it picked cannot be merged into the asked container.
_BATCH_EXTS = {"txt": (".txt",), "mp3": (".mp3",), "mp4": (".mp4", ".mkv"),
               "webm": (".webm", ".mkv")}


def _batch_name(stem, fmt, quality):
    """The file name a playlist item is saved under, without its extension.
    Same rule as a single download: a capped quality is part of the name."""
    if fmt in ("mp4", "webm") and quality != "Best":
        return f"{stem} [{quality}]"
    return stem


def _run_batch(task_id, items, out_dir, model, lang, opts, fmt="txt", quality="Best"):
    """Work through a playlist selection one video at a time, into `out_dir`.

    `fmt` is "txt" to transcribe, or mp4/webm/mp3 to download. One video
    failing must not cost the rest: it is marked and the queue moves on. A
    video whose file is already there is skipped, so running the same playlist
    again picks up where a cancelled or failed run stopped.
    """
    transcribing = fmt == "txt"
    if not transcriber.MODELS.get(model):
        model = transcriber.DEFAULT_MODEL

    cancel = threading.Event()
    tr = transcriber.Transcriber(get_whisper_cli(), _ffmpeg_path, MODELS_DIR,
                                 cancel_event=cancel)
    _set(task_id, _tr=tr)
    n = len(items)
    # The model download happens once ever, so it gets a slice of the bar only
    # when it is actually needed. The Transcriber is made for a download batch
    # too: its event is what the Cancel route sets.
    lo = 0 if not transcribing or tr.has_model(model) else 10
    clock = {"start": None, "skipped": 0}

    def overall(i, frac):
        """Bar position with `i` videos finished and `frac` of the next one."""
        pos = (i + frac) / n
        eta = 0
        worked = (i + frac - clock["skipped"]) / n
        if clock["start"] and worked > 0.01:
            eta = int((time.time() - clock["start"]) * (1 - pos) / worked)
        _set(task_id, percent=lo + (100 - lo) * pos, eta=eta)

    def mark(i, **kw):
        with _lock:
            t = tasks.get(task_id)
            if t:
                t["batch"][i].update(kw)
                # Lets /api/progress leave the per-video list out of every poll
                # in which nothing in it changed -- see progress().
                t["batch_rev"] = t.get("batch_rev", 0) + 1

    counts = {"done": 0, "skipped": 0, "error": 0}
    verb = "transcribed" if transcribing else "downloaded"

    def summary():
        # "0 transcribed" only says something when nothing else happened.
        bits = [f"{counts['done']} {verb}"] if counts["done"] or not counts["skipped"] else []
        if counts["skipped"]:
            bits.append(f"{counts['skipped']} already there, skipped")
        if counts["error"]:
            bits.append(f"{counts['error']} failed")
        return " · ".join(bits)

    gpu = {"use": _device() == "gpu"}
    try:
        model_path = None
        if transcribing:
            with _model_lock(model):
                model_path = tr.ensure_model(
                    model,
                    progress_cb=lambda p: _set(task_id, percent=lo * p / 100.0),
                    status_cb=lambda m: _set(task_id, status=m),
                )
        os.makedirs(out_dir, exist_ok=True)
        clock["start"] = time.time()

        for i, item in enumerate(items):
            if cancel.is_set():
                raise transcriber.Cancelled()
            tag = f"Video {i + 1} of {n}"
            say = lambda m, _t=tag: _set(task_id, status=f"{_t} · {m}")  # noqa: E731
            _set(task_id, index=i)
            prefix = os.path.join(out_dir, _batch_name(item["stem"], fmt, quality))
            if any(os.path.exists(prefix + ext) for ext in _BATCH_EXTS[fmt]):
                mark(i, state="skipped")
                counts["skipped"] += 1
                clock["skipped"] += 1
                overall(i + 1, 0)
                continue

            mark(i, state="running")
            url = f"https://www.youtube.com/watch?v={item['id']}"
            tmp_dir = tempfile.mkdtemp(prefix="y2obi_src_")
            try:
                if not transcribing:
                    _download_item(task_id, url, out_dir, item["stem"], fmt, quality,
                                   cancel, lambda pct, _eta, _i=i: overall(_i, pct / 100.0),
                                   say)
                else:
                    # Downloading audio is a small part of a video's time next
                    # to whisper, so it gets a tenth of that video's share.
                    audio = _fetch_audio(
                        task_id, url, tmp_dir,
                        None, cancel, lambda pct, _eta, _i=i: overall(_i, 0.1 * pct / 100.0),
                        say)
                    if cancel.is_set():
                        raise transcriber.Cancelled()
                    _transcribe_audio(
                        tr, cancel, audio, model_path, prefix, lang, opts,
                        lambda p, _eta, _i=i: overall(_i, 0.1 + 0.9 * p / 100.0), say, gpu)
                mark(i, state="done")
                counts["done"] += 1
            except Exception as e:
                if cancel.is_set() or "Cancelled" in str(e):
                    mark(i, state="pending")
                    raise transcriber.Cancelled()
                mark(i, state="error", error=_short_error(e))
                counts["error"] += 1
                if isinstance(e, BLOCKED):
                    _set(task_id, needs_cookies=True)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            overall(i + 1, 0)

        # Nothing at all came out: that is an error, not a summary of zeros.
        first = None
        if not counts["done"] and not counts["skipped"]:
            with _lock:
                first = next((t["error"] for t in tasks.get(task_id, {}).get("batch", [])
                              if t.get("error")), None)
        _set(task_id, path=out_dir, done=True, percent=100, eta=0,
             status=summary(), error=first, _done_at=time.time())
    except Exception as e:
        if "Cancelled" in str(e):
            _set(task_id, path=out_dir if os.path.isdir(out_dir) else None,
                 cancelled=True, status="Cancelled · " + summary(), done=True,
                 _done_at=time.time())
        else:
            _set(task_id, error=str(e), status="Error", done=True,
                 _done_at=time.time())
    finally:
        _set(task_id, _tr=None, _dl=None)


@app.route("/api/batch", methods=["POST"])
def start_batch():
    """Queue the chosen videos of a playlist: transcribe or download them.

    Only video ids come from the page, never URLs: every one is rebuilt here
    as a youtube.com watch link, so this cannot be pointed anywhere else.
    """
    data = request.json or {}
    raw = data.get("items")
    if not isinstance(raw, list) or not raw:
        return jsonify({"error": "Pick at least one video"}), 400
    if len(raw) > BATCH_MAX:
        return jsonify({"error": f"At most {BATCH_MAX} videos at a time"}), 400
    fmt = data.get("format", "txt")
    if fmt not in _BATCH_EXTS:
        return jsonify({"error": f"Unknown format: {fmt}"}), 400
    quality = data.get("quality", "Best")
    if quality not in QUALITY_MAP:
        return jsonify({"error": f"Unknown quality: {quality}"}), 400
    if fmt == "txt" and not get_whisper_cli():
        return jsonify({"error": "Transcription engine not available in this build"}), 400

    items, seen = [], set()
    for it in raw:
        if not isinstance(it, dict) or not is_video_id(it.get("id")):
            return jsonify({"error": "Not a YouTube video id"}), 400
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        try:
            index = max(1, int(it.get("index") or 0))
        except (TypeError, ValueError):
            index = 0
        items.append({"id": it["id"], "title": str(it.get("title") or it["id"])[:300],
                      "index": index or len(items) + 1})

    # Numbered by position in the playlist, padded to the playlist's length
    # rather than the selection's, so the name of a video does not depend on
    # which others were picked with it -- the skip-if-done check relies on that.
    try:
        total = int(data.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    width = max(2, len(str(max([total] + [it["index"] for it in items]))))
    for it in items:
        it["stem"] = f"{it['index']:0{width}d} - {safe_filename(it['title'], it['id'])}"

    out_dir = os.path.join(DOWNLOAD_DIR, safe_filename(data.get("playlist_title"), "Playlist"))
    task_id = uuid.uuid4().hex
    with _lock:
        _reap_tasks()
        busy = _active_job()
        if busy:
            return jsonify({
                "error": "Another job is already running. Wait for it to finish, "
                         "or cancel it first.",
                "busy_task_id": busy,
            }), 409
        tasks[task_id] = {
            "percent": 0, "speed": 0, "eta": 0, "rate": None,
            "status": "Starting...", "done": False,
            "cancelled": False, "path": None, "kind": "media",
            "_dl": None, "_tr": None, "_cv": None,
            "index": 0,
            "batch": [{"id": it["id"], "state": "pending", "error": None} for it in items],
        }
    threading.Thread(
        target=_run_batch,
        args=(task_id, items, out_dir,
              data.get("model") or transcriber.DEFAULT_MODEL,
              data.get("lang") or "auto", _transcript_opts(), fmt, quality),
        daemon=True,
    ).start()
    return jsonify({"task_id": task_id, "folder": out_dir})


def _run_convert(task_id, path, fmt, height):
    """Convert a local file the user picked, straight through ffmpeg."""
    cancel = threading.Event()
    conv = converter.Converter(_ffmpeg_path, cancel_event=cancel)
    _set(task_id, _cv=conv)

    started = time.time()

    def on_pct(p):
        elapsed = time.time() - started
        eta = int(elapsed * (100.0 - p) / p) if p > 1 else 0
        _set(task_id, percent=p, eta=eta)

    # ffmpeg's realtime factor. Output bytes/s would be meaningless here — the
    # question a user has is "how much faster than watching it is this going".
    def on_rate(x):
        _set(task_id, rate=f"{x:.1f}x" if x < 100 else f"{x:.0f}x")

    try:
        info = conv.probe(path)
        _set(task_id, status="Converting...")
        if fmt == "mp3":
            out = conv.to_mp3(path, DOWNLOAD_DIR, progress_cb=on_pct, info=info,
                              rate_cb=on_rate)
        else:
            out = conv.to_mp4(path, DOWNLOAD_DIR, height=height,
                              progress_cb=on_pct, info=info, rate_cb=on_rate)
        _set(task_id, path=out, done=True, percent=100, eta=0,
             status="Complete", _done_at=time.time())
    except Exception as e:
        msg = str(e)
        if "Cancelled" in msg:
            _set(task_id, cancelled=True, status="Cancelled", done=True,
                 _done_at=time.time())
        else:
            _set(task_id, error=msg, status="Error", done=True, _done_at=time.time())
    finally:
        _set(task_id, _cv=None)


@app.route("/api/analyze_file", methods=["POST"])
def analyze_file():
    """Probe a local file the user picked in the native dialog.

    The path only ever arrives from `Api.pick_file` in main.py, but it is still
    a client-supplied string, so it is checked before ffmpeg ever sees it.
    """
    path = (request.json or {}).get("path", "").strip()
    if not path:
        return jsonify({"error": "Path required"}), 400
    if not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 400
    if not converter.is_media(path):
        return jsonify({"error": "Not an audio or video file"}), 400
    try:
        info = converter.Converter(_ffmpeg_path).probe(path)
    except converter.ConvertError as e:
        return jsonify({"error": str(e)}), 400
    info["path"] = path
    return jsonify(info)


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp4")
    quality = data.get("quality", "Best")
    is_file = data.get("source") == "file"
    path = (data.get("path") or "").strip()

    if is_file:
        if not path or not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 400
        if not converter.is_media(path):
            return jsonify({"error": "Not an audio or video file"}), 400
        if fmt == "webm":
            # VP9 re-encoding a local file takes hours for no gain over mp4.
            return jsonify({"error": "WEBM is only available for YouTube downloads"}), 400
    elif not url:
        return jsonify({"error": "URL required"}), 400

    if fmt not in ("mp4", "mp3", "webm", "txt"):
        return jsonify({"error": f"Unknown format: {fmt}"}), 400

    # Rejected here rather than deep inside yt-dlp: a bad time silently
    # downloading the wrong part of a three-hour video is the failure worth
    # preventing, and the message has to reach the user before the job starts.
    try:
        clip = parse_clip(data.get("clip_start"), data.get("clip_end"))
    except ClipError as e:
        return jsonify({"error": str(e)}), 400
    if clip and is_file:
        # Local files go through Converter, which has no range support yet.
        return jsonify({"error": "Trimming is only available for YouTube downloads"}), 400
    if fmt == "txt" and not get_whisper_cli():
        return jsonify({"error": "Transcription engine not available in this build"}), 400

    task_id = uuid.uuid4().hex
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    with _lock:
        _reap_tasks()
        busy = _active_job()
        if busy:
            return jsonify({
                "error": "Another job is already running. Wait for it to finish, "
                         "or cancel it first.",
                "busy_task_id": busy,
            }), 409
        tasks[task_id] = {
            "percent": 0, "speed": 0, "eta": 0, "rate": None,
            "status": "Starting...", "done": False,
            "cancelled": False, "path": None, "kind": "media",
            "_dl": None, "_tr": None, "_cv": None,
        }

    if fmt == "txt":
        threading.Thread(
            target=_run_transcribe,
            args=(task_id, path if is_file else url,
                  data.get("model") or transcriber.DEFAULT_MODEL,
                  data.get("lang") or "auto", is_file, _transcript_opts(), clip),
            daemon=True,
        ).start()
        return jsonify({"task_id": task_id})

    if is_file:
        height = data.get("height")
        threading.Thread(
            target=_run_convert,
            args=(task_id, path, fmt, int(height) if height else None),
            daemon=True,
        ).start()
        return jsonify({"task_id": task_id})

    def _run():
        dl = _make_dl()
        _set(task_id, _dl=dl)
        dl.set_callbacks(progress=_progress_cb(task_id), status=_status_cb(task_id))

        def _go(d):
            if fmt == "mp4":
                return d.download_mp4(url, DOWNLOAD_DIR, quality, clip)
            if fmt == "webm":
                return d.download_webm(url, DOWNLOAD_DIR, quality, clip)
            return d.download_mp3(url, DOWNLOAD_DIR, clip)

        try:
            try:
                path = _go(dl)
            except BLOCKED:
                # One silent retry on a refreshed session, same as analyze: the
                # browser the user approved has probably just expired.
                if not _refresh_cookies():
                    raise
                _set(task_id, status="Reconnecting to YouTube...")
                path = _go(_make_dl())
            _set(task_id, path=path, done=True, percent=100, status="Complete",
                 _done_at=time.time())
        except Exception as e:
            if "Cancelled" in str(e):
                _set(task_id, cancelled=True, status="Cancelled", done=True,
                     _done_at=time.time())
            else:
                _set(task_id, error=str(e), status="Error", done=True,
                     needs_cookies=isinstance(e, BLOCKED), _done_at=time.time())

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id})


@app.route("/api/progress/<task_id>")
def progress(task_id):
    with _lock:
        task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    resp = {
        "percent": task["percent"],
        "speed": task["speed"],
        "rate": task.get("rate"),
        "eta": task["eta"],
        "status": task["status"],
        "done": task["done"],
        "cancelled": task["cancelled"],
        "error": task.get("error"),
        "already_exists": task.get("already_exists", False),
    }
    # Only once done: a playlist marks this on its first blocked video and keeps
    # going, and listing browsers spawns tasklist, which no 500 ms poll should.
    if task.get("needs_cookies") and task["done"]:
        resp["needs_cookies"] = True
        resp["browsers"] = installed_browsers()
    if "batch" in task:
        # The per-video list is the only part of a poll that grows with the
        # playlist. The page sends back the revision it already has, and the
        # list is left out until something in it actually changes.
        rev = task.get("batch_rev", 0)
        resp["batch"] = {"index": task.get("index", 0), "rev": rev}
        if request.args.get("rev") != str(rev):
            with _lock:
                resp["batch"]["items"] = [{"state": b["state"], "error": b["error"]}
                                          for b in task["batch"]]
        # Partial results are still results: a cancelled or half-failed
        # playlist has a folder worth opening.
        if task.get("path"):
            resp["folder"] = task["path"]
    if task["done"] and task.get("path") and not task.get("error") and not task["cancelled"]:
        resp["file_url"] = f"/api/file/{task_id}"
        resp["filename"] = os.path.basename(task["path"])
        resp["local_path"] = task["path"]
        extra = task.get("extra_files") or []
        if extra:
            resp["extra_filenames"] = [os.path.basename(p) for p in extra]
    return jsonify(resp)


@app.route("/api/cancel/<task_id>", methods=["POST"])
def cancel(task_id):
    with _lock:
        task = tasks.get(task_id)
        # A cancel racing a task that just finished must not rewrite its result.
        if task and not task["done"]:
            dl = task.get("_dl")
            if dl:
                dl.cancel()
            tr = task.get("_tr")
            if tr:
                tr.cancel()
            cv = task.get("_cv")
            if cv:
                cv.cancel()
            task["status"] = "Cancelling..."
    return jsonify({"ok": True})


@app.route("/api/file/<task_id>")
def serve_file(task_id):
    with _lock:
        task = tasks.get(task_id)
    if not task or not task.get("path") or not os.path.exists(task["path"]):
        return jsonify({"error": "File not found"}), 404
    return send_file(task["path"], as_attachment=True, download_name=os.path.basename(task["path"]))


def _explorer_command(target):
    """Build the explorer.exe command line for `target`.

    A list must not be passed to Popen here: subprocess would apply the MSVC
    quoting rules to each argument, wrapping `/select,C:\\...\\My Video.mp4` in
    quotes when the filename has a space. explorer.exe parses its command line
    with its own rules, so a quoted `/select,` token is never recognised and it
    silently opens the user's Documents folder instead. Hand-build the command
    line with the quotes around the path only.
    """
    norm = os.path.normpath(target)
    if os.path.isdir(norm):
        return f'explorer "{norm}"'
    return f'explorer /select,"{norm}"'


@app.route("/api/update")
def update_status():
    """What the background check found. Never triggers one itself.

    The page polls this once on load; a route that could start a network call
    would make the first paint wait on GitHub.
    """
    if not _config().get("update_check", True):
        return jsonify({"checked": False, "available": False, "disabled": True})
    return jsonify(updates.cached())


@app.route("/api/diagnostics")
def diagnostics_text():
    """The tail of the log plus the build facts, ready to paste into an issue.

    "It does not work" is not actionable and neither is talking someone through
    where %LOCALAPPDATA% is. This is the same content the log already holds --
    scrubbed on the way in, so the session token is not in it either.
    """
    lines = [f"Y2obi {VERSION}", f"frozen: {bool(getattr(sys, 'frozen', False))}",
             f"python: {sys.version.split()[0]}"]
    try:
        import platform
        lines.append(f"windows: {platform.platform()}")
    except Exception:
        pass
    lines.append(f"whisper: {get_whisper_cli() or 'not in this build'}")
    lines.append(f"device: {_device()}")
    try:
        with open(diagnostics.log_path(), encoding="utf-8", errors="replace") as f:
            tail = f.read().splitlines()[-120:]
    except OSError as e:
        tail = [f"(no log could be read: {e})"]
    body = ("\n".join(lines) + "\n\n--- last 120 log lines ---\n"
            + "\n".join(tail))
    return jsonify({"text": body})


@app.route("/api/open_logs", methods=["POST"])
def open_logs():
    """Reveal the log folder. No path comes from the client."""
    import subprocess
    try:
        target = diagnostics.log_dir()
        os.makedirs(target, exist_ok=True)
        subprocess.Popen(_explorer_command(target),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/open_folder", methods=["POST"])
def open_folder():
    """Open the output folder in Explorer — desktop only."""
    import subprocess
    try:
        # Explorer silently opens Documents when handed a path that does not
        # exist, so create the folder first rather than let the user chase a
        # phantom location before the first download.
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        subprocess.Popen(_explorer_command(DOWNLOAD_DIR),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/open_file/<task_id>", methods=["POST"])
def open_file(task_id):
    """Open a finished download with its default app, or reveal it in Explorer.

    The path is read out of the task record — the client only names a task, so
    this cannot be pointed at an arbitrary file on disk.
    """
    with _lock:
        task = tasks.get(task_id)
    path = task.get("path") if task else None
    if not path or not os.path.exists(path):
        return jsonify({"ok": False, "reason": "File not found"}), 404

    import subprocess
    try:
        if request.args.get("reveal"):
            subprocess.Popen(_explorer_command(path),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.startfile(path)
    except (AttributeError, OSError) as e:
        return jsonify({"ok": False, "reason": str(e)}), 500
    return jsonify({"ok": True})


def start_server(ffmpeg_path, static_dir, port=0):
    """Start Flask on a random loopback port. Returns (port, session_token)."""
    global _ffmpeg_path, _static_dir, _session_token
    _ffmpeg_path = ffmpeg_path
    _static_dir = static_dir
    _session_token = secrets.token_urlsafe(32)

    # Warm the backend probe before Flask starts serving. It spawns whisper-cli,
    # and doing that inside a request thread of a windowed frozen exe hung the
    # server hard: /api/transcribe/models never returned and every later
    # connection piled up in CLOSE_WAIT. It is a constant for the process, so
    # there is no reason to pay for it per request.
    try:
        transcriber.probe_backends(get_whisper_cli())
    except Exception:
        pass

    # Off the request path and off the startup path: a daemon thread that the
    # UI later asks for a cached answer. The app behaves the same offline.
    cfg = _config()
    if cfg.get("update_check", True):
        updates.check_in_background(
            current=VERSION,
            last_checked=cfg.get("update_checked_at", 0),
            save_cb=lambda ts: _save_config_key("update_checked_at", ts))

    import socket
    if port == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

    ready = threading.Event()

    def _run():
        # Werkzeug dev server — loopback only, single process
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # A frozen exe picks a random port and mints a token that is deliberately
    # never printed, which also makes it impossible to drive the built app from
    # a test harness -- and the built app is the only place several of this
    # project's bugs have ever appeared. Setting Y2OBI_SESSION_FILE asks the
    # server to drop the pair in that file. Nothing writes it otherwise, so a
    # released run leaves no credential on disk.
    session_file = os.environ.get("Y2OBI_SESSION_FILE")
    if session_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(session_file)), exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump({"port": port, "token": _session_token}, f)
        except OSError as e:
            print(f"[Y2obi] could not write the session file: {e}")

    # Wait until port accepts connections
    import time as _time
    deadline = _time.time() + 10
    while _time.time() < deadline:
        try:
            import socket as _s
            with _s.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            _time.sleep(0.05)

    return port, _session_token
