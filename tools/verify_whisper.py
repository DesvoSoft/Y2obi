"""Verify the bundled whisper/ggml binaries actually agree with each other.

Y2obi ships a Vulkan backend taken from a llama.cpp release alongside a
whisper.cpp build, because whisper.cpp publishes no Vulkan binaries for Windows.
They share ggml and the combination works, but that is a pinned fact rather than
a guarantee: an ABI drift between the two would corrupt results silently instead
of failing loudly.

So this does not just compare hashes. It synthesises speech locally with the
Windows voice, transcribes it once on the CPU and once on the GPU, and fails if
the two transcripts disagree.

    python tools/verify_whisper.py           # check the pinned set
    python tools/verify_whisper.py --pin     # re-pin after a successful check

Needs one model cached in %APPDATA%/Y2obi/models (any will do; small is plenty).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CORE = os.path.join(ROOT, "core", "whisper")
MANIFEST = os.path.join(CORE, "MANIFEST.json")

SAMPLE = (
    "The quick brown fox jumps over the lazy dog. "
    "Speech recognition converts spoken audio into written text. "
    "This recording exists only to check that two backends agree."
)


def _fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def check_hashes():
    if not os.path.exists(MANIFEST):
        _fail("core/whisper/MANIFEST.json is missing — run with --pin first.")
    pinned = json.load(open(MANIFEST, encoding="utf-8"))["files"]
    bad = []
    for name, meta in pinned.items():
        path = os.path.join(CORE, name)
        if not os.path.exists(path):
            bad.append(f"{name}: missing")
            continue
        digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if digest != meta["sha256"]:
            bad.append(f"{name}: changed since it was pinned ({meta['source']})")
    print(f"  pinned files: {len(pinned)}  mismatched: {len(bad)}")
    for b in bad:
        print("    " + b)
    return not bad


def make_speech(dst_wav, ffmpeg):
    """Synthesise a sample with the Windows voice — local, no network, no assets."""
    raw = dst_wav + ".raw.wav"
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{raw}'); "
        f"1..2 | ForEach-Object {{ $s.Speak('{SAMPLE}') }}; $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   capture_output=True)
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", raw,
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dst_wav],
                   check=True)
    os.unlink(raw)
    return dst_wav


def transcribe(cli, model, wav, use_gpu, out_prefix):
    args = [cli, "-m", model, "-f", wav, "-l", "en", "-t", "4", "-nt",
            "-otxt", "-of", out_prefix]
    if not use_gpu:
        args.append("-ng")
    t0 = time.time()
    p = subprocess.run(args, capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL)
    elapsed = time.time() - t0
    path = out_prefix + ".txt"
    if not os.path.exists(path):
        _fail(f"whisper produced no output ({'GPU' if use_gpu else 'CPU'}):\n"
              + (p.stdout + p.stderr)[-600:])
    return open(path, encoding="utf-8").read(), elapsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true",
                    help="rewrite MANIFEST.json once the check passes")
    args = ap.parse_args()

    from app.binaries import ensure_ffmpeg, get_whisper_cli
    from app import transcriber

    cli = get_whisper_cli()
    if not cli:
        _fail("no whisper binaries in core/whisper/")
    ffmpeg = ensure_ffmpeg()

    print("1. pinned hashes")
    hashes_ok = check_hashes() if os.path.exists(MANIFEST) else False
    if not hashes_ok and not args.pin:
        _fail("binaries differ from the manifest — verify, then re-run with --pin")

    print("2. backends the engine can load")
    transcriber._backends_cache.clear()
    backends = transcriber.probe_backends(cli)
    for b in backends:
        print(f"     {b['name']:8} {b['lib']}"
              + (f"  -> {b.get('device', '')}" if b.get("device") else ""))
    gpu = transcriber.gpu_backend(cli)
    if not gpu:
        print("   no GPU backend present; nothing to cross-check")
        if args.pin:
            pin()
        return

    models_dir = os.path.join(os.environ.get("APPDATA", ""), "Y2obi", "models")
    model = next((os.path.join(models_dir, f) for f in sorted(os.listdir(models_dir))
                  if f.endswith(".bin")), None) if os.path.isdir(models_dir) else None
    if not model:
        _fail("no model cached in %APPDATA%/Y2obi/models — download one first")
    print(f"3. cross-check with {os.path.basename(model)}")

    work = tempfile.mkdtemp(prefix="y2obi_verify_")
    try:
        wav = make_speech(os.path.join(work, "sample.wav"), ffmpeg)
        cpu_txt, cpu_s = transcribe(cli, model, wav, False, os.path.join(work, "cpu"))
        gpu_txt, gpu_s = transcribe(cli, model, wav, True, os.path.join(work, "gpu"))
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    cw, gw = cpu_txt.split(), gpu_txt.split()
    agree = sum(1 for a, b in zip(cw, gw) if a == b)
    print(f"     CPU {cpu_s:6.2f}s   GPU {gpu_s:6.2f}s   ({cpu_s / max(gpu_s, .01):.1f}x)")
    print(f"     words CPU={len(cw)} GPU={len(gw)} agreeing={agree}")

    if not cw or len(cw) != len(gw) or agree != len(cw):
        print("     CPU: " + " ".join(cw[:20]))
        print("     GPU: " + " ".join(gw[:20]))
        _fail("the two backends disagree — do not ship this combination")
    print("     transcripts match word for word")

    if args.pin:
        pin()
    print("\nOK: the bundled whisper/ggml set is consistent.")


def pin():
    files = {}
    known = json.load(open(MANIFEST, encoding="utf-8"))["files"] if os.path.exists(MANIFEST) else {}
    for name in sorted(os.listdir(CORE)):
        if not name.lower().endswith((".dll", ".exe")):
            continue
        path = os.path.join(CORE, name)
        files[name] = {
            "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
            "size": os.path.getsize(path),
            "source": known.get(name, {}).get("source", "unknown — fill this in"),
        }
    json.dump({
        "note": ("The Vulkan backend comes from llama.cpp and the rest from "
                 "whisper.cpp, because whisper.cpp publishes no Vulkan build for "
                 "Windows. They share ggml and this exact combination was verified "
                 "with tools/verify_whisper.py. build.spec refuses to build if any "
                 "hash here stops matching, so the pair can never drift silently."),
        "verified": time.strftime("%Y-%m-%d"),
        "verified_with": "tools/verify_whisper.py",
        "files": files,
    }, open(MANIFEST, "w", encoding="utf-8"), indent=2)
    print(f"   pinned {len(files)} files into MANIFEST.json")


if __name__ == "__main__":
    main()
