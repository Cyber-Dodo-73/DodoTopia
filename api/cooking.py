# -*- coding: utf-8 -*-
"""Cuisine dans le jeu : lancer / arreter, assistant de calibrage, test de detection, journal."""
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


class CookMixin:
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
            self._notify(i18n.t("api.log.none_cook"), "warn")
        return True
