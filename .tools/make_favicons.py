# -*- coding: utf-8 -*-
"""Icônes du site public, à partir du vrai logo (server/static/logo.png, 512×512, tuile arrondie avec le dodo).

    py .tools/make_favicons.py          écrit dans server/static :
        favicon.ico            16, 32 et 48 px (onglets des navigateurs, favoris Windows)
        favicon-96.png         96 px  : taille carrée multiple de 48 demandée par Google pour la favicon des résultats
        favicon-192.png        192 px : Android / Chrome, et une source nette pour tout affichage entre 96 et 192 px
        apple-touch-icon.png   180 px, aplati sur le crème du site (iOS met du noir sous la transparence)

Chaque taille est réduite en LANCZOS depuis le PNG source (Pillow réduit mal tout seul : à 16 et 32 px le dodo
devenait une bouillie, voir make_icon.py). Les fichiers gardent des noms stables, sans empreinte : Google et les
navigateurs demandent une URL de favicon qui ne change pas. Relancer après un changement de logo, puis contrôler
`.tools/ux_check.py --seo`. Les balises `<link rel="icon">` correspondantes sont dans `server/app/site.py` (head).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"
SOURCE = STATIC / "logo.png"
ICO_SIZES = (48, 32, 16)
PNG_SIZES = {"favicon-96.png": 96, "favicon-192.png": 192}
APPLE = ("apple-touch-icon.png", 180)
CREAM = (255, 249, 239)                 # `theme-color` clair du site (site.py)


def square(im: Image.Image) -> Image.Image:
    """Image carrée : l'originale centrée sur un fond transparent (une icône déformée est pire qu'une petite)."""
    w, h = im.size
    if w == h:
        return im
    side = max(w, h)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(im, ((side - w) // 2, (side - h) // 2))
    return out


def shrink(im: Image.Image, px: int) -> Image.Image:
    return im.resize((px, px), Image.LANCZOS)


def main() -> int:
    if not SOURCE.is_file():
        print(f"ERREUR : {SOURCE} introuvable", file=sys.stderr)
        return 1
    logo = square(Image.open(SOURCE).convert("RGBA"))
    written = []

    frames = [shrink(logo, n) for n in ICO_SIZES]
    ico = STATIC / "favicon.ico"
    frames[0].save(ico, format="ICO", sizes=[(n, n) for n in ICO_SIZES], append_images=frames[1:])
    written.append(ico)

    for name, px in PNG_SIZES.items():
        path = STATIC / name
        shrink(logo, px).save(path, format="PNG", optimize=True)
        written.append(path)

    name, px = APPLE
    flat = Image.new("RGBA", (px, px), CREAM + (255,))
    flat.alpha_composite(shrink(logo, px))
    path = STATIC / name
    flat.convert("RGB").save(path, format="PNG", optimize=True)
    written.append(path)

    for path in written:
        with Image.open(path) as check:
            sizes = sorted(check.ico.sizes()) if check.format == "ICO" else [check.size]
        print(f"{path.relative_to(ROOT)}  {check.format}  {' '.join(f'{w}x{h}' for w, h in sizes)}  "
              f"{path.stat().st_size / 1024:.1f} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
