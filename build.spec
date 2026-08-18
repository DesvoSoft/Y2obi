# -*- mode: python ; coding: utf-8 -*-
import os
import webview

# Path to pywebview package (for collecting DLLs / data files)
webview_pkg = os.path.dirname(webview.__file__)

# whisper.cpp ships nine ggml-cpu-*.dll variants and picks the best one at
# runtime. Benchmarked on 60 s of audio (ggml-small, 4 threads): the AVX-512
# build it auto-picks (cascadelake) encodes in 4160 ms, the AVX2 one (haswell)
# in 3069 ms, and plain x64 in 53323 ms. So AVX2 is both the fastest and the
# only variant worth shipping; x64 stays as the fallback for pre-2013 CPUs.
# Dropping the other seven saves 5.8 MB of payload and costs nothing.
WHISPER_FILES = [
    'whisper-cli.exe', 'whisper.dll', 'ggml.dll', 'ggml-base.dll',
    'ggml-cpu-haswell.dll',  # AVX2 — anything from 2013 on
    'ggml-cpu-x64.dll',      # baseline fallback
    # GPU. 54 MB, and worth every one: benchmarked on 111.5 s of speech with
    # ggml-small, CPU took 14.57 s and Vulkan 2.05 s once its shaders were
    # cached — 7.1x, with the encoder alone going 8.49 s -> 0.08 s. Transcripts
    # matched the CPU run word for word (264/264).
    # Taken from a llama.cpp Vulkan release, not whisper.cpp, which publishes no
    # Vulkan build for Windows. They share ggml and the ABI matched; if whisper
    # is ever updated, re-verify this pair together.
    'ggml-vulkan.dll',
]
whisper_datas = [
    (os.path.join('core', 'whisper', f), os.path.join('core', 'whisper'))
    for f in WHISPER_FILES
    if os.path.exists(os.path.join('core', 'whisper', f))
]

# The Vulkan backend is a llama.cpp binary and the rest are whisper.cpp ones, so
# the ggml ABI they share is a pinned combination, not a guarantee. A mismatch
# would be silent corruption rather than a clean failure, so the build refuses to
# proceed when a file stops matching the manifest that was verified with
# tools/verify_whisper.py. Swap a DLL -> build fails -> re-verify -> re-pin.
def _check_whisper_manifest():
    import hashlib
    import json
    manifest_path = os.path.join('core', 'whisper', 'MANIFEST.json')
    if not os.path.exists(manifest_path):
        raise SystemExit(
            'core/whisper/MANIFEST.json is missing. Run tools/verify_whisper.py '
            '--pin after installing the whisper binaries.')
    with open(manifest_path, encoding='utf-8') as fh:
        pinned = json.load(fh)['files']
    for name, meta in pinned.items():
        path = os.path.join('core', 'whisper', name)
        if not os.path.exists(path):
            raise SystemExit(f'{path} is missing but pinned in MANIFEST.json')
        digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()
        if digest != meta['sha256']:
            raise SystemExit(
                name + ' does not match MANIFEST.json (' + meta['source'] + '). '
                'The whisper/ggml pair changed. Re-run tools/verify_whisper.py '
                'to confirm CPU and GPU still agree, then --pin to update it.')


_check_whisper_manifest()

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Desktop HTML + Vitra CSS/JS + icons
        ('desktop', 'desktop'),
        # pywebview ships WebView2Loader.dll and Microsoft.Web.WebView2.* managed DLLs
        (os.path.join(webview_pkg, 'lib'), 'webview/lib'),
        # Bundled ffmpeg.exe — no runtime download needed (see app/binaries.py)
        (os.path.join('core', 'ffmpeg.exe'), 'core'),
        # whisper.cpp CLI + ggml DLLs for transcription. datas, not binaries:
        # they are loaded by whisper-cli.exe as a separate process, so letting
        # PyInstaller walk their imports buys nothing and can mangle them.
        *whisper_datas,
    ],
    hiddenimports=[
        # pywebview Windows backend
        'webview',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'webview.platforms.mshtml',
        'webview.platforms.win32',
        'webview.dom',
        'webview.models',
        'webview.util',
        'webview.js',
        # pythonnet / CLR
        'clr',
        'clr_loader',
        'pythonnet',
        # Flask / Werkzeug
        'flask',
        'flask.templating',
        'jinja2',
        'jinja2.ext',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.routing',
        'werkzeug.exceptions',
        'werkzeug.middleware',
        'werkzeug.middleware.shared_data',
        # yt-dlp
        'yt_dlp',
        'yt_dlp.extractor',
        'yt_dlp.downloader',
        'yt_dlp.postprocessor',
        'yt_dlp.networking',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'customtkinter',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'matplotlib', 'scipy', 'numpy',
        'tkinter.test',
        # Nothing in the app imports Pillow; it was only ever a stray dep.
        'PIL',
        # 13.2 MB of ciphers for extractors we do not use. yt-dlp only reaches
        # for pycryptodome on bilibili/ivi/tarangplus/wrestleuniverse and as an
        # AES accelerator; yt_dlp/dependencies/Cryptodome.py degrades to
        # __bool__ = False and yt_dlp/aes.py takes over in pure Python. Chromium
        # cookie decryption is unaffected — that AES-GCM lives in yt_dlp/aes.py.
        'Crypto', 'Cryptodome',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# PyInstaller reclassifies the whisper DLLs as binaries and walks their imports,
# which hoists a second copy of whisper.dll to the payload root. Nothing loads it
# there: whisper-cli.exe runs out of core/whisper/ and Windows resolves DLLs from
# the executable's own directory first. Drop the duplicate.
_bundled = {f.lower() for f in WHISPER_FILES}
a.binaries = [entry for entry in a.binaries
              if not (os.sep not in entry[0] and entry[0].lower() in _bundled)]

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Y2obi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='desktop/static/icon.ico',
    version='version_info.txt',
)
