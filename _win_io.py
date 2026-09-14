# -*- coding: utf-8 -*-
"""Plateforme Windows : SendInput (clavier, souris), lecture d'ecran Pillow, raccourcis via `keyboard`,
sortie MIDI winmm. Code deplace tel quel depuis core.py / draw.py / app.py."""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess

from platform_io import SCANCODES, VKCODES

try:
    from PIL import ImageGrab
except ImportError:  # Pillow absent : pas de lecture d'ecran (palette par defaut, grille par defaut)
    ImageGrab = None

SCREEN_OK = ImageGrab is not None


# ---------------------------------------------------------------- dossiers
def user_data_dir(app_name):
    """Donnees modifiables (config.json, songs/) de la version installee : %APPDATA%\\DodoTopia."""
    data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), app_name)
    _old = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Heartopia Player")
    if not os.path.exists(data_dir) and os.path.isdir(_old):
        try:
            os.rename(_old, data_dir)  # ancien nom de l'application
        except OSError:
            pass
    return data_dir


# ---------------------------------------------------------------- SendInput clavier
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


_user32 = ctypes.windll.user32
_user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.MapVirtualKeyW.argtypes = (wt.UINT, wt.UINT)
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = ctypes.c_short


def scan_code_for(key, mode):
    if mode == "vk":
        return _user32.MapVirtualKeyW(VKCODES[key], 0)
    return SCANCODES[key]


def _make_input(key, up, mode):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    flags = KEYEVENTF_KEYUP if up else 0
    if mode == "vk":
        vk = VKCODES[key]
        inp.u.ki.wVk = vk
        inp.u.ki.wScan = _user32.MapVirtualKeyW(vk, 0)
        inp.u.ki.dwFlags = flags
    else:
        inp.u.ki.wVk = 0
        inp.u.ki.wScan = SCANCODES[key]
        inp.u.ki.dwFlags = flags | KEYEVENTF_SCANCODE
    return inp


def send_keys(keys, up, mode):
    if not keys:
        return
    arr = (INPUT * len(keys))(*[_make_input(k, up, mode) for k in keys])
    _user32.SendInput(len(keys), arr, ctypes.sizeof(INPUT))


def mouse_button_down():
    """Vrai si le bouton gauche de la souris est enfonce (le clic droit sert a tourner la camera du jeu :
    il n'arrete pas la musique)."""
    return bool(_user32.GetAsyncKeyState(0x01) & 0x8000)


# ---------------------------------------------------------------- SendInput souris
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _MUNION(ctypes.Union):
    # 32 octets : taille de la plus grande variante (MOUSEINPUT) pour que sizeof(INPUT) == 40 (x64)
    _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]


class MINPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _MUNION)]


_muser32 = ctypes.WinDLL("user32", use_last_error=True)
_muser32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(MINPUT), ctypes.c_int)
_muser32.GetCursorPos.argtypes = (ctypes.POINTER(wt.POINT),)


def cursor_pos():
    p = wt.POINT()
    _muser32.GetCursorPos(ctypes.byref(p))
    return [int(p.x), int(p.y)]


def virtual_screen():
    x = _muser32.GetSystemMetrics(76)
    y = _muser32.GetSystemMetrics(77)
    w = _muser32.GetSystemMetrics(78)
    h = _muser32.GetSystemMetrics(79)
    return x, y, max(1, w), max(1, h)


def _mouse(flags, x=None, y=None):
    inp = MINPUT()
    inp.type = INPUT_MOUSE
    if x is not None:
        vx, vy, vw, vh = virtual_screen()
        inp.u.mi.dx = int((x - vx) * 65535 / (vw - 1))
        inp.u.mi.dy = int((y - vy) * 65535 / (vh - 1))
        flags |= MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MOVE
    inp.u.mi.dwFlags = flags
    ctypes.set_last_error(0)
    if _muser32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(MINPUT)) != 1:
        raise RuntimeError(f"SendInput souris refusé (code Windows {ctypes.get_last_error()})")


def mouse_move(x, y):
    _mouse(0, x, y)


def mouse_down():
    _mouse(MOUSEEVENTF_LEFTDOWN)


def mouse_up():
    _mouse(MOUSEEVENTF_LEFTUP)


# ---------------------------------------------------------------- lecture d'ecran
def grab(rect=None):
    if ImageGrab is None:
        return None
    try:
        if rect:
            x1, y1, x2, y2 = rect
            return ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True).convert("RGB")
        return ImageGrab.grab(all_screens=True).convert("RGB")
    except Exception:
        return None


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def mouse_hint():
    """Conseil ajoute au message « la souris ne se deplace pas dans le jeu »."""
    return "" if is_admin() else " Lance DodoTopia en administrateur (clic droit, Exécuter en tant qu'administrateur)."


# ---------------------------------------------------------------- Sortie MIDI (ecoute)
_winmm = ctypes.windll.winmm
MIDI_MAPPER = 0xFFFFFFFF


class MidiOut:
    """Synthetiseur Windows (Microsoft GS Wavetable) pour ecouter dans le logiciel."""

    def __init__(self):
        self.h = wt.HANDLE()
        self.ok = _winmm.midiOutOpen(ctypes.byref(self.h), MIDI_MAPPER, 0, 0, 0) == 0
        self.sounding = set()

    def _msg(self, status, d1, d2):
        if self.ok:
            _winmm.midiOutShortMsg(self.h, status | (d1 << 8) | (d2 << 16))

    def program(self, prog, channel=0):
        self._msg(0xC0 | channel, int(prog) & 0x7F, 0)

    def volume(self, value, channel=0):
        self._msg(0xB0 | channel, 7, max(0, min(127, int(value))))

    def note_on(self, note, vel=100, channel=0):
        self._msg(0x90 | channel, note & 0x7F, max(1, min(127, vel)))
        self.sounding.add(note)

    def note_off(self, note, channel=0):
        self._msg(0x80 | channel, note & 0x7F, 0)
        self.sounding.discard(note)

    def all_off(self, channel=0):
        for n in list(self.sounding):
            self.note_off(n, channel)
        self._msg(0xB0 | channel, 123, 0)

    def close(self):
        if self.ok:
            self.all_off()
            _winmm.midiOutReset(self.h)
            _winmm.midiOutClose(self.h)
            self.ok = False


# ---------------------------------------------------------------- systeme
def open_text_file(path):
    subprocess.Popen(["notepad", path])


def open_folder(path):
    subprocess.Popen(["explorer", path])


def open_url(url):
    """Ouvre une adresse http(s) dans le navigateur par defaut (connexion Discord)."""
    import webbrowser
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def set_dpi_aware():
    """Coordonnees physiques de l'ecran (souris, captures) meme avec une mise a l'echelle Windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def set_window_icon(title, icon_path):
    """Icone de la fenetre (barre de titre + barre des taches) depuis assets/logo.ico."""
    if not os.path.exists(icon_path):
        return
    try:
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            return
        for size, which in ((16, 0), (32, 1)):
            hicon = u32.LoadImageW(None, icon_path, 1, size, size, 0x00000010)
            if hicon:
                u32.SendMessageW(hwnd, 0x0080, which, hicon)
    except Exception:
        pass


def webview_start_kwargs(res_dir):
    return {}


# ---------------------------------------------------------------- raccourcis globaux (`keyboard`)
def add_hotkey(combo, fn):
    import keyboard
    return keyboard.add_hotkey(combo, fn, suppress=False)


def remove_hotkey(handle):
    import keyboard
    keyboard.remove_hotkey(handle)


def hook(callback):
    """Le callback recoit un evenement avec .event_type ("down"/"up"), .scan_code et .name."""
    import keyboard
    return keyboard.hook(callback)


def unhook(handle):
    import keyboard
    keyboard.unhook(handle)


def parse_hotkey(combo):
    import keyboard
    return keyboard.parse_hotkey(combo)
