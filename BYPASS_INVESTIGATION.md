# YouTube Bot Bypass — Investigation & Proposals

**Date:** 2026-06-20  
**Status:** BROKEN on Render — bot check fires on every request

---

## Root Cause Analysis

### Confirmed from logs
- `_make_dl cookies=None` → no cookies loaded on startup
- `cookies_exist=False` → `COOKIES_PATH` doesn't exist at request time
- Even after manual upload: `cookies_exist=True` → still fails → cookies not enough alone
- **NO** bgutil startup logs visible (`[Y2obi] Starting bgutil server:` never appears)

### Bug #1 — Missing `return` in `_start_bgutil()`
```python
# web/app.py ~line 23 — current (broken)
if not os.path.exists(main_js):
    print(f"[Y2obi] bgutil main.js not found at {main_js} — bgutil disabled", flush=True)
    # ← NO RETURN HERE — falls through into _run() definition, starts broken thread

# fix
if not os.path.exists(main_js):
    print(f"[Y2obi] bgutil main.js not found at {main_js} — bgutil disabled", flush=True)
    return  # ← add this
```

### Bug #2 — bgutil build may be silently failing on Render
- `render.yaml` uses `apt-get install -y nodejs` inside build command
- Render Python runtime may not have `sudo`/`apt` available at build time
- No verification step after `npx tsc` — build could fail with exit 0

### Bug #3 — Render free tier IP reputation
- YouTube aggressively blocks datacenter IPs
- Cookies from a real account *help* but don't fully bypass from known-bad IPs
- bgutil (BotGuard/PO token) is the real bypass — without it, even valid cookies fail

---

## What bgutil actually does
1. Runs a Node.js server on `127.0.0.1:4416`
2. `bgutil-ytdlp-pot-provider` pip package hooks into yt-dlp as a POT provider
3. On each yt-dlp call, fetches a fresh BotGuard attestation token from the server
4. YouTube sees a valid browser-like attestation → no bot check

Without bgutil running, `web` client always hits the bot check on server IPs.

---

## Proposals (ordered by effort/risk)

### P1 — Fix `return` bug + verbose bgutil logs [LOW effort, must-do]
- Add missing `return` in `_start_bgutil()`
- Log `main_js` path, Node version, stdout/stderr from bgutil process
- Verify `BGUTIL_SERVER_HOME` env var reaches the process

### P2 — Verify bgutil build on Render [LOW effort]
- Add `node --version && ls -la /opt/bgutil/server/build/` to build command
- Add `&& echo "BUILD OK"` sentinel to catch silent failures
- Consider pinning bgutil version in `render.yaml` (currently 1.3.1 — check if newer)

### P3 — Use `android_creator` client as fallback [LOW effort]
- `android_creator` doesn't require PO token in some yt-dlp versions
- Try: `'player_client': ['web', 'android_creator']`
- Downside: may get lower quality formats, may still fail on bad IPs

### P4 — Multi-client fallback strategy [MEDIUM effort]
```python
# Try in order until one works
CLIENTS_BY_PREFERENCE = [
    ['web'],           # best quality, needs bgutil
    ['tv_embedded'],   # no bot check historically
    ['android'],       # no POT needed
    ['mweb'],          # mobile web, sometimes less restricted
]
```

### P5 — `COOKIES_B64` env var pre-load [LOW effort, parallel fix]
- Currently: cookies only load if file exists at `COOKIES_PATH`
- Enhancement: decode `COOKIES_B64` at Flask startup (already in CLAUDE.md as planned)
- Means: cookies work from first request, no need for user to upload
- Confirmed already coded? Check `web/app.py` startup section

### P6 — Move bgutil to a persistent service [HIGH effort]
- Render free: process dies after 15min → bgutil dies → cold start loses it
- Option: run bgutil as separate Render service (always-on free web service on different port)
- Flask calls `http://bgutil-service:4416` instead of `127.0.0.1:4416`
- Cons: two services, bgutil service also sleeps on free tier

### P7 — Replace Render with Railway/Fly.io [HIGH effort]
- Better IP reputation than Render free tier
- Railway: $5/month hobby plan, persistent processes
- Fly.io: free tier, but better datacenter IP reputation
- Not a code fix — infrastructure change

### P8 — Self-hosted / VPS [HIGH effort]
- DigitalOcean/Hetzner $4-6/month
- Residential-adjacent IPs or dedicated server
- Full control over Node.js install, bgutil, persistent processes

---

## Immediate Action Plan

1. **Fix `return` bug** (P1) — deploy, check logs for bgutil startup
2. **Add build verification** (P2) — confirm bgutil actually built
3. **Add `android_creator` fallback** (P3) — works without bgutil
4. **Verify `COOKIES_B64` pre-load** (P5) — fix cookie flow
5. **Evaluate results** — if still failing, consider P6/P7/P8

---

## yt-dlp client matrix (research needed)

| Client | Needs POT | Quality | Bot-check resistance |
|--------|-----------|---------|----------------------|
| `web` | YES (bgutil) | Best | Low without POT |
| `android` | No | Good | Medium |
| `android_creator` | No | Good | Medium-High |
| `tv_embedded` | No | Medium | High (historically) |
| `mweb` | Sometimes | Medium | Unknown |
| `web_creator` | YES | Best | Low without POT |

---

## Open Questions
- Is bgutil 1.3.1 still current? (check GitHub releases)
- Does `tv_embedded` still bypass bot check as of June 2026?
- Are Render Virginia IPs on YouTube's datacenter blocklist?
- Is the uploaded cookies.txt actually valid (not expired)?
