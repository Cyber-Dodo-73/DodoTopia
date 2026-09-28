"""Rapport de diagnostic (diagnostic.py) : bons fichiers, rien de personnel, journaux tronqués."""
import io
import json
import os
import zipfile

import diagnostic


def _setup(d):
    home = os.path.expanduser("~")
    (d / "dodotopia.log").write_text(f"erreur dans {home}\\AppData\\x.py\n" * 3, encoding="utf-8")
    (d / "cuisine.log").write_text("x" * (diagnostic.LOG_TAIL_BYTES + 5000) + "\nfin du journal\n", encoding="utf-8")
    (d / "cuisine_echec.png").write_bytes(b"\x89PNG fake")
    (d / "cuisine_ref_cook.png").write_bytes(b"\x89PNG fake")
    (d / "multi_ecoute.wav").write_bytes(b"RIFF fake")
    (d / "account.json").write_text('{"token": "SECRET"}', encoding="utf-8")
    (d / "instance.key").write_text("SECRET", encoding="utf-8")
    (d / "library.json").write_text("{}", encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"multi": {"name": "MonPseudo", "mode": "solo"},
                                               "online": {"server_url": "https://x", "token": "SECRET"},
                                               "songs_folder": os.path.join(home, "songs")}), encoding="utf-8")


def _zip(data):
    zf = zipfile.ZipFile(io.BytesIO(data))
    return {n: zf.read(n) for n in zf.namelist()}


def test_contenu_et_confidentialite(tmp_path):
    _setup(tmp_path)
    data, listing = diagnostic.build(str(tmp_path), {"version": "2.1.0"}, note="la cuisine bloque", include_images=True)
    files = _zip(data)
    assert set(files) == {"systeme.json", "description.txt", "dodotopia.log", "cuisine.log", "cuisine_echec.png",
                          "cuisine_ref_cook.png", "config.json"}
    blob = b"".join(files.values())
    assert b"SECRET" not in blob, "ni jeton, ni clé d'instance"
    assert os.path.expanduser("~").encode() not in blob, "le dossier personnel est masqué"
    cfg = json.loads(files["config.json"])
    assert "name" not in cfg["multi"] and cfg["online"] == {"server_url": "https://x"}
    assert cfg["songs_folder"].startswith("~")
    assert json.loads(files["systeme.json"])["version"] == "2.1.0"
    assert files["description.txt"] == "la cuisine bloque".encode()


def test_journaux_tronques_et_audio_sur_demande(tmp_path):
    _setup(tmp_path)
    files = _zip(diagnostic.build(str(tmp_path))[0])
    assert len(files["cuisine.log"]) <= diagnostic.LOG_TAIL_BYTES
    assert files["cuisine.log"].rstrip().endswith(b"fin du journal")
    assert "multi_ecoute.wav" not in files
    assert "cuisine_echec.png" not in files, "aucune capture d'écran sans accord explicite"
    assert "multi_ecoute.wav" in _zip(diagnostic.build(str(tmp_path), include_audio=True)[0])


def test_apercu(tmp_path):
    _setup(tmp_path)
    p = diagnostic.preview(str(tmp_path))
    names = [f["name"] for f in p["files"]]
    assert "account.json" not in names and "instance.key" not in names and "library.json" not in names
    assert p["audio"] is True and p["images"] is True
    log = next(f for f in p["files"] if f["name"] == "cuisine.log")
    assert log["size"] == diagnostic.LOG_TAIL_BYTES


def test_dossier_vide(tmp_path):
    data, listing = diagnostic.build(str(tmp_path))
    assert [f["name"] for f in listing] == ["systeme.json"]
