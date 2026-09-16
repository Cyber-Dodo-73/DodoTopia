# -*- coding: utf-8 -*-
"""Plateforme Windows : SendInput (clavier, souris), lecture d'ecran Pillow, raccourcis via `keyboard`,
sortie MIDI winmm. Code deplace tel quel depuis core.py / draw.py / app.py."""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess

from platform_io import SCANCODES, VKCODES, InjectionError

try:
    from PIL import Image, ImageGrab
except ImportError:  # Pillow absent : pas de lecture d'ecran (palette par defaut, grille par defaut)
    Image = ImageGrab = None

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


_user32 = ctypes.WinDLL("user32", use_last_error=True)
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
    """Envoie l'appui (up=False) ou le relachement (up=True) de `keys` en un seul SendInput (accord simultane).
    Leve InjectionError si Windows refuse l'injection : c'est le cas quand le jeu tourne en administrateur et
    pas DodoTopia (UIPI) ; avant, l'echec etait silencieux et la musique « jouait » dans le vide."""
    if not keys:
        return
    arr = (INPUT * len(keys))(*[_make_input(k, up, mode) for k in keys])
    ctypes.set_last_error(0)
    sent = _user32.SendInput(len(keys), arr, ctypes.sizeof(INPUT))
    if sent != len(keys):
        code = ctypes.get_last_error()
        raise InjectionError(f"SendInput clavier refusé ({sent}/{len(keys)} touches, code Windows {code})", code)


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


def abs_coord(v, origin, size):
    """Coordonnee absolue SendInput (0..65535) qui atterrit exactement sur le pixel v : Windows convertit en
    pixel par troncature de dx * taille / 65536, on vise donc le milieu du pixel. (L'ancienne formule
    int((v - origine) * 65535 / (taille - 1)) tombait 1 a 2 px a cote sur deux tiers des positions, mesure sur
    un bureau de 3600 x 1191 : fatal pour des cases de dessin de 4 px.)"""
    return int((v - origin + 0.5) * 65536 / size)


def _mouse(flags, x=None, y=None):
    inp = MINPUT()
    inp.type = INPUT_MOUSE
    if x is not None:
        vx, vy, vw, vh = virtual_screen()
        inp.u.mi.dx = abs_coord(x, vx, vw)
        inp.u.mi.dy = abs_coord(y, vy, vh)
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
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi32.CreateCompatibleDC.argtypes = (wt.HDC,)
_gdi32.CreateCompatibleDC.restype = wt.HDC
_gdi32.CreateCompatibleBitmap.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int)
_gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
_gdi32.SelectObject.argtypes = (wt.HDC, wt.HGDIOBJ)
_gdi32.SelectObject.restype = wt.HGDIOBJ
_gdi32.BitBlt.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC,
                          ctypes.c_int, ctypes.c_int, wt.DWORD)
_gdi32.BitBlt.restype = wt.BOOL
_gdi32.GetDIBits.argtypes = (wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT)
_gdi32.DeleteObject.argtypes = (wt.HGDIOBJ,)
_gdi32.DeleteDC.argtypes = (wt.HDC,)
_user32.GetDC.argtypes = (wt.HWND,)
_user32.GetDC.restype = wt.HDC
_user32.ReleaseDC.argtypes = (wt.HWND, wt.HDC)
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def _grab_gdi(x1, y1, x2, y2):
    """Copie de la seule zone demandee (BitBlt), en coordonnees du bureau virtuel. Avant, chaque lecture de
    quelques pixels passait par ImageGrab qui capture TOUT le bureau (66 Mo sur deux ecrans 4K) puis rogne :
    la cuisine faisait cela plusieurs fois par tour de 100 ms."""
    w, h = int(x2 - x1), int(y2 - y1)
    if w <= 0 or h <= 0:
        return None
    screen = _user32.GetDC(None)
    if not screen:
        return None
    mem = bmp = None
    try:
        mem = _gdi32.CreateCompatibleDC(screen)
        bmp = _gdi32.CreateCompatibleBitmap(screen, w, h)
        if not mem or not bmp:
            return None
        old = _gdi32.SelectObject(mem, bmp)
        if not _gdi32.BitBlt(mem, 0, 0, w, h, screen, int(x1), int(y1), SRCCOPY | CAPTUREBLT):
            return None
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.biWidth, bi.biHeight = w, -h          # hauteur negative : lignes de haut en bas
        bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
        buf = ctypes.create_string_buffer(w * h * 4)
        _gdi32.SelectObject(mem, old)
        if _gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0) != h:
            return None
        return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        if bmp:
            _gdi32.DeleteObject(bmp)
        if mem:
            _gdi32.DeleteDC(mem)
        _user32.ReleaseDC(None, screen)


def grab(rect=None):
    if ImageGrab is None:
        return None
    try:
        if rect:
            x1, y1, x2, y2 = rect
            img = _grab_gdi(x1, y1, x2, y2)
            if img is not None:
                return img
            return ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True).convert("RGB")
        return ImageGrab.grab(all_screens=True).convert("RGB")
    except Exception:
        return None


# ---------------------------------------------------------------- fenetre du jeu
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_user32.GetForegroundWindow.restype = wt.HWND
_user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
_user32.GetWindowThreadProcessId.restype = wt.DWORD
_user32.GetKeyboardLayout.argtypes = (wt.DWORD,)
_user32.GetKeyboardLayout.restype = wt.HKL
_user32.IsWindowVisible.argtypes = (wt.HWND,)
_kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = (wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))
_kernel32.CloseHandle.argtypes = (wt.HANDLE,)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
_ENUM_PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _process_name(pid):
    if not pid:
        return None
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return None
    finally:
        _kernel32.CloseHandle(h)


def _process_elevated(pid):
    """Vrai si le processus tourne avec un jeton eleve (administrateur). None si indeterminable (souvent :
    processus eleve alors que nous ne le sommes pas, OpenProcess est alors refuse)."""
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    token = wt.HANDLE()
    try:
        if not _advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(token)):
            return None
        elevation = wt.DWORD(0)
        size = wt.DWORD(0)
        ok = _advapi32.GetTokenInformation(token, TokenElevation, ctypes.byref(elevation),
                                           ctypes.sizeof(elevation), ctypes.byref(size))
        return bool(elevation.value) if ok else None
    finally:
        if token:
            _kernel32.CloseHandle(token)
        _kernel32.CloseHandle(h)


def _foreground_pid():
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return 0, None
    pid = wt.DWORD(0)
    tid = _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value), int(tid)


def foreground_process_name():
    """Nom de l'executable de la fenetre active (« Heartopia.exe »), ou None si inconnu."""
    try:
        pid, _ = _foreground_pid()
        return _process_name(pid)
    except Exception:
        return None


def _find_process_windows(process_name):
    """PID du processus `process_name` qui possede une fenetre visible, ou 0."""
    wanted = process_name.lower()
    found = []
    seen = {}

    def cb(hwnd, _):
        if not _user32.IsWindowVisible(hwnd):
            return True
        pid = wt.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        p = int(pid.value)
        if p in seen:
            return True
        name = _process_name(p)
        seen[p] = name
        if name and name.lower() == wanted:
            found.append(p)
            return False
        return True

    _user32.EnumWindows(_ENUM_PROC(cb), 0)
    return found[0] if found else 0


def game_window_info(process_name):
    """Etat du jeu pour l'interface : {found, foreground, elevated}. Chaque valeur peut etre None (inconnu).
    `elevated` : le jeu tourne en administrateur (les touches seront refusees si DodoTopia ne l'est pas)."""
    info = {"found": None, "foreground": None, "elevated": None}
    if not process_name:
        return info
    try:
        fg_pid, _ = _foreground_pid()
        fg_name = _process_name(fg_pid)
        if fg_name and fg_name.lower() == process_name.lower():
            pid = fg_pid
            info["foreground"] = True
        else:
            pid = _find_process_windows(process_name)
            info["foreground"] = False
        info["found"] = bool(pid)
        if pid:
            elevated = _process_elevated(pid)
            # OpenProcess refuse depuis un processus non eleve = tres probablement eleve
            info["elevated"] = True if (elevated is None and not is_admin()) else bool(elevated)
    except Exception:
        pass
    return info


def foreground_keyboard_layout():
    """Disposition clavier ('azerty' | 'qwerty' | None) du fil de la fenetre active : celle que le jeu lit,
    pas celle de DodoTopia (les deux peuvent differer quand l'utilisateur a plusieurs claviers)."""
    try:
        _, tid = _foreground_pid()
        hkl = _user32.GetKeyboardLayout(tid or 0)
        lang = int(hkl) & 0xFFFF if hkl else 0
        primary = lang & 0x3FF
        if primary == 0x0C:       # francais (France, Belgique, Suisse…) : AZERTY, sauf le canadien (QWERTY)
            return "qwerty" if lang in (0x0C0C,) else "azerty"
        return "qwerty" if lang else None
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
        rc = _winmm.midiOutOpen(ctypes.byref(self.h), MIDI_MAPPER, 0, 0, 0)
        self.ok = rc == 0
        # code MMRESULT en cas d'echec (4 = MMSYSERR_ALLOCATED : peripherique deja pris, 2 = pas de peripherique)
        self.error = "" if self.ok else f"midiOutOpen a échoué (code {rc})"
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


APP_ID = "Dodo.DodoTopia"


def set_app_id(app_id=APP_ID):
    """Identite de l'application pour le shell Windows (AppUserModelID).

    Sans elle, Windows regroupe la fenetre sous l'identite du processus hote (python.exe ou l'exe PyInstaller
    tel qu'il etait la premiere fois) et reutilise l'icone qu'il a mise en cache pour cette identite : on voit
    alors l'ancien logo dans la barre des taches meme apres une mise a jour. A appeler avant la creation de
    la fenetre."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except Exception:
        return False


def set_window_icon(title, icon_path):
    """Icone de la fenetre (barre de titre + barre des taches) depuis assets/logo.ico."""
    if not os.path.exists(icon_path):
        return
    try:
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            return
        # tailles reellement attendues par le systeme (elles changent avec la mise a l'echelle de l'ecran)
        small = (u32.GetSystemMetrics(49) or 16, u32.GetSystemMetrics(50) or 16)     # SM_CXSMICON / SM_CYSMICON
        big = (u32.GetSystemMetrics(11) or 32, u32.GetSystemMetrics(12) or 32)       # SM_CXICON / SM_CYICON
        for (w, h), which in ((small, 0), (big, 1)):                                 # ICON_SMALL / ICON_BIG
            hicon = u32.LoadImageW(None, icon_path, 1, w, h, 0x00000010)             # LR_LOADFROMFILE
            if hicon:
                u32.SendMessageW(hwnd, 0x0080, which, hicon)                         # WM_SETICON
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
