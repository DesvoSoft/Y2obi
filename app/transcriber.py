"""Local speech-to-text via whisper.cpp.

Runs fully offline once a model is cached in %APPDATA%/Y2obi/models/.
Long audio is split into chunks — whisper falls into a repeat-the-same-line
hallucination loop on long continuous input, and restarting the decoder per
chunk avoids it. Chunks are sliced out of the 16 kHz mono WAV so each
whisper-cli process reads only its own slice and emits slice-relative
timestamps that we shift back ourselves.
"""
import math
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave

# name -> (filename, url, approx size in MB)
MODELS = {
    "tiny":           ("ggml-tiny.bin",           "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",           75),
    "base":           ("ggml-base.bin",           "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",          148),
    "small":          ("ggml-small.bin",          "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",         488),
    "medium":         ("ggml-medium.bin",         "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",       1500),
    "large-v3-turbo": ("ggml-large-v3-turbo.bin", "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin", 1620),
    "large-v3":       ("ggml-large-v3.bin",       "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin",     3100),
}

# Models offered up front as accuracy chips. The rest are one click away in the
# models panel but are not pushed at anyone: tiny/base lose to YouTube's own
# auto-captions, and large-v3 is ~8x slower than turbo for a marginal gain on
# CPU. A model the user has actually downloaded is always offered too.
UI_MODELS = ("small", "large-v3-turbo")

MODEL_LABELS = {
    "tiny":           {"label": "Tiny",     "note": "fastest, rough"},
    "base":           {"label": "Base",     "note": "fast, rough"},
    "small":          {"label": "Balanced", "note": "good, faster"},
    "medium":         {"label": "Medium",   "note": "accurate, slow"},
    "large-v3-turbo": {"label": "Best",     "note": "most accurate"},
    "large-v3":       {"label": "Large v3", "note": "accurate, very slow"},
}

DEFAULT_MODEL = "large-v3-turbo"

# Chunk length and overlap, in seconds. The overlap gives the decoder run-up
# context on both sides of a seam so a sentence split across the boundary is
# transcribed whole by at least one of the two chunks.
CHUNK_SEC = 600.0
OVERLAP_SEC = 8.0

# Characters of the previous chunk fed to the next as --prompt. whisper caps the
# initial prompt at n_text_ctx/2 tokens (~224); 300 chars stays well under.
CARRY_CHARS = 300

_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")


class TranscribeError(Exception):
    pass


class Cancelled(TranscribeError):
    """Message must contain 'Cancelled' — server.py keys task state off that."""
    def __init__(self):
        super().__init__("Cancelled")


def _no_window():
    """Keep whisper-cli/ffmpeg from flashing a console window in the GUI app."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


_BACKEND_RE = re.compile(r"load_backend:\s*loaded (\w+) backend from (.+?)\s*$", re.M)
# "ggml_vulkan: 0 = NVIDIA GeForce RTX 5060 Ti (NVIDIA) | uma: 0 | fp16: 1 | ..."
_GPU_DEV_RE = re.compile(r"^ggml_\w+:\s*(\d+)\s*=\s*(.+?)\s*\|", re.M)
_backends_cache = {}


def probe_backends(whisper_cli):
    """Which ggml backends this install can actually load, asked of the binary.

    ggml here is built with dynamic backend loading (its strings carry
    `load_backend`, `GGML_BACKEND_PATH` and the names vulkan/cuda/metal/...), so
    it discovers backend DLLs sitting next to it at runtime. That means the only
    honest answer to "is there GPU support" comes from the engine, not from
    guessing at the machine's hardware: drop a ggml-vulkan.dll in and it lights
    up by itself, with no code change here.

    `--help` loads every backend it finds and prints one line each. Costs ~30 ms,
    cached for the life of the process.
    """
    if not whisper_cli:
        return []
    if whisper_cli in _backends_cache:
        return _backends_cache[whisper_cli]
    try:
        # stdin=DEVNULL matters: the built exe is windowed (console=False), so
        # the process has no valid standard handles to inherit and a child that
        # touches stdin can wedge. Everything else here spawns the same way.
        p = subprocess.run([whisper_cli, "--help"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20,
                           stdin=subprocess.DEVNULL, creationflags=_no_window())
    except (OSError, subprocess.SubprocessError):
        _backends_cache[whisper_cli] = []
        return []

    out = (p.stdout or "") + (p.stderr or "")
    # A machine can expose several adapters — this one has a discrete NVIDIA and
    # an integrated AMD, and landing on the integrated one would be far slower
    # than the discrete card. whisper-cli picks by index with -dev.
    devices = [{"index": int(i), "name": n.strip()} for i, n in _GPU_DEV_RE.findall(out)]
    found = []
    for name, lib in _BACKEND_RE.findall(out):
        entry = {"name": name.upper(), "lib": os.path.basename(lib.strip())}
        if entry["name"] != "CPU":
            entry["devices"] = devices
            if devices:
                entry["device"] = devices[0]["name"]
        found.append(entry)
    _backends_cache[whisper_cli] = found
    return found


def gpu_backend(whisper_cli):
    """The first non-CPU backend, or None. Drives the CPU/GPU choice in the UI."""
    for b in probe_backends(whisper_cli):
        if b["name"] != "CPU":
            return b
    return None


def default_threads():
    """Leave one core for the UI so the window stays responsive."""
    return max(2, min(8, (os.cpu_count() or 4) - 1))


def wav_duration(path):
    """Duration in seconds, straight from the WAV header — no ffprobe needed
    (Y2obi bundles ffmpeg.exe only)."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / float(rate) if rate else 0.0
    except (wave.Error, OSError):
        return 0.0


def _slice_wav(src, dst, start_s, dur_s):
    with wave.open(src, "rb") as w:
        rate = w.getframerate()
        nch, width, total = w.getnchannels(), w.getsampwidth(), w.getnframes()
        start = max(0, min(total, int(start_s * rate)))
        count = total - start if dur_s <= 0 else min(total - start, int(dur_s * rate))
        w.setpos(start)
        frames = w.readframes(count)
    with wave.open(dst, "wb") as o:
        o.setnchannels(nch)
        o.setsampwidth(width)
        o.setframerate(rate)
        o.writeframes(frames)


def _parse_srt(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    cues = []
    i = 0
    while i < len(lines):
        if not lines[i].strip().isdigit() or i + 1 >= len(lines):
            i += 1
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[i + 1])
        if not m:
            i += 1
            continue
        g = [int(x) for x in m.groups()]
        start = (g[0] * 3600 + g[1] * 60 + g[2]) * 1000 + g[3]
        end = (g[4] * 3600 + g[5] * 60 + g[6]) * 1000 + g[7]
        j = i + 2
        text = []
        while j < len(lines) and lines[j].strip():
            text.append(lines[j].strip())
            j += 1
        if text:
            cues.append({"start": start, "end": end, "text": " ".join(text)})
        i = j
    return cues


def _merge_parts(parts, overlap_s):
    """parts: [(offset_s, slice-relative cues)] in order. Returns absolute cues.

    Stitches by how much new timeline each cue adds, walking the parts in order
    and tracking how far the transcript already reaches:

      - a cue lying entirely inside covered ground is a re-transcription of the
        overlap, so it is dropped;
      - a cue straddling the seam is kept only if most of it is new, otherwise
        its few new milliseconds are not worth repeating a whole sentence.

    Assigning fixed ownership by seam position instead would be tidier, but it
    silently loses any cue that begins before its seam and so is longer than the
    overlap — a long sentence at a chunk boundary vanishes from the transcript.
    Erring toward a couple of repeated words beats dropping a sentence.
    """
    covered = -math.inf
    out = []
    for offset_s, cues in parts:
        base = offset_s * 1000.0
        for c in cues:
            start, end = c["start"] + base, c["end"] + base
            if end <= covered:
                continue
            if start < covered and (end - covered) < 0.5 * max(1.0, end - start):
                continue
            out.append({"start": start, "end": end, "text": c["text"]})
            covered = max(covered, end)
    return out


def _detect_loops(cues, min_run=5):
    """Consecutive identical lines — the signature of a whisper hallucination loop."""
    runs, prev, count = [], None, 0
    for c in cues:
        t = c["text"].strip().lower()
        if not t:
            continue
        if t == prev:
            count += 1
        else:
            if count >= min_run:
                runs.append((prev, count))
            prev, count = t, 1
    if count >= min_run:
        runs.append((prev, count))
    return runs


def _fmt_ts(ms):
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_outputs(cues, out_prefix):
    """Write <prefix>.txt and <prefix>.srt. Returns the paths written."""
    txt_path = out_prefix + ".txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        for c in cues:
            f.write(c["text"].strip() + "\n")

    srt_path = out_prefix + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}\n{c['text'].strip()}\n\n")

    return [txt_path, srt_path]


class Transcriber:
    """One instance per task — it owns a live subprocess handle, so sharing it
    across concurrent tasks would let one cancel kill another's whisper run."""

    def __init__(self, whisper_cli, ffmpeg_path, model_dir, cancel_event=None):
        self.whisper_cli = whisper_cli
        self.ffmpeg_path = ffmpeg_path
        self.model_dir = model_dir
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

    # --- models -----------------------------------------------------------

    def model_file(self, name):
        spec = MODELS.get(str(name).lower())
        if not spec:
            raise TranscribeError(f"Unknown model '{name}'")
        return os.path.join(self.model_dir, spec[0])

    def has_model(self, name):
        return os.path.isfile(self.model_file(name))

    def ensure_model(self, name, progress_cb=None, status_cb=None):
        """Return the local model path, downloading it if absent.

        Resumes a partial download and verifies the final size — a truncated
        model would otherwise be cached and fail on every later run.
        """
        name = str(name).lower()
        if name not in MODELS:
            raise TranscribeError(f"Unknown model '{name}'")
        path = self.model_file(name)
        if os.path.isfile(path):
            return path

        fname, url, size_mb = MODELS[name]
        os.makedirs(self.model_dir, exist_ok=True)
        tmp = path + ".part"
        got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        if status_cb:
            status_cb(f"Downloading model {name} (~{size_mb} MB, one time)...")

        last_err = None
        for attempt in range(4):
            self._check_cancel()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Y2obi"})
                if got:
                    req.add_header("Range", f"bytes={got}-")
                with urllib.request.urlopen(req, timeout=60) as r:
                    resuming = got > 0 and r.status == 206
                    if not resuming:
                        got = 0
                    total = got + int(r.headers.get("Content-Length") or 0)
                    with open(tmp, "ab" if resuming else "wb") as f:
                        while True:
                            self._check_cancel()
                            buf = r.read(1 << 20)
                            if not buf:
                                break
                            f.write(buf)
                            got += len(buf)
                            if progress_cb and total:
                                progress_cb(min(got / total * 100.0, 100.0))
                last_err = None
                break
            except Cancelled:
                raise
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_err = e
                got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
                if attempt < 3:
                    if status_cb:
                        status_cb(f"Download interrupted, retrying ({attempt + 1}/3)...")
                    time.sleep(2 * (attempt + 1))

        if last_err is not None:
            raise TranscribeError(f"Model download failed: {last_err}")

        # Guard against a silently truncated file becoming a poisoned cache entry.
        if os.path.getsize(tmp) < size_mb * 900_000:
            os.unlink(tmp)
            raise TranscribeError("Model download incomplete — try again")

        os.replace(tmp, path)
        return path

    # --- audio ------------------------------------------------------------

    def to_wav(self, src, dst):
        """16 kHz mono PCM — what whisper wants, and what lets us slice chunks
        with the stdlib wave module.

        Popen, not subprocess.run: extracting an hour of audio takes minutes,
        and a blocking call keeps self._proc unset, so Cancel could not reach
        ffmpeg and was swallowed until the extraction finished on its own.
        """
        self._check_cancel()
        self._proc = subprocess.Popen(
            [self.ffmpeg_path, "-y", "-i", src, "-vn", "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", dst],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=_no_window(),
        )
        try:
            _out, err = self._proc.communicate()
            code = self._proc.returncode
        finally:
            proc, self._proc = self._proc, None
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass

        self._check_cancel()
        if code != 0 or not os.path.exists(dst):
            tail = (err or b"").decode("utf-8", "replace").strip().split("\n")[-1:]
            raise TranscribeError(f"Audio extraction failed: {' '.join(tail)}")
        return dst

    # --- whisper ----------------------------------------------------------

    def _run_chunk(self, wav, model_path, lang, threads, prompt, on_chunk_pct,
                   use_gpu=False, gpu_index=0):
        prefix = os.path.join(tempfile.gettempdir(), f"y2obi_w_{os.urandom(6).hex()}")
        srt_path = prefix + ".srt"
        args = [self.whisper_cli, "-m", model_path, "-f", wav,
                "-l", lang, "-t", str(threads), "-pp", "-sns", "-osrt", "-of", prefix]
        # whisper picks a GPU backend on its own when one loaded; -ng is the only
        # way to hold it to the CPU.
        if use_gpu:
            args += ["-dev", str(gpu_index)]
        else:
            args.append("-ng")
        if prompt:
            args += ["--prompt", prompt]

        self._check_cancel()
        self._proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_no_window(),
        )
        try:
            for line in self._proc.stdout:
                if self._cancelled():
                    break
                m = _PROGRESS_RE.search(line)
                if m and on_chunk_pct:
                    on_chunk_pct(int(m.group(1)))
            code = self._proc.wait()
        finally:
            proc, self._proc = self._proc, None
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass

        self._check_cancel()
        if code != 0:
            raise TranscribeError(f"whisper-cli exited with code {code}")
        if not os.path.isfile(srt_path):
            raise TranscribeError("whisper-cli produced no output")
        try:
            return _parse_srt(srt_path)
        finally:
            os.unlink(srt_path)

    def transcribe(self, audio, model_path, out_prefix, lang="auto", prompt=None,
                   threads=None, progress_cb=None, status_cb=None,
                   chunk_sec=CHUNK_SEC, overlap_s=OVERLAP_SEC, use_gpu=False,
                   gpu_index=0):
        """Transcribe `audio` to <out_prefix>.txt/.srt. Returns the paths written."""
        threads = threads or default_threads()
        log = status_cb or (lambda _m: None)
        report = progress_cb or (lambda _p: None)

        work_dir = tempfile.mkdtemp(prefix="y2obi_tr_")
        wav = os.path.join(work_dir, "audio.wav")
        try:
            log("Extracting audio...")
            self.to_wav(audio, wav)
            self._check_cancel()

            total_s = wav_duration(wav)
            if total_s <= 0:
                raise TranscribeError("Could not read the extracted audio")

            step = max(1.0, chunk_sec - overlap_s)
            n_chunks = max(1, int(math.ceil(total_s / step))) if total_s > chunk_sec else 1

            parts = []
            carry = None
            for i in range(n_chunks):
                self._check_cancel()
                start = i * step
                if start >= total_s:
                    break
                length = min(chunk_sec, total_s - start)

                if n_chunks == 1:
                    chunk_wav = wav
                    log("Transcribing...")
                else:
                    chunk_wav = os.path.join(work_dir, f"chunk{i}.wav")
                    _slice_wav(wav, chunk_wav, start, length)
                    log(f"Transcribing part {i + 1}/{n_chunks}...")

                def on_pct(p, _i=i):
                    report((_i + p / 100.0) / n_chunks * 100.0)

                # Tail of the previous chunk primes the decoder so a sentence
                # cut at the seam keeps its context (and its vocabulary).
                chunk_prompt = " ".join(x for x in (prompt, carry) if x) or None
                cues = self._run_chunk(chunk_wav, model_path, lang, threads,
                                       chunk_prompt, on_pct, use_gpu, gpu_index)
                parts.append((start, cues))
                carry = " ".join(c["text"] for c in cues[-6:])[-CARRY_CHARS:] or None

                if chunk_wav != wav:
                    os.unlink(chunk_wav)
                report((i + 1) / n_chunks * 100.0)

            cues = _merge_parts(parts, overlap_s)
            if not cues:
                raise TranscribeError("No speech detected in this audio")

            loops = _detect_loops(cues)
            if loops:
                text, n = loops[0]
                log(f"Note: {n} repeated lines detected (\"{text[:40]}...\")")

            return write_outputs(cues, out_prefix)
        finally:
            for name in os.listdir(work_dir) if os.path.isdir(work_dir) else []:
                try:
                    os.unlink(os.path.join(work_dir, name))
                except OSError:
                    pass
            try:
                os.rmdir(work_dir)
            except OSError:
                pass
