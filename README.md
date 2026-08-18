# Y2obi

> Clean, fast YouTube downloader for Windows. Paste a URL, pick quality, done.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey?style=flat-square&logo=windows)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

---

## Download

**[→ Latest release: Y2obi v1.1.0](https://github.com/DesvoSoft/Y2obi/releases/latest)**

1. Download `Y2obi-win.zip`
2. Extract `Y2obi.exe` anywhere
3. Run — no installer, no admin rights required

> First launch may install the WebView2 runtime automatically if it's not already on your system.

### "Windows protected your PC" / browser blocked the download?

Y2obi isn't code-signed (a signing certificate costs money we're not putting
into a free hobby project), so Windows SmartScreen, Defender, or your browser
may flag the download or show a warning the first time. This is a false
positive common to small unsigned apps, not malware:

- **Browser deleted/blocked the file**: check the browser's download history,
  restore/keep it.
- **SmartScreen popup on launch**: click **More info → Run anyway**.
- **Want to verify the file is untampered**: each release includes a
  `checksum.txt`. Compare it against the zip with:
  ```powershell
  Get-FileHash Y2obi-win.zip -Algorithm SHA256
  ```
  It should match the hash in `checksum.txt` for that release.
- Prefer to skip all of this? Run from source instead — see below.

---

## Features

- Download YouTube videos — WebM/MP4 up to **4K**
- Download **MP3 audio** at 320kbps
- **Transcribe** any video to `.txt` + `.srt` — runs offline on your CPU, no API key, no upload
- **Use your own files**: pick a local video or audio file to transcribe, convert to MP3, or convert/downscale to MP4
- Quality selector: Best / 2160p / 1440p / 1080p / 720p / 480p / 360p
- Real-time progress bar with speed and ETA
- Skips re-downloading files that already exist
- Pasting a URL with `&list=...` (mix/radio/autoplay links) downloads just that video, not the playlist
- Cookie support for age-restricted content
- **GPU transcription** via Vulkan (NVIDIA / AMD / Intel), with automatic CPU fallback
- Settings panel: themes, processing device, speech models, cookies, storage
- Glassmorphism UI powered by [Vitra CSS](https://vitracss.com)
- Single `.exe` — no Python, no FFmpeg, no Node.js, no setup, fully offline after download

---

## Transcription

Pick **TXT** as the format and Y2obi transcribes the video with
[whisper.cpp](https://github.com/ggerganov/whisper.cpp), writing a `.txt` and a
timestamped `.srt` next to your other downloads. Works on any length — long
audio is split into chunks internally so the transcript doesn't degrade.

Two accuracy levels are offered up front:

| Model | Size | Speed (CPU) |
|-------|------|-------------|
| Balanced | ~488 MB | roughly 1/5 of the video's length |
| Best (default) | ~1.6 GB | roughly 1/4 of the video's length |

Four more (Tiny, Base, Medium, Large v3) are a click away under **Models** in
the footer, where you can download one ahead of time, see what each is costing
you on disk, delete the ones you don't want, and set your default. Anything you
download shows up as an accuracy chip.

Models live in `%APPDATA%\Y2obi\models\` and are **never bundled in the exe** —
you only ever download the one you choose. After that transcription is fully
offline; nothing is uploaded anywhere. Language can be left on Auto or pinned
to one of eight.

**GPU acceleration** is on by default when your graphics card supports Vulkan —
which covers NVIDIA, AMD and Intel, including integrated graphics. Measured on
111.5 s of speech: 11.8 s on CPU versus 3.3 s on an RTX 5060 Ti, for the same
transcript word for word. Y2obi asks the engine what it can use, shows the card
it found in **Settings → Processing**, and falls back to the CPU on its own if
the GPU is unavailable or fails mid-run. No drivers or toolkits to install.

> On CPU only, transcription pins most of your cores and a one-hour video takes
> roughly 15 minutes.

---

## Your own files

Switch the source to **Local file** and pick anything ffmpeg can read — mp4,
mkv, webm, mov, avi, mp3, m4a, wav, flac, ogg and friends. From there you can:

- **Transcribe** it to `.txt` + `.srt`, same as a YouTube video
- **Convert to MP3** — pulls the audio out at 192 kbps
- **Convert to MP4** — keeps the original resolution or downscales to
  1080p/720p/480p/360p

An h264 file that needs no resize is remuxed rather than re-encoded, so it
finishes in seconds instead of minutes. Results land in
`%USERPROFILE%\Downloads\Y2obi\`, and a name that would collide gets a
` (2)` suffix — your source file is never overwritten.

The file is read straight off disk by the local ffmpeg. Nothing is uploaded and
nothing is copied anywhere first.

---

## What it leaves on your disk

Y2obi is portable — no installer, no registry keys, no services. It writes:

| Path | What |
|------|------|
| `%USERPROFILE%\Downloads\Y2obi\` | your downloads and transcripts |
| `%APPDATA%\Y2obi\` | settings, cookie jar, speech models |
| `%LOCALAPPDATA%\Y2obi\webview\` | browser profile for the window |

Temporary working files go to `%TEMP%` and are removed when the app closes. If
it is ever force-killed, the next launch sweeps what was left behind — and only
ever its own. Deleting those three folders removes Y2obi completely.

## Cookie Support

Some videos require authentication (age-restricted, private). Open **Settings -> Cookies** to export them from Firefox, Edge, Brave or Chrome, or to upload a `cookies.txt` by hand.

Cookies are stored in `%APPDATA%\Y2obi\cookies.txt` and persist across launches.

> **Chrome users:** Export cookies manually with a browser extension like [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc). Firefox export works natively from the app.

---

## Run from Source

**Easiest way (Windows):** double-click `run.bat`. It creates a virtual
environment, installs dependencies, and launches the app — only needs
[Python 3.10+](https://python.org) installed first. Safe to double-click
again later, it reuses the same environment.

Manual way:

```bash
pip install -r requirements.txt
python main.py
```

FFmpeg downloads automatically on first run (only when running from source).

## Build `.exe`

```bash
pip install pyinstaller
python -m PyInstaller build.spec
# Output: dist/Y2obi.exe
```

`build.spec` bundles `core/ffmpeg.exe` and `core/whisper/` straight into the
executable, so the built app needs no runtime download for either. Run
`python main.py` once from source first if `core/ffmpeg.exe` doesn't exist yet
— it'll be fetched automatically before you build.

`core/whisper/` (whisper-cli.exe plus the ggml DLLs, ~10 MB) is not fetched
automatically — grab a whisper.cpp Windows release build and drop its contents
there. Without it the app still builds and runs; the TXT format is simply
greyed out.

Releases are also built automatically by [GitHub Actions](.github/workflows/release.yml)
on every `v*` tag push.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Download engine | yt-dlp |
| Muxing / conversion | FFmpeg (bundled) |
| Transcription | whisper.cpp (bundled) + Vulkan GPU backend |
| Backend | Flask 3 (local, embedded) |
| Frontend | Vitra CSS + pywebview |
| Build | PyInstaller |

---

## Project Structure

```
Y2obi/
├── app/
│   ├── downloader.py     # yt-dlp wrapper — video/audio/mp3, cookies, progress hooks
│   ├── cleanup.py        # sweeps leftovers from killed runs; reports partial downloads
│   ├── converter.py      # ffmpeg wrapper for local files — probe, mp3/mp4, cancel
│   ├── transcriber.py    # whisper.cpp wrapper — models, chunking, txt/srt output
│   ├── server.py         # Flask app — API routes served to the embedded webview
│   └── binaries.py       # FFmpeg + whisper resolution — bundled binary, PATH, or download fallback
├── desktop/
│   ├── index.html        # UI — glassmorphism, particles, options panel, models panel
│   └── static/           # Vitra CSS/JS, icons
├── main.py               # Entry point — WebView2 check, FFmpeg, launch
├── run.bat               # Windows one-click setup + launch (source installs)
├── tests/                # stdlib unittest suite — python -m unittest discover tests
├── build.spec            # PyInstaller config
├── version_info.txt      # Exe file/product metadata (embedded in build)
└── requirements.txt      # Dependencies
```

---

## License

MIT — do whatever you want, just don't abuse it.
