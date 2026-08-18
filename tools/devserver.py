"""Serve the UI for development and screenshots, without touching real user data.

    python tools/devserver.py                 # http://127.0.0.1:8799
    http://127.0.0.1:8799/                    # the app, sandboxed
    http://127.0.0.1:8799/shot/pastel/full    # a forced theme and a faked state

The app normally writes to %APPDATA%/Y2obi and ~/Downloads/Y2obi. This points
both at a throwaway directory first, so a dev session can never overwrite the
real config, delete the real models, or drop files in the user's Downloads.

/shot/<theme>[/<state>] renders the page with `data-theme` rewritten and the
DOM driven into a state that would otherwise need a real download, which is what
makes headless screenshots reproducible. States: empty, full, done, txt, file,
fileaudio, settings, focus.

Two traps this file works around, both of which produced convincing wrong
answers before:

  * CSS transitions do not advance under Chromium's --virtual-time-budget, so a
    state reached by .click() screenshots with its *previous* colours. Hence the
    injected `transition: none`.
  * pywebview injects window.pywebview only after the document loads. Stubbing
    it synchronously here is a lie the real app does not tell, so anything about
    that timing has to be verified in the built exe, never here.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SANDBOX = os.path.join(tempfile.gettempdir(), "y2obi_devserver")
os.environ.setdefault("Y2OBI_HOME", os.path.join(SANDBOX, "home"))
os.environ.setdefault("Y2OBI_OUTPUT", os.path.join(SANDBOX, "downloads"))

import app.server as server  # noqa: E402  (must follow the env setup)
from flask import Response  # noqa: E402

server._static_dir = os.path.join(ROOT, "desktop")

# Mark the sandbox as already onboarded, otherwise the welcome modal covers
# every state you are trying to look at. /shot/<theme>/onboarding shows it.
os.makedirs(os.path.dirname(server.CONFIG_PATH), exist_ok=True)
if not os.path.exists(server.CONFIG_PATH):
    import json as _json
    with open(server.CONFIG_PATH, "w", encoding="utf-8") as _f:
        _json.dump({"onboarded": True}, _f)

STUB = """
<style>*, *::before, *::after { transition: none !important; animation: none !important; }</style>
<script>window.pywebview = { api: { pick_file: () => Promise.resolve(null) } };</script>
"""

FAKE = """
<script>
window.addEventListener('load', () => setTimeout(() => {
  const $ = id => document.getElementById(id);
  const STATE = 'S_TATE';
  if (STATE === 'settings') { $('settingsBtn').click(); return; }
  if (STATE === 'onboarding') { return; }
  if (STATE === 'focus') { document.querySelectorAll('#qualityChips .q-chip')[2].focus(); return; }
  if (STATE === 'botfix') {
    $('urlInput').value = 'https://www.youtube.com/watch?v=BOTCHECK';
    $('analyzeBtn').click();
    return;
  }
  if (STATE === 'file' || STATE === 'fileaudio') {
    document.querySelector('.src-tab[data-src="file"]').click();
    const audio = STATE === 'fileaudio';
    $('fileName').textContent = audio ? 'lecture recording.m4a' : 'holiday montage 2026.mp4';
    $('fileName').classList.remove('empty');
    $('titleText').textContent = $('fileName').textContent;
    $('channelText').textContent = 'Local file';
    $('metaText').textContent = audio ? '48m 12s  ·  44 MB  ·  aac'
                                      : '12m 04s  ·  1920x1080  ·  842 MB  ·  h264';
    const icon = audio
      ? '<path d="M9 18V6l10-2v12M9 18a3 3 0 11-3-3 3 3 0 013 3zm10-2a3 3 0 11-3-3 3 3 0 013 3z"/>'
      : '<path d="M15 10l4.5-2.6v9.2L15 14M4 6h11v12H4z"/>';
    $('thumbPlaceholder').innerHTML =
      '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + icon + '</svg>'
      + '<span class="thumb-ext">' + (audio ? 'M4A' : 'MP4') + '</span>';
    $('infoCard').classList.add('visible');
    document.querySelectorAll('.fmt-chip').forEach(c => c.disabled = false);
    $('fmtWebm').disabled = true;
    if (audio) { $('fmtMp4').disabled = true;
      document.querySelectorAll('.fmt-chip').forEach(c => c.classList.remove('active'));
      $('fmtMp3').classList.add('active'); }
    $('downloadBtn').disabled = false;
    $('downloadBtn').textContent = 'Convert';
    $('qualityRow').classList.toggle('hidden', audio);
    $('qualityRow').querySelector('.opt-label').textContent = 'Resolution';
    $('qualityChips').innerHTML = ['Original','1080p','720p','480p','360p']
      .map((q,i) => `<span class="q-chip${i===0?' active':''}">${q}</span>`).join('');
    return;
  }
  $('urlInput').value = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
  $('titleText').textContent = 'Rick Astley - Never Gonna Give You Up (Official Music Video)';
  $('channelText').textContent = 'Rick Astley';
  $('metaText').textContent = '3m 33s  ·  1.6B views  ·  18M likes';
  $('infoCard').classList.add('visible');
  $('qualityChips').innerHTML = ['Best','2160p','1440p','1080p','720p','480p','360p']
    .map((q,i) => `<span class="q-chip${i===3?' active':''}">${q}</span>`).join('');
  document.querySelectorAll('.fmt-chip').forEach(c => c.disabled = false);
  $('downloadBtn').disabled = false;
  $('progressCard').classList.add('visible');
  if (STATE === 'done') {
    $('barFill').style.width = '100%'; $('pctText').textContent = '100%';
    $('statusText').textContent = 'Saved to ~/Downloads/Y2obi/';
    $('speedText').textContent = 'Done';
    $('resultRow').classList.add('visible');
  } else {
    $('actionsRow').classList.add('busy');
    $('barFill').style.width = '64%'; $('pctText').textContent = '64%';
    $('statusText').textContent = 'Downloading...';
    $('speedText').textContent = '4.2 MB/s  1m 12s';
  }
  $('cookieLink').textContent = 'Cookies: firefox';
  $('cookieLink').classList.add('ok');
  $('detailsGroup').style.display = 'flex';
  TXT_BLOCK
}, 500));
</script></body>"""

TXT_BLOCK = """
  document.querySelectorAll('.fmt-chip').forEach(c => c.classList.remove('active'));
  $('fmtTxt').classList.add('active');
  $('qualityRow').classList.add('hidden');
  $('modelRow').classList.remove('hidden');
  $('langRow').classList.remove('hidden');
  $('downloadBtn').textContent = 'Transcribe';
  $('transcriptHint').textContent = 'First run downloads the best model (~1620 MB), once.';
  $('statusText').textContent = 'Transcribing part 2/4...';
  $('speedText').textContent = '12m 30s';
"""


_real_analyze = server.app.view_functions["analyze"]


def analyze_or_fake():
    """Answer the way YouTube does when its bot check trips, for one magic URL.

    Reaching that state for real means getting rate-limited by YouTube, which is
    not something to depend on while working on the recovery UI. Any other URL
    goes to the real extractor untouched.
    """
    from flask import jsonify, request
    from app.downloader import installed_browsers
    if "BOTCHECK" in ((request.json or {}).get("url") or ""):
        return jsonify({
            "error": "YouTube wants to confirm you are signed in before it hands "
                     "this video over.",
            "needs_cookies": True,
            "browsers": installed_browsers(),
        }), 400
    return _real_analyze()


server.app.view_functions["analyze"] = analyze_or_fake


@server.app.route("/shot/<theme>")
@server.app.route("/shot/<theme>/<state>")
def shot(theme, state="empty"):
    page = open(os.path.join(server._static_dir, "index.html"), encoding="utf-8").read()
    html = page.replace('data-theme="dark"', f'data-theme="{theme}"', 1)
    html = html.replace("defaultTheme: 'dark'", f"defaultTheme: '{theme}'")
    html = html.replace("<body>", "<body>" + STUB, 1)
    if state != "empty":
        html = html.replace("</body>", FAKE.replace("S_TATE", state).replace(
            "TXT_BLOCK", TXT_BLOCK if state == "txt" else ""))
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    print(f"sandbox: {SANDBOX}")
    print("serving http://127.0.0.1:8799  (Ctrl+C to stop)")
    server.app.run(host="127.0.0.1", port=8799, debug=False, use_reloader=False,
                   threaded=True)
