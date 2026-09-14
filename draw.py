# -*- coding: utf-8 -*-
"""Dessin dans Heartopia : calibrage (canevas, palette, outils) et peinture case par case a la souris."""
import threading
import time

from bot import MouseBot
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
        """Pour chaque case, l'index de la couleur de palette vue a l'ecran (-1 = vide / inconnu)."""
        x1, y1, cw, ch, W, H = geo
        im = grab((x1, y1, int(round(x1 + cw * W)), int(round(y1 + ch * H))))
        if im is None:
            return None
        px = im.load()
        iw, ih = im.size
        colors = self.colors()
        empties = self._empty_colors
        cache = {}
        out = [-1] * (W * H)
        for cy in range(H):
            py = min(ih - 1, int((cy + 0.5) * ch))
            for cx in range(W):
                pxx = min(iw - 1, int((cx + 0.5) * cw))
                c = px[pxx, py][:3]
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
                    cache[key] = k
                out[cy * W + cx] = k
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
        im = grab((int(x - radius), int(y - radius), int(x + radius + 1), int(y + radius + 1)))
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
        return (x - radius + (min(xs) + max(xs)) / 2.0, y - radius + (min(ys) + max(ys)) / 2.0)

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

    def _refine_geometry(self, cells, W, H, x1, y1, cw, ch, color, cell_a, cell_b):
        """Peint deux cases repères, les retrouve a l'ecran et en deduit la taille et la position exactes
        des cases. Retourne (x1, y1, cw, ch) corriges, ou None."""
        (ax, ay), (bx, by) = cell_a, cell_b
        if bx - ax < 10 or by - ay < 10:
            return None
        if not self._select(color):
            return None
        found = []
        for cx, cy in (cell_a, cell_b):
            px_ = x1 + (cx + 0.5) * cw
            py_ = y1 + (cy + 0.5) * ch
            if not self._click(int(round(px_)), int(round(py_)), delay=0.12):
                return None
            found.append(self._find_dot(px_, py_, self.colors()[color], max(8, 3.0 * max(cw, ch))))
        if not all(found):
            self.log("repères non retrouvés à l'écran, géométrie du calibrage conservée")
            return None
        (fax, fay), (fbx, fby) = found
        ncw = (fbx - fax) / (bx - ax)
        nch = (fby - fay) / (by - ay)
        if not (0.8 * cw < ncw < 1.2 * cw and 0.8 * ch < nch < 1.2 * ch):
            self.log(f"repères incohérents (cases {ncw:.2f}×{nch:.2f} px au lieu de {cw:.2f}×{nch:.2f}), calibrage conservé")
            return None
        nx1 = min((fax - (ax + 0.5 + k) * ncw for k in range(-2, 3)), key=lambda v: abs(v - x1))
        ny1 = min((fay - (ay + 0.5 + k) * nch for k in range(-2, 3)), key=lambda v: abs(v - y1))
        self.log(f"géométrie affinée : cases {ncw:.3f}×{nch:.3f} px (calibrage {cw:.3f}×{ch:.3f}), "
                 f"origine décalée de {nx1 - x1:+.1f},{ny1 - y1:+.1f} px")
        return nx1, ny1, ncw, nch

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
        cols = self.colors()
        ck = cols[k]
        # certaines nuances de familles voisines sont quasi identiques : on les accepte
        same = {k} | {i for i, c in enumerate(cols) if _cdist(c, ck) < 18 * 18}
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

        def center(cx, cy):
            return [int(round(x1 + (cx + 0.5) * cw)), int(round(y1 + (cy + 0.5) * ch))]

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
        if d.get("fill_background") and d["tools"].get("bucket") and d["tools"].get("pencil"):
            fill_color = order[0]

        # plan : par couleur, traits en zigzag sans lever le crayon (le jeu trace la ligne entre deux
        # positions de souris : seuls les changements de direction sont envoyes)
        outline = bool(d.get("outline", True)) and bool(d["tools"].get("bucket")) and bool(d["tools"].get("pencil"))
        if d.get("outline", True) and not outline:
            self.log("mode contours indisponible : calibre le crayon et le pot de peinture (étapes du calibrage)")
        plan = []   # (couleur, [strokes]) ; stroke = (points en coordonnees cases, nb de cases)
        pencil = fills = None
        if outline:
            # mode contours : traits seulement sur les cases de contour, le reste au pot de peinture
            ostrokes, pencil, fills, ostats = plan_outline(cells, W, H, skip, fill_color)
            for k in order:
                if k == fill_color:
                    continue
                plan.append((k, ostrokes.get(k, [])))
        else:
            for k in order:
                if k == fill_color:
                    continue
                plan.append((k, build_strokes(cells, W, H, k)))
        self.total = sum(counts.values())
        self.done = 0
        self.actions_done = 0
        self.actions_total = sum(len(p) + 1 for _, strokes in plan for p, _ in strokes) + len(plan) + (
            4 if fill_color is not None else (1 if d["tools"].get("pencil") else 0))
        if outline:
            self.actions_total += 2 * ostats["fill_zones"] + 1
        self.started_at = time.perf_counter()
        self.log(f"dessin {fmt} : {self.total} cases, {len(plan) + (1 if fill_color is not None else 0)} couleurs, "
                 f"{sum(len(s) for _, s in plan)} traits, {self.actions_total} actions"
                 + (f" ; mode contours : {ostats['pencil_cells']} cases au crayon, {ostats['fill_zones']} zones au pot "
                    f"({ostats['fill_cells']} cases)" if outline else ""))
        self._expected_pos = None
        self._check_mouse(*center(W // 2, H // 2))
        # teintes du canevas vide (rayures), lues avant le premier coup de pinceau
        self._empty_colors = []
        for fx, fy in ((0.5, 0.5), (0.25, 0.25), (0.75, 0.75), (0.5, 0.25)):
            c = sample_color(int(x1 + (x2 - x1) * fx), int(y1 + (y2 - y1) * fy), radius=1)
            if c:
                self._empty_colors.append(c)

        refine = d.get("refine", True) and SCREEN_OK
        colors = self.colors()

        def apply_geo(nx1, ny1, ncw, nch):
            nonlocal x1, y1, x2, y2, cw, ch
            x1, y1, cw, ch = nx1, ny1, ncw, nch
            x2, y2 = x1 + cw * W, y1 + ch * H
            f["rect"] = [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)]
            try:
                self.save()
            except Exception:
                pass

        # 1. remplissage du fond, puis mesure exacte du canevas sur le rectangle rempli
        if fill_color is not None:
            if not self._select(fill_color):
                return
            if not self._click(*d["tools"]["bucket"], delay=0.15):
                return
            if not self._click(*center(W // 2, H // 2), delay=0.3):
                return
            self.done += counts[fill_color]
            if refine and all(_cdist(colors[fill_color], e) > 40 * 40 for e in self._empty_colors):
                box = self._refine_by_fill(x1, y1, x2, y2, colors[fill_color])
                if box:
                    box = self._apply_inset(f, box)
                    apply_geo(box[0], box[1], (box[2] - box[0]) / W, (box[3] - box[1]) / H)
                    self.log(f"cases {cw:.3f}×{ch:.3f} px")
            if not self._click(*d["tools"]["pencil"], delay=0.15):
                return
        else:
            measured = False
            if refine and d["tools"].get("bucket") and d["tools"].get("undo") and d["tools"].get("pencil"):
                # remplissage temporaire avec la couleur la plus eloignee du fond vide, mesure, puis Annuler
                mk = max(sorted(avail), key=lambda i: min(_cdist(colors[i], e) for e in self._empty_colors) if self._empty_colors else 0)
                if not self._select(mk):
                    return
                if not self._click(*d["tools"]["bucket"], delay=0.15):
                    return
                if not self._click(*center(W // 2, H // 2), delay=0.3):
                    return
                box = self._refine_by_fill(x1, y1, x2, y2, colors[mk])
                if not self._click(*d["tools"]["undo"], delay=0.3):
                    return
                if box:
                    box = self._apply_inset(f, box)
                    apply_geo(box[0], box[1], (box[2] - box[0]) / W, (box[3] - box[1]) / H)
                    self.log(f"cases {cw:.3f}×{ch:.3f} px")
                    measured = True
            if d["tools"].get("pencil"):
                if not self._click(*d["tools"]["pencil"], delay=0.15):
                    return
            if refine and not measured:
                # deux cases reperes de la couleur principale, a 3 cases des bords
                m = 3
                k0 = order[0]
                own = [(i % W, i // W) for i, c in enumerate(cells)
                       if c == k0 and m <= i % W < W - m and m <= i // W < H - m]
                if not own:
                    own = [(i % W, i // W) for i, c in enumerate(cells) if c == k0]
                cell_a = min(own, key=lambda p: p[0] + p[1])
                cell_b = max(own, key=lambda p: p[0] + p[1])
                geo_new = self._refine_geometry(cells, W, H, x1, y1, cw, ch, k0, cell_a, cell_b)
                if self._stop.is_set():
                    return
                if geo_new:
                    apply_geo(*geo_new)

        # 2. crayon, couleur par couleur, avec verification a l'ecran et reparation
        geo = (x1, y1, cw, ch, W, H)
        self._cell_px = min(cw, ch)
        verify = d.get("verify", True) and SCREEN_OK
        colors = self.colors()
        self.stride = None if not d.get("dense") else max(2.0, min(cw, ch))
        self._probed = self.stride is not None
        self.repaired = 0
        self._seen = None
        if outline:
            self._paint_outline(plan, pencil, fills, cells, geo, verify, colors, d)
            return
        for k, strokes in plan:
            if self._stop.is_set():
                return
            if not self._select(k):
                return
            # couleur proche du fond vide : impossible a verifier a l'ecran
            checkable = verify and self._checkable(colors[k])
            if not self._paint_strokes(k, strokes, geo, cells, checkable):
                return
            if not checkable:
                continue
            if self._repair(k, cells, geo) is None:
                return
        self.message = "Dessin terminé !" + (f" ({self.repaired} cases repeintes après vérification)" if self.repaired else "") + (
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
                if miss is not None and len(miss) > len(idx) * 0.05:
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

    def _repair(self, k, cells, geo, only=None, select=False):
        """Reparation : jusqu'a 5 passes sur les cases de couleur k encore manquantes (only : sous-ensemble
        d'indices). A partir de la 2e passe le clic est decale d'un tiers de case (gauche, droite, haut, bas) :
        quand le centre calcule tombe sur la frontiere entre deux cases du jeu, une position un peu decalee
        tombe dedans. select : selectionner la couleur avant de repeindre (sinon elle l'est deja).
        Retourne la liste des cases restantes, ou None si le dessin est arrete."""
        x1, y1, cw, ch, W, H = geo
        saved_stride = self.stride
        prev = None
        miss = []
        selected = not select
        nudges = [(0, 0), (-0.3, 0), (0.3, 0), (0, -0.3), (0, 0.3)]
        for attempt, (ox, oy) in enumerate(nudges):
            if self._stop.is_set():
                return None
            if not self._sleep(0.08):
                return None
            miss = self._missing(geo, cells, k, only)
            if miss is None or not miss:
                miss = miss or []
                break
            if not selected:
                if not self._select(k):
                    return None
                selected = True
            if prev is not None and len(miss) > prev * 0.7 and attempt <= 1:
                self._slower(f"réparation inefficace ({prev} → {len(miss)} manquantes)", dense=True)
            prev = len(miss)
            self.log(f"réparation {attempt + 1} : {len(miss)} case(s) manquante(s)"
                     + (f", clic décalé de {ox:+.1f},{oy:+.1f} case" if (ox or oy) else ""))
            self.stride = max(2.0, min(cw, ch))
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
            if not self._paint_strokes(k, strokes, geo, cells, verify and self._checkable(colors[k])):
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
