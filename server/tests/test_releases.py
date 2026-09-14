"""Dépôt d'assets, publication, manifeste, latest/update_available, téléchargement de secours."""
import hashlib

import pytest

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
