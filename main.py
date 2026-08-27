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


# One definition, in app/version.py: the server needs it for the update check and
# cannot import main without a cycle.
from app.version import VERSION

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
                    help="enable right-click Inspect in the window (the log is "
                         "always written, with or without this)")
    ap.add_argument("--log", metavar="FILE",
                    help="write the log here instead of the default location")
    ap.add_argument("--reset", action="store_true",
                    help="delete settings before starting, so the first-run screen shows again")
    ap.add_argument("--cpu", action="store_true",
                    help="force CPU transcription for this run, ignoring the saved setting")
    ap.add_argument("--signin", action="store_true",
                    help="open a YouTube sign-in window (used internally by the app)")
    ap.add_argument("--version", action="version", version=f"Y2obi {VERSION}")
    return ap.parse_args(argv)


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
        # Underscored on purpose, and this is not style. pywebview builds the JS
        # bridge by walking dir(js_api) and recursing into every public
        # non-callable attribute -- see get_functions in webview/util.py, which
        # skips names starting with "_". A public `window` here handed it the
        # pywebview Window, so it walked on into window.native and the whole
        # WinForms/.NET object graph: thousands of COM property reads off the UI
        # thread, each one raising and being logged, until it hit the recursion
        # limit. That is the wall of "Error while processing
        # window.native.AccessibilityObject.Bounds.Empty.Empty..." at startup,
        # and it is not cosmetic: the walk holds the GIL long enough that the
        # stall watchdog fires at 20 s, which is the app "freezing in its first
        # moments". One underscore ends the whole recursion.
        self._window = None

    def pick_file(self):
        # Imported here, not at module scope: webview pulls in pythonnet/CLR and
        # the splash screen has to be up before that cost is paid.
        import webview
        from app.converter import AUDIO_EXTS, VIDEO_EXTS
        if not self._window:
            return None
        patterns = ";".join("*" + e for e in VIDEO_EXTS + AUDIO_EXTS)
        result = self._window.create_file_dialog(
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


def _boot_server(splash, ffmpeg_path):
    """Start Flask without letting the splash stop answering Windows.

    start_server binds a port, boots Flask on a thread and then waits for that
    port to accept a connection. Called straight from this thread it would stop
    the splash pumping messages for as long as that takes, and a window that
    stops pumping is a window Windows greys out and labels "Not responding" --
    which is exactly what "it freezes in the first moments" describes.

    So it runs on its own thread and we pump Tk until it is done. update() is
    deliberate: it processes pending events and returns, unlike mainloop().
    """
    from app.server import start_server
    out = {}

    def _run():
        try:
            out["value"] = start_server(ffmpeg_path, DESKTOP_DIR)
        except Exception as e:  # reported below, on the thread that can show UI
            out["error"] = e

    t = threading.Thread(target=_run, daemon=True, name="server-boot")
    t.start()
    while t.is_alive():
        try:
            splash.root.update()
        except tk.TclError:
            # The user closed the splash. Nothing left to pump; the server
            # thread is a daemon and dies with the process.
            break
        time.sleep(0.03)
    if "error" in out:
        raise out["error"]
    return out["value"]


def main(argv=None):
    args = _parse_args(argv)
    _arm_stall_watchdog()
    if args.signin:
        # No splash, no server, no single-instance lock: this is a short-lived
        # child of the running app.
        _run_signin_window()
        return
    # Logging is unconditional. It used to be behind --debug, which is never the
    # run that went wrong: by the time a user reports something the evidence is
    # gone and the only remedy is asking them to reproduce it. app/diagnostics.py
    # caps and rotates the file, and keeps the session token out of it.
    from app import diagnostics
    written = diagnostics.start(args.log)
    diagnostics.banner(VERSION)
    if not written:
        print("[Y2obi] could not open a log file; continuing without one")
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
            # Warm the whisper backend probe here, on this thread. It spawns a
            # subprocess and start_server calls it too, but it caches for the
            # life of the process, so paying for it on the worker leaves almost
            # nothing for the startup path to pay for later.
            try:
                from app import transcriber
                from app.binaries import get_whisper_cli
                transcriber.probe_backends(get_whisper_cli())
                diagnostics.log_backends()
            except Exception:
                pass
            result["path"] = path
        except Exception as e:
            result["stage"] = stage
            result["error"] = str(e)

    threading.Thread(target=_check, daemon=True).start()

    def _poll():
        # Only ends the loop. Everything that follows runs from main()'s own
        # frame -- see the comment below the mainloop call for why that matters.
        if result["path"] or result["error"]:
            splash.root.quit()
            return
        splash.root.after(100, _poll)

    splash.root.after(100, _poll)
    splash.root.mainloop()
    # quit() returns from mainloop and leaves the root alive, so the splash can
    # still paint below while nothing runs nested inside a Tcl callback.
    #
    # This used to launch the app from inside _poll, which meant webview.start()
    # -- and the WinForms message pump it owns -- ran on top of a mainloop frame
    # that was still on the C stack. Two GUI toolkits stacked in one thread is
    # what made the app wedge in its first seconds on an unrelated system event
    # such as the clipboard panel taking focus.

    # mainloop also returns if the window itself went away -- the user closed
    # the splash while the checks were still running. Nothing to launch, and
    # touching a destroyed root below would raise instead of exiting quietly.
    if not result["path"] and not result["error"]:
        print("[Y2obi] startup cancelled")
        return

    if result["error"]:
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
            f"Could not set up {stage}:" + chr(10) + result["error"] + chr(10) * 2 + hint,
        )
        splash.close()
        sys.exit(1)

    splash.update("Starting Y2obi...")
    port, token = _boot_server(splash, result["path"])
    # The token is handed to the page through the URL; the page sends it back
    # as a header on every API call. See _require_token in app/server.py.
    url = f"http://127.0.0.1:{port}/?t={token}"
    splash.close()

    import webview
    # Sweep what a killed or crashed earlier run left in %TEMP%. Each abandoned
    # onefile payload is ~150 MB. On its own thread: it walks %TEMP% and renames
    # directories to test whether they are in use, and doing that before the
    # window exists is several seconds of a frozen-looking app for a chore
    # nothing is waiting on.
    def _sweep():
        try:
            from app.cleanup import sweep_temp
            n, freed = sweep_temp()
            if n:
                print(f"[Y2obi] cleaned {n} leftover temp dirs ({freed / 1e6:.0f} MB)")
        except Exception:
            pass

    threading.Thread(target=_sweep, daemon=True, name="temp-sweep").start()

    # Sized so the full stack (info card + every option row + progress) fits
    # without scrolling; the page scrolls if the user shrinks it below this.
    api = Api()
    api._window = webview.create_window(
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


if __name__ == "__main__":
    main()
