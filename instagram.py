"""
Instagram Reels for Daily Finds UK (Instagram API with Instagram Login).

  python instagram.py --connect   paste the token from the Meta app dashboard; saves it to .env
  python instagram.py --check     shows which Instagram account the bot is connected to

Works with both kinds of Meta token: a system-user token ("EAA...", never expires; also
needs IG_USER_ID, the account ID shown in the dashboard) or an Instagram-login token
("IG...", 60 days, refreshed automatically on every run). Add the same values to GitHub
as secrets, and keep the account public (Meta only allows public accounts).
"""

import argparse
import sys
import time
from pathlib import Path

import requests

import dealbot

VERSION = "v23.0"
UPLOAD = f"https://rupload.facebook.com/ig-api-upload/{VERSION}"


def token():
    return dealbot.env("IG_ACCESS_TOKEN")


def is_facebook_token(tok):
    """Meta issues two kinds: Instagram-login tokens start "IG", Facebook/system-user ones "EAA"."""
    return not tok.startswith("IG")


def api(tok):
    host = "graph.facebook.com" if is_facebook_token(tok) else "graph.instagram.com"
    return f"https://{host}/{VERSION}"


def me(tok=None, ig_id=None):
    """Returns {'user_id', 'username'} for the connected Instagram account."""
    tok = tok or token()
    if is_facebook_token(tok):
        ig_id = ig_id or dealbot.env("IG_USER_ID")
        r = requests.get(f"{api(tok)}/{ig_id}", params={"fields": "id,username",
                                                         "access_token": tok}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Instagram check failed ({r.status_code}): {r.text[:300]}")
        d = r.json()
        return {"user_id": d["id"], "username": d.get("username"), "account_type": "business"}
    r = requests.get(f"{api(tok)}/me", params={"fields": "user_id,username,account_type",
                                               "access_token": tok}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Instagram check failed ({r.status_code}): {r.text[:300]}")
    return r.json()


def refresh():
    """Extends a 60-day Instagram-login token. System-user tokens never expire.
    Returns days left, or None."""
    if is_facebook_token(token()):
        return None
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token()}, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("access_token") and data["access_token"] != token():
        print("Note: Instagram issued a new token string. Update the IG_ACCESS_TOKEN secret "
              "(run instagram.bat again).")
    return int(data.get("expires_in", 0)) // 86400


def connect():
    print("In the Meta app dashboard (Instagram API > API setup), click 'Generate token'")
    print("next to your Instagram account, log in, then copy the token it shows.\n")
    tok = "".join(input("Paste the token here and press Enter: ").split())
    ig_id = None
    if is_facebook_token(tok):
        print("\nThis is a never-expiring system-user token. The bot also needs the account ID:")
        print("the long number shown under 'dailyfinds.ukdeals' in the Meta dashboard.")
        ig_id = "".join(input("Paste the Instagram account ID and press Enter: ").split())
    info = me(tok, ig_id)
    dealbot.save_env_value("IG_ACCESS_TOKEN", tok)
    if ig_id:
        dealbot.save_env_value("IG_USER_ID", ig_id)
    print("\nSaved to .env" + (" (IG_ACCESS_TOKEN and IG_USER_ID)" if ig_id else " (IG_ACCESS_TOKEN)"))
    print(f"Connected to Instagram: @{info.get('username')} ({info.get('account_type')})")
    print("Now add the same value(s) to GitHub as secrets: IG_ACCESS_TOKEN" + (" and IG_USER_ID" if ig_id else ""))


def post_reel(video_path, caption):
    """Uploads a vertical MP4 as a Reel. Returns the media id."""
    tok = token()
    user = me(tok)["user_id"]
    API = api(tok)
    r = requests.post(f"{API}/{user}/media", params={"access_token": tok}, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true",
        "thumb_offset": "10000"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Instagram container failed ({r.status_code}): {r.text[:300]}")
    container = r.json()["id"]
    data = Path(video_path).read_bytes()
    up = requests.post(f"{UPLOAD}/{container}", data=data, timeout=600, headers={
        "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(data))})
    if up.status_code != 200:
        raise RuntimeError(f"Instagram upload failed ({up.status_code}): {up.text[:300]}")
    for _ in range(40):   # Instagram processes the video before it can be published
        time.sleep(6)
        s = requests.get(f"{API}/{container}", params={"fields": "status_code,status",
                                                       "access_token": tok}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram couldn't process the video: {s.get('status')}")
    else:
        raise RuntimeError("Instagram took too long to process the video")
    p = requests.post(f"{API}/{user}/media_publish", params={"access_token": tok},
                      data={"creation_id": container}, timeout=60)
    if p.status_code != 200:
        raise RuntimeError(f"Instagram publish failed ({p.status_code}): {p.text[:300]}")
    return p.json()["id"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", action="store_true")
    a = ap.parse_args()
    if a.connect:
        connect()
    else:
        i = me()
        print(f"Connected to Instagram: @{i.get('username')} ({i.get('account_type')})")
