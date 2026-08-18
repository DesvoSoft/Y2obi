"""Test package init — redirects the app's data roots before anything imports it.

app.server resolves DOWNLOAD_DIR and %APPDATA%/Y2obi at import time, so this has
to happen here, in the package __init__ that unittest discovery imports first.
Without it a stray test writes into the real profile: during development that
actually overwrote a real config.json and dropped files in the user's Downloads
folder, which had to be restored by hand.
"""
import os
import tempfile

_SANDBOX = os.path.join(tempfile.gettempdir(), "y2obi_tests")
os.environ["Y2OBI_HOME"] = os.path.join(_SANDBOX, "home")
os.environ["Y2OBI_OUTPUT"] = os.path.join(_SANDBOX, "downloads")
