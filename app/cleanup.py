"""Housekeeping: remove what earlier runs of Y2obi left behind.

Everything the app writes outside the user's Downloads folder is temporary, but
"temporary" only holds if the process exits normally. Kill it from Task Manager,
or crash it, and three kinds of leftovers survive:

  - `y2obi_*` working directories (audio being transcribed, chunk WAVs);
  - `_MEI*` directories, the PyInstaller onefile payload — ~150 MB each;
  - the WebView2 profile, which pywebview puts in a fresh temp directory per run
    unless it is given a fixed `storage_path` (main.py now does).

None of it is ever cleaned by Windows on its own. This module sweeps our own
leftovers at startup and is deliberately conservative: it only touches
directories it can prove are ours and that nothing still has open.
"""
import os
import shutil
import sys
import tempfile
import time

# Files that together identify a PyInstaller payload as *this* app's, so the
# sweep can never delete another frozen program's extraction directory.
_MEI_MARKERS = (
    os.path.join("desktop", "index.html"),
    os.path.join("core", "whisper", "whisper-cli.exe"),
)

# Leave anything younger than this alone: a second instance may have just
# started, and its directory would look abandoned for a moment.
MIN_AGE_S = 3600


def _is_ours(mei_dir):
    return all(os.path.exists(os.path.join(mei_dir, m)) for m in _MEI_MARKERS)


def _removable(path):
    """True if nothing holds `path` open.

    Windows refuses to rename a directory that has open files inside it, which
    makes rename the cheapest way to ask "is anyone using this?" without
    half-deleting a directory that turns out to be live.
    """
    probe = path + ".sweep"
    try:
        os.rename(path, probe)
    except OSError:
        return False
    try:
        os.rename(probe, path)
    except OSError:
        # Renamed away but could not be put back; delete it under the new name.
        shutil.rmtree(probe, ignore_errors=True)
        return False
    return True


def _old_enough(path, min_age_s):
    # >= so that min_age_s=0 means "no age requirement" instead of "must be at
    # least one clock tick old", which is a coin flip on a fast machine.
    try:
        return time.time() - os.path.getmtime(path) >= min_age_s
    except OSError:
        return False


def sweep_temp(min_age_s=MIN_AGE_S):
    """Delete this app's abandoned temp directories. Returns (count, bytes)."""
    tmp = tempfile.gettempdir()
    live_mei = getattr(sys, "_MEIPASS", None)
    freed = 0
    removed = 0

    try:
        entries = os.listdir(tmp)
    except OSError:
        return 0, 0

    for name in entries:
        path = os.path.join(tmp, name)
        if live_mei and os.path.normcase(path) == os.path.normcase(live_mei):
            continue
        if name.startswith("y2obi_"):
            pass
        elif name.startswith("_MEI") and os.path.isdir(path) and _is_ours(path):
            pass
        else:
            continue
        if not _old_enough(path, min_age_s) or not _removable(path):
            continue
        size = _dir_size(path)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.unlink(path)
            except OSError:
                continue
        removed += 1
        freed += size
    return removed, freed


def _dir_size(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def partial_downloads(models_dir):
    """Half-finished model downloads, as {model filename: bytes}.

    These are kept on purpose — `ensure_model` resumes onto them with a Range
    request, so deleting one silently would throw away a 1.5 GB download that
    was 90% done. They are surfaced in the models panel instead, where the user
    can resume or discard them deliberately.
    """
    out = {}
    try:
        names = os.listdir(models_dir)
    except OSError:
        return out
    for n in names:
        if n.endswith(".part"):
            try:
                out[n[:-len(".part")]] = os.path.getsize(os.path.join(models_dir, n))
            except OSError:
                pass
    return out
