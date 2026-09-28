"""DodoTopia : arrangeur pour les instruments a peu de touches (15 notes diatoniques, 22 notes...).

`core.fit_notes` place chaque note isolement : repli d'octave note par note (la melodie saute d'une octave
au milieu d'une phrase), accords coupes en « basse + aigus » et alterations absentes « rapprochees » vers
une fausse note. L'arrangeur prepare le morceau AVANT fit_notes pour qu'il sonne juste :

- la melodie (voix superieure suivie dans le temps) est reperee et toujours gardee ;
- la transposition est choisie en donnant trois fois plus de poids a la melodie ;
- une phrase de melodie hors registre est deplacee d'une octave ENTIERE (pas note par note) ;
- l'accompagnement est ramene sous la melodie, reduit a la polyphonie de l'instrument, et une note
  d'accompagnement sans touche juste est omise plutot que remplacee par sa voisine ;
- une note d'accompagnement qui tomberait sur la touche de la melodie au meme moment est omise.

Sortie : un `grouped` au format de parse_midi (hauteurs AVANT transposition) et la transposition a imposer a
fit_notes (`shift=`) : toutes les notes rendues tombent alors sur une touche exacte, sauf les notes de
melodie sans touche juste, rapprochees comme avant (une melodie a trous serait pire qu'une note voisine).
"""

MELODY_WEIGHT = 3
PHRASE_GAP = 0.4            # silence (s) qui separe deux phrases de melodie
UNDER_HELD = 12             # une note plus grave d'une octave sous une melodie tenue = accompagnement
DEFAULT_POLYPHONY = 4       # instrument sans polyphonie declaree : 4 notes a la fois au plus


def applies(inst, mode):
    """L'arrangement s'applique-t-il ? mode : 'auto' (instruments non chromatiques), 'on', 'off'."""
    if not getattr(inst, "offset_to_key", None):
        return False
    if mode == "on":
        return True
    if mode == "off":
        return False
    return not getattr(inst, "chromatic", False)


def melody_flags(grouped):
    """Liste parallele a grouped : pour chaque accord, l'index (dans ns) de la note de melodie, ou None.

    Voix superieure de chaque attaque, sauf quand l'attaque est nettement sous une note de melodie encore
    tenue (basse ou accord d'accompagnement joue pendant une longue note chantee)."""
    flags = []
    held_until, held_note = -1.0, None
    for t, ns in grouped:
        if not ns:
            flags.append(None)
            continue
        top = max(range(len(ns)), key=lambda i: ns[i][0])
        n, dur, _ = ns[top]
        if held_note is not None and t < held_until - 1e-3 and n <= held_note - UNDER_HELD:
            flags.append(None)
            continue
        flags.append(top)
        held_note, held_until = n, t + max(0.0, float(dur))
    return flags


def _fits(m, lo, hi, scale):
    return lo <= m <= hi and (m - lo) in scale


def choose_shift(grouped, flags, inst, cfg, extra_fixed=None):
    """Comme core.choose_shift, avec la melodie ponderee et le repli par phrase pris en compte."""
    semi = int(cfg.get("transpose_semitones", 0)) if extra_fixed is None else 0
    auto = getattr(inst, "auto", "key")
    if auto == "off" and extra_fixed is None:
        return semi
    lo, hi = inst.lowest, inst.lowest + inst.span
    scale = set(inst.scale)
    classes = {o % 12 for o in scale}
    weighted = []
    for (t, ns), f in zip(grouped, flags):
        for i, (n, _, _) in enumerate(ns):
            weighted.append((n, MELODY_WEIGHT if i == f else 1))
    if not weighted:
        return semi + int(extra_fixed or 0)
    best = None
    for oct_shift in range(-4, 5):
        if extra_fixed is not None:
            semis = [int(extra_fixed)]
        else:
            semis = range(-6, 6) if auto == "key" else [0]
        for extra in semis:
            s = semi + 12 * oct_shift + extra
            score = 0
            for n, w in weighted:
                m = n + s
                if lo <= m <= hi:
                    score += w * (2 if (m - lo) in scale else 1)
                elif (m - lo) % 12 in classes:
                    score += w          # rattrapable par un repli d'octave
            cand = (score, -abs(extra), -abs(oct_shift), s)
            if best is None or cand > best:
                best = cand
    return best[3]


def _phrases(grouped, flags):
    """Indices d'accords de melodie groupes en phrases (coupure sur un silence > PHRASE_GAP)."""
    out, cur, end = [], [], None
    for gi, ((t, ns), f) in enumerate(zip(grouped, flags)):
        if f is None:
            continue
        if cur and end is not None and t - end > PHRASE_GAP:
            out.append(cur)
            cur = []
        cur.append(gi)
        end = max(end or t, t + float(ns[f][1]))
    if cur:
        out.append(cur)
    return out


def _fold(m, lo, hi):
    while m < lo:
        m += 12
    while m > hi:
        m -= 12
    return m


def arrange(grouped, inst, cfg, extra_fixed=None, octave=0):
    """-> (grouped_arrange, shift, stats). Voir la docstring du module. `octave` : octaves ajoutees a la
    transposition choisie (partie de l'Orchestre reglee a la main par le chef)."""
    lo, hi = inst.lowest, inst.lowest + inst.span
    scale = set(inst.scale)
    flags = melody_flags(grouped)
    shift = int(choose_shift(grouped, flags, inst, cfg, extra_fixed)) + 12 * int(octave or 0)
    try:
        poly = int(getattr(inst, "polyphony", None) or 0)
    except (TypeError, ValueError):
        poly = 0
    poly = poly if poly > 0 else DEFAULT_POLYPHONY
    min_gap = float(cfg.get("min_gap", 0.012) or 0.012)

    # 1. melodie : octave choisie par phrase
    mel_pitch = {}                      # index d'accord -> hauteur jouee (apres transposition)
    phrase_moves = 0
    for ph in _phrases(grouped, flags):
        notes = [grouped[gi][1][flags[gi]][0] + shift for gi in ph]
        best, k = None, 0
        for cand_k in range(-3, 4):
            ok = sum(1 for m in notes if _fits(m + 12 * cand_k, lo, hi, scale))
            inr = sum(1 for m in notes if lo <= m + 12 * cand_k <= hi)
            cand = (ok, inr, -abs(cand_k))
            if best is None or cand > best:
                best, k = cand, cand_k
        if k:
            phrase_moves += 1
        for gi, m in zip(ph, notes):
            mel_pitch[gi] = _fold(m + 12 * k, lo, hi)   # une note encore hors registre : repli individuel

    # 2. accompagnement : sous la melodie, touches justes seulement, polyphonie respectee
    out = []
    kept = dropped_acc = dropped_poly = mel_off = 0
    recent = {}                         # hauteur jouee -> dernier instant de melodie sur cette hauteur
    for gi, (t, ns) in enumerate(grouped):
        f = flags[gi]
        mel = mel_pitch.get(gi)
        if mel is not None:
            recent[mel] = t + float(ns[f][1])
            if (mel - lo) not in scale:
                mel_off += 1
        acc = []
        for i, (n, dur, vel) in enumerate(ns):
            if i == f:
                continue
            m = _fold(n + shift, lo, hi)
            if mel is not None:
                while m > mel and m - 12 >= lo:
                    m -= 12
                if m >= mel:
                    dropped_acc += 1
                    continue
            if (m - lo) not in scale:
                dropped_acc += 1        # pas de touche juste : on omet plutot que jouer une voisine
                continue
            # meme touche que la melodie qui sonne encore (ou vient d'etre relachee) : omise
            if m in recent and t < recent[m] + min_gap:
                dropped_acc += 1
                continue
            acc.append((m, dur, vel))
        # doublons de hauteur apres repli
        seen, uniq = set(), []
        for a in sorted(acc, key=lambda x: x[0]):
            if a[0] in seen or a[0] == mel:
                dropped_acc += 1
                continue
            seen.add(a[0])
            uniq.append(a)
        room = poly - (1 if mel is not None else 0)
        if len(uniq) > room:
            # la basse d'abord, puis les notes les plus longues (tenues de l'accord)
            keep = uniq[:1] + sorted(uniq[1:], key=lambda a: -float(a[1]))[:max(0, room - 1)] if room > 0 else []
            dropped_poly += len(uniq) - len(keep)
            uniq = sorted(keep, key=lambda a: a[0])
        played = list(uniq)
        if mel is not None:
            n, dur, vel = ns[f]
            played.append((mel, dur, vel))
        if played:
            kept += len(played)
            out.append((t, [(m - shift, d, v) for m, d, v in played]))

    total = sum(len(ns) for _, ns in grouped)
    stats = {"shift": shift, "melody": len(mel_pitch), "melody_snapped": mel_off, "phrase_moves": phrase_moves,
             "dropped_accompaniment": dropped_acc, "dropped_poly": dropped_poly, "kept": kept, "notes": total}
    return out, shift, stats
