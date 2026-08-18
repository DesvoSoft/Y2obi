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
# "best" alone means "best format with video AND audio muxed", which YouTube
# barely serves any more, so it is a fallback that almost never fires. best*
# accepts a format with either, and the acodec filter keeps us from happily
# downloading a silent video stream to transcribe.
AUDIO_FORMAT = "bestaudio/best*[acodec!=none]/best"

# Player clients tried in order, for both analyze and download. They must stay
# the same ladder: pinning downloads to the first pair alone made any video that
# only resolved via tv_embedded/web analyze fine and then fail at download.
PLAYER_CLIENTS = (['android_vr', 'mweb'], ['tv_embedded'], ['web'])


class DownloadError(Exception):
    pass


class AuthRequired(DownloadError):
    """YouTube wants a signed-in session. Loading cookies is the whole fix.

    Kept separate from DownloadError so the UI can offer the one action that
    actually helps instead of showing a wall of yt-dlp text that ends in
    "use --cookies-from-browser", which means nothing to someone who just wants
    a video.
    """


class StreamsUnavailable(DownloadError):
    """YouTube answered, but with nothing usable in it.

    In practice this is the same problem as AuthRequired wearing a different
    hat: when YouTube throttles anonymous requests it returns a stripped format
    list, and yt-dlp then reports "Requested format is not available", which
    sounds like a bug in the app and is not. A browser session fixes it.
    """


class PlaylistError(DownloadError):
    pass


_CHROMIUM_COOKIE_DB = {
    "edge":   os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Network\Cookies"),
    "brave":  os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Network\Cookies"),
    "chrome": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies"),
}


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


# Phrases yt-dlp surfaces when the only fix is a signed-in session. Matched
# loosely because the wording drifts between yt-dlp releases.
_AUTH_MARKERS = (
    "not a bot",
    "sign in to confirm",
    "confirm your age",
    "cookies-from-browser",
    "--cookies",
    "login required",
    "requires authentication",
    "video is private",
    "private video",
    "members-only",
    "age-restricted",
)


def looks_like_auth_error(text):
    low = str(text).lower()
    return any(m in low for m in _AUTH_MARKERS)


# yt-dlp's wording when the format list came back with nothing we can use.
_EMPTY_MARKERS = (
    "requested format is not available",
    "no video formats found",
    "unable to extract player response",
)


def looks_like_no_streams(text):
    low = str(text).lower()
    return any(m in low for m in _EMPTY_MARKERS)


# Where each browser keeps its profile, used to offer only browsers that are
# actually installed rather than a list of four that mostly fail.
_BROWSER_PROFILES = {
    "firefox": ("APPDATA", os.path.join("Mozilla", "Firefox", "Profiles")),
    "edge": ("LOCALAPPDATA", os.path.join("Microsoft", "Edge", "User Data")),
    "chrome": ("LOCALAPPDATA", os.path.join("Google", "Chrome", "User Data")),
    "brave": ("LOCALAPPDATA", os.path.join("BraveSoftware", "Brave-Browser", "User Data")),
}

BROWSER_LABELS = {"firefox": "Firefox", "edge": "Edge", "chrome": "Chrome",
                  "brave": "Brave"}


def installed_browsers():
    """Browsers present on this machine, with whether they are running.

    Firefox first: it is the only one whose cookie store yt-dlp can read while
    the browser is open. The Chromium ones hold a lock on theirs.
    """
    found = []
    for name in ("firefox", "edge", "chrome", "brave"):
        env, rel = _BROWSER_PROFILES[name]
        root = os.environ.get(env)
        if not root or not os.path.isdir(os.path.join(root, rel)):
            continue
        found.append({
            "name": name,
            "label": BROWSER_LABELS[name],
            "running": _is_browser_running(name),
            "needs_close": name in _CHROMIUM_COOKIE_DB,
        })
    return found


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
    if not quality_labels:
        quality_labels = ["Best"]
    return quality_labels, has_audio_only


class Downloader:
    def __init__(self, ffmpeg_path="ffmpeg", cookies=None):
        self.ffmpeg_path = ffmpeg_path
        self.cookies = cookies
        self._progress_cb = None
        self._status_cb = None
        self._cancel = False

    def set_callbacks(self, progress=None, status=None):
        self._progress_cb = progress
        self._status_cb = status

    def cancel(self):
        self._cancel = True

    def _apply_cookies_file_only(self, opts):
        """Apply only an explicit cookies.txt — never auto-browser (may fail on Windows DPAPI)."""
        if self.cookies and os.path.exists(self.cookies):
            opts["cookiefile"] = self.cookies

    def get_info(self, url):
        opts = {
            'quiet': True,
            'no_warnings': True,
            # Bounded on purpose. Analyze is synchronous and the window shows
            # "Analyzing..." the whole time, so a long retry storm behind a bot
            # check is indistinguishable from a frozen app. Three player clients
            # at 15 s and one retry each fails in under two minutes worst case,
            # and then the UI can offer the fix.
            'socket_timeout': 15,
            'retries': 1,
            'extractor_retries': 1,
            'extract_flat': False,
            'noplaylist': True,
        }
        self._apply_cookies_file_only(opts)
        info = None
        last_err = None
        for clients in PLAYER_CLIENTS:
            opts['extractor_args'] = {'youtube': {'player_client': clients}}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                break
            except yt_dlp.utils.DownloadError as e:
                last_err = e
                continue
            except Exception as e:
                raise DownloadError(f"Unexpected error: {e}\n\n{traceback.format_exc()}") from e
        if info is None:
            # Every player client failed. If the reason is a signed-in session,
            # say so in one line instead of forwarding yt-dlp's wall of text:
            # the user cannot act on "use --cookies-from-browser", but they can
            # act on a button that loads their browser's cookies.
            if looks_like_auth_error(last_err):
                raise AuthRequired(
                    "YouTube wants to confirm you are signed in before it hands "
                    "this video over."
                ) from last_err
            if looks_like_no_streams(last_err):
                raise StreamsUnavailable(
                    "YouTube did not offer a usable stream for this video. That "
                    "usually means it is throttling requests that are not signed in."
                ) from last_err
            raise DownloadError(f"YouTube error: {last_err}") from last_err

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
        opts = {
            'outtmpl': template,
            'ffmpeg_location': self._ffmpeg_dir(),
            'quiet': True,
            'no_warnings': True,
            'nooverwrites': True,
            'socket_timeout': 30,
            'noplaylist': True,
            'progress_hooks': [self._hook],
            'postprocessor_hooks': [self._pp_hook],
        }
        self._apply_cookies_file_only(opts)
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

    def _run_download(self, url, template, fmt_opts, what="download"):
        """Download `url` into `template`, walking PLAYER_CLIENTS on failure.

        Every format goes through here: the four callers only differ in the
        format selector and the postprocessors they add.
        """
        self._cancel = False
        last_err = None
        for clients in PLAYER_CLIENTS:
            opts = self._base_opts(template)
            opts.update(fmt_opts)
            opts['extractor_args'] = {'youtube': {'player_client': list(clients)}}
            ydl = yt_dlp.YoutubeDL(opts)
            try:
                info = ydl.extract_info(url, download=True)
            except yt_dlp.utils.DownloadError as e:
                if "Cancelled" in str(e):
                    raise
                last_err = e
                continue
            except Exception as e:
                raise DownloadError(f"Unexpected error: {e}\n\n{traceback.format_exc()}") from e
            finally:
                ydl.close()

            path = self._resolve_path(info, ydl, template)
            if path and os.path.exists(path):
                return path
            # Extraction worked, so another client will not help.
            raise DownloadError(f"No file — {what} did not produce output")

        if looks_like_auth_error(last_err):
            raise AuthRequired(
                "YouTube wants to confirm you are signed in before it hands "
                "this video over."
            ) from last_err
        if looks_like_no_streams(last_err):
            raise StreamsUnavailable(
                "YouTube did not offer a usable stream for this video. That "
                "usually means it is throttling requests that are not signed in."
            ) from last_err
        raise DownloadError(f"YouTube download error: {last_err}") from last_err

    def download_mp4(self, url, output_dir, quality="Best"):
        qlabel = f" [{quality}]" if quality != "Best" else ""
        template = os.path.join(output_dir, f"%(title)s{qlabel}.%(ext)s")
        max_h, _ = QUALITY_MAP.get(quality, (None, None))
        fmt_sort = [f"height:{max_h}", "ext", "vcodec", "acodec"] if max_h else ["res", "ext", "vcodec", "acodec"]
        return self._run_download(url, template, {
            'format': f"bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]" if max_h else "bestvideo+bestaudio/best",
            'format_sort': fmt_sort,
            'merge_output_format': 'mp4',
        })

    def download_webm(self, url, output_dir, quality="Best"):
        qlabel = f" [{quality}]" if quality != "Best" else ""
        template = os.path.join(output_dir, f"%(title)s{qlabel}.%(ext)s")
        return self._run_download(url, template, {
            'format': QUALITY_MAP_WEBM.get(quality, QUALITY_MAP_WEBM["Best"]),
            'merge_output_format': 'webm',
        })

    def download_mp3(self, url, output_dir):
        template = os.path.join(output_dir, "%(title)s.%(ext)s")
        return self._run_download(url, template, {
            'format': AUDIO_FORMAT,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
        })

    def download_audio_raw(self, url, output_dir):
        """bestaudio with no re-encode — input for transcription.

        Deliberately not download_mp3(): transcription decodes to 16 kHz mono
        WAV anyway, so encoding to 320 kbps mp3 in between is minutes of
        wasted ffmpeg time on a long video and loses quality twice.
        """
        template = os.path.join(output_dir, "%(title)s.%(ext)s")
        return self._run_download(url, template, {'format': AUDIO_FORMAT},
                                  what="audio download")

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
        # Postprocessing fires no download hooks, so without this a Cancel
        # pressed during "Converting..." was ignored and the file completed
        # anyway. yt-dlp emits 'started' before each postprocessor runs, so this
        # stops the next one — an ffmpeg run already in flight still finishes.
        if self._cancel:
            raise yt_dlp.utils.DownloadError("Cancelled")
        if d['status'] == 'started':
            if self._status_cb:
                self._status_cb(f"Converting...")
        elif d['status'] == 'finished':
            if self._status_cb:
                self._status_cb("Finalizing...")
