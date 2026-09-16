# -*- coding: utf-8 -*-
"""Dessin dans Heartopia : calibrage (canevas, palette, outils) et peinture case par case a la souris."""
import threading
import time

from bot import MouseBot, screen_changed, screen_fingerprint
from platform_io import cursor_pos, mouse_move, mouse_down, mouse_up, grab, mouse_hint, SCREEN_OK  # noqa: F401

FORMATS = ["16:9", "4:3", "1:1", "3:4", "9:16"]
# Nombre de cases (largeur x hauteur) a la finesse maximale, par format. Ecrase par le calibrage
# quand la grille du jeu est visible.
DEFAULT_GRIDS = {"16:9": [140, 84], "4:3": [150, 114], "1:1": [150, 150], "3:4": [114, 150], "9:16": [84, 150]}
# Palette du jeu (2 colonnes x 8 lignes, lue de gauche a droite puis de haut en bas).
# Valeurs approximatives, remplacees par la capture d'ecran au calibrage.
DEFAULT_PALETTE = [
    [27, 43, 43], [255, 255, 255],
    [138, 138, 138], [242, 236, 228],
    [242, 109, 125], [242, 105, 75],
    [247, 162, 51], [244, 208, 63],
    [168, 201, 58], [92, 184, 92],
    [63, 184, 168], [58, 166, 184],
    [59, 138, 217], [74, 107, 216],
    [168, 108, 217], [217, 95, 184],
]
PALETTE_COLS, PALETTE_ROWS = 2, 8
# Nuances du jeu : un clic sur une pastille de la palette ouvre 10 nuances (6 pour le noir/gris) en 2 colonnes x 5 lignes.
# (famille = index de la pastille dans la palette principale, nuances lues de gauche a droite puis de haut en bas)
SHADE_FAMILIES = [
    (0, [[5, 22, 22], [65, 69, 69], [128, 130, 130], [190, 191, 191], [254, 255, 255], [249, 246, 236]]),
    (4, [[207, 53, 77], [238, 111, 114], [166, 38, 61], [245, 172, 166], [201, 132, 131], [163, 93, 94], [105, 49, 59], [231, 213, 213], [192, 172, 171], [117, 94, 94]]),
    (5, [[233, 94, 43], [249, 131, 88], [171, 66, 38], [254, 186, 159], [217, 147, 124], [175, 108, 88], [117, 59, 49], [233, 213, 208], [193, 172, 166], [117, 94, 89]]),
    (6, [[244, 158, 22], [254, 174, 59], [177, 111, 22], [254, 206, 146], [218, 167, 109], [179, 129, 75], [121, 81, 38], [245, 228, 206], [205, 188, 169], [128, 111, 94]]),
    (7, [[237, 202, 22], [249, 216, 56], [179, 148, 22], [250, 231, 145], [211, 190, 111], [171, 149, 75], [117, 99, 38], [238, 231, 199], [198, 191, 162], [120, 114, 89]]),
    (8, [[168, 188, 22], [182, 201, 49], [117, 134, 22], [216, 223, 147], [173, 183, 109], [133, 145, 75], [83, 94, 43], [230, 233, 199], [188, 194, 163], [110, 116, 93]]),
    (9, [[5, 162, 93], [65, 185, 123], [5, 116, 71], [156, 218, 173], [118, 178, 139], [79, 137, 105], [36, 86, 64], [195, 224, 204], [157, 183, 166], [83, 105, 93]]),
    (10, [[5, 135, 129], [5, 171, 160], [5, 105, 102], [126, 205, 194], [85, 164, 156], [43, 126, 120], [5, 75, 75], [190, 224, 218], [152, 183, 178], [78, 107, 102]]),
    (11, [[5, 114, 156], [5, 153, 186], [5, 88, 120], [121, 187, 202], [81, 147, 165], [36, 109, 127], [5, 73, 91], [198, 221, 226], [158, 181, 186], [79, 103, 111]]),
    (12, [[5, 94, 166], [43, 131, 193], [5, 71, 130], [131, 168, 201], [93, 128, 161], [54, 91, 127], [25, 59, 86], [193, 205, 213], [155, 166, 176], [76, 89, 103]]),
    (13, [[83, 77, 161], [117, 119, 189], [62, 56, 126], [162, 160, 199], [120, 122, 161], [85, 86, 126], [51, 53, 85], [201, 202, 213], [162, 163, 176], [86, 88, 105]]),
    (14, [[129, 61, 139], [161, 103, 169], [96, 43, 108], [184, 155, 185], [144, 115, 149], [108, 77, 115], [67, 46, 75], [207, 201, 209], [171, 161, 172], [96, 86, 101]]),
    (15, [[173, 53, 111], [207, 107, 143], [134, 38, 88], [217, 161, 180], [180, 122, 140], [139, 83, 103], [96, 53, 75], [228, 213, 218], [188, 173, 177], [114, 94, 102]]),
]
SHADE_COLS, SHADE_ROWS = 2, 5
# liste plate des nuances : SHADES[k] = (famille, index de la nuance dans sa famille, rgb)
SHADES = [(fam, j, list(c)) for fam, cs in SHADE_FAMILIES for j, c in enumerate(cs)]
# pastille de la palette principale equivalente a chaque nuance (-1 : aucune). Les pastilles blanc, gris
# et creme de la palette principale sont des nuances de la famille du noir.
_MAIN_OF = {(0, 0): 0, (0, 4): 1, (0, 2): 2, (0, 5): 3}
_MAIN_OF.update({(fam, 1): fam for fam, _ in SHADE_FAMILIES if fam != 0})
SHADE_MAIN = [_MAIN_OF.get((fam, j), -1) for fam, j, _ in SHADES]
# pages de nuances, dans l'ordre de la bande « precedent / suivant » du jeu : noir, rouge, orange, ... rose
PAGES = [fam for fam, _ in SHADE_FAMILIES]

DEFAULT_DRAW = {
    "palette": {"pos0": None, "pos1": None, "cols": PALETTE_COLS, "rows": PALETTE_ROWS, "colors": DEFAULT_PALETTE,
                "btn": None, "strip": None, "prev": None, "next": None, "sub0": None, "sub1": None},
    "tools": {"pencil": None, "bucket": None, "undo": None},
    "formats": {},               # "16:9": {"rect": [x1, y1, x2, y2], "cols": 96, "rows": 54}
    "step_delay": 0.02,          # entre deux points d'un trait (>= une image du jeu, 60 fps = 0.017)
    "click_delay": 0.05,         # apres un clic (changement de couleur, case isolee)
    "fill_background": True,     # pot de peinture pour la couleur la plus presente
    "skip_white": False,         # ne pas peindre les cases blanches
    "verify": True,              # relire l'ecran apres chaque couleur et repeindre les cases manquantes
    "dense": False,              # envoyer un point par case des le depart (plus lent, plus sur)
    "refine": True,              # affiner la geometrie avec deux cases reperes au debut du dessin
    "outline": True,             # contours au crayon puis pot de peinture dans chaque zone (beaucoup moins de clics)
    "mouse_glide": True,         # la souris glisse jusqu'a chaque cible (bouton relache) au lieu de sauter
    "glide_speed": 1.0,          # facteur de duree des glissements (0.5 = deux fois plus rapide, 2 = plus lent)
}


def sample_color(x, y, radius=3):
    """Couleur moyenne autour d'un point de l'ecran, ou None."""
    im = grab((x - radius, y - radius, x + radius + 1, y + radius + 1))
    if im is None:
        return None
    px = list(im.getdata())
    n = len(px)
    return [sum(p[i] for p in px) // n for i in range(3)]


def _cdist(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _count_lines(profile, size):
    """Compte les cases sur un axe a partir du profil de luminosite (lignes de grille sombres)."""
    if len(profile) < 8:
        return None
    srt = sorted(profile)
    median = srt[len(srt) // 2]
    low = srt[max(0, len(srt) // 50)]
    if median - low < 4:
        return None
    thr = median - 0.4 * (median - low)
    marks, run = [], []
    for i, v in enumerate(profile):
        if v < thr:
            run.append(i)
        elif run:
            marks.append(sum(run) / len(run))
            run = []
    if run:
        marks.append(sum(run) / len(run))
    if len(marks) < 4:
        return None
    gaps = sorted(marks[i + 1] - marks[i] for i in range(len(marks) - 1))
    step = gaps[len(gaps) // 2]
    if step < 3:
        return None
    ok = sum(1 for g in gaps if abs(g - step) <= max(1.5, step * 0.25))
    if ok < len(gaps) * 0.6:
        return None
    return max(1, int(round(size / step)))


def detect_grid(rect):
    """(colonnes, lignes) en comptant les lignes de la grille du jeu dans le canevas, ou None."""
    im = grab(rect)
    if im is None:
        return None
    w, h = im.size
    if w < 20 or h < 20:
        return None
    g = im.convert("L")
    data = list(g.getdata())
    # profil par colonne (moyenne sur les lignes) et par ligne
    cols = [sum(data[y * w + x] for y in range(h)) / h for x in range(w)]
    rows = [sum(data[y * w + x] for x in range(w)) / w for y in range(h)]
    nx, ny = _count_lines(cols, w), _count_lines(rows, h)
    if nx and ny:
        return [nx, ny]
    return None


def build_strokes(cells, W, H, k, through=None):
    """Traits au crayon pour la couleur k : [(points [(x, y) cases], nb de cases)].
    Chaque ligne de cases contigues est un segment horizontal ; on enchaine avec une ligne de cases de la
    ligne du dessous sans lever le crayon (zigzag) : directement en dessous, ou en se decalant d'abord de
    cote (sur la ligne courante, ou sur celle du dessous) a travers des cases traversables.
    Traversables : les cases a peindre (cells == k) et, si `through` est donne, ses cases == k (mode
    contours : l'interieur d'une zone, rempli ensuite au pot). Les segments sont horizontaux ou verticaux
    et ne traversent que des cases de la couleur k, le jeu peut donc tracer la ligne."""
    trav = cells if through is None else through
    rows = {}
    for y in range(H):
        x = 0
        while x < W:
            if cells[y * W + x] != k:
                x += 1
                continue
            x0 = x
            while x < W and cells[y * W + x] == k:
                x += 1
            rows.setdefault(y, []).append((x0, x - 1))
    used = set()
    strokes = []

    def can(y, x0, x1):
        """Toutes les cases de la ligne y entre x0 et x1 (inclus) sont traversables."""
        base = y * W
        for x in range(min(x0, x1), max(x0, x1) + 1):
            if trav[base + x] != k and cells[base + x] != k:
                return False
        return True

    def find(y, x):
        for i, (a, b) in enumerate(rows.get(y, ())):
            if (y, i) not in used and a <= x <= b:
                return i, a, b
        return None

    def reach(cy, cx, d):
        """Ligne de cases atteignable sur la ligne cy + d depuis (cx, cy) : (index, a, b, points a ajouter, colonne)."""
        ny = cy + d
        f = find(ny, cx)
        if f:
            return f[0], f[1], f[2], [(cx, ny)], cx
        best = None
        for i, (a2, b2) in enumerate(rows.get(ny, ())):
            if (ny, i) in used:
                continue
            c = min(max(cx, a2), b2)
            cost = abs(c - cx)
            if best is not None and cost >= best[0]:
                continue
            if can(cy, cx, c):                                   # de cote sur la ligne courante, puis en bas / en haut
                best = (cost, i, a2, b2, [(c, cy), (c, ny)], c)
            elif can(ny, cx, c):                                 # en bas / en haut, puis de cote
                best = (cost, i, a2, b2, [(cx, ny), (c, ny)], c)
        return best[1:] if best else None

    for y in sorted(rows):
        for i, (a, b) in enumerate(rows[y]):
            if (y, i) in used:
                continue
            used.add((y, i))
            pts = [(a, y)]
            n = b - a + 1
            if b != a:
                pts.append((b, y))
            cx, cy = b, y
            dirn = 1
            while True:
                # vers le bas tant que possible, puis on remonte (le contour d'une zone : un bord en descendant,
                # l'autre en remontant, sans lever le crayon)
                found = reach(cy, cx, dirn)
                if not found:
                    dirn = -dirn
                    found = reach(cy, cx, dirn)
                    if not found:
                        break
                j, a2, b2, extra, cx = found
                cy += dirn
                used.add((cy, j))
                n += b2 - a2 + 1
                pts.extend(extra)
                if a2 == b2:
                    continue
                if cx == a2:
                    pts.append((b2, cy)); cx = b2
                elif cx == b2:
                    pts.append((a2, cy)); cx = a2
                else:
                    near, far = (a2, b2) if cx - a2 <= b2 - cx else (b2, a2)
                    pts.append((near, cy)); pts.append((far, cy)); cx = far
            strokes.append((pts, n))
    return strokes


def _stroke_cells(pts, W):
    """Indices des cases traversees par un trait (segments horizontaux ou verticaux)."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 == y1:
            out.extend(y0 * W + x for x in range(min(x0, x1), max(x0, x1) + 1))
        else:
            out.extend(y * W + x0 for y in range(min(y0, y1), max(y0, y1) + 1))
    if len(pts) == 1:
        out.append(pts[0][1] * W + pts[0][0])
    return sorted(set(out))


# ---------------------------------------------------------------- mode contours + pot de peinture
OUTLINE_MIN_FILL = 4   # en dessous, une zone interieure est peinte au crayon plutot qu'au pot


def _seed(comp, W, H):
    """Case la plus eloignee du bord de la zone (a egalite : la plus proche du centre), pour le clic du pot."""
    comp_set = set(comp)
    dist = {}
    queue = []
    for i in comp:
        x, y = i % W, i // W
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < W and 0 <= ny < H) or (ny * W + nx) not in comp_set:
                dist[i] = 0
                queue.append(i)
                break
    head = 0
    while head < len(queue):
        i = queue[head]
        head += 1
        x, y = i % W, i // W
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            j = ny * W + nx
            if 0 <= nx < W and 0 <= ny < H and j in comp_set and j not in dist:
                dist[j] = dist[i] + 1
                queue.append(j)
    xs, ys = [i % W for i in comp], [i // W for i in comp]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return max(comp, key=lambda i: (dist.get(i, 0), -((i % W - cx) ** 2 + (i // W - cy) ** 2)))


def _components(idx, W, H):
    """Composantes 4-connexes d'un ensemble d'indices de cases."""
    idx = set(idx)
    out = []
    while idx:
        i = idx.pop()
        comp = [i]
        stack = [i]
        while stack:
            c = stack.pop()
            cx, cy = c % W, c // W
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if 0 <= nx < W and 0 <= ny < H:
                    m = ny * W + nx
                    if m in idx:
                        idx.discard(m)
                        comp.append(m)
                        stack.append(m)
        out.append(comp)
    return out


def plan_outline(cells, W, H, skip=(), fill_color=None):
    """Mode contours : pour chaque couleur, traits au crayon (contours) et zones a remplir au pot de peinture.
    Retourne (strokes, pencil, fills, stats) : strokes[k] = traits (voir build_strokes) ; pencil[k] = cases
    peintes par ces traits ; fills[k] = [(graine, [indices])] ; stats = cases au crayon, zones au pot, cases au
    pot, cases a peindre (hors fond).
    Regle du mur unique : entre deux couleurs voisines, seule la moins presente (a egalite : l'index le plus
    grand) peint sa frontiere ; face au vide, chacune peint la sienne ; le fond deja rempli (fill_color) ne
    peint jamais. Apres les contours, toute case non peinte n'a pour voisines (8 directions) que des cases de
    sa couleur ou deja peintes : le pot ne peut pas deborder, quelle que soit sa connexite. Les traits peuvent
    traverser l'interieur d'une zone (meme couleur) pour ne pas lever le crayon ; les zones sont recalculees
    sur les cases restees vides."""
    skip = set(skip)
    n = W * H
    g = [(-1 if (c < 0 or c in skip) else c) for c in cells]
    if fill_color is not None:
        g = [fill_color if c < 0 else c for c in g]   # le fond est rempli partout avant de peindre
    counts = {}
    for c in g:
        if c >= 0:
            counts[c] = counts.get(c, 0) + 1

    def owns(k, j):
        """La couleur k peint-elle sa frontiere face a j ?"""
        if j < 0 or j == fill_color:
            return True
        return counts[j] > counts[k] or (counts[j] == counts[k] and j > k)

    own = {}
    contour = [False] * n
    for y in range(H):
        y0, y1 = max(0, y - 1), min(H - 1, y + 1)
        for x in range(W):
            i = y * W + x
            k = g[i]
            if k < 0 or k == fill_color:
                continue
            for yy in range(y0, y1 + 1):
                row = yy * W
                for xx in range(max(0, x - 1), min(W - 1, x + 1) + 1):
                    j = g[row + xx]
                    if j == k:
                        continue
                    o = own.get((k, j))
                    if o is None:
                        o = own[(k, j)] = owns(k, j)
                    if o:
                        contour[i] = True
                        break
                if contour[i]:
                    break
    by_color = {}
    for i, k in enumerate(g):
        if k >= 0 and k != fill_color:
            by_color.setdefault(k, []).append(i)
    strokes, pencil, fills = {}, {}, {}
    for k, idx in by_color.items():
        target = set(i for i in idx if contour[i])
        # petites zones interieures : au crayon plutot qu'au pot
        for comp in _components([i for i in idx if not contour[i]], W, H):
            if len(comp) < OUTLINE_MIN_FILL:
                target.update(comp)
        sub = [-2] * n
        for i in target:
            sub[i] = k
        st = build_strokes(sub, W, H, k, through=g)
        painted = set()
        for pts, _ in st:
            painted.update(_stroke_cells(pts, W))
        # zones restees vides apres les traits (qui ont pu traverser l'interieur) ; les trop petites au crayon
        zones = []
        extra = set()
        for comp in _components([i for i in idx if i not in painted], W, H):
            if len(comp) < OUTLINE_MIN_FILL:
                extra.update(comp)
            else:
                zones.append((_seed(comp, W, H), comp))
        if extra:
            sub = [-2] * n
            for i in extra:
                sub[i] = k
            more = build_strokes(sub, W, H, k)
            st = st + more
            for pts, _ in more:
                painted.update(_stroke_cells(pts, W))
        # nb de cases par trait = cases nouvelles (des traits peuvent se recouvrir), pour l'avancement
        covered = set()
        out = []
        for pts, _ in st:
            cs = set(_stroke_cells(pts, W))
            out.append((pts, len(cs - covered)))
            covered |= cs
        strokes[k] = out
        pencil[k] = painted
        fills[k] = zones
    stats = {
        "pencil_cells": sum(len(v) for v in pencil.values()),
        "fill_zones": sum(len(v) for v in fills.values()),
        "fill_cells": sum(len(c) for v in fills.values() for _, c in v),
        "total_cells": sum(v for k, v in counts.items() if k != fill_color),
        "strokes": sum(len(v) for v in strokes.values()),
    }
    return strokes, pencil, fills, stats


# ---------------------------------------------------------------- calibrage + dessin
STEPS = [
    ("tl", "Coin haut-gauche du canevas",
     "Place la souris exactement sur le coin haut-gauche de la zone rayée où l'on dessine (pas le cadre : en 1:1, 3:4 ou 9:16 elle est plus étroite que le cadre)."),
    ("br", "Coin bas-droit du canevas", "Place la souris sur le coin bas-droit de la zone rayée."),
    ("pal0", "Première couleur de la palette", "Survole la première pastille de couleur (en haut à gauche de la palette)."),
    ("pal1", "Dernière couleur de la palette", "Survole la dernière pastille (en bas à droite de la palette)."),
    ("palbtn", "Bouton « palette » (ouvre les nuances)",
     "Sans cliquer, survole le bouton rond avec l'icône palette, à gauche des pastilles de couleur : c'est lui qui affiche les nuances. Appuie sur F3."),
    ("strip", "Bande des familles : la pastille du centre",
     "Dans le jeu, clique sur le bouton palette : un bloc de 10 nuances apparaît, avec au-dessus une bande de familles de couleurs et des flèches < >. "
     "Sans cliquer, survole la pastille au centre de la bande (celle encadrée en blanc) et appuie sur F3."),
    ("prev", "Flèche « précédent » de la bande", "Survole (sans cliquer) la flèche < à gauche de la bande des familles, puis F3."),
    ("next", "Flèche « suivant » de la bande", "Survole (sans cliquer) la flèche > à droite de la bande des familles, puis F3."),
    ("sub0", "Nuances : celle en haut à gauche",
     "Sans cliquer, survole la nuance en haut à gauche du bloc de 10 nuances (2 colonnes × 5 lignes) et appuie sur F3."),
    ("sub1", "Nuances : celle en bas à droite",
     "Toujours sans cliquer, survole la nuance en bas à droite du même bloc (2e colonne, 5e ligne) et appuie sur F3. "
     "Ces 6 étapes sont nécessaires pour dessiner avec les 126 nuances."),
    ("pencil", "Outil crayon", "Survole le bouton du crayon, à gauche."),
    ("bucket", "Outil pot de peinture", "Survole le bouton du pot de peinture (remplissage)."),
    ("undo", "Bouton Annuler", "Survole la flèche « Annuler » au-dessus du canevas (facultatif : sert à mesurer le canevas quand le fond n'est pas rempli)."),
]


def ensure_defaults(cfg):
    d = cfg.setdefault("draw", {})
    for k, v in DEFAULT_DRAW.items():
        if k not in d:
            d[k] = v if not isinstance(v, (dict, list)) else __import__("copy").deepcopy(v)
    pal = d["palette"]
    if not pal.get("colors"):
        pal["colors"] = [list(c) for c in DEFAULT_PALETTE]
    return d


def format_grid(cfg, fmt):
    d = ensure_defaults(cfg)
    f = d["formats"].get(fmt) or {}
    return [int(f.get("cols") or DEFAULT_GRIDS[fmt][0]), int(f.get("rows") or DEFAULT_GRIDS[fmt][1])]


class Drawer(MouseBot):
    ACTIVE_STATES = ("drawing", "autocal")

    def __init__(self, cfg, log=print, on_change=None, save=None, logfile=None):
        self.cfg = cfg
        self._ui_log = log
        self.logfile = logfile
        self._t0 = time.perf_counter()
        self.step = 0.02              # delai courant entre deux points (adaptatif pendant le dessin)
        self.unrepaired = 0
        self.on_change = on_change or (lambda: None)
        self.save = save or (lambda: None)
        self.countdown = 0.0
        self._last_toggle = 0.0
        self.state = "idle"          # idle | calibrating | drawing
        self.step = 0
        self.fmt = "16:9"
        self.points = {}
        self.done = 0
        self.total = 0
        self.actions_done = 0
        self.actions_total = 0
        self.message = ""
        self.last_stop_reason = ""
        self.started_at = None
        self._stop = threading.Event()
        self._thread = None
        self._hook = None
        self._expected_pos = None
        self.stride = None            # pixels entre deux positions envoyees dans un trait (None = extremites)
        self.progress_msg = ""
        self._cell_px = 0.0
        self._empty_colors = []
        self.repaired = 0
        self._geo = None              # [x1, y1, cw, ch, W, H] du dessin en cours (corrige en direct)
        self._fill_box = None         # rectangle rempli mesure a l'ecran (avant correction par les reperes)
        self._marks_done = set()      # couleurs deja utilisees pour les reperes de geometrie
        self._last_seen = None        # derniere lecture du canevas (_read_canvas)
        self._used = None             # nuances utilisees par le dessin en cours (les autres se lisent « vide »)
        ensure_defaults(cfg)

    @property
    def draw_cfg(self):
        return ensure_defaults(self.cfg)

    def _mouse_cfg(self):
        return self.draw_cfg

    def _slower(self, why, dense=False):
        """Le jeu perd des positions : on espace davantage les points (jusqu'a 0.12 s),
        et, si demande, on envoie un point par case."""
        old = self.step
        self.step = min(0.12, round(self.step * 1.6, 3))
        if dense and self._cell_px:
            self.stride = max(2.0, self._cell_px)
        self.log(f"{why} : délai entre points {old:.3f} → {self.step:.3f} s"
                 + (", un point par case" if self.stride else ""))

    # ---- calibrage
    def start_calibration(self, fmt):
        if self.state == "drawing":
            self.stop("calibrage demandé")
        self.fmt = fmt if fmt in FORMATS else "16:9"
        self.points = {}
        self.step = 0
        self.state = "calibrating"
        self.message = ""
        self.log(f"calibrage {self.fmt} : étape 1")
        self.on_change()

    def cancel_calibration(self):
        if self.state == "calibrating":
            self.state = "idle"
            self.points = {}
            self.log("calibrage annulé")
            self.on_change()

    def capture_point(self):
        """Raccourci F3 pendant le calibrage : memorise la position de la souris pour l'etape en cours."""
        if self.state != "calibrating":
            return False
        key = STEPS[self.step][0]
        self.points[key] = cursor_pos()
        if key == "pal1":
            # la palette principale est visible maintenant (ensuite les nuances la recouvrent)
            self.points["_colors"] = self._read_main_palette(self.points["pal0"], self.points["pal1"])
        self.step += 1
        if self.step >= len(STEPS):
            self._finish_calibration()
        else:
            self.on_change()
        return True

    def _read_main_palette(self, p0, p1):
        pal = self.draw_cfg["palette"]
        old = pal.get("pos0"), pal.get("pos1")
        pal["pos0"], pal["pos1"] = p0, p1
        colors = []
        for i in range(pal["cols"] * pal["rows"]):
            x, y = self.palette_pos(i)
            c = sample_color(x, y)
            colors.append(c if c else (pal["colors"][i] if i < len(pal["colors"]) else [128, 128, 128]))
        pal["pos0"], pal["pos1"] = old
        return colors

    def back_point(self):
        """Revient a l'etape precedente : la position qui y avait ete enregistree est oubliee, pour etre
        reprise. Le calibrage deja en place dans la config n'est pas touche (il ne l'est qu'a la validation)."""
        if self.state != "calibrating" or self.step <= 0:
            return False
        self.step -= 1
        key = STEPS[self.step][0]
        self.points.pop(key, None)
        if key == "pal1":
            self.points.pop("_colors", None)
        self.message = ""
        self.log(f"calibrage : retour a l'etape {self.step + 1}")
        self.on_change()
        return True

    def goto_step(self, index):
        """Revient a une etape deja faite (clic dans le recapitulatif). On ne saute jamais en avant."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        if self.state != "calibrating" or not 0 <= index < self.step:
            return False
        while self.step > index:
            self.back_point()
        return True

    def skip_point(self):
        """Etape facultative (outils) : passe sans memoriser."""
        if self.state != "calibrating":
            return False
        key = STEPS[self.step][0]
        if key in ("palbtn", "strip", "prev", "next", "sub0", "sub1", "pencil", "bucket", "undo"):
            self.step += 1
            if self.step >= len(STEPS):
                self._finish_calibration()
            else:
                self.on_change()
            return True
        return False

    def _finish_calibration(self):
        d = self.draw_cfg
        p = self.points
        x1, y1 = p["tl"]
        x2, y2 = p["br"]
        rect = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
        if rect[2] - rect[0] < 40 or rect[3] - rect[1] < 40:
            self.state = "idle"
            self.message = "Canevas trop petit : refais le calibrage."
            self.log(self.message)
            self.on_change()
            return
        f = d["formats"].setdefault(self.fmt, {})
        f["rect"] = rect
        f["screen"] = screen_fingerprint()
        # le nombre de cases est connu par format ; la detection ne sert qu'a verifier
        f.setdefault("cols", DEFAULT_GRIDS[self.fmt][0])
        f.setdefault("rows", DEFAULT_GRIDS[self.fmt][1])
        grid = detect_grid(rect)
        if grid and [int(f["cols"]), int(f["rows"])] == list(grid):
            grid_msg = f"grille {f['cols']} × {f['rows']} confirmée à l'écran"
        elif grid and 8 <= grid[0] <= 400 and 8 <= grid[1] <= 400:
            grid_msg = (f"{f['cols']} × {f['rows']} cases ; à l'écran je compte plutôt {grid[0]} × {grid[1]}, "
                        f"vérifie le format et la finesse (modifiable dans Réglages)")
        else:
            grid_msg = f"{f['cols']} × {f['rows']} cases"
        pal = d["palette"]
        pal["pos0"], pal["pos1"] = p["pal0"], p["pal1"]
        if p.get("_colors"):
            pal["colors"] = p["_colors"]
        if all(k in p for k in ("palbtn", "strip", "prev", "next", "sub0", "sub1")):
            pal["btn"], pal["strip"], pal["prev"], pal["next"] = p["palbtn"], p["strip"], p["prev"], p["next"]
            pal["sub0"], pal["sub1"] = p["sub0"], p["sub1"]
            pal.pop("painted", None)   # les couleurs peintes seront reapprises au calibrage auto
            shade_msg = "126 nuances"
        elif self.shades_ok():
            shade_msg = "126 nuances (positions précédentes conservées)"
        else:
            shade_msg = "16 couleurs seulement (nuances non calibrées)"
        if "pencil" in p:
            d["tools"]["pencil"] = p["pencil"]
        if "bucket" in p:
            d["tools"]["bucket"] = p["bucket"]
        if "undo" in p:
            d["tools"]["undo"] = p["undo"]
        self.state = "idle"
        self.message = f"Calibrage {self.fmt} enregistré : {grid_msg}, {shade_msg}."
        self.log(self.message)
        try:
            self.save()
        except Exception as e:  # noqa
            self.log(f"sauvegarde du calibrage impossible : {e}")
        self.on_change()

    def palette_pos(self, i):
        pal = self.draw_cfg["palette"]
        p0, p1 = pal.get("pos0"), pal.get("pos1")
        if not p0 or not p1:
            return None
        cols, rows = max(1, int(pal["cols"])), max(1, int(pal["rows"]))
        c, r = i % cols, i // cols
        x = p0[0] + (p1[0] - p0[0]) * (c / (cols - 1) if cols > 1 else 0)
        y = p0[1] + (p1[1] - p0[1]) * (r / (rows - 1) if rows > 1 else 0)
        return [int(round(x)), int(round(y))]

    def shade_pos(self, j):
        """Position a l'ecran de la nuance j (0..9) quand les nuances d'une famille sont affichees."""
        pal = self.draw_cfg["palette"]
        p0, p1 = pal.get("sub0"), pal.get("sub1")
        if not p0 or not p1:
            return None
        c, r = j % SHADE_COLS, j // SHADE_COLS
        x = p0[0] + (p1[0] - p0[0]) * c / (SHADE_COLS - 1)
        y = p0[1] + (p1[1] - p0[1]) * r / (SHADE_ROWS - 1)
        return [int(round(x)), int(round(y))]

    def shades_ok(self):
        pal = self.draw_cfg["palette"]
        return bool(all(pal.get(k) for k in ("btn", "strip", "prev", "next", "sub0", "sub1")))

    def available(self):
        """Index (plats) des nuances que l'on sait selectionner dans le jeu."""
        if self.shades_ok():
            return list(range(len(SHADES)))
        return [k for k, m in enumerate(SHADE_MAIN) if m >= 0]

    def _page(self):
        """Page de nuances affichee (index dans PAGES), lue sur la pastille encadree de la bande des familles ;
        None si les nuances ne sont pas ouvertes (ou ecran illisible)."""
        pal = self.draw_cfg["palette"]
        strip = pal.get("strip")
        if not strip:
            return None
        c = sample_color(strip[0], strip[1], radius=2)
        if c is None:
            return None
        fams = pal["colors"]
        best, bd = None, 40 * 40
        for i, fam in enumerate(PAGES):
            if fam < len(fams):
                dd = _cdist(c, fams[fam])
                if dd < bd:
                    best, bd = i, dd
        return best

    def _shades_open(self):
        return self._page() is not None

    def _select(self, k, delay=0.15):
        """Selectionne la nuance k dans le jeu : ouvre les nuances (bouton palette) si besoin, va a la page
        de la famille avec les fleches precedent / suivant, puis clique sur la nuance."""
        fam, j, _ = SHADES[k]
        pal = self.draw_cfg["palette"]
        if not self.shades_ok():
            m = SHADE_MAIN[k]
            if m < 0:
                raise RuntimeError("cette nuance demande le calibrage des nuances (étapes « nuances » du calibrage)")
            return self._click(*self.palette_pos(m), delay=delay)
        target = PAGES.index(fam)
        cur = self._page()
        if cur is None:
            if not self._click(*pal["btn"], delay=0.25):
                return False
            cur = self._page()
            if cur is None:
                # le bouton n'a rien ouvert : on selectionne la famille dans la palette puis on reessaie
                if not self._click(*self.palette_pos(fam), delay=0.12) or not self._click(*pal["btn"], delay=0.25):
                    return False
                cur = self._page()
                if cur is None:
                    raise RuntimeError("les nuances ne s'ouvrent pas (bouton palette / bande des familles mal calibrés ?)")
        for attempt in range(3):
            if cur == target:
                break
            btn = pal["next"] if target > cur else pal["prev"]
            for _ in range(abs(target - cur)):
                if not self._click(*btn, delay=0.12):
                    return False
            if not self._sleep(0.08):
                return False
            cur = self._page()
            if cur is None:
                raise RuntimeError("bande des familles illisible pendant le changement de page")
            if cur != target:
                self.log(f"page de nuances {cur + 1} au lieu de {target + 1}, nouvel essai")
        if cur != target:
            raise RuntimeError(f"impossible d'atteindre la page de nuances {target + 1}")
        return self._click(*self.shade_pos(j), delay=delay)

    def calibrated(self, fmt):
        d = self.draw_cfg
        return bool(d["formats"].get(fmt, {}).get("rect") and d["palette"].get("pos0") and d["palette"].get("pos1"))

    # ---- dessin
    def start(self, job, delay=1.0):
        """job = {format, w, h, cells: [index palette jeu ou -1], skip: [indices a ne pas peindre]}
        delay : secondes avant le premier clic, le temps de passer sur le jeu."""
        if self.state == "drawing":
            self.log("dessin déjà en cours")
            return False
        now = time.perf_counter()
        if now - self._last_toggle < 0.8:
            return False
        self._last_toggle = now
        fmt = job.get("format", "16:9")
        if not self.calibrated(fmt):
            self.message = f"Format {fmt} pas encore calibré."
            self.log(self.message)
            self.on_change()
            return False
        if screen_changed(self.draw_cfg["formats"].get(fmt, {}).get("screen")):
            # resolution, mise a l'echelle ou ecrans changes depuis la configuration : les positions
            # enregistrees ne tombent plus sur la toile ni sur la palette
            self.message = (f"L'écran a changé depuis la configuration du format {fmt} (résolution, mise à "
                            f"l'échelle ou écrans) : refais la configuration de la zone du jeu.")
            self.log(self.message)
            self.on_change()
            return False
        self.state = "drawing"
        self.fmt = fmt
        self.last_stop_reason = ""
        self.message = ""
        self._stop.clear()
        self.countdown = float(delay)
        self._thread = threading.Thread(target=self._run, args=(job, float(delay)), daemon=True)
        self._thread.start()
        return True

    def stop(self, reason=""):
        if self.state == "autocal":
            self.last_stop_reason = reason
            self._stop.set()
            return True
        if self.state == "drawing":
            if reason == "stop" and time.perf_counter() - self._last_toggle < 0.8:
                return False  # rebond du raccourci qui vient de lancer le dessin
            self.last_stop_reason = reason
            self._stop.set()
            return True
        if self.state == "calibrating":
            self.cancel_calibration()
        return False

    def _drag(self, points):
        """Trait continu au crayon passant par les points (centres de cases, en pixels).
        self.stride : distance max (pixels) entre deux positions envoyees ; None = extremites seulement."""
        if self._user_moved():
            self.stop("souris bougée")
            return False
        step = self.step
        path = [points[0]]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            n = 1
            if self.stride:
                n = max(1, int(round(max(abs(x1 - x0), abs(y1 - y0)) / self.stride)))
            for i in range(1, n + 1):
                path.append((int(round(x0 + (x1 - x0) * i / n)), int(round(y0 + (y1 - y0) * i / n))))
        if not self._move(*path[0]):
            return False
        if not self._sleep(0.03):
            return False
        mouse_down()
        ok = self._sleep(0.035)
        for x, y in path[1:]:
            if not ok:
                break
            # crayon baisse : le jeu trace la ligne entre deux positions, on envoie le chemin tel quel
            self._move(x, y, glide=False)
            self.actions_done += 1
            ok = self._sleep(step)
        if ok:
            ok = self._sleep(0.02)
        mouse_up()
        self.actions_done += 1
        return ok and self._sleep(step)

    # ---- lecture du canevas a l'ecran (verification et reparation)
    def _read_canvas(self, geo):
        """Pour chaque case, l'index de la couleur de palette vue a l'ecran (-1 = vide / inconnu).
        Vote sur une croix de 5 pixels au centre de la case (le centre compte double), des que la case fait au
        moins 3,5 px : avec des cases de 4 px dont 1 px de ligne de grille, un seul pixel tombait une fois sur
        quatre sur la grille ou dans la case voisine, et une case bien peinte passait pour manquante (repeinte
        a chaque passe, puis « perdue »). Un bloc de 3 x 3 serait trop large : il mordrait sur la grille (3 px
        de couleur utile seulement). Une couleur de l'image vue sur au moins deux points bat le « vide » : une
        ligne de grille traverse souvent la croix (centre + gauche + droite), une couleur peinte n'y apparait
        pas par hasard. Les teintes que l'image n'utilise pas (self._used, grille lue comme un gris de la
        palette) comptent comme vide."""
        x1, y1, cw, ch, W, H = geo
        ox, oy = int(x1), int(y1)
        im = grab((ox, oy, int(round(x1 + cw * W)) + 1, int(round(y1 + ch * H)) + 1))
        if im is None:
            return None
        px = im.load()
        iw, ih = im.size
        colors = self.colors()
        empties = self._empty_colors
        used = self._used
        cache = {}
        block = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)) if min(cw, ch) >= 3.5 else ((0, 0),)

        def classify(c):
            key = (c[0] >> 2, c[1] >> 2, c[2] >> 2)
            k = cache.get(key)
            if k is None:
                best = -1
                bd = min(_cdist(c, e) for e in empties) if empties else 10 ** 9
                for i, pc in enumerate(colors):
                    dd = _cdist(c, pc)
                    if dd < bd:
                        bd, best = dd, i
                k = best if bd < 45 * 45 else -1
                if used is not None and k >= 0 and k not in used:
                    k = -1
                cache[key] = k
            return k

        out = [-1] * (W * H)
        fx, fy = x1 - ox, y1 - oy
        for cy in range(H):
            py = min(ih - 1, int(fy + (cy + 0.5) * ch))
            for cx in range(W):
                pxx = min(iw - 1, int(fx + (cx + 0.5) * cw))
                k0 = classify(px[pxx, py][:3])
                if len(block) == 1:
                    out[cy * W + cx] = k0
                    continue
                votes = {k0: 2}
                for dx, dy in block[1:]:
                    xx, yy = pxx + dx, py + dy
                    if 0 <= xx < iw and 0 <= yy < ih:
                        k = classify(px[xx, yy][:3])
                        votes[k] = votes.get(k, 0) + 1
                # une couleur vue au moins deux fois bat le vide ; sinon majorite, a egalite le pixel central
                colored = [k for k, v in votes.items() if k >= 0 and v >= 2]
                pool = colored or list(votes)
                out[cy * W + cx] = max(pool, key=lambda k: (votes[k], k == k0))
        self._last_seen = out
        return out

    def colors(self):
        """Couleurs des nuances telles qu'elles apparaissent une fois peintes (apprises au calibrage auto),
        sinon les valeurs connues des pastilles."""
        pal = self.draw_cfg["palette"]
        painted = pal.get("painted")
        base = [c for _, _, c in SHADES]
        if painted and len(painted) == len(base):
            return [list(p) if p else list(c) for p, c in zip(painted, base)]
        return [list(c) for c in base]

    def _find_dot(self, x, y, color, radius):
        """Centre (float) de la tache de couleur `color` autour de (x, y) a l'ecran, ou None."""
        ox, oy = int(x - radius), int(y - radius)      # origine entiere : la capture commence sur un pixel
        im = grab((ox, oy, int(x + radius) + 1, int(y + radius) + 1))
        if im is None:
            return None
        px = im.load()
        w, h = im.size
        xs, ys = [], []
        for j in range(h):
            for i in range(w):
                c = px[i, j][:3]
                if _cdist(c, color) < 40 * 40 and all(_cdist(c, e) > 30 * 30 for e in self._empty_colors):
                    xs.append(i)
                    ys.append(j)
        if len(xs) < 4:
            return None
        return (ox + (min(xs) + max(xs)) / 2.0, oy + (min(ys) + max(ys)) / 2.0)

    def _refine_by_fill(self, x1, y1, x2, y2, rgb):
        """Apres le pot de peinture : le rectangle de couleur `rgb` a l'ecran est le canevas exact."""
        from PIL import Image, ImageChops
        m = 14
        im = grab((int(x1 - m), int(y1 - m), int(x2 + m) + 1, int(y2 + m) + 1))
        if im is None:
            return None
        diff = ImageChops.difference(im, Image.new("RGB", im.size, tuple(int(v) for v in rgb))).convert("L")
        box = diff.point(lambda v: 255 if v < 28 else 0).getbbox()
        if not box:
            self.log("zone remplie non trouvée à l'écran, géométrie du calibrage conservée")
            return None
        bx1, by1, bx2, by2 = box
        nx1, ny1 = int(x1 - m) + bx1, int(y1 - m) + by1
        nx2, ny2 = int(x1 - m) + bx2, int(y1 - m) + by2   # getbbox : bord droit/bas exclusif
        if not (0.85 < (nx2 - nx1) / (x2 - x1) < 1.15 and 0.85 < (ny2 - ny1) / (y2 - y1) < 1.15):
            self.log(f"zone remplie incohérente ({nx2 - nx1}×{ny2 - ny1} px pour {x2 - x1:.0f}×{y2 - y1:.0f}), calibrage conservé")
            return None
        self.log(f"canevas mesuré après remplissage : {nx1},{ny1} → {nx2},{ny2} "
                 f"(calibrage {x1:.0f},{y1:.0f} → {x2:.0f},{y2:.0f})")
        return float(nx1), float(ny1), float(nx2), float(ny2)

    def _same(self, k, colors=None):
        """Indices des nuances que l'ecran ne distingue pas de k (certaines nuances de familles voisines sont
        quasi identiques)."""
        cols = colors or self.colors()
        ck = cols[k]
        return {k} | {i for i, c in enumerate(cols) if _cdist(c, ck) < 18 * 18}

    def _apply_geo(self, x0, y0, pw, ph):
        """Nouvelle geometrie des cases (origine, taille) : appliquee au dessin en cours (self._geo, lu par
        toutes les fonctions de centre) et enregistree dans le calibrage du format. Si le rectangle rempli a
        ete mesure, l'ecart entre ce rectangle et les cases est memorise (fill_inset) pour que le prochain
        dessin tombe juste des le remplissage."""
        geo = self._geo
        W, H = geo[4], geo[5]
        geo[0], geo[1], geo[2], geo[3] = float(x0), float(y0), float(pw), float(ph)
        f = self.draw_cfg["formats"].setdefault(self.fmt, {})
        f["rect"] = [round(x0, 2), round(y0, 2), round(x0 + pw * W, 2), round(y0 + ph * H, 2)]
        if self._fill_box:
            fb = self._fill_box
            f["fill_inset"] = [round(x0 - fb[0], 2), round(y0 - fb[1], 2),
                               round(x0 + pw * W - fb[2], 2), round(y0 + ph * H - fb[3], 2)]
        self._cell_px = min(pw, ph)
        try:
            self.save()
        except Exception:
            pass

    def _empties_setup(self, x1, y1, x2, y2, used):
        """Teintes de la toile vide (rayures, grille), indispensables pour lire l'ecran. 16 pixels isoles de la
        toile, regroupes par teinte (les groupes d'un seul pixel sont ignores) : c'est ce que la toile montre
        MAINTENANT, rayures si elle est vide, couleurs peintes sinon. En attendant de savoir (voir
        _settle_empties), l'ecran est lu avec les teintes enregistrees plus celles vues qui ne sont pas des
        couleurs de l'image (`used`) : le fond deja peint ne doit pas masquer les cases en place.
        Renvoie les teintes vues."""
        d = self.draw_cfg
        raw = []
        for i in range(4):
            for j in range(4):
                c = sample_color(int(x1 + (x2 - x1) * (i + 0.5) / 4), int(y1 + (y2 - y1) * (j + 0.5) / 4), radius=0)
                if c:
                    raw.append(list(c))
        clusters = []
        for c in raw:
            for cl in clusters:
                if _cdist(c, cl[0]) < 20 * 20:
                    cl.append(c)
                    break
            else:
                clusters.append([c])
        clusters.sort(key=len, reverse=True)
        cur = [[sum(p[i] for p in cl) // len(cl) for i in range(3)] for cl in clusters if len(cl) >= 2]
        stored = [list(c) for c in (d.get("empty_colors") or []) if c]
        self._empty_colors = list(stored)
        for c in cur:
            if all(_cdist(c, e) >= 20 * 20 for e in self._empty_colors) and all(_cdist(c, u) >= 45 * 45 for u in used):
                self._empty_colors.append(c)
        return cur

    def _settle_empties(self, cur, fresh, counts, colors):
        """Toile vide (aucune case de l'image deja en place) : les teintes vues sont celles du vide, on les
        enregistre pour les reprises. Toile entamee : on garde les teintes enregistrees ; s'il n'y en a pas
        (ancienne config), on prend les teintes vues qui ne sont pas des couleurs de l'image (le fond peint est
        une couleur de l'image, les rayures restantes non). Renvoie True si la liste a change (relire l'ecran)."""
        d = self.draw_cfg
        before = list(self._empty_colors)
        stored = [list(c) for c in (d.get("empty_colors") or []) if c]
        if fresh:
            self._empty_colors = list(cur)
            for e in stored:
                if all(_cdist(e, c) >= 20 * 20 for c in cur) and min((_cdist(e, c) for c in cur), default=10 ** 9) < 40 * 40:
                    self._empty_colors.append(e)      # meme toile, teinte deja connue, pas echantillonnee cette fois
            if cur and self._empty_colors != stored:
                d["empty_colors"] = [list(c) for c in self._empty_colors]
                try:
                    self.save()
                except Exception:
                    pass
        elif stored:
            self._empty_colors = stored
        else:
            used = [colors[k] for k in counts]
            self._empty_colors = [c for c in cur if all(_cdist(c, u) >= 45 * 45 for u in used)]
            if self._empty_colors:
                self.log(f"teintes de la toile vide estimées sur la toile entamée : {self._empty_colors}")
        return self._empty_colors != before

    def _refine_marks(self, k, cells, seen, geo, colors=None):
        """Reperes de geometrie pendant le dessin : jusqu'a 5 cases isolees a peindre en couleur k (deja
        selectionnee), cliquees puis retrouvees a l'ecran, pour mesurer l'origine et la taille reelles des cases.
        Le calibrage et la mesure du rectangle rempli donnent le bord du canevas, pas l'endroit exact ou le jeu
        place ses cases : un decalage d'un tiers de case suffisait pour que des centaines de clics tombent dans
        la case voisine (cinq passes de reparation a chaque couleur, des cases perdues quand meme).
        Renvoie True si la geometrie a ete mesuree, False si les reperes n'ont pas suffi, None si le dessin
        est arrete."""
        self._marks_done.add(k)
        if seen is None:
            return False
        x1, y1, cw, ch, W, H = geo
        colors = colors or self.colors()
        color = colors[k]
        r = 3
        # cases isolees : rien de la couleur k (ni d'une couleur proche) a moins de r cases, a l'ecran
        near = {i for i, c in enumerate(colors) if _cdist(c, color) < 40 * 40}
        cand = []
        for i, c in enumerate(cells):
            if c != k or seen[i] in near:
                continue
            x, y = i % W, i // W
            if not (r <= x < W - r and r <= y < H - r):
                continue
            ok = True
            for yy in range(y - r, y + r + 1):
                row = yy * W
                for xx in range(x - r, x + r + 1):
                    if seen[row + xx] in near:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                cand.append((x, y))
        if len(cand) < 2:
            self.log(f"repères : pas assez de cases isolées de la couleur {k} ({len(cand)}), géométrie conservée")
            return False
        m = max(r, W // 8)
        targets = [(m, m), (W - 1 - m, m), (m, H - 1 - m), (W - 1 - m, H - 1 - m), (W // 2, H // 2)]
        marks = []
        for tx, ty in targets:
            best = min(cand, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)
            if all(max(abs(best[0] - mx), abs(best[1] - my)) > 2 * r for mx, my in marks):
                marks.append(best)
        center = self._center_fn(geo)
        for cx, cy in marks:
            if not self._click(*center(cx, cy), delay=0.05):
                return None
        if not self._sleep(0.15):
            return None
        pairs = []
        rad = max(8, 2.5 * max(cw, ch))
        for cx, cy in marks:
            fx, fy = x1 + (cx + 0.5) * cw, y1 + (cy + 0.5) * ch
            p = self._find_dot(fx, fy, color, rad)
            if p:
                pairs.append((cx + 0.5, cy + 0.5, p[0], p[1]))
        if len(pairs) < 2:
            self.log(f"repères : {len(pairs)}/{len(marks)} retrouvés à l'écran, géométrie conservée")
            return False

        def fit(us, vs, scale, span_min):
            """v = v0 + u * scale ; l'echelle n'est ajustee (moindres carres) que si les reperes couvrent au
            moins 60 % de la toile : le jeu arrondit chaque bord de case au pixel, et sur 15 cases d'ecart ce
            bruit fausserait l'echelle de plusieurs pixels au bout de la toile."""
            n = len(us)
            um, vm = sum(us) / n, sum(vs) / n
            var = sum((u - um) ** 2 for u in us)
            if max(us) - min(us) >= span_min and var > 0:
                s = sum((u - um) * (v - vm) for u, v in zip(us, vs)) / var
                if 0.9 * scale < s < 1.1 * scale:
                    scale = s
            return vm - um * scale, scale

        x0, pw = fit([p[0] for p in pairs], [p[2] for p in pairs], cw, max(10, int(0.6 * W)))
        y0, ph = fit([p[1] for p in pairs], [p[3] for p in pairs], ch, max(10, int(0.6 * H)))
        resid = max(max(abs(fx - (x0 + u * pw)), abs(fy - (y0 + v * ph))) for u, v, fx, fy in pairs)
        if resid > max(1.5, 0.35 * min(pw, ph)):
            self.log(f"repères incohérents (écart {resid:.1f} px sur {len(pairs)} repères), géométrie conservée")
            return False
        self.log(f"géométrie mesurée sur {len(pairs)} repères : cases {pw:.3f}×{ph:.3f} px (avant {cw:.3f}×{ch:.3f}), "
                 f"origine décalée de {x0 - x1:+.1f},{y0 - y1:+.1f} px")
        self._apply_geo(x0, y0, pw, ph)
        return True

    def _apply_inset(self, f, box):
        ins = f.get("fill_inset")
        if ins and len(ins) == 4:
            return (box[0] + ins[0], box[1] + ins[1], box[2] + ins[2], box[3] + ins[3])
        return box

    # ---- calibrage automatique : dessine dans le canevas, mesure, corrige, valide
    def start_auto(self, fmt, delay=3.0):
        if self.state != "idle":
            return False
        d = self.draw_cfg
        if not self.calibrated(fmt) or not d["tools"].get("pencil") or not d["tools"].get("bucket"):
            self.message = "Fais d'abord le calibrage manuel (canevas, palette, crayon, pot de peinture)."
            self.on_change()
            return False
        self.fmt = fmt
        self.state = "autocal"
        self.last_stop_reason = ""
        self.message = ""
        self.progress_msg = ""
        self._stop.clear()
        self.countdown = float(delay)
        self._thread = threading.Thread(target=self._run_auto, args=(float(delay),), daemon=True)
        self._thread.start()
        return True

    def _run_auto(self, delay):
        self._t0 = time.perf_counter()
        if self.logfile:
            try:
                with open(self.logfile, "w", encoding="utf-8") as f:
                    f.write(f"DodoTopia calibrage automatique {time.strftime('%Y-%m-%d %H:%M:%S')} format {self.fmt}\n")
            except Exception:
                pass
        try:
            end = time.perf_counter() + delay
            while True:
                rem = end - time.perf_counter()
                self.countdown = max(0.0, rem)
                if rem <= 0 or self._stop.is_set():
                    break
                time.sleep(0.05)
            self.countdown = 0.0
            if not self._stop.is_set():
                self._auto()
        except Exception as e:  # noqa
            self.log(f"erreur calibrage auto : {e}")
            self.last_stop_reason = "erreur"
            self.message = f"Calibrage automatique impossible : {e}"
        finally:
            if self.last_stop_reason and self.last_stop_reason != "erreur":
                self.message = f"Calibrage automatique arrêté ({self.last_stop_reason})."
            try:
                mouse_up()
            except Exception:
                pass
            self._auto_cleanup()
            self.state = "idle"
            self.progress_msg = ""
            self._expected_pos = None
            self.log("calibrage auto terminé" if not self.last_stop_reason else f"calibrage auto arrêté ({self.last_stop_reason})")
            self.on_change()

    def _auto_cleanup(self):
        """Annule les actions du calibrage auto (bouton Annuler calibre), meme apres une erreur."""
        n = getattr(self, "_auto_actions", 0)
        undo = self.draw_cfg["tools"].get("undo")
        if not n or not undo:
            return
        self._progress(f"nettoyage du canevas : {n} Annuler")
        self._stop.clear()
        self._expected_pos = None
        for _ in range(n + 1):
            if not self._click(*undo, delay=0.06):
                break
        self._auto_actions = 0

    def _progress(self, msg):
        self.progress_msg = msg
        self.log(msg)
        self.on_change()

    def _auto(self):
        d = self.draw_cfg
        f = d["formats"][self.fmt]
        x1, y1, x2, y2 = [float(v) for v in f["rect"]]
        W, H = int(f["cols"]), int(f["rows"])
        cw, ch = (x2 - x1) / W, (y2 - y1) / H
        pal = d["palette"]
        swatch = self.colors()
        avail = self.available()
        n = len(swatch)
        self._auto_actions = 0

        def center(cx, cy):
            return [int(round(x1 + (cx + 0.5) * cw)), int(round(y1 + (cy + 0.5) * ch))]

        self._expected_pos = None
        self._check_mouse(*center(W // 2, H // 2))
        self._empty_colors = []
        for fx, fy in ((0.5, 0.5), (0.25, 0.25), (0.75, 0.75), (0.5, 0.25)):
            c = sample_color(int(x1 + (x2 - x1) * fx), int(y1 + (y2 - y1) * fy), radius=1)
            if c:
                self._empty_colors.append(c)
        if not self._empty_colors:
            raise RuntimeError("impossible de lire l'écran (Pillow absent ?)")
        spread = max(_cdist(a, b) for a in self._empty_colors for b in self._empty_colors)
        if spread > 40 * 40:
            raise RuntimeError("le canevas ne semble pas vide (couleurs différentes à plusieurs endroits) : ouvre un dessin vide")
        far = lambda c: min(_cdist(c, e) for e in self._empty_colors)

        # 1. remplissage avec la couleur la plus eloignee du fond vide, mesure du rectangle rempli
        self._progress("1/5 remplissage et mesure du canevas")
        mk = max(avail, key=lambda i: far(swatch[i]))
        if not self._select(mk):
            return
        if not self._click(*d["tools"]["bucket"], delay=0.15):
            return
        if not self._click(*center(W // 2, H // 2), delay=0.35):
            return
        self._auto_actions += 1
        painted = [None] * n
        painted[mk] = sample_color(*center(W // 2, H // 2), radius=1) or swatch[mk]
        box = self._refine_by_fill(x1, y1, x2, y2, painted[mk])
        if not box:
            raise RuntimeError("le remplissage n'a pas été trouvé à l'écran : le canevas était-il vide et visible ?")
        fill_box = box
        x1, y1 = box[0], box[1]
        cw, ch = (box[2] - box[0]) / W, (box[3] - box[1]) / H
        x2, y2 = x1 + cw * W, y1 + ch * H
        if not self._click(*d["tools"]["pencil"], delay=0.15):
            return

        # 2. un point de chaque couleur (en lignes espacees), pour apprendre les couleurs telles que peintes
        self._progress(f"2/5 lecture des {len(avail)} couleurs peintes")
        m = 3
        per_row = max(1, (W - 2 * m) // 2)
        dots = {}
        for idx_, i in enumerate(k for k in avail if k != mk):
            dots[i] = (m + 2 * (idx_ % per_row), m + 1 + 2 * (idx_ // per_row))
        top = m + 1 + 2 * ((len(dots) + per_row - 1) // per_row)   # premiere ligne libre sous les points
        for i, (cx, cy) in dots.items():
            if not self._select(i, delay=0.12):
                return
            if not self._click(*center(cx, cy), delay=0.05):
                return
            self._auto_actions += 1
        if not self._sleep(0.15):
            return
        unread = 0
        for i, (cx, cy) in dots.items():
            c = sample_color(*center(cx, cy), radius=0)
            if c and _cdist(c, painted[mk]) > 20 * 20 and far(c) > 20 * 20:
                painted[i] = c
            else:
                painted[i] = swatch[i]
                unread += 1
        if unread:
            self.log(f"{unread} couleur(s) non lue(s) après peinture, valeurs connues conservées")
        for i in range(n):
            if painted[i] is None:
                painted[i] = swatch[i]
        pal["painted"] = painted

        # 3. cinq reperes : ajustement fin de la taille et de la position des cases
        self._progress("3/5 repères de géométrie")
        dk = max((i for i in avail if i != mk), key=lambda i: min(_cdist(painted[i], painted[mk]), far(painted[i])))
        if not self._select(dk):
            return
        marks = [(m, top + 1), (W - 1 - m, top + 1), (m, H - 1 - m), (W - 1 - m, H - 1 - m), (W // 2, H // 2 + 3)]
        for cx, cy in marks:
            if not self._click(*center(cx, cy), delay=0.05):
                return
            self._auto_actions += 1
        if not self._sleep(0.15):
            return
        found = []
        for cx, cy in marks:
            fx = x1 + (cx + 0.5) * cw
            fy = y1 + (cy + 0.5) * ch
            found.append(self._find_dot(fx, fy, painted[dk], max(8, 2.5 * max(cw, ch))))
        if not all(found):
            raise RuntimeError(f"repères non retrouvés ({sum(1 for v in found if v)}/5) : vérifie que le crayon est sélectionné et le zoom au minimum")
        pw = sum((found[j][0] - found[i][0]) / (marks[j][0] - marks[i][0]) for i, j in ((0, 1), (2, 3))) / 2.0
        ph = sum((found[j][1] - found[i][1]) / (marks[j][1] - marks[i][1]) for i, j in ((0, 2), (1, 3))) / 2.0
        x0 = sum(fx - (cx + 0.5) * pw for (fx, _), (cx, _) in zip(found, marks)) / len(marks)
        y0 = sum(fy - (cy + 0.5) * ph for (_, fy), (_, cy) in zip(found, marks)) / len(marks)
        resid = max(max(abs(fx - (x0 + (cx + 0.5) * pw)), abs(fy - (y0 + (cy + 0.5) * ph)))
                    for (fx, fy), (cx, cy) in zip(found, marks))
        self.log(f"repères : cases {pw:.3f}×{ph:.3f} px (remplissage {cw:.3f}×{ch:.3f}), origine {x0:.1f},{y0:.1f} "
                 f"(remplissage {x1:.1f},{y1:.1f}), écart max {resid:.2f} px")
        if resid > max(1.5, 0.35 * min(pw, ph)):
            raise RuntimeError(f"repères incohérents (écart {resid:.1f} px) : le nombre de cases {W}×{H} est-il le bon ?")
        x1, y1, cw, ch = x0, y0, pw, ph
        x2, y2 = x1 + cw * W, y1 + ch * H
        f["rect"] = [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)]
        f["fill_inset"] = [round(x1 - fill_box[0], 2), round(y1 - fill_box[1], 2),
                           round(x2 - fill_box[2], 2), round(y2 - fill_box[3], 2)]

        # 4. rythme : trait zigzag de test, ralenti jusqu'a ce que le jeu suive
        self._progress("4/5 test du rythme des traits")
        self.step = float(d["step_delay"])
        self.stride = max(2.0, min(cw, ch)) if d.get("dense") else None
        self._cell_px = min(cw, ch)
        geo = (x1, y1, cw, ch, W, H)
        rows_t = list(range(top + 4, min(H - m - 2, top + 14)))
        cols_t = (m + 2, min(W - 1 - m, m + 60))
        cells = [-2] * (W * H)
        for yy in rows_t:
            for xx in range(cols_t[0], cols_t[1] + 1):
                cells[yy * W + xx] = dk
        idx = [i for i, v in enumerate(cells) if v == dk]
        strokes = build_strokes(cells, W, H, dk)
        best = None
        for attempt in range(5):
            for pts, _ in strokes:
                if not self._drag([center(*p) for p in pts]):
                    return
            self._auto_actions += len(strokes)
            if not self._sleep(0.15):
                return
            miss = self._missing(geo, cells, dk, idx)
            if miss is None:
                break
            self.log(f"rythme : essai {attempt + 1}, délai {self.step:.3f} s{' dense' if self.stride else ''}, "
                     f"{len(miss)}/{len(idx)} cases manquantes")
            if len(miss) <= len(idx) * 0.02:
                best = (self.step, bool(self.stride))
                break
            self._slower("le jeu perd des positions", dense=attempt >= 1)
        if best:
            # marge de 25 % : le rythme trouve est a la limite de ce que le jeu suit
            d["step_delay"] = round(min(0.12, best[0] * 1.25), 3)
            d["dense"] = best[1]
        else:
            self.log("rythme : pas de réglage fiable trouvé, la vérification corrigera pendant le dessin")

        # 5. validation : trois points a d'autres endroits doivent tomber exactement dans leur case
        self._progress("5/5 validation")
        vk = max((i for i in avail if i not in (mk, dk)), key=lambda i: min(_cdist(painted[i], painted[mk]), far(painted[i])))
        if not self._select(vk):
            return
        checks = [(W // 4, H * 3 // 4), (W * 3 // 4, H // 4), (W // 3, H // 2)]
        for cx, cy in checks:
            if not self._click(*center(cx, cy), delay=0.05):
                return
            self._auto_actions += 1
        if not self._sleep(0.15):
            return
        worst = 0.0
        for cx, cy in checks:
            fx, fy = x1 + (cx + 0.5) * cw, y1 + (cy + 0.5) * ch
            pos = self._find_dot(fx, fy, painted[vk], max(8, 2.5 * max(cw, ch)))
            if not pos:
                raise RuntimeError("validation : point non retrouvé à l'écran")
            worst = max(worst, abs(pos[0] - fx) / cw, abs(pos[1] - fy) / ch)
        self.log(f"validation : écart max {worst:.2f} case")
        if worst > 0.35:
            f["validated"] = False
            raise RuntimeError(f"validation échouée (écart {worst:.2f} case) : refais le calibrage manuel puis relance")
        f["validated"] = True
        try:
            self.save()
        except Exception:
            pass
        self.message = (f"Calibrage automatique validé pour {self.fmt} : cases {cw:.2f}×{ch:.2f} px, "
                        f"délai {d['step_delay']:.3f} s{' (point par case)' if d.get('dense') else ''}."
                        + ("" if d["tools"].get("undo") else " Ouvre un nouveau dessin vide avant de lancer le tien."))

    def outline_stats(self, job):
        """Statistiques du mode contours pour l'apercu (cases au crayon, zones au pot), ou None."""
        d = self.draw_cfg
        if not job or not d.get("outline", True):
            return None
        W, H = int(job["w"]), int(job["h"])
        cells = job["cells"]
        if len(cells) != W * H:
            return None
        skip = set(int(i) for i in job.get("skip", []))
        colors = self.colors()
        if d.get("skip_white"):
            skip.add(max(range(len(colors)), key=lambda i: sum(colors[i])))
        counts = {}
        for k in cells:
            if k >= 0 and k not in skip:
                counts[k] = counts.get(k, 0) + 1
        if not counts:
            return None
        fill_color = None
        if d.get("fill_background") and d["tools"].get("bucket") and d["tools"].get("pencil"):
            fill_color = max(sorted(counts), key=lambda k: counts[k])
        _, _, _, stats = plan_outline(cells, W, H, skip, fill_color)
        stats["available"] = bool(d["tools"].get("bucket") and d["tools"].get("pencil"))
        return stats

    def _missing(self, geo, cells, k, only=None):
        """Cases attendues en couleur k qui ne le sont pas a l'ecran. only : sous-ensemble d'indices."""
        seen = self._read_canvas(geo)
        if seen is None:
            return None
        idx = only if only is not None else range(len(cells))
        same = self._same(k)
        return [i for i in idx if cells[i] == k and seen[i] not in same]

    def _run(self, job, delay):
        self._t0 = time.perf_counter()
        if self.logfile:
            try:
                with open(self.logfile, "w", encoding="utf-8") as f:
                    f.write(f"DodoTopia dessin {time.strftime('%Y-%m-%d %H:%M:%S')} format {self.fmt}\n")
            except Exception:
                pass
        self.step = float(self.draw_cfg["step_delay"])
        self.unrepaired = 0
        self.progress_msg = ""
        try:
            end = time.perf_counter() + delay
            while True:
                rem = end - time.perf_counter()
                self.countdown = max(0.0, rem)
                if rem <= 0 or self._stop.is_set():
                    break
                time.sleep(0.05)
            self.countdown = 0.0
            if not self._stop.is_set():
                self._paint(job)
        except Exception as e:  # noqa
            self.log(f"erreur dessin : {e}")
            self.last_stop_reason = "erreur"
            self.message = f"Dessin impossible : {e}"
        finally:
            if self.last_stop_reason and self.last_stop_reason != "erreur":
                self.message = f"Dessin arrêté ({self.last_stop_reason}) : {self.done} / {self.total} cases peintes."
            try:
                mouse_up()
            except Exception:
                pass
            self.state = "idle"
            self.started_at = None
            self._expected_pos = None
            self._used = None
            self.progress_msg = ""
            self.log("dessin terminé" if not self.last_stop_reason else f"dessin arrêté ({self.last_stop_reason})")
            self.on_change()

    def _paint(self, job):
        d = self.draw_cfg
        fmt = self.fmt
        f = d["formats"][fmt]
        x1, y1, x2, y2 = [float(v) for v in f["rect"]]
        cols, rows = int(f["cols"]), int(f["rows"])
        W, H = int(job["w"]), int(job["h"])
        cells = job["cells"]
        if W != cols or H != rows or len(cells) != W * H:
            raise ValueError(f"grille {W}×{H} différente du calibrage {cols}×{rows}")
        cw, ch = (x2 - x1) / cols, (y2 - y1) / rows
        skip = set(int(i) for i in job.get("skip", []))
        if d.get("skip_white"):
            # la couleur la plus claire de la palette est consideree comme le blanc
            colors = self.colors()
            skip.add(max(range(len(colors)), key=lambda i: sum(colors[i])))
        tools = d["tools"]

        counts = {}
        for k in cells:
            if k >= 0 and k not in skip:
                counts[k] = counts.get(k, 0) + 1
        if not counts:
            self.message = "Rien à peindre."
            return
        if any(k >= len(SHADES) for k in counts):
            raise ValueError("couleurs inconnues dans l'image : recharge l'aperçu")
        avail = set(self.available())
        if any(k not in avail for k in counts):
            raise RuntimeError("l'image utilise des nuances : refais le calibrage en faisant les 6 étapes « nuances » (bouton palette, bande des familles, flèches, deux nuances)")
        order = sorted(counts, key=lambda k: -counts[k])
        fill_color = None
        if d.get("fill_background") and tools.get("bucket") and tools.get("pencil"):
            fill_color = order[0]
        outline = bool(d.get("outline", True)) and bool(tools.get("bucket")) and bool(tools.get("pencil"))
        if d.get("outline", True) and not outline:
            self.log("mode contours indisponible : calibre le crayon et le pot de peinture (étapes du calibrage)")

        # geometrie partagee (liste : les fonctions de centre lisent la valeur courante, corrigee en cours de
        # dessin par les reperes et les passes de reparation)
        geo = self._geo = [x1, y1, cw, ch, W, H]
        center = self._center_fn(geo)
        self._fill_box = None
        self._marks_done = set()
        self._last_seen = None
        self._cell_px = min(cw, ch)
        self.stride = None if not d.get("dense") else max(2.0, min(cw, ch))
        self._probed = self.stride is not None
        self.repaired = 0
        self._seen = None
        self.total = sum(counts.values())
        self.done = 0
        self.actions_done = 0
        self.actions_total = 0
        self.started_at = time.perf_counter()
        self._expected_pos = None
        self._check_mouse(*center(W // 2, H // 2))

        # toile vide (dessin neuf) ou deja entamee (reprise) : on lit l'ecran ; si des cases de l'image sont
        # deja en place, c'est une reprise et on ne peindra que ce qui manque
        colors = self.colors()
        cur = self._empties_setup(x1, y1, x2, y2, [colors[k] for k in counts])
        verify = d.get("verify", True) and SCREEN_OK
        refine = d.get("refine", True) and SCREEN_OK
        same = {k: self._same(k, colors) for k in counts}
        self._used = set().union(*same.values())
        seen = self._read_canvas(geo) if SCREEN_OK else None

        def in_place(seen_):
            return sum(1 for i, k in enumerate(cells) if k in same and seen_[i] in same[k]) if seen_ is not None else 0

        def pending_of(k, seen_):
            return [i for i, c in enumerate(cells) if c == k and (seen_ is None or seen_[i] not in same[k])]

        already = in_place(seen)
        # cases lues d'une couleur de palette qui contredit l'image : massif sur une toile uniforme (vide dont
        # les rayures ressemblent a une nuance), rare sur un dessin entame
        contra = sum(1 for i, k in enumerate(cells) if k in same and seen[i] >= 0 and seen[i] not in same[k])             if seen is not None else 0
        fresh = already <= 0.02 * self.total or contra >= 0.5 * self.total
        if self._settle_empties(cur, fresh, counts, colors) and seen is not None:
            seen = self._read_canvas(geo)
            already = in_place(seen)
        if not fresh:
            self.log(f"reprise d'un dessin : {already} cases déjà en place à l'écran, {self.total - already} à peindre")
            self.done = already
            if outline:
                self.log("mode contours : la reprise se fait au crayon, sur les cases manquantes")
                outline = False

        # plan : par couleur, traits en zigzag sans lever le crayon (le jeu trace la ligne entre deux
        # positions de souris : seuls les changements de direction sont envoyes)
        plan = []
        pencil = fills = ostats = None
        if outline:
            # mode contours : traits seulement sur les cases de contour, le reste au pot de peinture
            ostrokes, pencil, fills, ostats = plan_outline(cells, W, H, skip, fill_color)
            plan = [(k, ostrokes.get(k, [])) for k in order if k != fill_color]
            self.actions_total = sum(len(p) + 1 for _, strokes in plan for p, _ in strokes) + len(plan) + 4 \
                + 2 * ostats["fill_zones"] + 1
            self.log(f"dessin {fmt} : {self.total} cases, {len(plan) + 1} couleurs, "
                     f"{sum(len(s) for _, s in plan)} traits, {self.actions_total} actions ; mode contours : "
                     f"{ostats['pencil_cells']} cases au crayon, {ostats['fill_zones']} zones au pot ({ostats['fill_cells']} cases)")
        else:
            # reprise : le fond aussi passe au crayon la ou le pot ne l'aura pas atteint
            plan_colors = [k for k in order if k != fill_color] + ([fill_color] if fill_color is not None and not fresh else [])
            est = 0
            for k in plan_colors:
                pend = pending_of(k, seen)
                if pend:
                    sub = [-2] * (W * H)
                    for i in pend:
                        sub[i] = k
                    est += sum(len(p) + 1 for p, _ in build_strokes(sub, W, H, k, through=cells)) + 1
            self.actions_total = est + (4 if fill_color is not None else 1)
            self.log(f"dessin {fmt} : {self.total} cases, {len(plan_colors) + (1 if fill_color is not None and fresh else 0)} couleurs, "
                     f"{self.actions_total} actions" + ("" if fresh else " (reprise)"))

        # 1. fond au pot de peinture : toute la toile si elle est vide (puis mesure exacte du canevas sur le
        # rectangle rempli) ; en reprise, seulement la zone vide autour d'une case du fond encore vide
        if fill_color is not None:
            seed = None
            if fresh:
                seed = (W // 2, H // 2)
            elif seen is not None:
                empty_fill = [i for i, k in enumerate(cells) if k == fill_color and (seen[i] == -1 or seen[i] not in counts)]
                if empty_fill:
                    si = min(empty_fill, key=lambda i: (i % W - W / 2) ** 2 + (i // W - H / 2) ** 2)
                    seed = (si % W, si // W)
            if seed is not None:
                if not self._select(fill_color):
                    return
                if not self._click(*tools["bucket"], delay=0.15):
                    return
                if not self._click(*center(*seed), delay=0.3):
                    return
                if fresh:
                    self.done += counts[fill_color]
                    if refine and self._checkable(colors[fill_color]):
                        box = self._refine_by_fill(x1, y1, x2, y2, colors[fill_color])
                        if box:
                            self._fill_box = box
                            box = self._apply_inset(f, box)
                            self._apply_geo(box[0], box[1], (box[2] - box[0]) / W, (box[3] - box[1]) / H)
                            self.log(f"cases {geo[2]:.3f}×{geo[3]:.3f} px")
                else:
                    seen = self._read_canvas(geo)
                    self.done = in_place(seen)
            if not self._click(*tools["pencil"], delay=0.15):
                return
        else:
            if fresh and refine and tools.get("bucket") and tools.get("undo") and tools.get("pencil"):
                # remplissage temporaire avec la couleur la plus eloignee du fond vide, mesure, puis Annuler
                mk = max(sorted(avail), key=lambda i: min(_cdist(colors[i], e) for e in self._empty_colors) if self._empty_colors else 0)
                if not self._select(mk):
                    return
                if not self._click(*tools["bucket"], delay=0.15):
                    return
                if not self._click(*center(W // 2, H // 2), delay=0.3):
                    return
                box = self._refine_by_fill(x1, y1, x2, y2, colors[mk])
                if not self._click(*tools["undo"], delay=0.3):
                    return
                if box:
                    self._fill_box = box
                    box = self._apply_inset(f, box)
                    self._apply_geo(box[0], box[1], (box[2] - box[0]) / W, (box[3] - box[1]) / H)
                    self.log(f"cases {geo[2]:.3f}×{geo[3]:.3f} px")
            if tools.get("pencil"):
                if not self._click(*tools["pencil"], delay=0.15):
                    return

        # 2. crayon, couleur par couleur : seules les cases qui manquent a l'ecran ; reperes de geometrie sur la
        # premiere couleur verifiable ; verification et reparation apres chaque couleur
        if outline:
            self._paint_outline(plan, pencil, fills, cells, geo, verify, colors, d)
            return
        ncol = len(plan_colors)
        for ci, k in enumerate(plan_colors, 1):
            if self._stop.is_set():
                return
            if self._last_seen is not None:
                seen = self._last_seen
            pending = pending_of(k, seen)
            if not pending:
                continue
            self.progress_msg = f"Couleur {ci}/{ncol} : {len(pending)} cases"
            if not self._select(k):
                return
            # couleur proche du fond vide : impossible a verifier a l'ecran
            checkable = verify and self._checkable(colors[k])
            if refine and checkable and not self._marks_done:
                r = self._refine_marks(k, cells, seen, geo, colors)
                if r is None:
                    return
                if r:
                    seen = self._read_canvas(geo)
                    pending = pending_of(k, seen)
            sub = [-2] * (W * H)
            for i in pending:
                sub[i] = k
            if not self._paint_strokes(k, build_strokes(sub, W, H, k, through=cells), geo, cells, checkable):
                return
            if not checkable:
                continue
            if self._repair(k, cells, geo) is None:
                return

        # 3. verification finale de toutes les couleurs verifiables (une case peut avoir ete recouverte par un
        # clic voisin, un repere ou un trait decale)
        if verify:
            self.progress_msg = "Vérification finale"
            seen = self._read_canvas(geo)
            checks = list(plan_colors) + ([fill_color] if fill_color is not None and fill_color not in plan_colors else [])
            for k in checks:
                if seen is None or not self._checkable(colors[k]):
                    continue
                if pending_of(k, seen):
                    if self._repair(k, cells, geo, select=True) is None:
                        return
                    seen = self._last_seen if self._last_seen is not None else seen
        self.progress_msg = ""
        self.message = "Dessin terminé !" + (f" ({self.repaired} cases repeintes après vérification)" if self.repaired else "") + (
            "" if fresh else f" (reprise : {already} cases étaient déjà en place)") + (
            f" Attention : {self.unrepaired} cases n'ont pas pu être repeintes, voir le journal." if self.unrepaired else "")

    def _checkable(self, rgb):
        """Une couleur trop proche des rayures du canevas vide ne peut pas etre verifiee a l'ecran."""
        return all(_cdist(rgb, e) > 40 * 40 for e in self._empty_colors)

    @staticmethod
    def _center_fn(geo, ox=0.0, oy=0.0):
        x1, y1, cw, ch, W, H = geo
        return lambda cx, cy: [int(round(x1 + (cx + 0.5 + ox) * cw)), int(round(y1 + (cy + 0.5 + oy) * ch))]

    def _paint_strokes(self, k, strokes, geo, cells, checkable):
        """Trace les traits d'une couleur deja selectionnee. Sur le premier long trait, une sonde relit l'ecran
        et ralentit si le jeu a perdu des positions. False si le dessin est arrete."""
        W = geo[4]
        center = self._center_fn(geo)
        for pts, n in strokes:
            if len(pts) == 1:
                ok = self._click(*center(*pts[0]), delay=self.step)
            else:
                ok = self._drag([center(*p) for p in pts])
            if not ok:
                return False
            self.done += n
            self.on_change()
            if not self._probed and checkable and n >= 20:
                # sonde : le jeu a-t-il trace toute la ligne entre deux positions ?
                self._probed = True
                idx = _stroke_cells(pts, W)
                miss = self._missing(geo, cells, k, idx)
                geom = False
                if miss is not None and len(miss) > len(idx) * 0.05:
                    # le meme trait, a la meme vitesse : si les MEMES cases manquent encore, ce sont les clics
                    # qui tombent a la frontiere des cases (geometrie), pas des positions perdues (hasard) ;
                    # ralentir n'y changerait rien, la reparation et les reperes s'en chargent
                    if not self._drag([center(*p) for p in pts]):
                        return False
                    if not self._sleep(0.08):
                        return False
                    again = self._missing(geo, cells, k, idx)
                    if again is not None and len(again) > len(idx) * 0.05:
                        common = len(set(miss) & set(again))
                        geom = common >= 0.7 * min(len(miss), len(again))
                    miss = again
                if geom:
                    self.log(f"sonde : {len(miss)}/{len(idx)} cases manquantes, les mêmes deux fois de suite : "
                             f"clics à la frontière des cases (géométrie), pas un problème de rythme")
                elif miss is not None and len(miss) > len(idx) * 0.05:
                    # d'abord plus lent, puis un point par case si ca ne suffit pas
                    for k_try in range(3):
                        self._slower(f"sonde : {len(miss)}/{len(idx)} cases manquantes", dense=k_try >= 1)
                        if not self._drag([center(*p) for p in pts]):
                            return False
                        if not self._sleep(0.08):
                            return False
                        miss = self._missing(geo, cells, k, idx)
                        if miss is None or len(miss) <= len(idx) * 0.02:
                            break
                else:
                    self.log(f"sonde : lignes longues bien tracées ({len(miss) if miss is not None else '?'} manquante(s) sur {len(idx)})")
        return True

    def _shift_hint(self, miss, seen, cells, k, W, H):
        """Les cases manquantes sont-elles peintes a cote (dans une case voisine qui n'attend pas k) ? C'est un
        decalage des clics, pas des positions perdues par le jeu. Renvoie (decalage a essayer en cases, part
        des manquantes concernees) ; le decalage vaut None si rien ne se dessine."""
        if seen is None or not miss:
            return None, 0.0
        same = self._same(k)
        dirs = {(-1, 0): 0, (1, 0): 0, (0, -1): 0, (0, 1): 0}
        for i in miss:
            x, y = i % W, i // W
            for dx, dy in dirs:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    j = ny * W + nx
                    if cells[j] != k and seen[j] in same:
                        dirs[(dx, dy)] += 1
        (dx, dy), n = max(dirs.items(), key=lambda kv: kv[1])
        frac = n / len(miss)
        if frac < 0.4:
            return None, frac
        return (-0.3 * dx, -0.3 * dy), frac      # la peinture est au-dessus : il faut cliquer plus bas

    def _repair(self, k, cells, geo, only=None, select=False):
        """Reparation : jusqu'a 5 passes sur les cases de couleur k encore manquantes (only : sous-ensemble
        d'indices). A partir de la 2e passe le clic est decale d'un tiers de case (gauche, droite, haut, bas ;
        d'abord dans la direction ou la peinture est visiblement partie, voir _shift_hint) : quand le centre
        calcule tombe sur la frontiere entre deux cases du jeu, une position un peu decalee tombe dedans. Si la
        premiere passe n'a presque rien repare, la geometrie est d'abord re-mesuree sur des reperes (voir
        _refine_marks) ; et si un decalage a nettement mieux marche que le centre, il est adopte pour toute la
        suite du dessin. On ne ralentit jamais ici : une passe inefficace au meme rythme prouve que ce n'est pas
        le rythme (l'ancienne version ralentissait a chaque couleur, jusqu'a un dessin quatre fois plus lent).
        select : selectionner la couleur avant de repeindre (sinon elle l'est deja). Retourne la liste des cases
        restantes, ou None si le dessin est arrete."""
        W, H = geo[4], geo[5]
        saved_stride = self.stride
        prev = None
        miss = []
        selected = not select
        nudges = [(0, 0), (-0.3, 0), (0.3, 0), (0, -0.3), (0, 0.3)]
        queue = list(nudges)
        attempt = 0
        history = []          # [decalage, manquantes avant la passe, manquantes apres]
        marks_tried = k in self._marks_done or not self.draw_cfg.get("refine", True)
        while queue:
            ox, oy = queue.pop(0)
            if self._stop.is_set():
                return None
            if not self._sleep(0.08):
                return None
            miss = self._missing(geo, cells, k, only)
            if history:
                history[-1][2] = len(miss) if miss is not None else None
            if miss is None or not miss:
                miss = miss or []
                break
            if not selected:
                if not self._select(k):
                    return None
                selected = True
            hint, frac = self._shift_hint(miss, self._last_seen, cells, k, W, H)
            if hint is not None and attempt == 0 and (ox, oy) == (0, 0):
                # la peinture est a cote : on essaie tout de suite dans la bonne direction
                self.log(f"réparation : {frac:.0%} des cases manquantes sont peintes à côté, clic décalé de "
                         f"{hint[0]:+.1f},{hint[1]:+.1f} case d'abord")
                queue.insert(0, (0, 0))
                ox, oy = hint
            if prev is not None and len(miss) > prev * 0.7 and attempt <= 1 and hint is None and not marks_tried:
                # repeindre les memes cases n'a rien change : les clics tombent a cote (geometrie), on mesure
                # les reperes avant d'essayer les decalages (ralentir ne servirait a rien : ancienne erreur)
                marks_tried = True
                r = self._refine_marks(k, cells, self._last_seen, geo)
                if r is None:
                    return None
                if r:
                    queue, attempt, prev, history = list(nudges), 0, None, []
                    continue
            prev = len(miss)
            self.log(f"réparation {attempt + 1} : {len(miss)} case(s) manquante(s)"
                     + (f", clic décalé de {ox:+.1f},{oy:+.1f} case" if (ox or oy) else ""))
            history.append([(ox, oy), len(miss), None])
            self.stride = max(2.0, min(geo[2], geo[3]))
            sub = [-2] * (W * H)
            for i in miss:
                sub[i] = k
            pt = self._center_fn(geo, ox, oy)
            for pts, n in build_strokes(sub, W, H, k):
                if len(pts) == 1:
                    ok = self._click(*pt(*pts[0]), delay=self.step)
                else:
                    ok = self._drag([pt(*p) for p in pts])
                if not ok:
                    return None
                self.repaired += n
            self.on_change()
            attempt += 1
        if history and history[-1][2] is None:
            # la derniere passe a peint sans relecture : on lit, sinon son resultat (souvent le bon decalage,
            # essaye en dernier) serait ignore et les cases annoncees manquantes a tort
            if not self._sleep(0.08):
                return None
            miss = self._missing(geo, cells, k, only)
            if miss is None:
                miss = []
            history[-1][2] = len(miss)
        # decalage appris : si un clic decale a repare bien mieux que le centre, les centres etaient a cote
        gains = {}
        for nudge, before, after in history:
            if after is not None and before:
                gains[nudge] = max(gains.get(nudge, 0.0), 1 - after / before)
        best = max((n for n in gains if n != (0, 0)), key=lambda n: gains[n], default=None)
        if best is not None and gains[best] >= 0.5 and gains.get((0, 0), 0.0) < 0.5:
            ox, oy = best
            self._apply_geo(geo[0] + ox * geo[2], geo[1] + oy * geo[3], geo[2], geo[3])
            self.log(f"décalage appris : les clics tombent juste à {ox:+.1f},{oy:+.1f} case du centre calculé, "
                     f"géométrie corrigée pour la suite")
        if miss:
            cols_ = sorted(set(i % W for i in miss))
            rows_ = sorted(set(i // W for i in miss))
            self.log(f"couleur {k} : cases manquantes en colonnes {cols_[:12]}{'…' if len(cols_) > 12 else ''}"
                     f" et lignes {rows_[:12]}{'…' if len(rows_) > 12 else ''}")
            self.log(f"couleur {k} : {len(miss)} case(s) restent manquantes")
        self.unrepaired += len(miss)
        self.stride = saved_stride
        return miss

    # ---- mode contours + pot de peinture
    def _paint_outline(self, plan, pencil, fills, cells, geo, verify, colors, d):
        """A. contours de chaque couleur au crayon ; A'. verification des contours (un contour troue = fuite du
        pot) ; B. pot de peinture dans chaque zone, avec detection des fuites (Annuler + crayon de secours) ;
        C. crayon de secours puis verification finale."""
        x1, y1, cw, ch, W, H = geo
        center = self._center_fn(geo)
        tools = d["tools"]
        ncol = sum(1 for _, s in plan if s)
        nz = sum(len(v) for v in fills.values())
        npencil = sum(len(v) for v in pencil.values())
        # A. contours
        i = 0
        for k, strokes in plan:
            if not strokes:
                continue
            i += 1
            self.progress_msg = f"Contours : couleur {i}/{ncol}"
            if self._stop.is_set() or not self._select(k):
                return
            checkable = verify and self._checkable(colors[k])
            if checkable and d.get("refine", True) and not self._marks_done:
                if self._refine_marks(k, cells, self._read_canvas(geo), geo, colors) is None:
                    return
            if not self._paint_strokes(k, strokes, geo, cells, checkable):
                return
        # A'. verification des contours
        if verify:
            self.progress_msg = "Vérification des contours"
            for k, strokes in plan:
                if not strokes or not self._checkable(colors[k]):
                    continue
                if self._repair(k, cells, geo, only=sorted(pencil[k]), select=True) is None:
                    return
        # B. pot de peinture
        fallback = {}
        nleak = 0
        if nz:
            can_undo = bool(tools.get("undo"))
            if verify and not can_undo:
                self.log("bouton Annuler non calibré : les fuites du pot de peinture ne seront pas détectées")
            self._seen = self._read_canvas(geo) if verify and can_undo else None
            z = 0
            for k, _ in plan:
                comps = fills.get(k) or []
                if not comps:
                    continue
                if self._stop.is_set() or not self._select(k):
                    return
                if not self._click(*tools["bucket"], delay=0.15):
                    return
                checkable = verify and can_undo and self._seen is not None and self._checkable(colors[k])
                same = {k} | {i for i, c in enumerate(colors) if _cdist(c, colors[k]) < 18 * 18}
                for seed, comp in comps:
                    z += 1
                    self.progress_msg = f"Remplissage : zone {z}/{nz}"
                    if self._stop.is_set():
                        return
                    if not self._click(*center(seed % W, seed // W), delay=0.3):
                        return
                    ok = True
                    if checkable:
                        ok = self._check_fill(k, same, seed, comp, cells, geo, tools)
                        if ok is None:
                            return
                    if ok:
                        self.done += len(comp)
                    else:
                        nleak += 1
                        fallback.setdefault(k, []).extend(comp)
                    self.on_change()
        # C. crayon de secours + verification finale
        if not self._click(*tools["pencil"], delay=0.15):
            return
        for k, idx in fallback.items():
            self.progress_msg = f"Crayon de secours : {len(idx)} cases"
            if self._stop.is_set() or not self._select(k):
                return
            sub = [-2] * (W * H)
            for i in idx:
                sub[i] = k
            if not self._paint_strokes(k, build_strokes(sub, W, H, k), geo, cells, False):
                return
        if verify:
            self.progress_msg = "Vérification finale"
            for k, _ in plan:
                if not self._checkable(colors[k]):
                    continue
                if self._repair(k, cells, geo, select=True) is None:
                    return
        self.progress_msg = ""
        self.message = ("Dessin terminé !"
                        + f" ({nz - nleak} zone(s) remplies au pot, {npencil} cases au crayon"
                        + (f", {nleak} zone(s) repeintes au crayon après une fuite" if nleak else "") + ")"
                        + (f" ({self.repaired} cases repeintes après vérification)" if self.repaired else "")
                        + (f" Attention : {self.unrepaired} cases n'ont pas pu être repeintes, voir le journal." if self.unrepaired else ""))

    def _check_fill(self, k, same, seed, comp, cells, geo, tools):
        """Apres un clic du pot : la zone est-elle remplie sans deborder ? True : ok ; False : zone a repeindre
        au crayon (l'eventuelle fuite a ete annulee) ; None : dessin arrete."""
        W = geo[4]
        seen = self._read_canvas(geo)
        if seen is None:
            return True
        prev = self._seen
        leak = [i for i in range(len(cells)) if cells[i] != k and seen[i] in same and prev[i] not in same]
        if leak:
            self.log(f"fuite du pot de peinture (couleur {k}, zone de {len(comp)} cases, {len(leak)} cases débordées) : "
                     f"Annuler, la zone sera peinte au crayon")
            if not self._click(*tools["undo"], delay=0.3):
                return None
            return False
        if seen[seed] not in same:
            # la graine n'a pas ete remplie (clic sur une frontiere de case ?) : un essai decale d'un tiers de case
            self.log(f"zone non remplie (couleur {k}, case {seed % W},{seed // W}) : nouvel essai décalé")
            if not self._click(*self._center_fn(geo, 0.3, 0.3)(seed % W, seed // W), delay=0.3):
                return None
            seen = self._read_canvas(geo)
            if seen is None:
                return True
            leak = [i for i in range(len(cells)) if cells[i] != k and seen[i] in same and prev[i] not in same]
            if leak:
                self.log(f"fuite du pot de peinture après le second essai ({len(leak)} cases) : Annuler")
                if not self._click(*tools["undo"], delay=0.3):
                    return None
                return False
            if seen[seed] not in same:
                self.log("zone toujours vide : elle sera peinte au crayon")
                return False
        self._seen = seen
        return True

    # ---- etat pour l'interface
    def status(self):
        d = self.draw_cfg
        elapsed = (time.perf_counter() - self.started_at) if self.started_at else 0.0
        eta = None
        if self.state == "drawing" and self.actions_done > 3 and self.actions_total:
            eta = elapsed / self.actions_done * (self.actions_total - self.actions_done)
        st = {
            "state": self.state,
            "progress_msg": getattr(self, "progress_msg", ""),
            "validated": {fmt: bool(d["formats"].get(fmt, {}).get("validated")) for fmt in FORMATS},
            "format": self.fmt,
            "step": self.step,
            "steps": [{"key": k, "title": t, "help": h} for k, t, h in STEPS],
            "done": self.done, "total": self.total,
            "countdown": round(self.countdown, 1),
            "elapsed": elapsed, "eta": eta,
            "message": self.message,
            "stop_reason": self.last_stop_reason,
            "palette": self.colors(),
            "palette_main": SHADE_MAIN,
            "shades_ok": self.shades_ok(),
            "formats": {fmt: {"cols": format_grid(self.cfg, fmt)[0], "rows": format_grid(self.cfg, fmt)[1],
                              "calibrated": self.calibrated(fmt)} for fmt in FORMATS},
            "tools": {k: bool(v) for k, v in d["tools"].items()},
            "settings": {"step_delay": d["step_delay"], "click_delay": d["click_delay"],
                         "fill_background": bool(d["fill_background"]), "skip_white": bool(d["skip_white"]),
                         "verify": bool(d.get("verify", True)), "dense": bool(d.get("dense", False)),
                         "refine": bool(d.get("refine", True)), "outline": bool(d.get("outline", True)),
                         "mouse_glide": bool(d.get("mouse_glide", True)), "glide_speed": float(d.get("glide_speed", 1.0))},
            "repaired": self.repaired,
            "unrepaired": self.unrepaired,
            "step": self.step,
            "screen_ok": SCREEN_OK,
        }
        return st
