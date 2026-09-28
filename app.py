# -*- coding: utf-8 -*-
"""DodoTopia : interface graphique (fenetre WebView2 + moteur core.py)."""
import base64
import hashlib
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

# caches HTTP de WebView2 (dans le profil persistant) a vider quand l'interface change
WEBVIEW_CACHES = ("Cache", "Code Cache", "GPUCache")


def refresh_ui_cache(storage, ui_dir):
    """Vide le cache HTTP de WebView2 si un fichier de l'interface a change depuis le dernier lancement.

    Le profil est persistant (localStorage), cache HTTP compris : apres une mise a jour, WebView2 pouvait
    resservir l'ancienne index.html avec les nouveaux scripts (boutons sans effet). Signature = nom, taille et
    date de chaque fichier de ui/ ; le stockage local (preferences) n'est jamais touche. Renvoie True si vide."""
    parts = []
    for root, _, files in os.walk(ui_dir):
        for f in sorted(files):
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            parts.append(f"{os.path.relpath(p, ui_dir)}:{st.st_size}:{int(st.st_mtime)}")
    sig = hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()[:16] + ":" + VERSION   # hash() varie a chaque lancement
    marker = os.path.join(storage, "ui.sig")
    try:
        with open(marker, encoding="utf-8") as f:
            if f.read().strip() == sig:
                return False
    except OSError:
        pass
    for name in WEBVIEW_CACHES:
        shutil.rmtree(os.path.join(storage, "EBWebView", "Default", name), ignore_errors=True)
    try:
        os.makedirs(storage, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(sig)
    except OSError:
        pass
    log.info("interface modifiée : cache de WebView2 vidé")
    return True


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
    if platform_io.OVERLAY_OK:
        # overlay au-dessus du jeu (api/overlay.py) : cree cache, ne s'affiche que jeu devant + musique/dessin
        overlay = webview.create_window(
            "DodoTopia overlay", os.path.join(os.path.dirname(UI_PATH), "overlay.html"),
            width=340, height=104, frameless=True, on_top=True, focus=False, shadow=False, hidden=True,
            resizable=False, background_color="#fffaf1")
        api._overlay_attach(overlay)

        def close_overlay():
            # pywebview ne rend la main que quand TOUTES les fenetres sont fermees : sans cela, l'overlay cachee
            # gardait DodoTopia en vie apres la fermeture (processus fantome qui garde le verrou d'instance
            # et les raccourcis ; le lancement suivant lui etait transmis et rien ne s'affichait)
            api._overlay_close()
            try:
                overlay.destroy()
            except Exception:  # noqa
                pass
        window.events.closed += close_overlay
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
    storage = os.path.join(core.DATA_DIR, "webview")
    refresh_ui_cache(storage, os.path.dirname(UI_PATH))
    webview.start(debug="--debug" in sys.argv, private_mode=False,
                  storage_path=storage,
                  **platform_io.webview_start_kwargs(core.RES_DIR))
    instance.close()
    api._overlay_close()
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
