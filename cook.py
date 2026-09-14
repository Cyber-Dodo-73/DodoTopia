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
import time

from bot import MouseBot
from draw import sample_color, _cdist
from platform_io import cursor_pos, grab, mouse_up, SCREEN_OK

REF = 72            # cote (px) du masque de reference d'une icone
GRAB = 110          # zone lue autour de la souris au calibrage
LOCAL = 16          # suivi local : rayon (px) autour de la derniere position
COARSE = 8          # recherche large : pas (px) de la grille
RING = 56           # rayon (px) de la zone ou l'on compte le vert de l'anneau
WHITE = 200         # seuil pixel blanc (sur les 3 canaux)

DEFAULT_COOK = {
    "points": {},            # search [x1,y1,x2,y2] ; cook, tile, cook_btn, ready, neutral, spatula : [x, y]
    "cook_btn_color": None,  # couleur du bouton Cuisiner quand le menu est ouvert
    "ring_color": None,      # couleur de l'anneau vert lue au calibrage (etape spatule)
    "refs": {},              # cook / spatula / ready : {"png": masque 1 bit en base64}
    "max_dishes": 0,         # 0 = sans fin
    "cook_timeout": 240.0,   # secondes max pour qu'un plat soit pret
    "poll": 0.1,             # secondes entre deux lectures de l'ecran
    "match": 0.62,           # score minimal (Jaccard) pour reconnaitre une icone
    "green_px": 60,          # pixels verts minimum pour l'anneau de la spatule
    "click_delay": 0.3,      # secondes apres un clic
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
    if c.get("match") == 0.55:
        c["match"] = DEFAULT_COOK["match"]     # ancien defaut, trop proche des scores entre icones (0.53)
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


# ---------------------------------------------------------------- module
class Cooker(MouseBot):
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
        ensure_defaults(cfg)

    @property
    def cook_cfg(self):
        return ensure_defaults(self.cfg)

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
        self.state = "cooking"
        self.last_stop_reason = ""
        self.message = ""
        self.dishes = 0
        self.fires = 0
        self.actions_done = 0
        self.phase = ""
        self._pos = None
        self._last_state = None
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
        c = self.cook_cfg
        p = c["points"]
        max_dishes = int(c.get("max_dishes", 0) or 0)
        self._check_mouse(*p["neutral"])
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
        green = 0
        if pos is not None:
            gx, gy = pos[0] - ox, pos[1] - oy
            if gx - RING < 0 or gy - RING < 0 or gx + RING > im.size[0] or gy + RING > im.size[1]:
                ring = grab((pos[0] - RING, pos[1] - RING, pos[0] + RING, pos[1] + RING))
            else:
                ring = im.crop((gx - RING, gy - RING, gx + RING, gy + RING))
            if ring is not None:
                green = count(green_mask(ring, c.get("ring_color")))
            if green >= int(c.get("green_px", 60)):
                state = "spatula"
        scores["vert"] = green
        if state != self._last_state:
            self._last_state = state
            self.log(f"bulle : {state} {scores} à {pos}")
        return state, pos, scores

    def test(self):
        """Lecture immediate de l'ecran (bouton « Tester la détection ») : phrase pour l'interface."""
        if self.state != "idle":
            return "Occupé (cuisine ou calibrage en cours)."
        if not self.calibrated():
            return "La cuisine n'est pas calibrée."
        try:
            self._last_state = None
            st, pos, sc = self._find(wide=True)
        except Exception as e:  # noqa
            self.test_result = f"Échec : {e}"
            return self.test_result
        names = {"cook": "bulle « cuisiner »", "ready": "bulle « récupérer »", "spatula": "spatule avec anneau vert",
                 "cooking": "spatule sans anneau", "none": "aucune bulle reconnue"}
        detail = ", ".join(f"{k} {v}" for k, v in sc.items())
        menu = "menu Recettes ouvert" if self._menu_open() else "menu fermé"
        self.test_result = f"{names.get(st, st)}" + (f" en {pos[0]},{pos[1]}" if pos and st != "none" else "") + f" ({detail}) ; {menu}."
        self.log("test : " + self.test_result)
        return self.test_result

    # ---- etat pour l'interface
    def status(self):
        c = self.cook_cfg
        elapsed = (time.perf_counter() - self.started_at) if self.started_at else 0.0
        return {
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
            "settings": {"max_dishes": int(c.get("max_dishes", 0) or 0), "cook_timeout": float(c.get("cook_timeout", 240.0)),
                         "match": float(c.get("match", 0.55)), "click_delay": float(c.get("click_delay", 0.3)),
                         "green_px": int(c.get("green_px", 60))},
            "screen_ok": SCREEN_OK,
        }
