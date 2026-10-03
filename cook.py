# -*- coding: utf-8 -*-
"""Cuisine en boucle dans Heartopia : clic sur la bulle de la cuisiniere, menu Recettes (derniere recette
utilisee, bouton Cuisiner), surveillance de la cuisson (clic sur la spatule quand l'anneau vert apparait),
recuperation du plat, fermeture de l'animation eventuelle, et on recommence.

Detection a l'ecran (Pillow seulement) : la bulle est cherchee dans un rectangle calibre par la forme
de son icone blanche (masque des pixels blancs compare aux references capturees au calibrage, score de
Jaccard) ; l'anneau vert de la spatule est compte autour de la bulle ; le menu Recettes est reconnu par la
couleur du bouton Cuisiner."""
import base64
import io
import os
import threading
import math
import time

from bot import MouseBot, screen_changed, screen_fingerprint
from draw import sample_color, _cdist
from platform_io import cursor_pos, grab, mouse_up, SCREEN_OK

REF = 72            # cote (px) du masque de reference d'une icone
GRAB = 110          # zone lue autour de la souris au calibrage
LOCAL = 16          # suivi local : rayon (px) autour de la derniere position
COARSE = 8          # recherche large : pas (px) de la grille
RING = 56           # rayon (px) de la zone ou l'on compte le vert de l'anneau
WHITE = 200         # seuil pixel blanc (sur les 3 canaux)

MAX_COOKERS = 4     # nombre maximal de cuisinieres servies par la boucle (borne du reglage cook.cookers)
SEP = REF           # deux detections a moins de SEP px l'une de l'autre sont la meme bulle
ASSOC = 70          # tolerance (px) autour de la position ATTENDUE d'une bulle (apres le glissement commun)
STILL = 6           # une bulle qui bouge de plus de STILL px entre deux lectures est « en mouvement »
CAM_WINDOW = 4.5    # la camera ne bouge que dans les secondes qui suivent un clic sur une bulle (le personnage
                    # marche) : hors de cette fenetre, une bulle lointaine est une AUTRE cuisiniere, pas un glissement
READY_AGAIN = 3.0   # secondes : des gants recliques au meme endroit dans ce delai sont le meme plat (clic pas pris)
READY_SOFT = 0.56   # score « gants » qui suffit a la relecture juste avant le clic (le seuil normal est cook.match)
RING_PENDING = 1.5  # secondes au plus a attendre qu'un anneau vert vu une fois devienne stable avant de faire autre chose
CAM_SETTLE = 3.0    # secondes de recherche large forcee apres un clic sur une autre cuisiniere (la camera bouge)
WIDE_EVERY = 0.7    # secondes entre deux recherches larges quand toutes les bulles sont suivies
RING_MIN, RING_MAX = 60, 150   # cote (px) plausible de la boite englobante d'un anneau vert en 1080p
CELL = 8            # maille (px) de la grille qui regroupe les pixels verts en anneaux
PEAKS_MAX = 12      # pics gardes par une recherche large avant l'affinage (garde-fou)

DEFAULT_COOK = {
    "points": {},            # search [x1,y1,x2,y2] ; cook, tile, cook_btn, ready, neutral, spatula : [x, y]
    "cook_btn_color": None,  # couleur du bouton Cuisiner quand le menu est ouvert
    "ring_color": None,      # couleur de l'anneau vert lue au calibrage (etape spatule)
    "refs": {},              # cook / spatula / ready : {"png": masque 1 bit en base64}
    "cookers": 1,            # nombre de cuisinieres a servir (1 a MAX_COOKERS) ; leurs bulles doivent
                             # toutes tenir dans la zone de recherche calibree
    "max_dishes": 0,         # 0 = sans fin
    "cook_timeout": 240.0,   # secondes max pour qu'un plat soit pret
    "poll": 0.1,             # secondes entre deux lectures de l'ecran
    "match": 0.62,           # score minimal (Jaccard) pour reconnaitre une icone
    "red_ring": True,        # l'anneau passe au jaune, a l'orange ou au rouge se clique aussi, le plus rouge d'abord
    "green_px": 60,          # pixels verts minimum pour l'anneau de la spatule
    "click_delay": 0.3,      # secondes apres un clic
    # --- ordonnanceur multi-cuisinieres (voir Cooker._may_launch)
    # Lancer une cuisson couvre l'ecran avec le menu Recettes pendant 1 a 2 s : un anneau vert (« Ajuste le
    # feu ») qui apparaitrait ailleurs a ce moment-la n'est vu qu'a la fermeture du menu, puis clique en
    # priorite. launch_guard = secondes pendant lesquelles on s'interdit de lancer ailleurs apres un lancement
    # ou un feu ajuste. Releves en jeu (2026-09-21) : l'anneau arrive entre 3,5 et 8 s apres le lancement, 1 a
    # 3 fois par plat : l'ancien defaut (8 s, rearme a chaque feu) faisait attendre la 2e cuisiniere tres
    # longtemps et placait son lancement pile a l'heure de l'anneau de la 1re. Defaut : 0 (on lance des que
    # possible, le menu reste ouvert le moins longtemps possible). Reglage sans interface (config.json) a
    # remonter si des plats sont rates pendant un lancement.
    "launch_guard": 0.0,     # secondes de « fenetre de risque » apres un lancement / un feu ajuste (0 = aucune)
    # Priorite aux spatules (demande du proprietaire, 2026-10-03) : tant qu'une spatule SANS anneau est a l'ecran,
    # l'anneau vert arrive d'habitude dans les 2 s ; on ne recupere rien et on ne lance rien pendant spatula_wait
    # secondes au plus (0 = ne pas attendre), pour avoir la souris libre a l'arrivee de l'anneau.
    "spatula_wait": 5.0,
    "launch_anytime": False, # True : lancer une cuisson meme si une autre cuisiniere est dans sa fenetre
}

STEPS = [
    ("search_tl", "Zone de recherche : coin haut-gauche",
     "Place-toi devant la cuisinière dans le jeu. La bulle d'interaction apparaît au-dessus d'elle ; elle peut bouger un peu. "
     "Survole le coin haut-gauche d'une zone assez large autour de la bulle (sans les icônes du jeu en haut) et appuie sur F3."),
    ("search_br", "Zone de recherche : coin bas-droit",
     "Survole le coin bas-droit de cette même zone (la bulle doit toujours pouvoir s'y trouver), puis F3."),
    ("cook", "Bulle « cuisiner »",
     "Sans cliquer, place la souris au centre de la bulle ronde avec l'icône de cuisine (au-dessus de la cuisinière) et appuie sur F3 : "
     "DodoTopia mémorise la forme de l'icône."),
    ("tile", "Menu Recettes : la première tuile récente",
     "Clique sur la bulle pour ouvrir le menu Recettes. Survole la première tuile de « Utilisation récente » (en haut à gauche : "
     "c'est la dernière recette cuisinée, celle qui sera refaite en boucle), puis F3."),
    ("cook_btn", "Menu Recettes : le bouton « Cuisiner »",
     "Toujours dans le menu, survole le gros bouton « Cuisiner » (en bas à droite) et appuie sur F3 : sa couleur sert à savoir si le menu est ouvert."),
    ("spatula", "Bulle « spatule » avec l'anneau vert (facultatif, conseillé)",
     "Lance une cuisson (clique sur Cuisiner). Quand le jeu affiche « Ajuste le feu… » et que la bulle montre la spatule entourée d'un anneau vert, "
     "survole le centre de la bulle et appuie sur F3 (puis clique dessus toi-même pour ne pas brûler le plat). "
     "Sinon « Passer » : l'anneau sera reconnu par sa couleur verte standard."),
    ("ready", "Bulle « récupérer » (gants)",
     "À la fin de la cuisson, la bulle montre des gants : sans cliquer, survole son centre et appuie sur F3."),
    ("neutral", "Un endroit vide où cliquer",
     "Survole un coin d'herbe vide (loin de la bulle et des boutons) et appuie sur F3 : c'est là que DodoTopia cliquera pour fermer "
     "l'animation d'un plat amélioré. Tu peux ensuite récupérer ton plat."),
]
OPTIONAL = ("spatula",)
REQUIRED = ("search", "tile", "cook_btn", "neutral")
ICON_STEPS = ("cook", "spatula", "ready")      # recalibrage des icones seulement
SAME_ICON = 0.85                               # au-dela, deux references sont la meme icone


def ensure_defaults(cfg):
    c = cfg.setdefault("cook", {})
    for k, v in DEFAULT_COOK.items():
        if k not in c:
            c[k] = v if not isinstance(v, (dict, list)) else __import__("copy").deepcopy(v)
    if c.get("launch_guard") == 8.0:
        c["launch_guard"] = DEFAULT_COOK["launch_guard"]   # ancien defaut : la 2e cuisiniere attendait trop
    if c.get("match") == 0.55:
        c["match"] = DEFAULT_COOK["match"]     # ancien defaut, trop proche des scores entre icones (0.53)
    try:
        c["cookers"] = max(1, min(MAX_COOKERS, int(c.get("cookers", 1) or 1)))
    except (TypeError, ValueError):
        c["cookers"] = 1
    return c


# ---------------------------------------------------------------- masques (Pillow, tout en C)
def _lut(lo=None, hi=None):
    return [255 if (lo is None or v > lo) and (hi is None or v < hi) else 0 for v in range(256)]


def white_mask(im):
    """Pixels blancs (icone de la bulle) : image « L » 0/255."""
    from PIL import ImageChops
    r, g, b = im.split()
    lut = _lut(lo=WHITE)
    return ImageChops.darker(ImageChops.darker(r.point(lut), g.point(lut)), b.point(lut))


def green_mask(im, ring_color=None):
    """Pixels de l'anneau vert : autour de la couleur lue au calibrage (± 45 par canal), sinon vert vif standard."""
    from PIL import ImageChops
    r, g, b = im.split()
    if ring_color:
        r0, g0, b0 = ring_color
        t = 45
        m = ImageChops.darker(r.point(_lut(r0 - t, r0 + t)), g.point(_lut(g0 - t, g0 + t)))
        return ImageChops.darker(m, b.point(_lut(b0 - t, b0 + t)))
    return ImageChops.darker(ImageChops.darker(g.point(_lut(lo=175)), r.point(_lut(hi=150))), b.point(_lut(hi=130)))


ICON_BOX, ICON_MIN = 22, 150   # demi-cote (px) de la zone centrale d'une bulle et pixels blancs minimum de son icone
RING_RETRY = 0.4    # secondes laissees au jeu pour retirer l'anneau apres un clic, avant de recliquer s'il est encore la
RING_STUCK = 10     # clics de suite sans effet sur un meme anneau avant de le laisser de cote RING_IGNORE secondes
RING_IGNORE = 6.0
WARM_MIN = 120      # pixels minimum d'un arc jaune / orange / rouge (le lisere d'un anneau vert en donne ~70)
ARC_MIN_DEG = 45    # un arc chaud plus court que ca n'est pas pris pour un anneau (faux positifs du decor)
RING_LEVELS = ("vert", "jaune", "orange", "rouge")     # urgence croissante de l'anneau de la spatule


def warm_masks(im):
    """[(urgence, masque)] des anneaux jaune (1), orange (2) et rouge (3). Releve en jeu (2026-10-04,
    proprietaire) : l'anneau de la spatule passe du vert au jaune, a l'orange puis au rouge en quelques secondes ;
    plus il est rouge, plus c'est urgent, et tout crame si on attend. Mesure sur captures : vert vif de teinte 72
    (echelle 0-255 de Pillow), rouge saumon (251, 130, 96) de teinte 8, sature et clair ; le halo sombre autour
    (149, 95, 60) n'est pas pris. Toute teinte vive ENTRE le rouge et le vert compte (pas de trou entre deux
    couleurs : l'anneau en transition etait invisible, et le clic annule). Bornes des paliers non mesurees."""
    from PIL import ImageChops
    h, sat, val = im.convert("HSV").split()
    vivid = ImageChops.darker(sat.point(_lut(lo=100)), val.point(_lut(lo=180)))
    red = ImageChops.lighter(h.point(_lut(hi=16)), h.point(_lut(lo=247)))
    return [(1, ImageChops.darker(vivid, h.point(_lut(lo=29, hi=67)))),
            (2, ImageChops.darker(vivid, h.point(_lut(lo=15, hi=30)))),
            (3, ImageChops.darker(vivid, red))]


def warm_mask(im):
    """Union des masques jaune, orange et rouge."""
    from PIL import ImageChops
    m = None
    for _, part in warm_masks(im):
        m = part if m is None else ImageChops.lighter(m, part)
    return m


def warm_arcs(im, need):
    """Anneaux ou arcs jaunes, orange ou rouges de `im` : [(cx, cy, pixels, urgence)], (cx, cy) = centre de la bulle.
    La forme est cherchee sur l'union des trois couleurs ; l'urgence est celle de la couleur la plus presente."""
    from PIL import ImageChops
    need = max(need, WARM_MIN)
    parts = warm_masks(im)
    union = None
    for _, m in parts:
        union = m if union is None else ImageChops.lighter(union, m)
    if count(union) < need:
        return []
    out = []
    half = RING_MAX // 2 + 6
    for cx, cy, n in find_arcs(union, need):
        if not (ICON_BOX <= cx < im.size[0] - ICON_BOX and ICON_BOX <= cy < im.size[1] - ICON_BOX):
            continue                 # centre hors de l'image (ou colle au bord) : pas une bulle cliquable
        # Un anneau entoure une bulle, et une bulle a une icone blanche au centre. Releve en jeu (2026-10-04) : le
        # bord jaune d'une cuisiniere formait un arc « jaune » ; le bot le cliquait en boucle et ne cuisinait plus.
        # Mesure sur capture : 450 a 720 pixels blancs dans les 44 px du centre d'une vraie bulle, 18 sur la cuisiniere.
        core = (max(0, cx - ICON_BOX), max(0, cy - ICON_BOX), min(im.size[0], cx + ICON_BOX), min(im.size[1], cy + ICON_BOX))
        if count(white_mask(im.crop(core))) < ICON_MIN:
            continue
        box = (max(0, cx - half), max(0, cy - half), min(im.size[0], cx + half), min(im.size[1], cy + half))
        lvl = max(parts, key=lambda p: count(p[1].crop(box)))[0]
        out.append((cx, cy, n, lvl))
    return out


def _fit_circle(pts):
    """Cercle des moindres carres (Kasa) passant au mieux par `pts` : (cx, cy, rayon) ou None."""
    n = len(pts)
    if n < 12:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for x, y in pts:
        u, v = x - mx, y - my
        suu += u * u
        suv += u * v
        svv += v * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-6:
        return None
    bu, bv = 0.5 * (suuu + suvv), 0.5 * (svvv + svuu)
    uc, vc = (bu * svv - bv * suv) / det, (bv * suu - bu * suv) / det
    return mx + uc, my + vc, (uc * uc + vc * vc + (suu + svv) / n) ** 0.5


def find_arcs(gm, need):
    """Arcs d'anneau d'un masque (image « L » 0/255) : liste de (cx, cy, pixels), (cx, cy) etant le CENTRE du
    cercle, donc de la bulle. Un anneau chaud n'est plus entier (il se vide avec le temps) : on ne peut pas exiger
    une boite carree comme find_rings. On regroupe les pixels sur la grille de CELL px, puis on garde les groupes
    dont les pixels tiennent sur un cercle du rayon d'un anneau (a 22 % pres pour 80 % d'entre eux : la bulle a
    deux cercles voisins, l'arc et un lisere). Une tache pleine (flammes, plat orange) ne tient pas sur un cercle."""
    W, H = gm.size
    gw, gh = max(1, W // CELL), max(1, H // CELL)
    small = gm.resize((gw, gh), 4).point(lambda v: 255 if v >= 16 else 0)
    if not small.getbbox():
        return []
    px, full = small.load(), gm.load()
    seen, out = set(), []
    for y0 in range(gh):
        for x0 in range(gw):
            if not px[x0, y0] or (x0, y0) in seen:
                continue
            stack, cells = [(x0, y0)], []
            seen.add((x0, y0))
            while stack:
                x, y = stack.pop()
                cells.append((x, y))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < gw and 0 <= ny < gh and (nx, ny) not in seen and px[nx, ny]:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
            pts = [(x, y) for cx, cy in cells for y in range(cy * CELL, min(H, (cy + 1) * CELL))
                   for x in range(cx * CELL, min(W, (cx + 1) * CELL)) if full[x, y]]
            if len(pts) < need:
                continue
            fit = _fit_circle(pts[::max(1, len(pts) // 1500)])
            if fit is None:
                continue
            cx, cy, rad = fit
            if not (RING_MIN / 2.0 - 4 <= rad <= RING_MAX / 2.0 + 4):
                continue
            tol = max(3.0, 0.22 * rad)
            good = sum(1 for x, y in pts if abs(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - rad) <= tol)
            if good < 0.8 * len(pts):
                continue
            # un petit paquet de pixels « tient » sur n'importe quel cercle : il faut un vrai arc, d'au moins
            # ARC_MIN_DEG degres autour du centre (secteurs de 15 degres occupes)
            sectors = {int(math.degrees(math.atan2(y - cy, x - cx)) % 360) // 15 for x, y in pts}
            if len(sectors) * 15 < ARC_MIN_DEG:
                continue
            out.append((int(round(cx)), int(round(cy)), len(pts)))
    return out


def ring_read(im, ring_color=None, warm=True, need=60):
    """(pixels, urgence, masque, centre) de l'anneau de la spatule dans `im` ; urgence -1 s'il n'y en a pas, sinon
    0 (vert) a 3 (rouge). Le vert se compte comme avant (centre None). Les couleurs chaudes doivent former un arc
    de cercle (find_arcs) : `centre` est alors le centre de la bulle dans `im`."""
    gm = green_mask(im, ring_color)
    n = count(gm)
    level, mask, centre = (0 if n >= need else -1), gm, None
    if warm:
        arcs = warm_arcs(im, need)
        if arcs:
            cx, cy, k, lvl = max(arcs, key=lambda t: t[2])
            if level < 0 or k > n:                       # un anneau vert bien visible reste un anneau vert
                n, level, mask, centre = max(n, k), lvl, warm_mask(im), (cx, cy)
    return n, level, mask, centre


def find_rings(gm, need):
    """Anneaux verts d'un masque (image « L » 0/255) : liste de (cx, cy, pixels). Les pixels verts sont
    regroupes sur une grille de CELL px (composantes 8-connexes) ; on garde les groupes qui ont la taille et la
    forme d'un anneau : boite a peu pres carree de RING_MIN a RING_MAX px, et creuse (peu remplie)."""
    W, H = gm.size
    gw, gh = max(1, W // CELL), max(1, H // CELL)
    small = gm.resize((gw, gh), 4).point(lambda v: 255 if v >= 24 else 0)      # 4 = BOX (moyenne)
    if not small.getbbox():
        return []
    px = small.load()
    seen = set()
    out = []
    for y0 in range(gh):
        for x0 in range(gw):
            if not px[x0, y0] or (x0, y0) in seen:
                continue
            stack, cells = [(x0, y0)], []
            seen.add((x0, y0))
            while stack:
                x, y = stack.pop()
                cells.append((x, y))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < gw and 0 <= ny < gh and (nx, ny) not in seen and px[nx, ny]:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
            xs = [c[0] for c in cells]
            ys = [c[1] for c in cells]
            box = (min(xs) * CELL, min(ys) * CELL, min(W, (max(xs) + 1) * CELL), min(H, (max(ys) + 1) * CELL))
            part = gm.crop(box)
            bb = part.getbbox()
            if not bb:
                continue
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            n = count(part)
            if n < need or not (RING_MIN <= w <= RING_MAX and RING_MIN <= h <= RING_MAX):
                continue
            if not (0.7 <= w / float(h) <= 1.43) or n > 0.6 * w * h:
                continue
            out.append((box[0] + (bb[0] + bb[2]) // 2, box[1] + (bb[1] + bb[3]) // 2, n))
    return out


def dilate(mask):
    from PIL import ImageFilter
    return mask.filter(ImageFilter.MaxFilter(3))


def count(mask):
    return mask.histogram()[255]


def jaccard(a, b):
    from PIL import ImageChops
    union = count(ImageChops.lighter(a, b))
    if not union:
        return 0.0
    return count(ImageChops.darker(a, b)) / union


def halo_mask(radius):
    """Anneau (image « L ») entre le bord de l'icone et le bord du disque gris : il ne doit pas contenir de blanc.
    Renvoie (masque, rayon exterieur)."""
    from PIL import Image, ImageDraw
    r1 = int(round(radius + 4))
    r2 = int(round(r1 + max(6, radius * 0.4)))
    size = 2 * r2 + 1
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.ellipse((0, 0, size - 1, size - 1), fill=255)
    d.ellipse((r2 - r1, r2 - r1, r2 + r1, r2 + r1), fill=0)
    return m, r2


def encode_mask(mask):
    buf = io.BytesIO()
    mask.convert("1").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_mask(data):
    """Masque « L » de REF x REF (une reference plus petite, d'une ancienne version, est centree)."""
    from PIL import Image
    m = Image.open(io.BytesIO(base64.b64decode(data))).convert("L")
    if m.size != (REF, REF):
        dx, dy = (m.size[0] - REF) // 2, (m.size[1] - REF) // 2
        m = m.crop((dx, dy, dx + REF, dy + REF))
    return m


def make_ref(x, y):
    """Reference d'une icone : masque blanc REF x REF centre sur l'icone sous la souris, ou None.
    Renvoie (masque, image RGB de la meme zone, centre absolu, rayon de l'icone)."""
    half = GRAB // 2
    im = grab((x - half, y - half, x + half, y + half))
    if im is None:
        return None
    m = white_mask(im)
    box = m.getbbox()
    if not box or count(m) < 25:
        return None
    if box[0] <= 1 or box[1] <= 1 or box[2] >= GRAB - 1 or box[3] >= GRAB - 1:
        # du blanc touche le bord (texte, mur) : on ne garde que le centre de la zone
        inner = GRAB // 4
        m2 = m.crop((inner, inner, GRAB - inner, GRAB - inner))
        box = m2.getbbox()
        if not box or count(m2) < 25:
            return None
        box = (box[0] + inner, box[1] + inner, box[2] + inner, box[3] + inner)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    radius = max(box[2] - box[0], box[3] - box[1]) / 2
    x0, y0 = int(round(cx - REF / 2)), int(round(cy - REF / 2))
    crop = (x0, y0, x0 + REF, y0 + REF)
    return m.crop(crop), im.crop(crop), (x - half + int(round(cx)), y - half + int(round(cy))), radius


# ---------------------------------------------------------------- une cuisiniere suivie
class Burner:
    """Une cuisiniere servie par la boucle : sa bulle (identifiee par sa position, qui bouge un peu d'un plat
    a l'autre), l'etat lu a l'ecran et les instants qui servent a l'ordonnanceur."""

    def __init__(self, index, pos, state="none"):
        now = time.perf_counter()
        self.index = index          # 1, 2, 3... (de gauche a droite a la decouverte)
        self.pos = tuple(pos)       # centre absolu de la bulle
        self.state = state          # cook | ready | spatula (anneau vert) | cooking | none
        self.scores = {}
        self.seen = now             # derniere fois ou la bulle a ete reconnue
        self.since = now            # depuis quand l'etat ne change plus
        self.lost = 0               # suivis locaux consecutifs sans reconnaissance
        self.launched = 0.0         # instant du dernier « Cuisiner » clique
        self.fired = 0.0            # instant du dernier feu ajuste
        self.moved = now            # derniere fois ou la bulle a change de place (camera en mouvement)
        self.collected = 0.0        # instant de la derniere recuperation (la bulle « gants » reste un instant)
        self.dishes = 0
        self.fires = 0
        self.clicks = 0             # feux ajustes pour le plat en cours
        self.fails = 0              # lancements de suite ou le menu est reste ouvert

    def risky(self, guard):
        """Vrai si l'anneau vert peut surgir sur cette cuisiniere dans les secondes qui viennent (voir
        DEFAULT_COOK : la duree reelle de l'anneau n'a jamais ete mesuree, `guard` est une estimation)."""
        if self.state == "spatula":
            return True
        if self.state not in ("cooking", "none"):
            return False
        ref = max(self.launched, self.fired)
        return bool(ref) and (time.perf_counter() - ref) < guard

    def to_dict(self):
        return {"i": self.index, "state": self.state, "dishes": self.dishes, "fires": self.fires,
                "pos": [int(self.pos[0]), int(self.pos[1])]}


# ---------------------------------------------------------------- module
class Cooker(MouseBot):
    # Releve en jeu (2026-09-22) : un clic trop bref, juste apres l'arrivee de la souris, n'etait parfois pas pris
    # par la bulle (« il clique trop vite sur la spatule »). On survole un instant, puis on appuie plus longtemps.
    SETTLE = (0.07, 0.11)
    HOLD = (0.06, 0.10)

    ACTIVE_STATES = ("cooking",)

    def __init__(self, cfg, log=print, on_change=None, save=None, logfile=None, data_dir=None):
        self.cfg = cfg
        self._ui_log = log
        self.logfile = logfile
        self.data_dir = data_dir or (os.path.dirname(logfile) if logfile else ".")
        self._t0 = time.perf_counter()
        self.on_change = on_change or (lambda: None)
        self.save = save or (lambda: None)
        self.state = "idle"          # idle | calibrating | cooking
        self.step = 0
        self.steps = list(STEPS)
        self.points = {}
        self.message = ""
        self.last_stop_reason = ""
        self.countdown = 0.0
        self._last_toggle = 0.0
        self.dishes = 0
        self.fires = 0
        self.actions_done = 0
        self.started_at = None
        self.phase = ""
        self.test_result = ""
        self._stop = threading.Event()
        self._thread = None
        self._hook = None
        self._expected_pos = None
        self._pos = None             # dernier centre connu de la bulle (absolu)
        self._masks = None
        self._masks_key = None
        self._last_state = None
        self._last_im = None
        self._burners = []           # multi-cuisinieres : une machine a etats par cuisiniere (Burner)
        self._wide_at = 0.0          # instant de la derniere recherche large
        self._menu_for = None        # cuisiniere dont la bulle a ete cliquee en dernier (a qui est le menu)
        self._menu_tries = 0         # essais de suite pour fermer un menu Recettes reste ouvert
        self._wide_origin = (0, 0)   # coin haut-gauche (absolu) de la derniere recherche large
        self._stand = None           # cuisiniere devant laquelle se tient le personnage (derniere bulle cliquee)
        self._wide_until = 0.0       # recherche large forcee jusqu'a cet instant (camera en mouvement)
        self._stray_at = 0.0         # derniere ligne de journal « bulle non rattachee »
        self._clicked_at = 0.0       # dernier clic sur une bulle (ou fin d'un lancement) : la camera peut bouger
        self._debug_at = 0.0         # derniere image de diagnostic enregistree (cook.debug_frames)
        self._debug_n = 0
        self._stray_rings = []       # anneaux verts vus sans cuisiniere a qui les rattacher (cliques quand meme)
        self._stray_fired = 0.0
        ensure_defaults(cfg)

    @property
    def cook_cfg(self):
        return ensure_defaults(self.cfg)

    @property
    def cookers(self):
        """Nombre de cuisinieres a servir (borne 1..MAX_COOKERS). 1 = comportement historique."""
        try:
            return max(1, min(MAX_COOKERS, int(self.cook_cfg.get("cookers", 1) or 1)))
        except (TypeError, ValueError):
            return 1

    def apply_cookers(self):
        """Reglage cook.cookers change : arrete une boucle en cours (les machines a etats sont refaites au
        prochain demarrage). Renvoie (nombre, boucle arretee)."""
        n = self.cookers
        stopped = False
        if self.state == "cooking":
            self.stop("nombre de cuisinières changé")
            stopped = True
        else:
            self._burners = []
        self.log(f"cuisine : {n} cuisinière(s) à servir")
        self.on_change()
        return n, stopped

    def _mouse_cfg(self):
        d = dict(self.cfg.get("draw", {}))
        d["click_delay"] = float(self.cook_cfg.get("click_delay", 0.3))
        return d

    # ---- calibrage
    def start_calibration(self, keys=None):
        """keys : sous-ensemble des etapes (ex. ICON_STEPS pour ne recapturer que les icones), None = toutes."""
        if self.state == "cooking":
            self.stop("calibrage demandé")
        self.steps = [s for s in STEPS if keys is None or s[0] in keys] or list(STEPS)
        self.points = {}
        self.step = 0
        self.state = "calibrating"
        self.message = ""
        self.log(f"calibrage cuisine ({len(self.steps)} étapes) : étape 1")
        self.on_change()

    def cancel_calibration(self):
        if self.state == "calibrating":
            self.state = "idle"
            self.points = {}
            self.log("calibrage annulé")
            self.on_change()

    def capture_point(self):
        """F3 pendant le calibrage : memorise la position de la souris (et l'icone ou la couleur) pour l'etape."""
        if self.state != "calibrating":
            return False
        key = self.steps[self.step][0]
        pos = cursor_pos()
        if key in ICON_STEPS:
            ref = make_ref(*pos)
            if ref is None:
                self.message = "Aucune icône blanche sous la souris : place-la bien au centre de la bulle, puis F3."
                self.log(self.message)
                self.on_change()
                return False
            mask, rgb, center, radius = ref
            # la meme icone que celle deja capturee : la bulle n'a pas encore change
            names = {"cook": "cuisiner", "spatula": "spatule", "ready": "gants"}
            for other in ICON_STEPS:
                if other == key:
                    continue
                prev = self.points.get("_ref_" + other)
                if prev is None and other in self.cook_cfg["refs"] and other not in [s[0] for s in self.steps]:
                    prev = (decode_mask(self.cook_cfg["refs"][other]["png"]), 0)
                if prev is not None and jaccard(dilate(prev[0]), dilate(mask)) > SAME_ICON:
                    self.message = (f"C'est encore l'icône « {names[other]} » : attends que la bulle montre "
                                    f"{'la spatule avec son anneau vert' if key == 'spatula' else 'les gants (plat prêt)' if key == 'ready' else 'l’icône cuisiner'}, puis F3.")
                    self.log(self.message)
                    self.on_change()
                    return False
            ring = self._read_ring(center) if key == "spatula" else None
            if key == "spatula" and ring is None:
                self.message = "Pas d'anneau vert autour de la bulle : appuie sur F3 pendant que l'anneau est affiché (ou « Passer »)."
                self.log(self.message)
                self.on_change()
                return False
            self.points[key] = list(center)
            self.points["_ref_" + key] = (mask, radius)
            try:
                rgb.save(os.path.join(self.data_dir, f"cuisine_ref_{key}.png"))
            except Exception:
                pass
            if ring is not None:
                self.points["_ring"] = ring
        elif key == "cook_btn":
            self.points[key] = pos
            self.points["_btn_color"] = sample_color(pos[0], pos[1], radius=4)
        else:
            self.points[key] = pos
        self.step += 1
        if self.step >= len(self.steps):
            self._finish_calibration()
        else:
            self.on_change()
        return True

    def _read_ring(self, center):
        """Couleur moyenne de l'anneau vert autour de la bulle (pixels verts vifs), ou None."""
        x, y = center
        im = grab((x - RING, y - RING, x + RING, y + RING))
        if im is None:
            return None
        m = green_mask(im)
        n = count(m)
        if n < 20:
            return None
        px = im.load()
        mp = m.load()
        s = [0, 0, 0]
        for j in range(im.size[1]):
            for i in range(im.size[0]):
                if mp[i, j]:
                    p = px[i, j]
                    s[0] += p[0]
                    s[1] += p[1]
                    s[2] += p[2]
        return [v // n for v in s]

    def back_point(self):
        """Revient a l'etape precedente : ce qui y avait ete capture (position, icone, couleur) est oublie,
        pour etre repris. La configuration deja enregistree n'est touchee qu'a la validation."""
        if self.state != "calibrating" or self.step <= 0:
            return False
        self.step -= 1
        key = self.steps[self.step][0]
        for k in (key, "_ref_" + key):
            self.points.pop(k, None)
        if key == "spatula":
            self.points.pop("_ring", None)
        if key == "cook_btn":
            self.points.pop("_btn_color", None)
        self.message = ""
        self.log(f"calibrage cuisine : retour a l'etape {self.step + 1}")
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
        if self.state != "calibrating":
            return False
        if self.steps[self.step][0] not in OPTIONAL:
            return False
        self.step += 1
        if self.step >= len(self.steps):
            self._finish_calibration()
        else:
            self.on_change()
        return True

    def _finish_calibration(self):
        c = self.cook_cfg
        p = self.points
        pts = c["points"]
        if "_ref_cook" in p and "_ref_ready" in p and jaccard(dilate(p["_ref_cook"][0]), dilate(p["_ref_ready"][0])) > SAME_ICON:
            self.message = "Les icônes « cuisiner » et « gants » capturées sont identiques : recapture les icônes."
            self.log(self.message)
            self.state = "idle"
            self.on_change()
            return
        if "search_tl" in p and "search_br" in p:
            x1, y1 = p["search_tl"]
            x2, y2 = p["search_br"]
            rect = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
            if rect[2] - rect[0] < REF + 20 or rect[3] - rect[1] < REF + 20:
                self.state = "idle"
                self.message = "Zone de recherche trop petite : refais le calibrage."
                self.log(self.message)
                self.on_change()
                return
            pts["search"] = rect
        for k in ("cook", "tile", "cook_btn", "ready", "neutral", "spatula"):
            if k in p:
                pts[k] = [int(v) for v in p[k]]
        if "_btn_color" in p:
            c["cook_btn_color"] = p["_btn_color"]
        refs = c["refs"]
        for k in ("cook", "spatula", "ready"):
            if "_ref_" + k in p:
                refs[k] = {"png": encode_mask(p["_ref_" + k][0]), "radius": round(p["_ref_" + k][1], 1)}
        if "_ring" in p:
            c["ring_color"] = p["_ring"]
        c["screen"] = screen_fingerprint()
        self._masks = None
        self.points = {}
        self.state = "idle"
        extra = "spatule capturée" if "spatula" in refs else "spatule non capturée (anneau vert standard)"
        ring = "anneau vert lu" if c.get("ring_color") else "anneau vert standard"
        self.message = f"Calibrage de la cuisine enregistré ({extra}, {ring})."
        self.log(self.message)
        self.save()
        self.on_change()

    def calibrated(self):
        c = self.cook_cfg
        return all(c["points"].get(k) for k in REQUIRED) and all(k in c["refs"] for k in ("cook", "ready")) \
            and bool(c.get("cook_btn_color"))

    # ---- boucle
    def start(self, delay=1.0):
        if self.state == "cooking":
            self.log("cuisine déjà en cours")
            return False
        now = time.perf_counter()
        if now - self._last_toggle < 0.8:
            return False
        self._last_toggle = now
        if self.state == "calibrating":
            return False
        if not self.calibrated():
            self.message = "La cuisine n'est pas encore calibrée."
            self.log(self.message)
            self.on_change()
            return False
        if not SCREEN_OK:
            self.message = "Lecture d'écran indisponible (Pillow manquant)."
            self.log(self.message)
            self.on_change()
            return False
        if screen_changed(self.cook_cfg.get("screen")):
            self.message = ("L'écran a changé depuis la configuration de la cuisine (résolution, mise à "
                            "l'échelle ou écrans) : refais la configuration.")
            self.log(self.message)
            self.on_change()
            return False
        self.state = "cooking"
        self.last_stop_reason = ""
        self.message = ""
        self.dishes = 0
        self.fires = 0
        self.actions_done = 0
        self.phase = ""
        self._pos = None
        self._last_state = None
        self._burners = []
        self._wide_at = 0.0
        self._stop.clear()
        self.countdown = float(delay)
        self._thread = threading.Thread(target=self._run, args=(float(delay),), daemon=True)
        self._thread.start()
        return True

    def stop(self, reason=""):
        if self.state == "cooking":
            if reason == "stop" and time.perf_counter() - self._last_toggle < 0.8:
                return False
            self.last_stop_reason = reason
            self._stop.set()
            return True
        if self.state == "calibrating":
            self.cancel_calibration()
        return False

    def _run(self, delay):
        self._t0 = time.perf_counter()
        if self.logfile:
            try:
                with open(self.logfile, "w", encoding="utf-8") as f:
                    f.write(f"DodoTopia cuisine {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
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
            self.started_at = time.perf_counter()
            if not self._stop.is_set():
                self._loop()
        except Exception as e:  # noqa
            self.log(f"erreur cuisine : {e}")
            self.last_stop_reason = "erreur"
            self.message = f"Cuisine arrêtée : {e}"
            self._snapshot()
        finally:
            if self.last_stop_reason and self.last_stop_reason != "erreur":
                self.message = f"Cuisine arrêtée ({self.last_stop_reason}) : {self.dishes} plat(s) cuisiné(s)."
            elif not self.last_stop_reason and not self.message:
                self.message = f"Cuisine terminée : {self.dishes} plat(s) cuisiné(s)."
            try:
                mouse_up()
            except Exception:
                pass
            self.state = "idle"
            self.started_at = None
            self._expected_pos = None
            self.phase = ""
            self.log("cuisine terminée" if not self.last_stop_reason else f"cuisine arrêtée ({self.last_stop_reason})")
            self.on_change()

    def _snapshot(self):
        """Sauve la derniere capture de la zone de recherche pour comprendre un echec."""
        if self._last_im is not None:
            try:
                self._last_im.save(os.path.join(self.data_dir, "cuisine_echec.png"))
            except Exception:
                pass

    def _guard(self):
        """Arret demande ou souris bougee par l'utilisateur : True s'il faut sortir."""
        if self._stop.is_set():
            return True
        if self._user_moved():
            self.stop("souris bougée")
            return True
        return False

    def _loop(self):
        """Une seule cuisiniere : boucle sequentielle historique. Plusieurs : ordonnanceur (_loop_multi)."""
        p = self.cook_cfg["points"]
        self._check_mouse(*p["neutral"])
        if self.cookers > 1:
            self.log(f"cuisine : {self.cookers} cuisinières à servir")
            return self._loop_multi()
        return self._loop_single()

    def _loop_single(self):
        c = self.cook_cfg
        max_dishes = int(c.get("max_dishes", 0) or 0)
        while not self._stop.is_set():
            if max_dishes and self.dishes >= max_dishes:
                self.message = f"{self.dishes} plat(s) cuisiné(s), objectif atteint."
                return
            self.phase = "lancement"
            if not self._launch():
                return
            self.phase = "cuisson"
            res = self._watch()
            if res is None:
                return
            if res == "relaunch":
                continue
            self.phase = "récupération"
            if not self._collect(res):
                return

    def _collect(self, pos):
        if not self._click(*pos, delay=0.8):
            return False
        self.dishes += 1
        self.log(f"plat {self.dishes} récupéré")
        self.on_change()
        return True

    # ---- boucle multi-cuisinieres
    def _loop_multi(self):
        """Ordonnanceur a plusieurs cuisinieres. Il n'y a qu'une souris et qu'un menu Recettes : les actions sont
        serialisees. La boucle agit sur CE QU'ELLE VOIT, pas sur l'identite des cuisinieres :
          (a) tout anneau vert            -> clic, et re-clic tant que l'anneau reste (un clic peut ne pas prendre) ;
          (b) toute bulle « gants »       -> plat recupere ;
          (c) toute bulle « cuisiner »    -> cuisson lancee (voir _may_launch).
        Pourquoi (releves en jeu, 2026-09-22) : pendant la cuisson la bulle DISPARAIT (rien a suivre pendant ~9 s),
        et la cuisiniere qu'on vient de cliquer se retrouve toujours au meme endroit de l'ecran (la camera recentre
        le personnage). Savoir « quelle cuisiniere est-ce » est donc peu fiable : un plat pret etait ignore 7 s
        parce que sa bulle n'etait rattachee a aucune cuisiniere suivie. Les Burner ne servent plus qu'aux
        compteurs et a l'affichage (rattachement au mieux, voir _assign).
        Une bulle n'est cliquee que si elle est vue au meme endroit sur deux lectures de suite : pas de clic sur
        une bulle qui glisse encore avec la camera, ni sur un anneau qui vient a peine d'apparaitre."""
        c = self.cook_cfg
        p = c["points"]
        poll = float(c.get("poll", 0.1))
        max_dishes = int(c.get("max_dishes", 0) or 0)
        timeout = float(c.get("cook_timeout", 240.0))
        self._burners = []
        self._wide_at = 0.0
        self._wide_until = 0.0
        self._clicked_at = time.perf_counter()     # au depart on ne sait pas ou en est la camera
        self._debug_n = 0
        self._stand = None
        self._stray_rings = []
        self._menu_for = None
        self._menu_tries = 0
        last_action = time.perf_counter()
        last_neutral = time.perf_counter()
        prev, prev_at = [], 0.0          # lecture precedente (stabilite des bulles)
        ring_pos, ring_at, ring_streak = None, 0.0, 0
        ignored = []                     # [(position, jusqu'a quand)] : anneaux laisses de cote (clics sans effet)
        ready_at, ready_pos = 0.0, None
        pend_at = 0.0                    # anneau vert vu mais pas encore stable : depuis quand
        spat_at, spat_seen = 0.0, 0.0    # spatule sans anneau : debut de l'apparition, derniere lecture
        try:
            spat_wait = max(0.0, float(c.get("spatula_wait", 5.0)))
        except (TypeError, ValueError):
            spat_wait = 5.0
        self._launched_at = 0.0

        def near(a, b, r):
            return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 <= r * r

        while not self._stop.is_set():
            if max_dishes and self.dishes >= max_dishes:
                self.message = f"{self.dishes} plat(s) cuisiné(s), objectif atteint."
                return
            if self._menu_open():
                # menu Recettes ouvert hors lancement (clic de trop sur une bulle redevenue « cuisiner »...) :
                # il cache les bulles et un clic dans l'herbe ne le ferme pas -> on lance la recette
                self.phase = "menu"
                if not self._menu_recover():
                    return
                last_action = self._launched_at = time.perf_counter()
                prev = []
                continue
            self._menu_tries = 0
            # Releve en jeu (2026-10-04) : la boucle reagissait trop tard (lecture complete d'une grande zone, puis
            # une 2e lecture pour la stabilite, puis la souris qui glisse : plus de 2 s) et l'anneau virait a
            # l'orange, voire le plat cramait. Les anneaux sont donc lus a part, tres vite, et cliques au premier
            # coup d'oeil ; la bulle est de toute facon reverifiee juste avant d'appuyer (_still). La souris glisse
            # toujours (jamais de saut : le proprietaire l'a vu « se teleporter »), mais vite pour la spatule.
            rings = self._rings_quick()
            if ignored:
                t_now = time.perf_counter()
                ignored = [(q, until) for q, until in ignored if until > t_now]
                rings = [d for d in rings if not any(near(d["pos"], q, 40) for q, _ in ignored)]
            if rings:
                for d in rings:
                    d["burner"] = min(self._burners, key=lambda o: (o.pos[0] - d["pos"][0]) ** 2 + (o.pos[1] - d["pos"][1]) ** 2,
                                      default=None)
                    if d["burner"] is not None and not near(d["burner"].pos, d["pos"], ASSOC):
                        d["burner"] = None
                dets, stable = rings, []
                if self._guard():
                    return
                now = time.perf_counter()
                prev = []
            else:
                self._wide_at = time.perf_counter()
                dets = self._scan_wide()
                self._assign(dets)
                if self._guard():
                    return
                now = time.perf_counter()
                fresh = now - prev_at < 1.0
                stable = [d for d in dets if fresh and any(near(d["pos"], q["pos"], STILL) and q["state"] == d["state"]
                                                           for q in prev)]
                prev, prev_at = dets, now
                rings = [d for d in dets if d["state"] == "spatula" and not any(near(d["pos"], q, 40) for q, _ in ignored)]
            # (a) anneau : minute, tout le reste attend
            if rings:
                if ring_pos is not None and len(rings) > 1:      # deux anneaux : pas deux fois de suite le meme
                    rings.sort(key=lambda d: -((d["pos"][0] - ring_pos[0]) ** 2 + (d["pos"][1] - ring_pos[1]) ** 2))
                # le plus urgent d'abord : rouge, puis orange, puis jaune, puis vert (tri stable)
                rings.sort(key=lambda d: -d["scores"].get("urgence", 0))
                d = rings[0]
                again = ring_pos is not None and near(d["pos"], ring_pos, 40) and now - ring_at < 3.0
                if again and now - ring_at < RING_RETRY:
                    if not self._sleep(poll):                     # laisse au jeu le temps de retirer l'anneau
                        return
                    continue
                ring_streak = ring_streak + 1 if now - ring_at < 3.0 else 1
                # le jeu peut ignorer les clics un moment (personnage occupe) : on insiste longtemps avant d'abandonner
                if ring_streak > RING_STUCK:
                    # ni un anneau qui ne reagit pas ni un faux anneau ne doivent bloquer le reste de la cuisine
                    self.log(f"anneau en {d['pos'][0]},{d['pos'][1]} : {RING_STUCK} clics sans effet, laissé de côté {RING_IGNORE:.0f} s")
                    ignored.append((d["pos"], now + RING_IGNORE))
                    ring_streak = 0
                    continue
                self.phase = "feu"
                b = d.get("burner")
                self._acted(b)
                if not self._click(*d["pos"], delay=0.1, fast=True, confirm=lambda: self._still(d["pos"], "spatula")):
                    return
                if self._click_skipped:
                    # l'anneau a disparu pendant le deplacement de la souris : un clic ici tomberait sur la
                    # cuisiniere en pleine cuisson et retirerait le plat pas fini (releve en jeu, 2026-10-04)
                    self.log(f"anneau disparu avant le clic en {d['pos'][0]},{d['pos'][1]} : pas de clic")
                    prev = []
                    continue
                ring_pos, ring_at = d["pos"], time.perf_counter()
                last_action = ring_at
                pend_at = 0.0
                if not again:                                     # un re-clic sur le meme anneau n'est pas un 2e feu
                    self.fires += 1
                    if b is not None:
                        b.fires += 1
                if b is not None:
                    b.clicks += 1
                    b.fired = ring_at
                who = f"bulle {b.index}" if b is not None else "anneau sans cuisinière suivie"
                level = d["scores"].get("urgence", 0)
                self.log(f"{who} : feu ajusté en {d['pos'][0]},{d['pos'][1]}" + (" (re-clic)" if again else "")
                         + (f" (anneau {RING_LEVELS[level]})" if level else ""))
                self.on_change()
                continue
            # Priorite aux spatules : un anneau vu mais pas encore stable (il vient d'apparaitre, ou la camera
            # bouge) passe avant tout le reste -> on relit au lieu de partir recuperer un plat ou ouvrir le menu.
            if any(x["state"] == "spatula" for x in dets):
                pend_at = pend_at or now
                if now - pend_at < RING_PENDING:
                    self.phase = "feu"
                    if not self._sleep(poll):
                        return
                    continue
            else:
                pend_at = 0.0
            # ... et une spatule sans anneau annonce l'anneau : on garde la souris libre (spatula_wait s au plus)
            hold = False
            if spat_wait and any(x["state"] == "cooking" for x in dets):
                if now - spat_seen > 1.0:
                    spat_at = now
                spat_seen = now
                hold = now - spat_at < spat_wait
            # (b) plat pret. La bulle « gants » reste affichee ~1 s apres le clic (et la camera la deplace) : on
            # ne regarde plus les gants pendant 1,2 s, sinon le 2e clic tombe sur « cuisiner » et ouvre le menu.
            d = next((x for x in stable if x["state"] == "ready"), None) if now - ready_at >= 1.2 and not hold else None
            if d is not None:
                self.phase = "récupération"
                b = d.get("burner")
                self._acted(b)
                # Releve en jeu (2026-10-04) : le jeu ne prend pas toujours le clic sur les gants ; la bulle reste et
                # il fallait recliquer, ce qui comptait deux plats. Le clic est donc plus pose (survol et appui deux
                # fois plus longs), et un re-clic au meme endroit dans les READY_AGAIN secondes est le MEME plat.
                again = ready_pos is not None and near(d["pos"], ready_pos, 40) and now - ready_at < READY_AGAIN
                if not self._click(*d["pos"], delay=0.6, slow=2.0, confirm=lambda: self._still(d["pos"], "ready")):
                    return
                if self._click_skipped:
                    self.log(f"bulle « récupérer » disparue avant le clic en {d['pos'][0]},{d['pos'][1]} : pas de clic")
                    prev = []
                    continue
                ready_at = last_action = time.perf_counter()
                ready_pos = d["pos"]
                who = f"bulle {b.index}" if b is not None else "bulle sans cuisinière suivie"
                if again:
                    self.log(f"{who} : gants recliqués en {d['pos'][0]},{d['pos'][1]} (le premier clic n'avait pas pris)")
                    self.on_change()
                    continue
                self.dishes += 1
                if b is not None:
                    b.dishes += 1
                    b.clicks = 0
                    b.launched = b.fired = 0.0
                    b.collected = ready_at
                self.log(f"{who} : plat récupéré en {d['pos'][0]},{d['pos'][1]} ({self.dishes} en tout)")
                self.on_change()
                continue
            # (c) cuisiniere au repos
            d = next((x for x in stable if x["state"] == "cook"), None) if now - ready_at >= 1.0 and not hold else None
            if d is not None:
                b = d.get("burner") or Burner(0, d["pos"])
                b.pos = d["pos"]
                if self._may_launch(b, self._burners):
                    self.phase = "lancement"
                    if not self._launch_one(b):
                        return
                    last_action = time.perf_counter()
                    prev = []
                    continue
            # rien de reconnu : animation d'un plat ameliore, fenetre du jeu -> clic a cote pour la fermer
            if not dets and now - last_neutral > 1.5:
                if not self._click(*p["neutral"], delay=0.2):
                    return
                last_neutral = time.perf_counter()
                continue
            self.phase = "cuisson"
            if now - last_action > timeout:
                raise RuntimeError(f"aucune cuisinière n'a bougé depuis {timeout:.0f} s (plats pas prêts ?)")
            if not self._sleep(poll):
                return

    def _may_launch(self, b, burners):
        """Vrai si on peut lancer une cuisson sur `b` sans risquer de rater un anneau vert ailleurs.
        Le lancement (clic sur la bulle -> menu Recettes -> tuile -> Cuisiner) dure quelques secondes pendant
        lesquelles le menu couvre l'ecran : les autres bulles sont invisibles. Par prudence on ne le commence
        donc pas tant qu'une autre cuisiniere est dans sa « fenetre de risque » (launch_guard secondes apres
        son lancement ou son dernier feu ajuste).
        ATTENTION : la duree reelle de l'anneau vert dans le jeu n'a jamais ete chronometree ; launch_guard
        est une estimation prudente, reglable dans config.json (voir DEFAULT_COOK), et launch_anytime la
        desactive completement."""
        c = self.cook_cfg
        if c.get("launch_anytime"):
            return True
        try:
            guard = float(c.get("launch_guard", 0.0) or 0.0)
        except (TypeError, ValueError):
            guard = 0.0
        if guard <= 0:
            return True
        return not any(o is not b and o.risky(guard) for o in burners)

    def _launch_one(self, b):
        """Lance une cuisson sur la cuisiniere `b` : clic sur sa bulle, tuile de la derniere recette, bouton
        Cuisiner. False seulement si la boucle doit s'arreter (un echec est journalise et retente au tour
        suivant)."""
        p = self.cook_cfg["points"]
        self._acted(b)
        if not self._click(*b.pos, delay=0.3, confirm=lambda: self._still(b.pos, "cook")):
            return False
        if self._click_skipped:
            self.log(f"bulle « cuisiner » disparue avant le clic en {b.pos[0]},{b.pos[1]} : pas de clic")
            return True
        if not self._wait_menu(True, 4.0):
            self.log(f"bulle {b.index} : le menu ne s'est pas ouvert après le clic sur la bulle")
            return not self._stop.is_set()
        # le menu couvre l'ecran (aucun anneau visible) : on y reste le moins longtemps possible. Le jeu
        # preselectionne la derniere recette : « Cuisiner » suffit (confirme en jeu le 2026-09-21) ; la tuile
        # n'est cliquee qu'apres un echec, au cas ou la selection aurait saute.
        if b.fails:
            if not self._click(*p["tile"], delay=0.25):
                return False
            if not self._menu_open():
                self.log(f"bulle {b.index} : le menu a disparu avant Cuisiner (animation ?)")
                return not self._stop.is_set()
        if not self._click(*p["cook_btn"], delay=0.15):
            return False
        if not self._wait_menu(False, 5.0):
            if self._stop.is_set():
                return False
            b.fails += 1
            self.log(f"bulle {b.index} : le menu reste ouvert après Cuisiner ({b.fails})")
            if b.fails >= 3:
                raise RuntimeError(f"le menu Recettes reste ouvert sur la cuisinière {b.index} : "
                                   f"plus d'ingrédients pour cette recette ?")
            return True
        b.launched = time.perf_counter()
        self._clicked_at = b.launched
        self._wide_until = b.launched + CAM_SETTLE
        b.clicks = 0
        b.fails = 0
        b.state, b.since = "cooking", b.launched
        self.log(f"bulle {b.index} : cuisson lancée")
        self.on_change()
        return True

    def _menu_recover(self):
        """Multi-cuisinieres : le menu Recettes est ouvert alors qu'aucun lancement n'est en cours. On lance la
        recette (tuile + Cuisiner) sur la cuisiniere dont la bulle a ete cliquee en dernier ; apres 3 essais
        sans que le menu se ferme, on arrete (plus d'ingredients, ou couleur du bouton mal calibree).
        False si la boucle doit s'arreter."""
        c = self.cook_cfg
        p = c["points"]
        b = self._menu_for
        self._menu_tries += 1
        if self._menu_tries > 3:
            raise RuntimeError("le menu Recettes reste ouvert : plus d'ingrédients pour cette recette ? "
                               "(ou recalibre le bouton « Cuisiner »)")
        col = sample_color(*p["cook_btn"], radius=4)
        who = f"bulle {b.index}" if b else "cuisinière inconnue"
        self.log(f"menu Recettes ouvert ({who}, couleur du bouton {col}) : lancement de la recette ({self._menu_tries})")
        if self._menu_tries > 1:                  # « Cuisiner » seul n'a pas suffi : on reselectionne la recette
            if not self._click(*p["tile"], delay=0.4):
                return False
        if self._menu_open():
            if not self._click(*p["cook_btn"], delay=0.5):
                return False
        if not self._wait_menu(False, 5.0):
            return not self._stop.is_set()
        self._menu_tries = 0
        self._clicked_at = time.perf_counter()
        self._wide_until = self._clicked_at + CAM_SETTLE
        if b is not None:
            b.launched = time.perf_counter()
            b.clicks = 0
            b.fails = 0
            b.state, b.since = "cooking", b.launched
            self.log(f"bulle {b.index} : cuisson lancée")
        self._menu_for = None
        self.on_change()
        return True

    def _launch(self):
        """Lance une cuisson en reagissant a ce que montre l'ecran, jusqu'a ce qu'elle soit lancee :
        menu Recettes ouvert → tuile recente + Cuisiner ; bulle « cuisiner » → clic ; gants → recuperer ;
        rien de reconnu (animation d'un plat ameliore, fenetre) → clic a cote. La cuisson est consideree lancee
        quand la spatule est vue, ou quand, apres Cuisiner, ni le menu ni la bulle « cuisiner » ne reviennent
        pendant 3 s. Renvoie False si la boucle est arretee."""
        c = self.cook_cfg
        p = c["points"]
        poll = float(c.get("poll", 0.1))
        t0 = time.perf_counter()
        launched = None        # instant du clic sur Cuisiner apres lequel le menu s'est ferme
        none_since = None
        last_neutral = time.perf_counter()
        attempts = 0
        while True:
            if self._guard():
                return False
            now = time.perf_counter()
            if now - t0 > 90:
                raise RuntimeError("impossible de lancer la cuisson (bulle « cuisiner » ou menu Recettes introuvables)")
            if self._menu_open():
                none_since = None
                launched = None
                if attempts >= 3:
                    raise RuntimeError("le menu Recettes reste ouvert : plus d'ingrédients pour cette recette ?")
                attempts += 1
                if attempts > 1:                  # la derniere recette est preselectionnee : tuile en secours seulement
                    if not self._click(*p["tile"], delay=0.4):
                        return False
                    if not self._menu_open():
                        self.log("le menu a disparu avant Cuisiner (animation ?)")
                        continue
                if not self._click(*p["cook_btn"], delay=0.5):
                    return False
                end = time.perf_counter() + 5.0
                while self._menu_open() and time.perf_counter() < end:
                    if not self._sleep(0.1):
                        return False
                if not self._menu_open():
                    launched = time.perf_counter()
                    self.log(f"plat {self.dishes + 1} : Cuisiner cliqué")
                else:
                    self.log("le menu reste ouvert après Cuisiner, nouvel essai")
                continue
            st, pos, _ = self._find()
            if st in ("spatula", "cooking"):
                self.log(f"plat {self.dishes + 1} : cuisson en cours")
                return True
            if st == "cook":
                none_since = None
                if launched:
                    self.log("la bulle « cuisiner » est revenue : la cuisson n'a pas été lancée")
                    launched = None
                if not self._click(*pos, delay=0.3):
                    return False
                end = time.perf_counter() + 6.0
                while not self._menu_open() and time.perf_counter() < end:
                    if not self._sleep(0.1):
                        return False
                if not self._menu_open():
                    self.log("le menu ne s'est pas ouvert après le clic sur la bulle")
                continue
            if st == "ready":
                if not self._collect(pos):
                    return False
                continue
            # rien de reconnu : animation, fenetre, ou cuisson deja lancee
            if none_since is None:
                none_since = now
            if launched and now - none_since > 3.0:
                self.log(f"plat {self.dishes + 1} : cuisson lancée")
                return True
            if now - last_neutral > 1.5:
                if not self._click(*p["neutral"], delay=0.2):
                    return False
                last_neutral = time.perf_counter()
            if not self._sleep(poll):
                return False

    def _watch(self):
        """Surveille la cuisson : anneau vert → clic sur la spatule ; gants → renvoie leur position.
        None si la boucle est arretee ; "relaunch" si la bulle « cuisiner » reste affichee (rien ne cuit)."""
        c = self.cook_cfg
        poll = float(c.get("poll", 0.1))
        timeout = float(c.get("cook_timeout", 240.0))
        t0 = time.perf_counter()
        clicks = 0
        cook_since = None
        while True:
            if self._guard():
                return None
            now = time.perf_counter()
            if now - t0 > timeout:
                raise RuntimeError(f"plat pas prêt après {timeout:.0f} s")
            st, pos, _ = self._find()
            if st == "spatula":
                if clicks >= 6:
                    raise RuntimeError("le feu ne se règle pas (6 clics sur la spatule sans effet)")
                if not self._click(*pos, delay=0.6):
                    return None
                clicks += 1
                self.fires += 1
                self.log(f"feu ajusté ({clicks})")
                continue
            if st == "ready":
                self.log(f"plat prêt après {now - t0:.0f} s de cuisson, {clicks} feu(x)")
                return pos
            if st == "cook":
                cook_since = cook_since or now
                if now - cook_since > 4.0:
                    self.log("la bulle « cuisiner » reste affichée : rien ne cuit, nouveau lancement")
                    return "relaunch"
            else:
                cook_since = None
            if self._menu_open():
                self.log("le menu Recettes est ouvert pendant la cuisson : nouveau lancement")
                return "relaunch"
            if not self._sleep(poll):
                return None

    def _menu_open(self):
        c = self.cook_cfg
        x, y = c["points"]["cook_btn"]
        col = sample_color(x, y, radius=4)
        return bool(col) and _cdist(col, c["cook_btn_color"]) < 40 * 40

    def _wait_menu(self, want_open, timeout):
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            if self._stop.is_set():
                return False
            if self._menu_open() == want_open:
                return True
            if not self._sleep(0.1):
                return False
        return False

    # ---- detection
    def _load_masks(self):
        refs = self.cook_cfg["refs"]
        key = tuple(sorted((k, v.get("png", "")[:40]) for k, v in refs.items()))
        if self._masks is None or self._masks_key != key:
            self._masks = {}
            for k, v in refs.items():
                try:
                    m = decode_mask(v["png"])
                    radius = float(v.get("radius") or 0)
                    if not radius:
                        box = m.getbbox() or (0, 0, REF, REF)
                        radius = max(box[2] - box[0], box[3] - box[1]) / 2
                    dm = dilate(m)
                    self._masks[k] = (dm, count(dm), halo_mask(radius))
                except Exception as e:  # noqa
                    self.log(f"référence {k} illisible : {e}")
            self._masks_key = key
        return self._masks

    def _best_at(self, wm, masks, cands, plausible=True):
        """Meilleur score par reference sur les fenetres candidates (coin haut-gauche dans l'image)."""
        best = {}
        for (x, y) in cands:
            win = wm.crop((x, y, x + REF, y + REF))
            n = None
            if plausible:
                n = count(win)
            for name, (m, nref, _halo) in masks.items():
                if plausible and not (0.4 * nref <= n <= 2.5 * nref):
                    continue
                s = jaccard(m, win)
                if name not in best or s > best[name][0]:
                    best[name] = (s, (x, y))
        return best

    def _halo_ok(self, wm, masks, name, x, y):
        """Vrai si l'anneau autour de l'icone (fenetre REF en x, y) ne contient presque pas de blanc :
        c'est le disque gris de la bulle, pas un texte ni une tache blanche plus grande que l'icone."""
        from PIL import ImageChops
        halo, r2 = masks[name][2]
        cx, cy = x + REF // 2, y + REF // 2
        win = wm.crop((cx - r2, cy - r2, cx + r2 + 1, cy + r2 + 1))
        white = count(ImageChops.darker(win, halo))
        return white <= 0.06 * count(halo)

    def _pick(self, wm, masks, best, ox, oy, match, scores):
        """Parmi les meilleurs scores par reference, le premier au-dessus du seuil dont le halo est propre."""
        for name, (s, (x, y)) in sorted(best.items(), key=lambda kv: -kv[1][0]):
            if s < match:
                break
            if self._halo_ok(wm, masks, name, x, y):
                return name, s, (ox + x + REF // 2, oy + y + REF // 2)
            scores[name + "_halo"] = "rejeté"
        return None

    def _find(self, wide=False):
        """Etat de la bulle : (etat, centre absolu ou None, scores).
        Etats : cook, ready, spatula (anneau vert : il faut cliquer), cooking (spatule sans anneau), none.
        Suivi local (petite capture autour de la derniere position) puis, s'il echoue, recherche large
        dans la zone calibree (grille grossiere, affinage, verification du halo)."""
        c = self.cook_cfg
        rect = [int(v) for v in c["points"]["search"]]
        masks = self._load_masks()
        if not masks:
            raise RuntimeError("aucune icône de référence : refais le calibrage")
        match = float(c.get("match", 0.55))
        found = None            # (nom, score, centre absolu)
        scores = {}
        im = ox = oy = None
        if self._pos is not None and not wide:
            r = REF // 2 + LOCAL + 48
            ox, oy = self._pos[0] - r, self._pos[1] - r
            im = grab((ox, oy, ox + 2 * r, oy + 2 * r))
            if im is None:
                raise RuntimeError("capture d'écran impossible")
            self._last_im = im
            wm = dilate(white_mask(im))
            cx, cy = r - REF // 2, r - REF // 2
            cands = [(cx + dx, cy + dy) for dy in range(-LOCAL, LOCAL + 1, 4) for dx in range(-LOCAL, LOCAL + 1, 4)]
            best = self._best_at(wm, masks, cands, plausible=True)
            if best:
                # affinage au pixel pres autour du meilleur candidat
                name, (s, (x, y)) = max(best.items(), key=lambda kv: kv[1][0])
                fine = [(x + dx, y + dy) for dy in range(-3, 4) for dx in range(-3, 4)]
                best[name] = self._best_at(wm, {name: masks[name]}, fine, plausible=False).get(name) or best[name]
            scores = {k: round(v[0], 2) for k, v in best.items()}
            found = self._pick(wm, masks, best, ox, oy, match, scores)
        if found is None:
            ox, oy = rect[0], rect[1]
            im = grab(tuple(rect))
            if im is None:
                raise RuntimeError("capture d'écran impossible")
            self._last_im = im
            wm = dilate(white_mask(im))
            W, H = im.size
            cands = [(x, y) for y in range(0, max(1, H - REF + 1), COARSE) for x in range(0, max(1, W - REF + 1), COARSE)]
            coarse = self._best_at(wm, masks, cands)
            best = {}
            for name, (s, (x, y)) in coarse.items():
                if s < 0.2:
                    continue
                fine = [(x + dx, y + dy) for dy in range(-COARSE, COARSE + 1, 2) for dx in range(-COARSE, COARSE + 1, 2)]
                r = self._best_at(wm, {name: masks[name]}, fine, plausible=False).get(name)
                if r:
                    s2, (x2, y2) = r
                    fine = [(x2 + dx, y2 + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
                    best[name] = self._best_at(wm, {name: masks[name]}, fine, plausible=False).get(name) or r
            scores = {k: round(v[0], 2) for k, v in best.items()}
            found = self._pick(wm, masks, best, ox, oy, match, scores)
        state, pos = "none", self._pos
        if found:
            name, s, pos = found
            self._pos = pos
            state = "cooking" if name == "spatula" else name
        elif pos is not None:
            # icone non reconnue : si un anneau vert est la, on vise son centre et pas l'ancienne place de la
            # bulle (la camera a pu bouger quand le personnage a rejoint la cuisiniere)
            det = self._ring_only(Burner(0, pos), im, ox, oy)
            if det:
                pos = self._pos = det["pos"]
        green = 0
        if pos is not None:
            gx, gy = pos[0] - ox, pos[1] - oy
            if gx - RING < 0 or gy - RING < 0 or gx + RING > im.size[0] or gy + RING > im.size[1]:
                ring = grab((pos[0] - RING, pos[1] - RING, pos[0] + RING, pos[1] + RING))
            else:
                ring = im.crop((gx - RING, gy - RING, gx + RING, gy + RING))
            level = -1
            if ring is not None:
                green, level, _, _ = ring_read(ring, c.get("ring_color"), c.get("red_ring", True), int(c.get("green_px", 60)))
            if level >= 0:
                state = "spatula"
                scores["urgence"] = level
        scores["vert"] = green
        if state != self._last_state:
            self._last_state = state
            self.log(f"bulle : {state} {scores} à {pos}")
        return state, pos, scores

    # ---- detection de plusieurs bulles (multi-cuisinieres)
    def _all_at(self, wm, masks, cands, floor):
        """Tous les triplets (score, nom, coin haut-gauche) au-dessus de `floor` : contrairement a _best_at,
        on ne garde pas seulement le meilleur candidat par icone, sinon deux bulles n'en font qu'une."""
        out = []
        for (x, y) in cands:
            win = wm.crop((x, y, x + REF, y + REF))
            n = count(win)
            for name, (m, nref, _halo) in masks.items():
                if not (0.4 * nref <= n <= 2.5 * nref):
                    continue
                s = jaccard(m, win)
                if s >= floor:
                    out.append((s, name, (x, y)))
        return out

    @staticmethod
    def _peaks(raw, sep=SEP, limit=PEAKS_MAX):
        """Un pic par bulle : on parcourt les detections de la meilleure a la moins bonne et on ignore celles
        qui tombent a moins de `sep` px d'un pic deja retenu (c'est la meme bulle)."""
        kept = []
        for s, name, (x, y) in sorted(raw, key=lambda t: -t[0]):
            if all((x - kx) ** 2 + (y - ky) ** 2 >= sep * sep for _s, _n, (kx, ky) in kept):
                kept.append((s, name, (x, y)))
                if len(kept) >= limit:
                    break
        return kept

    def _around(self, wm, masks, x, y, span, step):
        """Meilleur score de chaque icone autour de (x, y), affine au pixel pres."""
        cands = [(x + dx, y + dy) for dy in range(-span, span + 1, step) for dx in range(-span, span + 1, step)]
        best = self._best_at(wm, masks, cands, plausible=False)
        for name, (s, (bx, by)) in list(best.items()):
            fine = [(bx + dx, by + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
            r = self._best_at(wm, {name: masks[name]}, fine, plausible=False).get(name)
            if r and r[0] > s:
                best[name] = r
        return best

    def _add_green(self, det, im, ox, oy):
        """Compte le vert autour d'une bulle reconnue : la spatule entouree de vert demande un clic."""
        c = self.cook_cfg
        x, y = det["pos"]
        ring = None
        if im is not None:
            gx, gy = x - ox, y - oy
            if gx - RING >= 0 and gy - RING >= 0 and gx + RING <= im.size[0] and gy + RING <= im.size[1]:
                ring = im.crop((gx - RING, gy - RING, gx + RING, gy + RING))
        if ring is None:
            ring = grab((x - RING, y - RING, x + RING, y + RING))
        green, level = 0, -1
        if ring is not None:
            green, level, _, _ = ring_read(ring, c.get("ring_color"), c.get("red_ring", True), int(c.get("green_px", 60)))
        det["scores"]["vert"] = green
        if level >= 0:
            det["state"] = "spatula"
            det["scores"]["urgence"] = level
        return green

    def _rings_quick(self):
        """Lecture rapide : seulement les anneaux (verts, ou jaunes / orange / rouges) de la zone, sans chercher
        les icones (quelques dizaines de ms au lieu de plusieurs dixiemes de seconde sur une grande zone).
        L'anneau ne dure que quelques secondes avant que le plat crame : il passe avant tout."""
        c = self.cook_cfg
        rect = [int(v) for v in c["points"]["search"]]
        try:
            im = grab(tuple(rect))
            if im is None:
                return []
            need = int(c.get("green_px", 60))
            found = [(cx, cy, n, 0) for cx, cy, n in find_rings(green_mask(im, c.get("ring_color")), need)]
            if c.get("red_ring", True):
                # pas d'arc chaud colle a un anneau vert : c'est son lisere, et son « centre » tombe a cote de la bulle
                found += [w for w in warm_arcs(im, need)
                          if not any((w[0] - g[0]) ** 2 + (w[1] - g[1]) ** 2 < RING_MAX * RING_MAX for g in found)]
        except Exception as e:  # noqa - la lecture rapide ne doit jamais arreter la cuisine : la lecture complete suit
            if not getattr(self, "_quick_failed", False):
                self._quick_failed = True
                self.log(f"lecture rapide des anneaux impossible ({e}) : lecture complète seulement")
            return []
        return [{"pos": (rect[0] + cx, rect[1] + cy), "state": "spatula", "scores": {"vert": n, "urgence": lvl}}
                for cx, cy, n, lvl in found]

    def _scan_wide(self):
        """Recherche large : TOUTES les bulles reconnues dans la zone calibree, separees spatialement.
        Renvoie une liste de dicts {pos, state, scores} (etats : cook, ready, spatula, cooking)."""
        c = self.cook_cfg
        rect = [int(v) for v in c["points"]["search"]]
        masks = self._load_masks()
        if not masks:
            raise RuntimeError("aucune icône de référence : refais le calibrage")
        match = float(c.get("match", 0.55))
        im = grab(tuple(rect))
        if im is None:
            raise RuntimeError("capture d'écran impossible")
        self._last_im = im
        self._wide_origin = (rect[0], rect[1])
        wm = dilate(white_mask(im))
        W, H = im.size
        cands = [(x, y) for y in range(0, max(1, H - REF + 1), COARSE) for x in range(0, max(1, W - REF + 1), COARSE)]
        out = []
        for _s, _name, (x, y) in self._peaks(self._all_at(wm, masks, cands, 0.2)):
            best = self._around(wm, masks, x, y, COARSE, 2)
            scores = {k: round(v[0], 2) for k, v in best.items()}
            found = self._pick(wm, masks, best, rect[0], rect[1], match, scores)
            if not found:
                continue
            name, s, pos = found
            # l'affinage peut faire converger deux pics vers la meme bulle : on garde la meilleure
            if any((pos[0] - d["pos"][0]) ** 2 + (pos[1] - d["pos"][1]) ** 2 < SEP * SEP for d in out):
                continue
            det = {"pos": pos, "state": "cooking" if name == "spatula" else name, "scores": scores}
            self._add_green(det, im, rect[0], rect[1])
            out.append(det)
        # anneaux verts de TOUTE la zone : pendant « Ajuste le feu » l'icone est animee et souvent pas
        # reconnue ; l'anneau, lui, se voit toujours. Il ne depend donc plus de la position suivie des bulles.
        need = int(c.get("green_px", 60))
        found = [(cx, cy, n, 0) for cx, cy, n in find_rings(green_mask(im, c.get("ring_color")), need)]
        if c.get("red_ring", True):                      # anneau passe au jaune, a l'orange ou au rouge
            # pas d'arc chaud colle a un anneau vert : c'est son lisere, et son « centre » tombe a cote de la bulle
            found += [w for w in warm_arcs(im, need)
                      if not any((w[0] - g[0]) ** 2 + (w[1] - g[1]) ** 2 < RING_MAX * RING_MAX for g in found)]
        for cx, cy, n, lvl in found:
            pos = (rect[0] + cx, rect[1] + cy)
            near = next((d for d in out if (pos[0] - d["pos"][0]) ** 2 + (pos[1] - d["pos"][1]) ** 2 < SEP * SEP), None)
            if near is not None:
                near["state"] = "spatula"
                near["scores"]["vert"] = max(n, near["scores"].get("vert", 0))
                near["scores"]["urgence"] = max(lvl, near["scores"].get("urgence", 0))
            else:
                out.append({"pos": pos, "state": "spatula", "scores": {"vert": n, "urgence": lvl}})
        out.sort(key=lambda d: (d["pos"][0], d["pos"][1]))
        self._debug_frame(im, rect, out)
        return out

    def _debug_frame(self, im, rect, dets):
        """cook.debug_frames (config.json, sans interface ; actif par defaut quand on tourne depuis les sources) : enregistre la zone de recherche et ce qui y a ete
        reconnu, 2 fois par seconde, dans <donnees>/cuisine_debug/ (900 images au plus, vide a chaque demarrage).
        Sert a comprendre un retour « il n'a pas clique » : le journal seul ne montre pas ce qui etait a l'ecran."""
        import sys
        if not self.cook_cfg.get("debug_frames", not getattr(sys, "frozen", False)) or self.state != "cooking":
            return
        now = time.perf_counter()
        if now - self._debug_at < 0.45 or self._debug_n >= 900:
            return
        self._debug_at = now
        try:
            folder = os.path.join(self.data_dir, "cuisine_debug")
            if self._debug_n == 0:
                os.makedirs(folder, exist_ok=True)
                for name in os.listdir(folder):
                    if name.startswith("z_") or name == "detections.jsonl":
                        os.remove(os.path.join(folder, name))
            self._debug_n += 1
            t = now - self._t0
            im.convert("RGB").save(os.path.join(folder, f"z_{t:07.2f}.jpg"), quality=70)
            import json
            with open(os.path.join(folder, "detections.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(t, 2), "origin": rect[:2],
                                    "dets": [[d["pos"][0], d["pos"][1], d["state"], d["scores"]] for d in dets],
                                    "burners": [[b.index, b.pos[0], b.pos[1], b.state] for b in self._burners]},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _scan_local(self, burner):
        """Suivi local d'une bulle connue : petite capture autour de sa derniere position (rapide).
        Renvoie {pos, state, scores} ou None si la bulle n'est plus reconnue la."""
        c = self.cook_cfg
        masks = self._load_masks()
        if not masks:
            raise RuntimeError("aucune icône de référence : refais le calibrage")
        match = float(c.get("match", 0.55))
        r = REF // 2 + LOCAL + 48
        ox, oy = burner.pos[0] - r, burner.pos[1] - r
        im = grab((ox, oy, ox + 2 * r, oy + 2 * r))
        if im is None:
            raise RuntimeError("capture d'écran impossible")
        self._last_im = im
        wm = dilate(white_mask(im))
        cx, cy = r - REF // 2, r - REF // 2
        cands = [(cx + dx, cy + dy) for dy in range(-LOCAL, LOCAL + 1, 4) for dx in range(-LOCAL, LOCAL + 1, 4)]
        best = self._best_at(wm, masks, cands, plausible=True)
        if best:
            name, (s, (x, y)) = max(best.items(), key=lambda kv: kv[1][0])
            fine = [(x + dx, y + dy) for dy in range(-3, 4) for dx in range(-3, 4)]
            best[name] = self._best_at(wm, {name: masks[name]}, fine, plausible=False).get(name) or best[name]
        scores = {k: round(v[0], 2) for k, v in best.items()}
        found = self._pick(wm, masks, best, ox, oy, match, scores)
        if not found:
            return self._ring_only(burner, im, ox, oy)
        name, s, pos = found
        det = {"pos": pos, "state": "cooking" if name == "spatula" else name, "scores": scores}
        self._add_green(det, im, ox, oy)
        return det

    def _still(self, pos, state):
        """Vrai si la bulle en `pos` est encore dans l'etat `state` : relecture locale juste avant d'appuyer. Entre
        la lecture de l'ecran et l'arrivee de la souris il se passe plus d'une seconde ; cliquer une spatule ou
        des gants qui ont disparu touche la cuisiniere elle-meme. En cas de doute (capture impossible) : vrai."""
        try:
            if state == "spatula":
                c = self.cook_cfg
                span = RING + 8
                part = grab((pos[0] - span, pos[1] - span, pos[0] + span, pos[1] + span))
                if part is None:
                    return True
                n = count(green_mask(part, c.get("ring_color")))
                if c.get("red_ring", True):
                    n += count(warm_mask(part))
                return n >= int(c.get("green_px", 60))
            det = self._scan_local(Burner(0, pos))
            if det is None:
                return False
            if state == "ready":
                # tolerant : un clic de trop sur des gants ne casse rien, un plat pret non ramasse bloque la cuisiniere
                return det["state"] == "ready" or float(det["scores"].get("ready", 0)) >= READY_SOFT
            return det["state"] == state
        except Exception:  # noqa - la relecture ne doit jamais arreter la cuisine
            return True

    def _ring_only(self, burner, im=None, ox=0, oy=0):
        """Icone non reconnue (spatule animee, recouverte, bulle qui vient de glisser...) : s'il y a un anneau
        vert pres de la derniere position connue, c'est quand meme une spatule a cliquer. La position renvoyee
        est le CENTRE DE L'ANNEAU (boite englobante du vert, en deux passes), pas l'ancienne place de la bulle :
        quand la camera vient de bouger, cliquer l'ancienne place tombait a cote (releve en jeu, 2026-09-21)."""
        c = self.cook_cfg
        need = int(c.get("green_px", 60))
        x, y = burner.pos
        green = 0
        for span in (RING + ASSOC, RING + 8):
            box = (x - span, y - span, x + span, y + span)
            if im is not None:
                l, t = max(0, box[0] - ox), max(0, box[1] - oy)
                r, b = min(im.size[0], box[2] - ox), min(im.size[1], box[3] - oy)
                if r - l < 8 or b - t < 8:
                    return None
                part, px, py = im.crop((l, t, r, b)), ox + l, oy + t
            else:
                part, px, py = grab(box), box[0], box[1]
            if part is None:
                return None
            green, level, gm, centre = ring_read(part, c.get("ring_color"), c.get("red_ring", True), need)
            bb = gm.getbbox()
            if level < 0 or not bb:
                return None
            if centre is not None:                       # arc chaud : le centre du cercle, pas celui de l'arc
                x, y = px + centre[0], py + centre[1]
                continue
            x, y = px + (bb[0] + bb[2]) // 2, py + (bb[1] + bb[3]) // 2
        return {"pos": (x, y), "state": "spatula", "scores": {"vert": green, "urgence": level}}

    def _scan(self, wide=False):
        """Met a jour les cuisinieres suivies. Suivi local tant que toutes les bulles sont retrouvees ;
        recherche large quand il en manque une, quand il reste des cuisinieres a decouvrir, ou toutes les
        WIDE_EVERY secondes (les bulles bougent un peu d'un plat a l'autre)."""
        now = time.perf_counter()
        age = now - self._wide_at
        manque = len(self._burners) < self.cookers     # cuisinieres pas encore reperees
        if (wide or not self._burners or age > WIDE_EVERY or (manque and age > 0.5)
                or now < self._wide_until or self._merged()):
            self._wide_at = now
            self._assign(self._scan_wide())
            return self._burners
        self._stray_rings = []
        for b in list(self._burners):
            det = self._scan_local(b)
            if det is None:
                b.lost += 1
                if b.lost >= 2:                 # bulle perdue : on refait tout de suite une recherche large
                    self._wide_at = time.perf_counter()
                    self._assign(self._scan_wide())
                    return self._burners
            else:
                self._apply(b, det)
        return self._burners

    def _acted(self, b):
        """A appeler juste avant de cliquer la bulle de `b`. Dans le jeu, les bulles sont accrochees aux
        cuisinieres (dans le decor) et le personnage rejoint celle qu'on clique : la camera le suit et TOUTES
        les bulles glissent a l'ecran (60 a 150 px releves en 1080p). Pendant ce mouvement le suivi local
        pourrait s'accrocher a la bulle de la voisine : on force la recherche large, qui rapparie l'ensemble."""
        now = time.perf_counter()
        self._wide_until = now + CAM_SETTLE
        self._clicked_at = now
        self._stand = b
        self._menu_for = b if (b is None or b.index) else None      # index 0 = cuisiniere de passage, non suivie

    def _merged(self):
        """Vrai si deux cuisinieres suivies pointent la meme bulle (suivi local accroche a la voisine)."""
        bs = self._burners
        return any((p.pos[0] - q.pos[0]) ** 2 + (p.pos[1] - q.pos[1]) ** 2 < SEP * SEP
                   for i, p in enumerate(bs) for q in bs[i + 1:])

    @staticmethod
    def _compatible(b, state):
        """Une cuisson lancee et pas encore recuperee ne peut pas montrer « cuisiner », et une cuisiniere au
        repos ne peut pas montrer la spatule : sert a departager deux appariements autrement equivalents."""
        if state == "cook":
            return not b.launched
        if state in ("cooking", "spatula"):
            return bool(b.launched)
        return True

    def _match(self, dets):
        """Apparie les detections aux cuisinieres suivies. La camera deplace toutes les bulles ENSEMBLE : on
        essaie chaque glissement commun possible (aucun, ou celui qui amene la cuisiniere i sur la detection j)
        et on garde celui qui explique le plus de bulles, puis le plus coherent avec l'etat des cuissons, puis
        le plus petit. Renvoie (paires [(cuisiniere, detection)], glissement retenu)."""
        burners = self._burners
        hyps = [(0, 0)] + [(d["pos"][0] - b.pos[0], d["pos"][1] - b.pos[1]) for b in burners for d in dets]
        if time.perf_counter() - self._clicked_at > CAM_WINDOW:
            # personne n'a clique de bulle depuis un moment : le personnage ne marche pas, la camera est fixe
            hyps = [t for t in hyps if t[0] * t[0] + t[1] * t[1] <= ASSOC * ASSOC]
        best_key, best = None, ([], (0, 0))
        for t in hyps:
            cand = []
            for b in burners:
                px, py = b.pos[0] + t[0], b.pos[1] + t[1]
                for d in dets:
                    d2 = (d["pos"][0] - px) ** 2 + (d["pos"][1] - py) ** 2
                    if d2 <= ASSOC * ASSOC:
                        cand.append((d2, id(b), id(d), b, d))
            cand.sort(key=lambda c: c[:3])
            used, pairs, resid = set(), [], 0
            for d2, ib, idd, b, d in cand:
                if ib in used or idd in used:
                    continue
                used.update((ib, idd))
                pairs.append((b, d))
                resid += d2
            ok = sum(1 for b, d in pairs if self._compatible(b, d["state"]))
            key = (len(pairs), ok, -(t[0] * t[0] + t[1] * t[1]), -resid)
            if best_key is None or key > best_key:
                best_key, best = key, (pairs, t)
        return best

    def _assign(self, dets):
        """Rattache les detections d'une recherche large aux cuisinieres suivies (voir _match), fait suivre le
        glissement de la camera a celles qui n'ont pas ete vues, cree les nouvelles tant qu'il en manque, et
        passe a « none » celles qui restent sans bulle."""
        pairs, t = self._match(dets) if self._burners and dets else ([], (0, 0))
        if len(self._burners) < self.cookers and (t[0] * t[0] + t[1] * t[1]) > ASSOC * ASSOC:
            # il reste une cuisiniere a decouvrir : une bulle lointaine ET incoherente avec la cuisson en cours
            # (« cuisiner » alors que celle-ci vient d'etre lancee) est la cuisiniere manquante, pas un glissement
            keep = [(b, d) for b, d in pairs if self._compatible(b, d["state"])]
            if len(keep) < len(pairs):
                pairs = keep
                if not pairs:
                    t = (0, 0)
        seen = {id(b) for b, _ in pairs}
        taken = {id(d) for _, d in pairs}
        free = [b for b in self._burners if id(b) not in seen]
        news = sorted((d for d in dets if id(d) not in taken), key=lambda d: (d["pos"][0], d["pos"][1]))
        if pairs and (t[0] or t[1]):
            for b in free:                      # pas vue cette fois : elle a glisse avec les autres
                b.pos = (b.pos[0] + t[0], b.pos[1] + t[1])
            if t[0] * t[0] + t[1] * t[1] > ASSOC * ASSOC:
                self.log(f"la vue a glissé de {t[0]:+d},{t[1]:+d} px : bulles rappariées")
        if (len(self._burners) >= self.cookers and free and len(free) == len(news)
                and time.perf_counter() - self._clicked_at <= CAM_WINDOW):
            # tout le monde est connu et il reste autant de bulles que de cuisinieres sans bulle : la
            # perspective a change plus que la tolerance -> meme ordre le long de l'axe ou elles s'alignent
            xs = [b.pos[0] for b in self._burners]
            ys = [b.pos[1] for b in self._burners]
            axis = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
            free.sort(key=lambda b: b.pos[axis])
            news.sort(key=lambda d: d["pos"][axis])
            pairs += list(zip(free, news))
            free, news = [], []
        for b, det in pairs:
            det["burner"] = b
            self._apply(b, det)
        self._stray_rings = []
        for det in news:
            if len(self._burners) >= self.cookers:
                if det["state"] == "spatula":
                    # un anneau vert ne se jette jamais : a la cuisiniere sans bulle la plus proche, sinon
                    # il sera clique quand meme par la boucle (anneau « sans cuisiniere »)
                    if free:
                        b = min(free, key=lambda f: (f.pos[0] - det["pos"][0]) ** 2 + (f.pos[1] - det["pos"][1]) ** 2)
                        free.remove(b)
                        det["burner"] = b
                        self._apply(b, det)
                    else:
                        self._stray_rings.append(det["pos"])
                    continue
                now = time.perf_counter()
                if now - self._stray_at > 5.0:
                    self._stray_at = now
                    self.log(f"bulle « {det['state']} » en {det['pos'][0]},{det['pos'][1]} ignorée "
                             f"({self.cookers} cuisinières déjà suivies)")
                continue
            b = Burner(len(self._burners) + 1, det["pos"])
            if det["state"] in ("cooking", "spatula"):
                b.launched = time.perf_counter()   # cuisson deja en cours : elle a droit a sa fenetre de risque
            self._burners.append(b)
            self.log(f"cuisinière {b.index} repérée en {b.pos[0]},{b.pos[1]}")
            det["burner"] = b
            self._apply(b, det)
        for b in free:
            det = self._ring_only(b, self._last_im, *self._wide_origin)
            if det and any((det["pos"][0] - o.pos[0]) ** 2 + (det["pos"][1] - o.pos[1]) ** 2 < SEP * SEP
                           for o in self._burners if o is not b and o.state != "none"):
                det = None                     # c'est l'anneau de la voisine, deja suivie
            self._apply(b, det)

    def _apply(self, b, det):
        """Applique une detection (ou son absence) a une cuisiniere et journalise les changements d'etat."""
        now = time.perf_counter()
        state = det["state"] if det else "none"
        if det:
            if abs(det["pos"][0] - b.pos[0]) > STILL or abs(det["pos"][1] - b.pos[1]) > STILL:
                b.moved = now
            b.pos = det["pos"]
            b.scores = det["scores"]
            b.seen = now
            b.lost = 0
        if state != b.state:
            b.state = state
            b.since = now
            self.log(f"bulle {b.index} : {state} {b.scores} à {b.pos[0]},{b.pos[1]}")

    def test(self):
        """Lecture immediate de l'ecran (bouton « Tester la détection ») : phrase pour l'interface."""
        if self.state != "idle":
            return "Occupé (cuisine ou calibrage en cours)."
        if not self.calibrated():
            return "La cuisine n'est pas calibrée."
        names = {"cook": "bulle « cuisiner »", "ready": "bulle « récupérer »", "spatula": "spatule avec anneau vert",
                 "cooking": "spatule sans anneau", "none": "aucune bulle reconnue"}
        if self.cookers > 1:
            return self._test_multi(names)
        try:
            self._last_state = None
            st, pos, sc = self._find(wide=True)
        except Exception as e:  # noqa
            self.test_result = f"Échec : {e}"
            return self.test_result
        detail = ", ".join(f"{k} {v}" for k, v in sc.items())
        menu = "menu Recettes ouvert" if self._menu_open() else "menu fermé"
        self.test_result = f"{names.get(st, st)}" + (f" en {pos[0]},{pos[1]}" if pos and st != "none" else "") + f" ({detail}) ; {menu}."
        self.log("test : " + self.test_result)
        return self.test_result

    def _test_multi(self, names):
        """« Tester la détection » avec plusieurs cuisinières : une ligne par bulle trouvée dans la zone."""
        n = self.cookers
        try:
            dets = self._scan_wide()
        except Exception as e:  # noqa
            self.test_result = f"Échec : {e}"
            return self.test_result
        menu = "menu Recettes ouvert" if self._menu_open() else "menu fermé"
        if not dets:
            self.test_result = f"Aucune bulle reconnue dans la zone ({n} cuisinières attendues) ; {menu}."
        else:
            parts = []
            for i, d in enumerate(dets[:n], 1):
                detail = ", ".join(f"{k} {v}" for k, v in d["scores"].items())
                parts.append(f"{i}. {names.get(d['state'], d['state'])} en {d['pos'][0]},{d['pos'][1]} ({detail})")
            extra = f" — {len(dets) - n} bulle(s) en trop ignorée(s)" if len(dets) > n else ""
            if len(dets) < n:
                extra = (f" — {n} cuisinières attendues : aucune autre bulle dans la zone calibrée "
                         f"(élargis-la ou rapproche les cuisinières)")
            self.test_result = f"{len(dets)} bulle(s) : " + " ; ".join(parts) + extra + f" ; {menu}."
        self.log("test : " + self.test_result)
        return self.test_result

    # ---- etat pour l'interface
    def status(self):
        c = self.cook_cfg
        elapsed = (time.perf_counter() - self.started_at) if self.started_at else 0.0
        burners = [b.to_dict() for b in list(self._burners)]
        return {
            "cookers": self.cookers,
            "burners": burners,
            "tracked": len(burners),
            "state": self.state,
            "phase": self.phase,
            "step": self.step,
            "steps": [{"key": k, "title": t, "help": h, "optional": k in OPTIONAL} for k, t, h in self.steps],
            "countdown": round(self.countdown, 1),
            "elapsed": elapsed,
            "dishes": self.dishes,
            "fires": self.fires,
            "message": self.message,
            "stop_reason": self.last_stop_reason,
            "calibrated": self.calibrated(),
            "refs": {k: (k in c["refs"]) for k in ("cook", "spatula", "ready")},
            "ring_color": c.get("ring_color"),
            "test_result": self.test_result,
            "settings": {"cookers": self.cookers,
                         "max_dishes": int(c.get("max_dishes", 0) or 0), "cook_timeout": float(c.get("cook_timeout", 240.0)),
                         "match": float(c.get("match", 0.55)), "click_delay": float(c.get("click_delay", 0.3)),
                         "green_px": int(c.get("green_px", 60))},
            "screen_ok": SCREEN_OK,
        }
