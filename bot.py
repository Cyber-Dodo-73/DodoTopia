# -*- coding: utf-8 -*-
"""Base commune des modules qui pilotent la souris dans le jeu (dessin, cuisine) : journal, attente
interruptible, deplacement « comme une main », clic, detection d'une souris ou d'un clavier touches."""
import random
import time

from platform_io import cursor_pos, mouse_move, mouse_down, mouse_up, mouse_hint


class MouseBot:
    """Champs attendus (initialises par la classe fille) : cfg, _ui_log, logfile, _t0, _stop (threading.Event),
    _expected_pos, actions_done, state, et une methode stop(reason). ACTIVE_STATES : etats pendant lesquels
    une frappe clavier arrete le module."""

    ACTIVE_STATES = ()

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
        """Hook clavier global : toute frappe pendant l'action l'arrete (sauf raccourcis de l'appli)."""
        if self.state not in self.ACTIVE_STATES or event.event_type != "down":
            return
        name = (event.name or "").lower()
        if name in self._hotkey_names():
            return
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

    def _click(self, x, y, delay=None):
        if self._user_moved():
            self.stop("souris bougée")
            return False
        if not self._move(x, y):
            return False
        # temps de pose, d'appui et d'attente irreguliers (jamais plus courts qu'avant)
        if not self._sleep(random.uniform(0.012, 0.045)):
            return False
        mouse_down()
        if not self._sleep(random.uniform(0.02, 0.06)):
            mouse_up()
            return False
        mouse_up()
        self.actions_done += 1
        wait = self._mouse_cfg()["click_delay"] if delay is None else delay
        return self._sleep(wait * random.uniform(1.0, 1.5))
