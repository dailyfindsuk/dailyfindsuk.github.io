"""
YouTube Shorts for Daily Finds UK.

  python youtube.py --connect    one-off: connect your YouTube channel (opens the browser)
  python youtube.py --check      shows which channel the bot is connected to

The connect step reads the client_secret_....json file you downloaded from Google
Cloud (keep it in this folder, never upload it anywhere) and saves three values to .env:
YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN. Add the same three as GitHub secrets.

Until Google approves the API audit, YouTube forces uploads from new API projects to
"private". The bot still uploads them; you can make the good ones public in YouTube Studio.
"""

import argparse
import http.server
import json
import secrets
import socket
import sys
import threading
import urllib.parse
from pathlib import Path

import requests

import dealbot

ROOT = Path(__file__).parent
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def client_file():
    files = sorted(ROOT.glob("client_secret_*.json"))
    if not files:
        sys.exit("Can't find the client_secret_....json file. Put it in the dealbot folder and try again.")
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return data.get("installed") or data.get("web")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def connect():
    import webbrowser
    c = client_file()
    port = _free_port()
    redirect = f"http://127.0.0.1:{port}"
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Done! You can close this tab and go back to the black window." if "code" in q \
                else "Something went wrong. Go back to the black window."
            self.wfile.write(f"<h2 style='font-family:sans-serif'>{msg}</h2>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=lambda: [server.handle_request() for _ in range(3) if not got])
    t.daemon = True
    t.start()

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": state,
    })
    print("Opening Google's permission page in your browser...\n")
    print("If it doesn't open, copy this link into your browser:\n" + url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("1. Pick the Google account that owns the Daily Finds UK YouTube channel")
    print("   (and the channel itself, if it asks).")
    print("2. If Google says 'Google hasn't verified this app': click Advanced,")
    print("   then 'Go to Daily Finds UK Bot'. It's your own app, so that's expected.")
    print("3. Tick the boxes and click Continue.\n")
    print("Waiting for you to finish in the browser...")
    t.join(timeout=600)
    server.server_close()
    if got.get("state") != state or "code" not in got:
        sys.exit(f"Didn't get permission ({got.get('error', 'timed out')}). Run it again.")

    r = requests.post(TOKEN_URL, data={
        "code": got["code"], "client_id": c["client_id"], "client_secret": c["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code"}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Failed ({r.status_code}): {r.text}")
    refresh = r.json().get("refresh_token")
    if not refresh:
        sys.exit("Google didn't return a refresh token. Run it again.")
    dealbot.save_env_value("YT_CLIENT_ID", c["client_id"])
    dealbot.save_env_value("YT_CLIENT_SECRET", c["client_secret"])
    dealbot.save_env_value("YT_REFRESH_TOKEN", refresh)
    print("\nSaved YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN to .env")
    check()


def access_token():
    r = requests.post(TOKEN_URL, data={
        "client_id": dealbot.env("YT_CLIENT_ID"), "client_secret": dealbot.env("YT_CLIENT_SECRET"),
        "refresh_token": dealbot.env("YT_REFRESH_TOKEN"), "grant_type": "refresh_token"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"YouTube token refresh failed ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


def check():
    tok = access_token()
    r = requests.get("https://www.googleapis.com/youtube/v3/channels",
                     params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        print("Connected, but this Google account has no YouTube channel.")
        print("Run it again and pick the Daily Finds UK channel.")
        return
    s = items[0]["snippet"]
    print(f"\nConnected to YouTube channel: {s['title']} {s.get('customUrl', '')}")


def upload_short(video_path, title, description, tags=(), privacy="public"):
    """Uploads a vertical video as a Short. Returns the video id."""
    tok = access_token()
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": list(tags)[:15], "categoryId": "26"},  # Howto & Style
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": False},
    }
    size = Path(video_path).stat().st_size
    r = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps(meta), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"YouTube upload start failed ({r.status_code}): {r.text[:300]}")
    with open(video_path, "rb") as f:
        up = requests.put(r.headers["Location"], data=f,
                          headers={"Content-Type": "video/mp4"}, timeout=600)
    if up.status_code not in (200, 201):
        raise RuntimeError(f"YouTube upload failed ({up.status_code}): {up.text[:300]}")
    return up.json()["id"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.connect:
        connect()
    else:
        check()
