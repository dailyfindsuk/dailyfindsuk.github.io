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
import collections
import csv
import datetime
import gzip
import html
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

# Windows terminals can't always print emoji (🎁): never crash over it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


# ---------- helpers ----------

def env(name, required=True):
    val = os.environ.get(name, "").strip()
    if required and not val:
        sys.exit(f"Missing environment variable: {name}")
    return val


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"posted": [], "next_category": 0}


def save_state(state):
    state["posted"] = state["posted"][-5000:]  # keep the file small
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


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
    if not env("EBAY_CLIENT_ID", required=False):
        print(f"[{cat['name']}] skipped: no eBay keys set")
        return []
    keyword = random.choice(cat["keywords"])
    items = ebay_search(keyword, rules)
    deals = [d for d in (ebay_deal(i, rules, posted) for i in items) if d]
    blocked = [w.lower() for w in cat.get("exclude_words", [])]
    deals = [d for d in deals if not any(w in d["title"].lower() for w in blocked)]
    print(f"[{cat['name']}] eBay '{keyword}': {len(items)} items, {len(deals)} deals")
    return deals


# ---------- Awin ----------

_feed_cache = {}


def awin_rows(feed_url):
    """Download an Awin Create-a-Feed CSV (plain or gzipped) and return its rows."""
    # Never include adult products: Pinterest doesn't allow them.
    feed_url = feed_url.replace("/adultcontent/1", "/adultcontent/0")
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
    if rows and "title" in rows[0] and "advertiser_name" in rows[0]:
        rows = [google_row(r) for r in rows]
    _feed_cache[feed_url] = rows
    return rows


def _money(v):
    """'53.99 GBP' -> (53.99, 'GBP')."""
    m = re.match(r"\s*([\d.,]+)\s*([A-Z]{3})?", v or "")
    if not m:
        return 0.0, ""
    return to_float(m.group(1).replace(",", "")), (m.group(2) or "")


def google_row(r):
    """Translate an Awin 'Google format' feed row into the classic Awin column names
    the rest of the bot uses. In this format a discount is a sale_price below price,
    and price is the shop's own normal price (so it's shown as "was", not "RRP")."""
    price, cur = _money(r.get("price"))
    sale, cur2 = _money(r.get("sale_price"))
    on_sale = 0 < sale < price
    avail = (r.get("availability") or "").lower().replace("_", " ")
    return {
        "aw_product_id": "g" + (r.get("id") or ""),
        "product_name": r.get("title") or "",
        "brand_name": r.get("brand") or "",
        "merchant_name": r.get("advertiser_name") or "",
        "aw_deep_link": r.get("aw_deep_link") or "",
        "merchant_image_url": r.get("image_link") or "",
        "large_image": r.get("lifestyle_image_link") or "",
        # extra photos: the bot picks the sharpest one
        "alternate_image": re.sub(r",\s*(?=https?://)", "|", r.get("additional_image_link") or ""),
        "search_price": str(sale if on_sale else price),
        "product_price_old": str(price) if on_sale else "",
        "rrp_price": "",
        "currency": cur2 if on_sale and cur2 else (cur or "GBP"),
        "in_stock": "1" if avail in ("in stock", "preorder", "backorder") else "0",
    }


def clean_title(title):
    """Tidy shop product names: drop stock codes and barcodes ("- 821971 - 5060388017149")
    and repeated colour parts ("Cervia - Cervia Dark Grey")."""
    if re.search("[\u00c2\u00c3\u00e2][\u0080-\u00bf\u20ac\u201a-\u2122]", title):
        try:  # repair text that was double-encoded by the shop ("Bedsâ„¢" -> "Beds™")
            title = title.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    title = title.replace("™", "").replace("®", "")
    parts = [p.strip() for p in re.split(r"\s+-\s+", title.strip()) if p.strip()]
    keep = []
    for p in parts:
        if re.fullmatch(r"[\d\s/]{4,}", p):          # pure number: SKU / EAN
            continue
        if keep and (p.lower() in keep[-1].lower() or keep[-1].lower() in p.lower()):
            if len(p) > len(keep[-1]):
                keep[-1] = p                             # keep the fuller version
            continue
        keep.append(p)
    return " - ".join(keep) or title.strip()


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
    rrp, old = to_float(row.get("rrp_price")), to_float(row.get("product_price_old"))
    was = max(rrp, old)
    # UK pricing rules: say "was" only for the shop's own previous price; a
    # recommended retail price must be called "RRP".
    ref = "was" if old and old >= rrp else "RRP"
    if now <= 0 or not price_ok(now, rules):
        return None
    discount = (was - now) / was * 100 if was > now else 0
    if discount == 0 or discount < rules["min_discount_percent"]:
        # Gift boards may post a full-price gift (never shown as a discount).
        if not rules.get("full_price_ok"):
            return None
        was, discount = now, 0
    # Ignore silly "discounts" that are usually feed errors.
    if discount > 85:
        return None
    images = row_images(row)
    image = images[0] if images else ""
    link = (row.get("aw_deep_link") or "").strip()
    if not image.startswith("http") or not link.startswith("http"):
        return None
    # Feeds sometimes contain HTML codes such as "Ralph&#039;s" instead of "Ralph's".
    title = clean_title(html.unescape(html.unescape(row.get("product_name") or "")))
    brand = html.unescape(row.get("brand_name") or "").strip()
    if brand and brand.lower() not in title.lower():
        title = f"{brand} {title}"
    return {
        "id": f"awin:{pid}",
        "title": title,
        "now": now, "was": was, "ref": ref, "discount": round(discount),
        "image": image, "images": images, "link": link,
        "affiliate": "awin1.com" in link or "awin" in link,
        "store": (row.get("merchant_name") or "the retailer").strip(),
    }


# Every Awin feed link the bot knows about. Each category reads all of them (each feed
# is downloaded once per run) and keeps only products from its own shops.
ALL_FEED_SECRETS = ["AWIN_FEED_ALL", "AWIN_FEED_GOOGLE", "AWIN_FEED_BEAUTY", "AWIN_FEED_KIDS"]


def word_re(words):
    """Match whole words/phrases only, so 'men' doesn't match 'women'."""
    if not words:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(w.lower()) for w in words) + r")\b")


def feed_secrets(cat):
    fs = cat.get("feed_secret")
    if fs:
        return [fs] if isinstance(fs, str) else list(fs)
    # The ALL-shops link replaces the older single-shop links (Scentsational is in it,
    # and GamingKit has no discounts), so don't download those twice.
    # AWIN_FEED_GOOGLE holds the shops that only offer Awin's newer "Google format" feed.
    if env("AWIN_FEED_ALL", required=False):
        return ["AWIN_FEED_ALL", "AWIN_FEED_GOOGLE", "AWIN_FEED_KIDS"]
    return ["AWIN_FEED_BEAUTY", "AWIN_FEED_GOOGLE", "AWIN_FEED_KIDS"]


def awin_all_rows(cat):
    rows, seen, used = [], set(), []
    for secret in feed_secrets(cat):
        url = env(secret, required=False)
        if not url:
            continue
        used.append(secret)
        for row in awin_rows(url):
            pid = row.get("aw_product_id") or row.get("merchant_product_id")
            if pid in seen:
                continue
            seen.add(pid)
            rows.append(row)
    return rows, used


def drop_fake_rrp_shops(deals, label):
    """If most of a shop's 'deals' share one discount, its RRPs are a fixed markup,
    not real discounts (e.g. every item exactly 28% off). Drop that shop."""
    by_shop = collections.defaultdict(list)
    for d in deals:
        if d["discount"] == 0:
            continue  # full-price gifts aren't claiming a discount
        by_shop[d["store"]].append(d)
    keep = []
    for shop, items in by_shop.items():
        if len(items) >= 30:
            common, count = collections.Counter(d["discount"] for d in items).most_common(1)[0]
            if count / len(items) > 0.6:
                print(f"[{label}] skipped {shop}: {count} of {len(items)} 'deals' are all "
                      f"{common}% off, which looks like a made-up RRP")
                continue
        keep.extend(items)
    return keep + [d for d in deals if d["discount"] == 0]


# Shops put a "No image available" picture on products without a photo. The same
# picture is then used by many different products, so an image URL shared by 6 or
# more products is treated as a placeholder and those products are skipped.
PLACEHOLDER_WORDS = ("noimage", "no_image", "no-image", "placeholder", "image-coming",
                     "imagecomingsoon", "coming-soon", "comingsoon", "image_not", "notavailable",
                     "not-available", "default-image", "missing-image")
_shared_cache = {}


def row_image(row):
    img = (row.get("large_image") or row.get("merchant_image_url") or row.get("aw_image_url") or "")
    return img.split("|")[0].strip()


IMAGE_FIELDS = ("large_image", "merchant_image_url", "aw_image_url", "alternate_image",
                "alternate_image_two", "alternate_image_three", "merchant_thumb_url", "aw_thumb_url")


def row_images(row):
    """Every product photo the feed gives, best fields first, no duplicates.
    Some shops (e.g. Stormforce) list several images joined with "|"."""
    out = []
    for f in IMAGE_FIELDS:
        for u in (row.get(f) or "").split("|"):
            u = u.strip()
            if u.startswith("http") and u not in out:
                out.append(u)
    return out


def bigger_versions(url):
    """Shops often link a thumbnail when a bigger copy of the same photo exists at a
    slightly different address. Try the usual patterns (the original comes last)."""
    tries = []
    def add(u):
        if u != url and u not in tries:
            tries.append(u)
    # Size folders such as /570x570/ or /thumbs/ in the path
    add(re.sub(r"/\d{2,4}x\d{2,4}/", "/1200x1200/", url))
    add(re.sub(r"/\d{2,4}x\d{2,4}/", "/", url))
    add(re.sub(r"/(thumbs?|thumbnails?|small|medium|med|sm)/", "/large/", url, flags=re.I))
    add(re.sub(r"/(thumbs?|thumbnails?|small|medium|med|sm)/", "/", url, flags=re.I))
    # Size endings such as photo_200x200.jpg, photo-300x300.jpg (Shopify, WordPress)
    add(re.sub(r"[_-]\d{2,4}x\d{0,4}(@2x)?(?=\.(jpe?g|png|webp)\b)", "", url, flags=re.I))
    # Size codes such as 12345_ml.jpg, _s.jpg, _small.jpg
    for big in ("_xl", "_xxl", "_l", "_large", "_big"):
        add(re.sub(r"_(s|m|ml|sm|small|med|medium|thumb|t)(?=\.(jpe?g|png|webp)\b)", big, url, flags=re.I))
    # Size settings in the address: ?w=300, &width=200, &h=, &size=
    p = urllib.parse.urlsplit(url)
    if p.query:
        q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)]
        size_keys = {"w", "h", "width", "height", "size", "resize", "fit", "sw", "sh", "wid", "hei"}
        if any(k.lower() in size_keys for k, _ in q):
            add(urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(
                [(k, "1500" if k.lower() in ("w", "width", "wid", "sw") else v) for k, v in q
                 if k.lower() not in ("h", "height", "hei", "sh", "size", "resize", "fit")]))))
            add(urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(
                [(k, v) for k, v in q if k.lower() not in size_keys]))))
    return tries + [url]


GOOD_IMAGE_PX = 700    # this big or more: sharp in pins and 1440p videos
MIN_IMAGE_PX = 450     # smaller than this looks blurry once blown up, so it's skipped
_size_cache = {}


IMAGE_CHECK_SECONDS = 75   # total time per run spent checking photos, so a run never stalls
_check_started = []


def _check_time_left():
    import time
    if not _check_started:
        _check_started.append(time.monotonic())
    return IMAGE_CHECK_SECONDS - (time.monotonic() - _check_started[0])


def image_size(url):
    """Width and height of a photo (0, 0 if it can't be loaded). Reads only the start
    of the file (the size is stored there) and gives up quickly on slow websites."""
    if url not in _size_cache:
        size = (0, 0)
        try:
            from PIL import ImageFile
            with requests.get(url, timeout=(4, 5), stream=True,
                              headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status_code == 200 and r.headers.get("content-type", "image").startswith("image"):
                    parser, got = ImageFile.Parser(), 0
                    for chunk in r.iter_content(16384):
                        parser.feed(chunk)
                        got += len(chunk)
                        if parser.image or got > 512000:
                            break
                    if parser.image:
                        size = parser.image.size
        except Exception:
            pass
        _size_cache[url] = size
    return _size_cache[url]


def best_image(deal):
    """Pick the sharpest photo we can find for a deal. Returns (url, longest side).
    Tries at most 6 addresses per deal; if the run's photo-check time is used up,
    the feed's own photo is accepted unchecked rather than holding up the run."""
    if _check_time_left() <= 0:
        return deal["image"], MIN_IMAGE_PX
    best, best_px, tries = deal["image"], 0, 0
    for src in (deal.get("images") or [deal["image"]])[:3]:
        for u in [src] + bigger_versions(src)[:-1]:   # its own photo first, then bigger copies
            if tries >= 6 or _check_time_left() <= 0:
                return best, best_px
            tries += 1
            px = max(image_size(u))   # the photo is fitted into a square by its longest side
            if px > best_px:
                best, best_px = u, px
            if best_px >= GOOD_IMAGE_PX:
                return best, best_px
    return best, best_px


def shared_images(rows):
    key = id(rows)
    if key not in _shared_cache:
        seen = collections.defaultdict(set)
        for r in rows:
            img = row_image(r)
            if img:
                seen[img].add(r.get("aw_product_id") or r.get("product_name"))
        _shared_cache.clear()
        _shared_cache[key] = {img for img, ids in seen.items() if len(ids) >= 6}
    return _shared_cache[key]


def bad_image(url, shared=()):
    u = (url or "").lower()
    return url in shared or any(w in urllib.parse.unquote(u) for w in PLACEHOLDER_WORDS)


def awin_candidates(cat, rules, posted):
    rows, used = awin_all_rows(cat)
    if not used:
        print(f"[{cat['name']}] skipped: no Awin feed links set yet")
        return []
    words = word_re(cat.get("include_words"))
    blocked = word_re(cat.get("exclude_words"))
    shops = word_re(cat.get("merchants"))
    # include_words_for: {Shop: [words]} applies a word filter to that shop only,
    # e.g. Rarewaves sells music and books too, but Stormforce is all gaming.
    shop_words = [(word_re([m]), word_re(w)) for m, w in (cat.get("include_words_for") or {}).items()]
    shared = shared_images(rows)
    deals = []
    for row in rows:
        shop = (row.get("merchant_name") or "").lower()
        if shops and not shops.search(shop):
            continue
        name = (row.get("product_name") or "").lower()
        if words and not words.search(name):
            continue
        if any(m.search(shop) and not w.search(name) for m, w in shop_words):
            continue
        if blocked and blocked.search(name):
            continue
        d = awin_deal(row, rules, posted)
        if d and not bad_image(d["image"], shared):
            deals.append(d)
    deals = drop_fake_rrp_shops(deals, cat["name"])
    print(f"[{cat['name']}] Awin: {len(rows)} products checked, {len(deals)} deals")
    # Shuffle the top deals so posts vary between retailers and runs.
    deals.sort(key=lambda d: d["discount"], reverse=True)
    top = deals[:30]
    random.shuffle(top)
    return top


# ---------- deal selection ----------

def easter(year):
    """Easter Sunday (Gregorian), used for the UK's Mothering Sunday."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return datetime.date(year, month, day)


def season_day(name, year):
    if name == "mothers_day":   # UK Mothering Sunday: 3 weeks before Easter
        return easter(year) - datetime.timedelta(days=21)
    if name == "fathers_day":   # third Sunday in June
        d = datetime.date(year, 6, 1)
        return d + datetime.timedelta(days=(6 - d.weekday()) % 7 + 14)
    if name == "black_friday":  # Friday after the fourth Thursday in November
        d = datetime.date(year, 11, 1)
        return d + datetime.timedelta(days=(3 - d.weekday()) % 7 + 22)
    raise ValueError(f"unknown season {name}")


def in_season(cat, today):
    """Seasonal boards only run in their window. Either fixed dates
    (active_from / active_until as MM-DD) or a named UK season that moves each year
    (season: mothers_day / fathers_day, starting season_lead_days before the day)."""
    if cat.get("season"):
        day = season_day(cat["season"], today.year)
        lead = int(cat.get("season_lead_days", 35))
        return day - datetime.timedelta(days=lead) <= today <= day
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
        deal = None
        for c in candidates[:8]:   # skip deals whose only photo is a small, blurry one
            url, px = best_image(c)
            if px >= MIN_IMAGE_PX:
                c["image"] = url
                deal = c
                break
            print(f"[{cat['name']}] skipped (photo only {px}px): {c['title'][:50]}")
        if deal:
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


FOR_HIM = word_re(["men", "mens", "men's", "him", "his", "homme", "pour homme", "boyfriend",
                   "husband", "dad", "father", "aftershave", "beard", "shaving", "gentleman"])
FOR_HER = word_re(["women", "womens", "women's", "her", "ladies", "femme", "pour femme",
                   "girlfriend", "wife", "mum", "mother", "mom"])
FOR_KIDS = word_re(["kids", "kid's", "children", "childrens", "children's", "child", "baby",
                    "toddler", "boys", "girls", "junior"])
PRICE_BANDS = [10, 15, 20, 30, 50, 75, 100, 150, 200]


def gift_season(today):
    """1 Nov to Christmas Eve: frame deals as gifts."""
    return datetime.date(today.year, 11, 1) <= today <= datetime.date(today.year, 12, 24)


def black_friday_week(today):
    bf = season_day("black_friday", today.year)
    return bf - datetime.timedelta(days=7) <= today <= bf + datetime.timedelta(days=3)


def gift_for(deal):
    """'for him' / 'for her' / 'for kids' from the product title, else the board's default."""
    t = deal["title"].lower()
    him, her = FOR_HIM.search(t), FOR_HER.search(t)
    if him and not her:
        return "for him"
    if her and not him:
        return "for her"
    if FOR_KIDS.search(t):
        return "for kids"
    return deal["category"].get("gift_for", "")


def price_band(now):
    for band in PRICE_BANDS:
        if now <= band:
            return f"under £{band}"
    return ""


def make_pin_text(deal, today=None):
    today = today or datetime.date.today()
    cat = deal["category"]
    rrp = deal.get("ref") == "RRP"
    off = (f"{deal['discount']}% off" + (" RRP" if rrp else "")) if deal["discount"] else ""
    giftable = cat.get("gift") or (gift_season(today) and cat.get("giftable", True)) or not off
    if off and black_friday_week(today):
        # Black Friday week: lead with the event people are searching for.
        title = f"Black Friday · {off}: {deal['title']}"
    elif giftable:
        # "Gift for him under £30 · 40% off: ..." gets far more engagement than a bare product.
        who, band = gift_for(deal), price_band(deal["now"])
        lead = " ".join(x for x in ("🎁 Gift" if off else "🎁 Gift idea", who, band) if x)
        title = f"{lead} · {off}: {deal['title']}" if off else f"{lead}: {deal['title']}"
    else:
        title = f"{off}: {deal['title']}"
    if len(title) > 100:
        title = title[:97].rstrip() + "..."
    tags = cat.get("hashtags", "#ukdeals")
    gift_line = ""
    if giftable:
        who, band = gift_for(deal), price_band(deal["now"])
        gift_line = " ".join(x for x in ("Great gift idea", who, band) if x) + ". "
    price = (f"Now £{deal['now']:.2f} ({deal.get('ref', 'was')} £{deal['was']:.2f}) at {deal['store']}, "
             f"save {deal['discount']}%{' on RRP' if rrp else ''}. ") if off else f"£{deal['now']:.2f} at {deal['store']}. "
    desc = (
        f"{price}{gift_line}Price correct when posted and may change. "
        f"#ad This pin contains an affiliate link. {tags}"
    )
    return title, desc[:500]


def branded_media(deal, today=None):
    """Make the tall 2:3 branded pin image. Returns a Pinterest media_source,
    or None if it can't be made (then the plain product photo is used)."""
    if os.environ.get("PIN_STYLE", "branded") != "branded":
        return None
    try:
        import tempfile
        import pin_image
        today = today or datetime.date.today()
        who = gift_for(deal) if not deal["discount"] else ""
        with tempfile.TemporaryDirectory() as tmp:
            path = pin_image.make_pin_image(deal, Path(tmp) / "pin.jpg",
                                            black_friday=black_friday_week(today), who=who)
            data = base64.b64encode(path.read_bytes()).decode()
        return {"source_type": "image_base64", "content_type": "image/jpeg", "data": data}
    except Exception as e:  # never lose a pin over the image
        print(f"Branded image failed ({e}); using the plain product photo.")
        return None


def post_pin(token, deal):
    title, desc = make_pin_text(deal)
    media = branded_media(deal) or {"source_type": "image_url", "url": deal["image"]}
    body = {
        "board_id": deal["category"]["board_id"],
        "title": title,
        "description": desc,
        "link": deal["link"],
        "alt_text": deal["title"][:500],
        "media_source": media,
    }
    try:
        return pin_request("POST", "/pins", token, json=body)
    except RuntimeError as e:
        if media.get("source_type") != "image_base64":
            raise
        print(f"Branded pin was refused ({e}); retrying with the plain photo.")
        body["media_source"] = {"source_type": "image_url", "url": deal["image"]}
        return pin_request("POST", "/pins", token, json=body)


# ---------- commands ----------

def oauth_connect():
    """Full Pinterest OAuth flow. Returns the token data (access + refresh token)."""
    import webbrowser
    app_id = env("PINTEREST_APP_ID")
    url = "https://www.pinterest.com/oauth/?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": PIN_REDIRECT,
        "response_type": "code", "scope": PIN_SCOPES,
    })
    print("Opening Pinterest's permission page in your browser:\n")
    print(url)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("\n1. If it didn't open, copy the link above into your browser.")
    print("2. Check you're logged in as Daily Finds UK, then click 'Give access'.")
    print("3. The browser goes to a page that fails to load. That's expected.")
    print("   Copy the whole address from the address bar.\n")
    pasted = input("4. Paste it here: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code", [pasted])[0]
    print("\nSwapping the one-time code for an access token...")
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
    print(f"Access granted. Scopes: {data.get('scope', PIN_SCOPES)}")
    return data


def save_env_value(key, value):
    lines = []
    if ENV_FILE.exists():
        lines = [l for l in ENV_FILE.read_text(encoding="utf-8").splitlines()
                 if not l.startswith(key + "=")]
    lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def cmd_auth():
    data = oauth_connect()
    days = int(data.get("refresh_token_expires_in", 0)) // 86400
    print("\nPinterest connected." + (f" (Renew in about {days} days.)" if days else ""))
    return data["refresh_token"]


def board_key(name):
    """Compare board names loosely: Pinterest may return '&' as '&amp;'."""
    import html
    return " ".join(html.unescape(html.unescape(name)).lower().split())


def existing_boards(token):
    boards, bookmark = {}, None
    while True:
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        page = pin_request("GET", "/boards", token, params=params)
        for b in page.get("items", []):
            boards[board_key(b["name"])] = b["id"]
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
        bid = have.get(board_key(cat["name"]))
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


# Safety net: GitHub sometimes skips scheduled runs. The workflow also runs at backup
# times; a scheduled run only posts if nothing was posted in the last MIN_GAP_HOURS,
# so a missed slot is caught up without doubling the number of posts.
MIN_GAP_HOURS = 2.75


def too_soon(state):
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return False   # manual runs and local runs always post
    last = state.get("last_post")
    if not last:
        return False
    try:
        then = datetime.datetime.fromisoformat(last)
    except ValueError:
        return False
    hours = (datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() / 3600
    if hours < MIN_GAP_HOURS:
        print(f"Posted {hours:.1f} hours ago, so this backup slot is skipped.")
        return True
    return False


def cmd_run(cfg, dry_run, count=None):
    state = load_state()
    if not dry_run and too_soon(state):
        return
    deals = find_deals(cfg, state, count or cfg.get("pins_per_run", 1))
    if not deals:
        print("No new deals this run.")
        return
    if dry_run:
        preview = ROOT / "videos" / "pin-preview"
        preview.mkdir(parents=True, exist_ok=True)
        for old_file in preview.glob("*.jpg"):
            old_file.unlink()
        for i, d in enumerate(deals, 1):
            title, desc = make_pin_text(d)
            print(f"\n--- {d['category']['name']} ---\n{title}\n{desc}\n"
                  f"link: {d['link']}\nimage: {d['image']}\naffiliate link: {d['affiliate']}")
            try:
                import pin_image
                who = gift_for(d) if not d["discount"] else ""
                pin_image.make_pin_image(d, preview / f"pin-{i:02d}.jpg",
                                         black_friday=black_friday_week(datetime.date.today()), who=who)
            except Exception as e:
                print(f"(preview image failed: {e})")
        print(f"\nPreview pin images saved in {preview}")
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
    number = site_builder.next_number()
    for d in ready:
        d["number"] = number   # shown on the pin image and the website
        number += 1
        try:
            pin = post_pin(token, d)
            print(f"Posted pin {pin.get('id')}: {d['title'][:60]}")
            state["posted"].append(d["id"])
            state["last_post"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            done.append(d)
        except RuntimeError as e:
            print(e)
    save_state(state)
    if done:
        site_builder.add_deals(done)   # gives each deal its #number for videos
        site_builder.build_site()
        print(f"Website updated with {len(done)} new deal(s).")
        post_videos(done[0])


def youtube_text(deal):
    """Title and description for a YouTube Short (descriptions may carry the link)."""
    num = f" #{deal['number']}" if deal.get("number") else ""
    if deal["discount"]:
        head = f"{deal['discount']}% off {deal['title']}"
        price = f"Now £{deal['now']:.2f} ({deal.get('ref', 'was')} £{deal['was']:.2f}) at {deal['store']}."
    else:
        head = f"Gift idea: {deal['title']}"
        price = f"£{deal['now']:.2f} at {deal['store']}."
    title = head[:88].rstrip(" ,.-") + " #Shorts"
    desc = (f"#ad Deal{num}: {deal['title']}\n{price}\n\n"
            f"Shop it here: {deal['link']}\n\n"
            "All our deals: https://dailyfindsuk.github.io\n"
            "Prices can change at any time, so check before you buy. "
            "We may earn a commission if you buy through the link, at no extra cost to you.\n\n"
            "#ukdeals #dealsuk #dailyfindsuk")
    tags = ["uk deals", "deals uk", "daily finds uk", deal["category"]["name"].lower(), deal["store"]]
    return title, desc, tags


def instagram_caption(deal):
    num = f"#{deal['number']}" if deal.get("number") else ""
    if deal["discount"]:
        head = f"{deal['discount']}% off: {deal['title']}"
        price = f"Now £{deal['now']:.2f} ({deal.get('ref', 'was')} £{deal['was']:.2f}) at {deal['store']}."
    else:
        head = f"🎁 Gift idea: {deal['title']}"
        price = f"£{deal['now']:.2f} at {deal['store']}."
    # Instagram allows at most 5 hashtags: the board's 3 topic tags + 2 of ours.
    tags = [t for t in deal["category"].get("hashtags", "").split() if t.startswith("#")]
    tags = list(dict.fromkeys(tags + ["#ukdeals", "#dailyfindsuk"]))[:5]
    # "Ad" up front (UK ad rules) without using one of the 5 hashtag slots.
    return (f"Ad · {head}\n{price}\n\n"
            f"👉 Link in bio: search deal {num} on our site.\n"
            "Prices can change, so check before you buy. We may earn a commission.\n\n"
            + " ".join(tags))


def post_videos(deal):
    """One video per run, shared as a YouTube Short and an Instagram Reel.
    Each is skipped quietly when not connected; failures never stop the pins."""
    yt = bool(os.environ.get("YT_REFRESH_TOKEN"))
    ig = bool(os.environ.get("IG_ACCESS_TOKEN"))
    if not (yt or ig):
        return
    try:
        import video_maker
        path = ROOT / "videos" / f"short-{deal.get('number', 'deal')}.mp4"
        video_maker.make_video(deal, path)
    except Exception as e:
        print(f"Video skipped: {e}")
        return
    if yt:
        try:
            import youtube
            title, desc, tags = youtube_text(deal)
            print(f"Uploaded YouTube Short {youtube.upload_short(path, title, desc, tags)}: {title}")
        except Exception as e:
            print(f"YouTube Short skipped: {e}")
    if ig:
        try:
            import instagram
            days = instagram.refresh()
            print(f"Posted Instagram Reel {instagram.post_reel(path, instagram_caption(deal))}"
                  + (f" (token good for {days} days)" if days else ""))
        except Exception as e:
            print(f"Instagram Reel skipped: {e}")


def cmd_demo(cfg):
    """Screen-recorded demo for Pinterest's Standard-access review:
    full OAuth flow, then a real pin created through the v5 API and opened on Pinterest."""
    import time
    import webbrowser
    def usable(c):
        if c.get("source", "ebay") == "awin":
            return any(env(x, required=False) for x in feed_secrets(c))
        return bool(env("EBAY_CLIENT_ID", required=False))
    cats = [c for c in cfg["categories"] if usable(c)]
    if not cats:
        sys.exit("No deal source set up yet. Add an Awin feed link (run setup.bat) first.")

    print("=" * 60)
    print("Daily Finds UK Deal Bot: Pinterest API demo")
    print("=" * 60)
    print("\nSTEP 1 of 4: Connect the Daily Finds UK Pinterest account (OAuth)\n")
    data = oauth_connect()
    token = data["access_token"]
    if data.get("refresh_token"):
        save_env_value("PINTEREST_REFRESH_TOKEN", data["refresh_token"])
    me = pin_request("GET", "/user_account", token)
    print(f"Connected to Pinterest as @{me.get('username')} "
          f"({me.get('account_type', 'account')})")

    print("\nSTEP 2 of 4: Find a real deal from our Awin retailer feeds\n")
    state = {"posted": [], "next_category": random.randrange(len(cats))}
    deals = find_deals({**cfg, "categories": cats, "active_from": None}, state, 1)
    if not deals:
        sys.exit("No deal found this time. Run the demo again.")
    d = deals[0]
    print(f"\nFound: {d['title']}")
    print(f"  Now £{d['now']:.2f}, {d.get('ref', 'was')} £{d['was']:.2f} ({d['discount']}% off) at {d['store']}")

    print("\nSTEP 3 of 4: Create the pin with the Pinterest API (POST /v5/pins)\n")
    boards = existing_boards(token)
    print("Boards on the connected account (GET /v5/boards):")
    for name in boards:
        print(f"  - {name}")
    # Trial apps may only create pins in Pinterest's API sandbox.
    os.environ["PINTEREST_SANDBOX"] = "1"
    print("\nThis app has Trial access, so the pin is created in Pinterest's API sandbox")
    print("(https://api-sandbox.pinterest.com). With Standard access it goes to the live board.\n")
    sb_token, sb_boards = None, None
    for cand in (token, env("PINTEREST_SANDBOX_TOKEN", required=False)):
        if not cand:
            continue
        try:
            sb_boards, sb_token = existing_boards(cand), cand
            break
        except RuntimeError:
            pass
    while sb_token is None:
        print("Pinterest needs a fresh Sandbox token: on developers.pinterest.com,")
        print("your app > Manage > Generate access tokens > tick Sandbox > Generate token.")
        cand = input("Sandbox token: ").strip()
        try:
            sb_boards, sb_token = existing_boards(cand), cand
            save_env_value("PINTEREST_SANDBOX_TOKEN", cand)
        except RuntimeError as e:
            print(f"That token didn't work: {e}\n")
    name = d["category"]["name"]
    bid = sb_boards.get(board_key(name))
    if not bid:
        try:
            bid = pin_request("POST", "/boards", sb_token, json={"name": name})["id"]
        except RuntimeError:
            # A board by that name exists but wasn't matched: re-read, else use a demo board.
            sb_boards = existing_boards(sb_token)
            bid = sb_boards.get(board_key(name))
            if not bid:
                name = f"{name} demo {datetime.datetime.now():%H%M%S}"
                bid = pin_request("POST", "/boards", sb_token, json={"name": name})["id"]
    d["category"] = {**d["category"], "board_id": bid}
    title, desc = make_pin_text(d)
    print(f"  Board: {name}")
    print(f"  Title: {title}")
    print(f"  Description: {desc}")
    print(f"  Link: {d['link'][:80]}...")
    print(f"  Image: {d['image'][:80]}")
    pin = post_pin(sb_token, d)
    print(f"\nPinterest created pin {pin.get('id')}.")

    print("\nSTEP 4 of 4: Read the new pin back from Pinterest (GET /v5/pins/{id})\n")
    got = pin_request("GET", f"/pins/{pin.get('id')}", sb_token)
    print(json.dumps({k: got.get(k) for k in
                      ("id", "board_id", "title", "description", "link", "created_at")},
                     indent=2, ensure_ascii=False))
    time.sleep(2)
    try:
        webbrowser.open(d["image"])
        webbrowser.open(f"https://www.pinterest.co.uk/{me.get('username')}/")
    except Exception:
        pass
    print("\nDone. In normal use the bot repeats steps 2 and 3 a few times a day,")
    print("using the saved refresh token instead of asking for access again.")


def main():
    p = argparse.ArgumentParser(description="Deal bot")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--count", type=int, help="with --dry-run: how many example pins to show")
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
        cmd_run(cfg, a.dry_run, a.count if a.dry_run else None)


if __name__ == "__main__":
    main()
