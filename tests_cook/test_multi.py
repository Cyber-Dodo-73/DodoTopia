# -*- coding: utf-8 -*-
"""Cuisine à plusieurs cuisinières : détection de plusieurs bulles et ordonnanceur de cook.py.

Tout se passe devant un faux écran : des images PIL synthétiques (herbe + un disque gris par cuisinière,
avec une icône blanche dedans et, pendant « Ajuste le feu », un anneau vert) rendues à la volée par `Ecran`,
qui remplace `cook.grab`. Les clics de la souris (`bot.mouse_down`) sont renvoyés à `Ecran.clic`, qui joue
les règles du jeu (bulle → menu Recettes → Cuisiner → cuisson → anneau → gants → plat). Aucun vrai écran,
aucune vraie souris, aucun fichier du projet touché (voir conftest.py).

Les durées sont raccourcies : les temporisations fixes des clics de cook.py sont divisées par 10 (voir
`souris_rapide`) et le jeu simulé cuit en quelques dixièmes de seconde."""
import sys
import threading
import time

import pytest
from PIL import Image, ImageDraw

import bot
import cook

HERBE = (70, 110, 70)        # fond : vert sombre, jamais pris pour l'anneau (vert vif) ni pour du blanc
GRIS = (120, 120, 128)       # disque de la bulle
BLANC = (255, 255, 255)
VERT = (40, 220, 90)         # anneau « Ajuste le feu »
MENU = (60, 50, 40)          # le menu Recettes couvre l'écran : plus aucune bulle visible
BTN = (230, 120, 40)         # couleur du bouton Cuisiner (repère du menu ouvert)

ECRAN = (1200, 700)
ZONE = [200, 150, 900, 470]              # zone de recherche calibrée
TILE, COOK_BTN, NEUTRAL = (980, 300), (1050, 600), (150, 650)
POSTES = [(330, 300), (600, 300), (860, 300)]   # centres des bulles possibles (> REF px d'écart)

RING_DELAY = 0.25            # cuisson -> anneau vert
RING_TTL = 0.80              # durée de l'anneau : au-delà le plat est raté
SIMMER = 0.20                # feu ajusté -> plat prêt


# ---------------------------------------------------------------- icônes (trois formes blanches distinctes)
def _ic_cook(d, x, y):
    d.rectangle((x - 15, y - 15, x + 15, y + 15), fill=BLANC)


def _ic_ready(d, x, y):
    d.ellipse((x - 20, y - 9, x - 2, y + 9), fill=BLANC)
    d.ellipse((x + 2, y - 9, x + 20, y + 9), fill=BLANC)


def _ic_spatula(d, x, y):
    d.rectangle((x - 4, y - 4, x + 4, y + 17), fill=BLANC)
    d.ellipse((x - 11, y - 17, x + 11, y - 3), fill=BLANC)


ICONES = {"cook": _ic_cook, "ready": _ic_ready, "spatula": _ic_spatula}
PHASE_ICONE = {"repos": "cook", "cuisson": "spatula", "anneau": "spatula", "mijote": "spatula", "pret": "ready"}


def _bulle(d, pos, icone, anneau=False):
    x, y = pos
    d.ellipse((x - 40, y - 40, x + 40, y + 40), fill=GRIS)
    if anneau:
        d.ellipse((x - 48, y - 48, x + 48, y + 48), outline=VERT, width=6)
    ICONES[icone](d, x, y)


def reference(icone):
    """(png base64, rayon) d'une icône, comme le calibrage (cook.make_ref) les enregistre."""
    im = Image.new("RGB", (240, 240), HERBE)
    _bulle(ImageDraw.Draw(im), (120, 120), icone)
    m = cook.white_mask(im)
    box = m.getbbox()
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    rayon = max(box[2] - box[0], box[3] - box[1]) / 2
    x0, y0 = int(round(cx - cook.REF / 2)), int(round(cy - cook.REF / 2))
    return cook.encode_mask(m.crop((x0, y0, x0 + cook.REF, y0 + cook.REF))), round(rayon, 1)


# ---------------------------------------------------------------- faux écran + règles du jeu
class Poste:
    def __init__(self, index, pos, phase="repos"):
        self.index = index
        self.pos = pos
        self.phase = phase
        self.t = time.perf_counter()
        self.plats = 0
        self.gants_jusqua = 0.0     # la bulle « gants » reste affichée un instant après la récupération

    def passe(self, phase):
        self.phase = phase
        self.t = time.perf_counter()


class Ecran:
    """Faux écran du jeu : rend l'image, encaisse les clics et fait avancer les cuissons."""

    def __init__(self, phases=("repos",)):
        self.lock = threading.RLock()
        self.postes = [Poste(i + 1, POSTES[i], ph) for i, ph in enumerate(phases)]
        self.menu = False           # menu Recettes ouvert
        self.attente = None         # poste dont le menu est ouvert
        self.clics = []             # toutes les positions cliquées
        self.events = []            # ("lance"|"anneau"|"rate"|"plat", index)
        self.rates = 0
        self.on_launch = None       # scénario : rappel juste après un « Cuisiner » (voir les tests)
        self.menu_colle = False     # vrai jeu : un clic dans l'herbe ne ferme pas le menu Recettes
        self.gants_restent = 0.0    # durée d'affichage des gants après la récupération
        self.icone_cachee = False   # l'icône de la spatule n'est pas reconnaissable pendant l'anneau
        self.sans_bulle_en_cuisson = False   # vrai jeu : aucune bulle tant que ça cuit (hors anneau et gants)
        self.clics_perdus = 0       # vrai jeu : les N premiers clics sur un anneau ne sont pas pris
        self.vues = None            # vrai jeu : {index du poste: (dx, dy)} = glissement de TOUTES les bulles
        self.cam = (0, 0)           # quand le personnage rejoint ce poste (la caméra le suit)

    def ou(self, p):
        """Position à l'écran de la bulle du poste `p` (décalée par la caméra)."""
        return (p.pos[0] + self.cam[0], p.pos[1] + self.cam[1])

    # ---- temps
    def _tick(self):
        now = time.perf_counter()
        for p in self.postes:
            if p.phase == "cuisson" and now - p.t >= RING_DELAY:
                p.passe("anneau")
            elif p.phase == "anneau" and now - p.t >= RING_TTL:
                self.rates += 1
                self.events.append(("rate", p.index))
                p.passe("mijote")
            elif p.phase == "mijote" and now - p.t >= SIMMER:
                p.passe("pret")

    # ---- image
    def _image(self):
        im = Image.new("RGB", ECRAN, HERBE)
        d = ImageDraw.Draw(im)
        if self.menu:
            d.rectangle((0, 0, ECRAN[0], ECRAN[1]), fill=MENU)
            return im
        now = time.perf_counter()
        for p in self.postes:
            icone = "ready" if now < p.gants_jusqua else PHASE_ICONE[p.phase]
            if self.sans_bulle_en_cuisson and p.phase in ("cuisson", "mijote") and now >= p.gants_jusqua:
                continue
            if p.phase == "anneau" and self.icone_cachee:
                x, y = self.ou(p)
                d.ellipse((x - 40, y - 40, x + 40, y + 40), fill=GRIS)
                d.ellipse((x - 48, y - 48, x + 48, y + 48), outline=VERT, width=6)
                continue
            _bulle(d, self.ou(p), icone, anneau=(p.phase == "anneau"))
        return im

    def grab(self, rect=None):
        with self.lock:
            self._tick()
            im = self._image()
        if rect is None:
            return im
        return im.crop(tuple(int(v) for v in rect))

    def couleur(self, x, y, radius=4):
        with self.lock:
            return list(BTN) if self.menu else list(HERBE)

    # ---- clics
    def clic(self, x, y):
        with self.lock:
            self._tick()
            self.clics.append((x, y))
            if self.menu:
                if abs(x - COOK_BTN[0]) < 30 and abs(y - COOK_BTN[1]) < 30:
                    self.menu = False
                    if self.attente is not None:
                        poste, self.attente = self.attente, None
                        poste.passe("cuisson")
                        self.events.append(("lance", poste.index))
                        if self.on_launch:
                            self.on_launch(poste)
                elif not self.menu_colle and not (abs(x - TILE[0]) < 30 and abs(y - TILE[1]) < 30):
                    self.menu = False          # clic ailleurs : le menu se referme
                return
            for p in self.postes:
                px, py = self.ou(p)
                if (x - px) ** 2 + (y - py) ** 2 > 45 * 45:
                    continue
                if self.vues:
                    self.cam = self.vues[p.index]      # le personnage rejoint ce poste : toutes les bulles glissent
                if p.phase == "repos":
                    self.menu = True
                    self.attente = p
                elif p.phase == "anneau":
                    if self.clics_perdus > 0:
                        self.clics_perdus -= 1             # clic pas pris : l'anneau reste, il faut recliquer
                        self.events.append(("clic perdu", p.index))
                        return
                    self.events.append(("anneau", p.index))
                    p.passe("mijote")
                elif p.phase == "pret":
                    p.plats += 1
                    self.events.append(("plat", p.index))
                    p.passe("repos")
                    p.gants_jusqua = time.perf_counter() + self.gants_restent
                return


# ---------------------------------------------------------------- montage
def config(cookers=2, **extra):
    c = {"cookers": cookers, "poll": 0.02, "match": 0.62, "green_px": 60, "cook_timeout": 15.0,
         "click_delay": 0.02, "launch_guard": 0.15, "max_dishes": 0,
         "points": {"search": list(ZONE), "tile": list(TILE), "cook_btn": list(COOK_BTN),
                    "neutral": list(NEUTRAL), "cook": list(POSTES[0])},
         "cook_btn_color": list(BTN), "ring_color": None, "refs": {}}
    for k in ("cook", "ready", "spatula"):
        png, rayon = reference(k)
        c["refs"][k] = {"png": png, "radius": rayon}
    c.update(extra)
    return {"cook": c, "draw": {"mouse_glide": False, "click_delay": 0.0}, "hotkeys": {}}


@pytest.fixture
def souris_rapide(monkeypatch):
    """Les temporisations fixes des clics de cook.py (0,3 à 0,8 s) sont divisées par 10 : les tests jouent
    la vraie mécanique de clic, mais en quelques dixièmes de seconde."""
    vrai = cook.Cooker._click

    def rapide(self, x, y, delay=None):
        return vrai(self, x, y, delay=0.01 if delay is None else float(delay) / 10.0)
    monkeypatch.setattr(cook.Cooker, "_click", rapide)


@pytest.fixture
def jeu(monkeypatch, tmp_path):
    """Fabrique (écran, cooker) : cook.grab / la souris de bot.py / la couleur du bouton sont bouchonnés."""
    faits = []

    def build(phases=("repos", "repos"), cookers=2, **extra):
        ecran = Ecran(phases)
        souris = [NEUTRAL[0], NEUTRAL[1]]
        monkeypatch.setattr(cook, "grab", ecran.grab)
        monkeypatch.setattr(cook, "sample_color", ecran.couleur)
        monkeypatch.setattr(cook, "mouse_up", lambda *a: None)
        monkeypatch.setattr(bot, "mouse_move", lambda x, y: souris.__setitem__(slice(0, 2), [x, y]))
        monkeypatch.setattr(bot, "cursor_pos", lambda: (souris[0], souris[1]))
        monkeypatch.setattr(bot, "mouse_down", lambda: ecran.clic(souris[0], souris[1]))
        monkeypatch.setattr(bot, "mouse_up", lambda: None)
        logs = []
        c = cook.Cooker(config(cookers, **extra), log=logs.append, save=lambda: None,
                        logfile=str(tmp_path / "cuisine.log"), data_dir=str(tmp_path))
        c.logs = logs
        faits.append(c)
        return ecran, c
    yield build
    for c in faits:
        c.stop("fin du test")
        if c._thread:
            c._thread.join(timeout=5)


def tourne(cooker, ecran, duree=6.0, plats=2):
    """Lance la boucle et attend `plats` plats (ou `duree` secondes), puis l'arrête proprement."""
    assert cooker.start(delay=0.0), "la boucle n'a pas démarré"
    fin = time.perf_counter() + duree
    while time.perf_counter() < fin:
        if cooker.dishes >= plats or cooker.state != "cooking":
            break
        time.sleep(0.02)
    cooker.stop("fin du test")
    cooker._thread.join(timeout=5)
    assert not cooker._thread.is_alive()
    return cooker.message


# ---------------------------------------------------------------- détection
def test_deux_bulles_distinctes(jeu):
    """Deux bulles éloignées : deux détections séparées, chacune avec son état, sans se confondre."""
    ecran, c = jeu(phases=("repos", "pret"))
    dets = c._scan_wide()
    assert len(dets) == 2, dets
    assert [d["state"] for d in dets] == ["cook", "ready"]
    for det, poste in zip(dets, ecran.postes):
        assert abs(det["pos"][0] - poste.pos[0]) <= 3 and abs(det["pos"][1] - poste.pos[1]) <= 3
    assert (dets[1]["pos"][0] - dets[0]["pos"][0]) >= cook.SEP


def test_trois_bulles_et_anneau(jeu):
    """Trois cuisinières, dont une avec l'anneau vert : seule celle-là est en état « spatula »."""
    ecran, c = jeu(phases=("repos", "anneau", "cuisson"), cookers=3)
    dets = c._scan_wide()
    assert len(dets) == 3, dets
    assert [d["state"] for d in dets] == ["cook", "spatula", "cooking"]
    assert dets[1]["scores"]["vert"] >= 60
    # l'anneau disparaît : la même bulle redevient une simple cuisson, les deux autres ne bougent pas
    ecran.postes[1].passe("mijote")
    dets = c._scan_wide()
    assert [d["state"] for d in dets] == ["cook", "cooking", "cooking"]


def test_suivi_local_et_association(jeu):
    """Une bulle qui bouge de quelques pixels reste la même cuisinière (même index)."""
    ecran, c = jeu(phases=("repos", "cuisson"))
    c._scan(wide=True)
    assert [b.index for b in c._burners] == [1, 2]
    assert [b.state for b in c._burners] == ["cook", "cooking"]
    pos0 = c._burners[0].pos
    ecran.postes[0].pos = (POSTES[0][0] + 9, POSTES[0][1] - 7)   # la bulle flotte un peu
    ecran.postes[0].passe("pret")
    c._scan(wide=True)
    assert len(c._burners) == 2
    assert c._burners[0].index == 1 and c._burners[0].state == "ready"
    assert c._burners[0].pos != pos0
    # suivi local (sans recherche large) : la bulle est retrouvée autour de sa dernière position
    det = c._scan_local(c._burners[0])
    assert det is not None and det["state"] == "ready"


def test_bulle_perdue(jeu):
    """Menu Recettes ouvert (il couvre l'écran) : plus aucune bulle reconnue, mais les cuisinières restent
    suivies à leur dernière position et repassent à « none »."""
    ecran, c = jeu(phases=("repos", "cuisson"))
    c._scan(wide=True)
    ecran.menu = True
    c._scan(wide=True)
    assert len(c._burners) == 2
    assert [b.state for b in c._burners] == ["none", "none"]
    ecran.menu = False
    c._scan(wide=True)
    assert [b.state for b in c._burners] == ["cook", "cooking"]


# ---------------------------------------------------------------- ordonnanceur
def test_anneau_prioritaire_meme_apres_un_lancement(jeu, souris_rapide):
    """Scénario du bug : la cuisinière 2 vient d'être lancée quand l'anneau vert surgit sur la cuisinière 1.
    L'anneau doit être cliqué tout de suite (c'est minuté, sinon le plat est raté), sans attendre la fin de
    ce qui se passe sur la 2."""
    ecran, c = jeu(phases=("repos", "repos"), launch_guard=0.0)

    def au_lancement(poste):
        if poste.index == 2:                 # « Cuisiner » vient d'être cliqué sur la 2...
            ecran.postes[0].passe("anneau")  # ...et au même instant la 1 demande d'ajuster le feu
    ecran.on_launch = au_lancement
    tourne(c, ecran, duree=12.0, plats=2)
    ordre = [e for e in ecran.events if e[0] in ("lance", "anneau", "rate")]
    assert ("lance", 1) in ordre and ("lance", 2) in ordre, ecran.events
    apres = ordre[ordre.index(("lance", 2)):]
    assert ("anneau", 1) in apres, ecran.events      # l'anneau de la 1 a bien été cliqué après le lancement de la 2
    assert ecran.rates == 0, ecran.events            # aucun plat raté faute d'avoir vu l'anneau à temps
    assert c.dishes == sum(b.dishes for b in c._burners)


def test_la_camera_suit_le_personnage(jeu, souris_rapide):
    """Relevé en jeu (2026-09-21) : cliquer la bulle d'une cuisinière y envoie le personnage, la caméra le suit
    et les deux bulles glissent ensemble (ici la bulle 1 arrive à 25 px de l'ancienne place de la bulle 2).
    Avant : la bulle 1 était prise pour la 2, la vraie 2 jetée, une seule cuisinière servie."""
    ecran, c = jeu()
    ecran.vues = {1: (250, 15), 2: (0, 0)}
    tourne(c, ecran, duree=20.0, plats=4)
    assert c.dishes >= 4, c.logs
    assert all(p.plats >= 1 for p in ecran.postes), (ecran.events, c.logs)
    assert ecran.rates == 0, ecran.events
    assert any("la vue a glissé" in m for m in c.logs)


def test_anneau_clique_en_son_centre_apres_le_glissement(jeu, souris_rapide):
    """Relevé en jeu : l'anneau vert était cliqué à l'ANCIENNE place de la bulle (104 px à côté) quand l'icône
    n'était pas reconnue juste après le déplacement de la caméra. On vise maintenant le centre de l'anneau."""
    ecran, c = jeu()
    ecran.vues = {1: (250, 15), 2: (0, 0)}
    ecran.icone_cachee = True
    tourne(c, ecran, duree=20.0, plats=4)
    assert c.dishes >= 4, c.logs
    assert ecran.rates == 0, (ecran.events, c.logs)
    assert all(p.plats >= 1 for p in ecran.postes), ecran.events


def test_comme_dans_le_vrai_jeu(jeu, souris_rapide, monkeypatch):
    """Tout ce qui a été relevé en jeu le 2026-09-22, en même temps : pas de bulle pendant la cuisson, la caméra
    suit le personnage, l'icône est illisible pendant l'anneau, et des clics sur l'anneau ne sont pas pris.
    Attendu : les deux cuisinières tournent, aucun plat raté, tous les plats prêts sont ramassés."""
    monkeypatch.setattr(sys.modules[__name__], "RING_TTL", 2.5)
    ecran, c = jeu()
    ecran.vues = {1: (250, 15), 2: (0, 0)}
    ecran.sans_bulle_en_cuisson = True
    ecran.icone_cachee = True
    ecran.clics_perdus = 2
    tourne(c, ecran, duree=40.0, plats=6)
    assert c.dishes >= 6, c.logs
    assert all(p.plats >= 2 for p in ecran.postes), (ecran.events, c.logs)
    assert ecran.rates == 0, (ecran.events, c.logs)
    assert [e for e in ecran.events if e[0] == "clic perdu"], "le scénario n'a pas joué les clics perdus"


def test_un_plat_pret_est_ramasse_meme_sans_cuisiniere_rattachee(jeu, souris_rapide):
    """Journal du 2026-09-22 : « bulle ready ignorée (2 cuisinières déjà suivies) » pendant 7 s. La boucle agit
    sur ce qu'elle voit : un plat prêt est ramassé même si le suivi des cuisinières est faux."""
    ecran, c = jeu(phases=("pret", "cuisson"))
    ecran.sans_bulle_en_cuisson = True
    vrai = cook.Cooker._assign

    def faux(self, dets):
        vrai(self, dets)
        for d in dets:
            d.pop("burner", None)                       # le suivi ne rattache rien
    c._assign = faux.__get__(c)
    tourne(c, ecran, duree=10.0, plats=1)
    assert ecran.postes[0].plats >= 1, (ecran.events, c.logs)


def test_find_rings_ne_garde_que_les_anneaux():
    im = Image.new("RGB", (640, 600), HERBE)
    d = ImageDraw.Draw(im)
    d.ellipse((100 - 48, 120 - 48, 100 + 48, 120 + 48), outline=VERT, width=7)      # anneau 1
    d.ellipse((420 - 48, 400 - 48, 420 + 48, 400 + 48), outline=VERT, width=7)      # anneau 2
    d.rectangle((250, 60, 340, 150), fill=VERT)                                     # pavé plein : pas un anneau
    d.rectangle((20, 500, 320, 520), fill=VERT)                                     # bande : pas un anneau
    d.ellipse((560, 40, 580, 60), outline=VERT, width=3)                            # trop petit
    rings = cook.find_rings(cook.green_mask(im), 60)
    assert sorted((round(x, -1), round(y, -1)) for x, y, n in rings) == [(100, 120), (420, 400)], rings


def test_anneau_clique_meme_si_le_suivi_est_perdu(jeu, souris_rapide):
    """Retour en jeu : « il ne clique pas sur les spatules ». Pendant l'anneau l'icône n'est pas reconnue, et
    l'anneau n'était cherché qu'autour de la position SUIVIE : suivi faux = anneau jamais vu. Il est maintenant
    cherché dans toute la zone, et cliqué même sans cuisinière à qui le rattacher."""
    ecran, c = jeu(phases=("anneau", "anneau"))
    ecran.icone_cachee = True
    for p in ecran.postes:
        p.t = time.perf_counter() + 30                   # l'anneau reste affiché
    a, b = cook.Burner(1, (450, 200)), cook.Burner(2, (760, 420))   # positions suivies fausses (loin des bulles)
    a.launched = b.launched = time.perf_counter()
    c._burners = [a, b]
    dets = c._scan_wide()
    assert sorted(d["state"] for d in dets) == ["spatula", "spatula"]
    c._assign(dets)
    assert {x.state for x in c._burners} == {"spatula"}
    assert sorted(x.pos[0] // 10 for x in c._burners) == [33, 60]
    # aucune cuisinière libre : l'anneau n'est pas jeté, la boucle le cliquera
    c._burners = [a]
    c.cfg["cook"]["cookers"] = 1
    a.pos, a.state = (330, 300), "spatula"
    c._assign(dets)
    assert len(c._stray_rings) == 1 and abs(c._stray_rings[0][0] - 600) < 8


def test_camera_fixe_hors_de_la_fenetre_de_clic(jeu):
    """Relevé en jeu : 8 s après le dernier clic, un anneau apparu sur l'AUTRE cuisinière (150 px plus loin) était
    pris pour un glissement de la vue, et la 2e cuisinière n'était jamais créée. La caméra ne bouge que juste
    après un clic sur une bulle : hors de cette fenêtre, une bulle lointaine est une autre cuisinière."""
    ecran, c = jeu()
    c._burners = []
    c._assign([{"pos": (600, 300), "state": "cooking", "scores": {}}])
    b1 = c._burners[0]
    b1.launched = time.perf_counter()
    c._clicked_at = time.perf_counter() - 10
    c._assign([{"pos": (330, 300), "state": "spatula", "scores": {"vert": 900}}])
    assert len(c._burners) == 2 and b1.pos == (600, 300)
    assert c._burners[1].pos == (330, 300) and c._burners[1].state == "spatula"
    # cuisinières toutes connues, caméra fixe : pas d'appariement forcé d'une bulle lointaine
    c._assign([{"pos": (860, 420), "state": "cook", "scores": {}}])
    assert b1.pos == (600, 300) and c._burners[1].pos == (330, 300)


def test_cuisiniere_manquante_plutot_qu_un_glissement(jeu):
    """Une seule bulle vue au départ ; après son lancement, une bulle « cuisiner » apparaît loin : c'est la
    2e cuisinière (la 1re vient d'être lancée, elle ne peut pas montrer « cuisiner »)."""
    ecran, c = jeu()
    c._burners = []
    c._assign([{"pos": (330, 300), "state": "cook", "scores": {}}])
    b1 = c._burners[0]
    b1.launched = time.perf_counter()
    b1.state = "cooking"
    c._assign([{"pos": (600, 300), "state": "cook", "scores": {}}])
    assert len(c._burners) == 2 and c._burners[1].pos == (600, 300)
    assert b1.pos == (330, 300)


def test_cuisiner_directement_sans_cliquer_la_tuile(jeu, souris_rapide):
    """Le jeu présélectionne la dernière recette : « Cuisiner » suffit (moins de temps menu ouvert)."""
    ecran, c = jeu()
    tourne(c, ecran, duree=12.0, plats=2)
    assert c.dishes >= 2
    assert not [k for k in ecran.clics if abs(k[0] - TILE[0]) < 30 and abs(k[1] - TILE[1]) < 30], ecran.clics


def test_une_seule_bulle_visible_apres_le_glissement(jeu):
    """Après un lancement la bulle de la cuisinière servie disparaît un instant : il ne reste que celle de la
    voisine, déplacée. L'état des cuissons départage : une bulle « cuisiner » ne peut pas être la cuisson lancée."""
    ecran, c = jeu()
    c._burners = []
    c._assign([{"pos": (330, 300), "state": "cook", "scores": {}}, {"pos": (600, 300), "state": "cook", "scores": {}}])
    b1, b2 = c._burners
    b1.launched = time.perf_counter()
    b1.state = "cooking"
    c._clicked_at = time.perf_counter()              # on vient de cliquer une bulle : la vue peut glisser
    c._assign([{"pos": (850, 315), "state": "cook", "scores": {}}])           # seule la bulle 2, glissée de 250 px
    assert b2.pos == (850, 315) and b2.state == "cook"
    assert b1.pos == (580, 315), "la cuisinière pas vue suit le glissement des autres"
    c._assign([{"pos": (583, 312), "state": "cooking", "scores": {"vert": 0}},
               {"pos": (850, 315), "state": "cook", "scores": {}}])
    assert b1.pos == (583, 312) and b1.state == "cooking" and b2.pos == (850, 315)


def test_perspective_tres_differente_garde_l_ordre(jeu):
    """Deux bulles vues, deux cuisinières suivies, mais l'écart entre les bulles a trop changé pour la
    tolérance : on garde l'ordre le long de l'axe où elles s'alignent."""
    ecran, c = jeu()
    c._burners = []
    c._assign([{"pos": (330, 300), "state": "cook", "scores": {}}, {"pos": (600, 300), "state": "cook", "scores": {}}])
    b1, b2 = c._burners
    c._clicked_at = time.perf_counter()
    c._assign([{"pos": (450, 380), "state": "cook", "scores": {}}, {"pos": (860, 420), "state": "cook", "scores": {}}])
    assert b1.pos == (450, 380) and b2.pos == (860, 420)


def test_compteur_de_plats_agrege(jeu, souris_rapide):
    """Le compteur de plats additionne toutes les cuisinières (et chaque Burner garde le sien)."""
    ecran, c = jeu(phases=("cuisson", "cuisson"))
    tourne(c, ecran, duree=12.0, plats=2)
    assert c.dishes >= 2
    assert c.dishes == sum(b.dishes for b in c._burners)
    assert c.dishes == sum(p.plats for p in ecran.postes)
    assert c.fires == sum(b.fires for b in c._burners) >= 2
    assert ecran.rates == 0, ecran.events
    st = c.status()
    assert st["cookers"] == 2 and st["tracked"] == 2
    assert [b["i"] for b in st["burners"]] == [1, 2]
    assert st["settings"]["cookers"] == 2


def test_max_dishes_arrete_la_boucle(jeu, souris_rapide):
    ecran, c = jeu(phases=("cuisson", "cuisson"), max_dishes=2)
    tourne(c, ecran, duree=12.0, plats=2)
    assert c.dishes == 2
    assert "objectif atteint" in c.message


def test_journal_par_cuisiniere(jeu):
    """Les changements d'état sont journalisés bulle par bulle (« bulle 2 : ... »)."""
    ecran, c = jeu(phases=("repos", "cuisson"))
    c._scan(wide=True)
    ecran.postes[1].passe("pret")
    c._scan(wide=True)
    assert any(l.startswith("bulle 1 : cook") for l in c.logs), c.logs
    assert any(l.startswith("bulle 2 : ready") for l in c.logs), c.logs


# ---------------------------------------------------------------- garde de lancement (anneau non chronométré)
def test_may_launch_prudent_par_defaut(jeu):
    """Avec une garde réglée, on ne lance pas de cuisson tant qu'une autre cuisinière peut demander un
    ajustement (le défaut est 0 depuis les relevés en jeu : voir DEFAULT_COOK)."""
    ecran, c = jeu(phases=("cuisson", "repos"), launch_guard=8.5)
    c._scan(wide=True)
    a, b = c._burners
    assert a.state == "cooking" and b.state == "cook"
    assert not c._may_launch(b, c._burners)          # A vient d'être repérée en cuisson : fenêtre de risque
    a.launched = time.perf_counter() - 99            # la fenêtre est passée
    assert c._may_launch(b, c._burners)
    a.launched = time.perf_counter()
    assert not c._may_launch(b, c._burners)
    c.cfg["cook"]["launch_anytime"] = True           # le réglage qui autorise quand même
    assert c._may_launch(b, c._burners)
    c.cfg["cook"]["launch_anytime"] = False
    c.cfg["cook"]["launch_guard"] = 0
    assert c._may_launch(b, c._burners)


def test_l_ancienne_garde_de_8_s_est_migree():
    cfg = {"cook": {"launch_guard": 8.0}}
    assert cook.ensure_defaults(cfg)["launch_guard"] == 0.0
    cfg = {"cook": {"launch_guard": 5.0}}
    assert cook.ensure_defaults(cfg)["launch_guard"] == 5.0, "un réglage choisi est conservé"
    assert cook.ensure_defaults({})["launch_guard"] == 0.0


def test_une_seule_cuisiniere_ne_bloque_jamais(jeu):
    ecran, c = jeu(phases=("cuisson",), cookers=1, launch_guard=8.5)
    c._scan(wide=True)
    assert len(c._burners) == 1
    assert c._may_launch(c._burners[0], c._burners)


# ---------------------------------------------------------------- une seule cuisinière : rien ne change
def test_cookers_1_garde_le_chemin_historique(jeu, souris_rapide, monkeypatch):
    """cookers = 1 : la boucle séquentielle historique (_loop_single / _find / _launch / _watch) est prise,
    l'ordonnanceur multi n'est jamais utilisé."""
    ecran, c = jeu(phases=("repos",), cookers=1)
    appels = []
    for nom in ("_loop_single", "_loop_multi"):
        vrai = getattr(cook.Cooker, nom)
        monkeypatch.setattr(cook.Cooker, nom, (lambda n, f: lambda self: (appels.append(n), f(self))[1])(nom, vrai))
    tourne(c, ecran, duree=12.0, plats=1)
    assert appels == ["_loop_single"]
    assert c._burners == []              # aucune machine à états multi
    assert c._pos is not None            # suivi de la bulle unique, comme avant
    assert c.dishes >= 1 and c.dishes == ecran.postes[0].plats
    assert ecran.rates == 0
    assert any(l.startswith("plat ") and "récupéré" in l for l in c.logs), c.logs


def test_cookers_1_detection_identique(jeu):
    """Avec une seule bulle, _find (historique) et _scan_wide (multi) voient la même chose."""
    ecran, c = jeu(phases=("anneau",), cookers=1)
    st, pos, sc = c._find(wide=True)
    dets = c._scan_wide()
    assert st == "spatula" and len(dets) == 1
    assert dets[0]["state"] == "spatula"
    assert abs(dets[0]["pos"][0] - pos[0]) <= 2 and abs(dets[0]["pos"][1] - pos[1]) <= 2


# ---------------------------------------------------------------- réglage
def test_ensure_defaults_borne_cookers():
    for brut, attendu in ((None, 1), (0, 1), (1, 1), (3, 3), (9, 4), (-2, 1), ("2", 2), ("abc", 1)):
        cfg = {"cook": {"cookers": brut}}
        assert cook.ensure_defaults(cfg)["cookers"] == attendu, brut
    assert cook.ensure_defaults({})["cookers"] == 1


def test_apply_cookers(jeu):
    ecran, c = jeu(phases=("repos",), cookers=1)
    assert c.cookers == 1
    c.cfg["cook"]["cookers"] = 3
    n, stopped = c.apply_cookers()
    assert (n, stopped) == (3, False)
    assert c.cookers == 3
    assert c.status()["cookers"] == 3


def test_test_detection_multi(jeu):
    """« Tester la détection » avec plusieurs cuisinières : une ligne par bulle trouvée."""
    ecran, c = jeu(phases=("repos", "pret"))
    msg = c.test()
    assert msg.startswith("2 bulle(s) :")
    assert "cuisiner" in msg and "récupérer" in msg
    assert "menu fermé" in msg
    ecran.postes = ecran.postes[:1]
    msg = c.test()
    assert "aucune autre bulle" in msg


# ---------------------------------------------------------------- retours en jeu (2026-09-16)
def test_menu_ouvert_par_erreur_est_utilise(jeu, souris_rapide):
    """Bug vu en jeu : la bulle « gants » reste affichée après la récupération, un second clic tombe sur la
    bulle « cuisiner » et ouvre le menu Recettes, qu'un clic dans l'herbe ne ferme pas. La boucle cliquait
    l'herbe en silence pour toujours (plus de lancement, plus de spatule). Elle doit récupérer une seule fois
    et continuer à cuisiner sur les deux cuisinières."""
    ecran, c = jeu(phases=("pret", "repos"), launch_guard=0.0)
    ecran.menu_colle = True
    ecran.gants_restent = 0.4
    tourne(c, ecran, duree=12.0, plats=4)
    assert c.dishes >= 4, (ecran.events, c.logs)
    assert c.dishes == sum(p.plats for p in ecran.postes), ecran.events
    assert {i for e, i in ecran.events if e == "lance"} == {1, 2}, ecran.events
    assert ecran.rates == 0, ecran.events


def test_menu_colle_arrete_avec_un_message(jeu, souris_rapide, monkeypatch):
    """Menu qui ne se ferme jamais (plus d'ingrédients) : arrêt explicite après 3 essais, pas une boucle muette."""
    ecran, c = jeu(phases=("repos", "repos"))
    ecran.menu = True
    monkeypatch.setattr(ecran, "clic", lambda x, y: ecran.clics.append((x, y)))   # rien ne ferme le menu
    monkeypatch.setattr(c, "_wait_menu", lambda want, timeout: c._menu_open() == want)
    assert c.start(delay=0.0)
    c._thread.join(timeout=10)
    assert not c._thread.is_alive()
    assert "plus d'ingrédients" in c.message, c.message
    assert sum("menu Recettes ouvert" in l for l in c.logs) == 3, c.logs


def test_anneau_sans_icone_reconnue(jeu, souris_rapide):
    """L'anneau vert autour d'une bulle suivie suffit pour cliquer, même si l'icône n'est pas reconnue."""
    ecran, c = jeu(phases=("cuisson", "cuisson"), launch_guard=0.0)
    ecran.icone_cachee = True
    tourne(c, ecran, duree=12.0, plats=2)
    assert ecran.rates == 0, ecran.events
    assert {i for e, i in ecran.events if e == "anneau"} == {1, 2}, ecran.events
