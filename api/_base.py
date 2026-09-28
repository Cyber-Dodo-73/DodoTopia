# -*- coding: utf-8 -*-
"""Socle de l'Api : conditions d'utilisation (garde), liaisons avec le client en ligne, journal, toasts, bascules F6 des trois activites."""
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

# ui_log : garde-fous du relais des erreurs de l'interface (etat au niveau du module : l'Api est un singleton)
_UI_LOG_LEVELS = ("error", "warn", "info")
_UI_LOG_MAX_CHARS = 500
_UI_LOG_PER_MINUTE = 20
_ui_log_times = deque()
_ui_log_lock = threading.Lock()


class BaseMixin:
    # ---------------------------------------------------------- conditions d'utilisation
    def _terms_blocked(self):
        """Vrai (et toast) si les CGU en vigueur ne sont pas acceptees : rien ne doit agir avant."""
        if not terms.required(self._cfg):
            return False
        self._notify(i18n.t("api.terms.accept_first"), "warn")
        return True

    def get_terms(self, lang="fr"):
        """Texte des CGU pour l'ecran d'acceptation : {version, lang, summary, markdown, html}."""
        try:
            return terms.load(core.RES_DIR, lang)
        except Exception:  # noqa : tout est journalise, l'ecran des CGU affiche son message d'erreur
            try:
                legal = terms.legal_dir(core.RES_DIR)
                found = sorted(os.listdir(legal)) if os.path.isdir(legal) else None
            except OSError:
                found = None
            log.exception("CGU illisibles : chemin tenté %s ; RES_DIR = %s ; dossier legal %s",
                          terms.path_for(core.RES_DIR, lang), core.RES_DIR,
                          "absent" if found is None else f"présent, contenu : {found}")
            return None

    def ui_log(self, level, msg):
        """Relais des erreurs JavaScript vers dodotopia.log (la console du navigateur est invisible dans l'application
        gelee). Niveau borne, message tronque a 500 caracteres, au plus 20 lignes par minute : le reste est ignore."""
        level = level if level in _UI_LOG_LEVELS else "error"
        text = " ".join(str(msg).split())[:_UI_LOG_MAX_CHARS]
        now = time.monotonic()
        with _ui_log_lock:
            while _ui_log_times and now - _ui_log_times[0] >= 60.0:
                _ui_log_times.popleft()
            if len(_ui_log_times) >= _UI_LOG_PER_MINUTE:
                return False
            _ui_log_times.append(now)
        log.warning("UI: [%s] %s", level, text)
        return True

    def accept_terms(self, version, lang="fr"):
        """Acceptation des CGU depuis l'ecran bloquant : enregistree dans la configuration et le journal."""
        if terms.accept(self._cfg, version, lang):
            core.save_config(self._cfg)
            log.info("CGU version %s acceptées (%s)", version, lang)
            self._notify(i18n.t("api.terms.accepted"), "ok")
            if not terms.required(self._cfg):
                self._flush_pending_links()       # liens dodotopia:// recus avant l'acceptation
        else:
            self._notify(i18n.t("api.terms.outdated"), "warn")
        return self.get_state()

    def _play_mode(self):
        """Mode de jeu EFFECTIF : « room » tant qu'on est dans un salon (quitter ramene au solo sans autre
        geste), sinon « audio » si la synchro par le son est activee, sinon « solo ». Le salon n'est plus un
        reglage memorise : c'etait lui qui detournait F6 apres un salon quitte."""
        if self._room.active():
            return "room"
        return "audio" if (self._cfg.get("multi") or {}).get("mode") == "audio" else "solo"

    def _music_toggle(self):
        """F6 / bouton Jouer : routeur selon le mode de jeu. room : salon en ligne (lobby : chef = top depart,
        autres = Pret ; compte a rebours : annuler ; lecture : stop) ; audio : top depart par note repere ;
        solo : lecture directe."""
        if self._terms_blocked():
            return
        p = self._player
        mode = self._play_mode()
        if mode == "room":
            self._room.on_f6()
        elif self._sync.active():
            self._sync.abort("stop")
        elif mode == "audio" and p.state == "stopped":
            self._sync.start()
        else:
            p.play_pause("game")

    def _draw_toggle(self, from_ui=False, job=None):
        """job : travail impose (reprise) ; sinon l'image de l'onglet, ou a defaut le dessin interrompu."""
        d = self._drawer
        job = job or self._draw_job or d.resume_job()
        if d.state in ("drawing", "autocal"):
            d.stop("stop")
        elif d.state == "calibrating":
            d.capture_point()
        elif job:
            if self._player.state != "stopped":
                self._player.stop(join=True)
            # depuis le bouton : 3 s pour passer sur le jeu, et la fenetre se reduit pour ne pas gener
            if d.start(job, delay=3.0 if from_ui else 1.0) and from_ui and self._window:
                try:
                    self._window.minimize()
                    self._minimized = True
                except Exception:
                    pass
        else:
            self._notify(i18n.t("api.draw.import_first"), "warn")

    def _cook_toggle(self, from_ui=False):
        """F6 / bouton Cuisiner en boucle : lance ou arrete la cuisine (ou capture un point en calibrage)."""
        c = self._cook
        if c.state == "cooking":
            c.stop("stop")
        elif c.state == "calibrating":
            c.capture_point()
        elif not c.calibrated():
            self._notify(i18n.t("api.cook.configure_first"), "warn")
        else:
            if self._player.state != "stopped":
                self._player.stop(join=True)
            if self._drawer.state in ("drawing", "autocal"):
                self._drawer.stop("cuisine")
            if c.start(delay=3.0 if from_ui else 1.0) and from_ui and self._window:
                try:
                    self._window.minimize()
                    self._minimized = True
                except Exception:
                    pass

    def _on_module_change(self):
        """Appele par le dessin et la cuisine quand leur etat change : toast des messages, retour de la fenetre."""
        d, c = self._drawer, self._cook
        if d.message and d.message != self._draw_msg:
            self._draw_msg = d.message
            ok = any(w in d.message for w in ("enregistré", "terminé"))
            self._notify(d.message, "ok" if ok else "warn")
        if c.message and c.message != self._cook_msg:
            self._cook_msg = c.message
            ok = any(w in c.message for w in ("enregistré", "terminé", "atteint"))
            self._notify(c.message, "ok" if ok else "warn")
        busy = d.state in ("drawing", "autocal") or c.state == "cooking"
        if not busy and self._minimized and self._window:
            self._minimized = False
            try:
                self._window.restore()
            except Exception:
                pass

    def _log(self, msg):
        self._logs.append({"t": time.time(), "msg": str(msg)})
        log.info("%s", msg)

    def _notify(self, msg, kind="info", sticky=False, action=None, progress=None):
        """Toast pour l'interface. kind : info | ok | warn | danger. sticky : reste affiche jusqu'a dismiss_toast(id)
        ou clic sur l'action ({"label", "method", "args"} = methode de l'Api a appeler) ; progress : 0-100 ou None.
        Renvoie l'id, a passer a _update_toast pour faire evoluer un toast persistant."""
        with self._ui_lock:
            self._toast_seq += 1
            self._toasts.append({"id": self._toast_seq, "t": time.time(), "msg": str(msg), "kind": kind,
                                 "sticky": bool(sticky), "action": action, "progress": progress})
            seq = self._toast_seq
        self._log(msg)
        return seq

    def _update_toast(self, toast_id, **fields):
        with self._ui_lock:
            for t in self._toasts:
                if t["id"] == toast_id:
                    t.update(fields)
                    return True
        return False

    def _live_toasts(self):
        """Toasts a afficher : les persistants, et les autres pendant 6 s (l'interface dedoublonne par id)."""
        now = time.time()
        with self._ui_lock:
            live = [t for t in self._toasts if t["sticky"] or now - t["t"] < 6.0]
            if len(live) != len(self._toasts):
                self._toasts = deque(live, maxlen=10)
            return [dict(t) for t in live]

    def dismiss_toast(self, toast_id):
        """Fermeture d'un toast (persistant) depuis l'interface."""
        with self._ui_lock:
            self._toasts = deque([t for t in self._toasts if t["id"] != toast_id], maxlen=10)
            if toast_id == self._update_toast_id:
                self._update_toast_id = None
        return True

    # ---------------------------------------------------------- client en ligne : liaisons
    def _online_notify(self, msg, kind="info", **kw):
        """notify() du client en ligne : un toast ordinaire (l'annonce d'une mise a jour passe par
        _update_available, jamais par une reconnaissance du texte)."""
        return self._notify(msg, kind, **kw)

    def _update_available(self, msg, latest=None):
        """on_update_available() de l'Updater : toast persistant avec l'action Installer (update_download)."""
        if self._update_toast_id is not None:
            self.dismiss_toast(self._update_toast_id)
        self._update_toast_id = self._notify(msg, "info", sticky=True,
                                             action={"label": i18n.t("update.toast.install"), "method": "update_download"})
        return self._update_toast_id

    def _sync_update_toast(self, upd):
        """Fait suivre au toast persistant de mise a jour l'etat de l'Updater (progression, Redemarrer).
        Appele a chaque get_state() ; aucune E/S."""
        tid = self._update_toast_id
        if tid is None or not upd:
            return
        st = upd.get("state")
        latest = upd.get("latest") or ""
        if st == "downloading":
            self._update_toast(tid, msg=i18n.t("update.toast.downloading", version=latest), kind="info",
                               progress=int(round(100 * float(upd.get("progress") or 0))), action=None)
        elif st == "ready":
            setup = upd.get("kind") == "setup"
            label = i18n.t("update.toast.restart") if setup else i18n.t("update.toast.open_folder")
            method = "update_install" if setup else "update_open_folder"
            self._update_toast(tid, msg=i18n.t("update.toast.ready", version=latest), kind="ok", progress=None,
                               action={"label": label, "method": method})
        elif st == "installing":
            self._update_toast(tid, msg=i18n.t("update.toast.installing"), kind="info",
                               progress=None, action=None)
        elif st in ("error", "idle", "uptodate"):
            # echec (toast d'erreur separe), ecarte (dismiss) ou plus rien a proposer : on retire le persistant
            self.dismiss_toast(tid)

    def _player_name(self):
        """Pseudo des salons : reglage multi.name, sinon le nom Discord, sinon « Joueur »."""
        name = str((self._cfg.get("multi") or {}).get("name") or "").strip()
        if not name:
            user = getattr(getattr(self, "_online", None), "account", None)
            user = getattr(user, "user", None)
            if isinstance(user, dict):
                name = str(user.get("username") or "").strip()
        return (name or i18n.t("room.default_player_name"))[:24]

    def _import_online_file(self, path, meta):
        """Fichier telecharge (bibliotheque en ligne ou salon) : copie dans songs/ avec le titre comme nom,
        meta {title, sha256, online_id, artist} appliquee. Renvoie l'identifiant local (nom de fichier)."""
        added, _ = self._import_files([path], extra_meta=meta or {})
        if not added:
            raise OSError(i18n.t("api.import.copy_failed"))
        sid = added[-1]
        if self._player.state == "stopped" and not self._room.active():
            try:
                self._player.index = self._player.songs.index(os.path.join(self._player.songs_folder, sid))
            except ValueError:
                pass
        return sid
