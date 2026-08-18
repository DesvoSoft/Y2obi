import os
import sys
import time
import zipfile
import urllib.error
import urllib.request
import shutil
import tempfile

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

def _get_bundled_ffmpeg():
    """ffmpeg.exe shipped inside the PyInstaller onefile payload (extracted to _MEIPASS)."""
    meipass = getattr(sys, '_MEIPASS', None)
    if not meipass:
        return None
    path = os.path.join(meipass, "core", "ffmpeg.exe")
    return path if os.path.exists(path) else None

def _get_core_dir():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "core")

def _fetch(url, dest, progress_cb=None, retries=3):
    """Download `url` to `dest` with a socket timeout and retries.

    urlretrieve has no timeout, so a stalled connection used to hang the splash
    screen forever with no way out but killing the app.
    """
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    buf = r.read(1 << 20)
                    if not buf:
                        break
                    f.write(buf)
                    got += len(buf)
                    if progress_cb and total:
                        progress_cb(f"Downloading FFmpeg... {min(got / total * 100, 100):.0f}%")
            return
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
            if progress_cb and attempt < retries - 1:
                progress_cb(f"Download interrupted, retrying ({attempt + 1}/{retries - 1})...")
            time.sleep(2 * (attempt + 1))
    raise OSError(f"Download failed after {retries} attempts: {last_err}")


def _download_ffmpeg(dest, progress_cb=None):
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name

        if progress_cb:
            progress_cb("Downloading FFmpeg (first run only)...")

        _fetch(FFMPEG_URL, tmp_path, progress_cb)

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

def get_whisper_cli():
    """whisper-cli.exe for transcription, or None if this build has no whisper.

    Same resolution order as ffmpeg: onefile payload first, then core/ next to
    the exe. Never downloaded — the ggml DLLs must sit beside the exe, so a
    partial fetch would be worse than no feature at all.
    """
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"

    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        path = os.path.join(meipass, "core", "whisper", name)
        if os.path.exists(path):
            return path

    path = os.path.join(_get_core_dir(), "whisper", name)
    if os.path.exists(path):
        return path

    return shutil.which("whisper-cli")


def ensure_ffmpeg(progress_cb=None):
    bundled = _get_bundled_ffmpeg()
    if bundled:
        return bundled

    path = shutil.which("ffmpeg")
    if path:
        return path

    # On Linux, ffmpeg should be in PATH; don't attempt download
    if os.name != "nt":
        return "ffmpeg"

    core_dir = _get_core_dir()
    os.makedirs(core_dir, exist_ok=True)
    exe_path = os.path.join(core_dir, "ffmpeg.exe")

    if os.path.exists(exe_path):
        return exe_path

    _download_ffmpeg(exe_path, progress_cb)
    return exe_path
