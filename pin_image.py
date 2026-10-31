"""
Branded 2:3 pin images (1000 x 1500) for Pinterest.

Pinterest favours tall pins, and a clear price tag stands out in the feed far more
than a plain square product photo. The product photo sits on a white card; the deal,
price and shop sit around it in the Daily Finds UK style (same look as the videos).

  python pin_image.py        makes three sample pins in videos/pin-samples/
"""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from video_maker import (DEEP, GOLD, GREEN, INK, LOGO, SOFT, WHITE, font, load_product,
                         price_tag, rounded, text_w)

W, H = 1000, 1500


def _background():
    bg = Image.new("RGB", (W, H), GREEN)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([-300, -250, W + 300, 1000], fill=95)
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    bg = Image.composite(Image.new("RGB", (W, H), (30, 140, 118)), bg, glow)
    shade = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shade).rectangle([0, 1050, W, H], fill=150)
    shade = shade.filter(ImageFilter.GaussianBlur(170))
    return Image.composite(Image.new("RGB", (W, H), DEEP), bg, shade).convert("RGBA")


def _label(deal, black_friday=False):
    num = deal.get("number")
    if not deal["discount"]:
        head = "GIFT IDEA"
    elif black_friday:
        head = "BLACK FRIDAY"
    else:
        head = "DEAL ALERT"
    return head + (f"  ·  #{num}" if num else "")


def make_pin_image(deal, out_path, black_friday=False, who=""):
    """deal needs: title, now, was, discount, image, store; number optional.
    who: optional 'for him' / 'for her' etc. shown on gift pins."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = _background()
    d = ImageDraw.Draw(img)

    # Header: logo, name, #ad (always visible, as UK ad rules require)
    logo = rounded(Image.open(LOGO).convert("RGBA").resize((76, 76), Image.LANCZOS), 38)
    img.alpha_composite(logo, (60, 52))
    d.text((152, 90), "Daily Finds UK", font=font(40), fill=WHITE, anchor="lm")
    d.rounded_rectangle([W - 170, 62, W - 60, 118], 28, fill=DEEP + (255,))
    d.text((W - 115, 90), "#ad", font=font(32), fill=WHITE, anchor="mm")

    # Hook pill
    hook = _label(deal, black_friday)
    hw = text_w(d, hook, font(44))
    d.rounded_rectangle([60, 160, 60 + hw + 52, 232], 36, fill=GOLD)
    d.text((86, 196), hook, font=font(44), fill=(58, 38, 0), anchor="lm")

    # Product card with soft shadow
    card_size, cx, top = 800, W // 2, 268
    shadow = Image.new("RGBA", (card_size + 80, card_size + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 52, card_size + 40, card_size + 52], 44,
                                             fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(24)),
                        (cx - card_size // 2 - 40, top - 40))
    product = rounded(load_product(deal["image"]).resize((card_size, card_size), Image.LANCZOS), 44)
    img.alpha_composite(product, (cx - card_size // 2, top))

    # Discount tag on the card corner (never on full-price gifts)
    if deal["discount"]:
        tag = price_tag(f"-{int(deal['discount'])}%", 1.15)
        img.alpha_composite(tag, (cx - card_size // 2 - 22, top + 34))

    # Title (2 lines max)
    lines = textwrap.wrap(deal["title"], 32)
    if len(lines) > 2:
        lines = lines[:2]
        lines[-1] = lines[-1].rstrip(" ,.-") + "…"
    y = top + card_size + 52
    for line in lines:
        d.text((W // 2, y), line, font=font(42, False), fill=WHITE, anchor="mm")
        y += 56

    # Price row
    py = 1306
    now = f"£{deal['now']:.2f}"
    if deal["discount"]:
        was = f"{deal.get('ref', 'was')} £{deal['was']:.2f}"
        nf, wf = font(92), font(42, False)
        nw, ww = text_w(d, now, nf), text_w(d, was, wf)
        x0 = W // 2 - (nw + 34 + ww) // 2
        d.text((x0, py), now, font=nf, fill=WHITE, anchor="lm")
        wx = x0 + nw + 34
        d.text((wx, py + 6), was, font=wf, fill=SOFT, anchor="lm")
        strike_from = wx + text_w(d, deal.get("ref", "was") + " ", wf)
        d.line([strike_from - 4, py + 8, wx + ww + 4, py + 4], fill=GOLD, width=6)
    else:
        sub = " ".join(x for x in ("Gift", who) if x)
        d.text((W // 2, py), f"{sub} · {now}", font=font(80), fill=WHITE, anchor="mm")

    # Call to action
    cta = f"Shop at {deal['store']}"
    cw = text_w(d, cta, font(40))
    d.rounded_rectangle([W // 2 - cw // 2 - 46, 1394, W // 2 + cw // 2 + 46, 1470], 40, fill=WHITE)
    d.text((W // 2, 1432), cta, font=font(40), fill=GREEN, anchor="mm")

    img.convert("RGB").save(out_path, quality=92)
    return out_path


def _sample_bottle(path, body=(232, 176, 160), cap=(60, 60, 60)):
    im = Image.new("RGB", (800, 800), (246, 240, 236))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([330, 120, 470, 230], 18, fill=cap)
    dd.rectangle([370, 220, 430, 260], fill=(200, 200, 200))
    dd.rounded_rectangle([230, 250, 570, 690], 70, fill=body)
    dd.rounded_rectangle([300, 400, 500, 540], 16, fill=(255, 255, 255))
    dd.text((400, 470), "EAU DE\nPARFUM", font=font(30), fill=INK, anchor="mm", align="center")
    im.save(path)
    return path


def _sample_flowers(path):
    im = Image.new("RGB", (800, 800), (246, 242, 238))
    dd = ImageDraw.Draw(im)
    dd.polygon([(330, 760), (470, 760), (520, 470), (280, 470)], fill=(214, 196, 170))
    for x, y, c in [(330, 330, (232, 120, 150)), (470, 320, (245, 200, 210)), (400, 240, (232, 120, 150)),
                    (300, 440, (250, 230, 235)), (500, 430, (232, 120, 150)), (400, 400, (245, 200, 210))]:
        dd.ellipse([x - 85, y - 85, x + 85, y + 85], fill=c)
        dd.ellipse([x - 30, y - 30, x + 30, y + 30], fill=(250, 220, 120))
    im.save(path)
    return path


if __name__ == "__main__":
    out = Path(__file__).parent / "videos" / "pin-samples"
    out.mkdir(parents=True, exist_ok=True)
    b1 = _sample_bottle(out / "bottle1.png")
    b2 = _sample_bottle(out / "bottle2.png", body=(40, 40, 46), cap=(190, 150, 70))
    fl = _sample_flowers(out / "flowers.png")
    a = make_pin_image({"title": "Calvin Klein Obsession For Men - 125ml Eau De Toilette Spray",
                        "now": 19.95, "was": 80.0, "discount": 75, "image": str(b2),
                        "store": "Scentsational", "number": 112}, out / "pin-deal.png")
    b = make_pin_image({"title": "Davidoff Cool Water For Women - 30ml Eau De Toilette",
                        "now": 11.0, "was": 49.0, "discount": 78, "image": str(b1),
                        "store": "Scentsational", "number": 113}, out / "pin-black-friday.png",
                       black_friday=True)
    c = make_pin_image({"title": "Rose and Lily Bouquet", "now": 34.5, "was": 34.5, "discount": 0,
                        "image": str(fl), "store": "Bunches", "number": 114}, out / "pin-gift.png",
                       who="for Mum")
    # Side-by-side preview
    sheet = Image.new("RGB", (W * 3 + 80, H + 40), (24, 24, 24))
    for i, p in enumerate((a, b, c)):
        sheet.paste(Image.open(p), (20 + i * (W + 20), 20))
    sheet.thumbnail((2100, 2100))
    sheet.save(out / "pin-samples.jpg", quality=90)
    print("Made", out / "pin-samples.jpg")
