"""Dépôt d'assets, publication, manifeste, latest/update_available, téléchargement de secours."""
import hashlib
import os
import time
from datetime import datetime, timezone

import pytest

from app import db, releases
from app.releases import version_key


def put(client, headers, version, platform, data, filename=None, sha=None):
    filename = filename or f"DodoTopia-{version}-{platform}.bin"
    sha = sha or hashlib.sha256(data).hexdigest()
    return client.put(f"/api/admin/releases/{version}/assets/{platform}", content=data,
                      headers={**headers, "X-Sha256": sha, "X-Filename": filename})


def test_version_key():
    assert version_key("1.10.0") > version_key("1.9.0")
    assert version_key("1.7") == (1, 7)
    with pytest.raises(ValueError):
        version_key("v1.0")
    with pytest.raises(ValueError):
        version_key("1")


def test_publish_flow(client, publish_headers, settings):
    setup = b"SETUP" * 1000
    assert client.get("/api/releases/latest").status_code == 404
    assert put(client, {}, "1.7.0", "windows-setup", setup).status_code == 403
    assert client.get("/api/admin/releases/check").status_code == 403
    assert client.get("/api/admin/releases/check", headers={"X-Publish-Token": "faux"}).status_code == 403
    assert client.get("/api/admin/releases/check", headers=publish_headers).json() == {"ok": True}

    # publication impossible sans l'installeur
    r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers, json={"notes": "n"})
    assert r.status_code == 409

    r = put(client, publish_headers, "1.7.0", "windows-setup", setup, "DodoTopia-1.7.0-Setup.exe")
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "http://testserver/dl/1.7.0/DodoTopia-1.7.0-Setup.exe"
    assert (settings.releases_dir / "1.7.0" / "DodoTopia-1.7.0-Setup.exe").read_bytes() == setup
    # idempotent
    assert put(client, publish_headers, "1.7.0", "windows-setup", setup, "DodoTopia-1.7.0-Setup.exe").status_code == 200
    assert put(client, publish_headers, "1.7.0", "windows-portable", b"ZIP" * 10, "DodoTopia-1.7.0-portable.zip").status_code == 200

    # non publiée : invisible
    assert client.get("/api/releases/1.7.0").status_code == 404
    assert client.get("/api/releases/latest").status_code == 404

    r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                    json={"notes": "Nouveautés", "mandatory": True})
    assert r.status_code == 200
    m = r.json()
    assert m["version"] == "1.7.0" and m["mandatory"] is True and m["published_at"]
    assert set(m["assets"]) == {"windows-setup", "windows-portable"}
    assert m["assets"]["windows-setup"]["size"] == len(setup)

    r = client.get("/api/releases/latest?current=1.6.1&platform=windows-setup")
    body = r.json()
    assert body["update_available"] is True and body["asset"]["filename"] == "DodoTopia-1.7.0-Setup.exe"
    assert client.get("/api/releases/latest?current=1.7.0").json()["update_available"] is False
    assert client.get("/api/releases/latest?current=1.8.0").json()["update_available"] is False
    assert client.get("/api/releases/latest?platform=linux-x64").json()["asset"] is None
    assert client.get("/api/releases/latest?current=abc").status_code == 422

    # téléchargement servi par l'API, avec reprise (Range)
    r = client.get("/dl/1.7.0/DodoTopia-1.7.0-Setup.exe")
    assert r.status_code == 200 and r.content == setup
    assert r.headers["accept-ranges"] == "bytes"
    r = client.get("/dl/1.7.0/DodoTopia-1.7.0-Setup.exe", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == setup[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(setup)}"
    assert client.get("/dl/1.7.0/absent.exe").status_code == 404
    assert client.get("/dl/1.7.0/..%2Fdodo.db").status_code == 404

    # une version plus récente devient latest, la liste est triée
    put(client, publish_headers, "1.10.0", "windows-setup", b"NEW", "DodoTopia-1.10.0-Setup.exe")
    client.post("/api/admin/releases/1.10.0/publish", headers=publish_headers, json={"notes": ""})
    assert client.get("/api/releases/latest").json()["version"] == "1.10.0"
    assert [x["version"] for x in client.get("/api/releases").json()["items"]] == ["1.10.0", "1.7.0"]

    # suppression
    r = client.delete("/api/admin/releases/1.10.0", headers=publish_headers)
    assert r.status_code == 200
    assert client.get("/api/releases/latest").json()["version"] == "1.7.0"
    assert not (settings.releases_dir / "1.10.0").exists()
    assert client.delete("/api/admin/releases/1.10.0", headers=publish_headers).status_code == 404


def test_put_bad_sha_and_headers(client, publish_headers, settings):
    r = put(client, publish_headers, "1.7.0", "windows-setup", b"abc", "x.exe", sha="0" * 64)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "sha_mismatch"
    assert not list((settings.releases_dir / "1.7.0").glob("*")) if (settings.releases_dir / "1.7.0").exists() else True
    r = client.put("/api/admin/releases/1.7.0/assets/windows-setup", content=b"abc", headers=publish_headers)
    assert r.status_code == 422
    assert put(client, publish_headers, "1.7.0", "mac", b"abc").status_code == 422
    assert put(client, publish_headers, "1.7.0", "windows-setup", b"abc", "../evil.exe").status_code == 422
    assert put(client, publish_headers, "v1", "windows-setup", b"abc", "a.exe").status_code == 422


# --- Usage réel : mises à jour comptées à part, installations actives, tableau de bord ------------------

def _publish(client, publish_headers, version="2.0.2"):
    put(client, publish_headers, version, "windows-setup", b"S" * 2000, f"DodoTopia-{version}-Setup.exe")
    put(client, publish_headers, version, "linux-x64", b"L" * 2000, f"DodoTopia-{version}-linux-x64.tar.gz")
    r = client.post(f"/api/admin/releases/{version}/publish", headers=publish_headers, json={"notes": "n"})
    assert r.status_code == 200, r.text


def test_update_downloads_are_counted_apart(client, publish_headers):
    _publish(client, publish_headers)
    url = "/dl/2.0.2/DodoTopia-2.0.2-Setup.exe"
    assert client.get(url).status_code == 200                          # lien direct : nouvelle installation
    assert client.get(url + "?via=update").status_code == 200          # l'application se met à jour
    assert client.get(url + "?via=update").status_code == 200
    assert client.head(url + "?via=update").status_code == 200         # HEAD : jamais compté
    asset = client.get("/api/releases/latest").json()["assets"]["windows-setup"]
    assert (asset["downloads"], asset["updates"]) == (3, 2)
    stats = client.get("/api/admin/stats", headers=publish_headers).json()
    assert stats["latest"]["assets"]["windows-setup"] == {"downloads": 3, "updates": 2, "new": 1}
    assert stats["latest"]["downloads"] == 3 and stats["latest"]["new_installs"] == 1
    assert client.get("/api/stats").json()["downloads_total"] == 3   # le compteur public reste le total


def test_update_checks_count_active_installs_anonymously(client, publish_headers, settings):
    _publish(client, publish_headers)
    assert client.get("/api/admin/stats").status_code == 403
    empty = client.get("/api/admin/stats", headers=publish_headers).json()
    assert empty["active_installs"]["30d"] == {"installs": 0, "on_latest": 0, "by_version": {}, "by_platform": {}}
    assert empty["recording_since"] is None and empty["days"] == []

    # une adresse sous Linux, en 2.0.1 (le client de test ne transmet pas X-Forwarded-For : sans proxy, cette
    # ligne porte la même empreinte que les suivantes et sera remplacée par la dernière vue ; derrière Traefik,
    # `--proxy-headers` donne l'adresse réelle et ce serait une deuxième installation)
    r = client.get("/api/releases/latest", params={"current": "2.0.1", "platform": "linux-x64"},
                   headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200
    # la même installation vérifie trois fois dans la journée, d'abord en 2.0.1 puis en 2.0.2 : une seule ligne
    for current in ("2.0.1", "2.0.1", "2.0.2"):
        r = client.get("/api/releases/latest", params={"current": current, "platform": "windows-setup"})
        assert r.status_code == 200
    # sans `current` (navigateur curieux) : rien n'est enregistré
    assert client.get("/api/releases/latest").status_code == 200

    conn = db.connect(settings)
    try:
        rows = conn.execute("SELECT day, fp, version, platform FROM install_pings ORDER BY fp").fetchall()
    finally:
        conn.close()
    assert len(rows) in (1, 2)
    for row in rows:
        assert len(row["fp"]) == 32 and "testclient" not in row["fp"] and "203.0.113.9" not in row["fp"]
        assert row["day"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mine = [r for r in rows if r["platform"] == "windows-setup"]
    assert len(mine) == 1 and mine[0]["version"] == "2.0.2"     # dernière version vue : la 2.0.2

    stats = client.get("/api/admin/stats", headers=publish_headers).json()
    for window in ("1d", "7d", "30d"):
        w = stats["active_installs"][window]
        assert w["installs"] == len(rows) and w["on_latest"] == 1
        assert w["by_version"]["2.0.2"] == 1 and w["by_platform"]["windows-setup"] == 1
    assert stats["latest"]["version"] == "2.0.2" and stats["latest"]["active_installs"]["7d"] == 1
    assert stats["days"] == [{"day": rows[0]["day"], "installs": len(rows), "on_latest": 1}]
    assert stats["recording_since"] == rows[0]["day"]
    # le sel est un secret du serveur, hors base, et l'empreinte change avec lui
    salt = settings.data_dir / releases.SALT_FILE
    assert salt.is_file() and len(salt.read_bytes()) == 32


def test_pings_are_purged_and_salt_renewed(client, publish_headers, settings):
    _publish(client, publish_headers)
    client.get("/api/releases/latest", params={"current": "2.0.2", "platform": "windows-setup"})
    conn = db.connect(settings)
    try:
        conn.execute("INSERT INTO install_pings (day, fp, version, platform) VALUES (?, ?, ?, ?)",
                     ("2020-01-01", "x" * 32, "1.0.0", "windows-setup"))
        conn.commit()
    finally:
        conn.close()
    releases.purge_pings(settings)
    conn = db.connect(settings)
    try:
        days = [r["day"] for r in conn.execute("SELECT day FROM install_pings").fetchall()]
    finally:
        conn.close()
    assert days == [datetime.now(timezone.utc).strftime("%Y-%m-%d")]
    salt = settings.data_dir / releases.SALT_FILE
    before = salt.read_bytes()
    old = time.time() - (releases.PINGS_KEEP_DAYS + 1) * 86400
    os.utime(salt, (old, old))
    assert releases.ping_salt(settings) != before                 # sel périmé : renouvelé
    assert salt.read_bytes() == releases.ping_salt(settings)      # puis stable


def test_stats_endpoint_without_any_release(client, publish_headers):
    stats = client.get("/api/admin/stats", headers=publish_headers).json()
    assert stats["latest"] is None and stats["active_installs"]["1d"]["installs"] == 0
