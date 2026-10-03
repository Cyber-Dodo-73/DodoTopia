# -*- coding: utf-8 -*-
"""Déclinaisons WebP des images du site public (captures de l'application et dodo), à partir des PNG d'origine.

    py .tools/make_shots.py

Produit dans `server/static/` :
  app-<nom>-730.webp, app-<nom>-1460.webp   captures pour `<source type="image/webp" srcset>` (qualité 82)
  dodo-96.webp, dodo-512.webp               le dodo du logo (en-tête / pied, héros)
Les PNG restent la source (`<img src>`, repli des navigateurs sans WebP). Vérifie aussi le poids du dossier
`server/static/art/` (< 40 Ko) et qu'aucun SVG n'y porte de `style` (la CSP de /static les bloquerait).
Relancer après une nouvelle capture de l'application ou un changement de logo.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

STATIC = Path(__file__).resolve().parents[1] / "server" / "static"
ART = STATIC / "art"
SHOTS = ("musique", "dessin", "cuisine", "creations")
SHOT_WIDTHS = (730, 1460)
DODO_SIZES = (96, 512)
QUALITY = 82
ART_BUDGET = 40 * 1024
SVG_BUDGET = 2 * 1024


def save_webp(img: Image.Image, path: Path, quality: int = QUALITY) -> int:
    img.save(path, "WEBP", quality=quality, method=6)
    return path.stat().st_size


def main() -> int:
    total = 0
    for name in SHOTS:
        src = Image.open(STATIC / f"app-{name}.png").convert("RGB")
        for width in SHOT_WIDTHS:
            img = src if width >= src.width else src.resize((width, round(src.height * width / src.width)),
                                                            Image.LANCZOS)
            size = save_webp(img, STATIC / f"app-{name}-{width}.webp")
            total += size
            print(f"app-{name}-{width}.webp  {img.width}×{img.height}  {size / 1024:.0f} Ko")
    logo = Image.open(STATIC / "logo.png").convert("RGBA")
    for px in DODO_SIZES:
        # affiché à la moitié de sa taille au plus (écrans 2x) : 96 -> 48 px, 512 -> 256 px
        size = save_webp(logo.resize((px, px), Image.LANCZOS), STATIC / f"dodo-{px}.webp", quality=88)
        total += size
        print(f"dodo-{px}.webp  {size / 1024:.0f} Ko")
    print(f"total WebP : {total / 1024:.0f} Ko")

    code = 0
    art_total = 0
    for svg in sorted(ART.glob("*.svg")):
        data = svg.read_text(encoding="utf-8")
        art_total += len(data.encode("utf-8"))
        if "style" in data:
            print(f"ERREUR {svg.name} : attribut ou balise style (bloqué par la CSP de /static)")
            code = 1
        if len(data.encode("utf-8")) > SVG_BUDGET:
            print(f"ERREUR {svg.name} : {len(data)} octets (> {SVG_BUDGET})")
            code = 1
    print(f"art/ : {art_total / 1024:.1f} Ko pour {len(list(ART.glob('*.svg')))} SVG (budget {ART_BUDGET // 1024} Ko)")
    if art_total >= ART_BUDGET:
        print("ERREUR art/ dépasse son budget")
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
