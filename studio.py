# -*- coding: utf-8 -*-
"""Studio : fabriquer un enregistrement d'Heartopia à plusieurs instruments à partir d'un fichier MIDI.

Chaque piste retenue reçoit un instrument et une octave ; toutes gardent la même tonalité (le décalage commun
de `sync.choose_common_extra`, comme en salon), puis chaque piste est ramenée sur les notes de son instrument
par `core.fit_notes`, le même code que la lecture dans le jeu. Le résultat est une suite d'événements au
format de `game_music` (touche enfoncée / relâchée, numéro d'instrument du jeu, numéro de touche du jeu).

Les numéros du jeu ne sont connus d'avance que pour le piano. Les autres instruments s'« apprennent » :
`learn()` lit un enregistrement fait dans le jeu où toutes les touches d'un instrument ont été jouées, et en tire
son numéro et la liste de ses touches, de la plus grave à la plus aiguë (hypothèse : le jeu numérote les touches
dans l'ordre des hauteurs, comme pour les touches blanches du piano). Les tables apprises vivent dans
`cfg["creations"]["game_instruments"]` : {identifiant du catalogue: {"type", "keys", "extra"}}.

NON VÉRIFIÉ dans le jeu au 2026-10-03 : qu'Heartopia rejoue un enregistrement où UN joueur tient plusieurs
instruments à la fois. Les duos enregistrés dans le jeu ont deux joueurs, un instrument chacun."""
import collections

import core
import game_music
import orchestra

PIANO_ID = "piano"
OCTAVES = (-2, -1, 0, 1, 2)
MAX_PARTS = 16


class StudioError(Exception):
    """Erreur lisible : instrument non appris, piste absente, aucune note jouable…"""


# ---------------------------------------------------------------- tables des instruments du jeu
def learned_tables(cfg):
    node = cfg.get("creations") if isinstance(cfg.get("creations"), dict) else {}
    tables = node.get("game_instruments") if isinstance(node.get("game_instruments"), dict) else {}
    out = {}
    for inst_id, t in tables.items():
        try:
            keys = [int(k) for k in t["keys"]]
            out[str(inst_id)] = {"type": int(t["type"]), "keys": keys, "extra": float(t.get("extra") or 0.0)}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def is_available(inst, tables):
    """Vrai si on sait écrire cet instrument dans un enregistrement du jeu."""
    if inst is None or not inst.bindings or getattr(inst, "percussive", False):
        return False
    if game_key_map(inst, tables, strict=False):
        return True
    return False


def game_key_map(inst, tables, strict=True):
    """{note MIDI de l'instrument: (numéro d'instrument du jeu, numéro de touche du jeu)}."""
    notes = sorted(inst.bindings)
    t = tables.get(inst.id)
    if t is not None:
        if len(t["keys"]) != len(notes):
            if strict:
                raise StudioError(f"{inst.name} : {len(t['keys'])} touches apprises pour {len(notes)} notes")
            return {}
        return {m: (t["type"], k) for m, k in zip(notes, t["keys"])}
    # Piano et instruments de sa famille non appris : les touches du piano du jeu, relevées (game_music).
    if inst.id == PIANO_ID and all(m in game_music._MIDI_TO_PIANO for m in notes):
        return {m: (game_music.PIANO, game_music._MIDI_TO_PIANO[m]) for m in notes}
    if strict:
        raise StudioError(f"{inst.name} : instrument pas encore appris")
    return {}


def learn(record_path, inst, uid=None):
    """Table {"type", "keys", "extra"} de `inst` d'après un enregistrement du jeu où toutes ses touches ont été
    jouées. On retient le joueur `uid` s'il y figure (sinon le plus présent) et, chez lui, l'instrument le plus
    joué. Lève StudioError si le nombre de touches jouées n'est pas celui de l'instrument."""
    try:
        events = game_music.read(record_path)["events"]
    except game_music.MusicError as e:
        raise StudioError(str(e)) from e
    if not events:
        raise StudioError("enregistrement vide")
    players = collections.Counter(e[1] for e in events)
    who = uid if uid in players else players.most_common(1)[0][0]
    mine = [e for e in events if e[1] == who]
    kind = collections.Counter(e[2] for e in mine if e[3]).most_common(1)[0][0]
    keys = sorted({e[4] for e in mine if e[2] == kind})
    wanted = len(inst.bindings)
    if not wanted:
        raise StudioError(f"{inst.name} n'a pas de touches connues dans DodoTopia")
    if len(keys) < wanted and keys and keys[-1] - keys[0] + 1 == wanted:
        # Le jeu numérote les touches d'un instrument à la suite (relevé : 10071-10085, 11086-11100) : si la plus
        # grave et la plus aiguë ont été jouées, celles qui manquent entre les deux se déduisent.
        keys = list(range(keys[0], keys[-1] + 1))
    if len(keys) != wanted:
        raise StudioError(f"{len(keys)} touches jouées dans cet enregistrement, {wanted} attendues pour {inst.name} "
                          "(joue au moins la plus grave et la plus aiguë)")
    extra = next(e[5] for e in mine if e[2] == kind)
    return {"type": int(kind), "keys": keys, "extra": float(extra)}


# ---------------------------------------------------------------- pistes
def tracks(path):
    """Pistes du MIDI qui ont des notes : [{index, name, notes, low, high, mean, drums}]."""
    try:
        return orchestra.track_summary(path)
    except ValueError as e:                     # MidiRefused
        raise StudioError(str(e)) from e


def suggest(track_list):
    """Répartition de départ : chaque piste mélodique au piano, la batterie laissée de côté."""
    return [{"track": t["index"], "instrument": PIANO_ID, "octave": 0, "on": not t["drums"]} for t in track_list]


# ---------------------------------------------------------------- fabrication
def _track_notes(path, cfg, index, all_indices):
    others = [i for i in all_indices if i != index]
    return core.parse_midi(path, cfg, skip_tracks=others)


def build(path, cfg, parts, instruments, tables, uid, extra_default=1.0):
    """Événements du jeu pour `parts` = [{"track", "instrument", "octave"}] (pistes retenues seulement).
    `instruments` : {identifiant: objet Instrument de core}. Renvoie (événements, rapport) ; le rapport donne,
    par piste, la part de notes jouées à leur hauteur exacte, et la durée totale."""
    import sync
    if not parts:
        raise StudioError("aucune piste retenue")
    if len(parts) > MAX_PARTS:
        raise StudioError(f"trop de pistes ({len(parts)}, {MAX_PARTS} au plus)")
    listing = tracks(path)
    all_indices = [t["index"] for t in listing]
    try:
        import mido
        all_indices = list(range(len(mido.MidiFile(path).tracks)))
    except Exception:  # noqa - la liste des pistes à notes suffit alors
        pass
    known = {t["index"] for t in listing}
    grouped_of = {}
    for part in parts:
        index = int(part["track"])
        if index not in known:
            raise StudioError(f"piste {index + 1} introuvable dans ce fichier")
        try:
            grouped_of[index] = _track_notes(path, cfg, index, all_indices)
        except ValueError as e:
            raise StudioError(str(e)) from e
    every = [n for g in grouped_of.values() for _, ns in g for n, _, _ in ns]
    if not every:
        raise StudioError("aucune note dans les pistes retenues")
    extra = sync.choose_common_extra(every)     # la même tonalité pour toutes les pistes

    presses, report = [], []
    for part in parts:
        index = int(part["track"])
        inst = instruments.get(str(part.get("instrument") or ""))
        if inst is None:
            raise StudioError(f"instrument inconnu : {part.get('instrument')}")
        keymap = game_key_map(inst, tables)
        grouped = grouped_of[index]
        notes = [n for _, ns in grouped for n, _, _ in ns]
        octave = max(OCTAVES[0], min(OCTAVES[-1], int(part.get("octave") or 0)))
        shift = core.choose_shift(notes, inst, cfg, extra) + 12 * octave
        fitted, info = core.fit_notes(grouped, inst, cfg, extra_fixed=extra, shift=shift)
        table = tables.get(inst.id) or {}
        value = float(table.get("extra") or extra_default)
        for t, _keys, played in fitted:
            for note, dur, _vel in played:
                kind, key = keymap[note]
                presses.append((t, t + max(0.05, dur), kind, key, value))
        report.append({"track": index, "instrument": inst.id, "octave": octave, "notes": info.get("notes", 0),
                       "played": sum(len(p) for _, _, p in fitted), "coverage": info.get("coverage", 0)})
    if not presses:
        raise StudioError("aucune note jouable avec ces instruments")
    events = presses_to_events(presses, uid)
    return events, {"parts": report, "duration": events[-1][0], "shift": extra,
                    "instruments": sorted({e[2] for e in events})}


def presses_to_events(presses, uid):
    """[(début, fin, instrument, touche, valeur)] -> événements du jeu triés, ramenés à zéro. Une touche rejouée
    avant d'être relâchée : la première tenue s'arrête juste avant la seconde frappe."""
    presses = sorted(presses)
    t0 = presses[0][0]
    last_of = {}
    kept = []
    for a, b, kind, key, value in presses:
        a, b = a - t0, b - t0
        slot = (kind, key)
        j = last_of.get(slot)
        if j is not None:
            pa, pb = kept[j][0], kept[j][1]
            if pa == a:
                continue                         # même touche au même instant : doublon
            if pb > a - 0.02:
                kept[j] = (pa, max(pa + 0.01, a - 0.02)) + kept[j][2:]
        last_of[slot] = len(kept)
        kept.append((a, b, kind, key, value))
    flat = []
    for a, b, kind, key, value in kept:
        flat.append((a, 1, kind, key, value))
        flat.append((b, 0, kind, key, value))
    flat.sort(key=lambda e: (e[0], e[1]))        # au même instant : relâchements avant frappes
    return [(t, int(uid or 0), kind, down, key, value) for t, down, kind, key, value in flat]
