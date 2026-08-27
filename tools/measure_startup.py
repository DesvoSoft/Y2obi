"""Time an exe from launch to server, to window, and to a responding window.

Version-agnostic on purpose: it watches the process and its listening socket
from outside, so the same script measures a build that predates any of this
session's changes.

    python measure_startup.py <path-to-exe> [runs]

Three moments are worth separating:

  server   the loopback port starts accepting -- Flask is up
  window   the process owns a top-level window -- something is on screen
  usable   that window answers Windows' "are you alive" ping, i.e. it is
           pumping messages. This is the one users describe as the app being
           frozen, and it is the one the pywebview introspection walk delayed.
"""

import subprocess
import sys
import time

PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]


def ps(script):
    r = subprocess.run(PS + [script], capture_output=True, text=True)
    return r.stdout.strip()


def kill_all():
    subprocess.run(["taskkill", "/IM", "Y2obi.exe", "/T", "/F"], capture_output=True)
    time.sleep(1.5)


def measure(exe, timeout=30):
    """Launch and watch entirely inside PowerShell.

    Python's time.time() is a UTC epoch and PowerShell 5.1's `Get-Date -UFormat %s`
    is a *local* one, so mixing them offsets every reading by the timezone -- six
    hours here, which showed up as negative durations. One clock, one process:
    PowerShell starts the exe and uses .NET's Stopwatch, which is monotonic and
    has nothing to do with either epoch.
    """
    kill_all()
    # Sampled continuously rather than waiting for milestones. The question is
    # not only "how long until a window" but "how much of that window's early
    # life is spent not answering Windows", which is what a user calls a freeze.
    script = f"""
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath '{exe}' -PassThru
$server = $null; $window = $null
$samples = @()
while ($sw.Elapsed.TotalSeconds -lt {timeout}) {{
  $t = $sw.Elapsed.TotalSeconds
  $procs = Get-Process Y2obi -ErrorAction SilentlyContinue
  if ($procs) {{
    if (-not $server) {{
      $ids = @($procs.Id)
      $conn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
              Where-Object {{ $ids -contains $_.OwningProcess -and $_.LocalAddress -eq '127.0.0.1' }}
      if ($conn) {{ $server = $t }}
    }}
    $main = $procs | Where-Object {{ $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
    if ($main) {{
      if (-not $window) {{ $window = $t }}
      $samples += ("{{0:N2}}:{{1}}" -f $t, [int]$main.Responding)
    }}
  }}
  Start-Sleep -Milliseconds 100
}}
"server=$server"; "window=$window"; "samples=" + ($samples -join ",")
"""
    out = ps(script)
    marks = {"server": None, "window": None, "stalled": 0.0, "longest": 0.0}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        v = v.strip()
        if k in ("server", "window") and v:
            try:
                marks[k] = float(v)
            except ValueError:
                pass
        elif k == "samples" and v:
            run = 0.0
            for item in v.split(","):
                if ":" not in item:
                    continue
                _t, _, ok = item.partition(":")
                if ok.strip() == "0":
                    # 100 ms per sample; a sample that says "not responding" is
                    # 100 ms the user could not have clicked anything.
                    marks["stalled"] += 0.1
                    run += 0.1
                    marks["longest"] = max(marks["longest"], run)
                else:
                    run = 0.0
    kill_all()
    return marks


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    exe = argv[1]
    runs = int(argv[2]) if len(argv) > 2 else 3
    rows = []
    for i in range(runs):
        m = measure(exe)
        rows.append(m)
        print(f"  run {i + 1}: " + "  ".join(
            f"{k}={v:.2f}s" if v is not None else f"{k}=--" for k, v in m.items()))
    print()
    for key in ("server", "window", "stalled", "longest"):
        vals = sorted(v for v in (r[key] for r in rows) if v is not None)
        if vals:
            print(f"  {key:7} median {vals[len(vals) // 2]:.2f}s"
                  f"   (min {vals[0]:.2f}  max {vals[-1]:.2f})")
        else:
            print(f"  {key:7} never reached")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
