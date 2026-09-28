# -*- coding: utf-8 -*-
"""Couche plateforme de DodoTopia : envoi des touches et de la souris, lecture d'ecran, raccourcis globaux,
sortie MIDI et petits services du systeme. Windows : _win_io.py (SendInput, keyboard, winmm, inchange).
Linux : _linux_io.py (X11 : extensions XTEST et XRECORD, mss, rtmidi)."""
import sys

IS_WINDOWS = sys.platform == "win32"

# Positions physiques des touches (scancodes set 1, disposition US). Sous X11 (evdev), keycode = scancode + 8.
SCANCODES = {
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07,
    "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B, "-": 0x0C, "=": 0x0D,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15,
    "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19, "[": 0x1A, "]": 0x1B,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23,
    "j": 0x24, "k": 0x25, "l": 0x26, ";": 0x27, "'": 0x28,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31,
    "m": 0x32, ",": 0x33, ".": 0x34, "/": 0x35,
}
VKCODES = {
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
for _c in "0123456789abcdefghijklmnopqrstuvwxyz":
    VKCODES[_c] = ord(_c.upper())


# Heartopia tourne sous « xdt.exe » (XD Games), pas « Heartopia.exe » : la 2.0.0 comparait au mauvais nom et
# refusait de jouer chez tout le monde. On reconnait donc le jeu par son executable OU par le titre exact de
# sa fenetre, et on ne bloque que si le jeu existe mais qu'une autre fenetre est devant. Jeu introuvable
# (executable renomme, autre plateforme) = aucune verification plutot qu'un blocage general.
DEFAULT_GAME_PROCESS = "xdt.exe, Heartopia.exe"
GAME_TITLES = ("heartopia", "\u5fc3\u52a8\u5c0f\u9547")


class InjectionError(RuntimeError):
    """L'envoi des touches a ete refuse par le systeme (jeu lance en administrateur alors que DodoTopia ne
    l'est pas : UIPI bloque SendInput). Le code Windows est dans `code`."""

    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code

# Les modules de plateforme importent SCANCODES / VKCODES depuis ce module : les tables doivent etre
# definies avant l'import ci-dessous (le module est alors partiellement initialise, c'est voulu).
if IS_WINDOWS:
    from _win_io import (  # noqa: E402,F401
        user_data_dir, scan_code_for, send_keys, mouse_button_down,
        cursor_pos, virtual_screen, mouse_move, mouse_down, mouse_up, grab, SCREEN_OK,
        is_admin, mouse_hint, MidiOut, open_text_file, open_folder, open_url,
        set_app_id, set_dpi_aware, set_window_icon, webview_start_kwargs,
        add_hotkey, remove_hotkey, hook, unhook, parse_hotkey,
        foreground_process_name, foreground_window, game_window_info, foreground_keyboard_layout,
        OVERLAY_OK, window_handle, overlay_prepare, overlay_show, overlay_hide, foreground_rect,
    )
else:
    from _linux_io import (  # noqa: E402,F401
        user_data_dir, scan_code_for, send_keys, mouse_button_down,
        cursor_pos, virtual_screen, mouse_move, mouse_down, mouse_up, grab, SCREEN_OK,
        is_admin, mouse_hint, MidiOut, open_text_file, open_folder, open_url,
        set_app_id, set_dpi_aware, set_window_icon, webview_start_kwargs,
        add_hotkey, remove_hotkey, hook, unhook, parse_hotkey,
        foreground_process_name, foreground_window, game_window_info, foreground_keyboard_layout,
        OVERLAY_OK, window_handle, overlay_prepare, overlay_show, overlay_hide, foreground_rect,
    )


# ---------------------------------------------------------------- le jeu est-il devant ?
_found_cache = {"at": 0.0, "key": None, "found": None}


def _basename(path):
    return str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()


def game_names(value):
    """Reglage `game_process` (liste separee par des virgules) -> ensemble d'executables en minuscules."""
    out = set()
    for part in str(value or "").replace(";", ",").split(","):
        name = _basename(part.strip().strip('"'))
        if name:
            out.add(name)
    return out


def is_game_window(proc, title, names):
    return _basename(proc) in names or str(title or "").strip().lower() in GAME_TITLES


def game_in_front(game_process):
    """True : le jeu est au premier plan ; False : le jeu existe mais une autre fenetre est devant (les
    touches et les clics partiraient ailleurs) ; None : pas de verification possible ou voulue (reglage vide,
    plateforme muette, jeu introuvable)."""
    import time as _time
    names = game_names(game_process)
    if not names:
        return None
    try:
        proc, title = foreground_window()
    except Exception:  # noqa
        return None
    if proc is None and not title:
        return None
    if is_game_window(proc, title, names):
        return True
    now = _time.monotonic()
    key = tuple(sorted(names))
    if _found_cache["key"] != key or now - _found_cache["at"] > 2.0:
        try:
            found = game_window_info(names, GAME_TITLES).get("found")
        except Exception:  # noqa
            found = None
        _found_cache.update(at=now, key=key, found=found)
    return False if _found_cache["found"] else None
