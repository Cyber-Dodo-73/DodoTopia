"""DodoTopia : instruments a frappes (conga). Ils ne jouent pas des notes mais des sons de batterie.

La piste de batterie d'un fichier MIDI (canal 10, numeros General MIDI : 36 grosse caisse, 38 caisse claire,
42 charleston...) est ramenee sur les pads de l'instrument par role. Les roles de chaque pad viennent d'une
ecoute dans le jeu (grave -> aigu). Un morceau sans batterie joue quand meme : le rythme des notes, les notes
graves sur les pads graves.

Les touches des pads sont dans la disposition de l'instrument (layouts.json) ; chaque role y est represente par
une note General MIDI (celle qu'affiche la table des touches).
"""

# role -> note General MIDI representative (cle de la disposition « conga-8 »)
ROLE_NOTE = {"kick": 36, "low_mute": 41, "low": 45, "mid": 47, "high": 50, "high_mute": 62, "snare": 38,
             "cymbal": 42}
# du plus grave au plus aigu (ecoute du 28/09/2026 : H L K J U O Y I)
ROLES_LOW_TO_HIGH = ("kick", "low_mute", "low", "mid", "high", "high_mute", "snare", "cymbal")

GM_ROLE = {
    35: "kick", 36: "kick",
    41: "low_mute", 43: "low_mute",                            # toms basses
    45: "low", 64: "low", 66: "low",                           # tom bas, conga grave, timbale grave
    47: "mid", 48: "mid", 65: "mid",                           # toms medium, timbale aigue
    50: "high", 63: "high", 61: "high", 60: "high",            # tom aigu, conga aigue ouverte, bongos
    62: "high_mute",                                           # conga aigue etouffee
    37: "snare", 38: "snare", 39: "snare", 40: "snare",        # baguette sur le cercle, caisse claire, clap
    42: "cymbal", 44: "cymbal", 46: "cymbal", 49: "cymbal", 51: "cymbal", 52: "cymbal", 53: "cymbal",
    54: "cymbal", 55: "cymbal", 56: "cymbal", 57: "cymbal", 59: "cymbal", 69: "cymbal", 70: "cymbal",
}


def role_of(note):
    """Role d'une note de batterie General MIDI (les notes rares vont au pad le plus proche en hauteur)."""
    r = GM_ROLE.get(int(note))
    if r:
        return r
    return "low" if note < 47 else ("high" if note < 60 else "cymbal")


def _pitch_roles(grouped):
    """Sans batterie : chaque note melodique va sur un pad selon sa hauteur dans le morceau (quatre zones)."""
    notes = sorted({n for _, ns in grouped for n, _, _ in ns})
    if not notes:
        return {}
    zones = ("kick", "low", "high", "snare")
    lo, hi = notes[0], notes[-1]
    span = max(1, hi - lo)
    return {n: zones[min(len(zones) - 1, (n - lo) * len(zones) // (span + 1))] for n in notes}


def fit(drums, melodic, inst):
    """(evenements, info) comme core.fit_notes, a partir de la batterie (`drums`, parse_midi drums_only) ou,
    faute de batterie, du rythme des notes (`melodic`). Aucune transposition : un pad n'a pas de hauteur."""
    keys_by_note = dict(inst.bindings)
    source, roles = drums, None
    if not any(ns for _, ns in drums):
        source, roles = melodic, _pitch_roles(melodic)
    events, dropped, total = [], 0, 0
    for t, ns in source:
        keys, played = [], []
        for n, dur, vel in ns:
            total += 1
            role = roles.get(n) if roles is not None else role_of(n)
            rep = ROLE_NOTE.get(role)
            k = keys_by_note.get(rep)
            if k is None:
                dropped += 1
                continue
            if k not in keys:
                keys.append(k)
                played.append((rep, min(float(dur), 0.1), vel))
        if keys:
            events.append((t, keys, played))
    played_n = total - dropped
    info = {"shift": 0, "folded": 0, "snapped": 0, "dropped": dropped, "dropped_poly": 0, "hits": len(events),
            "notes": total, "out_of_range": 0, "missing_accidental": 0, "exact": played_n,
            "coverage": round(100 * played_n / total) if total else 0, "arranged": None,
            "percussion": "drums" if roles is None else "rhythm"}
    return events, info
