# -*- coding: utf-8 -*-
"""Mes créations : les musiques qu'Heartopia enregistre sur cet ordinateur (dossier `record`, à côté de
ScreenCapture).

    …/LocalLow/xd/Heartopia/record/<joueur>/<nom>_<aaaammjjHHMMSSmmm>_<durée en ms>.bin    enregistrements du joueur
    …/LocalLow/xd/Heartopia/record/<joueur>/remote/…                                        ceux des autres (cache)

Format relevé le 2026-10-03 sur 24 fichiers (non chiffré, petit-boutiste) :
    en-tête   « DCER » · u16 version (1) · u32 nombre d'événements
    événement u32 rang (à partir de 1) · f32 instant (s) · u64 numéro du joueur · u8 instrument · u8 1 = touche
              enfoncée / 0 = relâchée · u32 touche · f32 valeur propre au joueur et à la séance (sens inconnu,
              recopiée telle quelle)
    fin       f32 durée totale (= instant du dernier événement)
Numéros d'instrument et de touches : table `GAME_INSTRUMENTS`, lue le 2026-10-03 dans les données du jeu (table
des types d'instrument du fichier de configuration « oversea »). Piano et harpe : 22 touches blanches à la suite
puis 15 noires ; les autres : 15 ou 8 touches à la suite. Recoupé avec les enregistrements réels et à l'écoute
par le propriétaire pour le piano, la harpe, le luth, la flûte à bec, la lyre, le concertina et le xylophone.

Dépendances : mido (export / import MIDI), core.parse_midi pour lire un MIDI comme le lecteur."""
import collections
import glob
import hashlib
import os
import re
import struct
import time

MAGIC = b"DCER"
VERSION = 1
HEADER = struct.Struct("<4sHI")
EVENT = struct.Struct("<IfQBBIf")
MAX_FILE_BYTES = 16 * 1024 * 1024
NAME_MAX = 24                 # le jeu coupe les titres à 24 caractères dans le nom du fichier
PIANO = 1                     # numéro d'instrument du piano dans les enregistrements
PIANO_LOW, PIANO_HIGH = 48, 84

_WHITE = [0, 2, 4, 5, 7, 9, 11]
_BLACK = [1, 3, 6, 8, 10]
PIANO_WHITE = [48 + 12 * o + s for o in range(3) for s in _WHITE] + [84]      # 10001…10022
PIANO_BLACK = [48 + 12 * o + s for o in range(3) for s in _BLACK]             # 10201…10215
_MIDI_TO_PIANO = {m: 10001 + i for i, m in enumerate(PIANO_WHITE)}
_MIDI_TO_PIANO.update({m: 10201 + i for i, m in enumerate(PIANO_BLACK)})
DIATONIC = [60 + 12 * o + s for o in range(3) for s in _WHITE]                # Do4 et au-dessus, gamme de do



def _white_then_black(white, black, notes=37, low=48):
    """Touches d'un clavier à 37 notes dans l'ordre des hauteurs : les blanches sont numérotées à partir de
    `white`, les noires à partir de `black`."""
    w = k = 0
    out = []
    for m in range(low, low + notes):
        if m % 12 in _BLACK:
            out.append(black + k)
            k += 1
        else:
            out.append(white + w)
            w += 1
    return out


def _row(first, count=15):
    return list(range(first, first + count))


# (numéro d'instrument du jeu, identifiant du catalogue DodoTopia, touches de la plus grave à la plus aiguë)
GAME_INSTRUMENTS = (
    (1, "piano", _white_then_black(10001, 10201)),
    (2, "conga", _row(10031, 8)),
    (3, "cajon", _row(10111, 8)),
    (4, "xylophone", _row(10119, 8)),
    (5, "steel-tongue-drum", _row(11161)),
    (6, "harp", _white_then_black(11201, 11223)),
    (11, "lute", _row(11001)),
    (12, "wooden-bass", _row(10051)),
    (13, "recorder", _row(10071)),
    (14, "concertina", _row(10086)),
    (15, "xiao", _row(11051)),
    (16, "mbira", _row(11071)),
    (17, "lyre", _row(11086)),
    (18, "bagpipe", _row(11101)),
    (19, "cello", _row(11121)),
    (20, "violin", _row(11141)),
    (21, "saxophone", _row(11176)),
    (22, "conch", _row(11251, 8)),
    (23, "ocarina", _row(11261)),
)
_TABLE = None


def game_table():
    """{identifiant du catalogue: {"type", "keys", "midis", "program", "name"}} pour les instruments dont la
    disposition par défaut de DodoTopia a autant de notes que l'instrument du jeu (les notes viennent de cette
    disposition, dans l'ordre des hauteurs). Calculé une fois ; {} si le catalogue est illisible."""
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    table = {}
    try:
        import instruments
        cat = instruments.load_catalogue()
        types = {t.id: t for t in cat.types}
        for kind, cat_id, keys in GAME_INSTRUMENTS:
            t = types.get(cat_id)
            layout = cat.layouts.get(t.default_layout_id) if t is not None and t.default_layout_id else None
            if layout is None:
                continue
            midis = sorted(layout.bindings())
            if len(midis) != len(keys):
                continue            # ex. cajón : 8 pads dans le jeu, pas de disposition équivalente ici
            table[cat_id] = {"type": kind, "keys": list(keys), "midis": midis, "program": int(t.preview_program or 0),
                             "name": t.label_en or t.label_fr, "percussive": bool(t.percussive)}
    except Exception:  # noqa - catalogue absent : on garde le piano en dur (key_to_midi)
        table = {}
    _TABLE = table
    return table


def _key_notes():
    """{touche du jeu: (note MIDI, identifiant du catalogue)}."""
    out = {}
    for cat_id, t in game_table().items():
        for key, midi in zip(t["keys"], t["midis"]):
            out[key] = (midi, cat_id)
    return out


_NAME = re.compile(r"^(?P<name>.*)_(?P<stamp>\d{17})_(?P<ms>\d{1,9})\.bin$", re.IGNORECASE)


class MusicError(Exception):
    """Erreur lisible : fichier illisible, format inconnu, MIDI sans note…"""


# ---------------------------------------------------------------- dossiers
def root_of(screen_capture):
    """Dossier `record` voisin de ScreenCapture, ou None."""
    if not screen_capture:
        return None
    d = os.path.join(os.path.dirname(os.path.abspath(screen_capture)), "record")
    return d if os.path.isdir(d) else None


def player_dirs(root):
    try:
        return sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    except OSError:
        return []


def my_uid(screen_capture):
    """Numéro (u64) de CE joueur : le jeu le met dans le nom de `phone_call_record_<numéro>.txt`."""
    if not screen_capture:
        return None
    base = os.path.dirname(os.path.abspath(screen_capture))
    best = None
    for p in glob.glob(os.path.join(base, "phone_call_record_*.txt")):
        m = re.search(r"phone_call_record_(\d+)\.txt$", p)
        if m and (best is None or os.path.getmtime(p) > best[0]):
            best = (os.path.getmtime(p), int(m.group(1)))
    return best[1] if best else None


# ---------------------------------------------------------------- noms de fichiers
def parse_name(filename):
    """{name, created (epoch ou None), ms} d'après le nom, ou None si ce n'est pas un enregistrement."""
    m = _NAME.match(filename)
    if not m:
        return None
    stamp = m.group("stamp")
    try:
        created = time.mktime(time.strptime(stamp[:14], "%Y%m%d%H%M%S")) + int(stamp[14:]) / 1000.0
    except (ValueError, OverflowError):
        created = None
    return {"name": m.group("name").strip() or m.group("name"), "created": created, "ms": int(m.group("ms"))}


def safe_title(text):
    """Titre accepté dans un nom de fichier du jeu : lettres, chiffres, espaces, 24 caractères au plus."""
    s = "".join(c if (c.isalnum() or c in " -'") else " " for c in str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()[:NAME_MAX].strip()
    return s or "DodoTopia"


def file_name(title, duration, now=None):
    now = time.time() if now is None else now
    stamp = time.strftime("%Y%m%d%H%M%S", time.localtime(now)) + f"{int((now % 1) * 1000):03d}"
    return f"{safe_title(title)}_{stamp}_{int(round(duration * 1000))}.bin"


# ---------------------------------------------------------------- lecture / écriture du format
def event_count(path):
    """Nombre d'événements annoncé par l'en-tête (lecture de 10 octets), ou None."""
    try:
        with open(path, "rb") as f:
            head = f.read(HEADER.size)
        magic, _, n = HEADER.unpack(head)
        return n if magic == MAGIC else None
    except (OSError, struct.error):
        return None


def parse(data):
    """Octets -> {events: [(t, joueur, instrument, enfoncée, touche, valeur)], duration}."""
    if len(data) < HEADER.size or data[:4] != MAGIC:
        raise MusicError("ce n'est pas un enregistrement d'Heartopia")
    _, version, n = HEADER.unpack_from(data, 0)
    if version != VERSION:
        raise MusicError(f"version d'enregistrement inconnue ({version})")
    if HEADER.size + n * EVENT.size > len(data):
        raise MusicError("enregistrement tronqué")
    events = []
    for i in range(n):
        _, t, uid, inst, down, key, extra = EVENT.unpack_from(data, HEADER.size + i * EVENT.size)
        events.append((t, uid, inst, 1 if down else 0, key, extra))
    end = HEADER.size + n * EVENT.size
    duration = struct.unpack_from("<f", data, end)[0] if len(data) >= end + 4 else (events[-1][0] if events else 0.0)
    return {"events": events, "duration": float(duration)}


def read(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise MusicError("fichier trop gros")
        with open(path, "rb") as f:
            return parse(f.read())
    except OSError as e:
        raise MusicError(str(e)) from e


def build(events):
    """[(t, joueur, instrument, enfoncée, touche, valeur)] -> octets du fichier (durée = dernier instant)."""
    out = [HEADER.pack(MAGIC, VERSION, len(events))]
    for i, (t, uid, inst, down, key, extra) in enumerate(events):
        out.append(EVENT.pack(i + 1, float(t), int(uid), int(inst), 1 if down else 0, int(key), float(extra)))
    out.append(struct.pack("<f", float(events[-1][0]) if events else 0.0))
    return b"".join(out)


# ---------------------------------------------------------------- touches <-> notes
def key_to_midi(key, low_key=None):
    """Note MIDI d'une touche du jeu d'après la table des instruments ; pour une touche hors table, gamme de do
    à partir de la touche la plus grave rencontrée (`low_key`), approximation."""
    hit = _key_notes().get(key)
    if hit is not None:
        return hit[0]
    if 10001 <= key <= 10022:
        return PIANO_WHITE[key - 10001]
    if 10201 <= key <= 10215:
        return PIANO_BLACK[key - 10201]
    i = key - (low_key if low_key is not None else key)
    if 0 <= i < len(DIATONIC):
        return DIATONIC[i]
    return max(0, min(127, 60 + i))


def summary(rec):
    """{notes, duration, players, instruments} d'un enregistrement lu."""
    ev = rec["events"]
    return {"notes": sum(1 for e in ev if e[3]), "duration": rec["duration"],
            "players": len({e[1] for e in ev}), "instruments": sorted({e[2] for e in ev})}


def to_midi(rec, dest):
    """Écrit l'enregistrement en fichier MIDI : une piste par (joueur, instrument)."""
    import mido
    tpb, tempo = 480, 500000                       # 120 à la noire : 960 tics par seconde
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
    groups = collections.OrderedDict()
    for e in rec["events"]:
        groups.setdefault((e[1], e[2]), []).append(e)
    channels = [c for c in range(16) if c != 9]
    for n, ((uid, inst), evs) in enumerate(groups.items()):
        track = mido.MidiTrack()
        mid.tracks.append(track)
        if n == 0:
            track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
        # nom et timbre de la piste d'après l'instrument du jeu (reconnu à ses touches)
        notes_of = _key_notes()
        ids = collections.Counter(notes_of[e[4]][1] for e in evs if e[4] in notes_of)
        info = game_table().get(ids.most_common(1)[0][0]) if ids else None
        track.append(mido.MetaMessage("track_name", name=info["name"] if info else f"Heartopia {inst}", time=0))
        percussion = bool(info and info["percussive"])
        ch = 9 if percussion else channels[n % len(channels)]
        if info and not percussion:
            track.append(mido.Message("program_change", program=max(0, min(127, info["program"])), channel=ch, time=0))
        low = None if inst == PIANO else min(e[4] for e in evs)
        last, held = 0, set()
        for t, _, _, down, key, _ in evs:
            note = key_to_midi(key, low)
            tick = max(last, int(round(t * 2 * tpb)))
            if down and note in held:              # deux touches rendues par la même note : on relance
                track.append(mido.Message("note_off", note=note, velocity=0, channel=ch, time=tick - last))
                last = tick
            if not down and note not in held:
                continue
            track.append(mido.Message("note_on" if down else "note_off", note=note, velocity=80 if down else 0,
                                      channel=ch, time=tick - last))
            last = tick
            (held.add if down else held.discard)(note)
        for note in sorted(held):
            track.append(mido.Message("note_off", note=note, velocity=0, channel=ch, time=0))
    try:
        mid.save(dest)
    except OSError as e:
        raise MusicError(str(e)) from e
    return dest


def _fit_piano(notes):
    """Décalage d'octaves qui garde le plus de notes dans Do3-Do6 ; le reste est replié octave par octave."""
    best, best_n = 0, -1
    for k in range(-4, 5):
        n = sum(1 for m in notes if PIANO_LOW <= m + 12 * k <= PIANO_HIGH)
        if n > best_n or (n == best_n and abs(k) < abs(best)):
            best, best_n = k, n
    return best


def from_midi(path, cfg, uid, extra=1.0):
    """Fichier MIDI -> événements de piano du jeu (lecture identique au lecteur : core.parse_midi)."""
    import core
    try:
        grouped = core.parse_midi(path, cfg or {})
    except ValueError as e:                         # MidiRefused
        raise MusicError(str(e)) from e
    flat = [(t, n, d) for t, chord in grouped for (n, d, _v) in chord]
    if not flat:
        raise MusicError("aucune note dans ce fichier MIDI")
    shift = 12 * _fit_piano([n for _, n, _ in flat])
    t0 = flat[0][0]
    presses = []                                    # (début, fin, touche)
    for t, n, d in flat:
        m = n + shift
        while m < PIANO_LOW:
            m += 12
        while m > PIANO_HIGH:
            m -= 12
        presses.append((t - t0, t - t0 + max(0.05, d), _MIDI_TO_PIANO[m]))
    presses.sort()
    # une touche rejouée avant d'être relâchée : la première tenue s'arrête juste avant la seconde frappe
    last_of = {}
    for i, (a, b, key) in enumerate(presses):
        j = last_of.get(key)
        if j is not None:
            pa, pb, _ = presses[j]
            if pa == a:
                presses[i] = None                  # même touche au même instant : doublon
                continue
            if pb > a - 0.02:
                presses[j] = (pa, max(pa + 0.01, a - 0.02), key)
        last_of[key] = i
    events = []
    for p in presses:
        if p is None:
            continue
        a, b, key = p
        events.append((a, 1, key))
        events.append((b, 0, key))
    events.sort(key=lambda e: (e[0], e[1]))         # au même instant : relâchements avant frappes
    return [(t, int(uid or 0), PIANO, down, key, float(extra)) for t, down, key in events]


def reference_values(paths, uid=None):
    """(numéro du joueur, valeur f32) à recopier dans un nouvel enregistrement, d'après les plus récents des
    fichiers `paths` : le joueur `uid` s'il est connu, sinon le plus présent ; sa valeur au piano de préférence."""
    fallback = None
    for p in sorted(paths, key=lambda q: -os.path.getmtime(q) if os.path.exists(q) else 0)[:8]:
        try:
            ev = read(p)["events"]
        except MusicError:
            continue
        if not ev:
            continue
        who = uid if uid and any(e[1] == uid for e in ev) else collections.Counter(e[1] for e in ev).most_common(1)[0][0]
        mine = [e for e in ev if e[1] == who]
        piano = [e for e in mine if e[2] == PIANO]
        if piano:
            return who, piano[0][5]
        if fallback is None:
            fallback = (who, mine[0][5])
    return fallback or (uid, 1.0)


# ---------------------------------------------------------------- liste
def _item_id(rel):
    return "m" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:15]


def scan(root, my_id=None):
    """Enregistrements du dossier `record` : une entrée par fichier. Mêmes champs que creations.scan pour ce
    qui est commun (id, base, cat, mine, created, modified, variants…), plus name, duration, notes, remote,
    section (« music » = enregistré par ce joueur, « cache » = téléchargé d'un autre)."""
    items = []
    players = player_dirs(root) if root else []
    for player in players:
        for sub, remote in (("", False), ("remote", True)):
            d = os.path.join(root, player, sub) if sub else os.path.join(root, player)
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for name in names:
                info = parse_name(name)
                path = os.path.join(d, name)
                if info is None or not os.path.isfile(path):
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                mine = (not remote) and (player == my_id if my_id else len(players) == 1)
                folder = "/".join(x for x in ("record", player, sub) if x)
                n = event_count(path)
                items.append({
                    "id": _item_id(folder + "/" + name), "base": name, "kind": "Record", "cat": "music",
                    "section": "music" if mine else "cache", "player": player, "mine": True if mine else (False if remote else None),
                    "created": info["created"], "modified": st.st_mtime, "w": 0, "h": 0, "indexed": False,
                    "name": info["name"], "duration": info["ms"] / 1000.0, "notes": (n or 0) // 2, "remote": remote,
                    "path": path, "largest": path, "thumb": None,
                    "variants": [{"path": path, "folder": folder, "name": name, "w": 0, "h": 0, "ext": ".bin",
                                  "bytes": st.st_size, "mtime": st.st_mtime}]})
    return items


def signature(root):
    sig = []
    for player in (player_dirs(root) if root else []):
        for d in (os.path.join(root, player), os.path.join(root, player, "remote")):
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.name.lower().endswith(".bin"):
                            st = e.stat()
                            sig.append((d, e.name, st.st_size, int(st.st_mtime)))
            except OSError:
                continue
    sig.sort()
    return hashlib.sha1(repr(sig).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- remplacement, ajout, export
def render_source(src_path, cfg, uid, extra):
    """Octets d'enregistrement à partir de `src_path` : un .bin du jeu (vérifié, recopié) ou un fichier MIDI
    (converti pour le piano). Renvoie (octets, durée en secondes)."""
    if not os.path.isfile(src_path):
        raise MusicError("fichier source introuvable")
    with open(src_path, "rb") as f:
        head = f.read(4)
    if head == MAGIC:
        rec = read(src_path)
        return build(rec["events"]), (rec["events"][-1][0] if rec["events"] else 0.0)
    events = from_midi(src_path, cfg, uid, extra)
    return build(events), events[-1][0]
