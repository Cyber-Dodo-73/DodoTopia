# -*- coding: utf-8 -*-
"""Reglages : lecture / ecriture par chemin (settings_schema), effets de bord, reinitialisation."""
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


class SettingsMixin:
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

    def _on_lang(self):
        """Langue de l'interface : Python bascule ses propres messages, l'interface recharge son catalogue."""
        pref = (self._cfg.get("general") or {}).get("lang", "auto")
        lang = i18n.set_lang(pref)
        self._log(f"langue : {pref} -> {lang}")
        if self._window:
            try:
                self._window.evaluate_js("typeof applyLanguage === 'function' && applyLanguage()")
            except Exception as e:  # noqa
                self._log(f"rechargement de la langue impossible : {e}")

    def get_i18n(self):
        """Catalogue de la langue courante (+ repli francais) pour l'interface, appele au demarrage et a chaque
        changement de langue : {lang, available, catalogue, fallback, meta}."""
        lang = i18n.current_lang()
        cats = i18n.catalogues()
        cur = cats.get(lang) or cats.get(i18n.FALLBACK_LANG)
        fb = cats.get(i18n.FALLBACK_LANG)
        return {"lang": cur.tag if cur else i18n.FALLBACK_LANG,
                "available": i18n.available(),
                "catalogue": dict(cur.messages) if cur else {},
                "fallback": dict(fb.messages) if fb and fb is not cur else {},
                "meta": cur.meta() if cur else {}}

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
            names = ", ".join(touched[:3]) + (" " + i18n.t("api.and_others", n=len(touched) - 3) if len(touched) > 3 else "")
            self._notify(i18n.t("api.keyboard.reverted", layout=kb.upper(), names=names, n=len(touched)), "warn")

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
        if mode == "audio" and self._room.active():
            self._log("salon : synchro par le son activee, on quitte le salon")
            self._room.leave()

    def _on_cookers(self):
        """Nombre de cuisinieres servies par la boucle de cuisine : applique au module Cuisine. Une boucle en
        cours est arretee proprement (les machines a etats sont refaites au prochain demarrage)."""
        n, stopped = self._cook.apply_cookers()
        if stopped:
            self._notify(i18n.t("api.cook.restart", n=n), "warn")

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
                "hotkey_labels": settings_schema.hotkey_labels(), "multi_devices": devices,
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
