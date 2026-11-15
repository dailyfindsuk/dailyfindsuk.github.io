"""
TikTok videos for Daily Finds UK (TikTok Content Posting API, Direct Post).

  python tiktok.py --connect        log in with TikTok once; saves the tokens to .env
  python tiktok.py --check          shows which TikTok account the bot is connected to
  python tiktok.py --test VIDEO.mp4 posts one video (privately, "only me") as a test
  python tiktok.py --test latest    same, using the newest video in the videos folder

Needs a TikTok developer app with Login Kit + Content Posting API (Direct Post), scopes
user.info.basic, video.publish and video.upload, and this redirect URI:
    https://dailyfindsuk.github.io/tiktok-callback.html
Add TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REFRESH_TOKEN to GitHub as secrets.

Until TikTok approves the app, it may only post privately: leave TIKTOK_PRIVACY unset
(= SELF_ONLY). After approval, set the secret TIKTOK_PRIVACY to PUBLIC_TO_EVERYONE.
"""

import argparse
import secrets
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

import dealbot

API = "https://open.tiktokapis.com/v2"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
REDIRECT_URI = "https://dailyfindsuk.github.io/tiktok-callback.html"
SCOPES = "user.info.basic,video.publish,video.upload"


def _check(r, what):
    try:
        data = r.json()
    except ValueError:
        data = {}
    err = (data.get("error") or {}) if isinstance(data.get("error"), dict) else {}
    if r.status_code != 200 or (err.get("code") not in (None, "", "ok")):
        raise RuntimeError(f"TikTok {what} failed ({r.status_code}): {r.text[:400]}")
    return data


def _token_request(fields):
    r = requests.post(f"{API}/oauth/token/", timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": dealbot.env("TIKTOK_CLIENT_KEY"),
                            "client_secret": dealbot.env("TIKTOK_CLIENT_SECRET"), **fields})
    data = r.json() if r.content else {}
    if r.status_code != 200 or "access_token" not in data:
        raise RuntimeError(f"TikTok login failed ({r.status_code}): {r.text[:400]}")
    return data


def access_token():
    """A fresh 24-hour access token from the long-lived (365-day) refresh token."""
    data = _token_request({"grant_type": "refresh_token",
                           "refresh_token": dealbot.env("TIKTOK_REFRESH_TOKEN")})
    new = data.get("refresh_token")
    if new and new != dealbot.env("TIKTOK_REFRESH_TOKEN") and dealbot.ENV_FILE.exists():
        dealbot.save_env_value("TIKTOK_REFRESH_TOKEN", new)   # only matters for local runs
    return data["access_token"]


def _headers(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}


def creator_info(tok):
    r = requests.post(f"{API}/post/publish/creator_info/query/", headers=_headers(tok), timeout=30)
    return _check(r, "account check")["data"]


def post_video(path, caption):
    """Uploads one video and publishes it. Returns the publish id."""
    path = Path(path)
    tok = access_token()
    info = creator_info(tok)
    options = info.get("privacy_level_options") or ["SELF_ONLY"]
    privacy = (dealbot.env("TIKTOK_PRIVACY", required=False) or "SELF_ONLY").strip()
    if privacy not in options:
        privacy = "SELF_ONLY" if "SELF_ONLY" in options else options[0]
    size = path.stat().st_size
    if size > 60 * 1024 * 1024:
        raise RuntimeError("video is over 60 MB; TikTok single-part upload limit")
    body = {
        "post_info": {
            "title": caption[:2200],
            "privacy_level": privacy,
            "disable_comment": bool(info.get("comment_disabled")),
            "disable_duet": bool(info.get("duet_disabled")),
            "disable_stitch": bool(info.get("stitch_disabled")),
            "video_cover_timestamp_ms": 4000,      # the frame where the price is showing
            "brand_organic_toggle": True,          # promoting our own deals business
        },
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": size, "total_chunk_count": 1},
    }
    r = requests.post(f"{API}/post/publish/video/init/", headers=_headers(tok), json=body, timeout=30)
    data = _check(r, "upload start")["data"]
    up = requests.put(data["upload_url"], data=path.read_bytes(), timeout=300, headers={
        "Content-Type": "video/mp4", "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}"})
    if up.status_code not in (200, 201):
        raise RuntimeError(f"TikTok video upload failed ({up.status_code}): {up.text[:300]}")
    pid = data["publish_id"]
    for _ in range(30):                             # wait up to ~2.5 minutes
        time.sleep(5)
        s = requests.post(f"{API}/post/publish/status/fetch/", headers=_headers(tok),
                          json={"publish_id": pid}, timeout=30)
        st = _check(s, "status check")["data"]
        status = st.get("status")
        if status == "PUBLISH_COMPLETE":
            return f"{pid} ({privacy.lower().replace('_', ' ')})"
        if status == "FAILED":
            raise RuntimeError(f"TikTok rejected the video: {st.get('fail_reason')}")
    return f"{pid} (still processing; it will appear shortly)"


def cmd_connect():
    for key, label in (("TIKTOK_CLIENT_KEY", "Client key"), ("TIKTOK_CLIENT_SECRET", "Client secret")):
        if not dealbot.env(key, required=False):
            val = input(f"Paste your TikTok app's {label}: ").strip()
            if not val:
                sys.exit("Nothing pasted, stopping.")
            dealbot.save_env_value(key, val)
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_key": dealbot.env("TIKTOK_CLIENT_KEY"), "scope": SCOPES,
        "response_type": "code", "redirect_uri": REDIRECT_URI, "state": state})
    print("\nOpening TikTok in your browser. Log in and tap Authorize.")
    print("If it doesn't open, copy this link into your browser:\n" + url + "\n")
    webbrowser.open(url)
    pasted = input("After authorizing, copy the CODE shown on the Daily Finds page and paste it here: ").strip()
    if "code=" in pasted:                           # they pasted the whole address instead
        q = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        pasted = (q.get("code") or [""])[0]
    if not pasted:
        sys.exit("No code pasted, stopping.")
    data = _token_request({"grant_type": "authorization_code", "code": pasted,
                           "redirect_uri": REDIRECT_URI})
    dealbot.save_env_value("TIKTOK_REFRESH_TOKEN", data["refresh_token"])
    info = creator_info(data["access_token"])
    print(f"\nConnected to TikTok as @{info.get('creator_username')}. Saved to .env.")
    print("Now add these three as GitHub secrets (Settings > Secrets and variables > Actions):")
    print("  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN  (values are in .env)")


def cmd_check():
    info = creator_info(access_token())
    print(f"Connected to TikTok as @{info.get('creator_username')} ({info.get('creator_nickname')})")
    print(f"Allowed privacy settings: {', '.join(info.get('privacy_level_options') or [])}")
    print(f"Posting as: {dealbot.env('TIKTOK_PRIVACY', required=False) or 'SELF_ONLY'}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--connect", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--test", metavar="VIDEO")
    a = p.parse_args()
    if a.connect:
        cmd_connect()
    elif a.test:
        video = a.test
        if video == "latest":
            found = sorted((dealbot.ROOT / "videos").glob("*.mp4"), key=lambda f: f.stat().st_mtime)
            if not found:
                sys.exit("No videos in the videos folder yet. Run testrun.bat first, or give a file.")
            video = found[-1]
        print(f"Uploading {Path(video).name} to TikTok (takes up to a minute)...")
        print("Posted:", post_video(video, "Test post from Daily Finds UK #ad"))
    else:
        cmd_check()


if __name__ == "__main__":
    main()
