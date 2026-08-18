# Y2obi

> YouTube downloader and offline transcriber for Windows. Paste a URL, pick a
> format, done. Works on your own video and audio files too.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey?style=flat-square&logo=windows)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

---

## Download

**[→ Latest release](https://github.com/DesvoSoft/Y2obi/releases/latest)**

1. Download `Y2obi-win.zip`
2. Extract `Y2obi.exe` anywhere
3. Run. No installer, no admin rights required

> First launch may install the WebView2 runtime automatically if it's not already on your system.

### "Windows protected your PC" / browser blocked the download?

Y2obi isn't code-signed, so Windows SmartScreen, Defender, or your browser may
warn you the first time. That's a false positive common to small unsigned apps,
not malware.

I'm an independent developer, and a Windows code-signing certificate is a
recurring yearly cost this project doesn't justify yet. Without one, Windows has
no publisher to vouch for and warns about any new executable until enough people
have run it, and that reputation builds slowly.

**If that leaves you uneasy, don't take my word for it.** The entire source is
in this repository, the release is built by a [public GitHub Actions
workflow](.github/workflows/release.yml) you can read line by line, and every
release ships a checksum so you can confirm the download is byte-for-byte what
CI produced. You can also skip the executable and [run from source](#run-from-source).

Getting past the warning:

- **Browser deleted/blocked the file**: check the browser's download history,
  restore/keep it.
- **SmartScreen popup on launch**: click **More info → Run anyway**.
- **Want to verify the file is untampered**: each release includes a
  `checksum.txt`. Compare it against the zip with:
  ```powershell
  Get-FileHash Y2obi-win.zip -Algorithm SHA256
  ```
  It should match the hash in `checksum.txt` for that release.
- Prefer to skip all of this? Run from source instead, see below.

---

## Features

**Downloading**
- YouTube video in MP4 or WebM, up to 4K
- MP3 audio at 320 kbps
- Quality selector: Best / 2160p / 1440p / 1080p / 720p / 480p / 360p
- Progress with speed and ETA, and it skips files you already downloaded
- A URL with `&list=...` (mix, radio, autoplay) downloads that one video, not the playlist
- Optional cookies for age-restricted or private videos

**Transcribing**
- Any video or audio to `.txt` plus a timestamped `.srt`
- Runs entirely on your machine. No API key, no account, nothing uploaded
- Uses your GPU through Vulkan (NVIDIA, AMD, Intel) and falls back to the CPU on its own
- Six model sizes to choose from, downloaded only when you ask for one

**Your own files**
- Transcribe a local video or audio file
- Convert to MP3, or to MP4 with an optional downscale

**The app itself**
- One `.exe`. No installer, no admin rights, no Python or FFmpeg to install
- Six themes, and a settings panel for models, processing device, cookies and storage
- Glassmorphism UI built on [Vitra CSS](https://vitracss.com)

---

## Transcription

Pick **TXT** as the format and Y2obi transcribes the video with
[whisper.cpp](https://github.com/ggerganov/whisper.cpp), writing a `.txt` and a
timestamped `.srt` next to your other downloads. Works on any length: long
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

Models live in `%APPDATA%\Y2obi\models\` and are **never bundled in the exe**.
You only ever download the one you choose. After that transcription is fully
offline; nothing is uploaded anywhere. Language can be left on Auto or pinned
to one of eight.

**GPU acceleration** is on by default when your graphics card supports Vulkan,
which covers NVIDIA, AMD and Intel, including integrated graphics. Measured on
111.5 s of speech: 11.8 s on CPU versus 3.3 s on an RTX 5060 Ti, for the same
transcript word for word. Y2obi asks the engine what it can use, shows the card
it found in **Settings → Processing**, and falls back to the CPU on its own if
the GPU is unavailable or fails mid-run. No drivers or toolkits to install.

> On CPU only, transcription pins most of your cores and a one-hour video takes
> roughly 15 minutes.

---

## Your own files

Switch the source to **Local file** and pick anything ffmpeg can read: mp4,
mkv, webm, mov, avi, mp3, m4a, wav, flac, ogg and friends. From there you can:

- **Transcribe** it to `.txt` + `.srt`, same as a YouTube video
- **Convert to MP3**, pulling the audio out at 192 kbps
- **Convert to MP4**, keeping the original resolution or downscaling to
  1080p/720p/480p/360p

An h264 file that needs no resize is remuxed rather than re-encoded, so it
finishes in seconds instead of minutes. Results land in
`%USERPROFILE%\Downloads\Y2obi\`, and a name that would collide gets a
` (2)` suffix, so your source file is never overwritten.

The file is read straight off disk by the local ffmpeg. Nothing is uploaded and
nothing is copied anywhere first.

---

## What it leaves on your disk

Y2obi is portable. No installer, no registry keys, no services. It writes:

| Path | What |
|------|------|
| `%USERPROFILE%\Downloads\Y2obi\` | your downloads and transcripts |
| `%APPDATA%\Y2obi\` | settings, cookie jar, speech models |
| `%LOCALAPPDATA%\Y2obi\webview\` | browser profile for the window |

Temporary working files go to `%TEMP%` and are removed when the app closes. If
it is ever force-killed, the next launch sweeps what was left behind, and only
ever its own. Deleting those three folders removes Y2obi completely.

## Cookie Support

If YouTube asks Y2obi to confirm it isn't a bot, the app says so in plain words
and puts the fix in the message itself: one button per browser you actually have
installed. Click it and the download retries on its own. You only do this once:
Y2obi remembers the browser and reconnects by itself when the session expires. Nothing is uploaded
anywhere; the cookies stay on your machine and are only sent to YouTube, exactly
as your browser sends them.

**Edge, Chrome and Brave cannot be read at all**, and closing them does not
help: since Chromium 127 they encrypt their cookie store with App-Bound
Encryption, which ties the key to the browser's own executable so that no other
program can decrypt it. That is not something Y2obi can work around.

So Y2obi offers its own window instead. Pick **Sign in to YouTube**, sign in
normally in the window that opens, close it, and the download continues. Firefox
is still readable directly, and a `cookies.txt` exported with a browser extension
works too.

Some videos need you to be signed in (age-restricted or private ones). Open
**Settings → Cookies** to export them from Firefox, Edge, Brave or Chrome, or
to upload a `cookies.txt` by hand.

Cookies are stored in `%APPDATA%\Y2obi\cookies.txt` and persist across launches.

> **Chrome users:** Export cookies manually with a browser extension like [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc). Firefox export works natively from the app.

---

## Troubleshooting

The app is built as a windowed program, so it normally prints nothing. If
something misbehaves, run it from a terminal:

```powershell
Y2obi.exe --debug
```

That writes everything to `%TEMP%\y2obi-debug.log` (startup, the local port,
every request, any error) and enables right-click → Inspect inside the window.
Attach that log to a bug report.

| Flag | What it does |
|------|--------------|
| `--debug` | log to `%TEMP%\y2obi-debug.log`, enable Inspect in the window |
| `--log FILE` | write the log somewhere specific instead |
| `--reset` | delete saved settings, so the first-run screen appears again |
| `--cpu` | force CPU transcription for one run, without changing your setting |
| `--version` | print the version |

`--cpu` is the quickest way to tell a GPU problem apart from everything else: if
a transcription fails on the GPU but works with `--cpu`, it is the graphics
driver, not the app.

---

## Run from Source

**Easiest way (Windows):** double-click `run.bat`. It creates a virtual
environment, installs dependencies, and launches the app. Only needs
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
executable, so the built app needs no runtime download for either. If
`core/ffmpeg.exe` isn't there yet, run `python main.py` once from source and it
will be fetched automatically.

`core/whisper/` is not fetched automatically. It needs seven files, and their
exact versions are pinned in `core/whisper/MANIFEST.json`:

- six from a [whisper.cpp Windows release](https://github.com/ggml-org/whisper.cpp/releases)
  (`whisper-cli.exe`, `whisper.dll`, `ggml.dll`, `ggml-base.dll`,
  `ggml-cpu-haswell.dll`, `ggml-cpu-x64.dll`)
- `ggml-vulkan.dll` from a [llama.cpp Vulkan release](https://github.com/ggml-org/llama.cpp/releases),
  because whisper.cpp publishes no Vulkan build for Windows. The two projects
  share ggml, and this combination is verified rather than assumed

`build.spec` refuses to build if any file stops matching the manifest, since a
mismatch between those two projects would corrupt transcripts quietly instead of
failing outright. After changing any of them, run:

```
python tools/verify_whisper.py
```

It transcribes the same audio on the CPU and the GPU and fails if the results
differ. Without `core/whisper/` the app still builds and runs; the TXT format is
simply greyed out.

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
│   ├── downloader.py     # yt-dlp wrapper: video, audio, cookies, progress
│   ├── converter.py      # ffmpeg wrapper for local files: probe, mp3/mp4, cancel
│   ├── transcriber.py    # whisper.cpp wrapper: models, chunking, txt/srt output
│   ├── cleanup.py        # clears leftovers from interrupted runs
│   ├── server.py         # Flask app, the API the window talks to
│   └── binaries.py       # finds ffmpeg and whisper (bundled first, then PATH)
├── desktop/
│   ├── index.html        # the whole UI
│   └── static/           # Vitra CSS/JS, icons
├── tools/
│   ├── devserver.py      # UI on :8799 with sandboxed data, for screenshots
│   └── verify_whisper.py # checks the CPU and GPU backends still agree
├── tests/                # unittest suite: python -m unittest discover tests
├── main.py               # entry point: WebView2 check, ffmpeg, launch
├── run.bat               # one-click setup and launch when running from source
├── build.spec            # PyInstaller config
├── version_info.txt      # exe file/product metadata
└── requirements.txt      # dependencies
```

---

## License

MIT. Do whatever you want, just don't abuse it.
