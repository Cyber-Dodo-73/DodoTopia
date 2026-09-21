# -*- coding: utf-8 -*-
"""Bibliotheque locale : import, suppression, renommage, favoris, pistes, dossiers, logo."""
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
import draw
import i18n
import instruments
import logging_setup
import online
import platform_io
import room
import settings_schema
import sync
import terms
from version import VERSION

from ._common import IMAGE_MIME, UI_PATH, ICON_PATH, TERMS_GATED, log


class LibraryMixin:
    # ---------------------------------------------------------- bibliotheque
    def import_dialog(self):
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=(i18n.t("api.dialog.midi_files"), i18n.t("api.dialog.all_files")))
        if not files:
            return self.get_state()
        return self.import_paths(list(files))

    def _import_files(self, paths, extra_meta=None):
        """Copie des .mid dans songs/ (suffixe « (2) » si le nom existe), metadonnees, refresh_songs.
        extra_meta (telechargement en ligne) : {title, sha256, online_id, artist} appliques a chaque fichier ;
        le titre sert alors de nom de fichier. Renvoie (added: [song_id], skipped: [nom])."""
        added, skipped = [], []
        lib = self._player.library
        meta = dict(extra_meta or {})
        title = str(meta.get("title") or "").strip()
        for src in paths:
            if not src or not os.path.isfile(src):
                continue
            if not src.lower().endswith((".mid", ".midi")):
                skipped.append(os.path.basename(src))
                continue
            # Le nom vient parfois d'un titre depose par un autre joueur : core.safe_join garantit un nom de
            # fichier sain (pas de separateur, pas de « .. », pas de nom reserve Windows) et un chemin qui
            # reste dans songs/ (defense en profondeur : online.py et room.py assainissent deja le titre).
            base_name = title or os.path.splitext(os.path.basename(src))[0]
            try:
                dst = core.safe_join(self._player.songs_folder, base_name)
            except ValueError:
                skipped.append(os.path.basename(src))
                continue
            name = os.path.basename(dst)
            if os.path.abspath(src) != os.path.abspath(dst):
                base, ext = os.path.splitext(dst)
                n = 2
                while os.path.exists(dst):
                    dst = f"{base} ({n}){ext}"
                    n += 1
                shutil.copy2(src, dst)
            sid = os.path.basename(dst)
            added.append(sid)
            lib.meta(sid)  # titre nettoye + date d'ajout
            if title:
                lib.set_title(sid, title)
            if meta.get("online_id") is not None or meta.get("sha256"):
                lib.set_online(sid, online_id=meta.get("online_id"), sha256=meta.get("sha256"))
            if meta.get("source_url"):
                online.set_source(lib, sid, meta.get("source_url"), meta.get("source_name"))
            if meta.get("artist"):
                with lib._lock:
                    lib.meta(sid)["artist"] = str(meta["artist"])[:120]
                    lib.save()
            try:
                lib.sha256(sid, dst)       # empreinte en cache (bibliotheque en ligne, salons)
            except Exception as e:  # noqa
                self._log(f"empreinte de {sid} : {e}")
        self._player.refresh_songs()
        return added, skipped

    def import_paths(self, paths):
        """Import multiple : le resultat est donne fichier par fichier quand certains echouent."""
        added, skipped = self._import_files(paths)
        if added:
            self._player.index = self._player.songs.index(
                os.path.join(self._player.songs_folder, added[-1]))
            self._notify(i18n.t("api.import.added", n=len(added)), "ok")
        if skipped:
            names = ", ".join(skipped[:3]) + (" " + i18n.t("api.and_others", n=len(skipped) - 3) if len(skipped) > 3 else "")
            if added:
                self._notify(i18n.t("api.import.skipped", n=len(skipped), names=names), "warn")
            else:
                self._notify(i18n.t("api.import.nothing", names=names), "warn")
        return self.get_state()

    def remove_song(self, song_id):
        path = os.path.join(self._player.songs_folder, song_id)
        if os.path.isfile(path):
            if self._player.current() == path:
                self._player.stop(join=True)
            os.remove(path)
            self._player.library.remove(song_id)
            self._player.refresh_songs()
            self._notify(i18n.t("api.song.removed"))
        return self.get_state()

    def rename_song(self, song_id, title):
        path = os.path.join(self._player.songs_folder, song_id)
        if os.path.isfile(path):
            self._player.library.set_title(song_id, title)
        return self.get_state()

    def toggle_favorite(self, song_id):
        path = os.path.join(self._player.songs_folder, song_id)
        if os.path.isfile(path):
            self._player.library.toggle_fav(song_id)
        return self.get_state()

    def song_tracks(self, song_id):
        """Pistes du fichier MIDI (index, nom, nombre de notes, canaux) et celles ignorees a la lecture."""
        path = os.path.join(self._player.songs_folder, song_id)
        if not os.path.isfile(path):
            return {"ok": False, "error": i18n.t("api.song.not_found"), "tracks": [], "off": []}
        try:
            tracks = core.midi_tracks(path)
        except core.MidiRefused as e:
            return {"ok": False, "error": str(e), "tracks": [], "off": []}
        return {"ok": True, "tracks": tracks, "off": self._player.song_skip_tracks(path)}

    def set_song_tracks(self, song_id, off):
        """Choix des pistes ignorees pour ce morceau (liste d'index). Efface le diagnostic en cache."""
        path = os.path.join(self._player.songs_folder, song_id)
        if os.path.isfile(path):
            try:
                self._player.library.set_tracks_off(song_id, off)
            except (TypeError, ValueError):
                pass
            self._compat_key = None
            self._compat_notes = None
        return self.get_state()

    def test_key(self):
        """« Tester une note » : envoie la premiere touche de l'instrument au jeu apres le delai de depart, et
        dit si les touches atteignent bien le jeu. Renvoie {ok, reason, state}."""
        p = self._player
        inst = p.instrument
        if p.state != "stopped":
            return {"ok": False, "reason": i18n.t("api.test_key.stop_first"), "state": self.get_state()}
        keys = list(getattr(inst, "offset_to_key", {}).values())
        if not keys:
            return {"ok": False, "reason": i18n.t("api.test_key.no_keys"), "state": self.get_state()}
        key = keys[len(keys) // 2]
        delay = float(self._cfg.get("start_delay", 1.0))
        time.sleep(max(0.2, delay))
        front = p._game_in_front()
        if front is False:
            proc, title = platform_io.foreground_window()
            self._log(f"test d'une note : fenêtre au premier plan = {proc or '?'} « {title or ''} »")
            name = "Heartopia"
            return {"ok": False, "reason": i18n.t("api.test_key.not_focused", name=name, delay=delay),
                    "state": self.get_state()}
        try:
            p.play_keys([key], hold=0.12)
        except platform_io.InjectionError as e:
            return {"ok": False, "reason": i18n.t("api.test_key.denied", code=e.code, admin=bool(self._is_admin)),
                    "state": self.get_state()}
        except Exception as e:  # noqa
            return {"ok": False, "reason": i18n.t("api.test_key.failed", error=e), "state": self.get_state()}
        label = instruments.key_label(key, self._keyboard_layout())
        return {"ok": True, "reason": i18n.t("api.test_key.sent", label=label), "key": key, "state": self.get_state()}

    def open_draw_log(self):
        path = os.path.join(core.DATA_DIR, "dessin.log")
        if os.path.isfile(path):
            platform_io.open_text_file(path)
        else:
            self._notify(i18n.t("api.log.none_draw"), "warn")
        return True

    def open_songs_folder(self):
        platform_io.open_folder(self._player.songs_folder)
        return True

    def open_data_folder(self):
        """Dossier des donnees (config.json, journaux, bibliotheque) : Reglages > General / A propos."""
        platform_io.open_folder(core.DATA_DIR)
        return True

    # Pages ouvertes depuis « A propos ». Liste fermee : l'interface ne choisit pas une URL libre.
    SITE_PAGES = {"site": "", "mentions": "/mentions-legales", "confidentialite": "/confidentialite",
                  "conditions": "/conditions"}

    def open_site(self, page="site"):
        """Ouvre une page du site DodoTopia dans le navigateur (le depot n'est pas public)."""
        if page not in self.SITE_PAGES:
            return False
        url = online.ensure_defaults(self._cfg)["server_url"] + self.SITE_PAGES[page]
        try:
            platform_io.open_url(url)
        except Exception as e:  # noqa
            self._notify(i18n.t("api.browser_failed", error=e), "warn")
            return False
        return True

    def open_log(self, name="multi"):
        """Ouvre un journal du dossier de donnees : multi | dessin | cuisine | online."""
        if name not in ("multi", "dessin", "cuisine", "online"):
            return False
        path = os.path.join(core.DATA_DIR, f"{name}.log")
        if os.path.isfile(path):
            platform_io.open_text_file(path)
        else:
            self._notify(i18n.t("api.log.none"), "warn")
        return True
