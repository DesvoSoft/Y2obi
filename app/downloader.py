import yt_dlp
import os
import traceback

try:
    import bgutil_ytdlp_pot_provider  # registers itself as yt-dlp POT provider
except ImportError:
    pass

QUALITY_MAP = {
    "Best":  (None, None),
    "2160p": (2160, None),
    "1440p": (1440, None),
    "1080p": (1080, None),
    "720p":  (720,  None),
    "480p":  (480,  None),
    "360p":  (360,  None),
}

QUALITY_MAP_WEBM = {
    "Best":  "bestvideo[ext=webm]+bestaudio[ext=webm]/bestvideo[ext=webm]+bestaudio/bestvideo+bestaudio/best",
    "2160p": "bestvideo[height<=2160][ext=webm]+bestaudio[ext=webm]/bestvideo[height<=2160]+bestaudio/best",
    "1440p": "bestvideo[height<=1440][ext=webm]+bestaudio[ext=webm]/bestvideo[height<=1440]+bestaudio/best",
    "1080p": "bestvideo[height<=1080][ext=webm]+bestaudio[ext=webm]/bestvideo[height<=1080]+bestaudio/best",
    "720p":  "bestvideo[height<=720][ext=webm]+bestaudio[ext=webm]/bestvideo[height<=720]+bestaudio/best",
    "480p":  "bestvideo[height<=480][ext=webm]+bestaudio[ext=webm]/bestvideo[height<=480]+bestaudio/best",
    "360p":  "bestvideo[height<=360][ext=webm]+bestaudio[ext=webm]/bestvideo[height<=360]+bestaudio/best",
}

# Audio format: m4a DASH preferred, fallback to any audio, last resort muxed 360p (format 18 = no DASH/no PO token)
AUDIO_FORMAT = "bestaudio/best"


class DownloadError(Exception):
    pass


class PlaylistError(DownloadError):
    pass


def _find_firefox_cookies():
    roots = [
        os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles"),
        os.path.expandvars(r"%LOCALAPPDATA%\Packages\Mozilla.Firefox_n80bbvh6b1yt2\LocalCache\Roaming\Mozilla\Firefox\Profiles"),
    ]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for profile in os.listdir(root):
            db = os.path.join(root, profile, "cookies.sqlite")
            if os.path.isfile(db):
                return True
    return False


# Chromium browsers lock their DB while running — cannot use cookiesfrombrowser auto
# Only Firefox is safe for automatic cookie extraction
_CHROMIUM_BROWSERS = {"edge", "brave", "chrome", "chromium", "opera", "vivaldi"}

_CHROMIUM_COOKIE_DB = {
    "edge":   os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Network\Cookies"),
    "brave":  os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Network\Cookies"),
    "chrome": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies"),
}


_FF_ONLY_AUTO = True  # Only Firefox supports auto-extraction without DPAPI issues


def _detect_browser():
    """File-existence check — no network calls, no browser launch.
    Only returns Firefox: Chromium browsers lock their DB and fail DPAPI on Windows."""
    if _find_firefox_cookies():
        return "firefox"
    return None


def _is_browser_running(browser):
    if os.name != "nt":
        return False  # Linux/Render: no desktop browsers
    import subprocess
    proc_names = {"edge": "msedge.exe", "brave": "brave.exe", "chrome": "chrome.exe", "chromium": "chromium.exe"}
    name = proc_names.get(browser)
    if not name:
        return False
    try:
        result = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                                capture_output=True, text=True, timeout=5)
        return name.lower() in result.stdout.lower()
    except FileNotFoundError:
        return False


def export_cookies_from_browser(browser, dest_path):
    """Export cookies to Netscape cookies.txt. Chromium browsers must be closed."""
    import http.cookiejar
    if browser in _CHROMIUM_COOKIE_DB and _is_browser_running(browser):
        raise DownloadError(
            f"{browser.capitalize()} is running. Close it completely, then try again."
        )
    try:
        cj = yt_dlp.cookies.extract_cookies_from_browser(browser)
        moz = http.cookiejar.MozillaCookieJar(dest_path)
        for cookie in cj:
            moz.set_cookie(cookie)
        moz.save(ignore_discard=True, ignore_expires=True)
        return True
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Cookie export failed: {e}") from e


def _parse_formats(info):
    """Return available video qualities and whether audio-only is available."""
    fmts = info.get("formats") or []
    heights = set()
    has_audio_only = False
    for f in fmts:
        h = f.get("height")
        if h and f.get("vcodec") not in (None, "none"):
            heights.add(h)
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none"):
            has_audio_only = True
    # Map heights to quality labels
    label_map = {2160: "2160p", 1440: "1440p", 1080: "1080p", 720: "720p", 480: "480p", 360: "360p", 240: "240p", 144: "144p"}
    quality_labels = []
    for h in sorted(heights, reverse=True):
        lbl = label_map.get(h, f"{h}p")
        if lbl not in quality_labels:
            quality_labels.append(lbl)
    return quality_labels, has_audio_only


class Downloader:
    def __init__(self, ffmpeg_path="ffmpeg", cookies=None):
        self.ffmpeg_path = ffmpeg_path
        self.cookies = cookies
        self._browser = None
        self._progress_cb = None
        self._status_cb = None
        self._cancel = False

    def set_callbacks(self, progress=None, status=None, complete=None):
        self._progress_cb = progress
        self._status_cb = status

    def _apply_cookies(self, opts):
        if self.cookies:
            opts["cookiefile"] = self.cookies
        else:
            if self._browser is None:
                detected = _detect_browser()
                self._browser = detected if detected else False
            if self._browser:
                opts["cookiesfrombrowser"] = (self._browser,)

    def cancel(self):
        self._cancel = True

    def _apply_cookies_file_only(self, opts):
        """Apply only an explicit cookies.txt — never auto-browser (may fail on Windows DPAPI)."""
        if self.cookies and os.path.exists(self.cookies):
            opts["cookiefile"] = self.cookies

    def get_info(self, url):
        has_cookies = bool(self.cookies and os.path.exists(self.cookies))
        opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'extract_flat': False,
            'playlist_items': '1',
            'extractor_args': {'youtube': {'player_client': ['android_vr', 'mweb']}},
        }
        self._apply_cookies_file_only(opts)
        print(f"[Y2obi] get_info cookies_exist={has_cookies}", flush=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(f"YouTube error: {e}") from e
        except Exception as e:
            raise DownloadError(f"Unexpected error: {e}\n\n{traceback.format_exc()}") from e

        if info and info.get('_type') == 'playlist':
            title = info.get('title', 'Untitled')
            count = len(info.get('entries', []))
            raise PlaylistError(
                f"Playlist detected: \"{title}\" ({count} videos)\n\n"
                "Y2obi does not support playlists.\n"
                "Paste a single video URL instead."
            )

        if info and 'entries' in info:
            entries = info['entries']
            if entries:
                info = entries[0]
                if info is None:
                    raise DownloadError("Could not extract video from playlist entry.")
                return info
            raise PlaylistError("Empty playlist.")

        return info

    def _ffmpeg_dir(self):
        loc = self.ffmpeg_path
        if loc and os.path.isfile(loc):
            return os.path.dirname(loc)
        return loc

    def _base_opts(self, template):
        has_cookies = bool(self.cookies and os.path.exists(self.cookies))
        clients = ['android_vr', 'mweb']
        opts = {
            'outtmpl': template,
            'ffmpeg_location': self._ffmpeg_dir(),
            'quiet': True,
            'no_warnings': True,
            'nooverwrites': True,
            'socket_timeout': 30,
            'progress_hooks': [self._hook],
            'postprocessor_hooks': [self._pp_hook],
            'extractor_args': {'youtube': {'player_client': clients}},
        }
        self._apply_cookies_file_only(opts)
        print(f"[Y2obi] download cookies={self.cookies} exists={has_cookies}", flush=True)
        return opts

    def _resolve_path(self, info, ydl, template):
        if not info:
            return None
        rds = info.get('requested_downloads')
        if rds:
            p = rds[0].get('filepath')
            if p and os.path.exists(p):
                return p
        p = info.get('filepath')
        if p and os.path.exists(p):
            return p
        try:
            p = ydl.prepare_filename(info)
            if p and os.path.exists(p):
                return p
            base = os.path.splitext(p)[0]
            for ext in ('mp4', 'mkv', 'webm', 'mp3', 'm4a', 'opus'):
                candidate = f"{base}.{ext}"
                if os.path.exists(candidate):
                    return candidate
        except Exception:
            pass
        return None

    def download_mp4(self, url, output_dir, quality="Best"):
        qlabel = f" [{quality}]" if quality != "Best" else ""
        template = os.path.join(output_dir, f"%(title)s{qlabel}.%(ext)s")
        max_h, _ = QUALITY_MAP.get(quality, (None, None))
        opts = self._base_opts(template)
        fmt_sort = [f"height:{max_h}", "ext", "vcodec", "acodec"] if max_h else ["res", "ext", "vcodec", "acodec"]
        opts.update({
            'format': f"bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]" if max_h else "bestvideo+bestaudio/best",
            'format_sort': fmt_sort,
            'merge_output_format': 'mp4',
        })
        self._cancel = False
        ydl = yt_dlp.YoutubeDL(opts)
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            if "Cancelled" in str(e):
                raise
            raise DownloadError(f"YouTube download error: {e}") from e
        except Exception as e:
            raise DownloadError(f"Unexpected error: {e}\n\n{traceback.format_exc()}") from e
        finally:
            ydl.close()

        path = self._resolve_path(info, ydl, template)
        if path and os.path.exists(path):
            return path
        raise DownloadError("No file — download did not produce output")

    def download_webm(self, url, output_dir, quality="Best"):
        qlabel = f" [{quality}]" if quality != "Best" else ""
        template = os.path.join(output_dir, f"%(title)s{qlabel}.%(ext)s")
        fmt = QUALITY_MAP_WEBM.get(quality, QUALITY_MAP_WEBM["Best"])
        opts = self._base_opts(template)
        opts.update({
            'format': fmt,
            'merge_output_format': 'webm',
        })
        self._cancel = False
        ydl = yt_dlp.YoutubeDL(opts)
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            if "Cancelled" in str(e):
                raise
            raise DownloadError(f"YouTube download error: {e}") from e
        except Exception as e:
            raise DownloadError(f"Unexpected error: {e}\n\n{traceback.format_exc()}") from e
        finally:
            ydl.close()
        path = self._resolve_path(info, ydl, template)
        if path and os.path.exists(path):
            return path
        raise DownloadError("No file — download did not produce output")

    def download_mp3(self, url, output_dir):
        template = os.path.join(output_dir, "%(title)s.%(ext)s")
        opts = self._base_opts(template)
        opts.update({
            'format': AUDIO_FORMAT,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
        })
        self._cancel = False
        ydl = yt_dlp.YoutubeDL(opts)
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            if "Cancelled" in str(e):
                raise
            raise DownloadError(f"YouTube download error: {e}") from e
        except Exception as e:
            raise DownloadError(f"Unexpected error: {e}\n\n{traceback.format_exc()}") from e
        finally:
            ydl.close()

        path = self._resolve_path(info, ydl, template)
        if path and os.path.exists(path):
            return path
        raise DownloadError("No file — download did not produce output")

    def _hook(self, d):
        if self._cancel:
            raise yt_dlp.utils.DownloadError("Cancelled")
        if d['status'] == 'already_downloaded':
            if self._status_cb:
                self._status_cb("__already_exists__")
            return
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            if total:
                pct = min(downloaded / total * 100, 100)
                if self._progress_cb:
                    self._progress_cb(pct, d.get('speed', 0), d.get('eta', 0))
        elif d['status'] == 'finished':
            if self._status_cb:
                self._status_cb("Processing...")

    def _pp_hook(self, d):
        if d['status'] == 'started':
            if self._status_cb:
                self._status_cb(f"Converting...")
        elif d['status'] == 'finished':
            if self._status_cb:
                self._status_cb("Finalizing...")
