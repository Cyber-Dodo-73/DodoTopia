# -*- coding: utf-8 -*-
"""Client en ligne : compte Discord, bibliotheque partagee, moderation, mise a jour, salon."""
import base64
import json
import logging
import os
import shutil
import sys
import threading
import time
from collections import deque

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


class OnlineMixin:
    # ---------------------------------------------------------- en ligne : compte, bibliotheque, moderation
    def _online_call(self, fn, *args, **kw):
        """Appelle une methode du client en ligne / du salon : OnlineError et toute autre exception deviennent
        un toast, jamais une exception vers le JS. Renvoie (ok, resultat)."""
        try:
            return True, fn(*args, **kw)
        except online.OnlineError as e:
            self._notify(str(e), "warn")
        except Exception as e:  # noqa
            self._log(f"en ligne : {e!r}")
            self._notify(i18n.t("api.online.error", error=e), "warn")
        return False, None

    def online_refresh(self):
        self._online_call(self._online.refresh)
        return self.get_state()

    def online_login(self):
        """Ouvre la page de connexion Discord ; renvoie aussi l'URL (bouton Copier de l'interface)."""
        ok, url = self._online_call(self._online.login)
        return {"url": url if ok else None, "state": self.get_state()}

    def online_login_cancel(self):
        self._online_call(self._online.login_cancel)
        return self.get_state()

    def online_logout(self):
        if self._room.active():
            self._room.leave()
        self._online_call(self._online.logout)
        return self.get_state()

    def online_delete_account(self):
        """Supprime le compte DodoTopia sur le serveur (morceaux approuves conserves anonymement, le reste
        efface) puis la session locale. Renvoie {ok, songs_kept, songs_deleted, state}."""
        if self._room.active():
            self._room.leave()
        ok, res = self._online_call(self._online.delete_account)
        out = dict(res) if ok and isinstance(res, dict) else {"ok": False}
        out["state"] = self.get_state()
        return out

    def online_search(self, q="", page=1, sort="recent", tag="", instrument=""):
        """Catalogue partage : texte, tri (recent | popular | trending | likes | title), tag et instrument."""
        self._online_call(self._online.search, q, page, sort, tag, instrument)
        return self.get_state()

    def online_like_song(self, song_id, liked=True):
        """« J'aime » sur un morceau partage : {ok, id, liked, likes, state} (connexion requise)."""
        ok, r = self._online_call(self._online.like_song, song_id, bool(liked))
        out = dict(r) if ok and isinstance(r, dict) else {"ok": False}
        out["state"] = self.get_state()
        return out

    def online_import_url(self, url):
        """Import d'un MIDI par lien (Online Sequencer, BitMidi, lien .mid) : le travail tourne dans un fil,
        son etat est dans get_state()["online"]["jobs"]["imports"][key]. Renvoie {ok, key, error, state}."""
        try:
            key = self._online.import_url(url)
        except online.OnlineError as e:
            msg = online.error_text(e, "import")
            self._notify(msg, "warn")
            return {"ok": False, "key": None, "error": msg, "state": self.get_state()}
        except Exception as e:  # noqa
            self._log(f"import par lien : {e!r}")
            self._notify(i18n.t("api.online.error", error=e), "warn")
            return {"ok": False, "key": None, "error": str(e), "state": self.get_state()}
        return {"ok": True, "key": key, "error": None, "state": self.get_state()}

    def online_download(self, online_id):
        self._online_call(self._online.download, online_id)
        return self.get_state()

    def online_share(self, song_id, meta=None):
        """Depose une musique locale sur le serveur (file de moderation). meta : {tags, instrument, source_url,
        source_name, license, rights} ; `rights` (case « J'ai le droit de partager ce fichier ») est obligatoire
        des que des metadonnees sont envoyees."""
        song_id = os.path.basename(str(song_id or ""))
        path = os.path.join(self._player.songs_folder, song_id)
        if not song_id or not os.path.isfile(path):
            self._notify(i18n.t("api.song.not_found_short"), "warn")
            return self.get_state()
        if meta is not None and not (isinstance(meta, dict) and meta.get("rights") is True):
            self._notify(i18n.t("api.online.share_rights"), "warn")
            return self.get_state()
        title = self._player.library.meta(song_id).get("title") or core.clean_title(song_id)
        if isinstance(meta, dict):
            meta = {k: meta.get(k) for k in ("tags", "instrument", "source_url", "source_name", "license")}
        self._online_call(self._online.share, song_id, path, title, meta)
        return self.get_state()

    # ---------------------------------------------------------- galerie de dessins
    def gallery_list(self, page=1, sort="recent"):
        self._online_call(self._online.drawings_list, page, sort)
        return self.get_state()

    def gallery_share(self, data_url, title="", cells=None):
        """Publie le dessin courant : PNG en data URL (<= 512 Ko, sans badge) et grille {format, w, h, cells}.
        Etat du depot : get_state()["online"]["gallery_upload"]. Renvoie {ok, error, state}."""
        try:
            png = online.decode_png_data_url(data_url, online.DRAWING_PNG_MAX_BYTES)
        except ValueError as e:
            self._notify(i18n.t("api.gallery.png_too_big") if str(e) == "size" else i18n.t("api.gallery.png_invalid"),
                         "warn")
            return {"ok": False, "error": str(e), "state": self.get_state()}
        ok, started = self._online_call(self._online.drawing_upload, png, title, cells)
        return {"ok": bool(ok and started), "error": None if ok else "refused", "state": self.get_state()}

    def gallery_open(self, drawing_id):
        """« Reproduire ce dessin » : recupere la grille en fond, la pose comme travail de dessin ; l'interface
        la reprend par gallery_take(seq) des que get_state()["online"]["drawing_open"] est pret."""
        ok, seq = self._online_call(self._online.open_drawing, drawing_id, self._on_drawing_loaded)
        if ok:
            self._tab = "image"
        return {"ok": bool(ok), "seq": seq if ok else None, "state": self.get_state()}

    def _on_drawing_loaded(self, job, info):
        self.set_draw_job(job)
        self._log(f"dessin {info.get('id')} chargé depuis la galerie ({job['w']}×{job['h']})")

    def gallery_take(self, seq):
        """Grille recuperee par gallery_open, remise une seule fois : {ok, id, title, job}."""
        got = self._online.take_drawing(seq)
        return dict(got, ok=True) if got else {"ok": False}

    def gallery_like(self, drawing_id, liked=True):
        ok, r = self._online_call(self._online.like_drawing, drawing_id, bool(liked))
        out = dict(r) if ok and isinstance(r, dict) else {"ok": False}
        out["state"] = self.get_state()
        return out

    def gallery_delete(self, drawing_id):
        ok, _ = self._online_call(self._online.drawing_delete, drawing_id)
        if ok:
            self._notify(i18n.t("api.gallery.deleted"), "ok")
        return {"ok": bool(ok), "state": self.get_state()}

    def gallery_report(self, drawing_id, reason):
        ok, _ = self._online_call(self._online.drawing_report, drawing_id, reason)
        if ok:
            self._notify(i18n.t("api.gallery.reported"), "ok")
        return {"ok": bool(ok), "state": self.get_state()}

    def online_pending(self, page=1):
        self._online_call(self._online.pending, page)
        return self.get_state()

    def online_moderate(self, online_id, action, reason=""):
        self._online_call(self._online.moderate, online_id, action, reason)
        return self.get_state()

    def online_reports(self):
        self._online_call(self._online.reports)
        return self.get_state()

    def online_resolve_report(self, report_id, action):
        """Admin : classe un signalement ('dismiss') ou retire le morceau signale ('remove_song')."""
        self._online_call(self._online.resolve_report, report_id, action)
        return self.get_state()

    # ---------------------------------------------------------- mise a jour
    def update_check(self):
        self._online_call(self._online.updater.check_async, True)
        return self.get_state()

    def update_download(self):
        self._online_call(self._online.updater.download_async)
        return self.get_state()

    def update_install(self):
        self._online_call(self._online.updater.install)
        return self.get_state()

    def update_dismiss(self):
        self._online_call(self._online.updater.dismiss)
        if self._update_toast_id is not None:
            self.dismiss_toast(self._update_toast_id)
        return self.get_state()

    def update_open_folder(self):
        self._online_call(self._online.updater.open_folder)
        return self.get_state()

    # ---------------------------------------------------------- salon en ligne
    def room_create(self):
        self._online_call(self._room.create)
        return self.get_state()

    def room_exists(self, code):
        """Le salon existe-t-il (et reste-t-il une place) ? {ok, code, valid, exists, full}, sans compte."""
        ok, r = self._online_call(self._online.room_exists, code)
        return dict(r, ok=True) if ok and isinstance(r, dict) else {"ok": False, "code": "", "valid": False,
                                                                    "exists": False, "full": False}

    def room_join(self, code):
        self._online_call(self._room.join, room.normalize_code(code))
        return self.get_state()

    def room_leave(self):
        self._online_call(self._room.leave)
        return self.get_state()

    def room_set_song(self, spec):
        """spec : song_id local (nom de fichier), chemin, ou identifiant en ligne (entier)."""
        self._online_call(self._room.set_song, spec)
        return self.get_state()

    def room_ready(self, on):
        self._online_call(self._room.set_ready, bool(on))
        return self.get_state()

    def room_start(self):
        self._online_call(self._room.start)
        return self.get_state()

    def room_cancel(self):
        self._online_call(self._room.cancel)
        return self.get_state()

    def room_stop(self):
        self._online_call(self._room.stop)
        return self.get_state()

    def room_set_parts(self, spec):
        """Orchestre (chef) : {enabled, parts: {id de siege: {tracks: [index], octave: int|None}}}."""
        self._online_call(self._room.set_parts, spec)
        return self.get_state()

    def room_propose_parts(self):
        """Orchestre (chef) : repartition automatique selon l'instrument de chaque joueur."""
        self._online_call(self._room.propose_parts, self._player.instruments)
        return self.get_state()

    def room_set_offset(self, ms):
        """Avance (negatif) / retard du joueur en ms (-300..300) : reglage multi.net_offset_ms + salon."""
        r = self.set_setting("multi.net_offset_ms", ms)
        if not r.get("ok"):
            self._notify(r.get("error") or i18n.t("api.value_refused"), "warn")
            return self.get_state()
        self._online_call(self._room.set_net_offset, r["value"])
        return self.get_state()

    def quit(self):
        self._integrations_close()
        self._drawer.stop("fermeture")
        self._cook.stop("fermeture")
        self._sync.abort("closing")
        try:
            self._online.close()
        except Exception as e:  # noqa
            self._log(f"en ligne : fermeture : {e}")
        self._player.close()
        if self._window:
            try:
                self._window.destroy()
            except Exception as e:  # noqa
                self._log(f"fenêtre : {e}")
        return True
