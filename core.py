# -*- coding: utf-8 -*-
"""Moteur de DodoTopia : instruments, lecture MIDI, envoi des touches, ecoute integree."""
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time

import mido

import instruments
import platform_io
from instruments import Instrument  # noqa: F401 (alias historique : core.Instrument)
from platform_io import SCANCODES, scan_code_for, send_keys, mouse_button_down, MidiOut  # noqa: F401

APP_NAME = "DodoTopia"
FROZEN = getattr(sys, "frozen", False)
# Ressources (ui/, assets/, config par defaut) : dans l'exe ou a cote du script
RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
# Donnees modifiables (config.json, songs/) : AppData quand installe, sinon le dossier du script
if FROZEN:
    DATA_DIR = platform_io.user_data_dir(APP_NAME)
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
# Config livree avec l'app : config.default.json (sans calibrage personnel). L'ancien nom reste accepte
# pour les installations faites avant la separation.
DEFAULT_CONFIG_PATH = os.path.join(RES_DIR, "config.default.json")
if not os.path.exists(DEFAULT_CONFIG_PATH):
    DEFAULT_CONFIG_PATH = os.path.join(RES_DIR, "config.json")


# ---------------------------------------------------------------- Config
DEFAULT_CONFIG = {
    "instrument": "piano",
    "songs_folder": "songs",
    "hotkeys": {"play_pause": "F6", "stop": "F7", "next_song": "F8", "prev_song": "F9",
                "speed_down": "F10", "speed_up": "F11", "next_instrument": "F12"},
    "start_delay": 1.0, "speed": 1.0, "hold_time": 0.04, "chord_window": 0.02,
    "transpose_semitones": 0, "fold_out_of_range": True, "ignore_drums": True,
    "input_mode": "scancode", "stop_on_input": True, "preview_volume": 100,
    "hold_mode": "note", "max_hold": 4.0,
    "keyboard_layout": "auto", "instrument_favorites": [],
}


def _log_migration(lines):
    """Journalise les lignes de migration des instruments (sans console : on ignore silencieusement)."""
    for line in lines:
        try:
            print(f"instruments : {line}")
        except Exception:  # noqa : pas de sortie standard en mode fenetre
            return


def load_config():
    if not os.path.exists(CONFIG_PATH) and os.path.exists(DEFAULT_CONFIG_PATH):
        shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    # Les instruments ne viennent plus de config.default.json : le catalogue (assets/instruments) fait foi.
    # La migration convertit l'ancien format, conserve les personnalisations et complete les types manquants.
    changes = instruments.migrate_config(cfg)
    cfg["_migration_log"] = changes
    _log_migration(changes)
    cfg["_instruments"] = instruments.build_instruments(cfg)
    if not cfg["_instruments"]:
        raise ValueError("aucun instrument dans le catalogue")
    return cfg


def save_config(cfg):
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- MIDI
# Garde-fous sur les fichiers ouverts : un .mid vient parfois d'internet (bibliotheque en ligne, salon).
# Un fichier hostile de quelques Mo en running status contient des centaines de milliers d'evenements et
# figerait l'application dans parse_midi. Plafonds volontairement plus larges que ceux du serveur
# (server/app/config.py) : les fichiers locaux de l'utilisateur ne doivent pas etre refuses a tort.
MAX_MIDI_BYTES = 16 * 1024 * 1024
MAX_MIDI_EVENTS = 200_000
MAX_MIDI_NOTES = 100_000


class MidiRefused(ValueError):
    """Fichier MIDI illisible ou hors des plafonds : message pret a afficher."""


def _open_midi(path):
    """mido.MidiFile avec verification prealable de la taille et de l'entete magique."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise MidiRefused(f"fichier illisible ({e.strerror or e})") from None
    if size > MAX_MIDI_BYTES:
        raise MidiRefused(f"fichier trop gros ({size // (1024 * 1024)} Mo, maximum {MAX_MIDI_BYTES // (1024 * 1024)} Mo)")
    with open(path, "rb") as f:
        if f.read(4) != b"MThd":
            raise MidiRefused("ce n'est pas un fichier MIDI (en-tete « MThd » absent)")
    try:
        mid = mido.MidiFile(path)
    except Exception as e:  # noqa : mido leve un peu de tout
        raise MidiRefused(f"fichier MIDI illisible ({type(e).__name__})") from None
    if mid.type not in (0, 1):
        raise MidiRefused(f"fichier MIDI de type {mid.type} non pris en charge (type 0 ou 1 attendu)")
    return mid


def parse_midi(path, cfg, stats=None):
    """Liste triee [(t, [(note, duree, velocite), ...])], accords regroupes.

    `stats` : dict facultatif rempli au passage avec "drums" (notes de percussion ignorees) et "channels"
    (canaux MIDI rencontres). La signature reste retro-compatible.

    Leve MidiRefused (ValueError) si le fichier n'est pas un MIDI exploitable ou depasse les plafonds."""
    mid = _open_midi(path)
    notes = []          # (t_on, note, dur, vel)
    pending = {}        # (channel, note) -> (t_on, vel)
    t = 0.0
    events = 0
    drums = 0
    channels = set()
    for msg in mid:
        events += 1
        if events > MAX_MIDI_EVENTS:
            raise MidiRefused(f"fichier MIDI trop charge (plus de {MAX_MIDI_EVENTS} evenements)")
        if len(notes) > MAX_MIDI_NOTES:
            raise MidiRefused(f"fichier MIDI trop charge (plus de {MAX_MIDI_NOTES} notes)")
        t += msg.time
        if msg.type in ("note_on", "note_off"):
            channels.add(msg.channel)
        if msg.type == "note_on" and msg.velocity > 0:
            if cfg.get("ignore_drums", True) and msg.channel == 9:
                drums += 1
                continue
            key = (msg.channel, msg.note)
            if key in pending:  # re-declenchee sans note_off
                t0, v0 = pending.pop(key)
                notes.append((t0, msg.note, max(0.05, t - t0), v0))
            pending[key] = (t, msg.velocity)
        elif msg.type in ("note_off", "note_on"):
            key = (msg.channel, msg.note)
            if key in pending:
                t0, v0 = pending.pop(key)
                notes.append((t0, msg.note, max(0.05, t - t0), v0))
    for (ch, note), (t0, v0) in pending.items():
        notes.append((t0, note, 0.5, v0))
    notes.sort()
    window = cfg.get("chord_window", 0.02)
    grouped = []
    for t0, note, dur, vel in notes:
        if grouped and t0 - grouped[-1][0] <= window:
            if all(n != note for n, _, _ in grouped[-1][1]):
                grouped[-1][1].append((note, dur, vel))
        else:
            grouped.append((t0, [(note, dur, vel)]))
    if isinstance(stats, dict):
        stats["drums"] = drums
        stats["channels"] = sorted(channels)
    return grouped


def midi_duration(path):
    try:
        return _open_midi(path).length
    except Exception:
        return 0.0


def choose_shift(all_notes, inst, cfg, extra_fixed=None):
    """Transposition (demi-tons). extra_fixed : decalage de tonalite impose (mode Multi : le meme pour tous les
    joueurs, seule l'octave est choisie par instrument ; la transposition manuelle est ignoree)."""
    semi = int(cfg.get("transpose_semitones", 0)) if extra_fixed is None else 0
    if (inst.auto == "off" and extra_fixed is None) or not all_notes:
        return semi + (extra_fixed or 0)
    lo, hi = inst.lowest, inst.lowest + inst.span
    in_scale = set(inst.scale)
    classes = {o % 12 for o in in_scale}
    candidates = []
    for oct_shift in range(-4, 5):
        if extra_fixed is not None:
            semis = [int(extra_fixed)]
        else:
            semis = range(-6, 6) if inst.auto == "key" else [0]
        for extra in semis:
            s = semi + 12 * oct_shift + extra
            score = 0
            for n in all_notes:
                m = n + s
                if lo <= m <= hi:
                    score += 2 if (m - lo) in in_scale else 1
                elif (m - lo) % 12 in classes:
                    score += 1
            candidates.append((score, -abs(extra), -abs(oct_shift), s))
    return max(candidates)[3]


def fit_notes(grouped, inst, cfg, extra_fixed=None, shift=None):
    """Retourne ([(t, [touches], [(note_jouee, duree, vel)])], info).

    info : shift, folded, snapped, dropped, hits, notes (cles historiques lues par sync.py, room.py et
    l'interface) + out_of_range (notes hors registre avant repli), missing_accidental (notes tombees sur
    une alteration absente), exact (notes jouees a la hauteur exacte) et coverage (0-100).
    `shift` force la transposition au lieu de la choisir (apercu d'une option de compatibilite)."""
    all_notes = [n for _, ns in grouped for n, _, _ in ns]
    if shift is None:
        shift = choose_shift(all_notes, inst, cfg, extra_fixed)
    shift = int(shift)
    if not inst.offset_to_key:
        # profil sans aucune touche : rien n'est jouable, on ne devine pas un mapping
        return [], {"shift": 0, "folded": 0, "snapped": 0, "dropped": len(all_notes), "hits": 0,
                    "notes": len(all_notes), "out_of_range": 0, "missing_accidental": 0,
                    "exact": 0, "coverage": 0}
    lo, hi = inst.lowest, inst.lowest + inst.span
    result = []
    dropped = folded = snapped = out_of_range = exact = 0
    for t, ns in grouped:
        keys, played = [], []
        for n, dur, vel in ns:
            m = n + shift
            in_range = lo <= m <= hi
            if not in_range:
                out_of_range += 1
                if cfg.get("fold_out_of_range", True):
                    while m < lo:
                        m += 12
                    while m > hi:
                        m -= 12
                    folded += 1
                else:
                    dropped += 1
                    continue
            off = inst.snap(m - lo)
            if off != m - lo:
                snapped += 1
            elif in_range:
                exact += 1
            k = inst.offset_to_key[off]
            if k not in keys:
                keys.append(k)
                played.append((lo + off, dur, vel))
        if keys:
            result.append((t, keys, played))
    info = {"shift": shift, "folded": folded, "snapped": snapped,
            "dropped": dropped, "hits": len(result), "notes": len(all_notes),
            "out_of_range": out_of_range, "missing_accidental": snapped, "exact": exact,
            "coverage": round(100 * exact / len(all_notes)) if all_notes else 0}
    return result, info


def coverage_at(grouped, inst, cfg, shift):
    """Part des notes (0-100) jouees a la hauteur exacte pour une transposition donnee."""
    _, info = fit_notes(grouped, inst, cfg, shift=shift)
    return info["coverage"]


def _option_label(kind, value, coverage):
    if kind == "octave":
        sens = "Monter" if value > 0 else "Descendre"
        n = abs(value) // 12
        return f"{sens} de {n} octave{'s' if n > 1 else ''} : {coverage} % des notes à la hauteur exacte"
    if kind == "transpose":
        return f"Transposer de {value:+d} demi-ton{'s' if abs(value) > 1 else ''} : {coverage} % à la hauteur exacte"
    note = "note hors registre" if value <= 1 else "notes hors registre"
    if kind == "fold":
        return (f"Rejouer {value} {note} une octave plus loin au lieu de les omettre : "
                f"{coverage} % à la hauteur exacte")
    return f"Omettre {value} {note} : {coverage} % à la hauteur exacte, aucune note déplacée d'octave"


def compat_report(grouped, inst, cfg, extra=None, stats=None):
    """Diagnostic de compatibilite d'un morceau avec un instrument, options reellement testees.

    `extra` : decalage de tonalite impose (salon en ligne), comme pour fit_notes. Par tolerance, un dict
    passe a cette place est compris comme les `stats` de parse_midi (notes de percussion ignorees)."""
    if isinstance(extra, dict):
        extra, stats = None, extra
    events, info = fit_notes(grouped, inst, cfg, extra)
    base = info["coverage"]
    options = []
    if inst.offset_to_key and info["notes"]:
        for delta in (12, -12, 24, -24):
            cov = coverage_at(grouped, inst, cfg, info["shift"] + delta)
            if cov > base:
                options.append({"kind": "octave", "value": delta, "coverage": cov,
                                "label": _option_label("octave", delta, cov)})
        for delta in range(-6, 7):
            if delta == 0:
                continue
            cov = coverage_at(grouped, inst, cfg, info["shift"] + delta)
            if cov > base:
                options.append({"kind": "transpose", "value": delta, "coverage": cov,
                                "label": _option_label("transpose", delta, cov)})
        if info["out_of_range"]:
            # « omettre » est une OPTION a activer, pas un constat : on mesure ce qu'elle donnerait, et on
            # ne la propose que quand le reglage inverse est celui en vigueur. Dans l'autre sens, on
            # propose de remettre le repli d'octave : un reglage ne doit jamais etre a sens unique.
            folding = bool(cfg.get("fold_out_of_range", True))
            alt_cfg = dict(cfg)
            alt_cfg["fold_out_of_range"] = not folding
            _, alt = fit_notes(grouped, inst, alt_cfg, shift=info["shift"])
            if folding and alt["dropped"]:
                options.append({"kind": "omit", "value": alt["dropped"], "coverage": alt["coverage"],
                                "label": _option_label("omit", alt["dropped"], alt["coverage"])})
            elif not folding and alt["folded"]:
                options.append({"kind": "fold", "value": alt["folded"], "coverage": alt["coverage"],
                                "label": _option_label("fold", alt["folded"], alt["coverage"])})
    options.sort(key=lambda o: (-o["coverage"], abs(o["value"])))
    return {"notes": info["notes"], "playable": info["notes"] - info["dropped"],
            "out_of_range": info["out_of_range"], "missing_accidental": info["missing_accidental"],
            "dropped": info["dropped"], "drums": int((stats or {}).get("drums", 0) or 0),
            "shift": info["shift"], "coverage": base, "hits": len(events),
            "folded": info["folded"], "fold": bool(cfg.get("fold_out_of_range", True)),
            "options": options[:4]}


def build_timeline(events, target, hold, hold_mode="note", max_hold=4.0):
    """Transforme les evenements en actions triees : (t, ordre, type, data).
    type 'on'/'off' ; data = touches (jeu) ou (note, vel) (ecoute).
    hold_mode 'note' : chaque touche reste enfoncee la duree reelle de la note (appuis longs) ;
    hold_mode 'tap'  : appui bref fixe de `hold` secondes."""
    tl = []
    if target == "game":
        if hold_mode == "tap":
            for i, (t, keys, _) in enumerate(events):
                release = t + hold
                if i + 1 < len(events):
                    release = min(release, max(t + 0.008, events[i + 1][0] - 0.005))
                tl.append((t, 1, "on", keys))
                tl.append((release, 0, "off", keys))
        else:
            # prochaine pression de chaque touche, pour relacher juste avant si besoin
            per_key = []
            for t, keys, played in events:
                for k, (note, dur, vel) in zip(keys, played):
                    per_key.append((t, k, dur))
            next_press = {}
            for idx in range(len(per_key) - 1, -1, -1):
                t, k, dur = per_key[idx]
                per_key[idx] = (t, k, dur, next_press.get(k))
                next_press[k] = t
            for t, k, dur, nxt in per_key:
                release = t + max(hold, min(dur, max_hold))
                if nxt is not None:
                    release = min(release, max(t + 0.008, nxt - 0.012))
                tl.append((t, 1, "on", [k]))
                tl.append((release, 0, "off", [k]))
    else:
        for t, _, played in events:
            for note, dur, vel in played:
                tl.append((t, 1, "on", (note, vel)))
                tl.append((t + min(dur, 6.0), 0, "off", (note, 0)))
    tl.sort(key=lambda a: (a[0], a[1]))
    if target != "game":
        return tl
    # regroupe les actions simultanees de meme type (un accord = une seule frappe)
    merged = []
    for t, order, kind, data in tl:
        if merged and merged[-1][2] == kind and abs(merged[-1][0] - t) < 0.001:
            merged[-1][3].extend(x for x in data if x not in merged[-1][3])
        else:
            merged.append((t, order, kind, list(data)))
    return merged


# ---------------------------------------------------------------- Bibliotheque (titres, favoris, ecoutes)
_JUNK = re.compile(r"\[.*?\]|\(.*?\)|\b(?:www\.)?[a-z0-9]+\.(?:com|net|org|fr|io)\b|"
                   r"\b(?:anonymous|midi|mid|karaoke|k|converted by \w+)\b|\b\d{8,}\b", re.I)


def clean_title(filename):
    """Nom lisible a partir d'un nom de fichier : 'The-Weeknd-Blinding-Lights-Anonymous-2020...-nonstop2k.com.mid'
    -> 'The Weeknd Blinding Lights'."""
    name = os.path.basename(filename)
    while True:
        base, ext = os.path.splitext(name)
        if ext.lower() in (".mid", ".midi") and base:
            name = base
        else:
            break
    name = re.sub(r"[_\-–—]+", " ", name)   # tirets et soulignes -> espaces
    name = _JUNK.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" -_.,")
    return name or os.path.splitext(os.path.basename(filename))[0]


# Caracteres retires de tout texte venu du reseau avant affichage ou usage dans un nom de fichier :
# commandes C0/C1 (dont \n et \r), surcharges bidirectionnelles (U+202A..U+202E, U+2066..U+2069 :
# « innocent + U+202E + dim.exe » s'affiche « innocentexe.mid »), largeurs nulles et separateurs de ligne.
_INVISIBLE = re.compile("[\u0000-\u001f\u007f-\u009f\u00ad\u061c\u180e"
                        "\u200b-\u200f\u202a-\u202e\u2060-\u2064"
                        "\u2066-\u206f\ufeff\ufff9-\ufffb]")
_LINES = re.compile("[\t\n\v\f\r\u0085\u2028\u2029]")
_FS_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')
# Noms de peripherique Windows : ouvrir « CON.mid » parle a la console, pas a un fichier.
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "COM0", "LPT0",
                   *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_FILENAME_STEM = 100


def clean_display_text(value, max_len=120):
    """Texte sur a afficher et a reutiliser : sans caractere de controle ni de formatage invisible,
    espaces normalises, longueur bornee."""
    s = _LINES.sub(" ", str(value or ""))
    s = _INVISIBLE.sub("", s)
    s = re.sub("[ \u00a0\u1680\u2000-\u200a\u205f\u3000]+", " ", s).strip()
    return s[:max_len].strip()


def safe_song_filename(name, default="musique", ext=".mid"):
    """Nom de fichier assaini pour songs/ : pas de dossier, pas de `..`, pas de caractere reserve Windows,
    pas de nom de peripherique, pas de point ni d'espace final, longueur bornee. Toujours non vide."""
    stem = clean_display_text(name, 400)
    stem = stem.replace("\\", "/").rsplit("/", 1)[-1]        # jamais de composant de chemin
    for suffix in (".mid", ".midi"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = _FS_FORBIDDEN.sub("", stem).strip(" .")
    stem = re.sub(r"\s+", " ", stem)[:MAX_FILENAME_STEM].strip(" .")
    if not stem or set(stem) <= {"."}:
        stem = default
    if stem.upper() in _RESERVED_NAMES or stem.upper().split(".")[0] in _RESERVED_NAMES:
        stem = "_" + stem
    return stem + ext


def safe_join(folder, name, default="musique", ext=".mid"):
    """Chemin d'un fichier assaini garanti a l'interieur de `folder` (verifie par os.path.realpath).
    Leve ValueError si le resultat sortait du dossier : rien n'est ecrit ailleurs."""
    base = os.path.realpath(folder)
    path = os.path.realpath(os.path.join(base, safe_song_filename(name, default, ext)))
    if path != base and not path.startswith(base + os.sep):
        raise ValueError("chemin hors du dossier des musiques")
    return path


def file_sha256(path, block=1024 * 1024):
    """Empreinte SHA-256 (hex) d'un fichier, lue par blocs."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(block)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class Library:
    """Metadonnees des musiques (library.json a cote du dossier songs) : titre, favori, ecoutes, empreinte
    sha256 et identifiant en ligne (bibliotheque du serveur). Le verrou protege library.json : le thread de fond
    (calcul des empreintes) et l'interface ecrivent tous deux les metadonnees."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        self._lock = threading.RLock()
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f) or {}
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        with self._lock:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
            except (OSError, ValueError, RuntimeError):
                pass

    def meta(self, song_id):
        m = self.data.get(song_id)
        if m is None:
            with self._lock:
                m = self.data.get(song_id)
                if m is None:
                    m = self.data[song_id] = {"title": clean_title(song_id), "fav": False, "plays": 0,
                                              "added": time.time(), "last_played": 0}
                    self.save()
        return m

    # ---- bibliotheque en ligne
    def set_online(self, song_id, online_id=None, sha256=None):
        """Associe une musique locale a son identifiant sur le serveur et/ou memorise son empreinte."""
        with self._lock:
            m = self.meta(song_id)
            if online_id is not None:
                m["online_id"] = online_id
            if sha256 is not None:
                m["sha256"] = sha256
            self.save()

    def sha256(self, song_id, path):
        """Empreinte du fichier, en cache dans les metadonnees (recalculee si le fichier a change)."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        m = self.meta(song_id)
        if m.get("sha256") and m.get("sha_mtime") == mtime:
            return m["sha256"]
        try:
            sha = file_sha256(path)
        except OSError:
            return None
        with self._lock:
            m["sha256"] = sha
            m["sha_mtime"] = mtime
            self.save()
        return sha

    def find_by_sha(self, sha):
        """Identifiant (nom de fichier) de la musique locale qui a cette empreinte, ou None."""
        if not sha:
            return None
        with self._lock:
            for sid, m in self.data.items():
                if m.get("sha256") == sha:
                    return sid
        return None

    def find_by_online_id(self, oid):
        if oid is None:
            return None
        with self._lock:
            for sid, m in self.data.items():
                if m.get("online_id") is not None and str(m.get("online_id")) == str(oid):
                    return sid
        return None

    def set_title(self, song_id, title):
        title = re.sub(r"\s+", " ", str(title)).strip()[:120]
        self.meta(song_id)["title"] = title or clean_title(song_id)
        self.save()

    def toggle_fav(self, song_id):
        m = self.meta(song_id)
        m["fav"] = not m.get("fav", False)
        self.save()
        return m["fav"]

    def record_play(self, song_id):
        m = self.meta(song_id)
        m["plays"] = int(m.get("plays", 0)) + 1
        m["last_played"] = time.time()
        self.save()

    def remove(self, song_id):
        if self.data.pop(song_id, None) is not None:
            self.save()


SPEED_MIN, SPEED_MAX = 0.2, 4.0


def clamp_speed(value):
    """Vitesse de lecture bornee. Une valeur illisible ou nulle venant de config.json ne doit jamais
    atteindre la division `t / self.speed` de la boucle de lecture."""
    try:
        v = round(float(value), 2)
    except (TypeError, ValueError):
        return 1.0
    if v != v or v in (float("inf"), float("-inf")):
        return 1.0
    return max(SPEED_MIN, min(SPEED_MAX, v))


# ---------------------------------------------------------------- Player
class Player:
    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.instruments = cfg["_instruments"]
        ids = [i.id for i in self.instruments]
        wanted = cfg.get("instrument", ids[0])
        self.inst_index = ids.index(wanted) if wanted in ids else 0
        self.songs = []
        self.index = 0
        self.speed = clamp_speed(cfg.get("speed", 1.0))
        self.state = "stopped"      # stopped | playing | paused | sync (mode Multi : ecoute / note repere)
        self.target = "preview"     # preview (dans le logiciel) | game (touches clavier)
        self.sync = None            # SyncSession du mode Multi (sync.py), pose par l'application
        self.room = None            # RoomSession du salon en ligne (room.py), pose par l'application
        self.lock_speed = False     # vitesse verrouillee a 1.0 pendant une lecture synchronisee
        self.info = {}
        self.duration = 0.0
        self.last_stop_reason = ""
        self._thread = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._lock = threading.Lock()
        self._held = []
        self._start_time = None
        self._pos_at_pause = 0.0
        self._durations = {}
        self._midi = None
        self._expected = {}         # (scan_code, 'down'|'up') -> compteur des frappes injectees
        self._hook = None
        self.library = Library(os.path.join(DATA_DIR, "library.json"))
        self.refresh_songs()

    # ---- bibliotheque
    @property
    def instrument(self):
        return self.instruments[self.inst_index]

    @property
    def songs_folder(self):
        folder = self.cfg["songs_folder"]
        if not os.path.isabs(folder):
            folder = os.path.join(DATA_DIR, folder)
        os.makedirs(folder, exist_ok=True)
        return folder

    def refresh_songs(self):
        cur = self.current()
        folder = self.songs_folder
        self.songs = sorted(
            (os.path.join(folder, f) for f in os.listdir(folder)
             if f.lower().endswith((".mid", ".midi"))),
            key=lambda p: os.path.basename(p).lower())
        if cur in self.songs:
            self.index = self.songs.index(cur)
        self.index = min(self.index, max(0, len(self.songs) - 1))

    def song_duration(self, path):
        try:
            key = (path, os.path.getmtime(path))
        except OSError:
            return 0.0
        if key not in self._durations:
            self._durations[key] = midi_duration(path)
        return self._durations[key]

    def current(self):
        return self.songs[self.index] if self.songs else None

    def select(self, index):
        if 0 <= index < len(self.songs) and index != self.index:
            self.stop(join=True)
            self.index = index

    def set_instrument(self, index_or_id):
        """Change l'instrument actif (identifiant ou index). Renvoie (ok, message).

        Refuse pendant une lecture : remapper une note encore tenue avec un autre profil laisserait des
        touches enfoncees dans le jeu."""
        ids = [i.id for i in self.instruments]
        if isinstance(index_or_id, str):
            if index_or_id not in ids:
                return False, "Instrument inconnu."
            index = ids.index(index_or_id)
        else:
            try:
                index = int(index_or_id)
            except (TypeError, ValueError):
                return False, "Instrument inconnu."
            if not 0 <= index < len(self.instruments):
                return False, "Instrument inconnu."
        if index == self.inst_index:
            return True, ""
        if self.state != "stopped":
            return False, "Arrête la lecture avant de changer d'instrument."
        self._silence()
        self.inst_index = index
        self.cfg["instrument"] = self.instrument.id
        self.log(f"instrument : {self.instrument.name}")
        return True, ""

    # ---- position
    def position(self):
        if self.state == "playing" and self._start_time is not None:
            return max(0.0, (time.perf_counter() - self._start_time) * self.speed)
        if self.state == "paused":
            return self._pos_at_pause
        return 0.0

    # ---- actions
    def play(self, target="preview"):
        """Demarre (ou reprend) la lecture. target = 'preview' ou 'game'."""
        with self._lock:
            if self.state == "paused" and self.target == target:
                self._pause.clear()
                self.state = "playing"
                self.log("reprise")
                return
        if self.state != "stopped":
            self.stop(join=True)
        with self._lock:
            self._start(target)

    def play_pause(self, target=None):
        """Raccourci clavier : joue dans le jeu, ou met en pause / reprend."""
        same = target is None or target == self.target
        with self._lock:
            if self.state == "playing" and same:
                self._pos_at_pause = self.position()
                self._pause.set()
                self.state = "paused"
                self._silence()
                self.log("pause")
                return
            if self.state == "paused" and same:
                self._pause.clear()
                self.state = "playing"
                self.log("reprise")
                return
        # autre mode en cours (ecoute vs jeu) ou arrete : on (re)demarre dans le mode demande
        self.play(target or "game")

    def pause(self):
        with self._lock:
            if self.state == "playing":
                self._pos_at_pause = self.position()
                self._pause.set()
                self.state = "paused"
                self._silence()
                self.log("pause")

    def stop(self, join=False, reason=""):
        with self._lock:
            # _start() tourne sous ce meme verrou : lu ici, « fil vivant » ne peut pas etre perime
            alive = bool(self._thread and self._thread.is_alive())
            if self.state != "stopped":
                self.last_stop_reason = reason
                self._stop.set()
                self._pause.clear()
                self.log("stop" + (f" ({reason})" if reason else ""))
                if not alive:
                    # aucun fil pour appeler _finish() : etat « sync » pose par un salon, ou fil mort sur
                    # une erreur. On remet l'etat a l'arret ici, sinon le lecteur reste bloque pour de bon.
                    self.state = "stopped"
                    self._start_time = None
                    self.lock_speed = False
                    self._silence()
        self._abort_sessions(reason or "stop")
        if join and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _abort_sessions(self, reason):
        """Previent les sessions synchronisees (mode Multi audio, salon en ligne) d'un arret local."""
        if self.sync is not None and self.sync.active():
            self.sync.abort(reason)
        if self.room is not None and self.room.active():
            try:
                self.room.on_player_stop(reason)
            except Exception as e:  # noqa
                self.log(f"salon : {e}")

    def next_song(self):
        self._switch(+1)

    def prev_song(self):
        self._switch(-1)

    def next_instrument(self):
        """Instrument suivant parmi ceux dont le profil est pret (F12)."""
        ready = [i for i, inst in enumerate(self.instruments) if inst.ready]
        if not ready:
            self.log("aucun instrument prêt : configure d'abord ses touches")
            return False, "Aucun instrument prêt : configure d'abord ses touches."
        index = next((i for i in ready if i > self.inst_index), ready[0])
        return self.set_instrument(index)

    def set_speed(self, value):
        if self.lock_speed:
            self.log("vitesse verrouillée à x1.00 en lecture synchronisée")
            return
        old_pos = self.position()
        self.speed = clamp_speed(value)
        if self.state == "playing" and self._start_time is not None:
            self._start_time = time.perf_counter() - old_pos / self.speed
        self.cfg["speed"] = self.speed

    def speed_up(self):
        self.set_speed(self.speed + 0.1)
        self.log(f"vitesse x{self.speed}")

    def speed_down(self):
        self.set_speed(self.speed - 0.1)
        self.log(f"vitesse x{self.speed}")

    def _switch(self, delta):
        self.stop(join=True)
        self.refresh_songs()
        if not self.songs:
            self.log("aucun fichier .mid dans la bibliotheque")
            return
        self.index = (self.index + delta) % len(self.songs)
        self.log(f"musique : {os.path.basename(self.current())}")

    # ---- interruption par l'utilisateur (mode jeu)
    def _on_key_event(self, event):
        """Hook clavier global : une vraie frappe (pas la notre) arrete la lecture jeu."""
        if self.state == "sync" and self.cfg.get("stop_on_input", True) and (self.sync is not None
                                                                              or self.room is not None):
            # mode Multi / salon en attente : nos notes reperes sont attendues, une autre touche annule
            key = (event.scan_code, event.event_type)
            n = self._expected.get(key, 0)
            if n > 0:
                self._expected[key] = n - 1
                return
            if (event.name or "").lower() in self._hotkey_names() or event.event_type != "down":
                return
            self._abort_sessions("clavier touche")
            return
        if self.state != "playing" or self.target != "game" or not self.cfg.get("stop_on_input", True):
            return
        if self._start_time is None or time.perf_counter() < self._start_time:
            return  # pendant le delai de depart (la touche du raccourci est encore enfoncee)
        key = (event.scan_code, event.event_type)
        n = self._expected.get(key, 0)
        if n > 0:
            self._expected[key] = n - 1
            return
        name = (event.name or "").lower()
        if name in self._hotkey_names():
            return
        self.stop(reason="clavier touche")

    def _hotkey_names(self):
        names = set()
        for combo in self.cfg.get("hotkeys", {}).values():
            for part in str(combo).lower().replace(" ", "").split("+"):
                if part:
                    names.add(part)
        return names

    def _expect(self, keys, up):
        mode = self.cfg["input_mode"]
        et = "up" if up else "down"
        for k in keys:
            key = (scan_code_for(k, mode), et)
            self._expected[key] = self._expected.get(key, 0) + 1

    # ---- lecture
    def _start(self, target, deadline=None, prepared=None):
        inst = self.instrument
        if not inst.ready:
            # un profil inconnu mene a la configuration, jamais au mapping du piano
            self.log(f"{inst.name} : {inst.blocked_reason}")
            self._abandon_start()
            return
        self.refresh_songs()
        song = prepared["song"] if prepared else self.current()
        if not song:
            self.log("aucun fichier .mid dans la bibliotheque")
            self._abandon_start()
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._pause.clear()
        self.state = "playing"
        self.target = target
        self.last_stop_reason = ""
        self._held = []
        self._expected = {}
        self._start_time = None
        self.library.record_play(os.path.basename(song))
        self._thread = threading.Thread(target=self._run, args=(song, self.instrument, target, deadline, prepared),
                                        daemon=True)
        self._thread.start()

    def _abandon_start(self):
        """Sortie anticipee de _start : l'appelant (play_at du salon) a pu forcer l'etat « sync », et aucun
        fil ne viendra le remettre a l'arret. Appele avec self._lock deja pris : on ne le reprend pas."""
        if self.state != "stopped":
            self.state = "stopped"
        self._start_time = None
        self.lock_speed = False
        self._silence()

    def play_at(self, deadline, prepared, target="game"):
        """Mode Multi : demarre la lecture (deja preparee par prepare()) a l'instant perf_counter `deadline`."""
        with self._lock:
            self._start(target, deadline, prepared)

    def prepare(self, song, inst, target, common_key=False, extra=None):
        """Analyse le fichier et construit la chronologie sans jouer. common_key : tonalite commune a tous
        les joueurs (mode Multi audio, calculee ici), vitesse ignoree. extra : decalage de tonalite impose tel
        quel (salon en ligne : fixe par le chef et envoye a tous)."""
        grouped = parse_midi(song, self.cfg)
        if extra is not None:
            extra = int(extra)
        elif common_key:
            from sync import choose_common_extra
            extra = choose_common_extra([n for _, ns in grouped for n, _, _ in ns])
        events, info = fit_notes(grouped, inst, self.cfg, extra)
        timeline = build_timeline(events, target, float(self.cfg.get("hold_time", 0.04)),
                                  self.cfg.get("hold_mode", "note"), float(self.cfg.get("max_hold", 4.0)))
        return {"song": song, "events": events, "info": info, "timeline": timeline,
                "duration": events[-1][0] if events else 0.0}

    def play_keys(self, keys, hold=0.12):
        """Appuie puis relache `keys` dans le jeu (note repere du mode Multi). Renvoie l'instant de l'appui."""
        mode = self.cfg["input_mode"]
        self._expect(keys, False)
        t = time.perf_counter()
        send_keys(keys, False, mode)
        time.sleep(hold)
        self._expect(keys, True)
        send_keys(keys, True, mode)
        return t

    def _silence(self):
        """Relache les touches / coupe les notes en cours (pause, stop).

        Ne leve jamais : c'est le dernier geste du fil de lecture et de stop(). Si l'envoi du relachement
        echoue, la liste est quand meme vidée (sinon chaque tentative suivante replanterait au meme endroit)
        et l'echec est journalise."""
        if self._held:
            keys, self._held = self._held, []
            try:
                self._expect(keys, True)
                send_keys(keys, True, self.cfg["input_mode"])
            except Exception as e:  # noqa
                self.log(f"relâchement des touches impossible : {e!r}")
        if self._midi:
            try:
                self._midi.all_off()
            except Exception as e:  # noqa
                self.log(f"arrêt des notes impossible : {e!r}")

    def _run(self, song, inst, target, deadline=None, prepared=None):
        """Fil de lecture. TOUT le corps est protege : une erreur d'injection ou de calcul ne doit jamais
        laisser une touche enfoncee dans le jeu ni le lecteur bloque en « playing » (le finally appelle
        _finish, qui relache les touches et remet l'etat a l'arret)."""
        try:
            self._run_body(song, inst, target, deadline, prepared)
        except Exception as e:  # noqa - panne silencieuse dans un build fenetre : on journalise
            self.log(f"erreur pendant la lecture : {e!r}")
            self.last_stop_reason = self.last_stop_reason or "erreur"
        finally:
            self._finish()

    def _run_body(self, song, inst, target, deadline=None, prepared=None):
        try:
            if prepared is None:
                prepared = self.prepare(song, inst, target)
            events, info, timeline = prepared["events"], prepared["info"], prepared["timeline"]
        except Exception as e:  # noqa
            self.log(f"erreur lecture MIDI : {e}")
            return
        self.info = info
        mode = self.cfg["input_mode"]
        self.duration = prepared["duration"]
        if target == "preview":
            if self._midi is None:
                self._midi = MidiOut()
            self._midi.program(inst.gm_program)
            self._midi.volume(int(self.cfg.get("preview_volume", 100)) * 127 // 100)
        self.log(f"{'ecoute' if target == 'preview' else 'jeu'} : {os.path.basename(song)} sur {inst.name} "
                 f"(transposition {info['shift']:+d})")
        if deadline is None:
            delay = float(self.cfg.get("start_delay", 1.0)) if target == "game" else 0.15
            self._start_time = time.perf_counter() + delay
        else:
            # mode Multi : echeance absolue partagee (un depart deja passe est rattrape par la boucle)
            self._start_time = float(deadline)
            delay = max(0.0, deadline - time.perf_counter())
        if self._wait(delay):
            return
        if target == "game" and deadline is None and self.cfg.get("stop_on_input", True):
            # attend que les boutons de la souris et le raccourci soient relaches
            while mouse_button_down() and not self._stop.is_set():
                time.sleep(0.02)

        start = self._start_time
        i = 0
        mouse_check = 0.0
        while i < len(timeline) and not self._stop.is_set():
            if self._pause.is_set():
                pause_at = time.perf_counter()
                while self._pause.is_set() and not self._stop.is_set():
                    time.sleep(0.02)
                start += time.perf_counter() - pause_at
                self._start_time = start
                continue
            t, _, kind, data = timeline[i]
            now = time.perf_counter()
            target_t = start + t / self.speed
            if target_t > now:
                if self._wait(target_t - now):
                    break
                continue
            if target == "game":
                if kind == "on":
                    self._expect(data, False)
                    send_keys(data, False, mode)
                    self._held = [k for k in self._held if k not in data] + list(data)
                else:
                    self._expect(data, True)
                    send_keys(data, True, mode)
                    self._held = [k for k in self._held if k not in data]
                if self.cfg.get("stop_on_input", True) and now - mouse_check > 0.03:
                    mouse_check = now
                    if mouse_button_down():
                        self.stop(reason="clic souris")
                        break
            else:
                note, vel = data
                if kind == "on":
                    if note in self._midi.sounding:
                        self._midi.note_off(note)
                    self._midi.note_on(note, vel)
                else:
                    self._midi.note_off(note)
            i += 1

    def _wait(self, seconds):
        end = time.perf_counter() + seconds
        check_mouse = self.target == "game" and self.cfg.get("stop_on_input", True)
        while True:
            if self._stop.is_set():
                return True
            if self._pause.is_set():
                return False
            now = time.perf_counter()
            rem = end - now
            if rem <= 0:
                return False
            if check_mouse and self._start_time is not None and now >= self._start_time and mouse_button_down():
                self.stop(reason="clic souris")
                return True
            time.sleep(min(rem, 0.01))

    def _finish(self):
        self._silence()
        with self._lock:
            self.state = "stopped"
        self._start_time = None
        self.lock_speed = False
        self.log("fin")

    def close(self):
        self.stop(join=True)
        if self._midi:
            self._midi.close()
            self._midi = None


def bind_hotkeys(player, cfg):
    """Raccourcis globaux + hook d'interruption. Retourne les handles a retirer."""
    hk = cfg["hotkeys"]
    actions = {
        "play_pause": lambda: player.play_pause("game"), "stop": player.stop,
        "next_song": player.next_song, "prev_song": player.prev_song,
        "speed_down": player.speed_down, "speed_up": player.speed_up,
        "next_instrument": player.next_instrument,
    }
    handles = []
    for name, fn in actions.items():
        combo = hk.get(name)
        if combo:
            try:
                handles.append(platform_io.add_hotkey(combo, fn))
            except Exception as e:  # noqa
                player.log(f"raccourci invalide {combo!r} : {e}")
    if player._hook is None:
        player._hook = platform_io.hook(player._on_key_event)
    return handles
