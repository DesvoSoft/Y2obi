# -*- mode: python ; coding: utf-8 -*-
import os
import webview

# Path to pywebview package (for collecting DLLs / data files)
webview_pkg = os.path.dirname(webview.__file__)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Desktop HTML + Vitra CSS/JS
        ('desktop', 'desktop'),
        # pywebview ships WebView2Loader.dll and Microsoft.Web.WebView2.* managed DLLs
        (os.path.join(webview_pkg, 'lib'), 'webview/lib'),
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
        # misc
        'PIL',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'customtkinter',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'matplotlib', 'scipy', 'numpy',
        'tkinter.test',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

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
    icon=None,
)
