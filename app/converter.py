"""Local-file handling: probe a file the user picked, and convert it with ffmpeg.

This is the non-YouTube half of the app. `Downloader` wraps yt-dlp and only
knows about URLs; everything here operates on a path the user chose in a native
file dialog (see `Api.pick_file` in main.py), so no bytes are ever copied
through the HTTP layer.

Y2obi bundles ffmpeg.exe only — no ffprobe — so `probe()` reads what it needs
out of ffmpeg's own stderr banner instead.
"""
import os
import re
import subprocess
import tempfile

# Containers ffmpeg in this build reads happily. Used to filter the file dialog
# and to reject junk early with a clear message instead of an ffmpeg dump.
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".ts")
AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".aiff")
MEDIA_EXTS = VIDEO_EXTS + AUDIO_EXTS

# Heights offered when re-encoding a local video. None means "leave it alone".
MP4_HEIGHTS = (None, 1080, 720, 480, 360)

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video: (\w+).*?, (\d+)x(\d+)", re.S)
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (\w+)")
_OUT_TIME_RE = re.compile(r"out_time_us=(\d+)")
# ffmpeg's own realtime factor, e.g. "speed=12.3x". For a conversion this is the
# number that means something to a user — output bytes per second does not.
_SPEED_RE = re.compile(r"speed=\s*([\d.]+)x")


class ConvertError(Exception):
    pass


class Cancelled(ConvertError):
    """Message must contain 'Cancelled' — server.py keys task state off that."""
    def __init__(self):
        super().__init__("Cancelled")


def _no_window():
    """Keep ffmpeg from flashing a console window in the windowed app."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_media(path):
    return os.path.splitext(path)[1].lower() in MEDIA_EXTS


def fmt_duration(seconds):
    """'1h 02m 03s' / '2m 03s' — same shape the analyze route returns."""
    if not seconds:
        return ""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return (f"{h}h " if h else "") + f"{m}m {s:02d}s"


def unique_path(path):
    """`name.mp3` -> `name (2).mp3` when the target already exists.

    Converting a local file can easily land on the name of the file next to it
    (an .mp4 in the output folder converted to .mp4), and silently overwriting
    the user's own input would be unforgivable.
    """
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


class Converter:
    """Probe and convert one local file. One instance per task.

    Holds its own cancel Event and subprocess handle, like `Transcriber` — a
    shared instance would let one task's Cancel kill another task's ffmpeg.
    """

    def __init__(self, ffmpeg_path, cancel_event=None):
        self.ffmpeg = ffmpeg_path
        self.cancel_event = cancel_event
        self._proc = None

    # --- cancellation -----------------------------------------------------

    def _cancelled(self):
        return bool(self.cancel_event and self.cancel_event.is_set())

    def _check_cancel(self):
        if self._cancelled():
            raise Cancelled()

    def cancel(self):
        if self.cancel_event:
            self.cancel_event.set()
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    # --- probing ----------------------------------------------------------

    def probe(self, path):
        """Duration, streams and resolution, parsed from ffmpeg's banner.

        `ffmpeg -i file` with no output writes the stream summary to stderr and
        exits non-zero ("At least one output file must be specified") — that
        exit code is expected here and is not an error.
        """
        if not os.path.isfile(path):
            raise ConvertError("File not found")

        p = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=_no_window(),
        )
        err = (p.stderr or b"").decode("utf-8", "replace")

        if "Invalid data found" in err or "No such file" in err:
            raise ConvertError("Unsupported or unreadable file")

        dur = 0.0
        m = _DURATION_RE.search(err)
        if m:
            dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

        v = _VIDEO_RE.search(err)
        a = _AUDIO_RE.search(err)
        # A cover-art JPEG inside an mp3 shows up as a video stream; treat a file
        # whose "video" is a still image as audio-only so the UI offers the right
        # formats.
        is_cover = bool(v) and v.group(1).lower() in ("mjpeg", "png", "bmp", "gif")

        if not a and (not v or is_cover):
            raise ConvertError("No audio or video stream in that file")

        return {
            "name": os.path.basename(path),
            "duration": dur,
            "duration_str": fmt_duration(dur),
            "has_video": bool(v) and not is_cover,
            "has_audio": bool(a),
            "vcodec": v.group(1) if v and not is_cover else None,
            "acodec": a.group(1) if a else None,
            "width": int(v.group(2)) if v and not is_cover else 0,
            "height": int(v.group(3)) if v and not is_cover else 0,
            "size": os.path.getsize(path),
        }

    # --- conversion -------------------------------------------------------

    def _run(self, args, total_sec, progress_cb, what, dst, rate_cb=None):
        """Run ffmpeg, reporting percent from -progress on stdout.

        Popen, not run: a two-hour re-encode has to stay cancellable, and a
        blocking call would leave self._proc unset so Cancel could not reach it.

        `dst` is removed if the run does not finish — otherwise Cancel leaves a
        truncated, unplayable file sitting in the user's Downloads folder.
        """
        self._check_cancel()
        cmd = [self.ffmpeg, "-hide_banner", "-nostats", "-y",
               "-progress", "pipe:1"] + args
        # stderr to a temp file, not a pipe: this loop only drains stdout, so a
        # chatty encode could fill the stderr pipe buffer and deadlock ffmpeg
        # against us. A file never blocks the writer.
        code = -1
        with tempfile.TemporaryFile() as errf:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=errf,
                creationflags=_no_window(),
            )
            try:
                for raw in self._proc.stdout:
                    if self._cancelled():
                        break
                    line = raw.decode("utf-8", "replace")
                    m = _OUT_TIME_RE.search(line)
                    if m and total_sec > 0 and progress_cb:
                        done = int(m.group(1)) / 1e6
                        progress_cb(max(0.0, min(100.0, done / total_sec * 100.0)))
                    sm = _SPEED_RE.search(line)
                    if sm and rate_cb:
                        rate_cb(float(sm.group(1)))
                code = self._proc.wait()
            finally:
                proc, self._proc = self._proc, None
                if proc:
                    if proc.poll() is None:
                        try:
                            proc.terminate()
                        except OSError:
                            pass
                    if proc.stdout:
                        proc.stdout.close()
            errf.seek(0)
            err = errf.read()

        if self._cancelled() or code != 0:
            try:
                if dst and os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass

        self._check_cancel()
        if code != 0:
            tail = (err or b"").decode("utf-8", "replace").strip().split("\n")[-1:]
            raise ConvertError(f"{what} failed: {' '.join(tail) or 'ffmpeg error ' + str(code)}")

    def to_mp3(self, src, out_dir, progress_cb=None, info=None, rate_cb=None):
        """Extract/convert the audio track to a 192 kbps mp3."""
        info = info or self.probe(src)
        if not info["has_audio"]:
            raise ConvertError("That file has no audio track")
        stem = os.path.splitext(os.path.basename(src))[0]
        dst = unique_path(os.path.join(out_dir, stem + ".mp3"))
        self._run(["-i", src, "-vn", "-c:a", "libmp3lame", "-b:a", "192k", dst],
                  info["duration"], progress_cb, "Audio conversion", dst, rate_cb)
        return dst

    def to_mp4(self, src, out_dir, height=None, progress_cb=None, info=None,
               rate_cb=None):
        """Convert to mp4, remuxing instead of re-encoding when that is enough.

        An h264+aac source that needs no resize only has to change container,
        which `-c copy` does in seconds instead of minutes.
        """
        info = info or self.probe(src)
        if not info["has_video"]:
            raise ConvertError("That file has no video track — convert it to MP3 instead")

        stem = os.path.splitext(os.path.basename(src))[0]
        dst = unique_path(os.path.join(out_dir, stem + ".mp4"))

        needs_resize = bool(height) and info["height"] > height
        can_copy = (not needs_resize
                    and info["vcodec"] in ("h264", "hevc")
                    and (info["acodec"] in ("aac", None)))

        if can_copy:
            args = ["-i", src, "-c", "copy", "-movflags", "+faststart", dst]
        else:
            args = ["-i", src]
            if needs_resize:
                # -2 keeps the width even, which H.264 requires.
                args += ["-vf", f"scale=-2:{height}"]
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                     "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst]

        self._run(args, info["duration"], progress_cb, "Video conversion", dst, rate_cb)
        return dst
