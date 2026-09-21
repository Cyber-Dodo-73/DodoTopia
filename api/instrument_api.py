# -*- coding: utf-8 -*-
"""Instruments : catalogue, fiche, choix, disposition du clavier, export / import de profils."""
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


class InstrumentsMixin:
    # ---------------------------------------------------------- instruments : catalogue, profils, assistant
    # Choisir un instrument ici n'equipe rien dans Heartopia : on choisit le TYPE joue, donc ses touches.
    # cles i18n des cinq etapes (traduites par _wizard_steps())
    WIZARD_STEPS = ("wizard.step.open", "wizard.step.layout", "wizard.step.bind", "wizard.step.test",
                    "wizard.step.save")
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
            self._notify(i18n.t("api.instrument.catalogue_error", error=e), "danger")
            return {"error": str(e), "categories": [], "layouts": [], "statuses": {}}
        kb = self._keyboard_layout()
        layouts = []
        for lay in cat.layouts.values():
            d = lay.to_dict(with_notes=False)
            d["notes"] = [self._note_line(n["midi"], n["key"], kb) for n in lay.notes]
            layouts.append(d)
        return {"categories": cat.category_labels(),
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
                "statuses": instruments.status_labels()}

    def get_instrument_detail(self, instrument_id):
        """Fiche complete d'un type : notes, rangees, dispositions candidates, profil, provenance."""
        inst = self._instrument(instrument_id)
        if inst is None:
            return {"error": i18n.t("api.instrument.unknown")}
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
            self._notify(msg or i18n.t("api.instrument.unknown"), "warn")
            return self.get_state()
        inst = self._player.instrument
        core.save_config(self._cfg)
        self._room.on_instrument_change(inst)
        if not inst.ready:
            self._notify(i18n.t("api.instrument.blocked", name=inst.name, reason=inst.blocked_reason), "warn")
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
            self._notify(r.get("error") or i18n.t("api.layout.refused"), "warn")
        return self.get_state()

    def set_instrument_layout(self, instrument_id, layout_id, force=False):
        """Choisit une disposition candidate pour un type.

        Des touches personnalisees ne sont effacees que sur confirmation explicite (force=True) : on ne
        remplace jamais un mapping deja adapte a l'installation par une table externe sans le dire."""
        inst = self._instrument(instrument_id)
        if inst is None:
            self._notify(i18n.t("api.instrument.unknown"), "warn")
            return self.get_state()
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(str(e), "danger")
            return self.get_state()
        lay = cat.layouts.get(str(layout_id or ""))
        if lay is None:
            self._notify(i18n.t("api.layout.unknown"), "warn")
            return self.get_state()
        if inst.id == self._player.instrument.id and self._player.state != "stopped":
            self._notify(i18n.t("api.layout.stop_first"), "warn")
            return self.get_state()
        if inst.custom and not force:
            self._notify(i18n.t("api.layout.confirm_custom", name=inst.name, layout=lay.name), "warn")
            return self.get_state()
        status = instruments.STATUS_DOCUMENTED if lay.id in inst.type.supported_layout_ids \
            else instruments.STATUS_CUSTOM
        instruments.set_profile(self._cfg, inst.id, layout_id=lay.id, bindings=None, status=status,
                                verified_at=None, catalogue=cat)
        core.save_config(self._cfg)
        self._rebuild_instruments()
        self._notify(i18n.t("api.layout.applied", name=inst.name, layout=lay.name, n=lay.note_count), "ok")
        return self.get_state()

    # ---------------------------------------------------------- profils : export / import
    def export_instrument_profile(self, instrument_id, path=None):
        """Profil d'un type au format JSON (donnees seulement). Propose un enregistrement de fichier."""
        inst = self._instrument(instrument_id)
        if inst is None:
            return {"ok": False, "error": i18n.t("api.instrument.unknown")}
        prof = instruments.profile_of(self._cfg, inst.id)
        payload = {"format": "dodotopia-instrument-profile",
                   "schemaVersion": instruments.SCHEMA_VERSION, "app": VERSION,
                   "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "instrumentId": inst.id, "labelFr": inst.label_fr, "labelEn": inst.label_en,
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
                    file_types=(i18n.t("api.dialog.profile"), i18n.t("api.dialog.all_files")))
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
                self._notify(i18n.t("api.profile.exported", name=os.path.basename(saved)), "ok")
            except OSError as e:
                self._notify(i18n.t("api.profile.export_failed", error=e), "warn")
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
                    file_types=(i18n.t("api.dialog.profile"), i18n.t("api.dialog.all_files")))
            except Exception as e:  # noqa
                self._notify(i18n.t("api.profile.import_failed", error=e), "warn")
                return self.get_state()
            if not files:
                return self.get_state()
            try:
                with open(files[0], "r", encoding="utf-8") as f:
                    data = f.read(self.MAX_PROFILE_BYTES + 1)
            except OSError as e:
                self._notify(i18n.t("api.profile.unreadable", error=e), "warn")
                return self.get_state()
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", "replace")
        if isinstance(data, str):
            if len(data) > self.MAX_PROFILE_BYTES:
                self._notify(i18n.t("api.profile.too_big"), "warn")
                return self.get_state()
            try:
                data = json.loads(data)
            except ValueError:
                self._notify(i18n.t("api.profile.not_json"), "warn")
                return self.get_state()
        if not isinstance(data, dict):
            self._notify(i18n.t("api.profile.bad_format"), "warn")
            return self.get_state()
        wanted = str(instrument_id or data.get("instrumentId") or "")
        wanted = instruments.LEGACY_IDS.get(wanted, wanted)
        inst = self._instrument(wanted)
        if inst is None:
            self._notify(i18n.t("api.profile.unknown_instrument", id=wanted or "?"), "warn")
            return self.get_state()
        if inst.id == self._player.instrument.id and self._player.state != "stopped":
            self._notify(i18n.t("api.profile.stop_first"), "warn")
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
            self._notify(i18n.t("api.profile.nothing_usable"), "warn")
            return self.get_state()
        conflicts = instruments.conflicts(bindings, self._cfg)
        if instruments.blocking(conflicts):
            msgs = [c["message"] for c in conflicts if c.get("severity") == "error"]
            self._notify(i18n.t("api.profile.conflict", reason=msgs[0] if msgs else i18n.t("api.profile.key_conflict")), "warn")
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
        self._notify(i18n.t("api.profile.imported", name=inst.name, rejected=rejected), "ok")
        return self.get_state()
