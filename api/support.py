"""Rapport de diagnostic (diagnostic.py) : aperçu, enregistrement local ou envoi au serveur (code à coller sur
Discord). Rien ne part sans que le joueur ait vu la liste des fichiers."""
import os
import platform
import sys
import time

import core
import diagnostic
import i18n
import online
import platform_io
from version import VERSION

REPORTS_DIR_NAME = "rapports"


class SupportMixin:
    def _diag_system(self):
        p = self._player
        inst = p.instrument
        info = {"version": VERSION, "lang": i18n.current_lang(), "frozen": bool(getattr(sys, "frozen", False)),
                "instrument": {"id": getattr(inst, "id", ""), "status": getattr(inst, "status", ""),
                               "layout": getattr(inst, "layout_id", None)},
                "play_mode": self._play_mode(), "player_state": p.state,
                "input_mode": self._cfg.get("input_mode"), "keyboard_layout": self._cfg.get("keyboard_layout")}
        try:
            info["game_window"] = self._game_window_state()
        except Exception:  # noqa
            pass
        try:
            info["admin"] = bool(platform_io.is_admin())
        except Exception:  # noqa
            pass
        return info

    def diag_preview(self):
        """{files: [{name, size, kind}], audio: bool} : ce que contiendrait le rapport."""
        try:
            return dict(diagnostic.preview(core.DATA_DIR), ok=True)
        except OSError as e:
            return {"ok": False, "files": [], "audio": False, "error": str(e)}

    def _diag_build(self, note, include_audio, include_images):
        return diagnostic.build(core.DATA_DIR, self._diag_system(), str(note or "")[:4000], bool(include_audio),
                                bool(include_images))

    def diag_save(self, note="", include_audio=False, include_images=False):
        """Enregistre le zip dans DATA_DIR/rapports/ et ouvre le dossier (marche hors ligne). {ok, path, name}."""
        try:
            data, _ = self._diag_build(note, include_audio, include_images)
            folder = os.path.join(core.DATA_DIR, REPORTS_DIR_NAME)
            os.makedirs(folder, exist_ok=True)
            name = time.strftime("rapport-dodotopia-%Y%m%d-%H%M%S.zip")
            path = os.path.join(folder, name)
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            self._notify(i18n.t("support.save_failed", error=str(e)), "warn")
            return {"ok": False, "error": str(e)}
        self._log(f"rapport de diagnostic enregistré : {path}")
        try:
            platform_io.open_folder(folder)
        except Exception:  # noqa
            pass
        return {"ok": True, "path": path, "name": name}

    def diag_send(self, note="", include_audio=False, include_images=False):
        """Envoie le rapport au serveur. {ok, code} ; le compte est rattaché si le joueur est connecté."""
        try:
            data, listing = self._diag_build(note, include_audio, include_images)
        except OSError as e:
            return {"ok": False, "error": str(e)}
        fields = {"note": str(note or "")[:2000], "version": VERSION,
                  "os": f"{platform.system()} {platform.release()}"}
        try:
            r = self._online.client.upload_bytes("/api/diag-reports", fields, "file", "rapport.zip", data,
                                                 content_type="application/zip")
        except online.OnlineError as e:
            self._log(f"rapport de diagnostic : envoi refusé ({e})")
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa - reseau coupe, serveur injoignable
            self._log(f"rapport de diagnostic : envoi impossible ({e})")
            return {"ok": False, "error": i18n.t("support.send_failed", error=str(e))}
        code = (r or {}).get("code") if isinstance(r, dict) else None
        if not code:
            return {"ok": False, "error": i18n.t("support.send_failed", error="?")}
        self._log(f"rapport de diagnostic envoyé : code {code} ({len(listing)} fichiers, {len(data)} octets)")
        return {"ok": True, "code": code, "files": len(listing)}
