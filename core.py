# -*- coding: utf-8 -*-
"""Moteur de DodoTopia : instruments, lecture MIDI, envoi des touches, ecoute integree."""
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import time

import mido

import i18n
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
                "speed_down": "F10", "speed_up": "F11", "next_instrument": ""},
    "start_delay": 1.0, "speed": 1.0, "hold_time": 0.04, "chord_window": 0.02,
    "transpose_semitones": 0, "fold_out_of_range": True, "ignore_drums": True,
    "input_mode": "scancode", "stop_on_input": True, "preview_volume": 100,
    "hold_mode": "note", "max_hold": 4.0,
    # appui minimal d'une touche et ecart minimal entre le relachement et l'appui suivant de la meme touche.
    # 8 ms etait sous la duree d'une image a 60 i/s : le jeu perdait des notes repetees.
    "min_press": 0.02, "min_gap": 0.012,
    # pedale de sustain (CC64) : False = ignoree (duree ecrite), True = les notes tenues durent jusqu'au
    # relachement de la pedale (borne par max_hold)
    "sustain": False,
    # executables du jeu, separes par des virgules (Heartopia tourne sous xdt.exe) : la lecture, le dessin et la
    # cuisine verifient que le jeu est au premier plan ; sa fenetre est aussi reconnue a son titre
    # ("" = aucune verification)
    "game_process": platform_io.DEFAULT_GAME_PROCESS,
    "keyboard_layout": "auto", "instrument_favorites": [],
    # arrangeur (arrange.py) : "auto" = instruments non chromatiques, "on", "off" ; surchargeable par morceau
    "arrange": "auto",
    # overlay au-dessus de Heartopia (api/overlay.py) : seulement jeu au premier plan + musique ou dessin en cours
    "overlay": {"enabled": True, "corner": "top-right"},
}


def _log_migration(lines):
    """Journalise les lignes de migration des instruments (sans console : on ignore silencieusement)."""
    for line in lines:
        try:
            print(f"instruments : {line}")
        except Exception:  # noqa : pas de sortie standard en mode fenetre
            return


def write_json_atomic(path, data, **dump_kw):
    """Ecrit `data` en JSON sans jamais laisser un fichier tronque : fichier temporaire dans le meme dossier,
    fsync, puis remplacement atomique (os.replace). Une coupure pendant l'ecriture laisse l'ancien fichier
    intact au lieu d'un JSON invalide qui empecherait l'application de demarrer."""
    dump_kw.setdefault("indent", 2)
    dump_kw.setdefault("ensure_ascii", False)
    tmp = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kw)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _read_config_file():
    """Lit config.json. Un fichier illisible (tronque, corrompu) est mis de cote sous un nom horodate et on
    repart de la configuration par defaut : l'application demarre toujours. Renvoie (cfg, recupere)."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError("config.json n'est pas un objet JSON")
        return cfg, False
    except (OSError, ValueError) as e:
        broken = f"{CONFIG_PATH}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(CONFIG_PATH, broken)
        except OSError:
            pass
        try:
            print(f"config.json illisible ({e}), sauvegardé sous {os.path.basename(broken)} ; valeurs par défaut")
        except Exception:  # noqa
            pass
        cfg = {}
        if os.path.exists(DEFAULT_CONFIG_PATH):
            try:
                with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except (OSError, ValueError):
                cfg = {}
        return (cfg if isinstance(cfg, dict) else {}), True


def is_note_key(combo):
    """Vrai si `combo` est une touche seule qui sert aussi a jouer une note (lettre, chiffre, ponctuation des
    dispositions d'instruments). Un raccourci global sur une telle touche se declenche quand DodoTopia
    l'envoie au jeu : la lecture s'arretait « sans raison » avec Arreter = b."""
    s = str(combo or "").strip().lower()
    return bool(s) and "+" not in s and s in SCANCODES


def sanitize_hotkeys(cfg):
    """Remet a leur valeur par defaut les raccourcis poses sur une touche de note. Renvoie les noms corriges."""
    fixed = []
    hk = cfg.get("hotkeys")
    if not isinstance(hk, dict):
        return fixed
    defaults = dict(DEFAULT_CONFIG["hotkeys"], draw_point="F3")
    for name, combo in list(hk.items()):
        if is_note_key(combo):
            hk[name] = defaults.get(name, "")
            fixed.append(name)
    return fixed


def load_config():
    if not os.path.exists(CONFIG_PATH) and os.path.exists(DEFAULT_CONFIG_PATH):
        shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
    cfg, recovered = _read_config_file()
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    cfg["_recovered"] = recovered
    # F12 (ancien defaut d'« instrument suivant ») est la capture d'ecran Steam : on retire ce raccourci s'il
    # n'a jamais ete change. Cycler 19 instruments a l'aveugle n'a plus de sens, le selecteur fait mieux.
    hk = cfg.get("hotkeys")
    if isinstance(hk, dict) and not cfg.get("hotkeys_migrated_f12"):
        if str(hk.get("next_instrument", "")).upper() == "F12":
            hk["next_instrument"] = ""
        cfg["hotkeys_migrated_f12"] = True
    cfg["_hotkeys_fixed"] = sanitize_hotkeys(cfg)
    # 2.0.0 livrait « Heartopia.exe », qui n'est pas le nom du processus du jeu (xdt.exe) : F6 refusait de jouer.
    if str(cfg.get("game_process") or "").strip().lower() == "heartopia.exe":
        cfg["game_process"] = platform_io.DEFAULT_GAME_PROCESS
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
    write_json_atomic(CONFIG_PATH, data)


# ---------------------------------------------------------------- MIDI
# Garde-fous sur les fichiers ouverts : un .mid vient parfois d'internet (bibliotheque en ligne, salon).
# Un fichier hostile de quelques Mo en running status contient des centaines de milliers d'evenements et
# figerait l'application dans parse_midi. Plafonds volontairement plus larges que ceux du serveur
# (server/app/config.py) : les fichiers locaux de l'utilisateur ne doivent pas etre refuses a tort.
MAX_MIDI_BYTES = 16 * 1024 * 1024
MAX_MIDI_EVENTS = 200_000
MAX_MIDI_NOTES = 100_000


class MidiRefused(ValueError):
    """Fichier MIDI illisible ou hors des plafonds : message pret a afficher (traduit par i18n.t)."""


# Raisons d'arret du lecteur (Player.stop(reason=...), last_stop_reason) : des codes stables, jamais du texte.
# Les modules dessin / cuisine posent leurs propres raisons (en francais) sur leur propre etat, pas ici.
STOP_CODES = ("stop", "keyboard", "mouse", "closing", "error", "injection_denied", "game_not_focused",
              "midi_out_unavailable", "mode_change", "cancel", "room_stop", "room_ended", "room_left",
              "room_closed", "restart")
# Arrets voulus ou attendus (information), par opposition aux arrets sur erreur (danger + toast).
BENIGN_STOP_CODES = ("stop", "keyboard", "mouse", "closing", "mode_change", "cancel", "room_stop",
                     "room_ended", "room_left", "room_closed", "restart")
# Cles construites dynamiquement (`stop.{code}`), declarees pour .tools/i18n_check.py.
I18N_KEYS = ["stop.stop", "stop.keyboard", "stop.mouse", "stop.closing", "stop.error", "stop.injection_denied",
             "stop.game_not_focused", "stop.midi_out_unavailable", "stop.mode_change", "stop.cancel",
             "stop.room_stop", "stop.room_ended", "stop.room_left", "stop.room_closed", "stop.restart",
             "stop.unknown"]


def stop_reason_text(code):
    """Phrase affichee pour un code d'arret (langue courante) ; un code inconnu est montre tel quel."""
    code = str(code or "")
    if code in STOP_CODES:
        return i18n.t(f"stop.{code}")
    return i18n.t("stop.unknown", reason=code)


def _open_midi(path):
    """mido.MidiFile avec verification prealable de la taille et de l'entete magique."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise MidiRefused(i18n.t("midi.unreadable_file", error=e.strerror or e)) from None
    if size > MAX_MIDI_BYTES:
        raise MidiRefused(i18n.t("midi.too_big", size=size // (1024 * 1024), max=MAX_MIDI_BYTES // (1024 * 1024)))
    with open(path, "rb") as f:
        if f.read(4) != b"MThd":
            raise MidiRefused(i18n.t("midi.not_midi"))
    try:
        mid = mido.MidiFile(path)
    except Exception:  # noqa : mido leve un peu de tout
        # certains exporteurs (BandLab...) ecrivent des octets de donnees > 127 (program change 255,
        # pitch bend mal forme) : on les ramene a 127 plutot que de refuser tout le fichier
        try:
            mid = mido.MidiFile(path, clip=True)
        except Exception as e:  # noqa
            raise MidiRefused(i18n.t("midi.corrupt", error=type(e).__name__)) from None
        logging.getLogger("midi").warning("MIDI avec octets hors plage, lu en mode tolerant : %s",
                                          os.path.basename(path))
    if mid.type not in (0, 1):
        raise MidiRefused(i18n.t("midi.type_unsupported", type=mid.type))
    return mid


def midi_tracks(path):
    """Pistes du fichier pour l'interface : [{index, name, notes, channels, drums}]. Les pistes sans note
    (tempo, paroles) sont listees avec notes = 0 pour que les index restent ceux du fichier."""
    mid = _open_midi(path)
    out = []
    for i, track in enumerate(mid.tracks):
        name = ""
        notes = 0
        channels = set()
        for msg in track:
            if msg.type == "track_name" and not name:
                name = clean_display_text(msg.name, 60)
            elif msg.type == "note_on" and msg.velocity > 0:
                notes += 1
                channels.add(msg.channel)
        out.append({"index": i, "name": name, "notes": notes, "channels": sorted(channels),
                    "drums": bool(channels) and channels <= {9}})
    return out


def _merged_messages(mid, skip_tracks):
    """Messages fusionnes en secondes (comme `for msg in mid`) en ignorant les notes des pistes `skip_tracks`.
    Les meta-messages (tempo, signature) des pistes ignorees sont conserves : le tempo est souvent sur la
    piste 0, la retirer casserait la chronologie de toutes les autres."""
    if not skip_tracks:
        return iter(mid)
    skip = {int(i) for i in skip_tracks}
    tracks = []
    for i, track in enumerate(mid.tracks):
        if i in skip:
            kept = mido.MidiTrack()
            t_acc = 0
            for msg in track:
                t_acc += msg.time
                if msg.is_meta:
                    kept.append(msg.copy(time=t_acc))
                    t_acc = 0
            tracks.append(kept)
        else:
            tracks.append(track)
    copy = mido.MidiFile(type=mid.type, ticks_per_beat=mid.ticks_per_beat)
    copy.tracks.extend(tracks)
    return iter(copy)


def parse_midi(path, cfg, stats=None, skip_tracks=None, drums_only=False):
    """Liste triee [(t, [(note, duree, velocite), ...])], accords regroupes.

    `skip_tracks` : index de pistes dont les notes sont ignorees (choix de l'utilisateur par morceau).
    `drums_only` : seulement la batterie (canal 10, notes General MIDI de percussion) pour les instruments a
    frappes (conga) ; sinon la batterie est ignoree ou gardee selon cfg["ignore_drums"].
    Pedale de sustain (CC64) : avec cfg["sustain"], une note relachee pedale enfoncee dure jusqu'au
    relachement de la pedale (comme au piano) ; sinon la duree ecrite est gardee.

    `stats` : dict facultatif rempli au passage avec "drums" (notes de percussion ignorees) et "channels"
    (canaux MIDI rencontres). La signature reste retro-compatible.

    Leve MidiRefused (ValueError) si le fichier n'est pas un MIDI exploitable ou depasse les plafonds."""
    mid = _open_midi(path)
    notes = []          # (t_on, note, dur, vel)
    pending = {}        # (channel, note) -> (t_on, vel)
    sustain = bool(cfg.get("sustain", False))
    pedal = set()       # canaux dont la pedale est enfoncee
    held = {}           # (channel, note) -> (t_on, vel) : relachees pedale enfoncee, en attente du CC64
    t = 0.0
    events = 0
    drums = 0
    channels = set()
    for msg in _merged_messages(mid, skip_tracks):
        events += 1
        if events > MAX_MIDI_EVENTS:
            raise MidiRefused(i18n.t("midi.too_many_events", n=MAX_MIDI_EVENTS))
        if len(notes) > MAX_MIDI_NOTES:
            raise MidiRefused(i18n.t("midi.too_many_notes", n=MAX_MIDI_NOTES))
        t += msg.time
        if msg.type in ("note_on", "note_off"):
            channels.add(msg.channel)
        if msg.type == "note_on" and msg.velocity > 0:
            if drums_only:
                if msg.channel != 9:
                    continue
            elif cfg.get("ignore_drums", True) and msg.channel == 9:
                drums += 1
                continue
            key = (msg.channel, msg.note)
            if key in held:     # rejouee pendant le sustain : la tenue precedente s'arrete ici
                t0, v0 = held.pop(key)
                notes.append((t0, msg.note, max(0.05, t - t0), v0))
            if key in pending:  # re-declenchee sans note_off
                t0, v0 = pending.pop(key)
                notes.append((t0, msg.note, max(0.05, t - t0), v0))
            pending[key] = (t, msg.velocity)
        elif msg.type in ("note_off", "note_on"):
            key = (msg.channel, msg.note)
            if key in pending:
                t0, v0 = pending.pop(key)
                if sustain and msg.channel in pedal:
                    held[key] = (t0, v0)
                else:
                    notes.append((t0, msg.note, max(0.05, t - t0), v0))
        elif sustain and msg.type == "control_change" and msg.control == 64:
            if msg.value >= 64:
                pedal.add(msg.channel)
            elif msg.channel in pedal:
                pedal.discard(msg.channel)
                for key in [k for k in held if k[0] == msg.channel]:
                    t0, v0 = held.pop(key)
                    notes.append((t0, key[1], max(0.05, t - t0), v0))
    for (ch, note), (t0, v0) in list(pending.items()) + list(held.items()):
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
    dropped = folded = snapped = out_of_range = exact = dropped_poly = 0
    try:
        polyphony = int(getattr(inst, "polyphony", None) or 0)
    except (TypeError, ValueError):
        polyphony = 0
    for t, ns in grouped:
        keys, played = [], []
        if polyphony > 0 and len(ns) > polyphony:
            # l'instrument ne tient pas autant de notes a la fois : on garde la plus grave (basse) et les
            # plus aigues (melodie), les intermediaires sont omises
            ordered = sorted(ns, key=lambda x: x[0])
            keep = [ordered[0]] + ordered[-(polyphony - 1):] if polyphony > 1 else ordered[-1:]
            dropped_poly += len(ns) - len(keep)
            ns = sorted(keep, key=lambda x: x[0])
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
            "dropped": dropped + dropped_poly, "dropped_poly": dropped_poly, "hits": len(result),
            "notes": len(all_notes),
            "out_of_range": out_of_range, "missing_accidental": snapped, "exact": exact,
            "coverage": round(100 * exact / len(all_notes)) if all_notes else 0}
    return result, info


ARRANGE_MODES = ("auto", "on", "off")


def fit_song(grouped, inst, cfg, extra_fixed=None, mode=None, octave=0):
    """fit_notes precede de l'arrangeur quand il s'applique (mode : 'auto' | 'on' | 'off', defaut cfg).
    info["arranged"] porte les chiffres de l'arrangement (None sans arrangement). `octave` : octaves ajoutees
    a la transposition choisie (partie de l'Orchestre reglee par le chef)."""
    import arrange
    mode = mode if mode in ARRANGE_MODES else cfg.get("arrange", "auto")
    octave = int(octave or 0)
    if not arrange.applies(inst, mode):
        if octave:
            notes = [n for _, ns in grouped for n, _, _ in ns]
            events, info = fit_notes(grouped, inst, cfg, shift=choose_shift(notes, inst, cfg, extra_fixed) + 12 * octave)
        else:
            events, info = fit_notes(grouped, inst, cfg, extra_fixed)
        info["arranged"] = None
        return events, info
    arranged, shift, stats = arrange.arrange(grouped, inst, cfg, extra_fixed, octave)
    events, info = fit_notes(arranged, inst, cfg, shift=shift)
    info["arranged"] = stats
    return events, info


def coverage_at(grouped, inst, cfg, shift):
    """Part des notes (0-100) jouees a la hauteur exacte pour une transposition donnee."""
    _, info = fit_notes(grouped, inst, cfg, shift=shift)
    return info["coverage"]


def _option_label(kind, value, coverage):
    """Libelle d'une option du diagnostic, dans la langue courante (pluriels par i18n)."""
    if kind == "octave":
        return i18n.t("compat.option.octave", dir="up" if value > 0 else "down", n=abs(value) // 12,
                      coverage=coverage)
    if kind == "transpose":
        return i18n.t("compat.option.transpose", delta=f"{value:+d}", n=abs(value), coverage=coverage)
    if kind == "fold":
        return i18n.t("compat.option.fold", n=value, coverage=coverage)
    return i18n.t("compat.option.omit", n=value, coverage=coverage)


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


MIN_PRESS_DEFAULT = 0.02    # appui minimal d'une touche (une image a 60 i/s dure 16,7 ms)
MIN_GAP_DEFAULT = 0.012     # ecart minimal entre le relachement et l'appui suivant de la meme touche


def build_timeline(events, target, hold, hold_mode="note", max_hold=4.0,
                   min_press=MIN_PRESS_DEFAULT, min_gap=MIN_GAP_DEFAULT):
    """Transforme les evenements en actions triees : (t, ordre, type, data).
    type 'on'/'off' ; data = touches (jeu) ou (note, vel) (ecoute).
    hold_mode 'note' : chaque touche reste enfoncee la duree reelle de la note (appuis longs) ;
    hold_mode 'tap'  : appui bref fixe de `hold` secondes.
    min_press / min_gap : planchers (secondes) pour que le jeu voie chaque appui et chaque relachement."""
    tl = []
    min_press = max(0.001, float(min_press or MIN_PRESS_DEFAULT))
    min_gap = max(0.001, float(min_gap or MIN_GAP_DEFAULT))
    if target == "game":
        if hold_mode == "tap":
            for i, (t, keys, _) in enumerate(events):
                release = t + max(hold, min_press)
                if i + 1 < len(events):
                    release = min(release, max(t + min_press, events[i + 1][0] - min_gap))
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
                release = t + max(hold, min_press, min(dur, max_hold))
                if nxt is not None:
                    release = min(release, max(t + min_press, nxt - min_gap))
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
        self.version = 0            # incremente a chaque enregistrement : signature de cache pour l'interface
        self._lock = threading.RLock()
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f) or {}
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        with self._lock:
            self.version += 1
            try:
                write_json_atomic(self.path, self.data)
            except (OSError, ValueError, RuntimeError) as e:
                logging.getLogger("library").warning("library.json non enregistré : %s", e)

    def set_tracks_off(self, song_id, indexes):
        """Pistes ignorees a la lecture pour ce morceau (liste d'index, videe si aucune)."""
        with self._lock:
            m = self.meta(song_id)
            off = sorted({int(i) for i in (indexes or [])})
            if off:
                m["tracks_off"] = off
            else:
                m.pop("tracks_off", None)
            self.save()
            return off

    def set_arrange(self, song_id, mode):
        """Arrangement propre a ce morceau ('auto' | 'on' | 'off'), None = suivre le reglage general."""
        with self._lock:
            m = self.meta(song_id)
            if mode in ARRANGE_MODES:
                m["arrange"] = mode
            else:
                m.pop("arrange", None)
            self.save()
            return m.get("arrange")

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
        self._held_at_pause = []    # touches enfoncees au moment de la pause (a re-enfoncer a la reprise)
        self._start_time = None
        self._pos_at_pause = 0.0
        # horloge de lecture : (position dans le morceau, instant perf_counter) de reference. La boucle et
        # position() la relisent a chaque fois ; set_speed() et la reprise la recalent (sous _clock_lock).
        self._clock = None
        self._clock_lock = threading.Lock()
        self._clock_changed = threading.Event()     # leve par set_speed : _wait() se reveille et recalcule
        self._durations = {}
        self._midi = None
        self._expected = {}         # (scan_code, 'down'|'up') -> compteur des frappes injectees
        self._exp_lock = threading.Lock()   # partage entre le fil de lecture et le crochet clavier
        self._hook = None
        self.library = Library(os.path.join(DATA_DIR, "library.json"))
        # reprise d'un morceau interrompu dans le jeu (solo) : {song, mtime, pos, duration, reason}
        self._cur = None                # (chemin, cible, joue en solo) de la lecture en cours
        self._completed = False         # la lecture en cours est allee jusqu'au bout
        self._resume_path = os.path.join(DATA_DIR, "lecture_reprise.json")
        self._resume = self._load_resume()
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
        """Duree du morceau, lue dans library.json si le fichier n'a pas change ; sinon calculee une fois et
        memorisee (l'appelant ne doit pas etre le tick de l'interface : voir Api._songs_state)."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return 0.0
        key = (path, mtime)
        if key in self._durations:
            return self._durations[key]
        sid = os.path.basename(path)
        m = self.library.meta(sid)
        if m.get("duration") is not None and m.get("dur_mtime") == mtime:
            self._durations[key] = float(m["duration"])
            return self._durations[key]
        dur = midi_duration(path)
        self._durations[key] = dur
        with self.library._lock:
            m["duration"] = dur
            m["dur_mtime"] = mtime
            self.library.save()
        return dur

    def current(self):
        return self.songs[self.index] if self.songs else None

    # ---- reprise d'un morceau interrompu (solo, dans le jeu)
    RESUME_MIN_POS = 3.0            # en dessous, recommencer au debut revient au meme

    def _load_resume(self):
        try:
            with open(self._resume_path, encoding="utf-8") as f:
                r = json.load(f)
            return r if isinstance(r, dict) and r.get("song") and float(r.get("pos", 0)) > 0 else None
        except (OSError, ValueError, TypeError):
            return None

    def _set_resume(self, r):
        self._resume = r
        try:
            if r is None:
                if os.path.exists(self._resume_path):
                    os.remove(self._resume_path)
            else:
                write_json_atomic(self._resume_path, r)
        except OSError as e:
            self.log(f"reprise du morceau non enregistrée : {e}")

    def resume_info(self):
        """Morceau interrompu qu'on peut reprendre : {song, name, index, pos, duration, reason}, ou None
        (fichier supprime ou modifie depuis : la position ne voudrait plus rien dire)."""
        r = self._resume
        if not r:
            return None
        path = os.path.join(self.songs_folder, r["song"])
        try:
            if path not in self.songs or os.path.getmtime(path) != r.get("mtime"):
                return None
        except OSError:
            return None
        return {"song": r["song"], "name": os.path.splitext(r["song"])[0], "index": self.songs.index(path),
                "pos": float(r["pos"]), "duration": float(r.get("duration") or 0.0), "reason": r.get("reason") or ""}

    def forget_resume(self):
        self._set_resume(None)

    def resume(self):
        """Reprend le morceau interrompu dans le jeu, a l'endroit ou il s'est arrete. False si rien a reprendre."""
        info = self.resume_info()
        if not info:
            return False
        if self.state != "stopped":
            self.stop(join=True)
        self.index = info["index"]
        with self._lock:
            self._start("game", offset=info["pos"])
        return True

    def _record_stop(self, pos):
        """Fin d'une lecture solo dans le jeu : arretee avant la fin -> on retient ou ; allee au bout -> oubli."""
        if not self._cur:
            return
        path, target, solo = self._cur
        if target != "game" or not solo:
            return
        song = os.path.basename(path)
        dur = float(self.duration or 0.0)
        if self._completed or (dur and pos >= dur - 1.0):
            if self._resume and self._resume.get("song") == song:
                self._set_resume(None)
            return
        if pos < self.RESUME_MIN_POS:
            return
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        self._set_resume({"song": song, "mtime": mtime, "pos": round(pos, 3), "duration": dur,
                          "reason": self.last_stop_reason or ""})
        self.log(f"reprise possible : {song} à {pos:.1f} s")

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
                return False, i18n.t("player.unknown_instrument")
            index = ids.index(index_or_id)
        else:
            try:
                index = int(index_or_id)
            except (TypeError, ValueError):
                return False, i18n.t("player.unknown_instrument")
            if not 0 <= index < len(self.instruments):
                return False, i18n.t("player.unknown_instrument")
        if index == self.inst_index:
            return True, ""
        if self.state != "stopped":
            return False, i18n.t("player.stop_before_instrument_change")
        self._silence()
        self.inst_index = index
        self.cfg["instrument"] = self.instrument.id
        self.log(f"instrument : {self.instrument.name}")
        return True, ""

    # ---- position
    def position(self):
        if self.state == "playing":
            clock = self._clock
            if clock is not None:
                t_ref, perf_ref = clock
                return max(0.0, t_ref + (time.perf_counter() - perf_ref) * self.speed)
            return 0.0
        if self.state == "paused":
            return self._pos_at_pause
        return 0.0

    def _set_clock(self, t_ref, perf_ref=None):
        with self._clock_lock:
            self._clock = (float(t_ref), time.perf_counter() if perf_ref is None else float(perf_ref))
            self._clock_changed.clear()

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
                self._do_pause()
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
                self._do_pause()

    def _do_pause(self):
        """Sous self._lock. Memorise la position et les touches tenues, relache tout."""
        self._pos_at_pause = self.position()
        self._pause.set()
        self.state = "paused"
        self._held_at_pause = list(self._held)
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
                    with self._clock_lock:
                        self._clock = None
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
            return False, i18n.t("player.no_ready_instrument")
        index = next((i for i in ready if i > self.inst_index), ready[0])
        return self.set_instrument(index)

    def set_speed(self, value):
        if self.lock_speed:
            self.log("vitesse verrouillée à x1.00 en lecture synchronisée")
            return
        with self._clock_lock:
            # recalage de l'horloge a la position courante : la boucle de lecture relit (t_ref, perf_ref) a
            # chaque iteration, la nouvelle vitesse s'applique donc sans rafale ni silence
            now = time.perf_counter()
            clock = self._clock
            if self.state == "playing" and clock is not None:
                t_ref, perf_ref = clock
                pos = max(0.0, t_ref + (now - perf_ref) * self.speed)
                self.speed = clamp_speed(value)
                self._clock = (pos, now)
                self._clock_changed.set()
            else:
                self.speed = clamp_speed(value)
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
            if self._consume_expected(event):
                return
            if (event.name or "").lower() in self._hotkey_names() or event.event_type != "down":
                return
            self._abort_sessions("keyboard")
            return
        if self.state != "playing" or self.target != "game" or not self.cfg.get("stop_on_input", True):
            return
        if self._start_time is None or time.perf_counter() < self._start_time:
            return  # pendant le delai de depart (la touche du raccourci est encore enfoncee)
        if self._consume_expected(event):
            return
        name = (event.name or "").lower()
        if name in self._hotkey_names():
            return
        self.stop(reason="keyboard")

    def _consume_expected(self, event):
        """Vrai si l'evenement est une de nos frappes injectees (compteur decremente sous verrou : le fil de
        lecture incremente au meme moment, sans verrou un accord rapide passait pour une frappe reelle)."""
        key = (event.scan_code, event.event_type)
        with self._exp_lock:
            n = self._expected.get(key, 0)
            if n > 0:
                self._expected[key] = n - 1
                return True
        return False

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
        with self._exp_lock:
            for k in keys:
                key = (scan_code_for(k, mode), et)
                self._expected[key] = self._expected.get(key, 0) + 1

    def _game_in_front(self):
        """True / False / None : voir platform_io.game_in_front (None = aucune verification)."""
        front = platform_io.game_in_front(self.cfg.get("game_process"))
        if front is False:
            try:
                proc, title = platform_io.foreground_window()
                self.log(f"fenêtre au premier plan : {proc or '?'} « {title or ''} »")
            except Exception:  # noqa
                pass
        return front

    # ---- lecture
    def _start(self, target, deadline=None, prepared=None, offset=0.0):
        """offset : position (s) dans le morceau au depart (reprise ; salon rejoint en cours de lecture)."""
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
        self._held_at_pause = []
        with self._exp_lock:
            self._expected = {}
        self._start_time = None
        with self._clock_lock:
            self._clock = None
        if not offset:
            self.library.record_play(os.path.basename(song))
        self._cur = (song, target, deadline is None)
        self._completed = False
        self._thread = threading.Thread(target=self._run, args=(song, self.instrument, target, deadline, prepared,
                                                                max(0.0, float(offset or 0.0))), daemon=True)
        self._thread.start()

    def _abandon_start(self):
        """Sortie anticipee de _start : l'appelant (play_at du salon) a pu forcer l'etat « sync », et aucun
        fil ne viendra le remettre a l'arret. Appele avec self._lock deja pris : on ne le reprend pas."""
        if self.state != "stopped":
            self.state = "stopped"
        self._start_time = None
        self.lock_speed = False
        self._silence()

    def play_at(self, deadline, prepared, target="game", offset=0.0):
        """Mode Multi : demarre la lecture (deja preparee par prepare()) a l'instant perf_counter `deadline`,
        a la position `offset` du morceau (salon rejoint en cours de lecture)."""
        with self._lock:
            self._start(target, deadline, prepared, offset)

    def prepare(self, song, inst, target, common_key=False, extra=None, skip_tracks=None, octave=0):
        """Analyse le fichier et construit la chronologie sans jouer. common_key : tonalite commune a tous
        les joueurs (mode Multi audio, calculee ici), vitesse ignoree. extra : decalage de tonalite impose tel
        quel (salon en ligne : fixe par le chef et envoye a tous). skip_tracks : pistes ignorees a la place du
        choix du morceau (partie de l'Orchestre) ; octave : octaves ajoutees a la transposition choisie."""
        if skip_tracks is None:
            skip_tracks = self.song_skip_tracks(song)
        grouped = parse_midi(song, self.cfg, skip_tracks=skip_tracks)
        if extra is not None:
            extra = int(extra)
        elif common_key:
            from sync import choose_common_extra
            extra = choose_common_extra([n for _, ns in grouped for n, _, _ in ns])
        if getattr(inst, "percussive", False) and inst.ready:
            # instrument a frappes (conga) : la batterie du fichier, ramenee sur les pads, sans transposition
            import percussion
            drums = parse_midi(song, self.cfg, skip_tracks=skip_tracks, drums_only=True)
            events, info = percussion.fit(drums, grouped, inst)
        else:
            events, info = fit_song(grouped, inst, self.cfg, extra, self.song_arrange(song), octave)
        timeline = build_timeline(events, target, float(self.cfg.get("hold_time", 0.04)),
                                  self.cfg.get("hold_mode", "note"), float(self.cfg.get("max_hold", 4.0)),
                                  float(self.cfg.get("min_press", MIN_PRESS_DEFAULT)),
                                  float(self.cfg.get("min_gap", MIN_GAP_DEFAULT)))
        return {"song": song, "events": events, "info": info, "timeline": timeline,
                "duration": events[-1][0] if events else 0.0}

    def song_arrange(self, song):
        """Arrangement choisi pour ce morceau ('auto' | 'on' | 'off'), ou None = reglage general."""
        try:
            v = self.library.meta(os.path.basename(song)).get("arrange")
        except (TypeError, AttributeError):
            return None
        return v if v in ARRANGE_MODES else None

    def song_skip_tracks(self, song):
        """Pistes ignorees pour ce morceau (choix de l'utilisateur, dans library.json)."""
        try:
            off = self.library.meta(os.path.basename(song)).get("tracks_off") or []
            return [int(i) for i in off]
        except (TypeError, ValueError):
            return []

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

    def _run(self, song, inst, target, deadline=None, prepared=None, offset=0.0):
        """Fil de lecture. TOUT le corps est protege : une erreur d'injection ou de calcul ne doit jamais
        laisser une touche enfoncee dans le jeu ni le lecteur bloque en « playing » (le finally appelle
        _finish, qui relache les touches et remet l'etat a l'arret)."""
        try:
            self._run_body(song, inst, target, deadline, prepared, offset)
        except Exception as e:  # noqa - panne silencieuse dans un build fenetre : on journalise
            self.log(f"erreur pendant la lecture : {e!r}")
            self.last_stop_reason = self.last_stop_reason or "error"
        finally:
            self._finish()

    def _run_body(self, song, inst, target, deadline=None, prepared=None, offset=0.0):
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
            if not getattr(self._midi, "ok", True):
                # synthetiseur Windows indisponible (peripherique occupe, service audio arrete) : une ecoute
                # muette sans explication passait pour un bug
                self.log(f"sortie MIDI indisponible : {getattr(self._midi, 'error', '') or 'midiOutOpen a échoué'}")
                self._midi = None
                self.stop(reason="midi_out_unavailable")
                return
            self._midi.program(inst.gm_program)
            self._midi.volume(int(self.cfg.get("preview_volume", 100)) * 127 // 100)
        self.log(f"{'ecoute' if target == 'preview' else 'jeu'} : {os.path.basename(song)} sur {inst.name} "
                 f"(transposition {info['shift']:+d})" + (f", reprise à {offset:.1f} s" if offset else ""))
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
        if target == "game" and self._game_in_front() is False:
            # les touches partiraient dans une autre application (Discord, navigateur...)
            self.log("le jeu n'est pas au premier plan : lecture annulée")
            self.stop(reason="game_not_focused")
            return

        # horloge : position `offset` (0 sauf reprise) a l'instant de depart ; relue a chaque iteration
        # (set_speed la recale). En reprise, les evenements d'avant la position sont sautes.
        self._set_clock(offset, self._start_time)
        i = 0
        while offset and i < len(timeline) and timeline[i][0] < offset:
            i += 1
        mouse_check = 0.0
        front_check = time.perf_counter()
        while i < len(timeline) and not self._stop.is_set():
            if self._pause.is_set():
                while self._pause.is_set() and not self._stop.is_set():
                    time.sleep(0.02)
                if self._stop.is_set():
                    break
                # reprise : l'horloge repart de la position de pause, et les touches qui etaient tenues
                # (mode « note ») sont re-enfoncees, sinon la suite du morceau les croit deja appuyees
                self._set_clock(self._pos_at_pause)
                if target == "game" and self._held_at_pause:
                    keys = [k for k in self._held_at_pause]
                    self._held_at_pause = []
                    self._expect(keys, False)
                    send_keys(keys, False, mode)
                    self._held = [k for k in self._held if k not in keys] + keys
                continue
            t, _, kind, data = timeline[i]
            now = time.perf_counter()
            t_ref, perf_ref = self._clock
            target_t = perf_ref + (t - t_ref) / self.speed
            if target_t > now:
                if self._wait(target_t - now):
                    break
                continue
            if target == "game":
                try:
                    if kind == "on":
                        self._expect(data, False)
                        send_keys(data, False, mode)
                        self._held = [k for k in self._held if k not in data] + list(data)
                    else:
                        self._expect(data, True)
                        send_keys(data, True, mode)
                        self._held = [k for k in self._held if k not in data]
                except platform_io.InjectionError as e:
                    self.log(f"envoi des touches refusé : {e}")
                    self.stop(reason="injection_denied")
                    break
                if self.cfg.get("stop_on_input", True) and now - mouse_check > 0.03:
                    mouse_check = now
                    if mouse_button_down():
                        self.stop(reason="mouse")
                        break
                if now - front_check > 0.25:
                    front_check = now
                    if self._game_in_front() is False:
                        self.log("le jeu a quitté le premier plan : arrêt")
                        self.stop(reason="game_not_focused")
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
        if i >= len(timeline) and not self._stop.is_set():
            self._completed = True

    def _wait(self, seconds):
        end = time.perf_counter() + seconds
        check_mouse = self.target == "game" and self.cfg.get("stop_on_input", True)
        while True:
            if self._stop.is_set():
                return True
            if self._pause.is_set():
                return False
            if self._clock_changed.is_set() and self._clock is not None:
                # vitesse changee pendant l'attente : l'instant vise n'est plus le bon, la boucle le recalcule
                self._clock_changed.clear()
                return False
            now = time.perf_counter()
            rem = end - now
            if rem <= 0:
                return False
            if check_mouse and self._start_time is not None and now >= self._start_time and mouse_button_down():
                self.stop(reason="mouse")
                return True
            time.sleep(min(rem, 0.01))

    def _finish(self):
        try:
            self._record_stop(self.position())
        except Exception as e:  # noqa - la reprise est un confort : elle ne doit jamais bloquer l'arret
            self.log(f"reprise du morceau : {e!r}")
        self._cur = None
        self._silence()
        with self._lock:
            self.state = "stopped"
        self._start_time = None
        with self._clock_lock:
            self._clock = None
        self._held_at_pause = []
        self.lock_speed = False
        self.log("fin")

    def close(self):
        self.stop(join=True)
        if self._midi:
            self._midi.close()
            self._midi = None

