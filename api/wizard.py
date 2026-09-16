# -*- coding: utf-8 -*-
"""Assistant de configuration des touches d'un instrument (5 etapes, test dans le jeu, enregistrement)."""
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


class WizardMixin:
    # ---------------------------------------------------------- assistant de configuration des touches
    def _wizard_busy(self):
        """Vrai pendant un test dans le jeu (la fenetre doit rester reduite)."""
        w = self._wizard
        t = (w or {}).get("test")
        return bool(t and t.get("state") in ("countdown", "playing"))

    def _wizard_test_abort(self, message=None):
        """Coupe un test de touches en cours. Appele par le raccourci d'arret, le bouton « Tout arrêter »
        et le bouton « Arrêter le test » de l'assistant : l'arret annonce doit exister pour de vrai."""
        t = (self._wizard or {}).get("test")
        if t and t.get("state") in ("countdown", "playing"):
            t["state"] = "cancelled"
            t["message"] = message or i18n.t("wizard.test.stopped")
            return True
        return False

    def _wizard_steps(self):
        """Libelles des etapes dans la langue courante."""
        return [i18n.t(k) for k in self.WIZARD_STEPS]

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
                "mode": w["mode"], "step": w["step"], "steps": self._wizard_steps(),
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
                "next_status_label": instruments.status_label(self._wizard_status(w))}

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
            self._notify(i18n.t("api.instrument.unknown"), "warn")
            return self.get_state()
        if self._player.state != "stopped":
            self._notify(i18n.t("wizard.stop_first"), "warn")
            return self.get_state()
        try:
            cat = self._catalogue()
        except instruments.InstrumentDataError as e:
            self._notify(str(e), "danger")
            return self.get_state()
        self._capture_end(force=True)
        candidates = [{"layoutId": lay.id, "labelFr": lay.label, "label": lay.name, "descriptionFr": lay.description,
                       "noteCount": lay.note_count, "rows": list(lay.rows), "documented": True}
                      for lay in cat.layouts_for(inst.id)]
        if not candidates:
            # aucun mapping documente pour ce type : les dispositions connues servent de grille de notes a
            # relever, JAMAIS de touches heritees (un instrument inconnu n'herite pas du profil piano).
            candidates = [{"layoutId": lay.id, "labelFr": lay.label, "label": lay.name, "descriptionFr": lay.description,
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
            "message": i18n.t("wizard.intro"),
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
            w["message"] = i18n.t("wizard.bind_first")
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
            w["message"] = i18n.t("wizard.layout.prefilled", layout=lay.name)
        else:
            w["bindings"] = {m: k for m, k in w["bindings"].items() if m in lay.bindings()}
            w["message"] = i18n.t("wizard.layout.to_capture", n=lay.note_count)
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
            w["message"] = i18n.t("wizard.key_not_injectable")
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
            self._notify(i18n.t("wizard.test.stop_first"), "warn")
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
                w["message"] = i18n.t("wizard.bind_first")
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
                "message": i18n.t("wizard.test.go")}
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
                    test["message"] = i18n.t("wizard.test.interrupted")
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
            test["message"] = i18n.t("wizard.test.heard_strike" if w["percussive"] else "wizard.test.heard_note")
        except Exception as e:  # noqa - un echec d'injection ne doit pas tuer le fil silencieusement
            test["state"] = "error"
            test["message"] = i18n.t("wizard.test.failed", error=e)
            self._log(f"test des touches : {e!r}")

    def instrument_wizard_test_stop(self):
        """Arret du test, accessible a tout moment."""
        self._wizard_test_abort(i18n.t("wizard.test.stopped_no_more"))
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
            w["message"] = test.get("message") or i18n.t("wizard.test.incomplete")
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
                w["message"] = i18n.t("wizard.answer.partial_full", n=len(midis), rest=rest)
                w["step"] = 4
            else:
                w["message"] = i18n.t("wizard.answer.quick")
                w["step"] = 5
        else:
            for m in midis:
                if m in w["verified"]:
                    w["verified"].remove(m)
            w["tested"] = False
            w["message"] = i18n.t("wizard.answer.wrong")
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
            return self._wizard_save_result(False, i18n.t("wizard.save.closed"))
        if w["id"] == self._player.instrument.id and self._player.state != "stopped":
            # meme garde-fou que set_instrument_layout et import_instrument_profile : on ne change pas le
            # profil de l'instrument qui joue sous les pieds de la lecture
            msg = i18n.t("wizard.save.stop_first")
            self._notify(msg, "warn")
            return self._wizard_save_result(False, msg)
        conflicts = instruments.conflicts(w["bindings"], self._cfg)
        if instruments.blocking(conflicts):
            msgs = [c["message"] for c in conflicts if c.get("severity") == "error"]
            msg = i18n.t("wizard.save.refused", reason=msgs[0] if msgs else i18n.t("api.profile.key_conflict"))
            self._notify(msg, "warn")
            w["step"] = 3
            return self._wizard_save_result(False, msg)
        if not w["bindings"]:
            msg = i18n.t("wizard.save.bind_first")
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
        self._notify(i18n.t("wizard.saved", name=name, status=instruments.status_label(status)), "ok")
        return self._wizard_save_result(True)

    def instrument_wizard_cancel(self):
        """Ferme l'assistant sans rien ecrire : un profil valide n'est jamais ecrase."""
        w = self._wizard
        if w and w.get("test"):
            w["test"]["state"] = "cancelled"
        self._capture_end(force=True)
        self._wizard = None
        return self.get_state()
