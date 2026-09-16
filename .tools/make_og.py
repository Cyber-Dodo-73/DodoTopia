# -*- coding: utf-8 -*-
"""Images de partage (Open Graph / Twitter) du site public : une PNG 1200×630 par page et par langue.

    py .tools/make_og.py            génère server/static/og/<page>-<lang>.png (toutes les pages, toutes les langues)
    py .tools/make_og.py fr en      seulement ces langues

Textes : les catalogues du site (`server/app/locales/<lang>.json`, repli en → fr), donc les mêmes que les pages.
Polices : Fredoka (server/static/fonts, sous-ensemble latin) pour les langues latines si Pillow sait la lire,
sinon une police système Windows (Segoe UI Bold) ; Microsoft YaHei (zh-CN), Yu Gothic (ja), Leelawadee UI (th).
Si aucune n'est trouvée, la police par défaut de Pillow. Relancer après une modification des textes `site.meta.*`
ou `site.nav.*`, du logo ou des captures.
"""
from __future__ import annotations

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
PAGES = ("home", "music", "draw", "cook", "together", "download", "instruments", "news", "community", "help",
         "legal", "privacy", "terms")
SHOTS = {"home": "musique", "music": "musique", "draw": "dessin", "cook": "cuisine", "together": "musique"}

CREAM = (244, 234, 216)
CREAM_LIGHT = (255, 248, 234)
BROWN = (79, 64, 57)
INK2 = (108, 92, 82)
TEAL = (24, 123, 117)
TEAL_SOFT = (223, 246, 244)
AMBER = (232, 165, 49)

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
        tokens = list(text)
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
    for idx, tok in enumerate(tokens):
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


def background() -> Image.Image:
    img = Image.new("RGB", (W, H), CREAM)
    glow = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(glow)
    d.ellipse((-300, -360, 700, 360), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img.paste(Image.new("RGB", (W, H), CREAM_LIGHT), (0, 0), glow)
    return img


def render(page_id: str, lang: str) -> Image.Image:
    img = background().convert("RGBA")
    draw = ImageDraw.Draw(img)
    shot_name = SHOTS.get(page_id)
    text_w = 600 if shot_name else 760

    # visuel à droite : capture de l'application ou logo
    logo = Image.open(STATIC / "logo.png").convert("RGBA")
    if shot_name:
        shot = Image.open(STATIC / f"app-{shot_name}.png").convert("RGBA")
        target_w = 620
        shot = shot.resize((target_w, round(shot.height * target_w / shot.width)), Image.LANCZOS)
        shot = rounded(shot, 22)
        x, y = W - target_w + 60, (H - shot.height) // 2 + 20
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((x + 8, y + 18, x + target_w + 8, y + shot.height + 18), 26,
                                                 fill=(107, 90, 82, 70))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
        img.alpha_composite(shot, (x, y))
    else:
        big = logo.resize((330, 330), Image.LANCZOS)
        disc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(disc).ellipse((790, 130, 1160, 500), fill=(255, 255, 255, 170))
        img.alpha_composite(disc.filter(ImageFilter.GaussianBlur(4)))
        img.alpha_composite(big, (810, 150))

    # marque
    small = logo.resize((64, 64), Image.LANCZOS)
    img.alpha_composite(rounded(small, 16), (64, 58))
    brand_font, _ = fonts("en", 38, 20)
    draw.text((144, 70), "DodoTopia", font=brand_font, fill=BROWN)

    # titre et description
    title = "DodoTopia" if page_id == "home" else i18n.t(lang, f"site.nav.{page_id}")
    if page_id == "home":
        title = i18n.t(lang, "site.footer.tagline").split(".")[0].split("。")[0]
    desc = i18n.t(lang, f"site.meta.{page_id}.description")
    cjk = lang in ("zh-CN", "ja")          # le thaï sépare ses propositions par des espaces
    for size in (64, 56, 48):
        title_font, text_font = fonts(lang, size, 30 if size == 64 else 28)
        title_lines = wrap(draw, title, title_font, text_w, 3, cjk)
        if len(title_lines) <= 2:
            break
    title_lh = int(getattr(title_font, "size", 60) * 1.2)
    text_lh = int(getattr(text_font, "size", 30) * 1.5)
    y = 170 + (0 if len(title_lines) > 2 else 20)
    for line in title_lines:
        draw.text((64, y), line, font=title_font, fill=BROWN)
        y += title_lh
    y += 12
    draw.rounded_rectangle((64, y, 64 + 90, y + 8), 4, fill=AMBER)
    y += 28
    room = max(1, (H - 110 - y) // text_lh)
    for line in wrap(draw, desc, text_font, text_w, min(4, room), cjk):
        draw.text((64, y), line, font=text_font, fill=INK2)
        y += text_lh

    # pied : domaine
    pill_font, _ = fonts("en", 26, 20)
    label = "dodotopia.cyber-dodo.fr"
    tw = draw.textlength(label, font=pill_font)
    draw.rounded_rectangle((64, H - 88, 64 + tw + 44, H - 40), 24, fill=TEAL_SOFT)
    draw.text((86, H - 83), label, font=pill_font, fill=TEAL)
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
