# -*- coding: utf-8 -*-
"""Dessin dans le jeu : faux écran + fausses règles du jeu, pour tester ce que draw.py fait vraiment.

`Jeu` rend une toile de W × H cases dont la grille est placée par le jeu à `dx, dy` pixels du calibrage
(c'est le cas réel : le calibrage donne le bord du canevas, pas l'endroit exact où le jeu met ses cases ;
avec des cases de 4,4 px un décalage de 2 px fait tomber la moitié des clics dans la case voisine). Comme
dans le journal du 16/09, le pot de peinture remplit tout le cadre calibré (la mesure du rectangle rempli ne
révèle donc PAS le décalage), seules les cases peintes au crayon montrent où sont vraiment les cases. Les
cellules ont une ligne de grille sur leur dernier pixel, les cases vides sont rayées. Les clics et
déplacements de la souris (bot.py / draw.py) sont renvoyés au faux jeu : palette, nuances, crayon (ligne
entre deux positions tant que le bouton est enfoncé), pot de peinture (4-connexe), Annuler.

Les temporisations de draw.py sont divisées par 25 (fixture `rapide`) : les vraies séquences de clics sont
jouées, en quelques secondes."""
import math
import threading
import time

import pytest
from PIL import Image, ImageDraw

import bot
import draw

W, H = 60, 40
CW, CH = 4.4, 4.38                        # tailles réelles vues dans le journal de l'utilisateur (1:1, 150 cases)
RECT = [600.0, 250.0, round(600 + W * CW, 2), round(250 + H * CH, 2)]
ECRAN = (1000, 600)
FOND = (40, 40, 40)
RAYURES = [(205, 205, 205), (215, 215, 215)]
GRILLE = (150, 150, 150)
FERME = (90, 60, 30)                      # pastille de la bande des familles quand les nuances sont fermées

PAL0, PAL1 = (900, 100), (960, 240)       # palette principale 2 × 8
BTN, STRIP, PREV, NEXT = (880, 60), (930, 300), (900, 300), (960, 300)
SUB0, SUB1 = (920, 340), (960, 420)       # nuances 2 × 5
PENCIL, BUCKET, UNDO = (50, 100), (50, 150), (50, 200)
HIT = 10                                  # rayon (px) des boutons


def flat(fam, j):
    """Index plat (draw.SHADES) de la nuance j de la famille fam."""
    return next(i for i, (f, jj, _) in enumerate(draw.SHADES) if f == fam and jj == j)


ROUGE, JAUNE, VERT, BLEU = flat(4, 0), flat(7, 0), flat(9, 0), flat(12, 0)


def image_test():
    """60 × 40 : fond bleu, disque rouge, rectangle jaune, points verts isolés, un bloc laissé vide."""
    cells = [BLEU] * (W * H)
    for y in range(H):
        for x in range(W):
            if (x - 20) ** 2 + (y - 22) ** 2 <= 64:
                cells[y * W + x] = ROUGE
            elif 35 <= x <= 55 and 5 <= y <= 15:
                cells[y * W + x] = JAUNE
            elif x > 30 and y > 20 and (x * 7 + y * 3) % 11 == 0:
                cells[y * W + x] = VERT
    for y in range(2, 5):
        for x in range(2, 5):
            cells[y * W + x] = -1
    return cells


# ---------------------------------------------------------------- faux jeu
class Jeu:
    def __init__(self, dx=0.0, dy=0.0):
        self.lock = threading.RLock()
        self.gx0, self.gy0 = RECT[0] + dx, RECT[1] + dy      # origine réelle de la grille du jeu
        self.gcw, self.gch = CW, CH
        self.cells = [-1] * (W * H)
        self.tool = "pencil"
        self.color = ROUGE
        self.family = 4
        self.page = None            # nuances ouvertes : index dans draw.PAGES
        self.pen = False
        self.prev = None
        self.mouse = (0, 0)
        self.history = []
        self.fills = 0
        self.undos = 0
        self.clicks = 0
        self.wasted = 0             # cases repeintes au crayon alors qu'elles avaient déjà la bonne couleur
        self._img = None

    # ---- géométrie du jeu
    def cell_at(self, x, y):
        cx = math.floor((x - self.gx0) / self.gcw)
        cy = math.floor((y - self.gy0) / self.gch)
        if 0 <= cx < W and 0 <= cy < H:
            return cy * W + cx
        return None

    def _bbox(self, cx, cy):
        return (int(round(self.gx0 + cx * self.gcw)), int(round(self.gy0 + cy * self.gch)),
                int(round(self.gx0 + (cx + 1) * self.gcw)), int(round(self.gy0 + (cy + 1) * self.gch)))

    # ---- rendu
    def image(self):
        if self._img is not None:
            return self._img
        im = Image.new("RGB", ECRAN, FOND)
        d = ImageDraw.Draw(im)
        # fond du cadre calibré : rayures, ou la couleur du pot si elle couvre (presque) toute la toile
        counts = {}
        for k in self.cells:
            counts[k] = counts.get(k, 0) + 1
        top = max(counts, key=counts.get)
        rx0, ry0, rx1, ry1 = int(RECT[0]), int(RECT[1]), int(round(RECT[2])), int(round(RECT[3]))
        if top >= 0 and counts[top] >= 0.95 * W * H:
            d.rectangle((rx0, ry0, rx1 - 1, ry1 - 1), fill=tuple(draw.SHADES[top][2]))
        else:
            for y in range(ry0, ry1):
                d.line((rx0, y, rx1 - 1, y), fill=RAYURES[(y // 3) % 2])
        for cy in range(H):
            for cx in range(W):
                x0, y0, x1, y1 = self._bbox(cx, cy)
                d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=GRILLE)
                k = self.cells[cy * W + cx]
                if k >= 0:
                    d.rectangle((x0, y0, x1 - 2, y1 - 2), fill=tuple(draw.SHADES[k][2]))
                else:
                    for y in range(y0, y1 - 1):
                        d.line((x0, y, x1 - 2, y), fill=RAYURES[(y // 3) % 2])
        for i in range(16):
            c, r = i % 2, i // 2
            x, y = PAL0[0] + 60 * c, PAL0[1] + 20 * r
            d.rectangle((x - 6, y - 6, x + 6, y + 6), fill=tuple(draw.DEFAULT_PALETTE[i]))
        strip = tuple(draw.DEFAULT_PALETTE[draw.PAGES[self.page]]) if self.page is not None else FERME
        d.rectangle((STRIP[0] - 4, STRIP[1] - 4, STRIP[0] + 4, STRIP[1] + 4), fill=strip)
        self._img = im
        return im

    def grab(self, rect=None):
        with self.lock:
            im = self.image()
            if rect is None:
                return im.copy()
            return im.crop(tuple(int(v) for v in rect))

    def _dirty(self):
        self._img = None

    # ---- souris
    def cursor_pos(self):
        return list(self.mouse)

    def mouse_move(self, x, y):
        with self.lock:
            self.mouse = (x, y)
            if self.pen and self.tool == "pencil":
                c = self.cell_at(x, y)
                if c is not None and self.prev is not None and c != self.prev:
                    self._line(self.prev, c)
                elif c is not None and self.prev is None:
                    self._paint(c)
                self.prev = c

    def mouse_down(self):
        with self.lock:
            self.pen = True
            self.prev = None
            self.clicks += 1
            self._click(*self.mouse)

    def mouse_up(self):
        with self.lock:
            self.pen = False
            self.prev = None

    @staticmethod
    def _near(p, q):
        return abs(p[0] - q[0]) <= HIT and abs(p[1] - q[1]) <= HIT

    def _click(self, x, y):
        p = (x, y)
        if self._near(p, PENCIL):
            self.tool = "pencil"
        elif self._near(p, BUCKET):
            self.tool = "bucket"
        elif self._near(p, UNDO):
            if self.history:
                self.cells = self.history.pop()
                self.undos += 1
                self._dirty()
        elif self._near(p, BTN):
            self.page = draw.PAGES.index(self.family) if self.family in draw.PAGES else 0
            self._dirty()
        elif self.page is not None and self._near(p, PREV):
            self.page = max(0, self.page - 1)
            self._dirty()
        elif self.page is not None and self._near(p, NEXT):
            self.page = min(len(draw.PAGES) - 1, self.page + 1)
            self._dirty()
        elif self.page is not None and SUB0[0] - HIT <= x <= SUB1[0] + HIT and SUB0[1] - HIT <= y <= SUB1[1] + HIT:
            c = int(round((x - SUB0[0]) / (SUB1[0] - SUB0[0]) * (draw.SHADE_COLS - 1)))
            r = int(round((y - SUB0[1]) / (SUB1[1] - SUB0[1]) * (draw.SHADE_ROWS - 1)))
            fam = draw.PAGES[self.page]
            n = len(dict(draw.SHADE_FAMILIES)[fam])
            j = r * draw.SHADE_COLS + c
            if j < n:
                self.color = flat(fam, j)
        elif PAL0[0] - HIT <= x <= PAL1[0] + HIT and PAL0[1] - HIT <= y <= PAL1[1] + HIT:
            c = int(round((x - PAL0[0]) / 60))
            r = int(round((y - PAL0[1]) / 20))
            i = r * 2 + c
            if 0 <= i < 16:
                self.family = i
                self.color = draw.SHADE_MAIN.index(i)
        else:
            cell = self.cell_at(x, y)
            if cell is None:
                return
            self.history.append(list(self.cells))
            if self.tool == "pencil":
                self._paint(cell)
                self.prev = cell
            else:
                self._flood(cell)

    # ---- peinture
    def _paint(self, cell):
        if self.cells[cell] != self.color:
            self.cells[cell] = self.color
            self._dirty()
        else:
            self.wasted += 1

    def _line(self, a, b):
        x0, y0, x1, y1 = a % W, a // W, b % W, b // W
        n = max(abs(x1 - x0), abs(y1 - y0))
        for i in range(n + 1):
            x = int(round(x0 + (x1 - x0) * i / n))
            y = int(round(y0 + (y1 - y0) * i / n))
            self._paint(y * W + x)

    def _flood(self, seed):
        self.fills += 1
        old = self.cells[seed]
        if old == self.color:
            return
        stack = [seed]
        self.cells[seed] = self.color
        while stack:
            c = stack.pop()
            x, y = c % W, c // W
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < W and 0 <= ny < H:
                    m = ny * W + nx
                    if self.cells[m] == old:
                        self.cells[m] = self.color
                        stack.append(m)
        self._dirty()


# ---------------------------------------------------------------- montage
def config(**extra):
    d = {"palette": {"pos0": list(PAL0), "pos1": list(PAL1), "cols": 2, "rows": 8,
                     "colors": [list(c) for c in draw.DEFAULT_PALETTE], "btn": list(BTN), "strip": list(STRIP),
                     "prev": list(PREV), "next": list(NEXT), "sub0": list(SUB0), "sub1": list(SUB1)},
         "tools": {"pencil": list(PENCIL), "bucket": list(BUCKET), "undo": list(UNDO)},
         "formats": {"16:9": {"rect": list(RECT), "cols": W, "rows": H}},
         "step_delay": 0.02, "click_delay": 0.05, "fill_background": True, "skip_white": False, "verify": True,
         "dense": False, "refine": True, "outline": False, "mouse_glide": False, "glide_speed": 1.0}
    d.update(extra)
    return {"draw": d, "hotkeys": {}}


@pytest.fixture
def rapide(monkeypatch):
    """Toutes les attentes de draw.py divisées par 25 : la mécanique réelle des clics, en quelques secondes."""
    vrai = draw.Drawer._sleep
    monkeypatch.setattr(draw.Drawer, "_sleep", lambda self, s: vrai(self, s / 25.0))


@pytest.fixture
def jeu(monkeypatch):
    """Fabrique (jeu, drawer) : écran, souris et bouton de la souris bouchonnés."""
    faits = []

    def build(dx=0.0, dy=0.0, cfg=None, **extra):
        j = Jeu(dx, dy)
        monkeypatch.setattr(draw, "grab", j.grab)
        monkeypatch.setattr(draw, "mouse_down", j.mouse_down)
        monkeypatch.setattr(draw, "mouse_up", j.mouse_up)
        monkeypatch.setattr(draw, "cursor_pos", j.cursor_pos)
        monkeypatch.setattr(draw, "SCREEN_OK", True)
        monkeypatch.setattr(bot, "mouse_move", j.mouse_move)
        monkeypatch.setattr(bot, "mouse_down", j.mouse_down)
        monkeypatch.setattr(bot, "mouse_up", j.mouse_up)
        monkeypatch.setattr(bot, "cursor_pos", j.cursor_pos)
        logs = []
        c = cfg or config(**extra)
        d = draw.Drawer(c, log=logs.append, on_change=lambda: None, save=lambda: None, logfile=None)
        d.logs = logs
        d.jeu = j
        faits.append(d)
        return j, d
    yield build
    for d in faits:
        d.stop("fin du test")
        if d._thread:
            d._thread.join(timeout=10)


def job(cells=None):
    cells = cells or image_test()
    return {"format": "16:9", "w": W, "h": H, "cells": list(cells), "skip": []}


def dessine(d, cells=None, timeout=120):
    d._last_toggle = 0.0                      # anti-rebond du bouton (0,8 s) : sans objet ici
    assert d.start(job(cells), delay=0.0), "le dessin n'a pas démarré"
    d._thread.join(timeout=timeout)
    assert not d._thread.is_alive(), "le dessin ne s'est pas terminé à temps"
    return d.message


def manquantes(j, cells):
    return [i for i, k in enumerate(cells) if k >= 0 and j.cells[i] != k]


# ---------------------------------------------------------------- lecture de l'écran
def test_lecture_canevas_vote_3x3(jeu):
    """Une toile entièrement peinte (rendu direct) est relue sans erreur, même avec un centre calculé qui
    tombe à un demi-pixel près (le vote sur la croix absorbe la ligne de grille)."""
    j, d = jeu()
    cells = image_test()
    j.cells = [k if k >= 0 else BLEU for k in cells]
    j._dirty()
    d._empty_colors = [list(c) for c in RAYURES]
    for shift in (0.0, 0.5, -0.5):
        geo = [j.gx0 + shift, j.gy0 + shift, CW, CH, W, H]
        seen = d._read_canvas(geo)
        diff = [i for i in range(W * H) if seen[i] != j.cells[i]]
        assert not diff, f"décalage {shift} : {len(diff)} cases mal lues, ex. {diff[:5]}"


def test_lecture_toile_vide(jeu):
    """Toile vide (rayures proches d'un gris de la palette) : tout est lu vide grâce aux teintes du vide."""
    j, d = jeu()
    d._empty_colors = [list(c) for c in RAYURES] + [list(GRILLE)]     # ce que _empties_setup relève
    seen = d._read_canvas([j.gx0, j.gy0, CW, CH, W, H])
    assert set(seen) == {-1}


# ---------------------------------------------------------------- géométrie décalée (le bug du 16/09)
def test_grille_decalee_est_mesuree_et_tout_est_peint(jeu, rapide):
    """Le jeu place ses cases 1,2 px à droite et 2,3 px plus bas que le calibrage : sans correction, la moitié
    des clics tombent dans la case du dessus. Les repères doivent mesurer ce décalage dès la première couleur,
    et toutes les cases doivent finir peintes, sans passes de réparation en cascade."""
    j, d = jeu(dx=1.2, dy=2.3)
    cells = image_test()
    msg = dessine(d, cells)
    assert d.last_stop_reason == "", (d.last_stop_reason, msg, d.logs[-5:])
    assert "terminé" in msg, msg
    assert not manquantes(j, cells), (len(manquantes(j, cells)), d.logs)
    assert any("géométrie mesurée" in l for l in d.logs), d.logs
    # ce qui compte : les centres calculés tombent dans la bonne case du jeu, aux quatre coins et au centre
    centre = d._center_fn(d._geo)
    for cx, cy in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1), (W // 2, H // 2)):
        assert j.cell_at(*centre(cx, cy)) == cy * W + cx, (cx, cy, centre(cx, cy), d._geo)
    assert abs(d._geo[2] - CW) < 0.05 and abs(d._geo[3] - CH) < 0.05, d._geo
    reparations = [l for l in d.logs if l.startswith("réparation")]
    assert len(reparations) <= 3, reparations
    assert d.unrepaired == 0
    # le calibrage enregistré est corrigé pour le prochain dessin
    rect = d.draw_cfg["formats"]["16:9"]["rect"]
    assert abs(rect[0] - d._geo[0]) < 0.01 and abs(rect[1] - d._geo[1]) < 0.01, (rect, d._geo)
    assert j.fills == 1


def test_grille_exacte_sans_reparation(jeu, rapide):
    """Calibrage juste : le dessin passe sans réparation et sans modifier la géométrie de plus d'un demi-pixel."""
    j, d = jeu()
    cells = image_test()
    msg = dessine(d, cells)
    assert "terminé" in msg, (msg, d.logs[-5:])
    assert not manquantes(j, cells), d.logs
    assert not [l for l in d.logs if l.startswith("réparation")], d.logs
    centre = d._center_fn(d._geo)
    for cx, cy in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1), (W // 2, H // 2)):
        assert j.cell_at(*centre(cx, cy)) == cy * W + cx, (cx, cy, centre(cx, cy), d._geo)


# ---------------------------------------------------------------- reprise d'un dessin interrompu
def test_reprise_apres_arret(jeu, rapide, monkeypatch):
    """Arrêt (touche) au milieu du dessin, puis relance sur la même toile : DodoTopia lit la toile, ne remplit
    pas le fond une deuxième fois, ne repeint que ce qui manque, et le résultat est complet."""
    j, d = jeu(dx=1.2, dy=2.3)
    cells = image_test()
    vrai = draw.Drawer._paint_strokes
    etat = {"stop": True}

    def coupe(self, *a, **kw):
        r = vrai(self, *a, **kw)
        if etat["stop"] and self.done > 0.4 * self.total:
            etat["stop"] = False
            self.stop("clavier touché")
        return r
    monkeypatch.setattr(draw.Drawer, "_paint_strokes", coupe)
    msg1 = dessine(d, cells)
    assert d.last_stop_reason == "clavier touché", (msg1, d.logs[-3:])
    restantes = manquantes(j, cells)
    assert restantes, "l'arrêt n'a rien laissé à reprendre"
    en_place = sum(1 for i, k in enumerate(cells) if k >= 0 and j.cells[i] == k)
    j.wasted = 0
    monkeypatch.setattr(draw.Drawer, "_paint_strokes", vrai)
    msg2 = dessine(d, cells)
    assert d.last_stop_reason == "", (msg2, d.logs[-5:])
    assert "terminé" in msg2 and "reprise" in msg2, msg2
    assert any(l.startswith("reprise d'un dessin") for l in d.logs), d.logs
    assert not manquantes(j, cells), d.logs
    assert j.fills == 1, "le fond a été rempli une seconde fois"
    assert j.wasted < 0.25 * en_place, f"la reprise a repeint {j.wasted} cases déjà en place (sur {en_place})"


def test_reprise_avec_fond_encore_vide(jeu, rapide):
    """Toile déjà entamée à la main (rectangle jaune peint) mais fond vide : le pot remplit la zone vide
    autour du centre, puis le reste est peint au crayon. Teintes du vide connues (config)."""
    j, d = jeu(dx=0.8, dy=1.0)
    cells = image_test()
    for i, k in enumerate(cells):
        if k == JAUNE:
            j.cells[i] = JAUNE
    j._dirty()
    d.draw_cfg["empty_colors"] = [list(c) for c in RAYURES]
    msg = dessine(d, cells)
    assert "terminé" in msg and "reprise" in msg, (msg, d.logs[-5:])
    assert not manquantes(j, cells), d.logs
    assert j.fills == 1


def test_reprise_sans_teintes_connues(jeu, rapide):
    """Même reprise, mais rien d'enregistré sur les teintes de la toile vide (ancienne config) : le dessin doit
    quand même finir complet, en estimant ces teintes sur la toile."""
    j, d = jeu()
    cells = image_test()
    for i, k in enumerate(cells):
        if k == JAUNE or k == ROUGE:
            j.cells[i] = k
    j._dirty()
    msg = dessine(d, cells)
    assert "terminé" in msg, (msg, d.logs[-5:])
    assert not manquantes(j, cells), (len(manquantes(j, cells)), d.logs)


def test_teintes_du_vide_enregistrees(jeu, rapide):
    """Un dessin sur toile vide mémorise les teintes des rayures dans la config (pour les reprises)."""
    j, d = jeu()
    dessine(d)
    stored = d.draw_cfg.get("empty_colors")
    assert stored and any(min(draw._cdist(s, r) for r in RAYURES) < 12 * 12 for s in stored), stored
    assert all(min(draw._cdist(s, c) for c in (RAYURES + [GRILLE])) < 12 * 12 for s in stored), stored


# ---------------------------------------------------------------- souris Windows
def test_coordonnee_absolue_souris():
    """SendInput : la coordonnée absolue doit retomber exactement sur le pixel visé après la conversion de
    Windows (troncature de dx * taille / 65536), sur tout bureau."""
    try:
        from _win_io import abs_coord
    except Exception:
        pytest.skip("module Windows")
    for origin, size in ((0, 1920), (0, 3600), (-111, 1191), (0, 1080)):
        for v in range(origin, origin + size):
            dx = abs_coord(v, origin, size)
            assert 0 <= dx <= 65535
            assert int(dx * size / 65536) + origin == v, (v, origin, size, dx)


# ---------------------------------------------------------------- mode contours, et repli sans repères
def test_mode_contours_grille_decalee(jeu, rapide):
    """Mode contours + pot de peinture, grille décalée : repères mesurés sur la première couleur, zones remplies
    au pot sans fuite, résultat complet."""
    j, d = jeu(dx=1.2, dy=2.3, outline=True)
    cells = image_test()
    msg = dessine(d, cells)
    assert d.last_stop_reason == "", (d.last_stop_reason, msg, d.logs[-5:])
    assert "terminé" in msg, msg
    assert not manquantes(j, cells), (len(manquantes(j, cells)), d.logs)
    assert any("géométrie mesurée" in l for l in d.logs), d.logs
    assert j.fills >= 2, "le pot n'a pas servi pour les zones"
    assert d.unrepaired == 0


def test_repli_decalage_appris_sans_reperes(jeu, rapide, monkeypatch):
    """Si les repères ne peuvent pas être mesurés (icône introuvable à l'écran), les passes de réparation
    décalées doivent quand même apprendre le décalage et le garder pour la suite du dessin."""
    monkeypatch.setattr(draw.Drawer, "_refine_marks", lambda self, k, *a, **kw: (self._marks_done.add(k), False)[1])
    j, d = jeu(dx=0.4, dy=2.0)
    cells = image_test()
    msg = dessine(d, cells)
    assert "terminé" in msg, (msg, d.logs[-5:])
    assert not manquantes(j, cells), (len(manquantes(j, cells)), d.logs)
    assert any(l.startswith("décalage appris") for l in d.logs), d.logs
    assert not [l for l in d.logs if "délai entre points" in l], ("le décalage a été pris pour un problème de rythme", d.logs)
    centre = d._center_fn(d._geo)
    for cx, cy in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1), (W // 2, H // 2)):
        assert j.cell_at(*centre(cx, cy)) == cy * W + cx, (cx, cy, centre(cx, cy), d._geo)
