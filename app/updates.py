"""Notice when a newer Y2obi has been released. Nothing is downloaded.

yt-dlp ages inside the exe. YouTube changes something every few weeks, yt-dlp
fixes it within days, and the copy frozen into a shipped binary stays broken
until a new build goes out -- so a user whose app stopped working has no way to
learn that the fix already exists. This closes that gap with the smallest thing
that could: it asks GitHub what the latest release is and, if it is newer, the
footer says so and links to it.

Deliberately *not* an auto-updater. Downloading and running code at startup is
the pattern this project has been trimming out of its own binary, not one to
add.

Three rules, because a version check is the classic place to get this wrong:

* **It never blocks anything.** It runs on a daemon thread and the UI asks for
  a cached answer; the app behaves identically when GitHub is unreachable.
* **It is quiet.** One request per day at most, remembered across launches.
* **It can be turned off**, and says so in Settings. This app otherwise talks to
  nobody but YouTube, and that is a promise worth keeping explicit.
"""

import json
import threading
import time
import urllib.error
import urllib.request

from app.version import VERSION, is_newer

RELEASES_API = "https://api.github.com/repos/DesvoSoft/Y2obi/releases/latest"
RELEASES_PAGE = "https://github.com/DesvoSoft/Y2obi/releases/latest"

# Once a day. The thing being watched moves every few weeks at best, so anything
# more often is noise on someone else's server.
CHECK_INTERVAL = 24 * 60 * 60
TIMEOUT = 8

_lock = threading.Lock()
_result = {"checked": False, "available": False, "latest": None, "url": RELEASES_PAGE}


def cached():
    """What the last check found. Never blocks, never raises."""
    with _lock:
        return dict(_result)


def _fetch():
    req = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        # GitHub rejects requests with no User-Agent outright.
        "User-Agent": f"Y2obi/{VERSION}",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def check(current=None, force=False, save_cb=None, last_checked=0):
    """Ask GitHub once. Returns the same shape as cached().

    `last_checked` is a unix timestamp the caller persists, so closing and
    reopening the app ten times in an afternoon still makes one request.
    """
    if not force and last_checked and time.time() - last_checked < CHECK_INTERVAL:
        return cached()
    try:
        data = _fetch()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        # Offline, rate-limited, or GitHub having a bad day. None of that is the
        # user's problem and none of it should surface anywhere but the log.
        print(f"[Y2obi] update check skipped: {e}")
        return cached()

    tag = (data.get("tag_name") or "").strip()
    # A draft or prerelease is not something to point a user at.
    if data.get("draft") or data.get("prerelease"):
        tag = ""
    result = {
        "checked": True,
        "available": bool(tag) and is_newer(tag, current),
        "latest": tag.lstrip("vV") or None,
        "url": data.get("html_url") or RELEASES_PAGE,
    }
    with _lock:
        _result.update(result)
    if save_cb:
        try:
            save_cb(time.time())
        except Exception:
            pass
    if result["available"]:
        print(f"[Y2obi] version {result['latest']} is available (running {current or VERSION})")
    return cached()


def check_in_background(current=None, save_cb=None, last_checked=0):
    """Fire the check off and return immediately."""
    t = threading.Thread(
        target=check, kwargs=dict(current=current, save_cb=save_cb,
                                  last_checked=last_checked),
        daemon=True, name="update-check")
    t.start()
    return t
