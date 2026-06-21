import os
import sys
import threading
import time
import uuid

from flask import Flask, request, jsonify, send_file, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.downloader import Downloader, DownloadError, PlaylistError, export_cookies_from_browser, _parse_formats

_lock = threading.Lock()
tasks = {}

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "Y2obi")
COOKIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies", "cookies.txt")

app = Flask(__name__, static_folder=None)
app.secret_key = uuid.uuid4().hex

_ffmpeg_path = "ffmpeg"
_static_dir = None  # set by start_server()


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
                             percent=100, already_exists=True, _done_at=__import__('time').time())
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


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp4")
    quality = data.get("quality", "Best")

    if not url:
        return jsonify({"error": "URL required"}), 400
    if fmt not in ("mp4", "mp3", "webm"):
        return jsonify({"error": f"Unknown format: {fmt}"}), 400

    task_id = uuid.uuid4().hex
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    with _lock:
        tasks[task_id] = {
            "percent": 0, "speed": 0, "eta": 0,
            "status": "Starting...", "done": False,
            "cancelled": False, "path": None,
            "_dl": None,
        }

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
    return jsonify(resp)


@app.route("/api/cancel/<task_id>", methods=["POST"])
def cancel(task_id):
    with _lock:
        task = tasks.get(task_id)
        if task:
            dl = task.get("_dl")
            if dl:
                dl.cancel()
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


def start_server(ffmpeg_path, static_dir, port=0):
    """Start Flask on a random loopback port. Returns the port."""
    global _ffmpeg_path, _static_dir
    _ffmpeg_path = ffmpeg_path
    _static_dir = static_dir

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

    return port
