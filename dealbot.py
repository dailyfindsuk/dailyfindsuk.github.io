#!/usr/bin/env python3
"""
Deal bot: finds genuine discounts and posts them to Pinterest with affiliate links.

Deal sources:
  eBay UK   via eBay's official Browse API + eBay Partner Network links
  Awin      via retailers' official product feeds (beauty, fragrance, baby & kids)

Commands:
  python dealbot.py                 normal run (posts pins)
  python dealbot.py --dry-run       find deals and print them, post nothing
  python dealbot.py --auth          one-off: get a Pinterest refresh token
  python dealbot.py --list-boards   show your Pinterest boards and their IDs
  python dealbot.py --create-boards find/create a board per category, save IDs
                                    (add --only "Name" to do just one)
  python dealbot.py --demo          post one pin to Pinterest's sandbox (for the
                                    Standard-access video)

Secrets come from environment variables (GitHub Actions secrets in production):
  EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EPN_CAMPAIGN_ID,
  PINTEREST_APP_ID, PINTEREST_APP_SECRET, PINTEREST_REFRESH_TOKEN,
  plus one feed link per Awin category (named in config.yaml, e.g. AWIN_FEED_BEAUTY)
Optional:
  PINTEREST_ACCESS_TOKEN   use this token directly (e.g. a sandbox token)
  PINTEREST_SANDBOX=1      post to Pinterest's sandbox (for Trial-access testing)
"""

import argparse
import base64
import csv
import datetime
import gzip
import io
import json
import os
import random
import re
import sys
import urllib.parse
from pathlib import Path

import requests
import yaml

import site_builder

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state" / "posted.json"
CONFIG_FILE = ROOT / "config.yaml"

EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
PIN_LIVE = "https://api.pinterest.com/v5"
PIN_SANDBOX = "https://api-sandbox.pinterest.com/v5"
PIN_SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
PIN_REDIRECT = "https://localhost/"

csv.field_size_limit(10_000_000)  # product descriptions can be long
ENV_FILE = ROOT / ".env"


def load_env_file():
    """Read KEY=value lines from .env (created by setup.py). Never overrides real env vars."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env_file()


# ---------- helpers ----------

def env(name, required=True):
    val = os.environ.get(name, "").strip()
    if required and not val:
        sys.exit(f"Missing environment variable: {name}")
    return val


def load_config():
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"posted": [], "next_category": 0}


def save_state(state):
    state["posted"] = state["posted"][-5000:]  # keep the file small
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1))


def to_float(v):
    try:
        return float(str(v).replace("£", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def price_ok(now, rules):
    return rules["min_price"] <= now <= rules["max_price"]


# ---------- eBay ----------

_ebay_token = None


def ebay_token():
    global _ebay_token
    if _ebay_token:
        return _ebay_token
    creds = f"{env('EBAY_CLIENT_ID')}:{env('EBAY_CLIENT_SECRET')}"
    r = requests.post(
        EBAY_TOKEN_URL,
        headers={
            "Authorization": "Basic " + base64.b64encode(creds.encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials",
              "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=30,
    )
    r.raise_for_status()
    _ebay_token = r.json()["access_token"]
    return _ebay_token


def ebay_search(keyword, rules):
    filters = ",".join([
        "buyingOptions:{FIXED_PRICE}",
        f"conditions:{{{rules.get('condition', 'NEW')}}}",
        "itemLocationCountry:GB",
        "deliveryCountry:GB",
        f"price:[{rules['min_price']}..{rules['max_price']}]",
        "priceCurrency:GBP",
    ])
    headers = {
        "Authorization": f"Bearer {ebay_token()}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_GB",
    }
    campaign = env("EPN_CAMPAIGN_ID", required=False)
    if campaign:
        # Makes eBay return itemAffiliateWebUrl = your tracked affiliate link
        headers["X-EBAY-C-ENDUSERCTX"] = (
            f"affiliateCampaignId={campaign},affiliateReferenceId=pinterest")
    r = requests.get(EBAY_SEARCH_URL, headers=headers,
                     params={"q": keyword, "filter": filters, "limit": 100},
                     timeout=30)
    r.raise_for_status()
    return r.json().get("itemSummaries", [])


def ebay_deal(item, rules, posted):
    if item.get("itemId") in posted:
        return None
    mp = item.get("marketingPrice") or {}
    try:
        discount = float(mp.get("discountPercentage", 0))
        was = float(mp["originalPrice"]["value"])
        now = float(item["price"]["value"])
    except (KeyError, TypeError, ValueError):
        return None
    if discount < rules["min_discount_percent"]:
        return None
    seller = item.get("seller") or {}
    try:
        if float(seller.get("feedbackPercentage", 0)) < rules["min_seller_feedback_percent"]:
            return None
        if int(seller.get("feedbackScore", 0)) < rules["min_seller_feedback_score"]:
            return None
    except ValueError:
        return None
    image = (item.get("image") or {}).get("imageUrl")
    if not image:
        return None
    image = re.sub(r"s-l\d+\.", "s-l1600.", image)  # largest version eBay offers
    return {
        "id": item["itemId"],
        "title": item.get("title", "").strip(),
        "now": now, "was": was, "discount": round(discount),
        "image": image,
        "link": item.get("itemAffiliateWebUrl") or item.get("itemWebUrl"),
        "affiliate": bool(item.get("itemAffiliateWebUrl")),
        "store": "eBay UK",
    }


def ebay_candidates(cat, rules, posted):
    keyword = random.choice(cat["keywords"])
    items = ebay_search(keyword, rules)
    deals = [d for d in (ebay_deal(i, rules, posted) for i in items) if d]
    print(f"[{cat['name']}] eBay '{keyword}': {len(items)} items, {len(deals)} deals")
    return deals


# ---------- Awin ----------

_feed_cache = {}


def awin_rows(feed_url):
    """Download an Awin Create-a-Feed CSV (plain or gzipped) and return its rows."""
    if feed_url in _feed_cache:
        return _feed_cache[feed_url]
    r = requests.get(feed_url, timeout=180)
    r.raise_for_status()
    data = r.content
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:5000]
    delim = "|" if sample.count("|") > sample.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    _feed_cache[feed_url] = rows
    return rows


def awin_deal(row, rules, posted):
    pid = row.get("aw_product_id") or row.get("merchant_product_id")
    if not pid or f"awin:{pid}" in posted:
        return None
    stock = str(row.get("in_stock", "1")).strip().lower()
    if stock in ("0", "false", "no", "out of stock"):
        return None
    if row.get("currency", "GBP").strip().upper() not in ("GBP", ""):
        return None
    now = to_float(row.get("search_price") or row.get("store_price"))
    was = max(to_float(row.get("rrp_price")), to_float(row.get("product_price_old")))
    if now <= 0 or was <= now or not price_ok(now, rules):
        return None
    discount = (was - now) / was * 100
    # Ignore silly "discounts" that are usually feed errors.
    if discount < rules["min_discount_percent"] or discount > 85:
        return None
    image = (row.get("large_image") or row.get("merchant_image_url")
             or row.get("aw_image_url") or "").strip()
    link = (row.get("aw_deep_link") or "").strip()
    if not image.startswith("http") or not link.startswith("http"):
        return None
    title = (row.get("product_name") or "").strip()
    brand = (row.get("brand_name") or "").strip()
    if brand and brand.lower() not in title.lower():
        title = f"{brand} {title}"
    return {
        "id": f"awin:{pid}",
        "title": title,
        "now": now, "was": was, "discount": round(discount),
        "image": image, "link": link,
        "affiliate": "awin1.com" in link or "awin" in link,
        "store": (row.get("merchant_name") or "the retailer").strip(),
    }


def awin_candidates(cat, rules, posted):
    feed_url = env(cat["feed_secret"], required=False)
    if not feed_url:
        print(f"[{cat['name']}] skipped: secret {cat['feed_secret']} not set yet")
        return []
    rows = awin_rows(feed_url)
    words = [w.lower() for w in cat.get("include_words", [])]
    blocked = [w.lower() for w in cat.get("exclude_words", [])]
    deals = []
    for row in rows:
        name = (row.get("product_name") or "").lower()
        if words and not any(w in name for w in words):
            continue
        if any(w in name for w in blocked):
            continue
        d = awin_deal(row, rules, posted)
        if d:
            deals.append(d)
    print(f"[{cat['name']}] Awin feed: {len(rows)} products, {len(deals)} deals")
    # Shuffle the top deals so posts vary between retailers and runs.
    deals.sort(key=lambda d: d["discount"], reverse=True)
    top = deals[:30]
    random.shuffle(top)
    return top


# ---------- deal selection ----------

def in_season(cat, today):
    """Seasonal boards only run between active_from and active_until (MM-DD)."""
    start, end = cat.get("active_from"), cat.get("active_until")
    if not start or not end:
        return True
    md = today.strftime("%m-%d")
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end  # window that crosses New Year


def rotation(cfg, today=None):
    """Categories in posting order. A board with weight 3 comes up 3x as often,
    spread evenly through the day rather than back to back."""
    today = today or datetime.date.today()
    active = [c for c in cfg["categories"] if in_season(c, today)]
    entries = []
    for i, c in enumerate(active):
        w = max(1, int(c.get("weight", 1)))
        for k in range(w):
            entries.append(((k + (i + 0.5) / len(active)) / w, i, c))
    entries.sort(key=lambda e: (e[0], e[1]))
    return [c for _, _, c in entries]


def find_deals(cfg, state, wanted):
    posted = set(state["posted"])
    cats = rotation(cfg)
    deals = []
    start = state.get("next_category", 0)
    # Walk the categories in rotation so boards get posts evenly.
    for step in range(len(cats) * 2):
        if len(deals) >= wanted:
            break
        cat = cats[(start + step) % len(cats)]
        rules = {**cfg, **cat}  # category settings override the defaults
        try:
            if cat.get("source", "ebay") == "awin":
                candidates = awin_candidates(cat, rules, posted)
            else:
                candidates = ebay_candidates(cat, rules, posted)
                candidates.sort(key=lambda d: d["discount"], reverse=True)
        except requests.RequestException as e:
            print(f"[{cat['name']}] search failed: {e}")
            continue
        if candidates:
            deal = candidates[0]
            deal["category"] = cat
            deals.append(deal)
            posted.add(deal["id"])
            state["next_category"] = (start + step + 1) % len(cats)
    return deals


# ---------- Pinterest ----------

def pin_base():
    return PIN_SANDBOX if env("PINTEREST_SANDBOX", required=False) == "1" else PIN_LIVE


def pin_basic_auth():
    creds = f"{env('PINTEREST_APP_ID')}:{env('PINTEREST_APP_SECRET')}"
    return "Basic " + base64.b64encode(creds.encode()).decode()


def pin_token():
    direct = env("PINTEREST_ACCESS_TOKEN", required=False)
    if direct:
        return direct
    r = requests.post(
        f"{PIN_LIVE}/oauth/token",
        headers={"Authorization": pin_basic_auth(),
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token",
              "refresh_token": env("PINTEREST_REFRESH_TOKEN")},
        timeout=30,
    )
    if r.status_code != 200:
        sys.exit(f"Pinterest token refresh failed ({r.status_code}): {r.text}\n"
                 "The refresh token may have expired. Run: python dealbot.py --auth")
    return r.json()["access_token"]


def pin_request(method, path, token, **kw):
    r = requests.request(method, pin_base() + path,
                         headers={"Authorization": f"Bearer {token}"},
                         timeout=30, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Pinterest {method} {path} failed ({r.status_code}): {r.text}")
    return r.json() if r.text else {}


def make_pin_text(deal):
    title = f"{deal['discount']}% off: {deal['title']}"
    if len(title) > 100:
        title = title[:97].rstrip() + "..."
    tags = deal["category"].get("hashtags", "#ukdeals")
    desc = (
        f"Now £{deal['now']:.2f} (was £{deal['was']:.2f}) at {deal['store']}, "
        f"save {deal['discount']}%. Price correct when posted and may change. "
        f"#ad This pin contains an affiliate link. {tags}"
    )
    return title, desc[:500]


def post_pin(token, deal):
    title, desc = make_pin_text(deal)
    body = {
        "board_id": deal["category"]["board_id"],
        "title": title,
        "description": desc,
        "link": deal["link"],
        "alt_text": deal["title"][:500],
        "media_source": {"source_type": "image_url", "url": deal["image"]},
    }
    return pin_request("POST", "/pins", token, json=body)


# ---------- commands ----------

def cmd_auth():
    app_id = env("PINTEREST_APP_ID")
    url = "https://www.pinterest.com/oauth/?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": PIN_REDIRECT,
        "response_type": "code", "scope": PIN_SCOPES,
    })
    print("1. Open this link while logged in to your Pinterest business account:\n")
    print(url)
    print("\n2. Click Allow. Your browser will go to a page that fails to load.")
    print("   That's expected. Copy the whole address from the address bar.\n")
    pasted = input("3. Paste it here: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code", [pasted])[0]
    r = requests.post(
        f"{PIN_LIVE}/oauth/token",
        headers={"Authorization": pin_basic_auth(),
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code,
              "redirect_uri": PIN_REDIRECT},
        timeout=30,
    )
    if r.status_code != 200:
        sys.exit(f"Failed ({r.status_code}): {r.text}")
    data = r.json()
    days = int(data.get("refresh_token_expires_in", 0)) // 86400
    print("\nPinterest connected." + (f" (Renew in about {days} days.)" if days else ""))
    return data["refresh_token"]


def existing_boards(token):
    boards, bookmark = {}, None
    while True:
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        page = pin_request("GET", "/boards", token, params=params)
        for b in page.get("items", []):
            boards[b["name"].strip().lower()] = b["id"]
        bookmark = page.get("bookmark")
        if not bookmark:
            return boards


def cmd_list_boards():
    for name, bid in existing_boards(pin_token()).items():
        print(f"{bid}  {name}")


def write_board_ids(ids):
    """Put board IDs into config.yaml in place, keeping all comments."""
    text = CONFIG_FILE.read_text(encoding="utf-8")
    for name, bid in ids.items():
        pattern = re.compile(
            r'(- name: ' + re.escape(name) + r'\s*\n(?:(?!\s*- name:).*\n)*?\s*board_id:\s*)"[^"]*"')
        text, n = pattern.subn(lambda m: m.group(1) + f'"{bid}"', text, count=1)
        if not n:
            print(f"Could not find '{name}' in config.yaml")
    CONFIG_FILE.write_text(text, encoding="utf-8")


def cmd_create_boards(cfg, only=None):
    token = pin_token()
    have = existing_boards(token)
    ids = {}
    for cat in cfg["categories"]:
        if only and cat["name"].lower() != only.lower():
            continue
        bid = have.get(cat["name"].strip().lower())
        if bid:
            print(f"Already exists: {cat['name']}")
        else:
            b = pin_request("POST", "/boards", token, json={
                "name": cat["name"],
                "description": f"Hand-picked {cat['name'].lower()} deals from UK shops, "
                               "checked for real discounts. Contains affiliate links.",
                "privacy": "PUBLIC",
            })
            bid = b["id"]
            print(f"Created: {cat['name']}")
        ids[cat["name"]] = bid
    write_board_ids(ids)
    print("Board IDs saved into config.yaml.")


def cmd_run(cfg, dry_run):
    state = load_state()
    deals = find_deals(cfg, state, cfg.get("pins_per_run", 1))
    if not deals:
        print("No new deals this run.")
        return
    if dry_run:
        for d in deals:
            title, desc = make_pin_text(d)
            print(f"\n--- {d['category']['name']} ---\n{title}\n{desc}\n"
                  f"link: {d['link']}\nimage: {d['image']}\naffiliate link: {d['affiliate']}")
        return
    ready = []
    for d in deals:
        if not d["affiliate"]:
            print(f"Skipping {d['id']}: no affiliate link (check your affiliate IDs).")
        elif d["category"]["board_id"] == "REPLACE_ME":
            print(f"Skipping {d['category']['name']}: set its board_id in config.yaml.")
        else:
            ready.append(d)
    if not ready:
        save_state(state)
        return
    token = pin_token()
    done = []
    for d in ready:
        try:
            pin = post_pin(token, d)
            print(f"Posted pin {pin.get('id')}: {d['title'][:60]}")
            state["posted"].append(d["id"])
            done.append(d)
        except RuntimeError as e:
            print(e)
    save_state(state)
    if done:
        site_builder.add_deals(done)   # gives each deal its #number for videos
        site_builder.build_site()
        print(f"Website updated with {len(done)} new deal(s).")


def cmd_demo(cfg):
    """Post one real deal to Pinterest's sandbox, for the Standard-access video."""
    token = env("PINTEREST_SANDBOX_TOKEN", required=False)
    if not token:
        print("On developers.pinterest.com open your app, find 'Sandbox' and")
        print("click to generate a sandbox access token, then paste it here.")
        token = input("Sandbox token: ").strip()
        with open(ENV_FILE, "a", encoding="utf-8") as f:
            f.write(f"\nPINTEREST_SANDBOX_TOKEN={token}\n")
    os.environ["PINTEREST_SANDBOX"] = "1"
    print("\nStep 1: finding a deal on eBay UK...")
    state = {"posted": [], "next_category": random.randrange(len(cfg["categories"]))}
    ebay_only = {**cfg, "categories": [c for c in cfg["categories"]
                                       if c.get("source", "ebay") == "ebay"]}
    deals = find_deals(ebay_only, state, 1)
    if not deals:
        sys.exit("No deal found this time. Run the demo again.")
    d = deals[0]
    print(f"Found: {d['title']} (£{d['now']:.2f}, was £{d['was']:.2f})")
    print("\nStep 2: creating the pin through the Pinterest API...")
    boards = existing_boards(token)
    bid = boards.get("deal bot demo") or pin_request(
        "POST", "/boards", token, json={"name": "Deal bot demo"})["id"]
    d["category"] = {**d["category"], "board_id": bid}
    pin = post_pin(token, d)
    print(f"\nSuccess. Pinterest created pin {pin.get('id')} on board 'Deal bot demo':")
    print(json.dumps({k: pin.get(k) for k in ("id", "title", "link", "board_id")}, indent=2))


def main():
    p = argparse.ArgumentParser(description="Deal bot")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--auth", action="store_true")
    p.add_argument("--list-boards", action="store_true")
    p.add_argument("--create-boards", action="store_true")
    p.add_argument("--only", help="with --create-boards: just this category")
    p.add_argument("--demo", action="store_true", help="post one pin to Pinterest's sandbox")
    a = p.parse_args()
    cfg = load_config()
    if a.auth:
        print("\nRefresh token (save as PINTEREST_REFRESH_TOKEN):\n" + cmd_auth())
    elif a.list_boards:
        cmd_list_boards()
    elif a.demo:
        cmd_demo(cfg)
    elif a.create_boards:
        cmd_create_boards(cfg, a.only)
    else:
        cmd_run(cfg, a.dry_run)


if __name__ == "__main__":
    main()
