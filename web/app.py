import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify, send_file, abort
from app.downloader import Downloader, DownloadError, PlaylistError, export_cookies_from_browser, _parse_formats
from app.binaries import ensure_ffmpeg

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", uuid.uuid4().hex)

ffmpeg_path = ensure_ffmpeg()

COOKIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies")
os.makedirs(COOKIES_DIR, exist_ok=True)
COOKIES_PATH = os.path.join(COOKIES_DIR, "cookies.txt")

# Shared downloader for metadata/cookies — browser detection is lazy (first request)
dl = Downloader(ffmpeg_path)
if os.path.exists(COOKIES_PATH):
    dl.cookies = COOKIES_PATH


# Bootstrap cookies from env var (Render: set COOKIES_B64 = base64-encoded cookies.txt)
_cookies_b64 = os.environ.get("COOKIES_B64")
if _cookies_b64 and not os.path.exists(COOKIES_PATH):
    try:
        import base64 as _b64
        with open(COOKIES_PATH, "wb") as _f:
            _f.write(_b64.b64decode(_cookies_b64))
        dl.cookies = COOKIES_PATH
    except Exception as _e:
        print(f"[Y2obi] COOKIES_B64 decode failed: {_e}")
tasks = {}
_lock = threading.Lock()
_CLEANUP_AFTER = 600


def _cleanup_loop():
    while True:
        time.sleep(300)
        now = time.time()
        dead = []
        with _lock:
            for tid, state in list(tasks.items()):
                done_at = state.get("_done_at")
                if done_at and now - done_at > _CLEANUP_AFTER:
                    dead.append(tid)
        for tid in dead:
            state = tasks.pop(tid, {})
            path = state.get("path")
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


threading.Thread(target=_cleanup_loop, daemon=True).start()


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
                s["status"] = msg
    return cb


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400
    try:
        info = dl.get_info(url)
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
    if thumb and not thumb.startswith("http"):
        thumb = ""

    # Get best HQ thumbnail from thumbnails list if available
    thumbnails = info.get("thumbnails") or []
    for t in sorted(thumbnails, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True):
        url_t = t.get("url", "")
        if url_t.startswith("http"):
            thumb = url_t
            break

    quality_labels, has_audio = _parse_formats(info)

    return jsonify({
        "title": info.get("title", "Unknown"),
        "channel": info.get("channel") or info.get("uploader", ""),
        "duration": dstr,
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "thumbnail": thumb,
        "qualities": quality_labels,   # e.g. ["2160p","1080p","720p","480p","360p"]
        "has_audio": has_audio,
    })


@app.route("/api/cookies", methods=["POST"])
def upload_cookies():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No file selected"}), 400
    f.save(COOKIES_PATH)
    dl.cookies = COOKIES_PATH
    return jsonify({"ok": True})


@app.route("/api/cookies/status", methods=["GET"])
def cookies_status():
    has_upload = os.path.exists(COOKIES_PATH)
    browser = getattr(dl, "_browser", None)
    has_browser = bool(browser)
    return jsonify({
        "loaded": has_upload or has_browser,
        "method": "uploaded" if has_upload else (browser if has_browser else None),
    })


@app.route("/api/cookies/export", methods=["POST"])
def export_cookies():
    data = request.json or {}
    browser = data.get("browser", "").strip().lower()
    allowed = {"firefox", "edge", "brave", "chrome", "chromium", "opera", "vivaldi"}
    if browser not in allowed:
        return jsonify({"ok": False, "reason": f"Unknown browser: {browser}"}), 400
    try:
        os.makedirs(COOKIES_DIR, exist_ok=True)
        export_cookies_from_browser(browser, COOKIES_PATH)
        dl.cookies = COOKIES_PATH
        return jsonify({"ok": True, "method": f"exported:{browser}"})
    except DownloadError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500


@app.route("/api/cookies", methods=["DELETE"])
def delete_cookies():
    if os.path.exists(COOKIES_PATH):
        os.remove(COOKIES_PATH)
    dl.cookies = None
    dl._browser = None
    return jsonify({"ok": True})


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp4")
    quality = data.get("quality", "Best")

    if not url:
        return jsonify({"error": "URL is required"}), 400
    if fmt not in ("mp4", "mp3", "webm"):
        return jsonify({"error": "Invalid format"}), 400

    task_id = uuid.uuid4().hex[:12]
    cookies = COOKIES_PATH if os.path.exists(COOKIES_PATH) else None
    task_dl = Downloader(ffmpeg_path, cookies=cookies)
    # Inherit browser detection result from shared dl
    task_dl._browser = getattr(dl, "_browser", None)

    task = {
        "percent": 0, "speed": 0, "eta": 0,
        "status": "Starting...", "path": None,
        "error": None, "done": False, "cancelled": False,
        "_done_at": None, "_dl": task_dl,
    }
    with _lock:
        tasks[task_id] = task

    output_dir = os.environ.get("DOWNLOAD_DIR", "/tmp/y2obi-web")
    os.makedirs(output_dir, exist_ok=True)

    task_dl.set_callbacks(progress=_progress_cb(task_id), status=_status_cb(task_id))

    def _run():
        try:
            if fmt == "mp4":
                path = task_dl.download_mp4(url, output_dir, quality)
            elif fmt == "webm":
                path = task_dl.download_webm(url, output_dir, quality)
            else:
                path = task_dl.download_mp3(url, output_dir)
            with _lock:
                t = tasks.get(task_id)
                if t:
                    t.update(path=path, percent=100, status="Complete", done=True, _done_at=time.time())
        except DownloadError as e:
            msg = str(e)
            with _lock:
                t = tasks.get(task_id)
                if t:
                    if "Cancelled" in msg:
                        t.update(cancelled=True, status="Cancelled", done=True, _done_at=time.time())
                    else:
                        t.update(error=msg, status="Error", done=True, _done_at=time.time())
        except Exception as e:
            with _lock:
                t = tasks.get(task_id)
                if t:
                    t.update(error=str(e), status="Error", done=True, _done_at=time.time())

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
    }
    if task["done"] and task["path"] and not task.get("error") and not task["cancelled"]:
        resp["file_url"] = f"/api/file/{task_id}"
        resp["filename"] = os.path.basename(task["path"])
    return jsonify(resp)


@app.route("/api/cancel/<task_id>", methods=["POST"])
def cancel(task_id):
    with _lock:
        task = tasks.get(task_id)
        if task:
            task_dl = task.get("_dl")
            if task_dl:
                task_dl.cancel()
            task["status"] = "Cancelling..."
    return jsonify({"ok": True})


@app.route("/api/file/<task_id>")
def serve_file(task_id):
    with _lock:
        task = tasks.get(task_id)
    if not task or not task.get("path"):
        abort(404)
    path = task["path"]
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
