# -*- coding: utf-8 -*-
"""Raccourcis globaux selon l'activite ouverte, crochets clavier, saisie d'une touche."""
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


class HotkeysMixin:
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
            self._wizard_test_abort(i18n.t("wizard.test.stopped"))
            if not self._room.stop_request("stop"):
                p.stop()
                self._sync.abort("stop")
            d.stop("stop")
            c.stop("stop")

        def next_instrument():
            # F12 : meme traitement que le selecteur (refus pendant une lecture, choix persiste)
            ok, msg = p.next_instrument()
            if not ok:
                self._notify(msg or i18n.t("api.instrument.change_failed"), "warn")
                return
            core.save_config(self._cfg)
            self._room.on_instrument_change(p.instrument)
            self._notify(i18n.t("api.instrument.current", name=p.instrument.name), "info")

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
