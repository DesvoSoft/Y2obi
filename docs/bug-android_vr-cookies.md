# Bug: "Requested format is not available" en desktop .exe

## Síntoma

Al intentar descargar un video desde el `.exe` bundleado, la UI mostraba:

```
YouTube download error: ERROR: [youtube] <ID>: Requested format is not available.
Use --list-formats for a list of available formats
```

El mismo video descargaba sin problema ejecutando `python main.py` directamente.

## Causa raíz

`_base_opts()` en `app/downloader.py` llamaba `_apply_cookies()`, que hace auto-detección de browsers instalados. Al detectar Firefox, agregaba `cookiesfrombrowser: ('firefox',)` a las opciones de yt-dlp.

El problema: **`android_vr` no soporta cookies**. Cuando yt-dlp detecta cookies en las opciones, descarta silenciosamente el client `android_vr` con:

```
WARNING: [youtube] Skipping client "android_vr" since it does not support cookies
```

Sin ningún client válido (`tv_embedded` también se descarta por ser unsupported), yt-dlp solo encuentra storyboard images — no formatos de video/audio — y el format selector falla.

## Por qué no fallaba en desarrollo

`python main.py` sin build no llegaba a este branch de código en las pruebas, o Firefox no estaba corriendo/disponible de la misma forma.

## Fix

Cambiar `_base_opts()` para usar `_apply_cookies_file_only()` en lugar de `_apply_cookies()`, igual que ya hacía `get_info()`.

```python
# app/downloader.py — _base_opts()
# Antes:
self._apply_cookies(opts)       # auto-detectaba Firefox → rompía android_vr

# Después:
self._apply_cookies_file_only(opts)  # solo cookies.txt explícito
```

`_apply_cookies_file_only` solo agrega cookies si hay un `cookies.txt` subido manualmente — nunca intenta auto-extracción del browser.

## Commit

`b359ea7` — fix: dont pass browser cookies to android_vr client

## Lección

`android_vr` y `tv_embedded` son los clients usados para bypassear el n-challenge de YouTube sin JS runtime. Ambos tienen restricciones — `android_vr` no acepta cookies. Si se necesita autenticación (videos de miembros, age-gated), hay que usar un client diferente o pasar cookies vía archivo sin activar estos clients.
