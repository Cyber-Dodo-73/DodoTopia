# -*- coding: utf-8 -*-
"""DodoTopia : interface graphique (fenetre WebView2 + moteur core.py)."""
import base64
import json
import os
import shutil
import sys
import time
from collections import deque

import webview

import cook
import core
import draw
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
        self._bind_hotkeys()
        try:
            self._is_admin = bool(platform_io.is_admin())
        except Exception:
            self._is_admin = False
        self._last_reason = ""

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
            if not self._room.stop_request("stop"):
                p.stop()
                self._sync.abort("stop")
            d.stop("stop")
            c.stop("stop")

        def next_instrument():
            p.next_instrument()
            self._room.on_instrument_change(p.instrument)

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
        if p._hook is None:
            p._hook = platform_io.hook(p._on_key_event)
        if d._hook is None:
            d._hook = platform_io.hook(d.on_key_event)
        if c._hook is None:
            c._hook = platform_io.hook(c.on_key_event)

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
            self._notify("Importe d'abord une image dans l'onglet Image", "warn")

    def _cook_toggle(self, from_ui=False):
        """F6 / bouton Cuisiner en boucle : lance ou arrete la cuisine (ou capture un point en calibrage)."""
        c = self._cook
        if c.state == "cooking":
            c.stop("stop")
        elif c.state == "calibrating":
            c.capture_point()
        elif not c.calibrated():
            self._notify("Calibre d'abord la cuisine (bouton Calibrer de l'onglet Cuisine)", "warn")
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
                and self._room.state not in ("armed", "playing")
                and self._drawer.state not in ("drawing", "autocal") and self._cook.state != "cooking"):
            self._minimized = False
            try:
                self._window.restore()
            except Exception:
                pass
        dcfg = self._cfg.get("draw") or {}
        ccfg = self._cfg.get("cook") or {}
        ocfg = online.ensure_defaults(self._cfg)
        mode = self._cfg["multi"].get("mode", "solo")
        ost = self._online.status()                 # copie sous verrou, aucune E/S reseau
        self._sync_update_toast(ost.get("update"))
        return {
            "version": VERSION,
            "instruments": [i.to_dict() for i in p.instruments],
            "instrument": p.inst_index,
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
        self._tab = name if name in ("image", "cook", "online") else "music"
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
        added, skipped = self._import_files(paths)
        if added:
            self._player.index = self._player.songs.index(
                os.path.join(self._player.songs_folder, added[-1]))
            s = "s" if len(added) > 1 else ""
            self._notify(f"{len(added)} musique{s} importée{s}", "ok")
        if skipped:
            self._notify(f"Ignoré (pas un .mid) : {', '.join(skipped[:3])}", "warn")
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
        """Bouton Arreter et F7 : en salon, le chef arrete tout le monde ; un invite ne coupe que lui."""
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

    def set_instrument(self, index):
        self._player.set_instrument(int(index))
        core.save_config(self._cfg)
        self._room.on_instrument_change(self._player.instrument)
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
