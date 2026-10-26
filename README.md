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
- Whole playlists and channels, see [Playlists](#playlists)
- Trim a download to a time range (`1:30` to `4:05`)
- Progress with speed and ETA, and it skips files you already downloaded
- Optional YouTube sign-in for age-restricted, private or throttled videos

**Transcribing**
- Any video or audio to `.txt`, with an optional timestamped `.srt`
- Optional timestamps in the `.txt` every 30 s to 10 min, as a point (`[00:01:00]`) or a range (`[00:01:00 - 00:02:00]`)
- Runs entirely on your machine. No API key, no account, nothing uploaded
- Uses your GPU through Vulkan (NVIDIA, AMD, Intel) and falls back to the CPU on its own
- Six model sizes to choose from, downloaded only when you ask for one

**Your own files**
- Transcribe a local video or audio file
- Convert to MP3, or to MP4 with an optional downscale

**The app itself**
- One `.exe`. No installer, no admin rights, no Python or FFmpeg to install
- Three colour families in light or dark, and a settings panel for models, processing device, YouTube sign-in and storage
- Tells you when a new release is out (one request to GitHub a day, can be turned off in **Settings → Updates**). Nothing is ever downloaded or installed on its own
- Glassmorphism UI built on [Vitra CSS](https://vitracss.com)

---

## Playlists

Paste a playlist link, or a channel link (`youtube.com/@name`), and Y2obi lists
every video in it in a couple of seconds. Tick the ones you want: there is a
filter, a select-all that acts on what the filter shows, and shift-click for
ranges. Then pick a format as usual. MP4, WebM, MP3 and TXT all work.

- Videos are processed one after another into
  `Downloads\Y2obi\<playlist>\`, numbered in playlist order
  (`003 - Lecture title.mp4`)
- A video that fails is marked with the reason and the rest carry on
- Running the same playlist again skips what is already there, so the same
  button retries the failures and resumes after a cancel
- A video link that carries `&list=...` stays that one video, with a button
  beside it to load the whole playlist. YouTube mixes are not offered, since
  they have no fixed end

---

## Transcription

Pick **TXT** as the format and Y2obi transcribes the video with
[whisper.cpp](https://github.com/ggerganov/whisper.cpp), writing a `.txt` next
to your other downloads, plus a timestamped `.srt` subtitle file if you want
one. Works on any length: long audio is split into chunks internally so the
transcript doesn't degrade.

The `.txt` can carry timestamps every 30 s, 1, 2, 5 or 10 minutes, either as a
point (`[00:01:00]`) or as a range (`[00:01:00 - 00:02:00]`), with the speech
grouped into one paragraph per interval.

Two accuracy levels are offered up front:

| Model | Size | Speed (CPU) |
|-------|------|-------------|
| Balanced | ~488 MB | roughly 1/5 of the video's length |
| Best (default) | ~1.6 GB | roughly 1/4 of the video's length |

Four more (Tiny, Base, Medium, Large v3) are a click away under
**Settings → Speech models**, where you can download one ahead of time, see what each is costing
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

- **Transcribe** it to `.txt` (and `.srt` if you want it), same as a YouTube video
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

## Signing in to YouTube

Most videos need nothing. Some do: age-restricted or private ones, and any
video at all when YouTube decides to throttle requests that are not signed in
("Sign in to confirm you're not a bot"). When that happens the app says so in
plain words and puts the fix in the message itself, then retries on its own.
You only do this once: Y2obi remembers how you connected and reconnects by
itself when the session expires.

**Sign in to YouTube** (in the error message, or **Settings → YouTube
sign-in**) opens a window of Y2obi's own. Sign in normally, close it, and the
download continues. This is the way that works for everyone.

Why not just read your browser? **Edge, Chrome and Brave cannot be read at
all**, and closing them does not help: since Chromium 127 they encrypt their
cookie store with App-Bound Encryption, which ties the key to the browser's own
executable so that no other program can decrypt it. Firefox is still readable
directly, and a `cookies.txt` exported with a browser extension such as
[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
can be loaded from Settings too.

The session is stored in `%APPDATA%\Y2obi\cookies.txt`, stays on your machine
and is only ever sent to YouTube, exactly as your browser would send it.
**Settings → YouTube sign-in → Disconnect** removes it.

---

## Troubleshooting

The app is built as a windowed program, so it normally prints nothing. If
something misbehaves, run it from a terminal:

```powershell
Y2obi.exe --debug
```

That writes everything to `%TEMP%\y2obi-debug.log` (startup, the local port,
every request, any error) and enables right-click → Inspect inside the window.

Without any flag, Y2obi still keeps a short log in
`%LOCALAPPDATA%\Y2obi\logs\`. **Settings → Storage → Diagnostic log → Copy**
puts the version, the bundled binaries and the last lines of that log on your
clipboard, ready to paste into a bug report. The session token is scrubbed out.

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

`build.spec` bundles `core/ffmpeg.exe`, `core/deno/deno.exe` and
`core/whisper/` straight into the executable, so the built app needs no runtime
download for any of them. If `core/ffmpeg.exe` isn't there yet, run
`python main.py` once from source and it will be fetched automatically.

`core/deno/deno.exe` runs yt-dlp's YouTube challenge solver, without which
signed-in downloads get nothing usable. Take the full `deno` binary (not
`denort`) from the [deno release](https://github.com/denoland/deno/releases)
pinned in `build.spec`; the build refuses any other hash.

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

Before a release, drive the built exe end to end. It launches `dist/Y2obi.exe`
in a throwaway profile and checks the API, the bundled binaries, a real
conversion and the log:

```
python tools/qa_exe.py
```

Releases are built automatically by [GitHub Actions](.github/workflows/release.yml)
on every `v*` tag push, from the same pinned binaries.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Download engine | yt-dlp |
| Muxing / conversion | FFmpeg (bundled) |
| Transcription | whisper.cpp (bundled) + Vulkan GPU backend |
| YouTube challenge solver | deno (bundled) + yt-dlp-ejs |
| Backend | Flask 3 (local, embedded) |
| Frontend | Vitra CSS + pywebview |
| Build | PyInstaller |

---

## Project Structure

```
Y2obi/
├── app/
│   ├── downloader.py     # yt-dlp wrapper: video, audio, playlists, cookies, progress
│   ├── converter.py      # ffmpeg wrapper for local files: probe, mp3/mp4, cancel
│   ├── transcriber.py    # whisper.cpp wrapper: models, chunking, txt/srt output
│   ├── server.py         # Flask app, the API the window talks to
│   ├── binaries.py       # finds ffmpeg, whisper and deno (bundled first, then PATH)
│   ├── cleanup.py        # clears leftovers from interrupted runs
│   ├── diagnostics.py    # the always-on log, token scrubbing
│   ├── updates.py        # the once-a-day "new release" check
│   └── version.py        # the one place the version lives
├── desktop/
│   ├── index.html        # the whole UI
│   └── static/           # Vitra CSS/JS, icons
├── core/whisper/MANIFEST.json  # pinned hashes of the bundled speech engine
├── tools/
│   ├── devserver.py      # UI on :8799 with sandboxed data, for screenshots
│   ├── qa_exe.py         # drives the built exe end to end, the release gate
│   ├── measure_startup.py# startup timing and freeze sampling of an exe
│   ├── verify_whisper.py # checks the CPU and GPU backends still agree
│   └── vtscan.py         # what VirusTotal's engines say about a build
├── tests/                # unittest suite: python -m unittest discover tests
├── main.py               # entry point: WebView2 check, ffmpeg, launch
├── run.bat               # one-click setup and launch when running from source
├── build.spec            # PyInstaller config
├── version_info.txt      # exe file/product metadata
└── requirements.txt      # dependencies
```

---

## License

[MIT](LICENSE). Do whatever you want, just don't abuse it.
