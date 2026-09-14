# -*- coding: utf-8 -*-
"""Genere assets/logo.ico a partir de assets/logo.png.

Pillow sait ecrire un .ico en une ligne, mais il reduit lui-meme l'image avec un filtre mediocre : a 32 et
16 pixels le dodo devient une bouillie. On reduit donc chaque taille en LANCZOS avant de les assembler.
L'image source est aussi recadree en carre : une icone Windows est carree, sinon elle est deformee.

Usage : py make_icon.py [source.png] [destination.ico]   (defaut : assets/logo.png -> assets/logo.ico)
Appele par build.bat avant PyInstaller.
"""
import os
import sys

from PIL import Image

# 24 px sert aux petites listes de l'explorateur, 256 px a l'affichage en grandes icones
SIZES = [256, 128, 64, 48, 32, 24, 16]
HERE = os.path.dirname(os.path.abspath(__file__))


def square(im):
    """Image carree, l'originale centree sur un fond transparent (aucune deformation)."""
    w, h = im.size
    if w == h:
        return im
    side = max(w, h)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(im, ((side - w) // 2, (side - h) // 2))
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join("assets", "logo.png")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join("assets", "logo.ico")
    src = src if os.path.isabs(src) else os.path.join(HERE, src)
    dst = dst if os.path.isabs(dst) else os.path.join(HERE, dst)
    if not os.path.isfile(src):
        sys.exit(f"ERREUR : {src} introuvable")

    im = square(Image.open(src).convert("RGBA"))
    sizes = [n for n in SIZES if n <= max(im.size)] or [min(im.size)]
    images = [im.resize((n, n), Image.LANCZOS) for n in sizes]
    images[0].save(dst, format="ICO", sizes=[(n, n) for n in sizes], append_images=images[1:])
    print(f"{os.path.relpath(dst, HERE)} genere depuis {os.path.relpath(src, HERE)} "
          f"({' '.join(str(n) for n in sizes)} px)")


if __name__ == "__main__":
    main()
