"""
Builds the Daily Finds UK website (served free by GitHub Pages from the docs/ folder).

The bot calls add_deals() after posting, then build_site(). Pages:
  docs/index.html    today's deals: the "link in bio" page for Instagram/YouTube
  docs/about.html    who we are + affiliate disclosure
  docs/privacy.html  privacy policy (needed by Pinterest, Meta and Google apps)
Every deal gets a short number (e.g. #124) so a Reel can say "deal #124, link in bio"
and viewers can type that number into the site's search box.
"""

import datetime
import html
import json
from pathlib import Path

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
DEALS_FILE = DOCS / "deals.json"
KEEP = 150          # deals listed on the site
FRESH_DAYS = 14     # older deals drop off (prices change)

SITE_NAME = "Daily Finds UK"
CONTACT = "dailyfindsukme21@gmail.com"
PINTEREST = "https://www.pinterest.com/dailyfinds_uk"

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800'
         '&family=Source+Sans+3:wght@400;600;700&display=swap">')

CSS = """
/* Layout: sticky slim header, filter chips, responsive card grid; price tag motif for discounts. */
:root{
  --bg:#F3F6F4;--surface:#FFFFFF;--fg:#14201C;--muted:#5A6964;--line:#DCE4E0;
  --brand:#0E6B5C;--brand-ink:#FFFFFF;--gold:#F4B23E;--gold-ink:#3A2600;--was:#8A9792;
  --display:"Bricolage Grotesque","Segoe UI",system-ui,sans-serif;
  --body:"Source Sans 3","Segoe UI",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0F1614;--surface:#18211E;--fg:#E7EDEA;--muted:#9AA9A3;--line:#2B3733;
  --brand:#4FC2A9;--brand-ink:#0B1B17;--gold:#F4B23E;--gold-ink:#3A2600;--was:#7D8A85;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0F1614;--surface:#18211E;--fg:#E7EDEA;--muted:#9AA9A3;--line:#2B3733;
  --brand:#4FC2A9;--brand-ink:#0B1B17;--gold:#F4B23E;--gold-ink:#3A2600;--was:#7D8A85;color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 var(--body)}
a{color:var(--brand)}
.wrap{max-width:1120px;margin:0 auto;padding-inline:16px}
header.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);
  border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-block:10px}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--fg)}
.brand img{width:36px;height:36px;border-radius:50%}
.brand b{font:800 20px/1 var(--display);letter-spacing:-.01em}
nav.links{display:flex;gap:16px;font-weight:600;font-size:15px}
nav.links a{color:var(--muted);text-decoration:none}
nav.links a:hover,nav.links a:focus-visible{color:var(--fg)}
.hero{padding-block:28px 8px;display:grid;gap:8px}
.hero h1{font:800 clamp(30px,6vw,46px)/1.05 var(--display);margin:0;letter-spacing:-.02em;text-wrap:balance}
.hero p{margin:0;color:var(--muted);max-width:60ch}
.disclose{font-size:14px;color:var(--muted)}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding-block:16px}
.chip{font:600 14px var(--body);border:1px solid var(--line);background:var(--surface);color:var(--fg);
  border-radius:99px;padding:6px 14px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--brand);color:var(--brand-ink);border-color:var(--brand)}
.chip:focus-visible,.search:focus-visible,.btn:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
.search{flex:1 1 220px;min-width:0;font:16px var(--body);padding:8px 14px;border-radius:99px;
  border:1px solid var(--line);background:var(--surface);color:var(--fg)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px;padding-block:4px 40px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden;
  display:flex;flex-direction:column;min-width:0}
.pic{position:relative;aspect-ratio:1/1;background:#fff;max-width:100%}
.pic img{width:100%;height:100%;object-fit:contain;display:block}
.tag{position:absolute;top:10px;left:10px;background:var(--gold);color:var(--gold-ink);
  font:800 15px/1 var(--display);padding:7px 10px 7px 16px;
  clip-path:polygon(9px 0,100% 0,100% 100%,9px 100%,0 50%)}
.num{position:absolute;top:10px;right:10px;background:rgba(20,32,28,.78);color:#fff;
  font:700 12px/1 var(--body);padding:5px 8px;border-radius:99px;font-variant-numeric:tabular-nums}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}
.cat{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.title{font-weight:600;line-height:1.3;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.price{display:flex;align-items:baseline;gap:8px;font-variant-numeric:tabular-nums;margin-top:auto}
.now{font:800 22px/1 var(--display)}
.was{color:var(--was);text-decoration:line-through}
.meta{font-size:13px;color:var(--muted)}
.btn{display:block;text-align:center;background:var(--brand);color:var(--brand-ink);text-decoration:none;
  font-weight:700;padding:10px;border-radius:10px;margin-top:6px}
.empty{padding:40px 0;color:var(--muted);text-align:center}
.page{max-width:720px;padding-block:28px 56px;display:grid;gap:22px}
.page h1{font:800 clamp(28px,5vw,40px)/1.1 var(--display);margin:0}
.page h2{font:700 20px var(--display);margin:0;color:var(--brand)}
.page section{display:grid;gap:8px;border-top:1px solid var(--line);padding-top:18px}
.page p,.page ul{margin:0}
footer{border-top:1px solid var(--line);padding-block:20px 32px;color:var(--muted);font-size:14px}
footer .wrap{display:flex;flex-wrap:wrap;gap:8px 20px;justify-content:space-between}
@media (max-width:560px){nav.links{gap:12px;font-size:14px}.brand b{font-size:17px}
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.body{padding:10px}.now{font-size:19px}
  .was{font-size:14px}.btn{padding:8px;font-size:14px}.tag{font-size:13px}.title{font-size:14px}}
"""


def esc(s):
    return html.escape(str(s or ""), quote=True)


def head(title, desc):
    return (f'<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">'
            f'<link rel="icon" href="logo.png">{FONTS}<style>{CSS}</style></head><body>'
            f'<header class="top"><div class="wrap">'
            f'<a class="brand" href="index.html"><img src="logo.png" alt=""><b>{SITE_NAME}</b></a>'
            f'<nav class="links"><a href="index.html">Deals</a><a href="about.html">About</a>'
            f'<a href="privacy.html">Privacy</a></nav></div></header>')


def foot():
    year = datetime.date.today().year
    return (f'<footer><div class="wrap"><span>&copy; {year} {SITE_NAME}. '
            f'We may earn a commission from links on this site, at no extra cost to you.</span>'
            f'<span><a href="{PINTEREST}" rel="noopener" target="_blank">Pinterest</a> · '
            f'<a href="privacy.html">Privacy</a> · {esc(CONTACT)}</span></div></footer></body></html>')


# ---------- deal storage ----------

def load_deals():
    if DEALS_FILE.exists():
        return json.loads(DEALS_FILE.read_text(encoding="utf-8"))
    return {"next_number": 100, "deals": []}


def add_deals(deals):
    """Store newly posted deals. Returns them with their site number attached."""
    data = load_deals()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")
    for d in deals:
        if any(x["id"] == d["id"] for x in data["deals"]):
            continue
        d["number"] = data["next_number"]
        data["next_number"] += 1
        data["deals"].insert(0, {
            "number": d["number"], "id": d["id"], "title": d["title"],
            "category": d["category"]["name"], "store": d["store"],
            "now": d["now"], "was": d["was"], "discount": d["discount"],
            "image": d["image"], "link": d["link"], "posted": now,
        })
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=FRESH_DAYS)
    data["deals"] = [x for x in data["deals"]
                     if datetime.datetime.fromisoformat(x["posted"]) >= cutoff][:KEEP]
    DOCS.mkdir(exist_ok=True)
    DEALS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return deals


def ago(iso):
    then = datetime.datetime.fromisoformat(iso)
    mins = int((datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() // 60)
    if mins < 60:
        return "just now"
    if mins < 60 * 24:
        h = mins // 60
        return f"{h} hour{'s' if h > 1 else ''} ago"
    d = mins // (60 * 24)
    return f"{d} day{'s' if d > 1 else ''} ago"


# ---------- pages ----------

def card(x):
    return (f'<article class="card" data-cat="{esc(x["category"])}" '
            f'data-text="{esc((x["title"] + " " + x["store"]).lower())} #{x["number"]} {x["number"]}" '
            f'id="deal-{x["number"]}">'
            f'<div class="pic"><img src="{esc(x["image"])}" alt="{esc(x["title"])}" loading="lazy">'
            f'<span class="tag">-{int(x["discount"])}%</span><span class="num">#{x["number"]}</span></div>'
            f'<div class="body"><span class="cat">{esc(x["category"])}</span>'
            f'<span class="title">{esc(x["title"])}</span>'
            f'<div class="price"><span class="now">£{x["now"]:.2f}</span>'
            f'<span class="was">£{x["was"]:.2f}</span></div>'
            f'<span class="meta">{esc(x["store"])} · {ago(x["posted"])}</span>'
            f'<a class="btn" href="{esc(x["link"])}" rel="sponsored nofollow noopener" target="_blank">'
            f'Shop this deal</a></div></article>')


SCRIPT = """
<script>
(function(){
  var chips=[].slice.call(document.querySelectorAll('.chip')),
      cards=[].slice.call(document.querySelectorAll('.card')),
      q=document.getElementById('q'), empty=document.getElementById('empty'), cat='all';
  function apply(){
    var t=(q.value||'').toLowerCase().trim().replace(/^#/,''), shown=0;
    cards.forEach(function(c){
      var ok=(cat==='all'||c.dataset.cat===cat)&&(!t||c.dataset.text.indexOf(t)>-1);
      c.hidden=!ok; if(ok) shown++;
    });
    empty.hidden=shown>0;
  }
  chips.forEach(function(ch){ch.addEventListener('click',function(){
    cat=ch.dataset.cat; chips.forEach(function(o){o.setAttribute('aria-pressed',o===ch)}); apply();
  })});
  q.addEventListener('input',apply);
  var h=location.hash.replace('#','');
  if(/^deal-\\d+$/.test(h)){q.value=h.replace('deal-','');apply();}
})();
</script>
"""


def index_page(data):
    deals = data["deals"]
    cats = []
    for x in deals:
        if x["category"] not in cats:
            cats.append(x["category"])
    chips = ['<button class="chip" type="button" data-cat="all" aria-pressed="true">All deals</button>']
    chips += [f'<button class="chip" type="button" data-cat="{esc(c)}" aria-pressed="false">{esc(c)}</button>'
              for c in cats]
    cards = "".join(card(x) for x in deals)
    updated = datetime.datetime.now(datetime.timezone.utc).strftime("%d %b %Y")
    body = (f'<main class="wrap"><div class="hero"><h1>Today\'s deals</h1>'
            f'<p>Hand-picked discounts from UK shops, checked for real price drops. '
            f'Saw a deal in a video? Type its number in the search box.</p>'
            f'<p class="disclose">Prices were correct when posted and can change. '
            f'Links are affiliate links (#ad). Updated {updated}.</p></div>'
            f'<div class="tools"><input class="search" id="q" type="search" '
            f'placeholder="Search, or type a deal number" aria-label="Search deals">'
            f'{"".join(chips)}</div>'
            f'<div class="grid">{cards}</div>'
            f'<p class="empty" id="empty" {"hidden" if deals else ""}>'
            f'{"No deals match that search." if deals else "New deals are on their way. Check back soon."}</p>'
            f'</main>')
    return head(f"{SITE_NAME}: today's deals",
                "Hand-picked UK deals with genuine discounts, updated daily.") + body + SCRIPT + foot()


def about_page():
    body = f"""<main class="wrap page">
<h1>About {SITE_NAME}</h1>
<p>{SITE_NAME} shares genuine discounts from UK shops, every day. We look for real price drops,
mostly 25% off or more, on new items from trusted retailers and well-rated sellers.</p>
<section><h2>Where to find us</h2>
<p>Deals are posted to our <a href="{PINTEREST}" target="_blank" rel="noopener">Pinterest boards</a>,
in short videos on Instagram and YouTube, and on this website.</p></section>
<section><h2>How we make money</h2>
<p>Links to shops are affiliate links. If you buy something after clicking one, the shop pays us a small
commission. You pay the same price. We are a member of the eBay Partner Network and the Awin network.</p></section>
<section><h2>Prices</h2>
<p>Prices and stock change quickly. Every deal was correct when we posted it, but please check the price
on the shop's page before you buy.</p></section>
<section><h2>Contact</h2><p>{esc(CONTACT)}</p></section>
</main>"""
    return head(f"About {SITE_NAME}", f"Who runs {SITE_NAME} and how the site is funded.") + body + foot()


def privacy_page():
    body = f"""<main class="wrap page">
<h1>Privacy policy</h1>
<p>This policy covers the {SITE_NAME} website, our social media accounts, and the app we use to publish
deals to our own Pinterest, Instagram and YouTube accounts. Last updated 8 October 2026.</p>
<section><h2>Who we are</h2>
<p>{SITE_NAME} is an independent deals curator based in the United Kingdom. Contact: {esc(CONTACT)}.</p></section>
<section><h2>Our publishing app</h2>
<p>Our app uses the Pinterest API, the Instagram Graph API and the YouTube Data API only to publish posts to
our own {SITE_NAME} accounts. It does not access, read or post to anyone else's account, and it does not
collect data about the people who view our posts.</p></section>
<section><h2>Information we collect</h2>
<ul><li>This website has no sign-up, no forms and no analytics tracking. We do not collect personal information.</li>
<li>The website is hosted by GitHub Pages, which may keep standard server logs (such as IP addresses) for security.</li>
<li>Our app keeps a list of products it has already posted. This list contains no personal information.</li></ul></section>
<section><h2>Affiliate links and cookies</h2>
<p>When you click a deal, you go to the shop through the eBay Partner Network or Awin. They and the shop may set
cookies to record that a sale came from us. Their own privacy policies apply to that.</p></section>
<section><h2>Your rights</h2>
<p>Because we do not hold personal data about visitors, there is usually nothing for us to share, correct or delete.
If you have any question, email us and we will reply within 30 days. You can also contact the UK Information
Commissioner's Office (ico.org.uk).</p></section>
</main>"""
    return head(f"Privacy policy | {SITE_NAME}", f"How {SITE_NAME} handles data.") + body + foot()


def build_site():
    DOCS.mkdir(exist_ok=True)
    data = load_deals()
    (DOCS / "index.html").write_text(index_page(data), encoding="utf-8")
    (DOCS / "about.html").write_text(about_page(), encoding="utf-8")
    (DOCS / "privacy.html").write_text(privacy_page(), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    return DOCS / "index.html"


if __name__ == "__main__":
    print("Built", build_site())
