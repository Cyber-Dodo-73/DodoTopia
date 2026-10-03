# -*- coding: utf-8 -*-
"""Constantes et journal partages par les mixins de l'Api (voir api/__init__.py)."""
import logging
import os

import core

log = logging.getLogger("app")

# Methodes de l'Api qui agissent (jeu, souris, reseau, fichiers) : refusees tant que les CGU en vigueur ne
# sont pas acceptees. La garde est posee au niveau de la classe (voir _install_terms_gate) pour qu'aucune
# methode ne puisse etre oubliee lors d'un ajout : la liste est la seule chose a maintenir.
TERMS_GATED = (
    "play_game", "preview", "set_play_mode", "multi_calibrate", "multi_test", "multi_listen_test",
    "draw_start", "draw_auto_calibrate", "draw_calibrate", "cook_start", "cook_test", "cook_calibrate",
    "import_dialog", "import_paths", "import_image_dialog", "load_image",
    "instrument_wizard_test", "online_login", "online_download", "online_share", "online_refresh",
    "room_create", "room_join", "update_download", "update_install", "test_key",
    "deeplink_confirm", "register_protocol",
    "online_like_song", "online_import_url", "gallery_share", "gallery_open", "gallery_like", "gallery_delete",
    "gallery_report", "open_external", "save_drawing_png",
    "creations_replace_dialog", "creations_replace", "creations_restore", "creations_export",
    "creations_choose_folder", "creations_set_folder", "creations_add_dialog", "creations_add", "creations_delete",
    "creations_listen", "creations_studio_open", "creations_studio_listen", "creations_studio_add", "creations_studio_edit", "creations_learn",
)

UI_PATH = os.path.join(core.RES_DIR, "ui", "index.html")
ICON_PATH = os.path.join(core.RES_DIR, "assets", "logo.ico")
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".bmp": "image/bmp", ".webp": "image/webp"}
