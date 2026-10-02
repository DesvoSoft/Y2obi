"""The log the app always writes, and the facts worth having in it.

Y2obi ships windowed (`console=False`), so a released exe prints nowhere. Until
now a log existed only when someone thought to pass `--debug`, which is never the
run that went wrong: by the time a user reports a problem, the evidence is gone
and all anyone can do is ask them to reproduce it. So the log is on by default,
capped, and kept in a folder the Settings panel can open.

Three rules it follows:

* **The session token never lands in it.** Werkzeug logs the request line, and
  the page is opened at ``/?t=<token>`` -- so the token that gates every /api/
  route was being written in plaintext to a file in %TEMP%. `_scrub` removes it
  on the way out, by pattern rather than by value, so it also covers a token
  minted by code that never told us about it.
* **It cannot grow without bound.** One rotation at `MAX_BYTES`, two files kept.
  A log that fills a disk is worse than no log.
* **It never breaks the app.** Every write is wrapped; a full disk or a locked
  file costs the log, not the run.
"""

import datetime
import os
import re
import sys
import tempfile
import threading

# One rotation, two files. Enough to cover "it broke, I restarted, then it broke
# again" without turning into something a user has to clean up.
MAX_BYTES = 2 * 1024 * 1024
LOG_NAME = "y2obi.log"

# The token is 43 URL-safe characters (secrets.token_urlsafe(32)), but matching
# on length alone would also eat ordinary query values, so it is anchored to the
# parameter name the app actually uses.
_TOKEN_RE = re.compile(r"([?&]t=)[A-Za-z0-9_\-]{16,}")
_HEADER_RE = re.compile(r"(X-Y2obi-Token:\s*)\S+", re.IGNORECASE)

_handle = None
_lock = threading.Lock()


def log_dir():
    """Where the log lives.

    %LOCALAPPDATA%, not %APPDATA%: a log is a machine-local artefact and has no
    business roaming to a user's other PCs. Y2OBI_LOG_DIR overrides it, which is
    what keeps a test run out of the real profile.
    """
    override = os.environ.get("Y2OBI_LOG_DIR")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "Y2obi", "logs")


def log_path():
    return os.path.join(log_dir(), LOG_NAME)


def scrub(text):
    """Remove anything that would turn the log itself into a credential."""
    text = _TOKEN_RE.sub(r"\1<redacted>", text)
    return _HEADER_RE.sub(r"\1<redacted>", text)


class _Tee:
    """Write to the log and to the original stream, if there is one.

    A windowed build has `sys.stdout is None`, which is why this wraps rather
    than replaces: with a console attached the output still shows up there.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        text = scrub(text)
        with _lock:
            if _handle:
                try:
                    _handle.write(text)
                    _handle.flush()
                except (OSError, ValueError):
                    pass
        if self._stream:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass
        return len(text)

    def flush(self):
        with _lock:
            for target in (_handle, self._stream):
                try:
                    if target:
                        target.flush()
                except (OSError, ValueError):
                    pass

    # Werkzeug and a few stdlib paths ask streams about themselves before using
    # them. Answering honestly is cheaper than discovering which ones do.
    def isatty(self):
        return bool(self._stream) and getattr(self._stream, "isatty", lambda: False)()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")


def _rotate(path):
    """Keep the previous run's log as .1, so a crash-and-restart keeps both."""
    try:
        if os.path.exists(path) and os.path.getsize(path) >= MAX_BYTES:
            backup = path + ".1"
            if os.path.exists(backup):
                os.unlink(backup)
            os.replace(path, backup)
    except OSError:
        pass


def start(path=None):
    """Begin logging. Returns the path, or None if the file could not be opened.

    Safe to call twice; the second call is a no-op, so `--log FILE` and the
    default cannot end up fighting over sys.stdout.
    """
    global _handle
    if _handle:
        return log_path()
    path = path or log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _rotate(path)
        _handle = open(path, "a", encoding="utf-8", errors="replace")
    except OSError:
        return None
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    _install_excepthooks()
    return path


def banner(version):
    """The environment facts that are always wanted and never to hand.

    Written once per run, before anything can fail. Every line here has been the
    answer to a real question: which build is this, is it the frozen one, did it
    find the bundled binaries or something else on PATH, does this machine have a
    GPU backend at all.
    """
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = ["", "=" * 62,
           f"Y2obi {version} started {stamp}",
           f"python   {sys.version.split()[0]}  frozen={bool(getattr(sys, 'frozen', False))}",
           f"exe      {sys.executable}"]
    try:
        import platform
        out.append(f"windows  {platform.platform()}")
    except Exception:
        pass
    try:
        from app import binaries
        # Resolution only -- no subprocess. probe_backends spawns whisper-cli,
        # and doing that on the startup thread of a windowed frozen exe is the
        # class of thing that wedged this app before; log_backends() reports it
        # later, from the worker that warms the cache anyway.
        out.append(f"ffmpeg   {binaries._get_bundled_ffmpeg() or '(none found yet)'}")
        out.append(f"whisper  {binaries.get_whisper_cli() or '(not in this build)'}")
        out.append(f"deno     {binaries.get_deno() or '(not in this build)'}")
        # Without the solver scripts deno has nothing to run, and a signed-in
        # session degrades to thumbnails only with no error of its own.
        try:
            import yt_dlp_ejs  # noqa: F401
            out.append("ejs      yt-dlp-ejs present")
        except ImportError:
            out.append("ejs      MISSING -- signed-in downloads will fail; pip install -r requirements.txt")
    except Exception as e:
        out.append(f"binaries could not be resolved for the banner: {e}")
    out.append("=" * 62)
    print(chr(10).join(out))


def log_backends():
    """Report the ggml backends, from a thread that can afford the subprocess."""
    try:
        from app import binaries, transcriber
        cli = binaries.get_whisper_cli()
        if not cli:
            return
        names = [b["name"] for b in transcriber.probe_backends(cli)]
        print(f"[Y2obi] whisper backends: {', '.join(names) or '(none reported)'}")
    except Exception as e:
        print(f"[Y2obi] backend probe failed: {e}")


def _install_excepthooks():
    """Make a crash in any thread reach the log instead of vanishing.

    yt-dlp, ffmpeg and whisper all run behind worker threads. An exception one of
    them fails to catch is printed by the default hook to a stderr that, in a
    windowed build, went nowhere at all.
    """
    def _hook(exc_type, exc, tb, thread=None):
        import traceback
        where = f" in thread {thread.name}" if thread else ""
        print(f"[Y2obi] unhandled {exc_type.__name__}{where}: {exc}")
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = lambda t, e, tb: _hook(t, e, tb)

    def _thread_hook(args):
        _hook(args.exc_type, args.exc_value, args.exc_traceback, args.thread)

    threading.excepthook = _thread_hook
