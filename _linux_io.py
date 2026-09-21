# -*- coding: utf-8 -*-
"""Plateforme Linux (X11, ou XWayland pour le jeu sous Proton), sans root :
- touches et souris injectees par l'extension XTEST (python-xlib) ;
- raccourcis globaux et hook clavier par l'extension XRECORD ;
- lecture d'ecran par mss ; sortie MIDI par python-rtmidi (optionnel, FluidSynth / TiMidity)."""
import os
import shutil
import subprocess
import sys
import threading
import time

# La fenetre de DodoTopia doit elle-meme etre un client X (sinon, sous Wayland, les raccourcis ne sont
# pas vus quand elle a le focus).
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ.setdefault("GDK_BACKEND", "x11")

from platform_io import SCANCODES  # noqa: E402

try:
    from Xlib import X, XK, display
    from Xlib.ext import record, xtest
    from Xlib.protocol import rq
except ImportError as e:  # pragma: no cover
    raise ImportError("python-xlib est requis sous Linux : pip install python-xlib") from e

try:
    import mss as _mss
except ImportError:
    _mss = None

FROZEN = getattr(sys, "frozen", False)
SCREEN_OK = _mss is not None and bool(os.environ.get("DISPLAY"))

_lock = threading.RLock()
_dpy = None


def _d():
    global _dpy
    if _dpy is None:
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("DISPLAY introuvable : DodoTopia a besoin d'une session X11 (ou XWayland)")
        _dpy = display.Display()
    return _dpy


# ---------------------------------------------------------------- dossiers
def user_data_dir(app_name):
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, app_name)


# ---------------------------------------------------------------- clavier (XTEST)
_kc_cache = {}


def scan_code_for(key, mode):
    """Keycode X envoye pour la touche : position physique (scancode + 8, regle evdev) ou lettre affichee."""
    if mode == "vk":
        kc = _kc_cache.get(key)
        if kc is None:
            with _lock:
                kc = _d().keysym_to_keycode(ord(key)) or (SCANCODES[key] + 8)
            _kc_cache[key] = kc
        return kc
    return SCANCODES[key] + 8


def send_keys(keys, up, mode):
    if not keys:
        return
    with _lock:
        d = _d()
        for k in keys:
            kc = scan_code_for(k, mode)
            if up:
                xtest.fake_input(d, X.KeyRelease, kc)
                d.change_keyboard_control(key=kc, auto_repeat_mode=X.AutoRepeatModeDefault)
            else:
                # sans cela le serveur X repete la touche tenue (appuis longs des notes tenues)
                d.change_keyboard_control(key=kc, auto_repeat_mode=X.AutoRepeatModeOff)
                xtest.fake_input(d, X.KeyPress, kc)
        d.sync()


def mouse_button_down():
    """Vrai si le bouton gauche de la souris est enfonce (le clic droit sert a tourner la camera du jeu)."""
    with _lock:
        mask = _d().screen().root.query_pointer().mask
    return bool(mask & X.Button1Mask)


# ---------------------------------------------------------------- souris (XTEST)
def cursor_pos():
    with _lock:
        p = _d().screen().root.query_pointer()
    return [int(p.root_x), int(p.root_y)]


def virtual_screen():
    with _lock:
        s = _d().screen()
    return 0, 0, max(1, int(s.width_in_pixels)), max(1, int(s.height_in_pixels))


def mouse_move(x, y):
    with _lock:
        d = _d()
        xtest.fake_input(d, X.MotionNotify, 0, x=int(x), y=int(y))
        d.sync()


def mouse_down():
    with _lock:
        d = _d()
        xtest.fake_input(d, X.ButtonPress, 1)
        d.sync()


def mouse_up():
    with _lock:
        d = _d()
        xtest.fake_input(d, X.ButtonRelease, 1)
        d.sync()


# ---------------------------------------------------------------- lecture d'ecran (mss)
def grab(rect=None):
    if _mss is None or not os.environ.get("DISPLAY"):
        return None
    try:
        from PIL import Image
        vx, vy, vw, vh = virtual_screen()
        if rect:
            x1, y1, x2, y2 = [int(v) for v in rect]
        else:
            x1, y1, x2, y2 = vx, vy, vx + vw, vy + vh
        x1, y1 = max(vx, x1), max(vy, y1)
        x2, y2 = min(vx + vw, x2), min(vy + vh, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        with _mss.mss() as sct:
            shot = sct.grab({"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception:
        return None


def is_admin():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def mouse_hint():
    return (" Sous Wayland, ouvre une session X11 (Xorg) : l'extension XTEST n'atteint que les fenêtres X"
            " (le jeu sous Proton en est une, mais la lecture d'écran peut échouer).")


# ---------------------------------------------------------------- Sortie MIDI (ecoute) : rtmidi, optionnel
_SOUNDFONTS = ("/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/sounds/sf2/default-GM.sf2",
               "/usr/share/soundfonts/default.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2")


class MidiOut:
    """Sortie MIDI vers un synthetiseur logiciel (FluidSynth, TiMidity). Sans synthe : silencieux (ok = False)."""

    def __init__(self):
        self.ok = False
        self.sounding = set()
        self._out = None
        self._synth = None
        try:
            import rtmidi
        except ImportError:
            return
        try:
            out = rtmidi.MidiOut()
            idx = self._pick(out.get_ports())
            if idx is None and shutil.which("fluidsynth"):
                sf2 = next((p for p in _SOUNDFONTS if os.path.isfile(p)), None)
                if sf2:
                    self._synth = subprocess.Popen(["fluidsynth", "-i", "-s", "-a", "pulseaudio", "-m", "alsa_seq", sf2],
                                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    for _ in range(20):
                        time.sleep(0.1)
                        idx = self._pick(out.get_ports())
                        if idx is not None:
                            break
            if idx is None:
                self._kill_synth()
                return
            out.open_port(idx)
            self._out = out
            self.ok = True
        except Exception:
            self._kill_synth()
            self.ok = False

    @staticmethod
    def _pick(ports):
        for i, name in enumerate(ports):
            if any(s in name for s in ("FLUID", "Fluid", "TiMidity", "Synth", "synth")):
                return i
        for i, name in enumerate(ports):
            if "Through" not in name:
                return i
        return None

    def _kill_synth(self):
        if self._synth is not None:
            try:
                self._synth.kill()
            except Exception:
                pass
            self._synth = None

    def _msg(self, status, d1, d2):
        if self.ok and self._out is not None:
            try:
                self._out.send_message([status & 0xFF, d1 & 0x7F, d2 & 0x7F])
            except Exception:
                pass

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
            try:
                self._out.close_port()
            except Exception:
                pass
            self._out = None
            self.ok = False
        self._kill_synth()


# ---------------------------------------------------------------- systeme
def _child_env():
    """Environnement pour un programme du systeme lance depuis le bundle PyInstaller : sans le LD_LIBRARY_PATH
    du bundle (ses bibliotheques casseraient xdg-open, le navigateur…), ou avec celui d'origine."""
    env = dict(os.environ)
    if FROZEN:
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def _xdg_open(path):
    try:
        subprocess.Popen(["xdg-open", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=_child_env(), start_new_session=True)
        return True
    except OSError:
        return False


def open_url(url):
    """Ouvre une adresse http(s) dans le navigateur par defaut (connexion Discord) ; repli webbrowser."""
    if _xdg_open(url):
        return True
    import webbrowser
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def open_text_file(path):
    _xdg_open(path)


def open_folder(path):
    _xdg_open(path)


def set_dpi_aware():
    pass  # X11 : coordonnees physiques, rien a faire


def set_app_id(app_id="Dodo.DodoTopia"):
    """Sans objet sous X11 (l'icone vient de WM_CLASS et du fichier .desktop)."""
    return False


def set_window_icon(title, icon_path):
    pass  # l'icone est donnee a webview.start(icon=...) (voir webview_start_kwargs)


def webview_start_kwargs(res_dir):
    kw = {}
    png = os.path.join(res_dir, "assets", "logo.png")
    if os.path.isfile(png):
        kw["icon"] = png
    if FROZEN:
        kw["gui"] = "qt"   # le bundle embarque PyQt6 + QtWebEngine (WebKit2GTK ne se gele pas)
    return kw


# ---------------------------------------------------------------- raccourcis globaux et hook clavier (XRECORD)
_MODS = {"ctrl": X.ControlMask, "control": X.ControlMask, "alt": X.Mod1Mask, "shift": X.ShiftMask,
         "meta": X.Mod4Mask, "super": X.Mod4Mask, "windows": X.Mod4Mask, "win": X.Mod4Mask}
_MOD_MASK = X.ControlMask | X.Mod1Mask | X.ShiftMask | X.Mod4Mask
# noms produits par l'interface (e.key du navigateur, en minuscules) -> keysym ; le premier alias est le nom rendu
_NAMES = [
    ("space", XK.XK_space), ("escape", XK.XK_Escape), ("esc", XK.XK_Escape), ("enter", XK.XK_Return),
    ("return", XK.XK_Return), ("tab", XK.XK_Tab), ("backspace", XK.XK_BackSpace), ("delete", XK.XK_Delete),
    ("del", XK.XK_Delete), ("insert", XK.XK_Insert), ("home", XK.XK_Home), ("end", XK.XK_End),
    ("pageup", XK.XK_Page_Up), ("page up", XK.XK_Page_Up), ("pagedown", XK.XK_Page_Down), ("page down", XK.XK_Page_Down),
    ("arrowup", XK.XK_Up), ("up", XK.XK_Up), ("arrowdown", XK.XK_Down), ("down", XK.XK_Down),
    ("arrowleft", XK.XK_Left), ("left", XK.XK_Left), ("arrowright", XK.XK_Right), ("right", XK.XK_Right),
    ("capslock", XK.XK_Caps_Lock), ("numlock", XK.XK_Num_Lock), ("scrolllock", XK.XK_Scroll_Lock),
    ("pause", XK.XK_Pause), ("printscreen", XK.XK_Print), ("contextmenu", XK.XK_Menu), ("menu", XK.XK_Menu),
    ("ctrl", XK.XK_Control_L), ("alt", XK.XK_Alt_L), ("shift", XK.XK_Shift_L), ("meta", XK.XK_Super_L),
]
for _i in range(1, 25):
    _NAMES.append((f"f{_i}", getattr(XK, f"XK_F{_i}")))
_NAME_TO_SYM = {n: s for n, s in _NAMES}
_SYM_TO_NAME = {}
for _n, _s in _NAMES:
    _SYM_TO_NAME.setdefault(_s, _n)
_SYM_TO_NAME.update({XK.XK_Control_R: "ctrl", XK.XK_Alt_R: "alt", XK.XK_Shift_R: "shift", XK.XK_Super_R: "meta",
                     XK.XK_KP_Enter: "enter"})


def parse_hotkey(combo):
    """"F6", "ctrl+f6", "space", "a" -> (masque de modificateurs, keysym). ValueError si inconnu."""
    parts = [p for p in str(combo).lower().replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError(f"raccourci vide : {combo!r}")
    mask, sym = 0, None
    for p in parts:
        if p in _MODS:
            mask |= _MODS[p]
        elif sym is not None:
            raise ValueError(f"raccourci invalide : {combo!r}")
        elif p in _NAME_TO_SYM:
            sym = _NAME_TO_SYM[p]
        elif len(p) == 1 and 0x20 <= ord(p) <= 0xFF:
            sym = ord(p)      # keysyms Latin-1 = points de code
        else:
            raise ValueError(f"touche inconnue : {p!r}")
    if sym is None:
        raise ValueError(f"raccourci sans touche : {combo!r}")
    return mask, sym


def _sym_name(sym):
    if sym in _SYM_TO_NAME:
        return _SYM_TO_NAME[sym]
    if 0x20 <= sym <= 0xFF:
        return chr(sym).lower()
    if 0xFFB0 <= sym <= 0xFFB9:          # pave numerique
        return str(sym - 0xFFB0)
    return (XK.keysym_to_string(sym) or "").lower()


class KeyEvent:
    """Meme forme que keyboard.KeyboardEvent : event_type "down"/"up", scan_code (keycode X), name."""
    __slots__ = ("event_type", "scan_code", "name", "time")

    def __init__(self, event_type, scan_code, name, t):
        self.event_type, self.scan_code, self.name, self.time = event_type, scan_code, name, t


class _Listener:
    def __init__(self):
        self.hooks = []          # [(id, callback)]
        self.hotkeys = []        # [(id, mask, keysym, fn)]
        self._next = 1
        self._thread = None
        self._ctl = None
        self._rec = None
        self._ctx = None
        self._lock = threading.Lock()
        self.error = None

    def _start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="xrecord", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self._rec = display.Display()
            self._ctl = display.Display()
            if not self._rec.has_extension("RECORD"):
                raise RuntimeError("extension RECORD absente du serveur X")
            self._ctx = self._rec.record_create_context(
                0, [record.AllClients],
                [{"core_requests": (0, 0), "core_replies": (0, 0), "ext_requests": (0, 0, 0, 0),
                  "ext_replies": (0, 0, 0, 0), "delivered_events": (0, 0),
                  "device_events": (X.KeyPress, X.KeyRelease), "errors": (0, 0),
                  "client_started": False, "client_died": False}])
            self._rec.record_enable_context(self._ctx, self._reply)
        except Exception as e:  # noqa
            self.error = e

    def _reply(self, reply):
        if reply.category != record.FromServer or reply.client_swapped:
            return
        data = reply.data
        if not data or data[0] < 2:
            return
        events = []
        while len(data):
            ev, data = rq.EventField(None).parse_binary_value(data, self._ctl.display, None, None)
            if ev.type in (X.KeyPress, X.KeyRelease):
                events.append(ev)
        # repetition automatique du serveur X : paire Release + Press de la meme touche au meme instant
        out = []
        i = 0
        while i < len(events):
            ev = events[i]
            if (ev.type == X.KeyRelease and i + 1 < len(events) and events[i + 1].type == X.KeyPress
                    and events[i + 1].detail == ev.detail and events[i + 1].time == ev.time):
                i += 2
                continue
            out.append(ev)
            i += 1
        for ev in out:
            self._dispatch(ev)

    def _dispatch(self, ev):
        sym = self._ctl.keycode_to_keysym(ev.detail, 0)
        name = _sym_name(sym)
        kind = "down" if ev.type == X.KeyPress else "up"
        event = KeyEvent(kind, int(ev.detail), name, int(ev.time))
        with self._lock:
            hooks = list(self.hooks)
            hotkeys = list(self.hotkeys)
        for _, cb in hooks:
            try:
                cb(event)
            except Exception:
                pass
        if kind == "down":
            state = ev.state & _MOD_MASK
            for _, mask, hsym, fn in hotkeys:
                if hsym == sym and state == mask:
                    try:
                        fn()
                    except Exception:
                        pass

    def add_hook(self, cb):
        with self._lock:
            hid = self._next
            self._next += 1
            self.hooks.append((hid, cb))
        self._start()
        return hid

    def remove_hook(self, hid):
        with self._lock:
            self.hooks = [h for h in self.hooks if h[0] != hid]

    def add_hotkey(self, combo, fn):
        mask, sym = parse_hotkey(combo)
        with self._lock:
            hid = self._next
            self._next += 1
            self.hotkeys.append((hid, mask, sym, fn))
        self._start()
        return hid

    def remove_hotkey(self, hid):
        with self._lock:
            self.hotkeys = [h for h in self.hotkeys if h[0] != hid]


_listener = _Listener()


def add_hotkey(combo, fn):
    return _listener.add_hotkey(combo, fn)


def remove_hotkey(handle):
    _listener.remove_hotkey(handle)


def hook(callback):
    return _listener.add_hook(callback)


def unhook(handle):
    _listener.remove_hook(handle)


# ---------------------------------------------------------------- fenetre du jeu (non disponible sous X11 generique)
def foreground_process_name():
    """Nom du processus de la fenetre active, ou None quand la plateforme ne sait pas le dire (aucune
    verification n'est alors faite par le lecteur)."""
    return None


def foreground_window():
    """(executable, titre) de la fenetre active ; non detecte sous Linux : (None, None)."""
    return None, None


def game_window_info(names, titles=()):
    """{found, foreground, elevated} pour l'interface ; sous Linux rien n'est detecte."""
    return {"found": None, "foreground": None, "elevated": None}


def foreground_keyboard_layout():
    """Disposition clavier de la fenetre active ('azerty' | 'qwerty' | None)."""
    return None
