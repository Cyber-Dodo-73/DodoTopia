"""Bibliothèque : dépôt, validation, modération, téléchargement, signalements."""
import hashlib

import pytest
from conftest import bearer, login, make_client, make_midi, make_settings

from app.library import MidiError, clean_title, validate_midi


def upload(client, token, data, name="Mon-Morceau-Anonymous-nonstop2k.com.mid", **fields):
    return client.post("/api/songs", headers=bearer(token), files={"file": (name, data, "audio/midi")}, data=fields)


def test_validate_midi_and_clean_title(midi_bytes, bad_midi_bytes):
    info = validate_midi(midi_bytes)
    assert info["note_count"] == 20 and 4.5 <= info["duration_s"] <= 5.5
    for bad in (bad_midi_bytes, make_midi(n_notes=5), make_midi(n_notes=1, tick=100)):
        try:
            validate_midi(bad)
        except MidiError:
            pass
        else:
            raise AssertionError("fichier invalide accepté")
    assert clean_title("The-Weeknd-Blinding-Lights-Anonymous-20201231-nonstop2k.com.mid") == "The Weeknd Blinding Lights"
    assert clean_title("x.mid.mid") == "x"


def test_upload_pending_approve_download(client, user_token, admin_token, midi_bytes, settings):
    assert client.post("/api/songs", files={"file": ("a.mid", midi_bytes)}).status_code == 401

    r = upload(client, user_token, midi_bytes)
    assert r.status_code == 201, r.text
    song = r.json()
    sid = song["id"]
    assert song["status"] == "pending" and song["title"] == "Mon Morceau" and song["note_count"] == 20
    sha = hashlib.sha256(midi_bytes).hexdigest()
    assert song["sha256"] == sha and (settings.songs_dir / f"{sha}.mid").is_file()

    # invisible au public tant que pending, visible pour l'uploader et l'admin
    assert client.get("/api/songs").json()["total"] == 0
    assert client.get(f"/api/songs/{sid}").status_code == 404
    assert client.get(f"/api/songs/{sid}", headers=bearer(user_token)).status_code == 200
    assert client.get(f"/api/songs/{sid}/download").status_code == 404

    r = client.get("/api/admin/songs?status=pending", headers=bearer(admin_token))
    assert r.status_code == 200 and [s["id"] for s in r.json()["items"]] == [sid]
    assert client.get("/api/admin/songs", headers=bearer(user_token)).status_code == 403

    r = client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    assert r.status_code == 200 and r.json()["status"] == "approved"

    lst = client.get("/api/songs?q=morceau&sort=title").json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == sid and lst["pages"] == 1
    assert client.get("/api/songs?q=inexistant").json()["total"] == 0

    r = client.get(f"/api/songs/{sid}/download")
    assert r.status_code == 200 and r.content == midi_bytes
    assert r.headers["etag"] == f'"{sha}"'
    assert client.get(f"/api/songs/{sid}").json()["downloads"] == 1


def test_duplicate_invalid_too_large(client, user_token, midi_bytes, bad_midi_bytes, tmp_path):
    assert upload(client, user_token, midi_bytes).status_code == 201
    r = upload(client, user_token, midi_bytes, name="copie.mid")
    assert r.status_code == 409 and r.json()["detail"]["existing_id"] == 1

    r = upload(client, user_token, bad_midi_bytes, name="pas.mid")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_midi"

    with make_client(make_settings(tmp_path / "small", MAX_MIDI_BYTES=300)) as c:
        tok, _ = login(c, "111")
        r = upload(c, tok, make_midi(n_notes=60), name="gros.mid")
        assert r.status_code == 413


def test_patch_delete_rights(client, user_token, other_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    r = client.patch(f"/api/songs/{sid}", headers=bearer(user_token), json={"title": "Nouveau", "artist": "X"})
    assert r.status_code == 200 and r.json()["title"] == "Nouveau" and r.json()["artist"] == "X"
    assert client.patch(f"/api/songs/{sid}", headers=bearer(other_token), json={"title": "Pas moi"}).status_code == 403
    assert client.delete(f"/api/songs/{sid}", headers=bearer(other_token)).status_code == 403

    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    # une fois validé, l'uploader ne modifie plus, l'admin oui
    assert client.patch(f"/api/songs/{sid}", headers=bearer(user_token), json={"title": "Encore"}).status_code == 403
    assert client.patch(f"/api/songs/{sid}", headers=bearer(admin_token), json={"title": "Admin"}).status_code == 200
    assert client.delete(f"/api/songs/{sid}", headers=bearer(admin_token)).status_code == 200
    assert client.get(f"/api/songs/{sid}", headers=bearer(admin_token)).status_code == 404


def test_reject_with_reason(client, user_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    r = client.post(f"/api/admin/songs/{sid}/reject", headers=bearer(admin_token), json={"reason": "doublon"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["reject_reason"] == "doublon"
    assert client.get("/api/songs").json()["total"] == 0


def test_report_and_resolve_remove_song(client, user_token, other_token, admin_token, midi_bytes, settings):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    r = client.post(f"/api/songs/{sid}/report", headers=bearer(other_token), json={"reason": "contenu"})
    assert r.status_code == 201
    rid = r.json()["id"]
    r = client.post(f"/api/songs/{sid}/report", headers=bearer(other_token), json={"reason": "encore"})
    assert r.status_code == 409

    r = client.get("/api/admin/reports?open=1", headers=bearer(admin_token))
    assert [x["id"] for x in r.json()["items"]] == [rid]
    assert r.json()["items"][0]["song_title"] == "Mon Morceau"

    r = client.post(f"/api/admin/reports/{rid}/resolve", headers=bearer(admin_token), json={"action": "remove_song"})
    assert r.status_code == 200 and r.json()["song_removed"] is True
    assert client.get(f"/api/songs/{sid}").status_code == 404
    assert client.get("/api/admin/reports?open=1", headers=bearer(admin_token)).json()["items"] == []
    sha = hashlib.sha256(midi_bytes).hexdigest()
    assert not (settings.songs_dir / f"{sha}.mid").exists()


def test_resolve_dismiss(client, user_token, other_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    rid = client.post(f"/api/songs/{sid}/report", headers=bearer(other_token), json={"reason": "x"}).json()["id"]
    r = client.post(f"/api/admin/reports/{rid}/resolve", headers=bearer(admin_token), json={"action": "dismiss"})
    assert r.status_code == 200 and r.json()["resolution"] == "dismiss"
    assert client.get("/api/admin/reports?open=1", headers=bearer(admin_token)).json()["items"] == []
    assert len(client.get("/api/admin/reports?open=0", headers=bearer(admin_token)).json()["items"]) == 1
    assert client.get(f"/api/songs/{sid}").status_code == 200


def test_ban_user(client, user_token, admin_token, midi_bytes):
    upload(client, user_token, midi_bytes)
    r = client.post("/api/admin/users/1/ban", headers=bearer(admin_token))
    assert r.status_code == 200
    assert client.get("/api/me", headers=bearer(user_token)).status_code == 401
    r = client.get("/api/admin/songs?status=rejected", headers=bearer(admin_token))
    assert r.json()["total"] == 1
    # un banni ne peut plus se reconnecter
    with pytest.raises(AssertionError):
        login(client, "111")
    # impossible de bannir un admin
    assert client.post("/api/admin/users/2/ban", headers=bearer(admin_token)).status_code == 403
