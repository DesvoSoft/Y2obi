import argparse
import sys
import os
import datetime
import faulthandler
import tkinter as tk
from tkinter import messagebox
import threading
import shutil
import urllib.request
import subprocess
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DESKTOP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop")
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def _webview2_installed():
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for path in (
                r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            ):
                try:
                    with winreg.OpenKey(hive, path):
                        return True
                except OSError:
                    pass
    except Exception:
        pass
    return False


def _install_webview2(progress_cb):
    progress_cb("Downloading WebView2 runtime...")
    # mkstemp, not mktemp: the installer is executed, so the file must be ours
    # from the moment it exists.
    fd, tmp = tempfile.mkstemp(suffix=".exe")
    os.close(fd)
    try:
        with urllib.request.urlopen(WEBVIEW2_URL, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        progress_cb("Installing WebView2 runtime...")
        subprocess.run([tmp, "/silent", "/install"], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


VERSION = "1.4.0"

# How long Python may stop making progress before we consider the app wedged.
# Nothing legitimate blocks this long: the slow work (yt-dlp, ffmpeg, whisper)
# runs in subprocesses, so Python threads keep ticking throughout.
STALL_SECONDS = 20
STALL_LOG = "y2obi-stall.log"


def _arm_stall_watchdog():
    """Record every thread's stack if the process stops responding.

    A watchdog written in Python cannot report a freeze that holds the GIL,
    because it would be frozen too. faulthandler's timer lives in C and fires
    regardless, which is the only way to see that kind of hang from the inside.
    The timer is re-armed by a healthy Python thread, so it only fires when that
    thread stops getting scheduled.

    Armed on every run again. It was moved behind --debug while the freeze was
    only a hypothesis; it is now reproducible in ordinary use, and a fault nobody
    can capture is worth more than two idle threads.
    """
    path = os.path.join(tempfile.gettempdir(), STALL_LOG)
    try:
        handle = open(path, "a", encoding="utf-8", errors="replace")
    except OSError:
        return None
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    handle.write(chr(10) + "===== watching from " + stamp
                 + " (a dump appears below only if the app wedges) =====" + chr(10))
    handle.flush()
    faulthandler.enable(file=handle)

    def _rearm():
        while True:
            faulthandler.dump_traceback_later(STALL_SECONDS, repeat=False,
                                              file=handle, exit=False)
            time.sleep(STALL_SECONDS / 4.0)

    threading.Thread(target=_rearm, daemon=True, name="stall-watchdog").start()
    return path

# Held for the life of the process; releasing it would let a second copy start.
_instance_mutex = None


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="Y2obi",
        description="YouTube downloader and offline transcriber.")
    ap.add_argument("--debug", action="store_true",
                    help="write a log file and enable right-click Inspect in the window")
    ap.add_argument("--log", metavar="FILE",
                    help="write the log here (implies --debug logging, default "
                         "%%TEMP%%" + os.sep + "y2obi-debug.log)")
    ap.add_argument("--reset", action="store_true",
                    help="delete settings before starting, so the first-run screen shows again")
    ap.add_argument("--cpu", action="store_true",
                    help="force CPU transcription for this run, ignoring the saved setting")
    ap.add_argument("--signin", action="store_true",
                    help="open a YouTube sign-in window (used internally by the app)")
    ap.add_argument("--version", action="version", version=f"Y2obi {VERSION}")
    return ap.parse_args(argv)


class _Tee:
    """Write to the log file and to the original stream, if there is one.

    The released exe is built windowed, so sys.stdout is None and anything the
    app prints is lost. That is fine until something misbehaves on a machine
    that is not this one, which is exactly when the output matters.
    """

    def __init__(self, stream, handle):
        self._stream = stream
        self._handle = handle

    def write(self, text):
        try:
            self._handle.write(text)
            self._handle.flush()
        except (OSError, ValueError):
            pass
        if self._stream:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass

    def flush(self):
        for target in (self._handle, self._stream):
            try:
                if target:
                    target.flush()
            except (OSError, ValueError):
                pass


def _start_logging(path):
    handle = open(path, "a", encoding="utf-8", errors="replace")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    handle.write(chr(10) + "===== Y2obi " + VERSION + " started " + stamp + " =====" + chr(10))
    handle.write("frozen=" + str(getattr(sys, "frozen", False))
                 + " exe=" + sys.executable + chr(10))
    sys.stdout = _Tee(sys.stdout, handle)
    sys.stderr = _Tee(sys.stderr, handle)
    return path


def _reset_settings():
    """Remove saved preferences so the next start behaves like a fresh install."""
    from app.server import CONFIG_PATH
    try:
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
            print(f"[Y2obi] removed {CONFIG_PATH}")
    except OSError as e:
        print(f"[Y2obi] could not remove settings: {e}")


def _claim_single_instance():
    """False if another Y2obi already owns the lock, after focusing its window.

    Y2obi keeps one WebView2 profile in a fixed folder (see webview.start below)
    so profiles cannot pile up in %TEMP%. WebView2 will not share a profile
    between processes, so a second copy would hang on startup instead of failing
    cleanly. One instance is the right behaviour for this app anyway.
    """
    global _instance_mutex
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    _instance_mutex = k32.CreateMutexW(None, False, "Y2obi.SingleInstance")
    if k32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return True
    u32 = ctypes.windll.user32
    hwnd = u32.FindWindowW(None, "Y2obi")
    if hwnd:
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
    return False


class Api:
    """Exposed to the page as `window.pywebview.api`.

    Only one thing genuinely needs the native layer: a real filesystem path.
    WebView2, like any browser, refuses to give one out from `<input type=file>`,
    and pushing a 2 GB video through the HTTP layer just to learn its name would
    be absurd. So the picker lives here and hands the path back; the server then
    reads the file straight off disk.
    """

    def __init__(self):
        self.window = None

    def pick_file(self):
        # Imported here, not at module scope: webview pulls in pythonnet/CLR and
        # the splash screen has to be up before that cost is paid.
        import webview
        from app.converter import AUDIO_EXTS, VIDEO_EXTS
        if not self.window:
            return None
        patterns = ";".join("*" + e for e in VIDEO_EXTS + AUDIO_EXTS)
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(f"Audio and video ({patterns})", "All files (*.*)"),
        )
        return result[0] if result else None


class FFmpegSplash:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Y2obi")
        self.root.geometry("420x160")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")
        self._center()

        tk.Label(self.root, text="Y2obi", font=("Segoe UI", 20, "bold"),
                 bg="#1a1a2e", fg="#e0e0e0").pack(pady=(20, 4))

        self.msg = tk.Label(self.root, text="Preparing...", font=("Segoe UI", 11),
                            bg="#1a1a2e", fg="#a0a0a0")
        self.msg.pack(pady=(0, 10))

        self.progress = tk.Canvas(self.root, width=320, height=6, bg="#2a2a3e",
                                  highlightthickness=0)
        self.progress.pack(pady=(0, 4))
        self._bar = self.progress.create_rectangle(0, 0, 0, 6, fill="#4fc3f7", width=0)

        self.pct_label = tk.Label(self.root, text="", font=("Segoe UI", 10),
                                  bg="#1a1a2e", fg="#707070")
        self.pct_label.pack()

        self._error = None

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def update(self, msg, pct=None):
        self.msg.config(text=msg)
        if pct is not None:
            bw = int(320 * pct / 100)
            self.progress.coords(self._bar, 0, 0, bw, 6)
            self.pct_label.config(text=f"{pct:.0f}%")

    def close(self):
        self.root.destroy()


SIGNIN_PROFILE = "ytsession"


def signin_profile_dir():
    """Where the sign-in window keeps its browser profile.

    Deliberately separate from the app's own WebView2 profile: pywebview's
    storage_path is per process, and the running app holds its cookie database
    locked, so a profile we can actually read afterwards has to belong to a
    process that has exited.
    """
    return os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
                        "Y2obi", SIGNIN_PROFILE)


def _run_signin_window():
    """Show YouTube in a normal browser window and let the user sign in.

    Chromium browsers encrypt their cookies with App-Bound Encryption since v127,
    which no outside process can decrypt: that is the "Failed to decrypt with
    DPAPI" wall, and it is not going away. A window of our own has no such
    problem, because the profile is ours.
    """
    import webview
    profile = signin_profile_dir()
    os.makedirs(profile, exist_ok=True)
    webview.create_window(
        "Sign in to YouTube",
        "https://www.youtube.com/account",
        width=980, height=800, min_size=(520, 480), resizable=True,
    )
    webview.start(private_mode=False, storage_path=profile)


def main(argv=None):
    args = _parse_args(argv)
    _arm_stall_watchdog()
    if args.signin:
        # No splash, no server, no single-instance lock: this is a short-lived
        # child of the running app.
        _run_signin_window()
        return
    if args.debug or args.log:
        log_path = args.log or os.path.join(tempfile.gettempdir(), "y2obi-debug.log")
        print(f"[Y2obi] logging to {_start_logging(log_path)}")
    if args.cpu:
        # Read by app/server.py when it resolves the processing device.
        os.environ["Y2OBI_FORCE_CPU"] = "1"
    if args.reset:
        _reset_settings()
    if not _claim_single_instance():
        print("[Y2obi] another instance is already running")
        return
    splash = FFmpegSplash()
    result = {"path": None, "error": None, "stage": None}

    def _check():
        stage = "WebView2 runtime"
        try:
            if not _webview2_installed():
                _install_webview2(lambda m: splash.root.after(0, lambda msg=m: splash.update(msg)))
            stage = "FFmpeg"
            from app.binaries import ensure_ffmpeg
            path = ensure_ffmpeg(progress_cb=lambda m: splash.root.after(0, lambda msg=m: splash.update(msg)))
            result["path"] = path
        except Exception as e:
            result["stage"] = stage
            result["error"] = str(e)

    threading.Thread(target=_check, daemon=True).start()

    def _poll():
        if result["path"]:
            _launch(result["path"])
            return
        if result["error"]:
            # Reuse the splash root rather than destroying it and building
            # another one just to own a message box.
            splash.root.withdraw()
            stage = result.get("stage") or "FFmpeg"
            hint = (
                "Install FFmpeg manually and add to PATH, or "
                "place ffmpeg.exe in the 'core' folder."
                if stage == "FFmpeg" else
                "Install the Microsoft Edge WebView2 runtime manually, "
                "then start Y2obi again."
            )
            messagebox.showerror(
                f"{stage} Error",
                f"Could not set up {stage}:\n{result['error']}\n\n{hint}",
            )
            splash.close()
            sys.exit(1)
        splash.root.after(100, _poll)

    def _launch(ffmpeg_path):
        from app.server import start_server
        # One Tk root for the whole pre-window phase. This used to close the
        # splash, build a second root plus a Toplevel to say "Starting...", then
        # tear both down before handing over to WinForms: three roots and two
        # GUI toolkits in one process, for one line of text.
        splash.update("Starting Y2obi...")
        splash.root.update()   # paint it now; start_server blocks the loop next

        # The token is handed to the page through the URL; the page sends it back
        # as a header on every API call. See _require_token in app/server.py.
        port, token = start_server(ffmpeg_path, DESKTOP_DIR)
        url = f"http://127.0.0.1:{port}/?t={token}"

        splash.close()

        import webview
        # Sweep what a killed or crashed earlier run left in %TEMP%. Each
        # abandoned onefile payload is ~150 MB.
        try:
            from app.cleanup import sweep_temp
            n, freed = sweep_temp()
            if n:
                print(f"[Y2obi] cleaned {n} leftover temp dirs ({freed / 1e6:.0f} MB)")
        except Exception:
            pass

        # Sized so the full stack (info card + every option row + progress) fits
        # without scrolling; the page scrolls if the user shrinks it below this.
        api = Api()
        api.window = webview.create_window(
            "Y2obi",
            url,
            width=940,
            # 900, not 780: with the transcript rows and the progress card open
            # the panel measures 782 px of content, and a 780 px window only
            # leaves 688 px of viewport once Windows takes its chrome, so the
            # bottom of the app needed scrolling to reach.
            height=900,
            min_size=(700, 620),
            resizable=True,
            js_api=api,
        )
        # A fixed profile directory instead of pywebview's default private mode:
        # private mode makes a fresh temp profile per launch and only removes it
        # on a clean exit, so every kill leaves another ~12 MB EBWebView folder
        # behind. One reusable folder cannot pile up.
        storage = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
                               "Y2obi", "webview")
        os.makedirs(storage, exist_ok=True)
        # debug=True turns on right-click Inspect in the window.
        webview.start(private_mode=False, storage_path=storage,
                      debug=bool(args.debug))

    splash.root.after(100, _poll)
    splash.root.mainloop()


if __name__ == "__main__":
    main()
