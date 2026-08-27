"""Upload a build to VirusTotal and print which engines flag it, and as what.

The point is measurement. "Antivirus complains" is not something you can act on;
"seven engines, all of them generic PyInstaller heuristics, none of them a named
family" is, and so is the same list shrinking after a build change. Run it before
and after anything meant to reduce detections.

    set VT_API_KEY=...          (a free key from virustotal.com/gui/my-apikey)
    python tools/vtscan.py dist/Y2obi.exe

A free key allows 4 requests a minute and 500 a day, which is far more than this
needs. Submitting makes the file public on VirusTotal -- fine for something we
publish as a release asset anyway, and worth knowing before pointing this at
anything else.
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://www.virustotal.com/api/v3"
# VirusTotal takes a direct POST up to 32 MB and requires a one-shot upload URL
# above that. Our onefile exe is well past it, so the second path is the normal
# one here and the first is the fallback, not the other way round.
DIRECT_LIMIT = 32 * 1024 * 1024


def _req(url, key, data=None, headers=None, method=None):
    h = {"x-apikey": key, "accept": "application/json"}
    h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _multipart(path):
    """Build a multipart/form-data body by hand.

    requests is not a dependency of this project and adding one for a developer
    tool would be silly; the body is three lines of bytes.
    """
    boundary = "----y2obi" + hashlib.sha1(path.encode()).hexdigest()[:16]
    name = os.path.basename(path)
    with open(path, "rb") as f:
        payload = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def lookup(digest, key):
    """The report for a file VirusTotal has already seen, or None."""
    try:
        return _req(f"{API}/files/{digest}", key)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def upload(path, key):
    size = os.path.getsize(path)
    if size > DIRECT_LIMIT:
        url = _req(f"{API}/files/upload_url", key)["data"]
        print(f"[vt] {size / 1e6:.0f} MB, using a one-shot upload URL")
    else:
        url = f"{API}/files"
    body, ctype = _multipart(path)
    return _req(url, key, data=body, headers={"content-type": ctype})["data"]["id"]


def wait_for_analysis(analysis_id, key, timeout=900):
    """Poll until the scan finishes. A cold file takes minutes, not seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = _req(f"{API}/analyses/{analysis_id}", key)["data"]
        status = d["attributes"]["status"]
        if status == "completed":
            return d["attributes"]["results"]
        print(f"[vt] {status}...")
        time.sleep(20)
    raise SystemExit("[vt] timed out waiting for the analysis")


def report(results):
    hits = {name: r for name, r in results.items()
            if r.get("category") in ("malicious", "suspicious")}
    total = len(results)
    print()
    print(f"{len(hits)} of {total} engines flagged this build")
    if not hits:
        print("clean")
        return 0
    print()
    width = max(len(n) for n in hits)
    for name in sorted(hits):
        r = hits[name]
        print(f"  {name:<{width}}  {r.get('category'):<10} {r.get('result') or ''}")
    print()
    # A generic name means the packer tripped a heuristic; a family name means an
    # engine believes it recognises specific malware, which is a different and
    # much more serious conversation.
    generic = [n for n, r in hits.items()
               if any(t in (r.get("result") or "").lower()
                      for t in ("generic", "heur", "unsafe", "ml.", "malware.ai",
                                "confidence", "susp", "pua", "packed"))]
    print(f"{len(generic)} of {len(hits)} read as generic/heuristic "
          f"(the packer), {len(hits) - len(generic)} name a specific family")
    return len(hits)


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = argv[1]
    if not os.path.isfile(path):
        print(f"no such file: {path}")
        return 2
    key = os.environ.get("VT_API_KEY")
    if not key:
        print("set VT_API_KEY first (free key: virustotal.com/gui/my-apikey)")
        return 2

    digest = sha256(path)
    print(f"[vt] {os.path.basename(path)}  sha256 {digest}")

    cached = lookup(digest, key)
    if cached:
        # Same bytes, same verdict: re-uploading would only cost time. A build
        # change produces a different hash and lands here as a miss.
        print("[vt] VirusTotal has seen these exact bytes before, reusing that report")
        results = cached["data"]["attributes"]["last_analysis_results"] \
            if "data" in cached else cached["attributes"]["last_analysis_results"]
    else:
        print("[vt] new to VirusTotal, uploading")
        results = wait_for_analysis(upload(path, key), key)

    hits = report(results)
    print(f"\nhttps://www.virustotal.com/gui/file/{digest}")
    return 0 if hits == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
