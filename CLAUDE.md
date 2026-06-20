# uTubby — Project Handover

## Status: v2 — Desktop + Web (Flask/Vitra) + Cookie support

## Stack
- **Desktop**: CustomTkinter 5.2.2, Python 3.14
- **Web**: Flask 3, Vitra CSS v1.7.1 (glassmorphism, particles, themes)
- **Engine**: yt-dlp v2026.6.9
- **Mux/Convert**: FFmpeg 8.1.1 (auto-downloaded to `core/ffmpeg.exe`)
- **Build**: PyInstaller → single `.exe`
- **Deploy**: PythonAnywhere (haggis image has FFmpeg global)

## Files

### Desktop
| File | Purpose |
|------|---------|
| `main.py` | Entry. Splash → FFmpeg download → UI launch. |
| `app/binaries.py` | FFmpeg auto-download from gyan.dev. |
| `app/downloader.py` | `Downloader` class. `get_info()`, `download_mp4()`, `download_mp3()`. Progress hooks. `cancel()`. Cookie auto-detect. |
| `app/ui.py` | `App(CTk)`. 700×580. URL → Analyze → info + quality → MP4/MP3/Cancel. |
| `build.spec` | PyInstaller config. |

### Web
| File | Purpose |
|------|---------|
| `web/app.py` | Flask SPA. 9 API routes. Browser cookie auto-detect at startup. |
| `web/templates/index.html` | Single-page UI. Vitra glassmorphism. Theme picker, particles, progress bar. |
| `web/static/vitra/vitra.min.css` | Vitra CSS (Google Fonts @import removed). |
| `web/static/vitra/vitra.min.js` | Vitra JS (theme, particles, reveal, ripple, spotlight, toast). |
| `web/wsgi.py` | PythonAnywhere WSGI entry point. |
| `web/pa_setup.md` | Deployment instructions for PythonAnywhere. |

## Desktop Data Flow
1. `main.py` → FFmpegSplash (Tk) → thread `ensure_ffmpeg()` with progress
2. Splash closes → App launches
3. URL paste → `on_analyze()` → thread `Downloader.get_info()`
4. Info panel: thumb, title, channel, duration, views, likes
5. Quality select (Best/1080p/720p/480p/360p) via ComboBox
6. Video HD / MP3 Audio → thread `download_mp4()` / `download_mp3()`
7. Progress: bar + pct + speed + ETA
8. Cancel → flag → `DownloadError` → "Cancelled"
9. Complete → open `~/Videos/uTubby/` in Explorer

## Web Data Flow
1. `GET /` → render Vitra SPA
2. `POST /api/analyze` → `Downloader.get_info()` returns JSON
3. UI shows: thumb, title, channel, duration, views, likes, quality (Best-360p)
4. `POST /api/download` → spawn thread, return `task_id`
5. `GET /api/progress/<id>` → poll every 500ms (pct, speed, eta, status)
6. `POST /api/cancel/<id>` → set cancel flag
7. `GET /api/file/<id>` → after complete, serve file then schedule delete
8. Cookie badges: auto-detect browser at startup; footer badge click to upload

## Cookie System (`app/downloader.py`)
- **Auto-detect**: tries Firefox → Chrome → Edge → Brave → Chromium → Opera via yt-dlp `cookiesfrombrowser`
- **Manual**: upload `cookies.txt` via UI badge, stored at `web/cookies/cookies.txt`
- **Known limitation**: Chrome DPAPI decryption broken in yt-dlp (ctypes bug). Firefox works. Chrome users export manually.
- **Desktop**: checks `cookies.txt` next to `.exe` at startup
- **`_detect_browser()`** : iterates browser list, returns first working name or `None`

## Layout
- `url-row`: CSS Grid `1fr auto` (fixes input/button overlap)
- `app-wrap`: `width: 680px; max-width: 94vw;` glass bg + blur + shadow
- `actions-row`: flex `flex: 1` on download buttons, `flex: 0 0 110px` on Cancel
- Progress: Vitra classes `vitra-progress-bar-striped vitra-progress-bar-animated`
- Particles: 3 groups (accent accent-dark, purple, pink) with different sizes

## Quality Mapping (`QUALITY_MAP`)
Dict: `Best` → `bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best`, `1080p`→`...height<=1080...`, etc. MP3 ignores quality.

## CSS Conventions
- `box-sizing: border-box` global reset
- `min-width: 0` on flex/grid children to prevent overflow
- No `@import` in CSS (removed Google Fonts from vitra.min.css)
- No emoji characters anywhere
- All colors via `var(--vitra-color-*)` CSS custom properties

## Deployment (PythonAnywhere)
- See `web/pa_setup.md`
- FFmpeg pre-installed on haggis image
- Cookies: manual upload only (no local browsers)
- Static: map `/static/vitra/` → `web/static/vitra/`
- WSGI: point to `web/wsgi.py`

## Build to EXE
```
pip install pyinstaller
pyinstaller build.spec
# Output: dist/uTubby.exe (~35-50 MB)
```
`core/ffmpeg.exe` NOT bundled. Auto-downloads on first run.

## Output Directory
`C:\Users\<user>\Videos\uTubby\` — created on first download.

## Known Limitations
1. **No playlist support** — Single video only
2. **No thumbnail caching** — Fetches from URL every analyze
3. **Chrome DPAPI bug** — Auto-cookie only works with Firefox. Chrome users export manually.
4. **No graceful browser close** — Web app crashes if user closes tab mid-download

## Requirements
```
customtkinter>=5.2.2
yt-dlp>=2024.12.0
pillow>=10.0.0
flask>=3.0.0
pycryptodome>=3.20.0
```

## Commands
```
pip install -r requirements.txt
python main.py       # desktop
python web/app.py    # web (localhost:5000)
pyinstaller build.spec  # build exe
```

## CONVENTION: Session continuity
At session start, read this file. At session end, update it. Keep it factual, short, action-oriented.
