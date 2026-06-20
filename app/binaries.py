import os
import sys
import zipfile
import urllib.request
import shutil
import tempfile

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

def _get_core_dir():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "core")

def _download_ffmpeg(dest, progress_cb=None):
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name

        if progress_cb:
            progress_cb("Downloading FFmpeg (first run only)...")

        def report(bcount, bsize, total):
            if progress_cb and total > 0:
                pct = min(bcount * bsize / total * 100, 100)
                progress_cb(f"Downloading FFmpeg... {pct:.0f}%")

        urllib.request.urlretrieve(FFMPEG_URL, tmp_path, reporthook=report)

        if progress_cb:
            progress_cb("Extracting FFmpeg...")

        with zipfile.ZipFile(tmp_path, 'r') as zf:
            for name in zf.namelist():
                if name.endswith("ffmpeg.exe") and "/bin/" in name:
                    with zf.open(name) as src, open(dest, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    break

        if progress_cb:
            progress_cb("FFmpeg ready!")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

def ensure_ffmpeg(progress_cb=None):
    path = shutil.which("ffmpeg")
    if path:
        return path

    # On Linux (Render, PythonAnywhere) ffmpeg should be in PATH; don't attempt download
    if os.name != "nt":
        return "ffmpeg"

    core_dir = _get_core_dir()
    os.makedirs(core_dir, exist_ok=True)
    exe_path = os.path.join(core_dir, "ffmpeg.exe")

    if os.path.exists(exe_path):
        return exe_path

    _download_ffmpeg(exe_path, progress_cb)
    return exe_path
