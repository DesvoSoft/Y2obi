# Y2obi — Project Handover

## Status: v4 — Live on Render + bgutil POT provider

## Stack
- **Desktop**: CustomTkinter 5.2.2, Python 3.14
- **Web**: Flask 3 + gunicorn 1 worker, Vitra CSS v1.7.1 (glassmorphism, particles, themes)
- **Engine**: yt-dlp >=2025.05.22
- **Mux/Convert**: FFmpeg (auto-download on Windows; system binary on Linux/Render)
- **Bot bypass**: bgutil-ytdlp-pot-provider (Node.js HTTP server on port 4416, auto-started at Flask startup)
- **Build**: PyInstaller -> single `.exe`
- **Deploy**: Render (free tier, Virginia US East)
- **Repo**: https://github.com/DesvoSoft/Y2obi
- **Live**: https://y2obi.onrender.com

## Files

### Desktop
| File | Purpose |
|------|---------|
| `main.py` | Entry. Splash -> FFmpeg download -> UI launch. |
| `app/binaries.py` | FFmpeg auto-download (Windows only; Linux returns system `ffmpeg`). |
| `app/downloader.py` | `Downloader` class. `get_info()`, `download_mp4/webm/mp3()`. Always uses `web` client — bgutil provides POT automatically. |
| `app/ui.py` | `App(CTk)`. 700x580. URL -> Analyze -> info + quality -> MP4/MP3/Cancel. |
| `build.spec` | PyInstaller config. |

### Web
| File | Purpose |
|------|---------|
| `web/app.py` | Flask SPA. 9 API routes. `_make_dl()` fresh Downloader per request. `_start_bgutil()` launches bgutil Node.js server at startup. |
| `web/templates/index.html` | Single-page UI. Vitra glassmorphism. cookies.txt extension link in footer. |
| `web/static/favicon.svg` | Dog favicon (purple). |
| `web/static/vitra/` | Vitra CSS + JS. |
| `web/wsgi.py` | PythonAnywhere WSGI (legacy). |
| `Procfile` | `gunicorn web.app:app --workers 1 --timeout 300` |
| `render.yaml` | Render deploy config — installs Node.js 20 + builds bgutil server. |
| `requirements-web.txt` | Web deps including `bgutil-ytdlp-pot-provider`. |

## Render Deploy Config
- **Build command** (in render.yaml):
  1. `pip install -r requirements-web.txt`
  2. Install Node.js 20 via nodesource
  3. Clone bgutil-ytdlp-pot-provider v1.3.1 to `/opt/bgutil`
  4. `npm ci && npx tsc` in `/opt/bgutil/server`
- **Start command**: `gunicorn web.app:app --workers 1 --timeout 300 --bind 0.0.0.0:$PORT`
- **Workers**: 1 (not 2) — bgutil server is per-process, multiple workers would each try to bind port 4416
- **Env vars**:
  - `SECRET_KEY`: auto-generated
  - `COOKIES_B64`: base64-encoded cookies.txt (optional, adds auth layer on top of POT)
  - `DOWNLOAD_DIR`: `/tmp/y2obi-web`
  - `BGUTIL_SERVER_HOME`: `/opt/bgutil/server`

## How bgutil Works
1. Flask startup calls `_start_bgutil()` in a daemon thread
2. bgutil Node.js server listens on `127.0.0.1:4416`
3. `bgutil-ytdlp-pot-provider` pip package registers itself as yt-dlp POT provider
4. Every yt-dlp call automatically fetches a fresh POT from `127.0.0.1:4416`
5. YouTube sees a valid BotGuard attestation — no bot check
6. `web` client used always (full DASH format list, up to 4K)

## yt-dlp Client Strategy
- **All operations**: `web` client only
- **POT**: provided automatically by bgutil HTTP server
- **Cookies**: optional extra layer (set COOKIES_B64 or upload via UI)
- **QUALITY_MAP**: tuples `(max_height, None)` + `format_sort`
- **AUDIO_FORMAT**: `bestaudio/best` -> FFmpeg -> 320kbps mp3

## Cookie System
- Upload via UI badge -> saved to `web/cookies/cookies.txt`
- `COOKIES_B64` env var -> decoded at startup to `web/cookies/cookies.txt`
- `_make_dl()` checks `os.path.exists(COOKIES_PATH)` fresh on each request
- Cookies are bonus — bgutil handles the real bypass

## Known Issues / Limits
1. Render free tier sleeps after 15min inactivity — bgutil server dies with process, restarts on next request (cold start ~30s)
2. 1 gunicorn worker = no parallel downloads
3. No playlist support
4. Desktop app does NOT use bgutil (would need Node.js locally) — relies on cookies or android_vr client

## Build to EXE
```
pip install pyinstaller
pyinstaller build.spec
# Output: dist/Y2obi.exe
```

## Output Directory
- Desktop: `C:\Users\<user>\Videos\Y2obi\`
- Web: `/tmp/y2obi-web/` (ephemeral, 10min cleanup)

## Commands
```
pip install -r requirements.txt
python main.py                    # desktop
python web/app.py                 # web dev (localhost:5000, no bgutil)
pip install -r requirements-web.txt
gunicorn web.app:app              # web prod (bgutil auto-starts if Node.js present)
pyinstaller build.spec            # build exe
```

## CONVENTION: Session continuity
At session start, read this file. At session end, update it. Keep it factual, short, action-oriented.
