# Y2obi

> Clean, fast YouTube downloader for Windows. Paste a URL, pick quality, done.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey?style=flat-square&logo=windows)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

---

## Download

**[→ Latest release: Y2obi v1.0.0](https://github.com/DesvoSoft/Y2obi/releases/latest)**

1. Download `Y2obi-v1.0.0.zip`
2. Extract `Y2obi.exe` anywhere
3. Run — no installer, no admin rights required

> First launch may install the WebView2 runtime automatically if it's not already on your system.

---

## Features

- Download YouTube videos — WebM/MP4 up to **4K**
- Download **MP3 audio** at 320kbps
- Quality selector: Best / 2160p / 1440p / 1080p / 720p / 480p / 360p
- Real-time progress bar with speed and ETA
- Skips re-downloading files that already exist
- Cookie support for age-restricted content
- Glassmorphism UI powered by [Vitra CSS](https://vitracss.com)
- Single `.exe` — no Python, no Node.js, no setup

---

## Cookie Support

Some videos require authentication (age-restricted, private). Upload a `cookies.txt` via the cookie badge in the app footer.

Cookies are stored in `%APPDATA%\Y2obi\cookies.txt` and persist across launches.

> **Chrome users:** Export cookies manually with a browser extension like [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc). Firefox export works natively from the app.

---

## Run from Source

```bash
pip install -r requirements.txt
python main.py
```

FFmpeg downloads automatically on first run.

## Build `.exe`

```bash
pip install pyinstaller
python -m PyInstaller build.spec
# Output: dist/Y2obi.exe
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| Download engine | yt-dlp |
| Muxing | FFmpeg (auto-downloaded) |
| Backend | Flask 3 (local, embedded) |
| Frontend | Vitra CSS + pywebview |
| Build | PyInstaller |

---

## Project Structure

```
Y2obi/
├── app/
│   ├── downloader.py     # yt-dlp wrapper — video/audio/mp3, cookies, progress hooks
│   ├── server.py         # Flask app — API routes served to the embedded webview
│   └── binaries.py       # FFmpeg auto-download (Windows)
├── desktop/
│   ├── index.html        # UI — glassmorphism, particles, quality picker
│   └── static/           # Vitra CSS/JS, icons
├── main.py               # Entry point — WebView2 check, FFmpeg, launch
├── build.spec            # PyInstaller config
└── requirements.txt      # Dependencies
```

---

## License

MIT — do whatever you want, just don't abuse it.
