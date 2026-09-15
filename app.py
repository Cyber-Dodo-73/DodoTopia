# -*- coding: utf-8 -*-
"""DodoTopia : interface graphique (fenetre WebView2 + moteur core.py)."""
import base64
import json
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
import instruments
import online
import platform_io
import room
import settings_schema
import sync
from version import VERSION

UI_PATH = os.path.join(core.RES_DIR, "ui", "index.html")
ICON_PATH = os.path.join(core.RES_DIR, "assets", "logo.ico")
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".bmp": "image/bmp", ".webp": "image/webp"}


class Api:
    def __init__(self):
        self._cfg = core.load_config()
        self._logs = deque(maxlen=50)
        self._player = core.Player(self._cfg, log=self._log)
        self._sync = sync.SyncSession(self._player, self._cfg, log=self._log, notify=self._notify,
                                      logfile=os.path.join(core.DATA_DIR, "multi.log"))
        self._player.sync = self._sync
        self._window = None
        self._toasts = deque(maxlen=10)     # file de toasts {id, t, msg, kind, sticky, action, progress}
        self._toast_seq = 0
        self._update_toast_id = None        # toast persistant « Version x disponible [Installer] »
        # client en ligne (online.py) : sante du serveur, compte Discord, mise a jour, bibliotheque, salon (room.py)
        self._online = online.OnlineService(
            self._cfg, self._player, log=self._log, notify=self._online_notify,
            logfile=os.path.join(core.DATA_DIR, "online.log"),
            minimize=self._minimize_for_game, request_quit=self.quit, import_file=self._import_online_file,
            get_instrument_id=lambda: self._player.instrument.id, get_player_name=self._player_name,
            open_url=platform_io.open_url, open_folder=platform_io.open_folder)
        self._room = self._online.room          # room.RoomSession
        self._player.room = self._room          # Player.stop() / frappe clavier -> room.on_player_stop(reason)
        self._cfg["hotkeys"].setdefault("draw_point", "F3")
        self._drawer = draw.Drawer(self._cfg, log=self._log, on_change=self._on_module_change,
                                   save=lambda: core.save_config(self._cfg),
                                   logfile=os.path.join(core.DATA_DIR, "dessin.log"))
        self._cook = cook.Cooker(self._cfg, log=self._log, on_change=self._on_module_change,
                                 save=lambda: core.save_config(self._cfg),
                                 logfile=os.path.join(core.DATA_DIR, "cuisine.log"), data_dir=core.DATA_DIR)
        self._minimized = False
        self._draw_job = None
        self._draw_stats = None
        self._draw_msg = ""
        self._cook_msg = ""
        self._tab = "music"
        self._hotkeys = []
        # instruments : catalogue charge a la demande, assistant de configuration, cache du diagnostic
        self._cat = None
        self._kb_layout = instruments.resolve_keyboard_layout(self._cfg.get("keyboard_layout", "auto"))
        self._wizard = None             # etat de l'assistant (aucun profil ecrit tant qu'on ne sauve pas)
        self._hotkeys_off = 0           # > 0 : raccourcis globaux debranches (saisie d'une touche)
        self._capture_since = 0.0
        self._compat = None             # dernier compat_report calcule
        self._compat_key = None         # (morceau, empreinte de l'instrument, transposition, options)
        self._compat_notes = None       # (cle, notes groupees) : evite de relire le .mid pour un apercu
        self._bind_hotkeys()
        try:
            self._is_admin = bool(platform_io.is_admin())
        except Exception:
            self._is_admin = False
        self._last_reason = ""
        # --debug (DodoTopia (debug).bat) : l'interface reserve le diagnostic technique a ce mode
        self._debug = "--debug" in sys.argv

    # ---------------------------------------------------------- raccourcis (selon l'onglet actif)
    def _bind_hotkeys(self):
        """Les memes touches servent a la musique (onglet Musique), au dessin (onglet Image) et a la cuisine
        (onglet Cuisine)."""
        for h in self._hotkeys:
            try:
                platform_io.remove_hotkey(h)
            except Exception:
                pass
        self._hotkeys = []
        p, d, c = self._player, self._drawer, self._cook
        if self._hotkeys_off:
            # saisie d'une touche dans l'assistant : aucun raccourci global tant qu'elle dure
            # (les crochets clavier restent en place, ils n'agissent que pendant une lecture)
            self._bind_key_hooks()
            return

        def music_only(fn):
            # l'onglet En ligne garde les raccourcis musique (salon)
            return lambda: fn() if self._tab not in ("image", "cook") else None

        def play_pause():
            if self._tab == "image":
                self._draw_toggle()
            elif self._tab == "cook":
                self._cook_toggle()
            else:
                self._music_toggle()

        def stop():
            # En salon, le chef arrete tout le monde (comme F6) : le serveur fixe l'instant et chacun se coupe
            # en le recevant, donc on ne touche pas au Player ici. Un invite ne coupe que lui.
            self._wizard_test_abort("Test arrêté.")
            if not self._room.stop_request("stop"):
                p.stop()
                self._sync.abort("stop")
            d.stop("stop")
            c.stop("stop")

        def next_instrument():
            # F12 : meme traitement que le selecteur (refus pendant une lecture, choix persiste)
            ok, msg = p.next_instrument()
            if not ok:
                self._notify(msg or "Changement d'instrument impossible.", "warn")
                return
            core.save_config(self._cfg)
            self._room.on_instrument_change(p.instrument)
            self._notify(f"Instrument : {p.instrument.name}", "info")

        def capture_point():
            # F3 : pour l'assistant de calibrage ouvert (dessin ou cuisine)
            if d.state == "calibrating":
                d.capture_point()
            else:
                c.capture_point()

        actions = {
            "play_pause": play_pause, "stop": stop,
            "next_song": music_only(p.next_song), "prev_song": music_only(p.prev_song),
            "speed_down": music_only(p.speed_down), "speed_up": music_only(p.speed_up),
            "next_instrument": music_only(next_instrument),
            "draw_point": capture_point,
        }
        for name, fn in actions.items():
            combo = self._cfg["hotkeys"].get(name)
            if combo:
                try:
                    self._hotkeys.append(platform_io.add_hotkey(combo, fn))
                except Exception as e:  # noqa
                    self._log(f"raccourci invalide {combo!r} : {e}")
        self._bind_key_hooks()

    def _bind_key_hooks(self):
        """Crochets clavier des modules (arret sur frappe, reperes de calibrage) : poses une seule fois."""
        p, d, c = self._player, self._drawer, self._cook
        if p._hook is None:
            p._hook = platform_io.hook(p._on_key_event)
        if d._hook is None:
            d._hook = platform_io.hook(d.on_key_event)
        if c._hook is None:
            c._hook = platform_io.hook(c.on_key_event)

    def _capture_begin(self):
        """Debranche les raccourcis globaux : la touche appuyee dans l'assistant ne doit ni partir au jeu
        ni declencher un raccourci. Toujours appele avec un _capture_end() correspondant."""
        self._hotkeys_off += 1
        self._capture_since = time.time()
        if self._hotkeys_off == 1:
            self._bind_hotkeys()

    def _capture_end(self, force=False):
        """Rebranche les raccourcis globaux (fin de saisie, annulation, erreur, securite)."""
        if not self._hotkeys_off:
            return
        self._hotkeys_off = 0 if force else max(0, self._hotkeys_off - 1)
        if not self._hotkeys_off:
            self._bind_hotkeys()

    def _music_toggle(self):
        """F6 / bouton Jouer : routeur selon le mode de jeu. room : salon en ligne (lobby : chef = top depart,
        autres = Pret ; compte a rebours : annuler ; lecture : stop) ; audio : top depart par note repere ;
        solo : lecture directe."""
        p = self._player
        mode = self._cfg.get("multi", {}).get("mode", "solo")
        if mode == "room":
            self._room.on_f6()
        elif self._sync.active():
            self._sync.abort("stop")
        elif mode == "audio" and p.state == "stopped":
            self._sync.start()
        else:
            p.play_pause("game")

    def _draw_toggle(self, from_ui=False):
        d = self._drawer
        if d.state in ("drawing", "autocal"):
            d.stop("stop")
        elif d.state == "calibrating":
            d.capture_point()
        elif self._draw_job:
            if self._player.state != "stopped":
                self._player.stop(join=True)
            # depuis le bouton : 3 s pour passer sur le jeu, et la fenetre se reduit pour ne pas gener
            if d.start(self._draw_job, delay=3.0 if from_ui else 1.0) and from_ui and self._window:
                try:
                    self._window.minimize()
                    self._minimized = True
                except Exception:
                    pass
        else:
            self._notify("Importe d'abord une image dans l'activite Dessin", "warn")

    def _cook_toggle(self, from_ui=False):
        """F6 / bouton Cuisiner en boucle : lance ou arrete la cuisine (ou capture un point en calibrage)."""
        c = self._cook
        if c.state == "cooking":
            c.stop("stop")
        elif c.state == "calibrating":
            c.capture_point()
        elif not c.calibrated():
            self._notify("Configure d'abord la cuisine (bouton « Configurer la cuisine », activite Cuisine)", "warn")
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

    def _notify(self, msg, kind="info", sticky=False, action=None, progress=None):
        """Toast pour l'interface. kind : info | ok | warn | danger. sticky : reste affiche jusqu'a dismiss_toast(id)
        ou clic sur l'action ({"label", "method", "args"} = methode de l'Api a appeler) ; progress : 0-100 ou None.
        Renvoie l'id, a passer a _update_toast pour faire evoluer un toast persistant."""
        self._toast_seq += 1
        self._toasts.append({"id": self._toast_seq, "t": time.time(), "msg": str(msg), "kind": kind,
                             "sticky": bool(sticky), "action": action, "progress": progress})
        self._log(msg)
        return self._toast_seq

    def _update_toast(self, toast_id, **fields):
        for t in self._toasts:
            if t["id"] == toast_id:
                t.update(fields)
                return True
        return False

    def _live_toasts(self):
        """Toasts a afficher : les persistants, et les autres pendant 6 s (l'interface dedoublonne par id)."""
        now = time.time()
        live = [t for t in self._toasts if t["sticky"] or now - t["t"] < 6.0]
        if len(live) != len(self._toasts):
            self._toasts = deque(live, maxlen=10)
        return list(live)

    def dismiss_toast(self, toast_id):
        """Fermeture d'un toast (persistant) depuis l'interface."""
        self._toasts = deque([t for t in self._toasts if t["id"] != toast_id], maxlen=10)
        if toast_id == self._update_toast_id:
            self._update_toast_id = None
        return True

    # ---------------------------------------------------------- client en ligne : liaisons
    def _online_notify(self, msg, kind="info", **kw):
        """notify() du client en ligne : l'annonce « Version x disponible » de l'Updater devient un toast
        persistant avec l'action Installer (update_download) ; le reste passe tel quel."""
        msg = str(msg)
        if msg.startswith("Version ") and msg.endswith(" disponible"):
            if self._update_toast_id is not None:
                self.dismiss_toast(self._update_toast_id)
            self._update_toast_id = self._notify(msg, kind, sticky=True,
                                                 action={"label": "Installer", "method": "update_download"})
            return self._update_toast_id
        return self._notify(msg, kind, **kw)

    def _sync_update_toast(self, upd):
        """Fait suivre au toast persistant de mise a jour l'etat de l'Updater (progression, Redemarrer).
        Appele a chaque get_state() ; aucune E/S."""
        tid = self._update_toast_id
        if tid is None or not upd:
            return
        st = upd.get("state")
        latest = upd.get("latest") or ""
        if st == "downloading":
            self._update_toast(tid, msg=f"Téléchargement de la version {latest}…", kind="info",
                               progress=int(round(100 * float(upd.get("progress") or 0))), action=None)
        elif st == "ready":
            label = "Redémarrer" if upd.get("kind") == "setup" else "Ouvrir le dossier"
            method = "update_install" if upd.get("kind") == "setup" else "update_open_folder"
            self._update_toast(tid, msg=f"Version {latest} prête à installer", kind="ok", progress=None,
                               action={"label": label, "method": method})
        elif st == "installing":
            self._update_toast(tid, msg="Installation en cours, DodoTopia va se fermer…", kind="info",
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
        return (name or "Joueur")[:24]

    def _import_online_file(self, path, meta):
        """Fichier telecharge (bibliotheque en ligne ou salon) : copie dans songs/ avec le titre comme nom,
        meta {title, sha256, online_id, artist} appliquee. Renvoie l'identifiant local (nom de fichier)."""
        added, _ = self._import_files([path], extra_meta=meta or {})
        if not added:
            raise OSError("copie impossible")
        sid = added[-1]
        if self._player.state == "stopped" and not self._room.active():
            try:
                self._player.index = self._player.songs.index(os.path.join(self._player.songs_folder, sid))
            except ValueError:
                pass
        return sid

    # ---------------------------------------------------------- etat
    def get_state(self):
        p = self._player
        songs = []
        for i, path in enumerate(p.songs):
            sid = os.path.basename(path)
            m = p.library.meta(sid)
            songs.append({
                "id": sid,
                "name": m.get("title") or core.clean_title(sid),
                "file": os.path.splitext(sid)[0],
                "fav": bool(m.get("fav")),
                "plays": int(m.get("plays", 0)),
                "added": m.get("added", 0),
                "last_played": m.get("last_played", 0),
                "duration": p.song_duration(path),
                "index": i,
                "online_id": m.get("online_id"),
                "sha256": m.get("sha256"),
            })
        # erreur explicite pour l'interface (composant .notice de la carte Musique) : {msg, kind, since} | None.
        # Arret par l'utilisateur (touche, clic) = info ; erreur de lecture / capture audio = danger.
        # Efface au prochain depart (last_stop_reason remis a "" par play/play_at).
        user_stop = ("stop", "clavier touche", "clic souris", "fermeture")
        if p.last_stop_reason and p.last_stop_reason != self._last_reason:
            self._last_reason = p.last_stop_reason
            reason = p.last_stop_reason
            benign = reason in user_stop or reason.startswith("mode ") or reason.startswith("annul")
            self._error = {"msg": ("Arrêt : " + reason) if benign else reason,
                           "kind": "info" if benign else "danger", "since": time.time(),
                           "target": p.target, "reason": reason}
            if not benign:
                self._notify("Arrêt : " + reason, "warn")
        elif not p.last_stop_reason:
            self._last_reason = ""
            if getattr(self, "_error", None) and self._error.get("reason") != "multi":
                self._error = None
        mu_status = self._sync.status()
        if mu_status["state"] == "idle":
            # session Multi terminee sur une erreur (capture audio, sortie introuvable...) : message explicite
            smsg = mu_status.get("message") or ""
            if smsg != getattr(self, "_last_sync_msg", ""):
                self._last_sync_msg = smsg
                low = smsg.lower()
                if smsg and not smsg.startswith(("Annulé", "Lecture", "Calibrage", "Calé", "Test", "Écoute", "Pas d'écho")) \
                        and any(w in low for w in ("introuvable", "erreur", "impossible", "indisponible", "ne démarre", "interrompue")):
                    self._error = {"msg": smsg, "kind": "danger", "since": time.time(), "target": "game", "reason": "multi"}
        else:
            self._last_sync_msg = ""
            if getattr(self, "_error", None) and self._error.get("reason") == "multi":
                self._error = None
        # fenetre reduite pour un test / calibrage Multi : on la rend quand plus rien ne tourne dans le jeu
        if (self._minimized and self._window and self._sync.state == "idle" and p.state == "stopped"
                and self._room.state not in ("armed", "playing") and not self._wizard_busy()
                and self._drawer.state not in ("drawing", "autocal") and self._cook.state != "cooking"):
            self._minimized = False
            try:
                self._window.restore()
            except Exception:
                pass
        # securite : si l'interface a oublie instrument_wizard_capture_end() (fenetre perdue, erreur JS),
        # les raccourcis globaux reviennent d'eux-memes au bout d'un moment.
        if self._hotkeys_off and time.time() - self._capture_since > self.CAPTURE_TIMEOUT:
            self._capture_end(force=True)
            if self._wizard:
                self._wizard["capturing"] = False
            self._log("saisie de touche trop longue : raccourcis rebranchés")
        dcfg = self._cfg.get("draw") or {}
        ccfg = self._cfg.get("cook") or {}
        ocfg = online.ensure_defaults(self._cfg)
        mode = self._cfg["multi"].get("mode", "solo")
        ost = self._online.status()                 # copie sous verrou, aucune E/S reseau
        self._sync_update_toast(ost.get("update"))
        return {
            "version": VERSION,
            # liste legere des 19 types (ordre du catalogue) : aucune table de notes ici, get_state()
            # est appele plusieurs fois par seconde. Le detail passe par get_instrument_detail().
            "instruments": [i.to_dict() for i in p.instruments],
            "instrument": p.inst_index,                 # index : compatibilite des anciens appels
            "instrument_id": p.instrument.id,
            "instrument_ready": bool(p.instrument.ready),
            "instrument_blocked": p.instrument.blocked_reason,
            "instrument_favorites": list(self._cfg.get("instrument_favorites") or []),
            "keyboard_layout": self._keyboard_layout(),
            "keyboard_layout_pref": self._cfg.get("keyboard_layout", "auto"),
            "instrument_wizard": self._wizard_state(),
            "song_compat": self._song_compat(),
            "debug": self._debug,
            "songs": songs,
            "current": p.index if p.songs else -1,
            "state": p.state,
            "target": p.target,
            "position": p.position(),
            "duration": p.duration if p.state != "stopped" else (
                p.song_duration(p.current()) if p.current() else 0.0),
            "speed": p.speed,
            "speed_locked": bool(p.lock_speed),
            "info": p.info if p.state != "stopped" else None,
            "hotkeys": self._cfg["hotkeys"],
            # mode room : RoomSession.status() (memes cles que SyncSession.status() + cle "room")
            "multi": ost["room"] if mode == "room" else self._sync.status(),
            "online": ost,
            "settings": {
                "input_mode": self._cfg["input_mode"],
                "hold_time": self._cfg["hold_time"],
                "start_delay": self._cfg["start_delay"],
                "transpose_semitones": self._cfg["transpose_semitones"],
                "stop_on_input": bool(self._cfg.get("stop_on_input", True)),
                "hold_mode": self._cfg.get("hold_mode", "note"),
                "preview_volume": int(self._cfg.get("preview_volume", 100)),
                "keyboard_layout": self._cfg.get("keyboard_layout", "auto"),
                "fold_out_of_range": bool(self._cfg.get("fold_out_of_range", True)),
                "multi": {k: self._cfg["multi"].get(k) for k in
                          ("enabled", "mode", "name", "player_id", "countdown", "lead", "offset_ms", "net_offset_ms",
                           "latency", "beacon_freqs", "tune", "device", "calib")},
                # valeurs affichees en contexte (page Image, panneau Multi, onglet Cuisine)
                "draw": {k: dcfg.get(k, draw.DEFAULT_DRAW.get(k)) for k in
                         ("outline", "fill_background", "skip_white", "verify", "dense", "refine", "mouse_glide",
                          "glide_speed", "step_delay", "click_delay")},
                "cook": {k: ccfg.get(k, cook.DEFAULT_COOK.get(k)) for k in
                         ("max_dishes", "cook_timeout", "match", "green_px", "click_delay")},
                "online": {"server_url": ocfg.get("server_url", ""), "check_updates": bool(ocfg.get("check_updates", True))},
            },
            "songs_folder": p.songs_folder,
            "log": list(self._logs)[-6:],
            "toasts": self._live_toasts(),
            "is_admin": self._is_admin,
            "error": getattr(self, "_error", None),
            "tab": self._tab,
            "draw": self._drawer.status(),
            "draw_stats": self._draw_stats,
            "cook": self._cook.status(),
        }

    def set_tab(self, name):
        """Activite ouverte : music | image (dessin) | cook. Les raccourcis suivent cette valeur.
        « online » est accepte pour compatibilite : le catalogue est maintenant une vue de la Musique."""
        self._tab = name if name in ("image", "cook") else "music"
        return True

    # ---------------------------------------------------------- cuisine dans le jeu
    def cook_start(self):
        self._cook_toggle(from_ui=True)
        return self.get_state()

    def cook_stop(self):
        self._cook.stop("stop")
        return self.get_state()

    def cook_calibrate(self, mode="all"):
        """mode « icons » : ne recapture que les trois icones de la bulle (cuisiner, spatule, gants)."""
        if self._drawer.state == "calibrating":
            self._drawer.cancel_calibration()
        self._cook.start_calibration(cook.ICON_STEPS if mode == "icons" else None)
        return self.get_state()

    def cook_calibrate_cancel(self):
        self._cook.cancel_calibration()
        return self.get_state()

    def cook_calibrate_skip(self):
        self._cook.skip_point()
        return self.get_state()

    def cook_calibrate_back(self):
        """Assistant : revenir a l'etape precedente pour la refaire."""
        self._cook.back_point()
        return self.get_state()

    def cook_calibrate_goto(self, index):
        """Assistant : revenir a une etape deja faite (recapitulatif)."""
        self._cook.goto_step(index)
        return self.get_state()

    def cook_calibrate_point(self):
        """Bouton de secours dans l'assistant (la souris doit deja etre sur la cible, sinon utiliser F3)."""
        self._cook.capture_point()
        return self.get_state()

    def cook_test(self):
        """Lit l'ecran maintenant : quelle bulle est reconnue, avec les scores (pour verifier le calibrage)."""
        msg = self._cook.test()
        self._notify(msg, "info")
        return self.get_state()

    def open_cook_log(self):
        path = os.path.join(core.DATA_DIR, "cuisine.log")
        if os.path.isfile(path):
            platform_io.open_text_file(path)
        else:
            self._notify("Pas encore de journal : lance la cuisine d'abord", "warn")
        return True

    # ---------------------------------------------------------- dessin dans le jeu
    def set_draw_job(self, job):
        """L'onglet Image envoie la grille a peindre (indices de la palette du jeu, -1 = vide)."""
        if isinstance(job, dict) and job.get("cells"):
            self._draw_job = {"format": job.get("format", "16:9"), "w": int(job["w"]), "h": int(job["h"]),
                              "cells": [int(c) for c in job["cells"]], "skip": list(job.get("skip", []))}
        else:
            self._draw_job = None
        self._refresh_draw_stats()
        return True

    def _refresh_draw_stats(self):
        """Statistiques du mode contours (cases au crayon, zones au pot) pour l'apercu."""
        try:
            self._draw_stats = self._drawer.outline_stats(self._draw_job)
        except Exception as e:  # noqa
            self._log(f"statistiques du mode contours : {e}")
            self._draw_stats = None

    def draw_start(self):
        self._draw_toggle(from_ui=True)
        return self.get_state()

    def draw_stop(self):
        self._drawer.stop("stop")
        return self.get_state()

    def draw_calibrate(self, fmt):
        self._drawer.start_calibration(fmt)
        return self.get_state()

    def draw_calibrate_cancel(self):
        self._drawer.cancel_calibration()
        return self.get_state()

    def draw_auto_calibrate(self, fmt):
        """Calibrage automatique : dessine dans le canevas du jeu, mesure, corrige et valide."""
        if self._player.state != "stopped":
            self._player.stop(join=True)
        if self._drawer.start_auto(fmt, delay=3.0) and self._window:
            try:
                self._window.minimize()
                self._minimized = True
            except Exception:
                pass
        return self.get_state()

    def draw_calibrate_skip(self):
        self._drawer.skip_point()
        return self.get_state()

    def draw_calibrate_back(self):
        """Assistant : revenir a l'etape precedente pour la refaire."""
        self._drawer.back_point()
        return self.get_state()

    def draw_calibrate_goto(self, index):
        """Assistant : revenir a une etape deja faite (recapitulatif)."""
        self._drawer.goto_step(index)
        return self.get_state()

    def draw_calibrate_point(self):
        """Bouton de secours dans l'assistant (la souris doit deja etre sur la cible, sinon utiliser F3)."""
        self._drawer.capture_point()
        return self.get_state()

    def draw_set_grid(self, fmt, cols, rows):
        """Nombre de cases d'un format, saisi a la main."""
        d = draw.ensure_defaults(self._cfg)
        try:
            cols, rows = int(cols), int(rows)
        except (TypeError, ValueError):
            return self.get_state()
        if fmt in draw.FORMATS and 4 <= cols <= 400 and 4 <= rows <= 400:
            f = d["formats"].setdefault(fmt, {})
            f["cols"], f["rows"] = cols, rows
            core.save_config(self._cfg)
            self._notify(f"Grille {fmt} : {cols} × {rows} cases", "ok")
        return self.get_state()

    # ---------------------------------------------------------- bibliotheque
    def import_dialog(self):
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=("Fichiers MIDI (*.mid;*.midi)", "Tous les fichiers (*.*)"))
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
            s = "s" if len(added) > 1 else ""
            self._notify(f"{len(added)} musique{s} importée{s}", "ok")
        if skipped:
            names = ", ".join(skipped[:3]) + (f" et {len(skipped) - 3} autre(s)" if len(skipped) > 3 else "")
            if added:
                self._notify(f"{len(skipped)} fichier(s) ignoré(s), ce ne sont pas des .mid : {names}", "warn")
            else:
                self._notify(f"Rien d'importé : DodoTopia lit les fichiers .mid et .midi. Ignoré : {names}", "warn")
        return self.get_state()

    def remove_song(self, song_id):
        path = os.path.join(self._player.songs_folder, song_id)
        if os.path.isfile(path):
            if self._player.current() == path:
                self._player.stop(join=True)
            os.remove(path)
            self._player.library.remove(song_id)
            self._player.refresh_songs()
            self._notify("Musique retirée de la bibliothèque")
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

    def open_draw_log(self):
        path = os.path.join(core.DATA_DIR, "dessin.log")
        if os.path.isfile(path):
            platform_io.open_text_file(path)
        else:
            self._notify("Pas encore de journal : lance un dessin d'abord", "warn")
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
            self._notify(f"Ouverture du navigateur impossible : {e}", "warn")
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
            self._notify("Pas encore de journal pour cette fonction", "warn")
        return True

    # ---------------------------------------------------------- image
    def import_image_dialog(self):
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("Images (*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp)", "Tous les fichiers (*.*)"))
        if not files:
            return None
        return self.load_image(files[0])

    def load_image(self, path):
        """Lit une image et la renvoie a l'interface en data URL (l'onglet Image fait le rendu)."""
        if not path or not os.path.isfile(path):
            return None
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_MIME:
            self._notify(f"Ignoré (pas une image) : {os.path.basename(path)}", "warn")
            return None
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        self._notify(f"Image importée : {os.path.basename(path)}", "ok")
        return {"name": os.path.splitext(os.path.basename(path))[0],
                "data": f"data:{IMAGE_MIME[ext]};base64,{data}"}

    LOGO_PX = 96        # affiche vers 40 px : 96 couvre les ecrans a forte densite

    def get_logo(self):
        """Logo en data URL : la page est servie depuis ui/, assets/ n'est pas accessible en relatif.
        Reduit et mis en cache : le fichier source fait plus d'un Mo, inutile de le passer en entier
        a chaque demarrage a travers le pont JS."""
        if getattr(self, "_logo_url", None) is not None:
            return self._logo_url
        path = os.path.join(core.RES_DIR, "assets", "logo.png")
        if not os.path.isfile(path):
            self._logo_url = None
            return None
        try:
            import io as _io
            from PIL import Image
            im = Image.open(path).convert("RGBA")
            if max(im.size) > self.LOGO_PX:
                im.thumbnail((self.LOGO_PX, self.LOGO_PX), Image.LANCZOS)
            buf = _io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
        except Exception as e:  # noqa - Pillow absent ou image illisible : on envoie le fichier tel quel
            self._log(f"logo non redimensionné : {e}")
            with open(path, "rb") as f:
                data = f.read()
        self._logo_url = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        return self._logo_url

    # ---------------------------------------------------------- lecture
    def select_song(self, index):
        self._player.select(int(index))
        return self.get_state()

    def preview(self, index=None):
        """Bouton lecture : ecoute dans le logiciel."""
        if index is not None:
            self._player.select(int(index))
        p = self._player
        if p.state == "playing" and p.target == "preview":
            p.pause()
        else:
            p.play("preview")
        return self.get_state()

    def play_game(self):
        """Bouton 'Jouer dans le jeu' : meme chose que le raccourci F6."""
        self._music_toggle()
        return self.get_state()

    def stop(self):
        """Bouton Arreter et F7 : en salon, le chef arrete tout le monde ; un invite ne coupe que lui.

        Coupe aussi un test de touches en cours dans l'assistant : « tout arrêter » doit vraiment tout
        arreter, y compris l'envoi d'un echantillon dans le jeu."""
        self._wizard_test_abort("Test arrêté.")
        if not self._room.stop_request("stop"):
            self._player.stop()
            self._sync.abort("stop")
        return self.get_state()

    def room_stop_local(self):
        """Salon : ne couper que soi-meme, meme quand on est chef (bouton « Arreter pour moi »)."""
        self._room.stop_local("stop")
        self._player.stop()
        return self.get_state()

    # ---------------------------------------------------------- mode de jeu (solo | audio | room)
    def set_play_mode(self, mode):
        """Segmente Solo | Multi audio | Salon en ligne du lecteur (= set_setting('multi.mode', mode))."""
        if mode not in sync.PLAY_MODES:
            self._notify(f"Mode inconnu : {mode}", "warn")
            return self.get_state()
        r = self.set_setting("multi.mode", mode)
        if not r.get("ok"):
            self._notify(r.get("error") or "Mode refusé", "warn")
        return self.get_state()

    def set_multi(self, on):
        """Interrupteur Solo / Multi de l'onglet Musique (alias historique de set_play_mode)."""
        return self.set_play_mode("audio" if on else "solo")

    def multi_calibrate(self):
        """Calibrage a plusieurs : tout le monde clique, le meneur joue son motif, les suiveurs repondent et
        mesurent leur aller-retour par le jeu. La fenetre se reduit le temps de passer sur le jeu."""
        if not self._cfg["multi"].get("enabled"):
            self.set_multi(True)
        if self._sync.calibrate():
            if self._window:
                try:
                    self._window.minimize()
                    self._minimized = True
                except Exception:
                    pass
        else:
            self._notify("Une écoute ou une lecture est déjà en cours", "warn")
        return self.get_state()

    def _minimize_for_game(self):
        """Reduit la fenetre le temps d'un test dans le jeu ; get_state() la rend quand tout est fini."""
        if self._window:
            try:
                self._window.minimize()
                self._minimized = True
            except Exception:
                pass

    def multi_test(self):
        """Test de detection : joue la note repere dans le jeu et mesure la latence (fenetre reduite)."""
        if self._sync.selftest():
            self._minimize_for_game()
        else:
            self._notify("Une écoute ou une lecture est déjà en cours", "warn")
        return self.get_state()

    def multi_listen_test(self, seconds=30):
        try:
            seconds = max(5.0, min(120.0, float(seconds)))
        except (TypeError, ValueError):
            seconds = 30.0
        if self._sync.listen_test(seconds):
            self._minimize_for_game()
        else:
            self._notify("Une écoute ou une lecture est déjà en cours", "warn")
        return self.get_state()

    def multi_devices(self):
        return sync.LoopbackCapture.list_devices()

    def next_song(self):
        self._player.next_song()
        return self.get_state()

    def prev_song(self):
        self._player.prev_song()
        return self.get_state()

    def set_speed(self, value):
        self._player.set_speed(value)
        return self.get_state()

    # ---------------------------------------------------------- instruments : catalogue, profils, assistant
    # Choisir un instrument ici n'equipe rien dans Heartopia : on choisit le TYPE joue, donc ses touches.
    WIZARD_STEPS = ("Ouvrir l'instrument dans Heartopia", "Disposition visible dans le jeu",
                    "Associer les touches", "Tester dans le jeu", "Enregistrer le profil")
    WIZARD_TEST_KEYS = 3        # un test porte sur un echantillon : jamais une validation integrale
    WIZARD_TEST_DELAY = 4.0     # secondes pour passer sur la fenetre du jeu
    CAPTURE_TIMEOUT = 45.0      # securite : raccourcis rebranches si l'interface oublie capture_end()

    def _catalogue(self):
        """Catalogue (types + dispositions), charge une fois : ces donnees ne changent pas en cours de route."""
        if self._cat is None:
            self._cat = instruments.load_catalogue()
        return self._cat

    def _keyboard_layout(self):
        """Disposition effective du clavier physique (preference « auto » resolue)."""
        return instruments.resolve_keyboard_layout(self._cfg.get("keyboard_layout", "auto"))

    def _instrument(self, instrument_id):
        """Instrument resolu d'apres son identifiant (ou son index), ou None."""
        insts = self._player.instruments
        if isinstance(instrument_id, str):
            return instruments.find_instrument(insts, instrument_id)
        try:
            i = int(instrument_id)
        except (TypeError, ValueError):
            return None
        return insts[i] if 0 <= i < len(insts) else None

    def _note_line(self, midi, key="", kb=None):
        """Une ligne de table de touches : la note, la position envoyee au jeu, la legende affichee."""
        kb = kb or self._keyboard_layout()
        key = str(key or "").lower()
        return {"midi": int(midi), "solfege": instruments.solfege(midi), "note": instruments.note_name(midi),
                "key": key, "label": instruments.key_label(key, kb) if key else "",
                "shift": bool(key) and instruments.key_needs_shift(key, kb),
                "bound": bool(key), "sendable": key in platform_io.SCANCODES}

    def _rebuild_instruments(self):
        """Reconstruit les instruments resolus apres une ecriture de profil, sans perdre l'instrument actif."""
        p = self._player
        current = p.instrument.id
        self._cfg["_instruments"] = instruments.build_instruments(self._cfg)
        p.instruments = self._cfg["_instruments"]
        ids = [i.id for i in p.instruments]
        p.inst_index = ids.index(current) if current in ids else 0
        self._cfg["instrument"] = p.instrument.id
        self._room.on_instrument_change(p.instrument)

    def get_instrument_catalogue(self):
        """Donnees fixes du selecteur : categories, dispositions completes, statuts, clavier physique.

        Appele UNE fois par l'interface (et memorise cote JS) : rien de tout cela ne bouge a chaque tick."""
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(f"Catalogue des instruments : {e}", "danger")
            return {"error": str(e), "categories": [], "layouts": [], "statuses": {}}
        kb = self._keyboard_layout()
        layouts = []
        for lay in cat.layouts.values():
            d = lay.to_dict(with_notes=False)
            d["notes"] = [self._note_line(n["midi"], n["key"], kb) for n in lay.notes]
            layouts.append(d)
        return {"categories": [{"id": cid, "label": label} for cid, label in cat.categories],
                "layouts": layouts,
                "octave_convention": cat.octave_convention,
                "retrieved_at": cat.retrieved_at,
                "source_urls": list(cat.source_urls),
                "notes": list(cat.notes),
                "keyboard_layout": kb,
                "keyboard_layout_pref": self._cfg.get("keyboard_layout", "auto"),
                "keyboard_layout_detected": instruments.detect_keyboard_layout(),
                "keyboard_layouts": list(instruments.KEYBOARD_LAYOUTS),
                "azerty_labels": dict(instruments.AZERTY_LABELS),
                "input_mode": self._cfg.get("input_mode", "scancode"),
                "statuses": dict(instruments.STATUS_LABELS)}

    def get_instrument_detail(self, instrument_id):
        """Fiche complete d'un type : notes, rangees, dispositions candidates, profil, provenance."""
        inst = self._instrument(instrument_id)
        if inst is None:
            return {"error": "Instrument inconnu."}
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            return {"error": str(e)}
        kb = self._keyboard_layout()
        d = inst.to_dict()
        rows = [[self._note_line(n["midi"], n["key"], kb) for n in row] for row in inst.note_rows()]
        prof = instruments.profile_of(self._cfg, inst.id, cat)
        layouts = []
        for lay in cat.layouts_for(inst.id):
            item = lay.to_dict(with_notes=False)
            item["notes"] = [self._note_line(n["midi"], n["key"], kb) for n in lay.notes]
            item["selected"] = (lay.id == inst.layout_id)
            layouts.append(item)
        d.update({
            "notes": [self._note_line(m, inst.bindings.get(m, ""), kb) for m in inst.available_notes],
            "rows": rows,
            # contrat SPEC : liste d'entiers MIDI (l'interface la formate elle-meme)
            "missing_notes": list(inst.missing_notes),
            "missing_notes_detail": [{"midi": m, "solfege": instruments.solfege(m),
                                      "note": instruments.note_name(m)} for m in inst.missing_notes],
            "unsendable": list(inst.unsendable),
            "source_urls": list(inst.source_urls),
            "layouts": layouts,
            "profile": prof,
            "image_source_url": inst.image_source_url,
            "catalog_item_ids": list(inst.catalog_item_ids),
            "variant_count": inst.variant_count,
            "status_label": inst.status_label,
            "category_label": cat.category_label(inst.category),
            "label_fr_status": inst.type.label_fr_status,
            "mapping_status": inst.type.mapping_status,
            "verified_at": inst.verified_at,
            "game_version": inst.game_version,
            "polyphony": inst.polyphony,
            "sounding_pitch_offset": inst.sounding_pitch_offset,
            "preview_program": inst.preview_program,
            "octave_convention": cat.octave_convention,
            "keyboard_layout": kb,
            "favorite": inst.id in (self._cfg.get("instrument_favorites") or []),
            "active": inst.id == self._player.instrument.id,
        })
        return d

    def set_instrument(self, index):
        """Type d'instrument actif. Accepte un identifiant (« lute ») ou un index (compatibilite)."""
        target = index
        if not isinstance(target, str):
            try:
                target = int(target)
            except (TypeError, ValueError):
                target = str(index)
        ok, msg = self._player.set_instrument(target)
        if not ok:
            self._notify(msg or "Instrument inconnu.", "warn")
            return self.get_state()
        inst = self._player.instrument
        core.save_config(self._cfg)
        self._room.on_instrument_change(inst)
        if not inst.ready:
            self._notify(f"{inst.name} : {inst.blocked_reason}", "warn")
        return self.get_state()

    def toggle_instrument_favorite(self, instrument_id):
        """Favori du selecteur (persiste dans config.json)."""
        inst = self._instrument(instrument_id)
        if inst is None:
            return self.get_state()
        favs = list(self._cfg.get("instrument_favorites") or [])
        if inst.id in favs:
            favs.remove(inst.id)
        else:
            favs.append(inst.id)
        self._cfg["instrument_favorites"] = favs
        core.save_config(self._cfg)
        return self.get_state()

    def set_keyboard_layout(self, value):
        """Disposition du clavier physique : « auto », « qwerty » ou « azerty »."""
        r = self.set_setting("keyboard_layout", value)
        if not r.get("ok"):
            self._notify(r.get("error") or "Disposition refusée", "warn")
        return self.get_state()

    def set_instrument_layout(self, instrument_id, layout_id, force=False):
        """Choisit une disposition candidate pour un type.

        Des touches personnalisees ne sont effacees que sur confirmation explicite (force=True) : on ne
        remplace jamais un mapping deja adapte a l'installation par une table externe sans le dire."""
        inst = self._instrument(instrument_id)
        if inst is None:
            self._notify("Instrument inconnu.", "warn")
            return self.get_state()
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(str(e), "danger")
            return self.get_state()
        lay = cat.layouts.get(str(layout_id or ""))
        if lay is None:
            self._notify("Disposition inconnue.", "warn")
            return self.get_state()
        if inst.id == self._player.instrument.id and self._player.state != "stopped":
            self._notify("Arrête la lecture avant de changer la disposition.", "warn")
            return self.get_state()
        if inst.custom and not force:
            self._notify(f"{inst.name} a des touches personnalisées : confirme pour les remplacer par "
                         f"« {lay.label} ».", "warn")
            return self.get_state()
        status = instruments.STATUS_DOCUMENTED if lay.id in inst.type.supported_layout_ids \
            else instruments.STATUS_CUSTOM
        instruments.set_profile(self._cfg, inst.id, layout_id=lay.id, bindings=None, status=status,
                                verified_at=None, catalogue=cat)
        core.save_config(self._cfg)
        self._rebuild_instruments()
        self._notify(f"{inst.name} : disposition « {lay.label} » ({lay.note_count} notes). "
                     f"Choisis la même dans le jeu.", "ok")
        return self.get_state()

    # ---------------------------------------------------------- assistant de configuration des touches
    def _wizard_busy(self):
        """Vrai pendant un test dans le jeu (la fenetre doit rester reduite)."""
        w = self._wizard
        t = (w or {}).get("test")
        return bool(t and t.get("state") in ("countdown", "playing"))

    def _wizard_test_abort(self, message="Test arrêté."):
        """Coupe un test de touches en cours. Appele par le raccourci d'arret, le bouton « Tout arrêter »
        et le bouton « Arrêter le test » de l'assistant : l'arret annonce doit exister pour de vrai."""
        t = (self._wizard or {}).get("test")
        if t and t.get("state") in ("countdown", "playing"):
            t["state"] = "cancelled"
            t["message"] = message
            return True
        return False

    def _wizard_forget_test(self, w):
        """Oublie un test termine sans reponse (annule ou en erreur) : sinon l'etape 4 resterait figee sur
        « Test en cours… » et l'utilisateur ne pourrait plus relancer."""
        t = (w or {}).get("test")
        if t and t.get("state") in ("cancelled", "error"):
            w["message"] = t.get("message") or w.get("message", "")
            w["test"] = None

    def _wizard_midis(self, w):
        """Notes de la table en cours : celles de la disposition retenue, plus celles deja associees."""
        midis = set(w["bindings"])
        try:
            lay = self._catalogue().layouts.get(w.get("layout_id") or "")
        except instruments.InstrumentDataError:
            lay = None
        if lay is not None:
            midis |= {n["midi"] for n in lay.notes}
        return sorted(midis)

    def _wizard_state(self):
        """Etat de l'assistant pour l'interface (None quand il est ferme)."""
        w = self._wizard
        if w is None:
            return None
        kb = self._keyboard_layout()
        midis = self._wizard_midis(w)
        lines = [self._note_line(m, w["bindings"].get(m, ""), kb) for m in midis]
        conflicts = instruments.conflicts(w["bindings"], self._cfg)
        bound = len(w["bindings"])
        test = dict(w["test"]) if w.get("test") else None
        if test and test.get("state") == "countdown":
            test["remaining"] = round(max(0.0, test["ends"] - time.time()), 1)
        return {"id": w["id"], "name": w["name"], "image": w["image"], "percussive": w["percussive"],
                "mode": w["mode"], "step": w["step"], "steps": list(self.WIZARD_STEPS),
                "layout_id": w.get("layout_id"), "layouts": w["layouts"],
                "keyboard_layout": kb, "capturing": bool(w.get("capturing")),
                "notes": lines, "rows": w.get("rows") or [],
                "conflicts": conflicts, "blocking": instruments.blocking(conflicts),
                "bound": bound, "total": len(midis),
                "verified": sorted(w["verified"]),
                "unverified": sorted(m for m in w["bindings"] if m not in w["verified"]),
                "tested": bool(w["tested"]),
                "test": test, "answers": list(w["answers"]), "message": w.get("message", ""),
                "can_save": bound > 0 and not instruments.blocking(conflicts),
                "next_status": self._wizard_status(w),
                "next_status_label": instruments.STATUS_LABELS.get(self._wizard_status(w), "")}

    def _wizard_status(self, w):
        """Statut qui sera reellement ecrit : on n'annonce jamais plus que ce qui a ete fait."""
        if not w["bindings"]:
            return instruments.STATUS_UNKNOWN
        try:
            lay = self._catalogue().layouts.get(w.get("layout_id") or "")
        except instruments.InstrumentDataError:
            lay = None
        inst = self._instrument(w["id"])
        supported = inst.type.supported_layout_ids if inst is not None else []
        # table inchangee ET disposition documentee pour ce type : le profil reste « documenté »
        documented = lay is not None and lay.id in supported and lay.bindings() == w["bindings"]
        if w["mode"] == "full" and w["verified"] and set(w["verified"]) >= set(w["bindings"]):
            return instruments.STATUS_CONFIRMED
        if w["tested"] and w["verified"]:
            return instruments.STATUS_QUICK
        return instruments.STATUS_DOCUMENTED if documented else instruments.STATUS_CUSTOM

    def instrument_wizard_start(self, instrument_id, mode="setup"):
        """Ouvre l'assistant. mode « setup » : assistant court ; « full » : validation intégrale."""
        inst = self._instrument(instrument_id)
        if inst is None:
            self._notify("Instrument inconnu.", "warn")
            return self.get_state()
        if self._player.state != "stopped":
            self._notify("Arrête la lecture avant de configurer les touches.", "warn")
            return self.get_state()
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(str(e), "danger")
            return self.get_state()
        self._capture_end(force=True)
        candidates = [{"layoutId": lay.id, "labelFr": lay.label, "descriptionFr": lay.description,
                       "noteCount": lay.note_count, "rows": list(lay.rows), "documented": True}
                      for lay in cat.layouts_for(inst.id)]
        if not candidates:
            # aucun mapping documente pour ce type : les dispositions connues servent de grille de notes a
            # relever, JAMAIS de touches heritees (un instrument inconnu n'herite pas du profil piano).
            candidates = [{"layoutId": lay.id, "labelFr": lay.label, "descriptionFr": lay.description,
                           "noteCount": lay.note_count, "rows": list(lay.rows), "documented": False}
                          for lay in cat.layouts.values()]
        self._wizard = {
            "id": inst.id, "name": inst.name, "image": inst.image, "percussive": inst.percussive,
            "mode": "full" if str(mode) == "full" else "setup",
            "step": 1, "layout_id": inst.layout_id, "layouts": candidates,
            "bindings": dict(inst.bindings),
            "rows": list(inst.layout.rows) if inst.layout is not None else [],
            "start_status": inst.status, "verified": [], "tested": False, "answers": [],
            "capturing": False, "test": None,
            "message": ("Ouvre l'instrument dans Heartopia avant de commencer : choisir ici n'équipe rien "
                        "dans le jeu."),
        }
        return self.get_state()

    def instrument_wizard_state(self):
        """Etat de l'assistant seul, sans effet de bord."""
        return self._wizard_state()

    def instrument_wizard_goto(self, step):
        """Navigation entre les etapes. N'ecrit jamais le profil enregistre."""
        w = self._wizard
        if w is None:
            return self.get_state()
        self._wizard_forget_test(w)
        try:
            step = int(step)
        except (TypeError, ValueError):
            return self.get_state()
        step = max(1, min(len(self.WIZARD_STEPS), step))
        if step >= 4 and not w["bindings"]:
            w["message"] = "Associe d'abord au moins une touche."
            step = 3
        w["step"] = step
        return self.get_state()

    def instrument_wizard_back(self):
        w = self._wizard
        if w is not None:
            self._wizard_forget_test(w)
            w["step"] = max(1, w["step"] - 1)
        return self.get_state()

    def instrument_wizard_layout(self, layout_id, prefill=True):
        """Etape 2 : disposition visible dans le jeu. Les touches d'une disposition documentee sont
        proposees comme point de depart ; pour un type sans mapping documente, seules les notes a relever
        sont posees (aucune touche inventee)."""
        w = self._wizard
        if w is None:
            return self.get_state()
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(str(e), "danger")
            return self.get_state()
        lay = cat.layouts.get(str(layout_id or ""))
        if lay is None:
            return self.get_state()
        self._wizard_forget_test(w)
        documented = any(c["layoutId"] == lay.id and c["documented"] for c in w["layouts"])
        w["layout_id"] = lay.id
        w["rows"] = list(lay.rows)
        if prefill and documented:
            w["bindings"] = {m: k for m, k in lay.bindings().items() if k in platform_io.SCANCODES}
            w["message"] = (f"Touches de « {lay.label} » proposées : profil documenté par une source, "
                            f"non vérifié sur cet ordinateur.")
        else:
            w["bindings"] = {m: k for m, k in w["bindings"].items() if m in lay.bindings()}
            w["message"] = (f"{lay.note_count} notes à relever : appuie sur la touche du jeu pour chaque "
                            f"note, aucune touche n'est devinée pour cet instrument.")
        w["verified"] = []
        w["tested"] = False
        w["answers"] = []
        return self.get_state()

    # alias : l'interface peut nommer cette etape « set_layout »
    def instrument_wizard_set_layout(self, layout_id, prefill=True):
        return self.instrument_wizard_layout(layout_id, prefill)

    def instrument_wizard_capture_begin(self):
        """Debranche les raccourcis globaux pendant la saisie d'une touche (rien ne part au jeu)."""
        if self._wizard is None:
            return self.get_state()
        self._capture_begin()
        self._wizard["capturing"] = True
        return self.get_state()

    def instrument_wizard_capture_end(self):
        """Rebranche les raccourcis globaux, meme si la saisie a ete abandonnee."""
        self._capture_end()
        if self._wizard is not None:
            self._wizard["capturing"] = False
        return self.get_state()

    def instrument_wizard_bind(self, midi, key):
        """Associe une position de touche a une note. Les conflits sont renvoyes avec l'etat."""
        w = self._wizard
        if w is None:
            return self.get_state()
        try:
            m = int(midi)
        except (TypeError, ValueError):
            return self.get_state()
        self._wizard_forget_test(w)
        k = str(key or "").lower()
        if k and k not in platform_io.SCANCODES:
            w["message"] = "Cette touche ne peut pas être envoyée au jeu."
            return self.get_state()
        if not k:
            w["bindings"].pop(m, None)
        else:
            w["bindings"][m] = k
        # une association modifiee annule ce que le test avait montre pour cette note
        w["verified"] = [v for v in w["verified"] if v != m]
        w["message"] = ""
        self._capture_end()
        w["capturing"] = False
        return self.get_state()

    def instrument_wizard_clear(self, midi):
        """Efface une association."""
        return self.instrument_wizard_bind(midi, "")

    def instrument_wizard_test(self, midis=None):
        """Test volontaire dans le jeu : annonce, delai de bascule, 3 touches au maximum, arret accessible.

        Un echantillon de trois notes ne vaut pas validation integrale : le statut obtenu est « Test rapide
        réussi », jamais « confirmé » (sauf en mode validation intégrale, note par note)."""
        w = self._wizard
        if w is None:
            return self.get_state()
        if self._wizard_busy():
            return self.get_state()
        if self._player.state != "stopped" or self._sync.active() or self._room.state in ("armed", "playing"):
            self._notify("Arrête la lecture avant de tester les touches.", "warn")
            return self.get_state()
        if w.get("capturing"):
            self._capture_end()
            w["capturing"] = False
        chosen = []
        if isinstance(midis, (list, tuple)):
            for m in midis:
                try:
                    m = int(m)
                except (TypeError, ValueError):
                    continue
                if m in w["bindings"] and m not in chosen:
                    chosen.append(m)
        if not chosen:
            avail = sorted(w["bindings"])
            if not avail:
                w["message"] = "Associe d'abord au moins une touche."
                return self.get_state()
            rest = [m for m in avail if m not in w["verified"]]
            if w["mode"] == "full" and rest:
                # validation integrale : on avance dans les associations encore non verifiees, par groupes
                chosen = rest[:self.WIZARD_TEST_KEYS]
            else:
                # echantillon reparti sur le registre (grave, milieu, aigu) : plus parlant que trois voisines
                picks = {0, len(avail) // 2, len(avail) - 1}
                chosen = [avail[i] for i in sorted(picks)]
        chosen = chosen[:self.WIZARD_TEST_KEYS]
        delay = max(2.0, float(self._cfg.get("start_delay", 1.0) or 1.0) + 3.0)
        delay = min(delay, self.WIZARD_TEST_DELAY + 2.0)
        test = {"state": "countdown", "midis": list(chosen),
                "keys": [w["bindings"][m] for m in chosen],
                "labels": [instruments.key_label(w["bindings"][m], self._keyboard_layout()) for m in chosen],
                "solfege": [instruments.solfege(m) for m in chosen],
                "delay": delay, "ends": time.time() + delay, "index": -1,
                "message": "Passe sur Heartopia : DodoTopia va appuyer sur ces touches."}
        w["test"] = test
        w["message"] = ""
        self._minimize_for_game()
        threading.Thread(target=self._wizard_test_run, args=(test, list(chosen)),
                         name="instrument-test", daemon=True).start()
        return self.get_state()

    def _wizard_test_alive(self, test, w):
        """Vrai tant que ce test est celui de l'assistant ouvert et qu'il n'a pas ete arrete."""
        return (w or {}).get("test") is test and test.get("state") in ("countdown", "playing")

    def _wizard_test_pause(self, test, w, seconds):
        """Attente decoupee : l'arret (F7, bouton) doit etre pris en compte entre deux frappes, pas
        seulement au debut de la boucle."""
        end = time.time() + seconds
        while time.time() < end:
            if not self._wizard_test_alive(test, w):
                return False
            time.sleep(0.03)
        return self._wizard_test_alive(test, w)

    def _wizard_test_run(self, test, midis):
        """Envoi de l'echantillon dans le jeu, dans un fil : compte a rebours interruptible puis 3 frappes."""
        w = self._wizard
        try:
            while time.time() < test["ends"]:
                if test.get("state") != "countdown" or (w or {}).get("test") is not test:
                    return
                time.sleep(0.05)
            for i, m in enumerate(midis):
                if not self._wizard_test_alive(test, w):
                    return
                if self._player.state != "stopped":
                    test["state"] = "cancelled"
                    test["message"] = "Test interrompu : une lecture a démarré."
                    return
                test["state"] = "playing"
                test["index"] = i
                key = w["bindings"].get(m)
                if not key:
                    continue
                self._player.play_keys([key], hold=0.12)
                if not self._wizard_test_pause(test, w, 0.7):
                    return
            if not self._wizard_test_alive(test, w):
                return
            test["index"] = -1
            test["state"] = "answer"
            test["message"] = ("Qu'as-tu entendu dans le jeu ?" if not w["percussive"]
                               else "Quelle frappe as-tu entendue ?")
        except Exception as e:  # noqa - un echec d'injection ne doit pas tuer le fil silencieusement
            test["state"] = "error"
            test["message"] = f"Test impossible : {e}"
            self._log(f"test des touches : {e!r}")

    def instrument_wizard_test_stop(self):
        """Arret du test, accessible a tout moment."""
        self._wizard_test_abort("Test arrêté : aucune autre touche n'a été envoyée.")
        return self.get_state()

    def instrument_wizard_answer(self, ok, note_or_strike=""):
        """Reponse de l'utilisateur au test. Pour une percussion, `note_or_strike` decrit la FRAPPE
        entendue (pas un Do/Ré arbitraire)."""
        w = self._wizard
        if w is None or not w.get("test"):
            return self.get_state()
        test = w["test"]
        if test.get("state") not in ("answer",):
            # test arrete ou en erreur : repondre « oui » ne prouverait rien, aucune touche n'est partie
            self._wizard_forget_test(w)
            w["message"] = (test.get("message") or "Le test n'est pas allé au bout : relance-le avant de "
                                                   "répondre.")
            w["step"] = 4
            return self.get_state()
        midis = list(test.get("midis") or [])
        detail = core.clean_display_text(note_or_strike, 80) if note_or_strike else ""
        ok = bool(ok) and not (isinstance(ok, str) and ok.strip().lower() in ("0", "non", "false"))
        w["answers"].append({"midis": midis, "ok": ok, "detail": detail,
                             "keys": list(test.get("keys") or [])})
        if ok:
            w["tested"] = True
            for m in midis:
                if m not in w["verified"]:
                    w["verified"].append(m)
            rest = len(set(w["bindings"]) - set(w["verified"]))
            if w["mode"] == "full" and rest:
                w["message"] = (f"Test rapide réussi sur {len(midis)} note(s). Validation intégrale : "
                                f"{rest} association(s) restent à vérifier.")
                w["step"] = 4
            else:
                w["message"] = ("Test rapide réussi : vérification partielle, seules les touches envoyées "
                                "ont été contrôlées.")
                w["step"] = 5
        else:
            for m in midis:
                if m in w["verified"]:
                    w["verified"].remove(m)
            w["tested"] = False
            w["message"] = ("Ces touches n'ont pas produit ce qui était attendu : corrige les associations "
                            "puis recommence le test.")
            w["step"] = 3
        w["test"] = None
        return self.get_state()

    def _wizard_save_result(self, ok, error=""):
        """Verdict explicite de l'enregistrement : l'interface ne doit annoncer « Profil enregistré » que
        quand il l'est vraiment, et rester sur l'etape sinon."""
        return {"ok": bool(ok), "error": "" if ok else str(error or ""), "state": self.get_state()}

    def instrument_wizard_save(self):
        """Ecrit le profil : statut « personnalisé », « test rapide » ou « confirmé » selon ce qui a
        reellement ete fait, jamais plus.

        Renvoie {ok, error, state} et non l'etat seul : un refus silencieux ferait perdre le travail de
        l'utilisateur sans qu'il le sache."""
        w = self._wizard
        if w is None:
            return self._wizard_save_result(False, "L'assistant n'est plus ouvert : rien n'a été enregistré.")
        if w["id"] == self._player.instrument.id and self._player.state != "stopped":
            # meme garde-fou que set_instrument_layout et import_instrument_profile : on ne change pas le
            # profil de l'instrument qui joue sous les pieds de la lecture
            msg = "Arrête la lecture avant d'enregistrer les touches."
            self._notify(msg, "warn")
            return self._wizard_save_result(False, msg)
        conflicts = instruments.conflicts(w["bindings"], self._cfg)
        if instruments.blocking(conflicts):
            msgs = [c["message"] for c in conflicts if c.get("severity") == "error"]
            msg = "Enregistrement refusé : " + (msgs[0] if msgs else "conflit de touches.")
            self._notify(msg, "warn")
            w["step"] = 3
            return self._wizard_save_result(False, msg)
        if not w["bindings"]:
            msg = "Associe au moins une touche avant d'enregistrer."
            self._notify(msg, "warn")
            return self._wizard_save_result(False, msg)
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(str(e), "danger")
            return self._wizard_save_result(False, str(e))
        status = self._wizard_status(w)
        verified_at = time.strftime("%Y-%m-%dT%H:%M:%S") if status in (
            instruments.STATUS_QUICK, instruments.STATUS_CONFIRMED) else None
        extra = {"keyboard_layout": self._keyboard_layout()} if w["tested"] else {}
        instruments.set_profile(self._cfg, w["id"], layout_id=w.get("layout_id"), bindings=w["bindings"],
                                status=status, verified_at=verified_at, catalogue=cat, **extra)
        core.save_config(self._cfg)
        self._capture_end(force=True)
        name = w["name"]
        self._wizard = None
        self._rebuild_instruments()
        self._notify(f"{name} : {instruments.STATUS_LABELS.get(status, status)}", "ok")
        return self._wizard_save_result(True)

    def instrument_wizard_cancel(self):
        """Ferme l'assistant sans rien ecrire : un profil valide n'est jamais ecrase."""
        w = self._wizard
        if w and w.get("test"):
            w["test"]["state"] = "cancelled"
        self._capture_end(force=True)
        self._wizard = None
        return self.get_state()

    # ---------------------------------------------------------- profils : export / import
    def export_instrument_profile(self, instrument_id, path=None):
        """Profil d'un type au format JSON (donnees seulement). Propose un enregistrement de fichier."""
        inst = self._instrument(instrument_id)
        if inst is None:
            return {"ok": False, "error": "Instrument inconnu."}
        prof = instruments.profile_of(self._cfg, inst.id)
        payload = {"format": "dodotopia-instrument-profile",
                   "schemaVersion": instruments.SCHEMA_VERSION, "app": VERSION,
                   "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "instrumentId": inst.id, "labelFr": inst.name, "labelEn": inst.label_en,
                   "layoutId": prof.get("layoutId"), "keyboardLayout": prof.get("keyboardLayout"),
                   "verificationStatus": prof.get("verificationStatus"),
                   "verifiedAt": prof.get("verifiedAt"), "gameVersion": prof.get("gameVersion"),
                   "polyphony": prof.get("polyphony"),
                   "soundingPitchOffset": prof.get("soundingPitchOffset"),
                   "bindings": {str(m): k for m, k in sorted(inst.bindings.items())}}
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if path is None and self._window is not None:
            try:
                path = self._window.create_file_dialog(
                    webview.SAVE_DIALOG, save_filename=f"profil-{inst.id}.json",
                    file_types=("Profil DodoTopia (*.json)", "Tous les fichiers (*.*)"))
            except Exception as e:  # noqa
                self._log(f"export de profil : {e}")
                path = None
        if isinstance(path, (list, tuple)):
            path = path[0] if path else None
        saved = None
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                saved = str(path)
                self._notify(f"Profil exporté : {os.path.basename(saved)}", "ok")
            except OSError as e:
                self._notify(f"Export impossible : {e}", "warn")
        return {"ok": True, "payload": payload, "text": text, "path": saved}

    MAX_PROFILE_BYTES = 200_000

    def import_instrument_profile(self, payload=None, instrument_id=None):
        """Lit un profil JSON : validation du schéma, rien n'est exécuté du contenu importé.

        Un profil « confirmé » ailleurs redevient « touches personnalisées · à vérifier » : une validation
        faite sur un autre ordinateur ne prouve rien sur celui-ci."""
        data = payload
        if data is None:
            if self._window is None:
                return self.get_state()
            try:
                files = self._window.create_file_dialog(
                    webview.OPEN_DIALOG, allow_multiple=False,
                    file_types=("Profil DodoTopia (*.json)", "Tous les fichiers (*.*)"))
            except Exception as e:  # noqa
                self._notify(f"Import impossible : {e}", "warn")
                return self.get_state()
            if not files:
                return self.get_state()
            try:
                with open(files[0], "r", encoding="utf-8") as f:
                    data = f.read(self.MAX_PROFILE_BYTES + 1)
            except OSError as e:
                self._notify(f"Fichier illisible : {e}", "warn")
                return self.get_state()
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", "replace")
        if isinstance(data, str):
            if len(data) > self.MAX_PROFILE_BYTES:
                self._notify("Profil refusé : fichier trop gros.", "warn")
                return self.get_state()
            try:
                data = json.loads(data)
            except ValueError:
                self._notify("Profil refusé : ce n'est pas un fichier JSON valide.", "warn")
                return self.get_state()
        if not isinstance(data, dict):
            self._notify("Profil refusé : format inattendu.", "warn")
            return self.get_state()
        wanted = str(instrument_id or data.get("instrumentId") or "")
        wanted = instruments.LEGACY_IDS.get(wanted, wanted)
        inst = self._instrument(wanted)
        if inst is None:
            self._notify(f"Profil refusé : instrument inconnu ({wanted or '?'}).", "warn")
            return self.get_state()
        if inst.id == self._player.instrument.id and self._player.state != "stopped":
            self._notify("Arrête la lecture avant d'importer un profil.", "warn")
            return self.get_state()
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(str(e), "danger")
            return self.get_state()
        raw_bindings = data.get("bindings")
        bindings, rejected = {}, 0
        if isinstance(raw_bindings, dict):
            for m, k in raw_bindings.items():
                try:
                    m = int(m)
                except (TypeError, ValueError):
                    rejected += 1
                    continue
                k = str(k or "").lower()
                if 0 <= m <= 127 and k in platform_io.SCANCODES:
                    bindings[m] = k
                else:
                    rejected += 1
        layout_id = data.get("layoutId")
        layout_id = layout_id if layout_id in cat.layouts else None
        if not bindings and not layout_id:
            self._notify("Profil refusé : ni touches utilisables ni disposition connue.", "warn")
            return self.get_state()
        conflicts = instruments.conflicts(bindings, self._cfg)
        if instruments.blocking(conflicts):
            msgs = [c["message"] for c in conflicts if c.get("severity") == "error"]
            self._notify("Profil refusé : " + (msgs[0] if msgs else "conflit de touches."), "warn")
            return self.get_state()
        status = data.get("verificationStatus")
        if status not in instruments.STATUSES or status in (instruments.STATUS_QUICK,
                                                            instruments.STATUS_CONFIRMED):
            # ce qui a ete verifie ailleurs reste a verifier ici
            status = instruments.STATUS_CUSTOM if bindings else instruments.STATUS_DOCUMENTED
        instruments.set_profile(self._cfg, inst.id, layout_id=layout_id,
                                bindings=bindings or None, status=status, verified_at=None,
                                catalogue=cat)
        core.save_config(self._cfg)
        self._rebuild_instruments()
        extra = f" ({rejected} entrée(s) ignorée(s))" if rejected else ""
        self._notify(f"Profil importé pour {inst.name} : à vérifier dans le jeu{extra}.", "ok")
        return self.get_state()

    # ---------------------------------------------------------- compatibilite du morceau
    def _song_compat(self):
        """Diagnostic du morceau courant sur l'instrument courant.

        Recalcule seulement quand (morceau, empreinte du profil, transposition, options) change, et dans un
        fil : get_state() est appele plusieurs fois par seconde, il ne doit jamais relire un .mid."""
        p = self._player
        song = p.current()
        inst = p.instrument
        if not song or not inst.bindings:
            self._compat_key = None
            self._compat = None
            return None
        key = (song, inst.fingerprint, int(self._cfg.get("transpose_semitones", 0) or 0),
               bool(self._cfg.get("fold_out_of_range", True)), bool(self._cfg.get("ignore_drums", True)))
        if key != self._compat_key:
            self._compat_key = key
            self._compat = {"pending": True, "song": os.path.basename(song), "instrument_id": inst.id,
                            "instrument": inst.name}
            threading.Thread(target=self._compat_worker, args=(key, song, inst),
                             name="song-compat", daemon=True).start()
        return self._compat

    def _compat_worker(self, key, song, inst):
        try:
            stats = {}
            grouped = core.parse_midi(song, self._cfg, stats)
            report = core.compat_report(grouped, inst, self._cfg, stats=stats)
        except Exception as e:  # noqa - fichier illisible, refuse, disparu : diagnostic sans diagnostic
            if self._compat_key == key:
                self._compat = {"pending": False, "error": str(e), "song": os.path.basename(song),
                                "instrument_id": inst.id, "instrument": inst.name}
            return
        if self._compat_key != key:
            return          # l'utilisateur a change de morceau ou d'instrument entre-temps
        self._compat_notes = (key, grouped)
        report.update({"pending": False, "song": os.path.basename(song), "instrument_id": inst.id,
                       "instrument": inst.name, "ready": bool(inst.ready),
                       "transpose": int(self._cfg.get("transpose_semitones", 0) or 0),
                       "fold": bool(self._cfg.get("fold_out_of_range", True))})
        self._compat = report

    def _compat_grouped(self):
        """Notes groupees du morceau courant (cache du diagnostic), relues si besoin."""
        key = self._compat_key
        cached = self._compat_notes
        if cached and cached[0] == key:
            return cached[1]
        song = self._player.current()
        if not song:
            return None
        grouped = core.parse_midi(song, self._cfg)
        self._compat_notes = (key, grouped)
        return grouped

    def song_compat_preview(self, shift):
        """Couverture simulee pour une transposition candidate : l'effet annonce est reellement mesure.

        `shift` : demi-tons AJOUTES a la transposition retenue par le diagnostic."""
        try:
            shift = int(shift)
        except (TypeError, ValueError):
            return {"ok": False, "error": "valeur attendue en demi-tons"}
        inst = self._player.instrument
        if not inst.bindings:
            return {"ok": False, "error": inst.blocked_reason}
        base = int((self._compat or {}).get("shift") or 0)
        try:
            grouped = self._compat_grouped()
        except Exception as e:  # noqa
            return {"ok": False, "error": str(e)}
        if not grouped:
            return {"ok": False, "error": "aucun morceau sélectionné"}
        total = base + shift
        _, info = core.fit_notes(grouped, inst, self._cfg, shift=total)
        return {"ok": True, "shift": shift, "total_shift": total, "coverage": info["coverage"],
                "out_of_range": info["out_of_range"], "missing_accidental": info["missing_accidental"],
                "dropped": info["dropped"], "notes": info["notes"]}

    def song_compat_apply(self, kind, value=0):
        """Applique une option proposee par le diagnostic (jamais appliquee toute seule) :
        « transpose » / « octave » ajoutent des demi-tons, « omit » cesse de replier les notes hors
        registre, « reset » revient aux reglages de depart."""
        kind = str(kind or "")
        if kind in ("transpose", "octave"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return self.get_state()
            cur = int(self._cfg.get("transpose_semitones", 0) or 0)
            r = self.set_setting("transpose_semitones", max(-24, min(24, cur + value)))
            if not r.get("ok"):
                self._notify(r.get("error") or "Transposition refusée", "warn")
            else:
                self._notify(f"Transposition : {r['value']:+d} demi-ton(s)", "ok")
        elif kind == "omit":
            self._cfg["fold_out_of_range"] = False
            core.save_config(self._cfg)
            self._notify("Les notes hors registre sont maintenant omises (plus de repli d'octave).", "ok")
        elif kind == "fold":
            self._cfg["fold_out_of_range"] = True
            core.save_config(self._cfg)
            self._notify("Les notes hors registre sont de nouveau rejouées une octave plus loin.", "ok")
        elif kind == "reset":
            self._cfg["fold_out_of_range"] = True
            self.set_setting("transpose_semitones", 0)
            self._notify("Réglages du morceau remis à zéro.", "ok")
        return self.get_state()

    # ---------------------------------------------------------- reglages
    # ---- effets de bord des reglages (noms references par settings_schema.SCHEMA["after"])
    def _apply_after(self, name):
        fn = getattr(self, name, None) if name else None
        if not callable(fn):
            return
        try:
            fn()
        except Exception as e:  # noqa
            self._log(f"réglage : effet {name} : {e}")

    def _on_transpose(self):
        """La transposition est lue a la prochaine preparation d'un morceau ; une lecture en cours n'est pas touchee."""

    def _on_keyboard_layout(self):
        """Disposition du clavier physique : elle ne change aucune position envoyee au jeu, seulement les
        legendes affichees. Mais une conclusion prise avec l'ancienne disposition n'est plus garantie : les
        profils confirmes ou testes repassent a « touches personnalisées · à vérifier », touches conservees."""
        kb = self._keyboard_layout()
        if kb == getattr(self, "_kb_layout", None):
            return
        self._kb_layout = kb
        touched = []
        for inst in list(self._player.instruments):
            if inst.status in (instruments.STATUS_QUICK, instruments.STATUS_CONFIRMED):
                instruments.set_profile(self._cfg, inst.id, status=instruments.STATUS_CUSTOM,
                                        verified_at=None, keyboard_layout=kb)
                touched.append(inst.name)
        if touched:
            self._rebuild_instruments()
            names = ", ".join(touched[:3]) + (f" et {len(touched) - 3} autre(s)" if len(touched) > 3 else "")
            self._notify(f"Clavier {kb.upper()} : {names} repasse(nt) à « à vérifier » "
                         f"(aucune touche supprimée).", "warn")

    def _on_volume(self):
        """Volume de l'ecoute : applique tout de suite a la sortie MIDI si elle est ouverte."""
        midi = getattr(self._player, "_midi", None)
        if midi is not None:
            midi.volume(int(self._cfg.get("preview_volume", 100)) * 127 // 100)

    def _on_play_mode(self):
        """solo | audio | room : `enabled` (interrupteur historique) suit le mode ; quitter le mode audio annule
        une session de synchronisation en cours. Le mode « room » (salon en ligne) sera branche avec le client reseau."""
        m = sync.ensure_defaults(self._cfg)
        mode = m.get("mode", "solo")
        m["enabled"] = (mode == "audio")
        if mode != "audio" and self._sync.active():
            self._sync.abort("mode " + mode)
        if mode != "room" and self._room.active():
            self._log("salon : changement de mode, on quitte")
            self._room.leave()

    def _on_cookers(self):
        """Nombre de cuisinieres servies par la boucle de cuisine : applique au module Cuisine. Une boucle en
        cours est arretee proprement (les machines a etats sont refaites au prochain demarrage)."""
        n, stopped = self._cook.apply_cookers()
        if stopped:
            self._notify(f"Cuisine arrêtée : relance-la pour servir {n} cuisinière{'s' if n > 1 else ''}.", "warn")

    def _on_server_url(self):
        """Adresse du serveur : nouveau client HTTP, compte recharge (invalide si l'URL change), sante refaite."""
        self._online.apply_config()

    def _on_check_updates(self):
        """Mises a jour automatiques (re)activees : une verification tout de suite si rien n'est en cours."""
        o = online.ensure_defaults(self._cfg)
        if o.get("check_updates") and self._online.updater.state in ("idle", "error", "uptodate"):
            self._online.updater.check_async()

    def set_setting(self, path, value):
        """Un champ du panneau Reglages : valide, borne et convertit (settings_schema), ecrit, sauve, applique
        l'effet de bord. Aucun toast : l'interface affiche l'erreur sous le champ et remet la valeur renvoyee."""
        try:
            v, after = settings_schema.set_value(self._cfg, path, value)
        except settings_schema.SettingError as e:
            try:
                cur = settings_schema.to_ui(path, settings_schema.get(self._cfg, path))
            except settings_schema.SettingError:
                cur = None
            return {"ok": False, "path": path, "error": str(e), "value": cur}
        self._apply_after(after)
        if path == "online.check_updates":
            self._apply_after("_on_check_updates")
        core.save_config(self._cfg)
        return {"ok": True, "path": path, "value": settings_schema.to_ui(path, v), "state": self.get_state()}

    def reset_settings(self, section):
        """Remet une section (settings_schema.SECTIONS) a ses valeurs par defaut, sans toucher aux autres."""
        try:
            afters = settings_schema.reset(self._cfg, section)
        except settings_schema.SettingError as e:
            return {"ok": False, "error": str(e), "state": self.get_state()}
        for a in afters:
            self._apply_after(a)
        core.save_config(self._cfg)
        return {"ok": True, "state": self.get_state()}

    def get_settings_schema(self):
        """Tout ce qu'il faut au panneau Reglages : champs (bornes, unites, defaut, valeur), sections, libelles."""
        try:
            devices = sync.LoopbackCapture.list_devices()
        except Exception:  # noqa
            devices = []
        try:
            kind = online.Updater.install_kind()
        except Exception:  # noqa
            kind = "source"
        logs = {n: os.path.isfile(os.path.join(core.DATA_DIR, f"{n}.log")) for n in ("multi", "dessin", "cuisine", "online")}
        return {"fields": settings_schema.for_ui(self._cfg), "sections": list(settings_schema.SECTIONS),
                "hotkey_labels": dict(settings_schema.HOTKEY_LABELS), "multi_devices": devices,
                "songs_folder": self._player.songs_folder, "data_dir": core.DATA_DIR, "version": VERSION,
                "install_kind": kind, "logs": logs, "online_ready": True}

    def save_settings(self, settings, quiet=False):
        """Facade historique (formulaire complet) : chaque champ passe par settings_schema dans les unites de
        l'interface (ms pour ce qui dure moins d'une seconde) ; une valeur refusee est ignoree sans bloquer les
        autres. `quiet` est conserve pour les anciens appels ; il n'y a plus de toast."""
        afters = []

        def put(path, value):
            try:
                _, after = settings_schema.set_value(self._cfg, path, value)
            except settings_schema.SettingError as e:
                self._log(f"réglage {path} refusé : {e}")
                return
            if after and after not in afters:
                afters.append(after)

        for key, val in (settings or {}).items():
            if key == "hotkeys" and isinstance(val, dict):
                for k, v in val.items():
                    if k in self._cfg["hotkeys"]:
                        put(f"hotkeys.{k}", v)
            elif key in ("multi", "draw", "cook", "online") and isinstance(val, dict):
                for k, v in val.items():
                    if key == "multi" and k == "enabled":
                        put("multi.mode", "audio" if v else "solo")
                    elif key == "draw" and k == "grids" and isinstance(v, dict):
                        for fmt, wh in v.items():
                            try:
                                put(f"draw.formats.{fmt}.cols", wh[0])
                                put(f"draw.formats.{fmt}.rows", wh[1])
                            except (TypeError, IndexError, KeyError):
                                pass
                    else:
                        put(f"{key}.{k}", v)
            else:
                put(key, val)
        if isinstance((settings or {}).get("online"), dict) and "check_updates" in settings["online"] \
                and "_on_check_updates" not in afters:
            afters.append("_on_check_updates")
        for a in afters:
            self._apply_after(a)
        core.save_config(self._cfg)
        return self.get_state()

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
            self._notify(f"En ligne : {e}", "warn")
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

    def online_search(self, q="", page=1, sort="recent"):
        self._online_call(self._online.search, q, page, sort)
        return self.get_state()

    def online_download(self, online_id):
        self._online_call(self._online.download, online_id)
        return self.get_state()

    def online_share(self, song_id):
        """Depose une musique locale sur le serveur (file de moderation)."""
        song_id = os.path.basename(str(song_id or ""))
        path = os.path.join(self._player.songs_folder, song_id)
        if not song_id or not os.path.isfile(path):
            self._notify("Musique introuvable", "warn")
            return self.get_state()
        title = self._player.library.meta(song_id).get("title") or core.clean_title(song_id)
        self._online_call(self._online.share, song_id, path, title)
        return self.get_state()

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

    def room_set_offset(self, ms):
        """Avance (negatif) / retard du joueur en ms (-300..300) : reglage multi.net_offset_ms + salon."""
        r = self.set_setting("multi.net_offset_ms", ms)
        if not r.get("ok"):
            self._notify(r.get("error") or "Valeur refusée", "warn")
            return self.get_state()
        self._online_call(self._room.set_net_offset, r["value"])
        return self.get_state()

    def quit(self):
        self._drawer.stop("fermeture")
        self._cook.stop("fermeture")
        self._sync.abort("fermeture")
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


def main():
    # coordonnees physiques de l'ecran (souris, captures) meme avec une mise a l'echelle Windows
    platform_io.set_dpi_aware()
    platform_io.set_app_id()      # icone de la barre des taches liee a DodoTopia, pas au cache de l'hote
    api = Api()
    title = "DodoTopia"
    window = webview.create_window(
        title, UI_PATH, js_api=api,
        width=1040, height=720, min_size=(960, 660),
        background_color="#f4ead8")
    api._window = window
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
    webview.start(debug="--debug" in sys.argv, **platform_io.webview_start_kwargs(core.RES_DIR))
    api._drawer.stop("fermeture")
    api._cook.stop("fermeture")
    try:
        api._online.close()
    except Exception as e:  # noqa
        api._log(f"en ligne : fermeture : {e}")
    api._player.close()


if __name__ == "__main__":
    main()
