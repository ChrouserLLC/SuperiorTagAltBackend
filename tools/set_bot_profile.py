"""
Gives the Discord bot a purple pixel-style profile picture, banner and About Me.

    python tools/set_bot_profile.py             # make the images and upload them
    python tools/set_bot_profile.py --preview   # only make the images (bot/profile/)
    python tools/set_bot_profile.py --name "Superior Tag"   # also rename the bot

Uses Pixelify Sans from api/fonts if it's there (falls back to DejaVu).
Reads DISCORD_BOT_TOKEN from private/vercel-env-values.txt like the other tools.
Discord limits avatar/name changes to a couple per hour, so don't spam it.
"""
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, HERE)

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

import discord_bot  # noqa: E402  (for _font / the accent colour)
from register_discord_commands import _value  # noqa: E402

OUT = os.path.join(ROOT, "bot", "profile")
PURPLE = (168, 85, 247)
DEEP = (59, 7, 100)
NIGHT = (14, 9, 26)

ABOUT_ME = (
    "\U0001f98d Official Superior Tag bot\n"
    "\n"
    "/players • live player count + chart\n"
    "/rooms • public rooms right now\n"
    "/status • is everything up?\n"
    "\n"
    "Staff: /player /ban /unban /code /live /verifybadge"
)

# An original 16x16 pixel monke. D = fur, d = fur shadow, F = face, E = eye white,
# P = pupil, N = nostril, M = mouth.
MONKE = [
    "................",
    ".....dDDDDDd....",
    "...dDDDDDDDDDd..",
    "..dDDDDDDDDDDDd.",
    ".dDDFFFDDDFFFDDd",
    ".dDFFFFFFFFFFFDd",
    "dDDFEEPFFFEEPFDd",
    "dDDFEEPFFFEEPFDd",
    "dDDFFFFFFFFFFFDd",
    ".dDFFFFNFFNFFFDd",
    ".dDDFFFFFFFFFDDd",
    "..dDFFMMMMMMFDd.",
    "..dDDFFFFFFFDDd.",
    "...dDDDDDDDDDd..",
    ".....dDDDDDd....",
    "................",
]
MONKE_COLOURS = {
    "D": (46, 38, 64), "d": (30, 24, 44), "F": (214, 196, 238), "E": (255, 255, 255),
    "P": (20, 12, 36), "N": (120, 92, 160), "M": (88, 52, 130),
}


def monke(cell):
    img = Image.new("RGBA", (16 * cell, 16 * cell), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y, row in enumerate(MONKE):
        for x, ch in enumerate(row):
            if ch in MONKE_COLOURS:
                d.rectangle([x * cell, y * cell, (x + 1) * cell - 1, (y + 1) * cell - 1], fill=MONKE_COLOURS[ch])
    return img


def gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def pixel_grid(img, step, alpha=18):
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for x in range(0, img.size[0], step):
        d.line([(x, 0), (x, img.size[1])], fill=(255, 255, 255, alpha))
    for y in range(0, img.size[1], step):
        d.line([(0, y), (img.size[0], y)], fill=(255, 255, 255, alpha))
    return Image.alpha_composite(img.convert("RGBA"), over)


def glow_text(base, xy, text, font, fill=(255, 255, 255), glow=PURPLE, anchor="la"):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=glow + (255,), anchor=anchor)
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(base).text(xy, text, font=font, fill=fill, anchor=anchor)


def make_avatar():
    size = 512
    img = pixel_grid(gradient(size, size, (88, 28, 135), NIGHT), 32, 14)
    # soft purple halo behind the monke
    halo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse([66, 66, 446, 446], fill=PURPLE + (150,))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(40)))
    # Discord crops avatars to a circle, so keep everything near the middle.
    m = monke(21)
    img.alpha_composite(m, ((size - m.size[0]) // 2, (size - m.size[1]) // 2))
    return img.convert("RGB")


def make_banner():
    w, h = 1200, 480  # Discord shows banners at 5:2
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for x in range(w):
        t = x / (w - 1)
        d.line([(x, 0), (x, h)], fill=tuple(int(NIGHT[i] + (DEEP[i] - NIGHT[i]) * (1 - abs(0.5 - t) * 2) * 1.0)
                                            for i in range(3)))
    img = pixel_grid(img, 24, 12)
    # chunky pixel "stars"
    dd = ImageDraw.Draw(img)
    for i, (x, y) in enumerate([(90, 70), (1080, 60), (1010, 400), (160, 410), (620, 50), (760, 430), (1130, 230)]):
        s = 12 if i % 2 else 8
        dd.rectangle([x, y, x + s, y + s], fill=PURPLE + (200,))
    m = monke(14)
    img.alpha_composite(m, (110, (h - m.size[1]) // 2))
    glow_text(img, (400, 200), "SUPERIOR TAG", discord_bot._font(96, bold=True), anchor="lm")
    glow_text(img, (404, 290), "IN-GAME MANAGEMENT", discord_bot._font(38), fill=(216, 180, 254), anchor="lm")
    return img.convert("RGB")


def data_uri(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def api(method, path, body, token):
    req = urllib.request.Request("https://discord.com/api/v10" + path, data=json.dumps(body).encode("utf-8"),
                                 method=method, headers={
                                     "Authorization": "Bot " + token, "Content-Type": "application/json",
                                     "User-Agent": "DiscordBot (https://github.com/ChrouserLLC/SuperiorTagAltBackend, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return False, e.read().decode("utf-8", "replace")[:300]


def main(argv):
    os.makedirs(OUT, exist_ok=True)
    avatar, banner = make_avatar(), make_banner()
    avatar.save(os.path.join(OUT, "avatar.png"))
    banner.save(os.path.join(OUT, "banner.png"))
    print("Saved bot/profile/avatar.png and bot/profile/banner.png")
    if "--preview" in argv:
        return 0

    token = _value("DISCORD_BOT_TOKEN")
    if not token:
        print("Couldn't find DISCORD_BOT_TOKEN in private/vercel-env-values.txt")
        return 1
    me = {"avatar": data_uri(avatar), "banner": data_uri(banner)}
    if "--name" in argv and argv.index("--name") + 1 < len(argv):
        me["username"] = argv[argv.index("--name") + 1]
    ok, res = api("PATCH", "/users/@me", me, token)
    print("Profile picture + banner:", "updated" if ok else "FAILED - " + str(res))
    ok, res = api("PATCH", "/applications/@me", {"description": ABOUT_ME}, token)
    print("About Me:", "updated" if ok else "FAILED - " + str(res))
    print("Discord can take a minute to show the new look (restart Discord if it doesn't).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
