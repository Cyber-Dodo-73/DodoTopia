# -*- coding: utf-8 -*-
"""Conditions d'utilisation obligatoires : etat d'acceptation, garde des methodes de l'Api, rendu du texte."""
import os
import re
import threading
from collections import deque

import pytest

import core
import terms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_la_version_du_code_correspond_au_texte_livre():
    for lang in terms.LANGS:
        assert os.path.isfile(terms.path_for(ROOT, lang)), f"legal/CGU-{lang}.md manquant"
        doc = terms.load(ROOT, lang)
        assert doc["lang"] == lang
        assert doc["version"] == terms.TERMS_VERSION, f"legal/CGU-{lang}.md : Version ≠ TERMS_VERSION"
        assert len(doc["summary"]) == 6, f"le résumé en 6 points manque en {lang}"
        assert "<h2>" in doc["html"] and "<ol>" in doc["html"]
        assert "<!--" not in doc["html"] and "<!--" not in doc["markdown"], "commentaire interne publié"
        assert "<script" not in doc["html"].lower()


def test_rendu_markdown_echappe_tout():
    html = terms.markdown_to_html("# T <b>x</b>\n\nPara **gras** et *ital* `code` [lien](https://a.b/c)\n\n- a\n- b\n\n1. un\n2. deux\n")
    assert "<h1>T &lt;b&gt;x&lt;/b&gt;</h1>" in html
    assert "<strong>gras</strong>" in html and "<em>ital</em>" in html and "<code>code</code>" in html
    assert '<a href="https://a.b/c" rel="noopener">lien</a>' in html
    assert html.count("<li>") == 4 and "<ul>" in html and "<ol>" in html
    # un lien non https n'est pas transforme
    assert "<a" not in terms.markdown_to_html("[x](javascript:alert(1))")


def test_acceptation_versionnee():
    cfg = {}
    assert terms.required(cfg) is True
    assert terms.accept(cfg, "0000-00") is False
    assert terms.required(cfg) is True
    assert terms.accept(cfg, terms.TERMS_VERSION, "en") is True
    assert terms.required(cfg) is False
    st = terms.state(cfg)
    assert st["required"] is False and st["accepted_version"] == terms.TERMS_VERSION and st["accepted_at"]
    # nouvelle version des CGU : il faut accepter de nouveau
    cfg["terms_accepted_version"] = "2020-01"
    assert terms.required(cfg) is True


@pytest.fixture
def api_stub(monkeypatch):
    """Api minimale (sans fenetre ni fils) : seulement ce que la garde et get_terms utilisent."""
    import app
    monkeypatch.setattr(core.platform_io, "foreground_window", lambda: (None, None))
    cfg = core.load_config()
    api = object.__new__(app.Api)
    api._cfg = cfg
    api._logs = deque(maxlen=50)
    api._toasts = deque(maxlen=10)
    api._toast_seq = 0
    api._ui_lock = threading.RLock()
    api._error = None
    api._is_admin = False
    api._player = core.Player(cfg, log=lambda m: None)
    api.get_state = lambda: {"terms": terms.state(cfg)}
    yield api, cfg
    api._player.stop(join=True)


def test_les_actions_sont_refusees_avant_acceptation(api_stub):
    api, cfg = api_stub
    assert terms.required(cfg)
    res = api.play_game()
    assert res["ok"] is False and res["error"] == "terms.required"
    assert api._player.state == "stopped"
    assert any("conditions" in t["msg"].lower() for t in api._toasts)
    res = api.test_key()
    assert res["ok"] is False and res["error"] == "terms.required"


def test_apres_acceptation_les_actions_passent(api_stub):
    api, cfg = api_stub
    api.accept_terms(terms.TERMS_VERSION, "fr")
    assert not terms.required(cfg)
    assert core.load_config()["terms_accepted_version"] == terms.TERMS_VERSION, "acceptation non enregistrée"
    res = api.test_key()          # passe la garde ; echoue plus loin faute de jeu, mais pas sur les CGU
    assert res.get("error") != "terms.required"


def test_toutes_les_methodes_de_la_liste_existent_et_sont_gardees():
    import app
    for name in app.TERMS_GATED:
        fn = getattr(app.Api, name, None)
        assert callable(fn), f"{name} n'existe plus dans Api : retire-la de TERMS_GATED"
        assert getattr(fn, "_terms_gated", False), f"{name} n'est pas gardée"


def test_get_terms_renvoie_le_texte(api_stub):
    api, _ = api_stub
    doc = api.get_terms("en")
    assert doc["lang"] == "en" and doc["version"] == terms.TERMS_VERSION and len(doc["summary"]) == 6
    assert api.get_terms("xx")["lang"] == "fr"


def test_get_terms_sans_dossier_legal_renvoie_none_et_journalise_le_chemin(api_stub, tmp_path, monkeypatch, caplog):
    """Bundle sans legal/ (panne de l'archive Linux 2.0.0) : pas d'exception, et le journal dit où le texte était attendu."""
    import logging
    api, _ = api_stub
    monkeypatch.setattr(core, "RES_DIR", str(tmp_path))
    with caplog.at_level(logging.ERROR, logger="app"):
        assert api.get_terms("fr") is None
    attendu = terms.path_for(str(tmp_path), "fr")
    assert attendu in caplog.text, "le chemin tenté n'apparaît pas dans le journal"
    assert "absent" in caplog.text
    # dossier present mais vide : le contenu est journalise
    caplog.clear()
    os.mkdir(os.path.join(str(tmp_path), "legal"))
    with caplog.at_level(logging.ERROR, logger="app"):
        assert api.get_terms("en") is None
    assert terms.path_for(str(tmp_path), "en") in caplog.text and "contenu : []" in caplog.text


def test_ui_log_borne_le_niveau_la_longueur_et_le_debit(api_stub, monkeypatch, caplog):
    import logging
    import api._base as base
    api, _ = api_stub
    monkeypatch.setattr(base, "_ui_log_times", deque())
    with caplog.at_level(logging.WARNING, logger="app"):
        assert api.ui_log("n'importe quoi", "x" * 2000 + chr(10) + "ligne 2") is True
        rec = caplog.records[-1]
        assert rec.getMessage().startswith("UI: [error] ") and len(rec.getMessage()) <= 500 + len("UI: [error] ")
        assert chr(10) not in rec.getMessage()
        results = [api.ui_log("warn", f"m{i}") for i in range(40)]
    assert results.count(True) == 19 and not any(results[19:]), "au plus 20 lignes par minute"
    assert len([r for r in caplog.records if r.getMessage().startswith("UI: ")]) == 20


def test_la_config_livree_n_accepte_pas_les_cgu_a_la_place_du_joueur():
    """config.default.json est copiee au premier lancement : elle ne doit jamais contenir d'acceptation."""
    import json
    with open(os.path.join(ROOT, "config.default.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert not [k for k in cfg if k.startswith("terms_accepted")]
    assert terms.required(cfg)


def test_la_config_livree_garde_les_valeurs_par_defaut_du_code():
    """config.default.json est générée depuis la config de développement : ses essais (raccourci d'arrêt
    changé, délai court, arrêt au clavier coupé) ne doivent jamais partir chez les joueurs."""
    import json
    with open(os.path.join(ROOT, "config.default.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in core.DEFAULT_CONFIG.items():
        if k in ("instruments", "songs_folder"):
            continue
        if k == "hotkeys":
            assert {n: cfg["hotkeys"].get(n) for n in v} == v
        else:
            assert cfg.get(k) == v, k
