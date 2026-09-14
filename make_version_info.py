# -*- coding: utf-8 -*-
"""Genere build/version_info.txt : les metadonnees Windows de DodoTopia.exe (onglet Details des proprietes).

Un binaire sans editeur, sans description et sans version est un signal de mefiance de plus pour
SmartScreen et pour l'utilisateur qui lit l'avertissement. Ces informations ne remplacent pas une
signature de code, mais elles coutent zero euro et rendent l'executable identifiable.

Usage : py make_version_info.py [destination]    (defaut : build/version_info.txt)
Appele par build.bat / build.sh avant PyInstaller (option --version-file).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPANY = "Dodo"
PRODUCT = "DodoTopia"
DESCRIPTION = "DodoTopia - boite a outils pour Heartopia (musique, dessin, cuisine)"
COPYRIGHT = "Dodo"

TEMPLATE = """# Genere par make_version_info.py : ne pas editer a la main.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, 0),
    prodvers=({v0}, {v1}, {v2}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040C04B0',
        [StringStruct('CompanyName', {company!r}),
         StringStruct('FileDescription', {description!r}),
         StringStruct('FileVersion', {version!r}),
         StringStruct('InternalName', {product!r}),
         StringStruct('LegalCopyright', {copyright!r}),
         StringStruct('OriginalFilename', 'DodoTopia.exe'),
         StringStruct('ProductName', {product!r}),
         StringStruct('ProductVersion', {version!r})])
    ]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
"""


def read_version():
    src = open(os.path.join(HERE, "version.py"), encoding="utf-8").read()
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
    if not m:
        sys.exit("ERREUR : VERSION introuvable dans version.py")
    return m.group(1)


def main():
    dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join("build", "version_info.txt")
    dst = dst if os.path.isabs(dst) else os.path.join(HERE, dst)
    version = read_version()
    parts = [int(x) for x in re.findall(r"\d+", version)][:3]
    while len(parts) < 3:
        parts.append(0)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(v0=parts[0], v1=parts[1], v2=parts[2], version=version,
                                company=COMPANY, product=PRODUCT, description=DESCRIPTION,
                                copyright=COPYRIGHT))
    print(f"{os.path.relpath(dst, HERE)} genere (version {version})")


if __name__ == "__main__":
    main()
