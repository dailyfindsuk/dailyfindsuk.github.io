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
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

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



def ffmpeg_path():
    """The system ffmpeg if installed, otherwise the copy that comes with the
    imageio-ffmpeg pip package (so the bot never waits on Ubuntu's download servers)."""
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

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

def trim_whitespace(im, tol=18, margin=0.04):
    """Crop away plain white/transparent borders that many shop photos have,
    so the product fills the card. Leaves the photo alone if nothing to trim."""
    rgb = Image.new("RGB", im.size, (255, 255, 255))
    rgb.paste(im, mask=im.getchannel("A"))
    diff = ImageChops.difference(rgb, Image.new("RGB", im.size, (255, 255, 255))).convert("L")
    box = diff.point(lambda v: 255 if v > tol else 0).getbbox()
    if not box:
        return im
    l, t, r, b = box
    pad = int(max(r - l, b - t) * margin)
    l, t = max(0, l - pad), max(0, t - pad)
    r, b = min(im.width, r + pad), min(im.height, b + pad)
    if (r - l) * (b - t) > 0.92 * im.width * im.height:
        return im  # already fills the frame (e.g. a lifestyle photo)
    return rgb.crop((l, t, r, b)).convert("RGBA")


def load_product(image):
    """image: URL or local path. Returns an RGBA image on a white square."""
    if str(image).startswith("http"):
        data = requests.get(image, timeout=30).content
        im = Image.open(io.BytesIO(data))
    else:
        im = Image.open(image)
    im = im.convert("RGBA")
    im = trim_whitespace(im)
    im.thumbnail((780, 780), Image.LANCZOS)
    if max(im.size) < 780:  # small photos: scale up so the product fills the card
        k = 780 / max(im.size)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.BICUBIC)
        # light sharpen so an enlarged photo doesn't look soft
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=min(140, int(60 * k)), threshold=2))
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

def hook_text(deal):
    """Big first-second headline: the saving for deals, the budget for gift ideas."""
    if deal["discount"]:
        saved = (deal.get("was") or 0) - deal["now"]
        return f"SAVE £{saved:.0f}" if saved >= 5 else f"{int(deal['discount'])}% OFF"
    now = deal["now"]
    for cap in (10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 150, 200, 300, 500, 1000):
        if now <= cap:
            return f"GIFT UNDER £{cap}"
    return "GIFT IDEA"


def draw_frame(t, deal, base, product, logo):
    # Everything (product, price, saving, link) is on screen from the very first frame:
    # TikTok viewers decide in under a second, so nothing fades in. Motion comes from
    # a slow zoom, a pulsing price and a shine across the card.
    frame = base.copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # text layer, composited last
    d = ImageDraw.Draw(ov)
    num = deal.get("number")

    # Header: logo + name, and #ad label
    frame.alpha_composite(logo, (70, 150))
    d.text((170, 198), "Daily Finds UK", font=font(44), fill=WHITE, anchor="lm")
    d.rounded_rectangle([W - 190, 168, W - 70, 228], 30, fill=DEEP + (255,))
    d.text((W - 130, 198), "#ad", font=font(34), fill=WHITE, anchor="mm")

    # Hook: big gold "SAVE £40" / "GIFT UNDER £25" pill, with a little bounce
    bounce = 1.0 + 0.04 * math.sin(t * 2 * math.pi / 1.6)
    hook = hook_text(deal)
    hf = font(int(76 * bounce))
    hw = text_w(d, hook, hf)
    hy = 300
    d.rounded_rectangle([70, hy - 10, 70 + hw + 70, hy + 96], 53, fill=GOLD)
    d.text((105, hy + 43), hook, font=hf, fill=(58, 38, 0), anchor="lm")
    sub = deal["category"]["name"].upper() + (f"  ·  #{num}" if num else "")
    d.text((72, hy + 140), sub, font=font(36, False), fill=SOFT, anchor="lm")

    # Product card: full size from frame one, slow zoom throughout
    zoom = 1.0 + 0.07 * clamp(t / SECONDS)
    size = int(860 * zoom * 0.84)
    card = rounded(product.resize((size, size), Image.LANCZOS), 48)
    # shine: a soft diagonal light sweeps across the card every 4 seconds
    sp = (t % 4.0) / 0.9
    if sp < 1:
        shine = Image.new("L", (size, size), 0)
        x = int(-size * 0.6 + sp * size * 2.2)
        ImageDraw.Draw(shine).polygon([(x, 0), (x + 90, 0), (x - size // 2 + 90, size), (x - size // 2, size)], fill=90)
        shine = ImageChops.multiply(shine.filter(ImageFilter.GaussianBlur(18)), card.getchannel("A"))
        card = Image.composite(Image.new("RGBA", (size, size), WHITE + (255,)), card, shine)
    cx, cy = W // 2, 900
    shadow = Image.new("RGBA", (size + 80, size + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 50, size + 40, size + 50], 48, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    frame.alpha_composite(shadow, (cx - size // 2 - 40, cy - size // 2 - 40))
    frame.alpha_composite(card, (cx - size // 2, cy - size // 2))

    # Discount tag on the card's corner, gently pulsing
    if deal["discount"]:
        tag = price_tag(f"-{int(deal['discount'])}%", 1.0 + 0.06 * max(0, math.sin(t * 2 * math.pi / 1.2)))
        frame.alpha_composite(tag, (cx - size // 2 - 20, cy - size // 2 + 30))

    # Title under the card
    lines = textwrap.wrap(deal["title"], 30)[:2]
    if len(textwrap.wrap(deal["title"], 30)) > 2:
        lines[-1] = lines[-1].rstrip(" ,.-") + "…"
    y = 1330
    for line in lines:
        d.text((W // 2, y), line, font=font(48, False), fill=WHITE, anchor="mm")
        y += 64

    # Prices: crossed-out old price and big new price, both visible at once
    py = 1465
    if deal["discount"]:
        was = f"£{deal['was']:.2f}"
        wf = font(56, False)
        ww = text_w(d, was, wf)
        wx = W // 2 - 250
        d.text((wx, py), deal.get("ref", "was"), font=font(34, False), fill=SOFT, anchor="mm")
        d.text((wx, py + 58), was, font=wf, fill=SOFT, anchor="mm")
        x0 = wx - ww // 2 - 8
        d.line([x0, py + 60, x0 + ww + 16, py + 56], fill=GOLD, width=8)
    sc = 1.0 + 0.05 * max(0, math.sin(t * 2 * math.pi / 1.2 + 0.6))
    now = f"£{deal['now']:.2f}"
    nx = W // 2 + 170 if deal["discount"] else W // 2
    label = "now" if deal["discount"] else f"at {deal['store']}"
    d.text((nx, py), label, font=font(34, False), fill=GOLD, anchor="mm")
    d.text((nx, py + 66), now, font=font(int(100 * sc)), fill=WHITE, anchor="mm")

    # Call to action
    y = 1650
    cta = f"Link in bio  ·  search #{num}" if num else "Link in bio for this deal"
    cw = text_w(d, cta, font(46))
    d.rounded_rectangle([W // 2 - cw // 2 - 44, y - 50, W // 2 + cw // 2 + 44, y + 50], 50, fill=WHITE)
    d.text((W // 2, y), cta, font=font(46), fill=GREEN, anchor="mm")
    frame.alpha_composite(ov)
    return frame.convert("RGB")


def make_video(deal, out_path):
    """deal needs: title, now, was, discount, image, store, category{name}; number optional."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = background()
    product = load_product(deal["image"])
    logo = rounded(Image.open(LOGO).convert("RGBA").resize((84, 84), Image.LANCZOS), 42)
    from music import music_for_video
    track = music_for_video(SECONDS, out_path.with_suffix(".music.wav"), seed=deal.get("number"))
    cmd = [ffmpeg_path(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(track),
           # Upscaled to 1440x2560 and encoded at high quality: YouTube gives
           # uploads above 1080p its sharper encoding, so text stays crisp.
           "-t", str(SECONDS), "-vf", "scale=1440:2560:flags=lanczos",
           "-af", f"afade=t=out:st={SECONDS - 1}:d=1",
           "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-tune", "animation",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "128k", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(FPS * SECONDS):
        proc.stdin.write(draw_frame(i / FPS, deal, base, product, logo).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed to make the video")
    if Path(track).name.endswith(".music.wav"):
        Path(track).unlink(missing_ok=True)
    return out_path


def video_caption(deal, tags):
    num = f" (deal #{deal['number']})" if deal.get("number") else ""
    return (f"{deal['discount']}% off: {deal['title']}\n"
            f"Now £{deal['now']:.2f}, {deal.get('ref', 'was')} £{deal['was']:.2f} at {deal['store']}{num}.\n"
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
