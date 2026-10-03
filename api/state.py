# -*- coding: utf-8 -*-
"""get_state() : l'etat complet sonde par l'interface, et ce qui n'y est calcule qu'au changement."""
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


class StateMixin:
    # ---------------------------------------------------------- etat
    def _songs_state(self):
        """Liste des morceaux pour l'interface, recalculee seulement quand la bibliotheque change (fichiers ou
        metadonnees) : get_state() est appele plusieurs fois par seconde, il ne doit faire aucune E/S."""
        p = self._player
        sig = (tuple(p.songs), p.library.version)
        cached = self._songs_cache
        if cached is not None and cached[0] == sig:
            return cached[1]
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
                "tracks_off": list(m.get("tracks_off") or []),
                "arrange": m.get("arrange"),
                "source_url": m.get("source_url"),
                "source_name": m.get("source_name"),
            })
        self._songs_cache = (sig, songs)
        return songs

    def _game_window_state(self):
        """Etat de la fenetre du jeu {found, foreground, elevated}, rafraichi au plus une fois par seconde."""
        info, at = self._game_window
        now = time.time()
        if now - at > 1.0:
            name = str(self._cfg.get("game_process") or "").strip()
            try:
                info = (platform_io.game_window_info(platform_io.game_names(name), platform_io.GAME_TITLES)
                        if name else {"found": None, "foreground": None, "elevated": None})
            except Exception:  # noqa
                info = {"found": None, "foreground": None, "elevated": None}
            info = dict(info)
            info["process"] = name
            info["checked"] = bool(name)
            self._game_window = (info, now)
        return info

    def get_state(self):
        p = self._player
        songs = self._songs_state()
        # erreur explicite pour l'interface (composant .notice de la carte Musique) : {msg, kind, since} | None.
        # last_stop_reason est un CODE (core.STOP_CODES) traduit ici ; arret voulu (touche, clic, salon) = info,
        # erreur de lecture / capture audio = danger. Efface au prochain depart (remis a "" par play/play_at).
        with self._ui_lock:
            if p.last_stop_reason and p.last_stop_reason != self._last_reason:
                self._last_reason = p.last_stop_reason
                reason = p.last_stop_reason
                benign = reason in core.BENIGN_STOP_CODES
                text = core.stop_reason_text(reason)
                self._error = {"msg": text, "kind": "info" if benign else "danger", "since": time.time(),
                               "target": p.target, "reason": reason}
                if not benign:
                    self._notify(text, "warn")
            elif not p.last_stop_reason:
                self._last_reason = ""
                if self._error and self._error.get("reason") != "multi":
                    self._error = None
            mu_status = self._sync.status()
            if mu_status["state"] == "idle":
                # session Multi terminee sur une erreur (capture audio, sortie introuvable...) : la session
                # le dit explicitement (`error`), aucune reconnaissance de texte
                smsg = mu_status.get("error") or ""
                if smsg != self._last_sync_msg:
                    self._last_sync_msg = smsg
                    if smsg:
                        self._error = {"msg": smsg, "kind": "danger", "since": time.time(), "target": "game", "reason": "multi"}
            else:
                self._last_sync_msg = ""
                if self._error and self._error.get("reason") == "multi":
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
        mode = self._play_mode()
        ost = self._online.status()                 # copie sous verrou, aucune E/S reseau
        self._sync_update_toast(ost.get("update"))
        st = {
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
            "resume": p.resume_info() if p.state == "stopped" else None,
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
                "arrange": self._cfg.get("arrange", "auto"),
                "multi": {**{k: self._cfg["multi"].get(k) for k in
                          ("enabled", "mode", "name", "player_id", "countdown", "lead", "offset_ms", "net_offset_ms",
                           "latency", "beacon_freqs", "tune", "device", "calib")}, "mode": mode},
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
            "game_window": self._game_window_state(),
            "terms": terms.state(self._cfg),
            "error": dict(self._error) if self._error else None,
            "tab": self._tab,
            "draw": self._drawer.status(),
            "draw_stats": self._draw_stats,
            "cook": self._cook.status(),
        }
        # lien dodotopia:// en attente de confirmation : {id, action, label, params} | None
        st["deeplink"] = self._deeplink_state()
        try:
            self._integrations_tick(songs, ost.get("room"))
        except Exception as e:  # noqa : une integration ne doit jamais casser l'etat de l'interface
            self._warn_once("tick", f"intégrations : {e!r}")
        return st

    def set_tab(self, name):
        """Activite ouverte : music | image (dessin) | cook | creations. Les raccourcis suivent cette valeur
        (« creations » garde ceux de la musique, comme l'ancien onglet En ligne).
        « online » est accepte pour compatibilite : le catalogue est maintenant une vue de la Musique."""
        self._tab = name if name in ("image", "cook", "creations") else "music"
        return True
