# -*- coding: utf-8 -*-
"""Assistant de configuration (dessin et cuisine) : navigation en arrière et protection du calibrage existant.

Ces tests ne touchent ni l'écran ni la souris : ils ne manipulent que la machine à états des assistants
(`start_calibration`, `back_point`, `goto_step`, `cancel_calibration`). Les points « capturés » sont écrits
à la main, comme le ferait `capture_point` après une lecture d'écran.
"""
import cook
import draw


def _cfg():
    return {"hotkeys": {"play_pause": "F6", "stop": "F7", "draw_point": "F3"}}


def _cooker():
    c = cook.Cooker(_cfg(), log=lambda m: None, on_change=lambda: None, save=lambda: None,
                    logfile=None, data_dir=None)
    return c


def _drawer():
    return draw.Drawer(_cfg(), log=lambda m: None, on_change=lambda: None, save=lambda: None, logfile=None)


def _avance(module, n):
    """Simule n captures réussies (sans écran) : une position par étape, et l'étape suivante."""
    for _ in range(n):
        key = module.steps[module.step][0] if hasattr(module, "steps") else draw.STEPS[module.step][0]
        module.points[key] = [10 * module.step, 20 * module.step]
        module.step += 1


# --- cuisine -------------------------------------------------------------------------

def test_cook_back_point_oublie_l_etape_et_recule():
    c = _cooker()
    c.start_calibration()
    _avance(c, 3)
    assert c.step == 3 and len(c.points) == 3
    assert c.back_point() is True
    assert c.step == 2
    assert c.steps[2][0] not in c.points          # la position de l'étape reprise est oubliée
    assert len(c.points) == 2


def test_cook_back_point_refuse_a_la_premiere_etape():
    c = _cooker()
    c.start_calibration()
    assert c.step == 0
    assert c.back_point() is False
    assert c.step == 0


def test_cook_goto_step_revient_mais_ne_saute_jamais_en_avant():
    c = _cooker()
    c.start_calibration()
    _avance(c, 5)
    assert c.goto_step(1) is True
    assert c.step == 1 and len(c.points) == 1
    assert c.goto_step(4) is False                # en avant : refusé
    assert c.goto_step("oui") is False            # valeur invalide : refusé, pas d'exception
    assert c.step == 1


def test_cook_annuler_conserve_la_configuration_precedente():
    c = _cooker()
    c.cook_cfg["points"] = {"tile": [1, 2], "cook_btn": [3, 4], "neutral": [5, 6]}
    c.start_calibration()
    _avance(c, 2)
    c.cancel_calibration()
    assert c.state == "idle"
    assert c.cook_cfg["points"] == {"tile": [1, 2], "cook_btn": [3, 4], "neutral": [5, 6]}


# --- dessin --------------------------------------------------------------------------

def test_draw_back_point_oublie_l_etape_et_recule():
    d = _drawer()
    d.start_calibration("16:9")
    _avance(d, 2)
    assert d.step == 2
    assert d.back_point() is True
    assert d.step == 1
    assert draw.STEPS[1][0] not in d.points


def test_draw_back_point_oublie_les_couleurs_lues_a_l_etape_pal1():
    """L'étape « dernière couleur » lit la palette à l'écran : revenir dessus doit aussi jeter la lecture."""
    d = _drawer()
    d.start_calibration("16:9")
    _avance(d, 4)                                  # tl, br, pal0, pal1
    d.points["_colors"] = [[1, 2, 3]]
    assert d.goto_step(3) is True                  # on revient sur pal1
    assert "_colors" not in d.points
    assert d.step == 3


def test_draw_annuler_conserve_le_calibrage_precedent():
    d = _drawer()
    d.draw_cfg["formats"].setdefault("16:9", {})["rect"] = [10, 20, 500, 400]
    d.start_calibration("16:9")
    _avance(d, 2)
    d.cancel_calibration()
    assert d.state == "idle"
    assert d.draw_cfg["formats"]["16:9"]["rect"] == [10, 20, 500, 400]


def test_navigation_arriere_ignoree_hors_assistant():
    d, c = _drawer(), _cooker()
    assert d.state == "idle" and c.state == "idle"
    assert d.back_point() is False and d.goto_step(0) is False
    assert c.back_point() is False and c.goto_step(0) is False


def test_ecran_change_refuse_le_lancement(monkeypatch):
    """Un calibrage fait sur un autre agencement d'écrans n'est plus valable : dessin et cuisine refusent."""
    import bot
    monkeypatch.setattr(bot, "virtual_screen", lambda: (0, 0, 1920, 1080))
    assert bot.screen_changed(None) is False
    assert bot.screen_changed([0, 0, 1920, 1080]) is False
    assert bot.screen_changed([0, 0, 2560, 1440]) is True
    d = _drawer()
    d.draw_cfg["formats"]["16:9"] = {"rect": [0, 0, 500, 300], "screen": [0, 0, 2560, 1440]}
    d.draw_cfg["palette"]["pos0"], d.draw_cfg["palette"]["pos1"] = [1, 1], [2, 2]
    assert d.start({"format": "16:9", "w": 1, "h": 1, "cells": [0]}) is False
    assert "écran a changé" in d.message
    c = _cooker()
    c.cook_cfg["screen"] = [0, 0, 2560, 1440]
    monkeypatch.setattr(c, "calibrated", lambda: True)
    assert c.start(delay=0) is False
    assert "écran a changé" in c.message
