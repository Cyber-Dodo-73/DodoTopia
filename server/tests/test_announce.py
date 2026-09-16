"""Annonce Discord d'une version publiée : une seule fois (`releases.announced_at`), notes tronquées, nouvel essai
après un échec, rien sans DISCORD_ANNOUNCE_WEBHOOK. `httpx.post` est remplacé : aucun appel réseau."""
import hashlib

import httpx
import pytest
from conftest import PUBLISH_TOKEN, make_client, make_settings

from app import db, releases

WEBHOOK = "https://discord.com/api/webhooks/123/abc"
HEADERS = {"X-Publish-Token": PUBLISH_TOKEN}


class FakePost:
    def __init__(self, status=204, exc=None):
        self.calls = []
        self.status = status
        self.exc = exc

    def __call__(self, url, json=None, timeout=None, **kw):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.exc:
            raise self.exc
        return httpx.Response(self.status, request=httpx.Request("POST", url))


def publish(client, version="1.7.0", notes="Nouveautés"):
    data = b"SETUP" + version.encode()
    r = client.put(f"/api/admin/releases/{version}/assets/windows-setup", content=data,
                   headers={**HEADERS, "X-Sha256": hashlib.sha256(data).hexdigest(),
                            "X-Filename": f"DodoTopia-{version}-Setup.exe"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/admin/releases/{version}/publish", headers=HEADERS, json={"notes": notes})
    assert r.status_code == 200, r.text
    return r


def announced_at(settings, version):
    conn = db.connect(settings)
    try:
        return conn.execute("SELECT announced_at FROM releases WHERE version=?", (version,)).fetchone()["announced_at"]
    finally:
        conn.close()


def test_release_is_announced_once(tmp_path, monkeypatch):
    fake = FakePost()
    monkeypatch.setattr(releases.httpx, "post", fake)
    settings = make_settings(tmp_path, DISCORD_ANNOUNCE_WEBHOOK=WEBHOOK)
    with make_client(settings) as c:
        long_notes = "- " + "x" * 3000
        publish(c, "1.7.0", long_notes)
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["url"] == WEBHOOK and call["timeout"] == 10
        embed = call["json"]["embeds"][0]
        assert embed["title"] == "DodoTopia 1.7.0"
        assert embed["url"] == "http://testserver/fr/telecharger"
        assert len(embed["description"]) == 1500 and embed["description"].endswith("…")
        assert call["json"]["allowed_mentions"] == {"parse": []}
        assert announced_at(settings, "1.7.0")
        publish(c, "1.7.0", "republiée")                    # republication : pas de seconde annonce
        assert len(fake.calls) == 1
        publish(c, "1.7.1", "Correctifs")
        assert len(fake.calls) == 2 and fake.calls[1]["json"]["embeds"][0]["description"] == "Correctifs"


def test_failed_announce_is_retried_on_next_publish(tmp_path, monkeypatch):
    failing = FakePost(status=500)
    monkeypatch.setattr(releases.httpx, "post", failing)
    settings = make_settings(tmp_path, DISCORD_ANNOUNCE_WEBHOOK=WEBHOOK)
    with make_client(settings) as c:
        publish(c)
        assert len(failing.calls) == 1 and announced_at(settings, "1.7.0") is None
        ok = FakePost()
        monkeypatch.setattr(releases.httpx, "post", ok)
        publish(c)
        assert len(ok.calls) == 1 and announced_at(settings, "1.7.0")
        monkeypatch.setattr(releases.httpx, "post", FakePost(exc=httpx.ConnectError("réseau")))
        publish(c, "1.8.0")                                  # erreur réseau : la publication réussit quand même
        assert announced_at(settings, "1.8.0") is None


@pytest.mark.parametrize("webhook", ["", "http://discord.com/api/webhooks/1/a"])
def test_no_announce_without_https_webhook(tmp_path, monkeypatch, webhook):
    fake = FakePost()
    monkeypatch.setattr(releases.httpx, "post", fake)
    settings = make_settings(tmp_path, DISCORD_ANNOUNCE_WEBHOOK=webhook)
    with make_client(settings) as c:
        publish(c)
    assert fake.calls == [] and announced_at(settings, "1.7.0") is None


def test_announce_ignores_unpublished_release(tmp_path, monkeypatch):
    fake = FakePost()
    monkeypatch.setattr(releases.httpx, "post", fake)
    settings = make_settings(tmp_path, DISCORD_ANNOUNCE_WEBHOOK=WEBHOOK)
    db.init(settings)
    conn = db.connect(settings)
    try:
        conn.execute("INSERT INTO releases (version) VALUES ('2.0.0')")
        conn.commit()
    finally:
        conn.close()
    assert releases.announce_release(settings, "2.0.0") is False and fake.calls == []
    assert releases.truncate_notes("court") == "court"
