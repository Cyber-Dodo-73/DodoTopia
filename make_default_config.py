# -*- coding: utf-8 -*-
"""Genere config.default.json : la configuration livree avec l'app, sans aucun calibrage personnel.

En mode source, DATA_DIR est le dossier du projet : config.json contient donc les reglages ET le calibrage
de la machine de developpement (position de la palette, des outils, de la bulle de la cuisine, images de
reference...). Livrer ce fichier donnerait a chaque nouvel utilisateur des coordonnees d'ecran fausses, avec
un module Cuisine qui se croirait deja calibre.

Usage : py make_default_config.py [source] [destination]   (defaut : config.json -> config.default.json)
Appele automatiquement par build.bat / build.sh avant PyInstaller.
"""
import json
import os
import sys

# Cles a remettre a zero : tout ce qui depend de l'ecran, du compte ou de l'historique de la machine.
PALETTE_KEYS = ("pos0", "pos1", "btn", "strip", "prev", "next", "sub0", "sub1")
TOOL_KEYS = ("pencil", "bucket", "undo")
MULTI_RESET = {"player_id": 1, "offset_ms": 0, "latency": None, "beacon_freqs": None, "tune": 1.0,
               "device": "", "calib": None, "last_room": None, "name": "", "net_offset_ms": 0,
               "enabled": False, "mode": "solo"}
COOK_RESET = {"points": {}, "refs": {}, "cook_btn_color": None, "ring_color": None}


def sanitize(cfg):
    """Renvoie une copie de `cfg` sans calibrage ni preference locale."""
    cfg = json.loads(json.dumps(cfg))          # copie profonde
    cfg.pop("_instruments", None)

    d = cfg.get("draw")
    if isinstance(d, dict):
        pal = d.get("palette")
        if isinstance(pal, dict):
            for k in PALETTE_KEYS:
                if k in pal:
                    pal[k] = None              # les couleurs et la taille de la grille restent : constantes du jeu
        tools = d.get("tools")
        if isinstance(tools, dict):
            for k in TOOL_KEYS:
                if k in tools:
                    tools[k] = None
        d["formats"] = {}                      # rect + validated + grilles mesurees : propres a l'ecran

    c = cfg.get("cook")
    if isinstance(c, dict):
        c.update(COOK_RESET)

    m = cfg.get("multi")
    if isinstance(m, dict):
        for k, v in MULTI_RESET.items():
            if k in m or k in ("mode", "enabled"):
                m[k] = v

    # preferences de session, pas des reglages a livrer
    cfg["instrument"] = "piano"
    cfg["speed"] = 1.0
    cfg["transpose_semitones"] = 0
    if os.path.isabs(str(cfg.get("songs_folder", "songs"))):
        cfg["songs_folder"] = "songs"
    cfg.pop("online", None)                    # l'URL du serveur a ses valeurs par defaut dans online.py
    return cfg


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "config.default.json"
    here = os.path.dirname(os.path.abspath(__file__))
    src = src if os.path.isabs(src) else os.path.join(here, src)
    dst = dst if os.path.isabs(dst) else os.path.join(here, dst)

    # config.json n'est pas versionne (il contient le calibrage de la machine de developpement) : sur un
    # runner d'integration continue il n'existe pas, et config.default.json du depot fait deja foi.
    if not os.path.exists(src):
        if os.path.exists(dst):
            print(f"{os.path.basename(src)} absent : {os.path.basename(dst)} du depot conserve tel quel.")
            return
        sys.exit(f"ERREUR : ni {os.path.basename(src)} ni {os.path.basename(dst)} dans {here}.")

    with open(src, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    clean = sanitize(cfg)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
    print(f"{os.path.basename(dst)} genere depuis {os.path.basename(src)} "
          f"({len(clean.get('instruments', {}))} instruments, calibrages retires)")


if __name__ == "__main__":
    main()
