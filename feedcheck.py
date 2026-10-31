"""Checks an Awin feed shop by shop and writes the results to feedcheck.txt."""
import collections
import dealbot

out = []
url = input("Paste the Awin feed link (right-click), then press Enter: ").strip()
rows = dealbot.awin_rows(url) if url else []
out.append(f"rows: {len(rows)}")
if rows:
    out.append(f"columns: {list(rows[0].keys())}")
cfg = dealbot.load_config()
rules = {**cfg, "min_discount_percent": 15}
by_shop = collections.defaultdict(list)
for r in rows:
    by_shop[(r.get("merchant_name") or "?").strip()].append(r)
for shop, items in sorted(by_shop.items(), key=lambda x: -len(x[1])):
    def filled(col):
        return sum(1 for r in items if (r.get(col) or "").strip() not in ("", "0", "0.00"))
    deals = [d for d in (dealbot.awin_deal(r, rules, set()) for r in items) if d]
    disc = collections.Counter(d["discount"] for d in deals)
    top_disc = disc.most_common(1)[0] if disc else (None, 0)
    out.append("")
    out.append(f"=== {shop}: {len(items)} products")
    out.append(f"  rrp_price filled: {filled('rrp_price')}, product_price_old filled: {filled('product_price_old')}, "
               f"in stock: {sum(1 for r in items if str(r.get('in_stock','1')).strip() in ('1','true','yes'))}, "
               f"large_image: {filled('large_image')}")
    out.append(f"  deals (15%+ off, in price range): {len(deals)}; most common discount {top_disc[0]}% x{top_disc[1]}")
    out.append(f"  discount spread: {sorted(disc.items())[:25]}")
    for d in sorted(deals, key=lambda d: -d['discount'])[:6]:
        out.append(f"    {d['discount']}% | now {d['now']} was {d['was']} | {d['title'][:70]}")
    for r in items[:2]:
        out.append(f"    sample: {r.get('product_name','')[:60]} | price {r.get('search_price')} rrp {r.get('rrp_price')} old {r.get('product_price_old')} | img {(r.get('large_image') or r.get('merchant_image_url') or '')[:50]}")
open("feedcheck.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out[:3]))
print("\nSaved feedcheck.txt")
