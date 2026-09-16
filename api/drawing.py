# -*- coding: utf-8 -*-
"""Dessin dans le jeu : travail, lancement, calibrage, mesure automatique, import d'image."""
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


class DrawMixin:
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
            self._notify(i18n.t("api.draw.grid_set", fmt=fmt, cols=cols, rows=rows), "ok")
        return self.get_state()

    # ---------------------------------------------------------- image
    def import_image_dialog(self):
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=(i18n.t("api.dialog.images"), i18n.t("api.dialog.all_files")))
        if not files:
            return None
        return self.load_image(files[0])

    def load_image(self, path):
        """Lit une image et la renvoie a l'interface en data URL (l'onglet Image fait le rendu)."""
        if not path or not os.path.isfile(path):
            return None
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_MIME:
            self._notify(i18n.t("api.image.not_image", name=os.path.basename(path)), "warn")
            return None
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        self._notify(i18n.t("api.image.imported", name=os.path.basename(path)), "ok")
        return {"name": os.path.splitext(os.path.basename(path))[0],
                "data": f"data:{IMAGE_MIME[ext]};base64,{data}"}

    LOGO_PX = 96        # affiche vers 40 px : 96 couvre les ecrans a forte densite

    def get_logo(self):
        """Logo en data URL : la page est servie depuis ui/, assets/ n'est pas accessible en relatif.
        Reduit et mis en cache : le fichier source fait plus d'un Mo, inutile de le passer en entier
        a chaque demarrage a travers le pont JS."""
        if getattr(self, "_logo_url", None) is not None:
            return self._logo_url
        # logo-256.png (genere par make_icon.py, livre dans l'exe) ; logo.png source en mode developpement
        path = os.path.join(core.RES_DIR, "assets", "logo-256.png")
        if not os.path.isfile(path):
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
