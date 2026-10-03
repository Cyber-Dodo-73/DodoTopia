# -*- coding: utf-8 -*-
"""Base commune des modules qui pilotent la souris dans le jeu (dessin, cuisine) : journal, attente
interruptible, deplacement « comme une main », clic, detection d'une souris ou d'un clavier touches."""
import random
import time

from platform_io import cursor_pos, mouse_move, mouse_down, mouse_up, mouse_hint, game_in_front, virtual_screen


def screen_fingerprint():
    """[x, y, largeur, hauteur] du bureau virtuel : un calibrage en pixels absolus n'est valable que pour cet
    agencement d'ecrans (resolution, mise a l'echelle, ecran ajoute ou retire). None si indisponible."""
    try:
        return [int(v) for v in virtual_screen()]
    except Exception:  # noqa
        return None


def screen_changed(saved):
    """Vrai si une empreinte enregistree existe et differe de l'ecran actuel (calibrage perime)."""
    if not saved:
        return False
    cur = screen_fingerprint()
    return cur is not None and list(saved) != cur


class MouseBot:
    """Champs attendus (initialises par la classe fille) : cfg, _ui_log, logfile, _t0, _stop (threading.Event),
    _expected_pos, actions_done, state, et une methode stop(reason). ACTIVE_STATES : etats pendant lesquels
    une frappe clavier arrete le module."""

    ACTIVE_STATES = ()
    KEY_CONFIRM = 2.0          # secondes : deux frappes dans ce delai arretent, une frappe isolee est ignoree

    def _mouse_cfg(self):
        """Dictionnaire de reglages avec mouse_glide, glide_speed, click_delay."""
        return {}

    def log(self, msg):
        """Journal : interface + fichier (horodate depuis le debut de l'action)."""
        self._ui_log(msg)
        if self.logfile:
            try:
                with open(self.logfile, "a", encoding="utf-8") as f:
                    f.write(f"[{time.perf_counter() - self._t0:7.2f}s] {msg}\n")
            except Exception:
                pass

    def on_key_event(self, event):
        """Hook clavier global : le clavier arrete l'action (sauf raccourcis de l'appli). Échap arrete tout de
        suite ; une autre touche n'arrete que si une deuxieme frappe suit dans les KEY_CONFIRM secondes (une touche
        maintenue se repete, donc arrete aussi). Releve en jeu (2026-10-04) : une frappe isolee (« g ») arrivait
        sans que personne ne touche le clavier et coupait la cuisine ; une frappe seule est donc ignoree."""
        if self.state not in self.ACTIVE_STATES or event.event_type != "down":
            return
        name = (event.name or "").lower()
        if name in self._hotkey_names():
            return
        # quelle touche : une frappe sans que personne ne tape vient d'un autre programme
        now = time.perf_counter()
        last, self._key_at = getattr(self, "_key_at", 0.0), now
        if name not in ("esc", "escape", "échap") and not (last and now - last <= self.KEY_CONFIRM):
            self.log(f"touche reçue : « {event.name} » (code {getattr(event, 'scan_code', '?')}) — frappe isolée, ignorée "
                     f"(Échap, ou deux frappes en {self.KEY_CONFIRM:.0f} s, arrêtent)")
            return
        self.log(f"touche reçue : « {event.name} » (code {getattr(event, 'scan_code', '?')})")
        self.stop("clavier touché")

    def _hotkey_names(self):
        names = set()
        for combo in self.cfg.get("hotkeys", {}).values():
            for part in str(combo).lower().replace(" ", "").split("+"):
                if part:
                    names.add(part)
        return names

    def _sleep(self, s):
        end = time.perf_counter() + s
        while True:
            if self._stop.is_set():
                return False
            rem = end - time.perf_counter()
            if rem <= 0:
                return True
            time.sleep(min(rem, 0.01))

    def _user_moved(self):
        if self._expected_pos is None:
            return False
        x, y = cursor_pos()
        ex, ey = self._expected_pos
        return abs(x - ex) > 20 or abs(y - ey) > 20

    def _check_mouse(self, x, y):
        """Deplace la souris et verifie qu'elle est bien arrivee (sinon le jeu bloque SendInput)."""
        self._expected_pos = None
        self._move(x, y)
        time.sleep(0.06)
        cx, cy = cursor_pos()
        if abs(cx - x) > 6 or abs(cy - y) > 6:
            hint = mouse_hint()
            raise RuntimeError(f"la souris ne se déplace pas dans le jeu (attendu {x},{y}, obtenu {cx},{cy})." + hint)
        self._expected_pos = (cx, cy)

    def _glide(self, x, y):
        """Deplace la souris jusqu'a (x, y) comme une main : positions intermediaires rapprochees, en accelerant
        puis en freinant (au lieu d'un saut instantane). False si l'action est arretee pendant le mouvement."""
        x0, y0 = self._expected_pos if self._expected_pos is not None else cursor_pos()
        dist = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
        if dist < 4:
            mouse_move(x, y)
            self._expected_pos = (x, y)
            return True
        # ~0.1 s pour 100 px, ~0.3 s pour 500 px, 0.45 s au plus, puis un alea de -25 % a +35 % ;
        # une position toutes les ~8 ms (cadence elle aussi irreguliere)
        dur = min(0.45, 0.07 + dist / 1800) * float(self._mouse_cfg().get("glide_speed", 1.0) or 1.0)
        dur *= random.uniform(0.75, 1.35)
        n = max(3, int(dur / 0.008))
        # trajectoire pas tout a fait droite : une courbe (bosse perpendiculaire, cote et amplitude au hasard)
        # plus un tremblement de quelques pixels, tous deux nuls a l'arrivee
        nx, ny = -(y - y0) / dist, (x - x0) / dist
        bow = random.uniform(-1, 1) * min(40.0, dist * random.uniform(0.03, 0.12))
        bow_peak = random.uniform(0.3, 0.7)
        jit = random.uniform(0.5, 2.5)
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)          # accelere puis freine
            # bosse asymetrique (max en bow_peak), fondue a zero aux deux bouts
            u = t / bow_peak if t < bow_peak else (1 - t) / (1 - bow_peak)
            off = bow * u * u * (3 - 2 * u)
            fade = 1 - t
            px = x0 + (x - x0) * e + nx * off + random.uniform(-jit, jit) * fade
            py = y0 + (y - y0) * e + ny * off + random.uniform(-jit, jit) * fade
            if i == n:
                px, py = x, y
            px, py = int(round(px)), int(round(py))
            mouse_move(px, py)
            self._expected_pos = (px, py)
            if i < n and not self._sleep(dur / n * random.uniform(0.6, 1.4)):
                return False
        if self._expected_pos != (x, y):
            mouse_move(x, y)
            self._expected_pos = (x, y)
        return True

    def _move(self, x, y, glide=True):
        """Deplacement bouton relache : en glissant (reglage « souris comme une main ») ou d'un saut."""
        if glide and self._mouse_cfg().get("mouse_glide", True):
            return self._glide(x, y)
        mouse_move(x, y)
        self._expected_pos = (x, y)
        return True

    def _game_in_front(self):
        """True / False / None : voir platform_io.game_in_front (None = aucune verification)."""
        return game_in_front(self.cfg.get("game_process"))

    def _check_game_front(self):
        """Au plus toutes les 0,25 s : si le jeu a quitte le premier plan, on arrete avant le prochain clic
        (les clics partiraient dans une autre application)."""
        now = time.perf_counter()
        if now - getattr(self, "_front_check", 0.0) < 0.25:
            return True
        self._front_check = now
        if self._game_in_front() is False:
            self.log("le jeu n'est pas au premier plan : arrêt")
            self.stop("jeu pas au premier plan")
            return False
        return True

    SETTLE = (0.012, 0.045)      # secondes entre l'arrivee de la souris et l'appui
    HOLD = (0.02, 0.06)          # duree de l'appui

    def _click(self, x, y, delay=None):
        if self._user_moved():
            self.stop("souris bougée")
            return False
        if not self._check_game_front():
            return False
        if not self._move(x, y):
            return False
        # temps de pose, d'appui et d'attente irreguliers (jamais plus courts qu'avant)
        if not self._sleep(random.uniform(*self.SETTLE)):
            return False
        mouse_down()
        if not self._sleep(random.uniform(*self.HOLD)):
            mouse_up()
            return False
        mouse_up()
        self.actions_done += 1
        wait = self._mouse_cfg()["click_delay"] if delay is None else delay
        return self._sleep(wait * random.uniform(1.0, 1.5))
