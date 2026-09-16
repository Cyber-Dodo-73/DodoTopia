# -*- coding: utf-8 -*-
"""DodoTopia : interface graphique (fenetre WebView2 + moteur core.py)."""
import base64
import json
import logging
import os
import shutil
import sys
import threading
import time
from collections import deque

import webview

import cook
import core
import deeplink
import draw
import instruments
import logging_setup
import online
import platform_io
import room
import settings_schema
import single_instance
import sync
import terms
from version import VERSION
from api import Api, TERMS_GATED, UI_PATH, ICON_PATH, IMAGE_MIME  # noqa: F401 (re-exportes : app.Api)

log = logging.getLogger("app")

def _fatal(msg):
    """Erreur avant l'ouverture de la fenetre : sans console en version fenetree, une boite Windows est le
    seul moyen de le dire. Journalise dans tous les cas."""
    log.critical("%s", msg)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(msg), "DodoTopia", 0x10)
    except Exception:  # noqa : pas sous Windows, ou pas de bureau
        try:
            print(msg, file=sys.stderr)
        except Exception:  # noqa
            pass
    sys.exit(1)


def main():
    logging_setup.setup(core.DATA_DIR, debug="--debug" in sys.argv)
    log.info("DodoTopia %s démarre (%s)", VERSION, "exe" if core.FROZEN else "sources")
    # instance unique : un deuxieme lancement (double clic, lien dodotopia://) confie ses arguments a la
    # fenetre deja ouverte et s'arrete la, avant de creer l'Api (fils, peripheriques, raccourcis globaux)
    instance = single_instance.SingleInstance(core.DATA_DIR)
    if not instance.acquire(sys.argv[1:]):
        return
    # coordonnees physiques de l'ecran (souris, captures) meme avec une mise a l'echelle Windows
    platform_io.set_dpi_aware()
    platform_io.set_app_id()      # icone de la barre des taches liee a DodoTopia, pas au cache de l'hote
    try:
        api = Api()
    except Exception as e:  # noqa : catalogue absent, dossier de donnees en lecture seule...
        log.exception("démarrage impossible")
        instance.close()
        _fatal(f"DodoTopia ne peut pas démarrer : {e}\n\nJournal : {logging_setup.log_path(core.DATA_DIR)}")
        return
    # lien du lancement (--url dodotopia://...) : demande de confirmation dans get_state()["deeplink"]
    for url in deeplink.urls_from_argv(sys.argv[1:]):
        api.handle_deeplink(url)
    title = "DodoTopia"
    window = webview.create_window(
        title, UI_PATH, js_api=api,
        width=1040, height=720, min_size=(960, 660),
        background_color="#f4ead8")
    api._window = window
    instance.set_handler(api._on_forwarded_argv)     # lancements suivants : liens relayes, fenetre au premier plan
    api._online.start_background()      # sante du serveur, /api/me, mise a jour, empreintes (thread daemon)

    def on_loaded():
        platform_io.set_window_icon(title, ICON_PATH)
        if "--updated" in sys.argv:      # relance par l'installeur apres une mise a jour silencieuse
            api._notify(f"Mise à jour vers {VERSION} réussie", "ok")
        try:
            body = window.dom.get_element("body")

            def on_drop(e):
                files = e.get("dataTransfer", {}).get("files", [])
                paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
                if not paths:
                    api._notify("Glisser-déposer indisponible ici, utilise le bouton Importer", "warn")
                    return
                images = [p for p in paths if os.path.splitext(p)[1].lower() in IMAGE_MIME]
                others = [p for p in paths if p not in images]
                if images:
                    payload = api.load_image(images[0])
                    if payload:
                        window.evaluate_js("loadImageData(%s)" % json.dumps(payload))
                if others:
                    api.import_paths(others)
            body.events.drop += on_drop
        except Exception as e:  # noqa
            api._log(f"drag&drop non disponible : {e}")

    window.events.loaded += on_loaded
    # Stockage persistant : sans lui (private_mode par defaut), localStorage est vide a chaque lancement et le
    # theme, la decouverte deja faite et les preferences d'affichage seraient oublies.
    webview.start(debug="--debug" in sys.argv, private_mode=False,
                  storage_path=os.path.join(core.DATA_DIR, "webview"),
                  **platform_io.webview_start_kwargs(core.RES_DIR))
    instance.close()
    api._integrations_close()
    api._drawer.stop("fermeture")
    api._cook.stop("fermeture")
    try:
        api._online.close()
    except Exception as e:  # noqa
        api._log(f"en ligne : fermeture : {e}")
    api._player.close()


if __name__ == "__main__":
    main()
