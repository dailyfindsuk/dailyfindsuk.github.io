"""
Turns a deal into a 12-second vertical video (1080x1920, MP4) for Instagram Reels,
YouTube Shorts and TikTok.

  python video_maker.py            makes videos/sample.mp4 from a built-in example

Layout keeps text inside the "safe zone" so the apps' own buttons don't cover it.
Needs ffmpeg (installed automatically on GitHub Actions by the workflow).
"""

import io
import math
import subprocess
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
FONT_BOLD = str(ROOT / "fonts" / "Poppins-Bold.ttf")
FONT_MED = str(ROOT / "fonts" / "Poppins-Medium.ttf")
LOGO = ROOT / "docs" / "logo.png"

W, H, FPS, SECONDS = 1080, 1920, 30, 12
GREEN = (14, 107, 92)
DEEP = (8, 60, 52)
GOLD = (244, 178, 62)
INK = (20, 32, 28)
WHITE = (255, 255, 255)
SOFT = (226, 240, 235)

_fonts = {}


def font(size, bold=True):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(FONT_BOLD if bold else FONT_MED, size)
    return _fonts[key]


# ---------- easing ----------

def clamp(x):
    return max(0.0, min(1.0, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def pop(x):
    """Overshoot then settle: 0 -> 1.12 -> 1."""
    x = clamp(x)
    if x < 0.6:
        return ease_out(x / 0.6) * 1.12
    return 1.12 - 0.12 * ease_out((x - 0.6) / 0.4)


def progress(t, start, dur):
    return clamp((t - start) / dur)


# ---------- assets ----------

def load_product(image):
    """image: URL or local path. Returns an RGBA image on a white square."""
    if str(image).startswith("http"):
        data = requests.get(image, timeout=30).content
        im = Image.open(io.BytesIO(data))
    else:
        im = Image.open(image)
    im = im.convert("RGBA")
    im.thumbnail((820, 820), Image.LANCZOS)
    tile = Image.new("RGBA", (860, 860), WHITE + (255,))
    tile.alpha_composite(im, ((860 - im.width) // 2, (860 - im.height) // 2))
    return tile


def rounded(im, radius):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius, fill=255)
    out = im.copy()
    out.putalpha(mask)
    return out


def background():
    bg = Image.new("RGB", (W, H), GREEN)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([-300, -200, W + 300, 1300], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    bg = Image.composite(Image.new("RGB", (W, H), (30, 140, 118)), bg, glow)
    shade = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shade).rectangle([0, 1250, W, H], fill=140)
    shade = shade.filter(ImageFilter.GaussianBlur(200))
    return Image.composite(Image.new("RGB", (W, H), DEEP), bg, shade).convert("RGBA")


def text_w(draw, s, f):
    b = draw.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def price_tag(text, scale):
    """Gold price tag shape with text, scaled for the pop animation."""
    f = font(int(64 * scale))
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = text_w(tmp, text, f)
    pw, ph = tw + int(90 * scale), int(110 * scale)
    tag = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(tag)
    notch = int(34 * scale)
    d.polygon([(notch, 0), (pw, 0), (pw, ph), (notch, ph), (0, ph // 2)], fill=GOLD)
    r = int(10 * scale)
    d.ellipse([notch - r // 2, ph // 2 - r, notch + r + r // 2, ph // 2 + r], fill=(0, 0, 0, 0))
    d.text((notch + int(30 * scale), ph // 2), text, font=f, fill=(58, 38, 0), anchor="lm")
    return tag


# ---------- frame drawing ----------

def draw_frame(t, deal, base, product, logo):
    frame = base.copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # text layer, composited last
    d = ImageDraw.Draw(ov)
    num = deal.get("number")

    # Header: logo + name, and #ad label (always visible)
    frame.alpha_composite(logo, (70, 150))
    d.text((170, 198), "Daily Finds UK", font=font(44), fill=WHITE, anchor="lm")
    d.rounded_rectangle([W - 190, 168, W - 70, 228], 30, fill=DEEP + (255,))
    d.text((W - 130, 198), "#ad", font=font(34), fill=WHITE, anchor="mm")

    # Hook: "DEAL ALERT" + category (slides in, then stays small)
    a = ease_out(progress(t, 0.0, 0.6))
    hook_y = 300 + int((1 - a) * 60)
    hook = "DEAL ALERT" + (f"  ·  #{num}" if num else "")
    hw = text_w(d, hook, font(54))
    d.rounded_rectangle([70, hook_y - 8, 70 + hw + 56, hook_y + 74], 41, fill=GOLD)
    d.text((98, hook_y + 33), hook, font=font(54), fill=(58, 38, 0), anchor="lm")
    d.text((70, hook_y + 118), deal["category"]["name"].upper(), font=font(36, False),
           fill=SOFT, anchor="lm")

    # Product card: rises in, then slow zoom
    a = ease_out(progress(t, 0.3, 0.8))
    zoom = 1.0 + 0.06 * clamp((t - 1.1) / (SECONDS - 1.1))
    size = int(860 * (0.9 + 0.1 * a) * zoom * 0.84)
    card = rounded(product.resize((size, size), Image.LANCZOS), 48)
    cx, cy = W // 2, 880 + int((1 - a) * 120)
    shadow = Image.new("RGBA", (size + 80, size + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 50, size + 40, size + 50], 48, fill=(0, 0, 0, int(90 * a)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    frame.alpha_composite(shadow, (cx - size // 2 - 40, cy - size // 2 - 40))
    if a > 0:
        card.putalpha(card.getchannel("A").point(lambda v: int(v * a)))
        frame.alpha_composite(card, (cx - size // 2, cy - size // 2))

    # Discount tag pops onto the card's corner
    p = progress(t, 6.2, 0.5)
    if p > 0:
        tag = price_tag(f"-{int(deal['discount'])}%", pop(p))
        frame.alpha_composite(tag, (cx - size // 2 - 20, cy - size // 2 + 30))

    # Title under the card
    a = ease_out(progress(t, 1.6, 0.6))
    if a > 0:
        lines = textwrap.wrap(deal["title"], 30)[:2]
        if len(textwrap.wrap(deal["title"], 30)) > 2:
            lines[-1] = lines[-1].rstrip(" ,.-") + "…"
        y = 1310
        for line in lines:
            d.text((W // 2, y + int((1 - a) * 30)), line, font=font(48, False),
                   fill=WHITE + (int(255 * a),), anchor="mm")
            y += 64

    # Prices: WAS appears, gets struck through, NOW pops in
    py = 1445
    a = ease_out(progress(t, 3.2, 0.5))
    if a > 0:
        was = f"£{deal['was']:.2f}"
        wf = font(56, False)
        ww = text_w(d, was, wf)
        wx = W // 2 - 250
        d.text((wx, py), "was", font=font(34, False), fill=SOFT + (int(255 * a),), anchor="mm")
        d.text((wx, py + 58), was, font=wf, fill=SOFT + (int(255 * a),), anchor="mm")
        s = progress(t, 4.3, 0.4)
        if s > 0:
            x0 = wx - ww // 2 - 8
            d.line([x0, py + 60, x0 + int((ww + 16) * ease_out(s)), py + 56], fill=GOLD, width=8)
    p = progress(t, 4.9, 0.55)
    if p > 0:
        sc = pop(p)
        now = f"£{deal['now']:.2f}"
        d.text((W // 2 + 170, py), "now", font=font(34, False), fill=GOLD, anchor="mm")
        d.text((W // 2 + 170, py + 62), now, font=font(int(96 * sc)), fill=WHITE, anchor="mm")

    # Call to action slides up for the last seconds
    a = ease_out(progress(t, 8.6, 0.6))
    if a > 0:
        y = 1620 + int((1 - a) * 80)
        cta = f"Link in bio  ·  search #{num}" if num else "Link in bio for this deal"
        cw = text_w(d, cta, font(46))
        d.rounded_rectangle([W // 2 - cw // 2 - 44, y - 50, W // 2 + cw // 2 + 44, y + 50], 50,
                            fill=WHITE + (int(255 * a),))
        d.text((W // 2, y), cta, font=font(46), fill=GREEN + (int(255 * a),), anchor="mm")
    else:
        d.text((W // 2, 1625), f"at {deal['store']}", font=font(40, False), fill=SOFT, anchor="mm")
    frame.alpha_composite(ov)
    return frame.convert("RGB")


def make_video(deal, out_path):
    """deal needs: title, now, was, discount, image, store, category{name}; number optional."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = background()
    product = load_product(deal["image"])
    logo = rounded(Image.open(LOGO).convert("RGBA").resize((84, 84), Image.LANCZOS), 42)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "128k", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(FPS * SECONDS):
        proc.stdin.write(draw_frame(i / FPS, deal, base, product, logo).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed to make the video")
    return out_path


def video_caption(deal, tags):
    num = f" (deal #{deal['number']})" if deal.get("number") else ""
    return (f"{deal['discount']}% off: {deal['title']}\n"
            f"Now £{deal['now']:.2f}, was £{deal['was']:.2f} at {deal['store']}{num}.\n"
            f"Link in bio: search the deal number on our site. Prices can change.\n"
            f"#ad {tags} #dealsuk #ukdeals")


if __name__ == "__main__":
    sample_img = ROOT / "videos" / "sample-product.png"
    sample_img.parent.mkdir(exist_ok=True)
    im = Image.new("RGB", (800, 800), (245, 230, 225))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([290, 160, 510, 260], 20, fill=(60, 60, 60))
    dd.rounded_rectangle([230, 240, 570, 680], 60, fill=(232, 176, 160))
    dd.rounded_rectangle([300, 380, 500, 520], 16, fill=(255, 255, 255))
    im.save(sample_img)
    demo = {"title": "Sentier Ivory Eau de Parfum 100ml, Long Lasting Floral Scent",
            "now": 34.0, "was": 68.0, "discount": 50, "image": str(sample_img),
            "store": "Sentier Fragrance", "category": {"name": "Beauty & Fragrance"}, "number": 105}
    print("Made", make_video(demo, ROOT / "videos" / "sample.mp4"))
