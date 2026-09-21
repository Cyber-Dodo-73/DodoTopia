# -*- coding: utf-8 -*-
"""settings_schema : validation par type, bornes, unites affichees, raccourcis (conflits, desactivation),
reset par section, for_ui, et les nouveaux reglages de lecture (planchers, sustain, programme du jeu)."""
import pytest

import core
import settings_schema as ss


@pytest.fixture
def cfg():
    return core.load_config()


def test_defaults_couvrent_le_schema(cfg):
    d = ss.defaults()
    for path in d:
        ss._spec(path)                                    # chaque defaut correspond a un champ decrit
    for k in ("min_press", "min_gap", "sustain", "game_process", "hotkeys.next_instrument"):
        assert k in d
    assert d["hotkeys.next_instrument"] == "", "F12 (capture Steam) ne doit plus être le défaut"


def test_num_en_millisecondes(cfg):
    v, after = ss.set_value(cfg, "min_press", 25)          # l'interface parle en ms
    assert abs(v - 0.025) < 1e-9 and after is None
    assert ss.to_ui("min_press", v) == 25
    with pytest.raises(ss.SettingError):
        ss.validate("min_press", 500)                       # hors bornes (5-60 ms)
    with pytest.raises(ss.SettingError):
        ss.validate("min_press", "abc")


def test_bool_et_choix(cfg):
    assert ss.validate("sustain", "oui") is True
    assert ss.validate("sustain", 0) is False
    assert ss.validate("input_mode", "vk") == "vk"
    with pytest.raises(ss.SettingError):
        ss.validate("input_mode", "magic")


def test_str_borne(cfg):
    assert ss.validate("game_process", "  Heartopia.exe ") == "Heartopia.exe"
    assert ss.validate("game_process", "") == ""
    with pytest.raises(ss.SettingError):
        ss.validate("game_process", "x" * 65)


def test_raccourcis_conflit_et_desactivation(cfg):
    with pytest.raises(ss.SettingError):
        ss.validate("hotkeys.next_song", "F7", cfg)         # F7 = arrêter
    assert ss.validate("hotkeys.next_instrument", "", cfg) == ""
    for essential in ("play_pause", "stop", "draw_point"):
        with pytest.raises(ss.SettingError):
            ss.validate(f"hotkeys.{essential}", "", cfg)
    with pytest.raises(ss.SettingError):
        ss.validate("hotkeys.next_song", "touche-qui-n-existe-pas", cfg)


def test_reset_de_la_section_lecture(cfg):
    ss.set_value(cfg, "min_press", 40)
    ss.set_value(cfg, "sustain", True)
    ss.reset(cfg, "lecture")
    assert abs(cfg["min_press"] - core.DEFAULT_CONFIG["min_press"]) < 1e-9
    assert cfg["sustain"] is False
    with pytest.raises(ss.SettingError):
        ss.reset(cfg, "nimporte")


def test_for_ui_expose_bornes_et_valeur(cfg):
    ui = ss.for_ui(cfg)
    f = ui["min_gap"]
    assert f["type"] == "num" and f["unit"] == "ms" and f["min"] == 5 and f["max"] == 60
    assert f["value"] == ss.to_ui("min_gap", cfg["min_gap"])
    assert ui["game_process"]["value"] == "xdt.exe, Heartopia.exe"
    assert ui["hotkeys.next_instrument"]["value"] == ""


def test_chemin_inconnu(cfg):
    with pytest.raises(ss.SettingError):
        ss.get(cfg, "pas.un.reglage")


def test_une_touche_de_note_ne_peut_pas_etre_un_raccourci(cfg):
    """Arrêter = « b » arrêtait la lecture toute seule : DodoTopia envoie lui-même cette touche au jeu."""
    for key in ("b", "B", ";", "5"):
        with pytest.raises(ss.SettingError):
            ss.validate("hotkeys.stop", key, cfg)
    assert ss.validate("hotkeys.stop", "F7", cfg) == "F7"
    assert ss.validate("hotkeys.next_song", "ctrl+b", cfg) == "ctrl+b"
    assert core.is_note_key("b") and not core.is_note_key("F7") and not core.is_note_key("ctrl+b")


def test_un_raccourci_pose_sur_une_note_est_repare_au_chargement():
    import json
    with open(core.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"hotkeys": {"play_pause": "F6", "stop": "b", "next_song": "ctrl+n"}}, f)
    cfg = core.load_config()
    assert cfg["hotkeys"]["stop"] == "F7"
    assert cfg["hotkeys"]["next_song"] == "ctrl+n"
    assert cfg["_hotkeys_fixed"] == ["stop"]
