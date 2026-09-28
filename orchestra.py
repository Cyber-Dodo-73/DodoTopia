"""DodoTopia : l'Orchestre. Dans un salon, le chef répartit les pistes du fichier MIDI entre les joueurs :
le piano prend la mélodie, la basse en bois la basse, le luth l'accompagnement...

Ce module ne fait que des calculs (aucune E/S réseau) :
- `track_summary(path)` : pistes jouables du fichier avec leur tessiture (envoyées au serveur avec le morceau) ;
- `propose(tracks, seats)` : répartition automatique, la piste la plus aiguë au registre le plus aigu ;
- `part_label(...)` : libellé court d'une partie pour l'interface.

Le protocole (message `set_parts`, clé `parts` de l'état du salon) est décrit dans server/app/rooms.py.
"""
import core

MAX_TRACKS = 64


def track_summary(path):
    """[{index, name, notes, low, high, mean, drums}] des pistes qui ont des notes (index = ceux du fichier)."""
    mid = core._open_midi(path)
    out = []
    for i, track in enumerate(mid.tracks):
        name, notes, lo, hi, total = "", 0, 127, 0, 0
        channels = set()
        for msg in track:
            if msg.type == "track_name" and not name:
                name = core.clean_display_text(msg.name, 60)
            elif msg.type == "note_on" and msg.velocity > 0:
                notes += 1
                channels.add(msg.channel)
                lo, hi, total = min(lo, msg.note), max(hi, msg.note), total + msg.note
        if notes:
            out.append({"index": i, "name": name, "notes": notes, "low": lo, "high": hi,
                        "mean": round(total / notes, 1), "drums": channels <= {9}})
    return out[:MAX_TRACKS]


def seat_register(inst):
    """(bas, haut, percussif) d'un instrument résolu (instruments.Instrument) ; défaut piano si inconnu."""
    if inst is None or not getattr(inst, "offset_to_key", None):
        return 48, 84, False
    lo = int(inst.lowest)
    return lo, lo + int(inst.span), bool(getattr(inst, "percussive", False))


def _split_balanced(tracks, n):
    """Découpe `tracks` (déjà triées) en n groupes contigus aux nombres de notes équilibrés."""
    total = sum(t["notes"] for t in tracks)
    groups, cur, acc = [], [], 0
    for i, t in enumerate(tracks):
        cur.append(t)
        acc += t["notes"]
        left_groups = n - len(groups) - 1
        left_tracks = len(tracks) - i - 1
        if left_groups > 0 and (acc >= total * (len(groups) + 1) / n or left_tracks == left_groups):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    while len(groups) < n:
        groups.append([])
    return groups


def propose(tracks, seats):
    """Répartition automatique.

    tracks : track_summary() ; seats : [{"id", "low", "high", "percussive"}].
    -> {id de siège: {"tracks": [index...], "octave": None}}. Chaque piste mélodique est jouée par au moins un
    siège quand il y a assez de joueurs ; s'il y a plus de joueurs que de pistes, les pistes sont doublées par
    les joueurs de registre voisin (la mélodie d'abord)."""
    melodic = sorted((t for t in tracks if not t.get("drums") and t.get("notes")),
                     key=lambda t: -(t.get("mean") if t.get("mean") is not None else 60))
    drums = [t["index"] for t in tracks if t.get("drums") and t.get("notes")]
    pitched = sorted((s for s in seats if not s.get("percussive")),
                     key=lambda s: -((s.get("low", 48) + s.get("high", 84)) / 2.0))
    perc = [s for s in seats if s.get("percussive")]
    out = {}
    if melodic and pitched:
        S, T = len(pitched), len(melodic)
        if S >= T:
            for j, s in enumerate(pitched):
                k = round(j * (T - 1) / (S - 1)) if S > 1 else 0
                out[s["id"]] = {"tracks": [melodic[k]["index"]], "octave": None}
        else:
            for s, group in zip(pitched, _split_balanced(melodic, S)):
                out[s["id"]] = {"tracks": sorted(t["index"] for t in group), "octave": None}
    for s in perc:
        chosen = drums or ([melodic[-1]["index"]] if melodic else [])
        out[s["id"]] = {"tracks": sorted(chosen), "octave": None}
    if not melodic and not drums:
        return {}
    for s in pitched:
        out.setdefault(s["id"], {"tracks": [t["index"] for t in melodic] or drums, "octave": None})
    return out


def part_label(tracks, part, fallback="Piste {n}"):
    """« Mélodie + Basse » : noms des pistes d'une partie (repli : « Piste 3 »)."""
    if not part:
        return ""
    names = {t["index"]: (t.get("name") or "").strip() for t in tracks or []}
    labels = [names.get(i) or fallback.format(n=i + 1) for i in part.get("tracks") or []]
    return " + ".join(labels)
