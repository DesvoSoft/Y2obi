import hmac
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid

from flask import Flask, request, jsonify, send_file, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.downloader import Downloader, DownloadError, PlaylistError, export_cookies_from_browser, _parse_formats
from app import cleanup
from app import converter
from app import transcriber
from app.binaries import get_whisper_cli

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


def _make_dl():
    cookies = COOKIES_PATH if os.path.exists(COOKIES_PATH) else None
    return Downloader(_ffmpeg_path, cookies=cookies)


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


@app.route("/api/analyze", methods=["POST"])
def analyze():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    try:
        info = _make_dl().get_info(url)
    except PlaylistError as e:
        return jsonify({"error": str(e), "playlist": True}), 400
    except DownloadError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    dur = info.get("duration", 0)
    dstr = ""
    if dur:
        h, r = divmod(int(dur), 3600)
        m, s = divmod(r, 60)
        dstr = (f"{h}h " if h else "") + f"{m}m {s:02d}s"

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
    })


@app.route("/api/cookies/status", methods=["GET"])
def cookies_status():
    has_upload = os.path.exists(COOKIES_PATH)
    return jsonify({
        "loaded": has_upload,
        "method": "uploaded" if has_upload else None,
    })


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


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = _config()
    return jsonify({
        "model": cfg.get("model") or transcriber.DEFAULT_MODEL,
        "lang": cfg.get("lang") or "auto",
        "device": _device(),
        "gpu_index": _gpu_index(),
        "onboarded": bool(cfg.get("onboarded")),
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


def _run_transcribe(task_id, src, model, lang, is_file=False):
    """Run whisper over `src` and write .txt + .srt to DOWNLOAD_DIR.

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

        if is_file:
            # ffmpeg reads the user's file directly; Transcriber.to_wav does the
            # decode, so there is nothing to fetch and nothing to clean up.
            audio_path = src
        else:
            _set(task_id, status="Downloading audio...")
            dl = _make_dl()
            _set(task_id, _dl=dl)
            dl.set_callbacks(
                progress=lambda pct, speed, eta: (
                    report("audio", pct, eta), _set(task_id, speed=speed)
                ),
                status=lambda msg: _set(task_id, status="Downloading audio..."),
            )
            audio_path = dl.download_audio_raw(src, tmp_dir)
            _set(task_id, _dl=None, speed=0)
        if cancel.is_set():
            raise transcriber.Cancelled()

        stem = os.path.splitext(os.path.basename(audio_path))[0]
        out_prefix = os.path.join(DOWNLOAD_DIR, stem)

        started = time.time()

        def on_text_pct(p):
            elapsed = time.time() - started
            eta = int(elapsed * (100.0 - p) / p) if p > 1 else 0
            report("text", p, eta)

        _set(task_id, status="Transcribing...")
        want_gpu = _device() == "gpu"
        kw = dict(lang=lang or "auto", progress_cb=on_text_pct,
                  status_cb=lambda m: _set(task_id, status=m))
        try:
            files = tr.transcribe(audio_path, model_path, out_prefix,
                                  use_gpu=want_gpu, gpu_index=_gpu_index(), **kw)
        except Exception as e:
            # A GPU that initialises but then fails mid-run (old driver, VRAM
            # pressure) must not cost the user the whole job.
            if not want_gpu or "Cancelled" in str(e) or cancel.is_set():
                raise
            _set(task_id, status="GPU failed — retrying on CPU...")
            started = time.time()
            files = tr.transcribe(audio_path, model_path, out_prefix,
                                  use_gpu=False, **kw)
        _set(task_id, path=files[0], extra_files=files[1:], done=True, percent=100,
             eta=0, status="Complete", _done_at=time.time())
    except Exception as e:
        msg = str(e)
        if "Cancelled" in msg:
            _set(task_id, cancelled=True, status="Cancelled", done=True,
                 _done_at=time.time())
        else:
            _set(task_id, error=msg, status="Error", done=True, _done_at=time.time())
    finally:
        _set(task_id, _tr=None, _dl=None)
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
                  data.get("lang") or "auto", is_file),
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
        with _lock:
            t = tasks.get(task_id)
            if t:
                t["_dl"] = dl
        dl.set_callbacks(progress=_progress_cb(task_id), status=_status_cb(task_id))
        try:
            if fmt == "mp4":
                path = dl.download_mp4(url, DOWNLOAD_DIR, quality)
            elif fmt == "webm":
                path = dl.download_webm(url, DOWNLOAD_DIR, quality)
            else:
                path = dl.download_mp3(url, DOWNLOAD_DIR)
            with _lock:
                t = tasks.get(task_id)
                if t:
                    t.update(path=path, done=True, percent=100, status="Complete", _done_at=time.time())
        except Exception as e:
            msg = str(e)
            with _lock:
                t = tasks.get(task_id)
                if t:
                    if "Cancelled" in msg:
                        t.update(cancelled=True, status="Cancelled", done=True, _done_at=time.time())
                    else:
                        t.update(error=msg, status="Error", done=True, _done_at=time.time())

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


@app.route("/api/open_folder", methods=["POST"])
def open_folder():
    """Open the output folder in Explorer — desktop only."""
    import subprocess
    try:
        subprocess.Popen(["explorer", DOWNLOAD_DIR])
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
            # /select, needs the comma glued to the path, hence one argument.
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
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
