"""Espace admin du site : connexion Discord par cookie, statistiques, webhook de notifications, journal, comptes."""
from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest

from app import admin, db, notify, stats
from conftest import bearer, login, make_midi

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/" + "a" * 68
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/128.0 Safari/537.36")


@pytest.fixture
def sent(monkeypatch, client):
    """Notifications envoyées (webhook simulé, envoi synchrone)."""
    out = []

    class Ok:
        status_code = 204

    def fake_post(url, payload):
        out.append((url, payload))
        return Ok()

    monkeypatch.setattr(notify, "post_webhook", fake_post)
    client.app.state.notifier.sync = True
    return out


def web_login(client, discord_id: str):
    """Déroule la connexion du site : POST /admin/login -> Discord -> callback. Renvoie la réponse du callback."""
    r = client.post("/admin/login")
    assert r.status_code == 303, r.text
    loc = urlparse(r.headers["location"])
    assert loc.netloc == "discord.com"
    state = parse_qs(loc.query)["state"][0]
    return client.get(f"/auth/discord/callback?code={discord_id}&state={state}")


def set_webhook(client, token):
    r = client.put("/api/admin/settings", headers=bearer(token), json={"webhook_url": WEBHOOK})
    assert r.status_code == 200, r.text
    return r


def flush(client):
    stats.flush(client.app.state.settings, client.app.state.stats)


# --- connexion ---------------------------------------------------------------------------------------------------

def test_admin_page_redirects_to_login_when_anonymous(client):
    r = client.get("/admin")
    assert r.status_code == 302 and r.headers["location"] == "/admin/login"
    r = client.get("/admin/login")
    assert r.status_code == 200 and "Se connecter avec Discord" in r.text
    assert "noindex" in r.headers["x-robots-tag"]


def test_web_login_as_admin_sets_cookie_and_opens_dashboard(client):
    r = web_login(client, "999")
    assert r.status_code == 302 and r.headers["location"] == "/admin", r.text
    assert "dodo_admin=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    page = client.get("/admin")
    assert page.status_code == 200 and "/static/admin.js" in page.text
    assert client.get("/api/admin/overview").status_code == 200
    with db.connect(client.app.state.settings) as conn:
        assert conn.execute("SELECT kind FROM sessions").fetchone()["kind"] == "web"


def test_web_login_refused_for_non_admin(client):
    r = web_login(client, "111")
    assert r.status_code == 302 and r.headers["location"] == "/admin/login?error=forbidden"
    assert "dodo_admin=" not in r.headers.get("set-cookie", "").replace("dodo_admin_state", "")
    assert client.get("/admin").status_code == 302
    with db.connect(client.app.state.settings) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def _confirm_token(html):
    import re
    return re.search(r'name="token" value="([^"]+)"', html).group(1)


def test_web_login_in_another_browser_asks_for_a_click_and_never_logs_in_silently(client):
    r = client.post("/admin/login")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.cookies.clear()     # autre navigateur (appli Discord sur mobile), ou lien de retour envoyé par un tiers
    r = client.get(f"/auth/discord/callback?code=999&state={state}")
    # aucune session : une page nomme le compte et demande un clic
    assert r.status_code == 200 and "Continuer en tant que" in r.text and "dodo_admin=" not in r.headers["set-cookie"]
    assert "dodo_admin_confirm=" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    assert client.get("/admin").status_code == 302
    token = _confirm_token(r.text)

    # un formulaire soumis depuis un autre site n'emporte pas le cookie Strict : refusé, et le jeton est consommé
    saved = dict(client.cookies)
    client.cookies.clear()
    r2 = client.post("/admin/login/confirm", data={"token": token})
    assert r2.status_code == 303 and r2.headers["location"] == "/admin/login?error=expired"
    for k, v in saved.items():
        client.cookies.set(k, v)
    r2 = client.post("/admin/login/confirm", data={"token": token})
    assert r2.headers["location"] == "/admin/login?error=expired"          # usage unique
    assert client.get("/admin").status_code == 302


def test_web_login_in_another_browser_completes_after_the_click(client):
    r = client.post("/admin/login")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.cookies.clear()
    page = client.get(f"/auth/discord/callback?code=999&state={state}")
    r = client.post("/admin/login/confirm", data={"token": _confirm_token(page.text)})
    assert r.status_code == 303 and r.headers["location"] == "/admin" and "dodo_admin=" in r.headers["set-cookie"]
    assert client.get("/admin").status_code == 200
    assert client.post("/admin/login/confirm", data={"token": "inconnu"}).headers["location"] == "/admin/login?error=expired"


def test_web_login_in_another_browser_still_refuses_a_non_admin(client):
    r = client.post("/admin/login")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.cookies.clear()
    r = client.get(f"/auth/discord/callback?code=111&state={state}")
    assert r.headers["location"] == "/admin/login?error=forbidden"


def test_cookie_needs_admin_header_to_write(client):
    web_login(client, "999")
    assert client.put("/api/admin/settings", json={"mention": ""}).status_code == 401
    r = client.put("/api/admin/settings", json={"mention": "42"}, headers={"X-Dodo-Admin": "1"})
    assert r.status_code == 200 and r.json()["mention"] == "42"


def test_logout_deletes_web_session(client):
    web_login(client, "999")
    r = client.post("/admin/logout")
    assert r.status_code == 303
    assert client.get("/admin").status_code == 302
    with db.connect(client.app.state.settings) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE kind='web'").fetchone()[0] == 0


def test_admin_api_refuses_players(client, user_token):
    for path in ("/api/admin/overview", "/api/admin/stats", "/api/admin/live", "/api/admin/users",
                 "/api/admin/settings", "/api/admin/log", "/api/admin/releases-stats"):
        assert client.get(path, headers=bearer(user_token)).status_code == 403, path
        assert client.get(path).status_code == 401, path


# --- statistiques --------------------------------------------------------------------------------------------------

def test_page_views_visitors_bots_and_app_clients_are_counted(client, admin_token):
    for _ in range(3):
        assert client.get("/fr/", headers={"User-Agent": BROWSER_UA, "Referer": "https://www.google.com/search"}
                          ).status_code == 200
    client.get("/fr/", headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"})
    client.get("/api/songs", headers={"User-Agent": "DodoTopia/2.0.2 (Windows)"})
    r = client.get("/api/admin/stats?days=7", headers=bearer(admin_token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["series"]["pv"][-1] == 3
    assert d["series"]["visitors"][-1] == 1
    assert d["series"]["bots"][-1] == 1
    assert d["series"]["app_active"][-1] == 1
    b = d["breakdowns"]
    assert {"label": "google.com", "value": 3} in b["referrers"]
    assert b["browsers"][0]["label"] == "Chrome" and b["os"][0]["label"] == "Windows"
    assert b["app_versions"] == [{"label": "2.0.2", "value": 1}]
    assert b["bots"][0]["label"] == "googlebot"
    assert sum(map(sum, d["heatmap"])) == 3


def test_admin_pages_are_not_counted_as_audience(client, admin_token):
    web_login(client, "999")
    client.get("/admin", headers={"User-Agent": BROWSER_UA})
    flush(client)
    d = client.get("/api/admin/stats", headers=bearer(admin_token)).json()
    assert d["series"]["pv"][-1] == 0


def test_business_events_feed_the_series(client, admin_token, user_token):
    client.post("/api/songs", headers=bearer(user_token), files={"file": ("a.mid", make_midi(), "audio/midi")})
    d = client.get("/api/admin/stats", headers=bearer(admin_token)).json()
    s = d["series"]
    assert s["signups"][-1] == 2 and s["logins"][-1] == 2 and s["songs_uploaded"][-1] == 1


def test_release_downloads_are_counted_by_platform_and_origin(client, admin_token, publish_headers):
    data = b"SETUP" * 100
    r = client.put("/api/admin/releases/2.0.0/assets/windows-setup", content=data,
                   headers={**publish_headers, "X-Sha256": hashlib.sha256(data).hexdigest(),
                            "X-Filename": "DodoTopia-2.0.0-Setup.exe"})
    assert r.status_code == 200, r.text
    assert client.post("/api/admin/releases/2.0.0/publish", headers=publish_headers, json={"notes": "n"}).status_code == 200
    client.get("/dl/2.0.0/DodoTopia-2.0.0-Setup.exe", headers={"User-Agent": "DodoTopia/1.9.0 (Windows)"})
    client.get("/dl/2.0.0/DodoTopia-2.0.0-Setup.exe", headers={"User-Agent": BROWSER_UA})
    d = client.get("/api/admin/stats", headers=bearer(admin_token)).json()
    assert d["series"]["dl_app"][-1] == 2
    assert d["breakdowns"]["dl_platforms"] == [{"label": "windows-setup", "value": 2}]
    assert {x["label"] for x in d["breakdowns"]["dl_sources"]} == {"app", "direct"}
    rel = client.get("/api/admin/releases-stats", headers=bearer(admin_token)).json()
    assert rel["items"][0]["downloads"] == 2


def test_uniques_of_past_days_are_frozen_and_erased(client, settings):
    rec = client.app.state.stats
    rec.unique("visitors", "1.2.3.4|ua", day="2026-01-01")
    rec.unique("visitors", "5.6.7.8|ua", day="2026-01-01")
    rec.unique("visitors", "1.2.3.4|ua", day="2026-01-01")
    flush(client)
    with db.connect(settings) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stat_uniques").fetchone()[0] == 0
        row = conn.execute("SELECT n FROM stat_daily WHERE day='2026-01-01' AND key='u:visitors'").fetchone()
        assert row["n"] == 2
    assert "2026-01-01" not in rec._salts


def test_gauges_keep_the_daily_maximum(client, settings):
    rec = client.app.state.stats
    rec.gauge("players", 5, day="2026-02-02")
    flush(client)
    rec.gauge("players", 3, day="2026-02-02")
    flush(client)
    with db.connect(settings) as conn:
        assert conn.execute("SELECT n FROM stat_daily WHERE key='peak_players'").fetchone()["n"] == 5


def test_dimensions_are_capped_per_day(client):
    rec = client.app.state.stats
    for i in range(stats.MAX_DIMS_PER_KEY_DAY + 20):
        rec.hit("pv_path", f"/p/{i}", day="2026-03-03")
    counts, _, _ = rec.take()
    assert counts[("2026-03-03", "pv_path", stats.OTHER)] == 20


def test_csv_export(client, admin_token):
    r = client.get("/api/admin/stats.csv?days=7", headers=bearer(admin_token))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("jour;pv;visitors") and len(lines) == 8


def test_live_and_overview(client, admin_token):
    o = client.get("/api/admin/overview", headers=bearer(admin_token)).json()
    assert o["users"]["total"] == 1 and o["live"] == {"rooms": 0, "players": 0, "playing": 0}
    lv = client.get("/api/admin/live", headers=bearer(admin_token)).json()
    assert lv["server"]["db"] in ("sqlite", "postgres") and "folders" in lv["storage"]
    admin.background_tick(client.app)   # échantillon du direct + écriture
    assert len(client.app.state.stats.live) == 1


def test_user_agent_classification():
    assert stats.browser_of(BROWSER_UA) == "Chrome"
    assert stats.device_of("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "Mobile"
    assert stats.os_of("Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0") == "Linux"
    assert stats.referrer_host("https://www.reddit.com/r/x", "dodotopia.fr") == "reddit.com"
    assert stats.referrer_host("https://dodotopia.fr/fr/aide", "dodotopia.fr") == ""
    assert stats.api_family("/api/songs/12/download") == "songs"
    assert stats.api_family("/api/admin/songs") == "admin/songs"


# --- notifications -------------------------------------------------------------------------------------------------

def test_webhook_settings_are_validated_and_masked(client, admin_token):
    r = client.put("/api/admin/settings", headers=bearer(admin_token), json={"webhook_url": "https://evil.example/x"})
    assert r.status_code == 422
    body = set_webhook(client, admin_token).json()
    assert body["webhook_set"] and body["source"] == "site"
    assert WEBHOOK not in r.text and body["webhook_masked"].endswith("aaaa")
    assert "a" * 20 not in str(body)
    r = client.put("/api/admin/settings", headers=bearer(admin_token), json={"mention": "@everyone"})
    assert r.status_code == 422


def test_notifications_for_moderation_and_reports(client, admin_token, user_token, sent):
    set_webhook(client, admin_token)
    r = client.post("/api/songs", headers=bearer(user_token), files={"file": ("a.mid", make_midi(), "audio/midi")},
                    data={"title": "Ma chanson"})
    assert r.status_code == 201
    song_id = r.json()["id"]
    assert sent[-1][0] == WEBHOOK
    embed = sent[-1][1]["embeds"][0]
    assert embed["title"] == "Morceau à valider : Ma chanson"
    assert sent[-1][1]["allowed_mentions"] == {"parse": []}
    client.post(f"/api/admin/songs/{song_id}/approve", headers=bearer(admin_token))
    client.post(f"/api/songs/{song_id}/report", headers=bearer(user_token), json={"reason": "doublon"})
    assert sent[-1][1]["embeds"][0]["title"].startswith("Signalement")


def test_new_user_is_announced_once(client, admin_token, sent):
    set_webhook(client, admin_token)
    login(client, "111")
    login(client, "111")
    titles = [p["embeds"][0]["title"] for _, p in sent]
    assert titles.count("Nouveau compte : Alice") == 1


def test_disabled_events_are_not_sent(client, admin_token, user_token, sent):
    set_webhook(client, admin_token)
    client.put("/api/admin/settings", headers=bearer(admin_token), json={"events": {"song_pending": False}})
    client.post("/api/songs", headers=bearer(user_token), files={"file": ("a.mid", make_midi(), "audio/midi")})
    assert not any("Morceau" in p["embeds"][0]["title"] for _, p in sent)


def test_role_mention_only_on_actionable_events(client, admin_token, user_token, sent):
    set_webhook(client, admin_token)
    client.put("/api/admin/settings", headers=bearer(admin_token), json={"mention": "4242424242"})
    client.post("/api/songs", headers=bearer(user_token), files={"file": ("a.mid", make_midi(), "audio/midi")})
    assert sent[-1][1]["content"] == "<@&4242424242>"
    assert sent[-1][1]["allowed_mentions"] == {"roles": ["4242424242"]}


def test_webhook_test_button(client, admin_token, sent):
    assert client.post("/api/admin/settings/test", headers=bearer(admin_token)).status_code == 409
    set_webhook(client, admin_token)
    assert client.post("/api/admin/settings/test", headers=bearer(admin_token)).status_code == 200
    assert "Test du webhook" in sent[-1][1]["embeds"][0]["title"]


def test_server_errors_are_throttled(client, admin_token, sent):
    set_webhook(client, admin_token)
    n = client.app.state.notifier
    n.server_error("GET", "/api/songs/1", 500)
    n.server_error("GET", "/api/songs/2", 500)   # même chemin une fois les chiffres masqués
    assert sum(1 for _, p in sent if p["embeds"][0]["title"] == "Erreur 500") == 1


def test_daily_summary_once_per_day(client, admin_token, sent, monkeypatch):
    set_webhook(client, admin_token)
    monkeypatch.setattr(stats, "local_now", lambda: datetime(2026, 9, 28, 10, 0, tzinfo=stats.TZ))
    assert admin.maybe_daily_summary(client.app) is True
    assert admin.maybe_daily_summary(client.app) is False
    assert sent[-1][1]["embeds"][0]["title"] == "Bilan du 2026-09-27"
    monkeypatch.setattr(stats, "local_now", lambda: datetime(2026, 9, 29, 8, 0, tzinfo=stats.TZ))
    assert admin.maybe_daily_summary(client.app) is False    # avant 9 h


def test_failed_delivery_is_reported_not_raised(client, admin_token, monkeypatch):
    set_webhook(client, admin_token)
    n = client.app.state.notifier
    n.sync = True

    def boom(url, payload):
        raise OSError("réseau coupé")

    monkeypatch.setattr(notify, "post_webhook", boom)
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    assert n.emit("new_user", "x") is False
    assert n.failed == 1 and "réseau coupé" in n.last_failure


# --- journal et comptes --------------------------------------------------------------------------------------------

def test_moderation_actions_are_logged(client, admin_token, user_token):
    r = client.post("/api/songs", headers=bearer(user_token), files={"file": ("a.mid", make_midi(), "audio/midi")},
                    data={"title": "Titre"})
    sid = r.json()["id"]
    client.post(f"/api/admin/songs/{sid}/reject", headers=bearer(admin_token), json={"reason": "qualité"})
    log = client.get("/api/admin/log", headers=bearer(admin_token)).json()
    assert log["items"][0]["action"] == "song_reject" and log["items"][0]["detail"] == "qualité"
    assert log["items"][0]["admin_name"] == "Admin"


def test_users_list_detail_ban_unban_revoke(client, admin_token, user_token):
    users = client.get("/api/admin/users?q=ali", headers=bearer(admin_token)).json()
    assert users["total"] == 1
    uid = users["items"][0]["id"]
    detail = client.get(f"/api/admin/users/{uid}", headers=bearer(admin_token)).json()
    assert detail["user"]["username"] == "Alice" and len(detail["sessions"]) == 1
    assert client.post(f"/api/admin/users/{uid}/revoke", headers=bearer(admin_token)).json()["revoked"] == 1
    assert client.get("/api/me", headers=bearer(user_token)).status_code == 401
    client.post(f"/api/admin/users/{uid}/ban", headers=bearer(admin_token))
    assert client.get("/api/admin/users?filter=banned", headers=bearer(admin_token)).json()["total"] == 1
    client.post(f"/api/admin/users/{uid}/unban", headers=bearer(admin_token))
    assert client.get("/api/admin/users?filter=banned", headers=bearer(admin_token)).json()["total"] == 0
    actions = [x["action"] for x in client.get("/api/admin/log", headers=bearer(admin_token)).json()["items"]]
    assert actions[:3] == ["user_unban", "user_ban", "sessions_revoke"]


def test_community_content_stats(client, admin_token, user_token):
    r = client.post("/api/songs", headers=bearer(user_token), files={"file": ("a.mid", make_midi(40), "audio/midi")},
                    data={"title": "Top", "tags": "anime"})
    client.post(f"/api/admin/songs/{r.json()['id']}/approve", headers=bearer(admin_token))
    client.get(f"/api/songs/{r.json()['id']}/download")
    d = client.get("/api/admin/stats", headers=bearer(admin_token)).json()
    c = d["content"]
    assert c["top_songs_downloads"][0]["title"] == "Top" and c["top_songs_downloads"][0]["downloads"] == 1
    assert d["breakdowns"]["top_song_downloads"][0]["label"] == "Top"
    assert c["moderation"]["approval_rate"] == 100.0
    assert c["top_uploaders"][0]["username"] == "Alice"
