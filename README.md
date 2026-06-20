# Y2obi

> YouTube downloader — web app + desktop app. Built with yt-dlp, Flask, and CustomTkinter.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-black?style=flat-square&logo=flask)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

---

## Features

- Download YouTube videos as **MP4** (up to 4K), **WebM**, or **MP3 320kbps**
- Quality selector: Best / 2160p / 1440p / 1080p / 720p / 480p / 360p
- Real-time progress bar — percent, speed, ETA
- Cookie support — upload `cookies.txt` to bypass age-gates and rate limits
- Glassmorphism UI powered by [Vitra CSS](https://vitracss.com)
- Desktop app for Windows (CustomTkinter, single `.exe`)

---

## Web App

### Run locally

```bash
pip install -r requirements-web.txt
python web/app.py
# Open http://localhost:5000
```

### Deploy to Render (free tier)

1. Fork / clone this repo and push to GitHub
2. Create a new **Web Service** on [Render](https://render.com), connect the repo
3. Render auto-detects `render.yaml` — no manual config needed
4. Add environment variables in the Render dashboard:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Auto-generated | Flask session key (Render generates it) |
| `COOKIES_B64` | Optional | Base64-encoded `cookies.txt` for cookie auth |
| `DOWNLOAD_DIR` | Optional | Temp download path (default: `/tmp/y2obi-web`) |

**To encode your cookies file:**
```bash
base64 -w0 cookies.txt
# Paste the output as COOKIES_B64 in Render environment vars
```

> **Note:** Render free tier sleeps after 15 min of inactivity. In-progress downloads survive within the same instance. Downloaded files are deleted after 10 minutes.

---

## Desktop App (Windows)

### Run from source

```bash
pip install -r requirements.txt
python main.py
```

FFmpeg is auto-downloaded on first run (`core/ffmpeg.exe`).

### Build `.exe`

```bash
pip install pyinstaller
pyinstaller build.spec
# Output: dist/Y2obi.exe
```

---

## Cookie Support

Some videos require authentication (age-restricted, private, etc.). Y2obi supports cookies in two ways:

**Web app — upload via UI**
Click the cookie badge in the footer and upload a `cookies.txt` (Netscape format).

**Web app — environment variable (recommended for Render)**
Encode your cookies file and set `COOKIES_B64`.

**Desktop app**
Place `cookies.txt` next to the `.exe`. Auto-detected on startup.

> Chrome users: DPAPI decryption is broken in yt-dlp on some systems. Export cookies manually with a browser extension (e.g. [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)). Firefox auto-export works natively.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Download engine | yt-dlp |
| Muxing | FFmpeg |
| Web backend | Flask 3 |
| Web frontend | Vitra CSS (glassmorphism) |
| Desktop UI | CustomTkinter |
| Build | PyInstaller |
| Deploy | Render |

---

## Project Structure

```
Y2obi/
├── app/
│   ├── downloader.py     # yt-dlp wrapper (MP4/WebM/MP3, cookies, progress)
│   ├── binaries.py       # FFmpeg auto-download (Windows only)
│   └── ui.py             # Desktop UI (CustomTkinter)
├── web/
│   ├── app.py            # Flask app — 9 API routes
│   ├── templates/
│   │   └── index.html    # Single-page UI
│   ├── static/vitra/     # Vitra CSS + JS
│   └── wsgi.py           # WSGI entry (PythonAnywhere)
├── main.py               # Desktop entry point
├── Procfile              # Render / Heroku start command
├── render.yaml           # Render deployment config
├── requirements.txt      # All deps (desktop + web)
└── requirements-web.txt  # Web-only deps (no CustomTkinter/Pillow)
```

---

## License

MIT — do whatever you want, just don't abuse public instances.
