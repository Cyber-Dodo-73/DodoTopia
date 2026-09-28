# -*- coding: utf-8 -*-
"""Lecture (ecoute / jeu), mode de jeu (solo, son, salon), diagnostic de compatibilite du morceau."""
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


class MusicMixin:
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
        self._wizard_test_abort(i18n.t("wizard.test.stopped"))
        if not self._room.stop_request("stop"):
            self._player.stop()
            self._sync.abort("stop")
        return self.get_state()

    def resume_song(self):
        """Reprend dans le jeu le morceau interrompu, a l'endroit ou il s'est arrete (solo)."""
        if self._room.active() or self._sync.active():
            self._notify(i18n.t("api.music.resume_solo_only"), "warn")
            return self.get_state()
        if self._player.resume():
            self._minimize_for_game()
        else:
            self._notify(i18n.t("api.music.nothing_to_resume"), "warn")
        return self.get_state()

    def forget_song_resume(self):
        self._player.forget_resume()
        return self.get_state()

    def room_rejoin(self):
        """Salon : reprendre la lecture la ou en sont les autres (apres un arret par erreur)."""
        self._room.rejoin()
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
            self._notify(i18n.t("api.mode.unknown", mode=mode), "warn")
            return self.get_state()
        if mode == "room":
            mode = "solo"       # le salon se deduit du salon rejoint (voir _play_mode) : rien a memoriser
        r = self.set_setting("multi.mode", mode)
        if not r.get("ok"):
            self._notify(r.get("error") or i18n.t("api.mode.refused"), "warn")
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
            self._notify(i18n.t("api.busy"), "warn")
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
            self._notify(i18n.t("api.busy"), "warn")
        return self.get_state()

    def multi_listen_test(self, seconds=30):
        try:
            seconds = max(5.0, min(120.0, float(seconds)))
        except (TypeError, ValueError):
            seconds = 30.0
        if self._sync.listen_test(seconds):
            self._minimize_for_game()
        else:
            self._notify(i18n.t("api.busy"), "warn")
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
            return {"ok": False, "error": i18n.t("api.compat.semitones_expected")}
        inst = self._player.instrument
        if not inst.bindings:
            return {"ok": False, "error": inst.blocked_reason}
        base = int((self._compat or {}).get("shift") or 0)
        try:
            grouped = self._compat_grouped()
        except Exception as e:  # noqa
            return {"ok": False, "error": str(e)}
        if not grouped:
            return {"ok": False, "error": i18n.t("api.compat.no_song")}
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
                self._notify(r.get("error") or i18n.t("api.transpose.refused"), "warn")
            else:
                self._notify(i18n.t("api.transpose.applied", delta=f"{r['value']:+d}", n=abs(int(r["value"]))), "ok")
        elif kind == "omit":
            self._cfg["fold_out_of_range"] = False
            core.save_config(self._cfg)
            self._notify(i18n.t("api.compat.omit_on"), "ok")
        elif kind == "fold":
            self._cfg["fold_out_of_range"] = True
            core.save_config(self._cfg)
            self._notify(i18n.t("api.compat.fold_on"), "ok")
        elif kind == "reset":
            self._cfg["fold_out_of_range"] = True
            self.set_setting("transpose_semitones", 0)
            self._notify(i18n.t("api.compat.reset"), "ok")
        return self.get_state()
