"""bot.MouseBot : une frappe isolée n'arrête pas l'action, deux frappes rapprochées ou Échap l'arrêtent."""
import types

import bot


class _Bot(bot.MouseBot):
    ACTIVE_STATES = ("cooking",)

    def __init__(self):
        self.cfg = {"hotkeys": {"cook": "f8"}}
        self.state = "cooking"
        self.logs, self.stops, self.logfile, self._t0 = [], [], None, 0.0
        self._ui_log = self.logs.append

    def stop(self, reason=""):
        self.stops.append(reason)


def _key(name, kind="down"):
    return types.SimpleNamespace(name=name, event_type=kind, scan_code=34)


def test_une_frappe_isolee_est_ignoree(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(bot.time, "perf_counter", lambda: now[0])
    b = _Bot()
    b.on_key_event(_key("g"))
    assert b.stops == [] and "ignorée" in b.logs[-1]
    now[0] += 5.0                                   # une autre frappe isolée, bien plus tard
    b.on_key_event(_key("g"))
    assert b.stops == []
    now[0] += 0.4                                   # deux frappes rapprochées : quelqu'un tape
    b.on_key_event(_key("h"))
    assert b.stops == ["clavier touché"]


def test_echap_arrete_tout_de_suite_et_les_raccourcis_sont_ignores(monkeypatch):
    monkeypatch.setattr(bot.time, "perf_counter", lambda: 50.0)
    b = _Bot()
    b.on_key_event(_key("f8"))
    b.on_key_event(_key("g", "up"))
    assert b.stops == [] and b.logs == []
    b.on_key_event(_key("esc"))
    assert b.stops == ["clavier touché"]
    b.state = "idle"
    b.on_key_event(_key("esc"))
    assert len(b.stops) == 1
