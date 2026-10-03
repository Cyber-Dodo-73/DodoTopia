# -*- coding: utf-8 -*-
"""Images de partage (Open Graph / Twitter) du site public : une PNG 1200×630 par page et par langue.

    py .tools/make_og.py            génère server/static/og/<page>-<lang>.png (toutes les pages, toutes les langues)
    py .tools/make_og.py fr en      seulement ces langues

Style « Cozy illustré », le même que le site : dégradé de la rubrique (musique pêche, dessin rose-lilas, cuisine
menthe, salons bleu, neutre crème), nuages, collines en bas, capture de l'application inclinée dans un cadre
fenêtre à trois pastilles, dodo posé dessus, pastille du domaine. Les pages sans capture montrent le dodo en grand.

Textes : les catalogues du site (`server/app/locales/<lang>.json`, repli en → fr), donc les mêmes que les pages.
Polices : Fredoka (server/static/fonts, sous-ensemble latin) pour les langues latines si Pillow sait la lire,
sinon une police système Windows (Segoe UI Bold) ; Microsoft YaHei (zh-CN), Yu Gothic (ja), Leelawadee UI (th).
Si aucune n'est trouvée, la police par défaut de Pillow. Relancer après une modification des textes `site.meta.*`
ou `site.nav.*`, du logo ou des captures.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
STATIC = SERVER / "static"
OUT = STATIC / "og"
sys.path.insert(0, str(SERVER))

from app import i18n  # noqa: E402  (module sans dépendance web)

W, H = 1200, 630
PAGES = ("home", "music", "draw", "cook", "creations", "together", "download", "instruments", "news", "community", "help",
         "legal", "privacy", "terms", "songs", "gallery")
SHOTS = {"home": "musique", "music": "musique", "draw": "dessin", "cook": "cuisine", "creations": "creations", "together": "musique",
         "songs": "musique", "gallery": "dessin"}
# Mêmes ambiances que `site.THEMES` et les jetons de site.css : (fond, fond 2, accent, encre).
THEMES = {
    "music": ((255, 233, 199), (255, 211, 176), (232, 147, 47), (122, 67, 16)),
    "draw": ((255, 224, 236), (230, 220, 255), (217, 99, 154), (122, 47, 87)),
    "cook": ((217, 247, 234), (200, 240, 239), (31, 157, 143), (15, 92, 85)),
    "rooms": ((220, 239, 255), (227, 230, 255), (61, 139, 217), (29, 79, 134)),
    "neutral": ((255, 249, 239), (255, 225, 196), (217, 138, 75), (107, 68, 35)),
}
PAGE_THEME = {"music": "music", "songs": "music", "draw": "draw", "gallery": "draw", "creations": "draw", "cook": "cook",
              "together": "rooms"}

HEAD = (59, 45, 39)
INK2 = (106, 88, 77)
WHITE = (255, 255, 255)
LINE = (228, 207, 174)
PANEL_SOFT = (255, 244, 227)

WIN_FONTS = Path("C:/Windows/Fonts")
FONT_FILES = {
    "zh-CN": (("msyhbd.ttc", "msyh.ttc"), ("msyh.ttc",)),
    "ja": (("YuGothB.ttc", "YuGothM.ttc", "meiryob.ttc"), ("YuGothM.ttc", "YuGothR.ttc", "meiryo.ttc")),
    "th": (("LeelaUIb.ttf", "LeelawUI.ttf"), ("LeelawUI.ttf",)),
}


def _truetype(candidates, size: int, weight: int | None = None):
    for path in candidates:
        path = Path(path)
        if not path.is_file():
            continue
        try:
            font = ImageFont.truetype(str(path), size)
        except OSError:
            continue
        if weight is not None:
            try:
                font.set_variation_by_axes([weight])
            except Exception:  # noqa - police non variable : on garde l'instance par défaut
                pass
        return font
    return None


def fonts(lang: str, size_title: int, size_text: int):
    """(police du titre, police du texte) pour cette langue."""
    if lang in FONT_FILES:
        bold, regular = FONT_FILES[lang]
        title = _truetype([WIN_FONTS / f for f in bold], size_title)
        text = _truetype([WIN_FONTS / f for f in regular], size_text)
    else:
        title = (_truetype([STATIC / "fonts" / "fredoka-latin.woff2"], size_title, 600)
                 or _truetype([WIN_FONTS / "segoeuib.ttf"], size_title))
        text = (_truetype([STATIC / "fonts" / "nunito-latin.woff2"], size_text, 650)
                or _truetype([WIN_FONTS / "segoeui.ttf"], size_text))
    default = ImageFont.load_default()
    return title or default, text or default


def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int, cjk: bool = False) -> list[str]:
    """Coupe aux espaces (langues latines) ; caractère par caractère pour le chinois et le japonais, et
    pour tout mot plus large que la colonne. Dernière ligne terminée par « … » si le texte est tronqué."""
    tokens: list[str] = []
    if cjk:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*|.", text)        # « Heartopia » ne se coupe pas
    else:
        for i, word in enumerate(text.split(" ")):
            piece = word if i == 0 else " " + word
            if draw.textlength(piece.strip(), font=font) > width:
                tokens.extend(piece)
            else:
                tokens.append(piece)
    lines: list[str] = []
    cur = ""
    truncated = False
    for tok in tokens:
        trial = cur + tok
        if draw.textlength(trial.strip(), font=font) <= width:
            cur = trial
            continue
        lines.append(cur.strip())
        cur = tok
        if len(lines) == max_lines:
            truncated = True
            break
    if not truncated and cur.strip():
        if len(lines) < max_lines:
            lines.append(cur.strip())
        else:
            truncated = True
    if truncated and lines:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip(" ,;:—-、，") + "…"
    return lines


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), radius, fill=255)
    out = Image.new("RGBA", img.size)
    out.paste(img, (0, 0), mask)
    return out


def mix(a, b, t: float):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def background(theme: str) -> Image.Image:
    """Dégradé à 160° de la rubrique, halo clair en haut à gauche, nuages, deux rangs de collines en bas."""
    bg, bg2, accent, _ink = THEMES[theme]
    small = Image.new("RGB", (W // 8, H // 8))
    px = small.load()
    for y in range(small.height):
        for x in range(small.width):
            t = (0.34 * (1 - x / small.width) + 0.94 * (y / small.height)) / 1.28
            px[x, y] = mix(bg, bg2, max(0.0, min(1.0, t)))
    img = small.resize((W, H), Image.BICUBIC).convert("RGBA")
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((-320, -380, 620, 320), fill=150)
    img.paste(Image.new("RGBA", (W, H), WHITE + (255,)), (0, 0), glow.filter(ImageFilter.GaussianBlur(110)))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for cx, cy, s, alpha in ((1020, 70, 1.0, 190), (560, 40, 0.62, 150)):          # nuages
        for dx, dy, r in ((0, 0, 34), (38, -18, 44), (84, 0, 36), (42, 14, 40)):
            d.ellipse((cx + (dx - r) * s, cy + (dy - r) * s, cx + (dx + r) * s, cy + (dy + r) * s),
                      fill=WHITE + (alpha,))
        d.rounded_rectangle((cx - 34 * s, cy, cx + 120 * s, cy + 36 * s), 18 * s, fill=WHITE + (alpha,))
    hill_back = mix(bg2, accent, 0.2)
    hill_front = mix(bg2, accent, 0.08)
    d.ellipse((-260, H - 120, 640, H + 260), fill=hill_back + (255,))
    d.ellipse((480, H - 96, 1500, H + 300), fill=hill_back + (255,))
    d.ellipse((-420, H - 64, 520, H + 300), fill=hill_front + (255,))
    d.ellipse((300, H - 78, 1100, H + 280), fill=hill_front + (255,))
    d.ellipse((900, H - 58, 1700, H + 300), fill=hill_front + (255,))
    for x, y, r in ((610, 118, 9), (1150, 250, 7), (672, 520, 6)):                 # étoiles à quatre branches
        d.polygon([(x, y - r * 2), (x + r * .5, y - r * .5), (x + r * 2, y), (x + r * .5, y + r * .5),
                   (x, y + r * 2), (x - r * .5, y + r * .5), (x - r * 2, y), (x - r * .5, y - r * .5)],
                  fill=accent + (170,))
    img.alpha_composite(layer)
    return img


def window(shot: Image.Image, width: int) -> Image.Image:
    """Capture dans un cadre fenêtre (barre de titre, trois pastilles), dessinée en 2x puis réduite."""
    scale = 2
    w = width * scale
    bar = 34 * scale
    shot = shot.resize((w, round(shot.height * w / shot.width)), Image.LANCZOS)
    frame = Image.new("RGBA", (w, bar + shot.height), WHITE + (255,))
    d = ImageDraw.Draw(frame)
    d.rectangle((0, 0, w, bar), fill=PANEL_SOFT + (255,))
    d.line((0, bar, w, bar), fill=LINE + (255,), width=scale)
    for i, color in enumerate(((255, 138, 122), (255, 193, 94), (111, 211, 155))):
        cx = (22 + i * 20) * scale
        d.ellipse((cx - 6 * scale, bar // 2 - 6 * scale, cx + 6 * scale, bar // 2 + 6 * scale), fill=color + (255,))
    frame.paste(shot, (0, bar))
    frame = rounded(frame, 22 * scale)
    return frame.resize((width, frame.height // scale), Image.LANCZOS)


def paste_with_shadow(img: Image.Image, item: Image.Image, x: int, y: int, blur: int = 22, alpha: int = 95) -> None:
    shadow = Image.new("RGBA", img.size, (90, 60, 40, 0))       # même teinte partout : le flou ne grise pas
    shape = Image.new("RGBA", item.size, (90, 60, 40, alpha))
    shape.putalpha(item.getchannel("A").point(lambda v: v * alpha // 255))
    shadow.alpha_composite(shape, (x + 6, y + 26))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
    img.alpha_composite(item, (x, y))


def dodo(img: Image.Image, logo: Image.Image, size: int, x: int, y: int) -> None:
    """Le dodo (logo arrondi) sur un halo blanc flou."""
    halo = Image.new("RGBA", img.size, WHITE + (0,))
    pad = size // 4
    ImageDraw.Draw(halo).ellipse((x - pad, y - pad, x + size + pad, y + size + pad), fill=WHITE + (200,))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(size // 8)))
    paste_with_shadow(img, logo.resize((size, size), Image.LANCZOS), x, y, blur=14, alpha=80)


def render(page_id: str, lang: str) -> Image.Image:
    theme = PAGE_THEME.get(page_id, "neutral")
    _bg, _bg2, accent, ink = THEMES[theme]
    img = background(theme)
    draw = ImageDraw.Draw(img)
    shot_name = SHOTS.get(page_id)
    text_w = 520 if shot_name else 700

    # visuel à droite : capture inclinée dans son cadre + dodo posé dessus, ou le dodo en grand
    logo = Image.open(STATIC / "logo.png").convert("RGBA")
    if shot_name:
        frame = window(Image.open(STATIC / f"app-{shot_name}.png").convert("RGBA"), 640)
        frame = frame.rotate(-3.5, resample=Image.BICUBIC, expand=True)
        paste_with_shadow(img, frame, W - frame.width + 116, 128)
        dodo(img, logo, 150, 650, 424)
    else:
        dodo(img, logo, 300, 800, 150)

    # marque
    img.alpha_composite(rounded(logo.resize((64, 64), Image.LANCZOS), 18), (64, 56))
    brand_font, _ = fonts("en", 38, 20)
    draw.text((144, 68), "DodoTopia", font=brand_font, fill=HEAD)

    # titre et description
    title = i18n.t(lang, f"site.nav.{page_id}")
    if page_id == "home":
        title = i18n.t(lang, "site.footer.tagline").split(".")[0].split("。")[0]
    desc = i18n.t(lang, f"site.meta.{page_id}.description")
    cjk = lang in ("zh-CN", "ja")          # le thaï sépare ses propositions par des espaces
    for size in (68, 58, 50):
        title_font, text_font = fonts(lang, size, 30 if size == 68 else 28)
        title_lines = wrap(draw, title, title_font, text_w, 3, cjk)
        if len(title_lines) <= 2:
            break
    title_lh = int(getattr(title_font, "size", 60) * 1.16)
    text_lh = int(getattr(text_font, "size", 30) * 1.5)
    y = 166 + (0 if len(title_lines) > 2 else 20)
    for line in title_lines:
        draw.text((64, y), line, font=title_font, fill=ink if theme != "neutral" else HEAD)
        y += title_lh
    y += 14
    draw.rounded_rectangle((64, y, 64 + 96, y + 10), 5, fill=accent)
    y += 32
    room = max(1, (H - 118 - y) // text_lh)
    for line in wrap(draw, desc, text_font, text_w, min(4, room), cjk):
        draw.text((64, y), line, font=text_font, fill=INK2)
        y += text_lh

    # pied : pastille du domaine
    pill_font, _ = fonts("en", 26, 20)
    label = "dodotopia.cyber-dodo.fr"
    tw = draw.textlength(label, font=pill_font)
    draw.rounded_rectangle((64, H - 92, 64 + tw + 62, H - 40), 26, fill=WHITE)
    draw.ellipse((84, H - 73, 98, H - 59), fill=accent)
    draw.text((108, H - 85), label, font=pill_font, fill=ink)
    return img.convert("RGB")


def main(argv: list[str]) -> int:
    langs = [a for a in argv if a in i18n.LANGS] or list(i18n.LANGS)
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for lang in langs:
        for page_id in PAGES:
            path = OUT / f"{page_id}-{lang}.png"
            img = render(page_id, lang)
            img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
            img.save(path, optimize=True)
            total += path.stat().st_size
    print(f"{len(langs) * len(PAGES)} images dans {OUT} ({total / 1024 / 1024:.1f} Mo)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
