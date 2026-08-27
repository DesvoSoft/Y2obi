"""Drive the built exe and check it actually works. The gate before a release.

    pyinstaller build.spec
    python tools/qa_exe.py

Running the test suite proves the pure functions are fine. It says nothing about
the thing users download: several of this project's worst bugs existed **only**
in the frozen build -- the whisper probe that wedged the server, the Local file
tab that never appeared, binaries resolving to something other than the bundled
copy. Those need the real exe, launched the way a user launches it.

The exe mints a random port and a token it deliberately never prints, so this
sets Y2OBI_SESSION_FILE and reads the pair back from there (see start_server).
Nothing writes that file unless the variable is set, so a released run is
unaffected.

Everything happens in a throwaway profile: Y2OBI_HOME, Y2OBI_OUTPUT and
Y2OBI_LOG_DIR are pointed at a temp directory, so a QA run cannot touch the
config, models or Downloads folder of the app the user is actually using.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "Y2obi.exe")

_failures = []
_checks = 0


def check(name, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        _failures.append(name)
    return ok


def _y2obi_already_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Y2obi.exe"],
                         capture_output=True, text=True).stdout
    return "Y2obi.exe" in out


class App:
    """The running exe, plus the two facts needed to talk to it."""

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.session = os.path.join(sandbox, "session.json")
        self.log_dir = os.path.join(sandbox, "logs")
        self.proc = None
        self.port = None
        self.token = None

    def start(self, timeout=90):
        env = dict(os.environ)
        env["Y2OBI_HOME"] = os.path.join(self.sandbox, "home")
        env["Y2OBI_OUTPUT"] = os.path.join(self.sandbox, "downloads")
        env["Y2OBI_LOG_DIR"] = self.log_dir
        env["Y2OBI_SESSION_FILE"] = self.session
        print(f"launching {EXE}")
        started = time.time()
        self.proc = subprocess.Popen([EXE], env=env)
        # A onefile exe unpacks ~150 MB to %TEMP% before a single line of our
        # code runs, so the first wait here is genuinely long on a cold cache.
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                # Exit 0 without ever publishing a session is the single-instance
                # lock, not a crash: say so, because the two look identical here.
                if self.proc.returncode == 0 and _y2obi_already_running():
                    raise SystemExit(
                        "another Y2obi is already running, so this one bowed out. "
                        "Close it (or: taskkill /IM Y2obi.exe /F) and run again.")
                raise SystemExit(f"the exe exited during startup, code {self.proc.returncode}")
            if os.path.exists(self.session):
                try:
                    with open(self.session, encoding="utf-8") as f:
                        data = json.load(f)
                    self.port, self.token = data["port"], data["token"]
                    print(f"up in {time.time() - started:.1f}s on port {self.port}")
                    return
                except (OSError, ValueError, KeyError):
                    pass  # still being written
            time.sleep(0.25)
        raise SystemExit("the exe never published a session file")

    def api(self, path, method="GET", body=None, token=True, timeout=120):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Y2obi-Token"] = self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                try:
                    return r.status, json.loads(raw)
                except ValueError:
                    return r.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw

    def wait_task(self, task_id, timeout=180):
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            _, last = self.api(f"/api/progress/{task_id}")
            if not isinstance(last, dict):
                return {}
            if last.get("done"):
                return last
            time.sleep(0.4)
        return last

    def stop(self):
        """Kill the tree, not the process we happen to hold a handle to.

        A onefile exe is two processes: the bootloader unpacks the payload and
        launches the real app as a child. terminate() on the handle here reaps
        only the parent, and the child goes on holding the single-instance mutex
        -- so the *next* run exits 0 with "another instance is already running"
        and looks like a startup crash. That cost a confusing ten minutes once.
        """
        if not self.proc or self.proc.poll() is not None:
            return
        subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                       capture_output=True)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def make_sample(sandbox):
    """A real media file, produced by the same ffmpeg the exe will use.

    Generated rather than committed: a binary fixture in the repo would be one
    more thing to keep, and this proves the bundled ffmpeg runs at the same time.
    """
    ffmpeg = os.path.join(ROOT, "core", "ffmpeg.exe") or "ffmpeg"
    out = os.path.join(sandbox, "sample.mp4")
    cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=5",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", out]
    subprocess.run(cmd, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out if os.path.isfile(out) else None


def main():
    if not os.path.isfile(EXE):
        raise SystemExit(f"no exe at {EXE} — run: pyinstaller build.spec")
    print(f"exe {os.path.getsize(EXE) / 1e6:.1f} MB")

    sandbox = tempfile.mkdtemp(prefix="y2obi_qa_")
    app = App(sandbox)
    try:
        app.start()

        print("\n-- the token gate --")
        status, _ = app.api("/api/config", token=False)
        check("an API call without the token is refused", status == 403, f"got {status}")
        status, cfg = app.api("/api/config")
        check("an API call with the token is served", status == 200, f"got {status}")

        print("\n-- config --")
        check("config carries the timestamp interval", isinstance(cfg, dict)
              and "ts_interval" in cfg)
        check("config carries the log directory", isinstance(cfg, dict)
              and bool(cfg.get("log_dir")))
        status, _ = app.api("/api/config", "POST", {"ts_interval": 120})
        _, cfg2 = app.api("/api/config")
        check("a timestamp interval round-trips", cfg2.get("ts_interval") == 120)
        status, _ = app.api("/api/config", "POST", {"ts_interval": 7})
        check("an interval nobody offered is refused", status == 400, f"got {status}")

        print("\n-- bundled binaries --")
        status, models = app.api("/api/transcribe/models")
        check("the speech engine is bundled and answers",
              status == 200 and models.get("available") is True)
        check("the model catalogue is complete", len(models.get("models", [])) == 6,
              f"{len(models.get('models', []))} models")
        backends = [b.get("name") for b in models.get("backends", [])]
        check("whisper reports its backends", bool(backends), ", ".join(backends))

        sample = make_sample(sandbox)
        if not check("ffmpeg produced a sample file", bool(sample)):
            return
        status, probe = app.api("/api/analyze_file", "POST", {"path": sample})
        check("the bundled ffmpeg probes a local file",
              status == 200 and bool(probe.get("duration")), str(probe)[:90])

        print("\n-- a real job, end to end --")
        status, started = app.api("/api/download", "POST",
                                  {"source": "file", "path": sample, "format": "mp3"})
        task = started.get("task_id")
        if check("a conversion starts", status == 200 and bool(task)):
            status2, second = app.api("/api/download", "POST",
                                      {"source": "file", "path": sample, "format": "mp3"})
            check("a second job is refused while one runs", status2 == 409,
                  f"got {status2}")
            done = app.wait_task(task)
            check("the conversion finishes", done.get("done") and not done.get("error"),
                  done.get("error") or done.get("status", ""))
            check("it reports 100%", done.get("percent") == 100, str(done.get("percent")))
            out = os.path.join(sandbox, "downloads")
            produced = os.listdir(out) if os.path.isdir(out) else []
            check("the output file exists", any(f.endswith(".mp3") for f in produced),
                  ", ".join(produced) or "nothing written")

        print("\n-- the log --")
        log = os.path.join(app.log_dir, "y2obi.log")
        if check("a log was written without being asked for", os.path.isfile(log)):
            text = open(log, encoding="utf-8", errors="replace").read()
            check("it records which build this is", "Y2obi " in text and "frozen=True" in text)
            check("it names the bundled binaries", "ffmpeg" in text and "whisper" in text)
            # The whole point of scrubbing. A failure here is a leaked credential,
            # not a cosmetic problem.
            check("the session token is NOT in it", app.token not in text,
                  "TOKEN LEAKED" if app.token in text else "")
            check("redaction actually fired", "t=<redacted>" in text)

        print("\n-- shutdown --")
        app.stop()
        check("the exe exits when asked", app.proc.poll() is not None)

    finally:
        app.stop()
        shutil.rmtree(sandbox, ignore_errors=True)

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        print("failed: " + "; ".join(_failures))
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
