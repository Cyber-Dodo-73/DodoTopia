"""Galerie de dessins : dépôt (PNG vérifié et ré-encodé, grille facultative), PNG hostiles, modération, likes,
suppression, signalements, suppression de compte, limitation de débit."""
import hashlib
import io
import json
import struct
import zlib

import pytest
from conftest import bearer, login, make_client, make_settings
from PIL import Image, PngImagePlugin

from app import db


def make_png(w=64, h=48, color=(200, 120, 40), mode="RGB", text=None, trailer=b"") -> bytes:
    img = Image.new(mode, (w, h), color)
    info = None
    if text:
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", text)
        info.add_text("Author", text, zip=True)
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=info)
    return buf.getvalue() + trailer


def raw_png(w, h, idat=b"") -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def cells_for(w=4, h=3, fmt="30x30"):
    return json.dumps({"format": fmt, "w": w, "h": h, "cells": [i % 5 - 1 for i in range(w * h)]})


def upload(client, token, png, title="Mon dessin", cells=None):
    data = {"title": title}
    if cells is not None:
        data["cells"] = cells
    return client.post("/api/drawings", headers=bearer(token), files={"png": ("dessin.png", png, "image/png")},
                       data=data)


def approved_drawing(client, token, admin_token, **kw):
    r = upload(client, token, make_png(color=(len(kw.get("title", "")) * 7 % 255, 10, 10)), **kw)
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert client.post(f"/api/admin/drawings/{did}/approve", headers=bearer(admin_token)).status_code == 200
    return did


def test_upload_reencodes_and_moderation_flow(client, user_token, other_token, admin_token, settings):
    hostile = make_png(text="secret-metadonnee", trailer=b"PK\x03\x04 zip colle apres IEND <script>")
    assert client.post("/api/drawings", files={"png": ("a.png", hostile)}).status_code == 401
    r = upload(client, user_token, hostile, title="  Chat‮ roux  ", cells=cells_for())
    assert r.status_code == 201, r.text
    d = r.json()
    did = d["id"]
    assert d["status"] == "pending" and d["title"] == "Chat roux" and (d["w"], d["h"]) == (64, 48)
    assert d["has_cells"] is True and d["app_url"] == f"dodotopia://drawing/{did}" and d["likes"] == 0
    stored = (settings.drawings_dir / f"{d['sha256']}.png").read_bytes()
    assert hashlib.sha256(stored).hexdigest() == d["sha256"] and d["png_size"] == len(stored)
    assert b"secret-metadonnee" not in stored and b"PK\x03\x04" not in stored and b"tEXt" not in stored
    assert stored.endswith(b"IEND\xaeB`\x82")
    assert Image.open(io.BytesIO(stored)).size == (64, 48)
    assert (settings.drawings_dir / f"{d['sha256']}.thumb.png").is_file()

    # en attente : invisible au public, visible pour l'auteur et l'admin
    assert client.get("/api/drawings").json()["total"] == 0
    for path in (f"/api/drawings/{did}", f"/api/drawings/{did}.png", f"/api/drawings/{did}/thumb.png",
                 f"/api/drawings/{did}/cells"):
        assert client.get(path).status_code == 404, path
        assert client.get(path, headers=bearer(other_token)).status_code == 404, path
        assert client.get(path, headers=bearer(user_token)).status_code == 200, path
    pending = client.get("/api/admin/drawings?status=pending", headers=bearer(admin_token)).json()
    assert [x["id"] for x in pending["items"]] == [did]
    assert client.get("/api/admin/drawings", headers=bearer(user_token)).status_code == 403

    assert client.post(f"/api/admin/drawings/{did}/approve", headers=bearer(admin_token)).json()["status"] == "approved"
    lst = client.get("/api/drawings").json()
    assert lst["total"] == 1 and lst["items"][0]["thumb_url"].endswith(f"/api/drawings/{did}/thumb.png")
    r = client.get(f"/api/drawings/{did}.png")
    assert r.status_code == 200 and r.content == stored and r.headers["content-type"] == "image/png"
    assert "public" in r.headers["cache-control"] and r.headers["x-content-type-options"] == "nosniff"
    thumb = client.get(f"/api/drawings/{did}/thumb.png")
    assert thumb.status_code == 200 and Image.open(io.BytesIO(thumb.content)).size == (64, 48)
    cells = client.get(f"/api/drawings/{did}/cells").json()
    assert cells == json.loads(cells_for())

    r = client.post(f"/api/admin/drawings/{did}/reject", headers=bearer(admin_token), json={"reason": "flou"})
    assert r.json()["status"] == "rejected" and r.json()["reject_reason"] == "flou"
    assert client.get(f"/api/drawings/{did}.png").status_code == 404
    assert client.get("/api/admin/drawings?status=bad", headers=bearer(admin_token)).status_code == 422


def test_thumbnail_is_400px_max_and_duplicates_refused(client, user_token, settings):
    png = make_png(1000, 500, color=(1, 2, 3, 128), mode="RGBA")
    r = upload(client, user_token, png)
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["thumb_w"], d["thumb_h"]) == (400, 200) and d["has_cells"] is False and d["cells_url"] is None
    thumb = Image.open(settings.drawings_dir / f"{d['sha256']}.thumb.png")
    assert thumb.size == (400, 200)
    dup = upload(client, user_token, png + b"garbage")          # même pixels : même PNG ré-encodé
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == d["id"]
    assert client.get(f"/api/drawings/{d['id']}/cells", headers=bearer(user_token)).status_code == 404


def _apng() -> bytes:
    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 255, 0))]
    buf = io.BytesIO()
    frames[0].save(buf, "PNG", save_all=True, append_images=frames[1:])
    return buf.getvalue()


def _gif() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "GIF")
    return buf.getvalue()


@pytest.mark.parametrize("name, payload, status, code", [
    ("gif", _gif(), 422, "invalid_png"),
    ("html", b"<html><script>alert(1)</script></html>", 422, "invalid_png"),
    ("signature seule", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, 422, "invalid_png"),
    ("tronqué", make_png(300, 300, color=(9, 9, 9))[:120], 422, "invalid_png"),
    ("IDAT corrompu", raw_png(16, 16, b"pas du zlib"), 422, "invalid_png"),
    ("IHDR géant", raw_png(50000, 50000, zlib.compress(b"\x00" * 10)), 422, "image_too_large"),
    ("trop large", make_png(1025, 10), 422, "image_too_large"),
    ("APNG", _apng(), 422, "invalid_png"),
    ("vide", b"", 422, "invalid_png"),
])
def test_hostile_pngs_are_refused(client, user_token, settings, name, payload, status, code):
    r = upload(client, user_token, payload)
    assert r.status_code == status and r.json()["detail"]["code"] == code, (name, r.text)
    assert not list(settings.drawings_dir.glob("*.png")), name


def test_too_heavy_png_and_bad_cells(tmp_path):
    with make_client(make_settings(tmp_path, MAX_DRAWING_PNG_BYTES=2000, MAX_DRAWING_CELLS_BYTES=300)) as c:
        tok, _ = login(c, "111")
        noisy = Image.frombytes("RGB", (200, 200), bytes((i * 7919) % 251 for i in range(200 * 200 * 3)))
        buf = io.BytesIO()
        noisy.save(buf, "PNG")
        r = upload(c, tok, buf.getvalue())
        assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
        small = make_png(8, 8)
        assert upload(c, tok, small, cells=cells_for(30, 30)).status_code == 413
        for bad in ("pas du json", "[1,2]", '{"format":"x","w":2,"h":2,"cells":[1,2,3]}',
                    '{"format":"x","w":2,"h":2,"cells":[1,2,3,"4"]}', '{"format":"x","w":0,"h":2,"cells":[]}',
                    '{"format":"<b>","w":1,"h":1,"cells":[1]}', '{"format":"x","w":1,"h":1,"cells":[true]}',
                    '{"format":"x","w":1,"h":1,"cells":[70000]}'):
            r = upload(c, tok, small, cells=bad)
            assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_cells", bad


def test_drawing_likes_delete_and_rights(client, user_token, other_token, admin_token, settings):
    did = approved_drawing(client, user_token, admin_token, title="A")
    for _ in range(2):
        assert client.post(f"/api/drawings/{did}/like", headers=bearer(other_token)).json()["likes"] == 1
    assert client.get(f"/api/drawings/{did}", headers=bearer(other_token)).json()["liked_by_me"] is True
    assert client.get("/api/drawings", headers=bearer(user_token)).json()["items"][0]["liked_by_me"] is False
    did2 = approved_drawing(client, user_token, admin_token, title="BB")
    assert [x["id"] for x in client.get("/api/drawings?sort=popular").json()["items"]] == [did, did2]
    assert [x["id"] for x in client.get("/api/drawings?sort=recent").json()["items"]] == [did2, did]
    assert client.delete(f"/api/drawings/{did}/like", headers=bearer(other_token)).json()["likes"] == 0
    assert client.delete(f"/api/drawings/{did}/like", headers=bearer(other_token)).json()["likes"] == 0

    sha = client.get(f"/api/drawings/{did}").json()["sha256"]
    assert client.delete(f"/api/drawings/{did}", headers=bearer(other_token)).status_code == 403
    assert client.delete(f"/api/drawings/{did}").status_code == 401
    assert client.delete(f"/api/drawings/{did}", headers=bearer(user_token)).status_code == 200
    assert client.get(f"/api/drawings/{did}").status_code == 404
    assert not (settings.drawings_dir / f"{sha}.png").exists()
    assert not (settings.drawings_dir / f"{sha}.thumb.png").exists()
    assert client.delete(f"/api/drawings/{did2}", headers=bearer(admin_token)).status_code == 200


def test_reports_for_both_types(client, user_token, other_token, admin_token, midi_bytes):
    did = approved_drawing(client, user_token, admin_token, title="Signalé")
    r = client.post("/api/songs", headers=bearer(user_token), files={"file": ("m.mid", midi_bytes)})
    sid = r.json()["id"]
    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))

    r = client.post(f"/api/drawings/{did}/report", headers=bearer(other_token), json={"reason": "contenu choquant"})
    assert r.status_code == 201 and r.json()["target_type"] == "drawing" and r.json()["target_id"] == did
    drawing_report = r.json()["id"]
    assert client.post(f"/api/drawings/{did}/report", headers=bearer(other_token),
                       json={"reason": "encore"}).status_code == 409
    song_report = client.post(f"/api/songs/{sid}/report", headers=bearer(other_token), json={"reason": "x"}).json()["id"]
    assert client.post("/api/drawings/999/report", headers=bearer(other_token), json={"reason": "x"}).status_code == 404

    items = client.get("/api/admin/reports", headers=bearer(admin_token)).json()["items"]
    by_id = {x["id"]: x for x in items}
    assert by_id[drawing_report]["target_type"] == "drawing" and by_id[drawing_report]["target_title"] == "Signalé"
    assert by_id[drawing_report]["target_status"] == "approved" and by_id[drawing_report]["song_id"] is None
    assert by_id[song_report]["target_type"] == "song" and by_id[song_report]["target_id"] == sid
    only = client.get("/api/admin/reports?target_type=drawing", headers=bearer(admin_token)).json()["items"]
    assert [x["id"] for x in only] == [drawing_report]

    r = client.post(f"/api/admin/reports/{drawing_report}/resolve", headers=bearer(admin_token),
                    json={"action": "remove_drawing"})
    assert r.status_code == 200 and r.json()["drawing_removed"] is True and r.json()["song_removed"] is False
    assert client.get(f"/api/drawings/{did}").status_code == 404
    r = client.post(f"/api/admin/reports/{song_report}/resolve", headers=bearer(admin_token), json={"action": "dismiss"})
    assert r.json()["resolution"] == "dismiss" and r.json()["target_type"] == "song"
    assert client.get(f"/api/songs/{sid}").status_code == 200
    assert client.get("/api/admin/reports?open=1", headers=bearer(admin_token)).json()["items"] == []


def test_ban_and_account_deletion(client, user_token, other_token, admin_token, settings):
    kept = approved_drawing(client, user_token, admin_token, title="Gardé")
    pending = upload(client, user_token, make_png(color=(1, 1, 1))).json()
    client.post(f"/api/drawings/{kept}/like", headers=bearer(other_token))
    client.post(f"/api/drawings/{kept}/like", headers=bearer(user_token))
    r = client.delete("/api/me", headers=bearer(user_token))
    assert r.status_code == 200 and r.json()["drawings_kept"] == 1 and r.json()["drawings_deleted"] == 1
    assert not (settings.drawings_dir / f"{pending['sha256']}.png").exists()
    d = client.get(f"/api/drawings/{kept}").json()
    assert d["uploader_id"] is None and d["uploader_name"] == "Compte supprimé" and d["likes"] == 1

    other_pending = upload(client, other_token, make_png(color=(2, 2, 2))).json()["id"]
    assert client.post("/api/admin/users/2/ban", headers=bearer(admin_token)).status_code == 200
    rejected = client.get("/api/admin/drawings?status=rejected", headers=bearer(admin_token)).json()["items"]
    assert [x["id"] for x in rejected] == [other_pending] and rejected[0]["reject_reason"] == "ban"


def test_drawing_upload_limited_5_per_hour(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as c:
        tok, _ = login(c, "111")
        codes = [upload(c, tok, make_png(color=(i, 0, 0))).status_code for i in range(6)]
        assert codes[:5] == [201] * 5 and codes[5] == 429


def test_cells_stored_compressed(client, user_token, settings):
    did = upload(client, user_token, make_png(), cells=cells_for(150, 150)).json()["id"]
    conn = db.connect(settings)
    try:
        stored = conn.execute("SELECT cells_json_gz FROM drawings WHERE id=?", (did,)).fetchone()["cells_json_gz"]
    finally:
        conn.close()
    assert isinstance(stored, str) and len(stored) < len(cells_for(150, 150))
    body = client.get(f"/api/drawings/{did}/cells", headers=bearer(user_token)).json()
    assert body["w"] == 150 and len(body["cells"]) == 22500
