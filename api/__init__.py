# -*- coding: utf-8 -*-
"""Api de DodoTopia exposee a l'interface (pywebview `js_api`) : une classe composee de mixins par domaine.
pywebview expose toutes les methodes publiques de l'objet ; le decoupage en modules ne change rien au
contrat avec le JavaScript (tests_client/test_api_contract.py fige la liste des methodes).

Les sous-modules ne portent pas le nom d'un module de la racine (cook, draw, online...) : un sous-module
homonyme deviendrait un attribut du paquet et masquerait le module importe ici."""
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
from ._base import BaseMixin
from .hotkeys import HotkeysMixin
from .state import StateMixin
from .cooking import CookMixin
from .drawing import DrawMixin
from .library_api import LibraryMixin
from .music import MusicMixin
from .instrument_api import InstrumentsMixin
from .wizard import WizardMixin
from .settings_api import SettingsMixin
from .online_api import OnlineMixin
from .integrations import IntegrationsMixin
from .support import SupportMixin
from .overlay import OverlayMixin


class Api(BaseMixin, HotkeysMixin, StateMixin, CookMixin, DrawMixin, LibraryMixin, MusicMixin, InstrumentsMixin, WizardMixin, SettingsMixin, OnlineMixin,
          IntegrationsMixin, SupportMixin, OverlayMixin):
    def __init__(self):
        # pywebview execute chaque appel JS dans un fil : tout ce que get_state() lit et que les autres
        # methodes ecrivent (toasts, erreur, diagnostic) passe par ce verrou reentrant
        self._ui_lock = threading.RLock()
        self._error = None                  # {msg, kind, since, target, reason} | None (voir get_state)
        self._last_sync_msg = ""
        self._songs_cache = None            # (signature, liste) : get_state ne relit pas le disque a chaque tick
        self._game_window = ({"found": None, "foreground": None, "elevated": None}, 0.0)
        self._cfg = core.load_config()
        i18n.set_lang((self._cfg.get("general") or {}).get("lang", "auto"))
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
            on_update_available=self._update_available,
            logfile=os.path.join(core.DATA_DIR, "online.log"),
            minimize=self._minimize_for_game, request_quit=self.quit, import_file=self._import_online_file,
            get_instrument_id=lambda: self._player.instrument.id, get_player_name=self._player_name,
            open_url=platform_io.open_url, open_folder=platform_io.open_folder)
        self._room = self._online.room          # room.RoomSession
        self._player.room = self._room          # Player.stop() / frappe clavier -> room.on_player_stop(reason)
        self._cfg["hotkeys"].setdefault("draw_point", "F3")
        self._drawer = draw.Drawer(self._cfg, log=self._log, on_change=self._on_module_change,
                                   save=lambda: core.save_config(self._cfg),
                                   logfile=os.path.join(core.DATA_DIR, "dessin.log"),
                                   resume_path=os.path.join(core.DATA_DIR, "dessin_reprise.json"))
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
        # instruments : catalogue charge a la demande, assistant de configuration, cache du diagnostic
        self._cat = None
        self._kb_layout = instruments.resolve_keyboard_layout(self._cfg.get("keyboard_layout", "auto"))
        self._wizard = None             # etat de l'assistant (aucun profil ecrit tant qu'on ne sauve pas)
        self._hotkeys_off = 0           # > 0 : raccourcis globaux debranches (saisie d'une touche)
        self._capture_since = 0.0
        self._compat = None             # dernier compat_report calcule
        self._compat_key = None         # (morceau, empreinte de l'instrument, transposition, options)
        self._compat_notes = None       # (cle, notes groupees) : evite de relire le .mid pour un apercu
        self._bind_hotkeys()
        try:
            self._is_admin = bool(platform_io.is_admin())
        except Exception:
            self._is_admin = False
        self._last_reason = ""
        # --debug (DodoTopia (debug).bat) : l'interface reserve le diagnostic technique a ce mode
        self._debug = "--debug" in sys.argv
        if self._cfg.get("_hotkeys_fixed"):
            core.save_config(self._cfg)
            self._notify(i18n.t("notify.hotkeys_fixed"), "warn", sticky=True)
        if self._cfg.get("_recovered"):
            self._notify(i18n.t("api.config_recovered"), "warn", sticky=True)
        logging_setup.on_crash(lambda msg: self._notify(i18n.t("api.internal_error", error=msg), "danger"))
        # liens dodotopia://, Discord Rich Presence, nowplaying.txt (api/integrations.py)
        self._init_integrations()


def _install_terms_gate(cls):
    """Enveloppe chaque methode de TERMS_GATED : tant que les CGU ne sont pas acceptees, l'appel ne fait rien
    et renvoie {ok: False, error: "terms.required", state}. L'ecran bloquant de l'interface empeche deja
    d'y arriver ; la garde protege aussi des appels par raccourci ou par lien externe."""
    import functools

    def gated(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kw):
            if self._terms_blocked():
                return {"ok": False, "error": "terms.required", "state": self.get_state()}
            return fn(self, *args, **kw)
        return wrapper

    for name in TERMS_GATED:
        fn = getattr(cls, name, None)
        if callable(fn) and not getattr(fn, "_terms_gated", False):
            w = gated(fn)
            w._terms_gated = True
            setattr(cls, name, w)
    return cls

_install_terms_gate(Api)
