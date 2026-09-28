# -*- coding: utf-8 -*-
"""Overlay : petite fenetre au-dessus de Heartopia qui montre ou en est la musique (solo, a plusieurs, salon)
ou le dessin. Elle ne s'affiche que si le jeu est au premier plan ET qu'une musique ou un dessin tourne ; elle
ne prend jamais le focus, les clics la traversent et les captures d'ecran ne la voient pas (platform_io)."""
import json
import os
import threading
import time

import i18n
import platform_io

OVERLAY_W, OVERLAY_H, OVERLAY_MARGIN = 340, 104, 16      # en pixels a 100 % (multiplies par l'echelle)
OVERLAY_TICK = 0.25
CORNERS = ("top-right", "top-left", "top-center", "bottom-left", "bottom-right")
DEFAULT_OVERLAY = {"enabled": True, "corner": "top-right"}
# cles choisies par une condition (expression ternaire) : declarees pour .tools/i18n_check.py
I18N_KEYS = ["overlay.role.music", "overlay.role.paused", "overlay.hint.room_host", "overlay.hint.room_guest"]


def overlay_cfg(cfg):
    o = cfg.setdefault("overlay", {})
    for k, v in DEFAULT_OVERLAY.items():
        o.setdefault(k, v)
    if o.get("corner") not in CORNERS:
        o["corner"] = DEFAULT_OVERLAY["corner"]
    return o


def overlay_rect(game_rect, scale, corner):
    """Position de l'overlay (x, y, w, h) dans le coin choisi de la fenetre du jeu, en pixels physiques."""
    x1, y1, x2, y2 = game_rect
    w, h, m = int(OVERLAY_W * scale), int(OVERLAY_H * scale), int(OVERLAY_MARGIN * scale)
    if corner == "top-left":
        return x1 + m, y1 + m, w, h
    if corner == "top-center":
        return (x1 + x2 - w) // 2, y1 + m, w, h
    if corner == "bottom-left":
        return x1 + m, y2 - h - m, w, h
    if corner == "bottom-right":
        return x2 - w - m, y2 - h - m, w, h
    return x2 - w - m, y1 + m, w, h


def _song_name(path):
    return os.path.splitext(os.path.basename(path or ""))[0]


class OverlayMixin:
    # ---------------------------------------------------------- contenu
    def _overlay_content(self):
        """Ce que l'overlay affiche, ou None si ni musique ni dessin ne tourne. Tout est deja traduit :
        {kind, role, title, count, progress: {pct, left, right} | None, meta}."""
        hk = self._cfg.get("hotkeys") or {}
        play, stop = hk.get("play_pause") or "F6", hk.get("stop") or "F7"
        now = time.perf_counter()
        d = self._drawer
        if d.state == "drawing":
            if d.countdown > 0:
                return {"kind": "draw", "role": i18n.t("overlay.role.draw"), "title": i18n.t("overlay.draw.starting"),
                        "count": i18n.t("overlay.seconds", n=int(d.countdown + 0.99)), "progress": None,
                        "meta": i18n.t("overlay.hint.draw", stop=stop)}
            pct = d.done / d.total * 100 if d.total else 0.0
            st = d.status()
            right = _dur(st.get("eta")) if st.get("eta") is not None else _dur(st.get("elapsed"))
            return {"kind": "draw", "role": i18n.t("overlay.role.draw"),
                    "title": d.progress_msg or i18n.t("overlay.draw.cells", done=d.done, total=d.total),
                    "count": f"{pct:.0f} %",
                    "progress": {"pct": pct, "left": i18n.t("overlay.draw.cells", done=d.done, total=d.total),
                                 "right": right},
                    "meta": i18n.t("overlay.hint.draw", stop=stop)}
        if d.state == "autocal":
            return {"kind": "draw", "role": i18n.t("overlay.role.measure"), "title": d.progress_msg or "",
                    "count": "", "progress": None, "meta": i18n.t("overlay.hint.draw", stop=stop)}

        p, rs = self._player, self._room
        if rs.active():
            song = (rs.song or {}).get("name") or ""
            dur = float((rs.song or {}).get("duration_ms") or 0) / 1000.0
            host = rs.is_host()
            if rs.state == "armed" and rs.deadline is not None:
                return {"kind": "room", "role": i18n.t("overlay.role.room", code=rs.code or ""), "title": song,
                        "count": i18n.t("overlay.seconds", n=max(0, int(rs.deadline - now + 0.99))),
                        "progress": None, "meta": i18n.t("overlay.hint.room_start")}
            if rs.state == "playing" and p.state in ("playing", "paused"):
                pos = min(p.position(), dur) if dur else p.position()
                return {"kind": "room", "role": i18n.t("overlay.role.room", code=rs.code or ""), "title": song,
                        "count": i18n.t("overlay.players", n=len(rs.players)),
                        "progress": {"pct": pos / dur * 100 if dur else 0, "left": _dur(pos), "right": _dur(dur)},
                        "meta": i18n.t("overlay.hint.room_host" if host else "overlay.hint.room_guest", stop=stop)}
            pos = rs.rejoin_position()
            if pos is not None:
                return {"kind": "room", "role": i18n.t("overlay.role.room_without_you"), "title": song, "count": "",
                        "progress": {"pct": pos / dur * 100 if dur else 0, "left": _dur(pos), "right": _dur(dur)},
                        "meta": i18n.t("overlay.hint.rejoin", play=play)}
            return None
        sy = self._sync
        if sy.active() and p.state not in ("playing", "paused"):
            s = sy.status()
            left = s.get("seconds_left")
            return {"kind": "music", "role": i18n.t("overlay.role.sync"), "title": s.get("message") or "",
                    "count": i18n.t("overlay.seconds", n=int(left + 0.99)) if left is not None else "",
                    "progress": None, "meta": i18n.t("overlay.hint.sync", stop=stop)}
        if p.target == "game" and p.state in ("playing", "paused"):
            dur = float(p.duration or 0.0)
            pos = p.position()
            start = p._start_time
            count = ""
            if p.state == "playing" and start is not None and start > now:
                count = i18n.t("overlay.seconds", n=int(start - now + 0.99))
            return {"kind": "music",
                    "role": i18n.t("overlay.role.paused" if p.state == "paused" else "overlay.role.music"),
                    "title": _song_name(p.current()), "count": count,
                    "progress": {"pct": pos / dur * 100 if dur else 0, "left": _dur(pos), "right": _dur(dur)},
                    "meta": i18n.t("overlay.hint.music", play=play, stop=stop)}
        return None

    # ---------------------------------------------------------- fenetre
    def _overlay_attach(self, window):
        """Appele par app.py avec la fenetre overlay (creee cachee) : styles, puis boucle d'affichage."""
        self._ov_window = window
        self._ov_hwnd = None
        self._ov_shown = False
        self._ov_last = None
        self._ov_place = None
        self._ov_placed_at = 0.0
        self._ov_stop = threading.Event()

        def on_loaded():
            hwnd = platform_io.window_handle(window)
            if hwnd and platform_io.overlay_prepare(hwnd):
                self._ov_hwnd = hwnd
                platform_io.overlay_hide(hwnd)
                threading.Thread(target=self._overlay_loop, name="overlay", daemon=True).start()
            else:
                self._log("overlay indisponible sur ce système")
        window.events.loaded += on_loaded

    def _overlay_close(self):
        ev = getattr(self, "_ov_stop", None)
        if ev is not None:
            ev.set()

    def _overlay_visible_content(self):
        """Contenu a afficher maintenant, ou None : overlay active, musique ou dessin en cours, jeu devant."""
        if not overlay_cfg(self._cfg).get("enabled", True):
            return None
        content = self._overlay_content()
        if content is None:
            return None
        if platform_io.game_in_front(self._cfg.get("game_process")) is not True:
            return None
        return content

    def _overlay_loop(self):
        while not self._ov_stop.wait(OVERLAY_TICK):
            try:
                self._overlay_tick()
            except Exception as e:  # noqa - l'overlay est un confort : jamais d'arret du reste
                self._log(f"overlay : {e}")
                self._ov_stop.wait(2.0)

    def _overlay_tick(self):
        hwnd = self._ov_hwnd
        content = self._overlay_visible_content()
        if content is None:
            if self._ov_shown:
                platform_io.overlay_hide(hwnd)
                self._ov_shown = False
            return
        payload = json.dumps(content, ensure_ascii=False)
        if payload != self._ov_last:
            self._ov_last = payload
            self._ov_window.run_js(f"window.render && render({payload})")
        fr = platform_io.foreground_rect()
        if not fr:
            return
        place = overlay_rect(fr[0], fr[1], overlay_cfg(self._cfg).get("corner"))
        now = time.perf_counter()
        # replace si la fenetre du jeu bouge, et de temps en temps pour rester au-dessus (jeu en plein ecran)
        if not self._ov_shown or place != self._ov_place or now - self._ov_placed_at > 1.0:
            if not self._ov_shown:
                self._ov_window.run_js("window.appear && appear()")     # animation d'apparition
            platform_io.overlay_show(hwnd, *place)
            self._ov_place, self._ov_placed_at, self._ov_shown = place, now, True


def _dur(s):
    s = max(0, int(s or 0))
    return f"{s // 60}:{s % 60:02d}"
