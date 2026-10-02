"""The single place the version number lives.

It used to live in main.py, which the server cannot import without a cycle. The
update check needs it, the log banner needs it, and `--version` needs it, so it
moved here rather than being spelled out three times and drifting.

`version_info.txt` carries it a fourth time for the Windows file metadata, which
PyInstaller reads at build time and cannot read from Python. `tests/test_version`
asserts the two agree, because a mismatch there is invisible until someone reads
the properties of a shipped exe.
"""

VERSION = "1.5.0"


def as_tuple(text=None):
    """(1, 4, 1) from "1.4.1", "v1.4.1" or "1.4.1-beta". None if unparseable.

    Tolerant on purpose: it compares our own constant against whatever a GitHub
    release happens to be tagged, and tags are written by hand.
    """
    # `text or VERSION` would be wrong: an empty tag is not "no argument", and
    # falling back to our own version would report a nameless release as the one
    # already installed.
    if text is None:
        text = VERSION
    text = text.strip().lstrip("vV")
    if not text:
        return None
    parts = []
    for chunk in text.split(".")[:3]:
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            return None
        parts.append(int(digits))
    if not parts:
        return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate, current=None):
    """True if `candidate` is a later version than `current`.

    A tag that cannot be parsed is never newer. Announcing an update the user
    cannot act on is worse than staying quiet.
    """
    a, b = as_tuple(candidate), as_tuple(current)
    if a is None or b is None:
        return False
    return a > b
