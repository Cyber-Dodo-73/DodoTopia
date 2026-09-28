"""Le cache HTTP de WebView2 est vidé quand l'interface change (sinon : ancienne page + nouveaux scripts)."""
import os

import app


def test_cache_vide_seulement_si_l_interface_change(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("v1", encoding="utf-8")
    storage = tmp_path / "webview"
    cache = storage / "EBWebView" / "Default" / "Cache"
    local = storage / "EBWebView" / "Default" / "Local Storage"
    cache.mkdir(parents=True)
    local.mkdir(parents=True)
    (cache / "f").write_text("x")
    assert app.refresh_ui_cache(str(storage), str(ui)) is True
    assert not cache.exists() and local.exists(), "le cache part, les préférences restent"
    cache.mkdir()
    assert app.refresh_ui_cache(str(storage), str(ui)) is False and cache.exists(), "rien n'a changé"
    (ui / "index.html").write_text("version 2", encoding="utf-8")
    assert app.refresh_ui_cache(str(storage), str(ui)) is True and not cache.exists()
