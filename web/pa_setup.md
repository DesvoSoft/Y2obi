# PythonAnywhere Deployment

## Requirements
- PythonAnywhere account (free tier works)
- "haggis" image (has FFmpeg pre-installed globally)
- Git

## Steps

### 1. Clone repo
```bash
git clone <your-repo-url> Y2obi
cd Y2obi
```

### 2. Create venv & install deps
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Set up Web app
- **Dashboard** > **Web** > **Add a new web app**
- Manual configuration (not a template)
- Python version: 3.12 or 3.14 (match your venv)

### 4. WSGI configuration
- **Code** > **WSGI configuration file**: browse to `Y2obi/web/wsgi.py`
- Or copy contents of `web/wsgi.py` into the PA WSGI file

### 5. Working directory
- **Code** > **Working directory**: `/home/<username>/Y2obi`

### 6. Static files
- **Static files**:
  - URL: `/static/vitra/` → Directory: `/home/<username>/Y2obi/web/static/vitra/`
- (Everything else is served by Flask at `/static/`)

### 7. Virtualenv
- **Virtualenv**: `/home/<username>/Y2obi/venv`

### 8. Reload
- Click **Reload** green button

## Cookies
- Auto-detect won't work on PA (no local browsers)
- Use the cookie badge in the footer to upload `cookies.txt` manually
- Export from browser via extensions like "Get cookies.txt" (for Chrome) or "cookies.txt" (for Firefox)

## Known PA quirks
- No `yt-dlp` CLI on PATH (uses Python package)
- FFmpeg is at `/usr/bin/ffmpeg` on haggis image
- Download speeds limited (~200 Mbps) on free tier
- Files saved to `~/Videos/Y2obi/` on PA filesystem (not served by web app)
- Web app downloads to temp dir, served via Flask, then deleted

## Troubleshooting
- Check **Error log** on PA Web tab for tracebacks
- Run `python3 web/app.py` in Bash console to test locally on PA
- If FFmpeg not found: `which ffmpeg` → update path in app code
