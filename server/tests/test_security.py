"""Durcissement autour des .mid partagés entre joueurs.

Un joueur dépose, un autre télécharge et ouvre : chaque test ci-dessous décrit une manière de faire du
fichier, de son titre ou de son nom une arme, et vérifie que le serveur la refuse.
"""
import hashlib

import pytest
from conftest import bearer, login, make_client, make_midi, make_settings

from app.library import MidiError, clean_title, content_disposition, safe_ascii_filename, scan_midi, validate_midi
from app.schemas import clean_text

BIDI = "\u202e"          # RIGHT-TO-LEFT OVERRIDE : déguise la fin d'un nom de fichier
ZWSP = "\u200b"          # espace de largeur nulle : deux titres visuellement identiques


# --- fabriques de fichiers MIDI hostiles -----------------------------------------

def header(fmt=1, ntrks=1, division=480):
    return (b"MThd" + (6).to_bytes(4, "big") + fmt.to_bytes(2, "big")
            + ntrks.to_bytes(2, "big") + division.to_bytes(2, "big"))


def track(payload: bytes) -> bytes:
    return b"MTrk" + len(payload).to_bytes(4, "big") + payload


def notes_payload(n: int, running_status: bool = True) -> bytes:
    """n couples note_on/note_off. En running status, un évènement ne coûte que 3 octets."""
    out = bytearray(b"\x00\xff\x51\x03\x07\xa1\x20")     # set_tempo 500000
    for i in range(n):
        note = 60 + i % 12
        out += b"\x00" + (b"" if running_status and i else b"\x90") + bytes([note, 80])
        out += b"\x60" + (b"" if running_status else b"\x90") + bytes([note, 0])
    out += b"\x00\xff\x2f\x00"
    return bytes(out)


def midi(fmt=1, division=480, n=20, ntrks=1):
    return header(fmt, ntrks, division) + track(notes_payload(n))


def upload(client, token, data, name="morceau.mid", **fields):
    return client.post("/api/songs", headers=bearer(token), files={"file": (name, data, "audio/midi")}, data=fields)


# --- 1. injection d'en-tête HTTP au téléchargement --------------------------------

def test_content_disposition_never_injectable():
    """Guillemet, CRLF, point-virgule, caractères non-ASCII : rien ne sort du cadre de l'en-tête."""
    sha = "ab" * 32
    for hostile in ['x" ; filename="evil.exe', "a\r\nX-Injecté: 1", "titre\nsur\ndeux lignes",
                    "Chanson à l'accent ♪", BIDI + "gnp.exe", "../../etc/passwd", "CON", "." * 40, ""]:
        cd = content_disposition(hostile, sha)
        assert "\r" not in cd and "\n" not in cd
        ascii_part = cd.split('filename="', 1)[1].split('"', 1)[0]
        assert ascii_part.isascii() and '"' not in ascii_part and ";" not in ascii_part
        assert "/" not in ascii_part and "\\" not in ascii_part and ".." not in ascii_part
        assert ascii_part.endswith(".mid") and ascii_part.upper()[:-4] not in ("CON", "NUL", "PRN")
        ext = cd.split("filename*=UTF-8''", 1)[1]
        assert ext.isascii() and '"' not in ext and ";" not in ext and " " not in ext
        # la forme étendue est intégralement percent-encodée : aucun octet brut de l'utilisateur
        assert all(c.isalnum() or c in "%-._~" for c in ext)


def test_download_header_of_hostile_title(client, user_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes, title='pwn" ; filename="virus.exe').json()["id"]
    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    r = client.get(f"/api/songs/{sid}/download")
    assert r.status_code == 200 and r.content == midi_bytes
    cd = r.headers["content-disposition"]
    # le guillemet et le point-virgule du titre ont disparu : un seul paramètre filename, un seul filename*
    assert cd.startswith('attachment; filename="') and cd.count("filename=") == 1
    assert cd.count("filename*=") == 1 and not set(cd) & {chr(13), chr(10)}
    ascii_part = cd.split('filename="', 1)[1].split('"', 1)[0]
    assert ascii_part == "pwn filenamevirus.exe.mid"   # texte inoffensif, plus aucune syntaxe d'en-tête
    assert r.headers["x-sha256"] == hashlib.sha256(midi_bytes).hexdigest()


def test_title_with_newlines_is_stored_on_one_line(client, user_token, midi_bytes):
    song = upload(client, user_token, midi_bytes, title="Ligne 1\r\nLigne 2\tsuite").json()
    assert song["title"] == "Ligne 1 Ligne 2 suite"


# --- 6. texte affiché : bidi, largeur nulle, longueur ----------------------------

def test_bidi_and_zero_width_are_stripped_everywhere(client, user_token, other_token, admin_token, midi_bytes):
    song = upload(client, user_token, midi_bytes,
                  title=f"innocent{BIDI}dim.exe", artist=f"Anon{ZWSP}yme").json()
    sid = song["id"]
    assert BIDI not in song["title"] and song["title"] == "innocentdim.exe"
    assert song["artist"] == "Anonyme"

    r = client.patch(f"/api/songs/{sid}", headers=bearer(user_token), json={"title": f"{BIDI}re{ZWSP}nommé"})
    assert r.status_code == 200 and r.json()["title"] == "renommé"
    # un titre entièrement composé d'invisible ne remplace pas le titre existant
    assert client.patch(f"/api/songs/{sid}", headers=bearer(user_token),
                        json={"title": ZWSP * 5}).json()["title"] == "renommé"

    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    r = client.post(f"/api/songs/{sid}/report", headers=bearer(other_token), json={"reason": f"vol{BIDI}\n"})
    assert r.status_code == 201
    reports = client.get("/api/admin/reports", headers=bearer(admin_token)).json()["items"]
    assert reports[0]["reason"] == "vol"
    r = client.post(f"/api/admin/songs/{sid}/reject", headers=bearer(admin_token),
                    json={"reason": f"copie{BIDI}\r\nillégale"})
    assert r.json()["reject_reason"] == "copie illégale"


def test_clean_text_unit():
    assert clean_text("a\x00b\x1fc") == "abc"
    assert clean_text(f"a{BIDI}b\u2066c\u2069") == "abc"
    assert clean_text("  trop   d'espaces \t ") == "trop d'espaces"
    assert clean_text("x" * 500) == "x" * 120
    assert clean_text(None) == "" and clean_text(ZWSP) == ""


def test_uploader_name_is_cleaned(client, monkeypatch):
    from app import auth
    monkeypatch.setattr(auth, "discord_fetch_user",
                        lambda access: {"id": "777", "username": "bob", "global_name": f"Bo{BIDI}b\n", "avatar": None})
    token, user = login(client, "777")
    assert user["username"] == "Bob"


# --- 3. contenu réellement MIDI ---------------------------------------------------

def test_non_midi_disguised_as_mid(client, user_token):
    for payload in (b"MZ\x90\x00" + b"\x00" * 200, b"<html>hello</html>" * 20, b"\x00" * 4000,
                    b"RIFF\x24\x00\x00\x00WAVEfmt "):
        r = upload(client, user_token, payload, name="innocent.mid")
        assert r.status_code == 422, payload[:8]
        assert r.json()["detail"]["code"] == "invalid_midi"
        assert "MThd" in r.json()["detail"]["message"] or "illisible" in r.json()["detail"]["message"]


def test_midi_type_2_refused(client, user_token):
    r = upload(client, user_token, midi(fmt=2, n=40), name="type2.mid")
    assert r.status_code == 422 and "type 0 ou 1" in r.json()["detail"]["message"]
    with pytest.raises(MidiError):
        scan_midi(midi(fmt=2, n=40))


def test_zero_division_refused(client, user_token):
    r = upload(client, user_token, midi(division=0, n=40), name="div0.mid")
    assert r.status_code == 422 and "Division nulle" in r.json()["detail"]["message"]


def test_smpte_division():
    scan_midi(header(1, 1, 0xE728) + track(notes_payload(20)))          # -25 im/s, 40 ticks : valide
    for bad in (0x8000, 0xE000, 0xFF00):
        with pytest.raises(MidiError, match="SMPTE"):
            scan_midi(header(1, 1, bad) + track(notes_payload(20)))


def test_type_0_with_several_tracks_refused():
    with pytest.raises(MidiError, match="type 0"):
        scan_midi(header(0, 2) + track(notes_payload(20)) + track(notes_payload(20)))


def test_too_many_tracks_refused(client, user_token, tmp_path):
    data = header(1, 8) + b"".join(track(notes_payload(3)) for _ in range(8))
    with pytest.raises(MidiError, match="pistes"):
        scan_midi(data, scan_midi.__defaults__[0]._replace(max_tracks=4))
    with make_client(make_settings(tmp_path / "t", MAX_MIDI_TRACKS=4)) as c:
        tok, _ = login(c, "111")
        r = upload(c, tok, data, name="pistes.mid")
        assert r.status_code == 422 and "piste" in r.json()["detail"]["message"]


def test_too_many_events_refused(tmp_path):
    """Un fichier en running status : 3 octets par évènement, des centaines de milliers dans 2 Mo."""
    hostile = header(1, 1) + track(notes_payload(60_000))
    assert len(hostile) < 2 * 1024 * 1024
    with pytest.raises(MidiError, match="évènements"):
        scan_midi(hostile, scan_midi.__defaults__[0]._replace(max_events=1000))
    with make_client(make_settings(tmp_path / "ev", MAX_MIDI_EVENTS=1000)) as c:
        tok, _ = login(c, "111")
        r = upload(c, tok, hostile, name="bombe.mid")
        assert r.status_code == 422 and "évènements" in r.json()["detail"]["message"]


def test_too_many_notes_refused(tmp_path):
    hostile = header(1, 1) + track(notes_payload(5000))
    with pytest.raises(MidiError, match="notes"):
        scan_midi(hostile, scan_midi.__defaults__[0]._replace(max_notes=100))


def test_default_limits_reject_a_real_bomb():
    """Sans réglage particulier : 200 000 évènements (~600 Ko) sont refusés avec les plafonds par défaut."""
    with pytest.raises(MidiError, match="évènements"):
        validate_midi(header(1, 1) + track(notes_payload(200_000)))


def test_truncated_and_malformed_files_refused():
    good = midi(n=20)
    for bad in (good[:10], good[:40], b"MThd" + (2).to_bytes(4, "big") + b"\x00\x01",
                header(1, 1) + b"MTrk" + (50).to_bytes(4, "big") + b"\x40\x40\x40",
                header(1, 0) + track(notes_payload(20))):
        with pytest.raises(MidiError):
            scan_midi(bad)


def test_running_status_without_status_refused():
    with pytest.raises(MidiError, match="statut courant"):
        scan_midi(header(1, 1) + track(b"\x00\x40\x40" * 20))


def test_valid_file_still_accepted(midi_bytes):
    info = scan_midi(midi_bytes)
    assert info["type"] == 1 and info["tracks"] == 1 and info["note_count"] == 20
    assert validate_midi(midi_bytes)["note_count"] == 20
    assert scan_midi(midi(fmt=0, n=30))["note_count"] == 30
    # running status et statut explicite donnent le même compte
    assert scan_midi(header(1, 1) + track(notes_payload(40, running_status=False)))["note_count"] == 40


# --- 4. refus sans résidu sur disque ----------------------------------------------

def test_refused_uploads_leave_no_file(client, user_token, settings):
    for data, name in ((b"pas du midi", "a.mid"), (midi(fmt=2, n=40), "b.mid"),
                       (midi(division=0, n=40), "c.mid"), (b"", "d.mid")):
        assert upload(client, user_token, data, name=name).status_code in (413, 422)
    assert not settings.songs_dir.exists() or list(settings.songs_dir.glob("*")) == []
    assert not settings.tmp_dir.exists() or list(settings.tmp_dir.glob("*")) == []


def test_too_large_upload_refused(tmp_path):
    with make_client(make_settings(tmp_path / "small", MAX_MIDI_BYTES=4096)) as c:
        tok, _ = login(c, "111")
        r = upload(c, tok, make_midi(n_notes=2000), name="gros.mid")
        assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"


def test_oversized_body_is_cut_before_parsing(tmp_path):
    """Le corps est coupé au niveau ASGI : Starlette ne déverse pas des mégaoctets sur le disque d'abord."""
    settings = make_settings(tmp_path / "cap", MAX_MIDI_BYTES=4096, ROOM_SONG_MAX_BYTES=4096,
                             REQUEST_OVERHEAD_BYTES=1024)
    with make_client(settings) as c:
        tok, _ = login(c, "111")
        r = upload(c, tok, b"\x00" * (settings.max_request_bytes + 10_000), name="enorme.mid")
        assert r.status_code in (400, 413)
        assert not settings.songs_dir.exists() or list(settings.songs_dir.glob("*")) == []


# --- 2. traversée de chemin et noms de fichiers ----------------------------------

def test_path_traversal_in_upload_filename(client, user_token, midi_bytes, settings, tmp_path):
    hostile = "../../../../Windows/System32/evil.mid"
    song = upload(client, user_token, midi_bytes, name=hostile).json()
    sha = hashlib.sha256(midi_bytes).hexdigest()
    # le fichier est nommé par son empreinte, le nom envoyé n'est que du texte (et nettoyé)
    assert (settings.songs_dir / f"{sha}.mid").is_file()
    assert list(settings.songs_dir.glob("*")) == [settings.songs_dir / f"{sha}.mid"]
    assert "/" not in song["original_name"] and ".." not in song["original_name"]
    assert song["original_name"] == "evil.mid"
    assert not (tmp_path / "Windows").exists()


def test_safe_ascii_filename_unit():
    assert safe_ascii_filename("../../etc/passwd", "x") == "etcpasswd.mid"
    assert safe_ascii_filename("CON", "x") == "x.mid"
    assert safe_ascii_filename("", "fallback") == "fallback.mid"
    assert safe_ascii_filename("a" * 200, "x") == "a" * 80 + ".mid"
    assert safe_ascii_filename("fin.  ", "x") == "fin.mid"
    assert clean_title("The-Weeknd-Anonymous-nonstop2k.com.mid") == "The Weeknd"


# --- 7. abus de dépôt : bannis, morceaux non validés, limites de débit -------------

def test_pending_song_is_not_served_to_a_third_party(client, user_token, other_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    for who in (None, other_token):
        h = bearer(who) if who else {}
        assert client.get(f"/api/songs/{sid}", headers=h).status_code == 404
        assert client.get(f"/api/songs/{sid}/download", headers=h).status_code == 404
    # l'auteur et l'admin, eux, y ont accès
    assert client.get(f"/api/songs/{sid}/download", headers=bearer(user_token)).status_code == 200
    assert client.get(f"/api/songs/{sid}/download", headers=bearer(admin_token)).status_code == 200


def test_rejected_song_is_not_served_to_a_third_party(client, user_token, other_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    client.post(f"/api/admin/songs/{sid}/reject", headers=bearer(admin_token), json={"reason": "copie"})
    assert client.get(f"/api/songs/{sid}/download", headers=bearer(other_token)).status_code == 404
    assert client.get(f"/api/songs/{sid}/download").status_code == 404
    assert client.get(f"/api/songs/{sid}/download", headers=bearer(user_token)).status_code == 200
    # un morceau non approuvé ne fait pas monter le compteur de téléchargements
    assert client.get(f"/api/songs/{sid}", headers=bearer(user_token)).json()["downloads"] == 0


def test_banned_user_cannot_upload_or_report(client, user_token, other_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    assert client.post("/api/admin/users/1/ban", headers=bearer(admin_token)).status_code == 200
    r = upload(client, user_token, make_midi(n_notes=30), name="apres-ban.mid")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unauthorized"
    assert client.post(f"/api/songs/{sid}/report", headers=bearer(user_token),
                       json={"reason": "x"}).status_code == 401
    assert client.patch(f"/api/songs/{sid}", headers=bearer(user_token), json={"title": "x"}).status_code == 401
    assert client.delete(f"/api/songs/{sid}", headers=bearer(user_token)).status_code == 401


def test_upload_and_report_are_rate_limited(tmp_path):
    with make_client(make_settings(tmp_path / "rl", RATE_LIMIT=1)) as c:
        tok, _ = login(c, "111")
        codes = [upload(c, tok, make_midi(n_notes=12 + i), name=f"m{i}.mid").status_code for i in range(12)]
        assert 429 in codes and codes.count(201) <= 10


# --- 8. morceau éphémère d'un salon ------------------------------------------------

def room_code(client, token):
    ws = client.websocket_connect("/ws")
    ws.__enter__()
    ws.send_json({"type": "create", "token": token, "name": "A", "instrument": "piano", "version": "1.7.0"})
    code = ws.receive_json()["room_code"]
    ws.receive_json()
    return ws, code


def test_room_song_validated_like_the_library(client, user_token, settings):
    ws, code = room_code(client, user_token)
    try:
        for data in (b"pas du midi", midi(fmt=2, n=40), midi(division=0, n=40)):
            r = client.post(f"/api/rooms/{code}/song", headers=bearer(user_token),
                            files={"file": ("x.mid", data)})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_midi"
        assert not settings.tmp_dir.exists() or list(settings.tmp_dir.glob("*")) == []
    finally:
        ws.__exit__(None, None, None)


def test_room_file_is_not_shared_with_another_room(client, user_token, other_token, midi_bytes):
    """Connaître un sha256 ne suffit pas : le fichier n'est servi qu'aux membres du salon où il a été déposé."""
    wsa, code_a = room_code(client, user_token)
    wsb, code_b = room_code(client, other_token)
    try:
        r = client.post(f"/api/rooms/{code_a}/song", headers=bearer(user_token),
                        files={"file": ("m.mid", midi_bytes)})
        assert r.status_code == 201
        sha = r.json()["sha256"]
        assert client.get(f"/api/rooms/{code_a}/song/{sha}", headers=bearer(user_token)).status_code == 200
        # membre d'un autre salon : le fichier existe sur le disque mais ne lui est pas servi
        assert client.get(f"/api/rooms/{code_b}/song/{sha}", headers=bearer(other_token)).status_code == 404
        # non membre du salon A
        assert client.get(f"/api/rooms/{code_a}/song/{sha}", headers=bearer(other_token)).status_code == 403
        assert client.get(f"/api/rooms/{code_a}/song/{sha}").status_code == 401
    finally:
        wsa.__exit__(None, None, None)
        wsb.__exit__(None, None, None)


def test_room_song_download_name_is_the_hash(client, user_token, midi_bytes):
    ws, code = room_code(client, user_token)
    try:
        sha = client.post(f"/api/rooms/{code}/song", headers=bearer(user_token),
                          files={"file": ('ev"il\n.mid', midi_bytes)}).json()["sha256"]
        r = client.get(f"/api/rooms/{code}/song/{sha}", headers=bearer(user_token))
        cd = r.headers["content-disposition"]
        assert cd == f'attachment; filename="{sha[:12]}.mid"'
        assert "\n" not in cd and r.content == midi_bytes
    finally:
        ws.__exit__(None, None, None)


def test_banned_user_cannot_use_room_files(client, user_token, admin_token, midi_bytes):
    ws, code = room_code(client, user_token)
    try:
        sha = client.post(f"/api/rooms/{code}/song", headers=bearer(user_token),
                          files={"file": ("m.mid", midi_bytes)}).json()["sha256"]
        client.post("/api/admin/users/1/ban", headers=bearer(admin_token))
        assert client.post(f"/api/rooms/{code}/song", headers=bearer(user_token),
                           files={"file": ("m2.mid", make_midi(n_notes=30))}).status_code == 401
        assert client.get(f"/api/rooms/{code}/song/{sha}", headers=bearer(user_token)).status_code == 401
    finally:
        ws.__exit__(None, None, None)
