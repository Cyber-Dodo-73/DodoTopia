# -*- coding: utf-8 -*-
"""Durcissement cote client : nom de fichier assaini, sha256 revefifie, plafonds a l'ouverture d'un .mid.

Tout ce qui arrive du reseau (titre d'un autre joueur, contenu du .mid) est traite ici comme hostile.
L'isolation vient de tests_client/conftest.py : core.DATA_DIR et les dossiers ecrits par online.py sont
rediriges vers un tmp_path, rien n'est ecrit dans le projet.
"""
import hashlib
import os

import pytest

import core
import online
from helpers import FakePlayer, make_midi, wait_for

BIDI = "\u202e"          # RIGHT-TO-LEFT OVERRIDE : « innocent<BIDI>dim.exe » s'affiche « innocentexe.mid »
ZWSP = "\u200b"


# ---------------------------------------------------------------- nom de fichier assaini
def test_safe_song_filename_rejects_paths_and_reserved_names():
    for hostile, attendu in [
        ("..", "musique.mid"),
        ("../../evil", "evil.mid"),
        ("..\\..\\Windows\\System32\\evil", "evil.mid"),
        ("dossier/sous/fichier.mid", "fichier.mid"),
        ("CON", "_CON.mid"),
        ("con.mid", "_con.mid"),
        ("NUL.midi", "_NUL.mid"),
        ("COM1", "_COM1.mid"),
        ("LPT9.mid", "_LPT9.mid"),
        ("point final.  ", "point final.mid"),
        ('guille"met<>:|?*', "guillemet.mid"),
        ("", "musique.mid"),
        (None, "musique.mid"),
        ("   ", "musique.mid"),
        ("....", "musique.mid"),
        (ZWSP * 4, "musique.mid"),
        ("in" + BIDI + "nocent.exe", "innocent.exe.mid"),
        ("deux\nlignes", "deux lignes.mid"),
        ("nul\x00octet", "nuloctet.mid"),
    ]:
        assert core.safe_song_filename(hostile) == attendu, hostile
    long_name = core.safe_song_filename("x" * 500)
    assert len(long_name) == core.MAX_FILENAME_STEM + 4 and long_name.endswith(".mid")


def test_safe_join_stays_in_the_songs_folder(tmp_path):
    songs = tmp_path / "songs"
    songs.mkdir()
    base = os.path.realpath(str(songs))
    for hostile in ("../../../evil", "..\\..\\evil", "a/b/../../../c", "..", "CON", "normal"):
        path = core.safe_join(str(songs), hostile)
        assert os.path.realpath(path).startswith(base + os.sep), hostile
        assert os.path.dirname(os.path.realpath(path)) == base


def test_safe_join_refuses_a_name_that_escapes(tmp_path, monkeypatch):
    """Si l'assainissement laissait passer un separateur, safe_join le verrait par realpath et refuserait."""
    songs = tmp_path / "songs"
    songs.mkdir()
    monkeypatch.setattr(core, "safe_song_filename", lambda *a, **k: os.path.join("..", "echappe.mid"))
    with pytest.raises(ValueError, match="hors du dossier"):
        core.safe_join(str(songs), "peu importe")


def test_clean_display_text():
    assert core.clean_display_text("a\x00b\x1fc") == "abc"
    assert core.clean_display_text(f"a{BIDI}b{ZWSP}c") == "abc"
    assert core.clean_display_text("copie\r\nillegale") == "copie illegale"
    assert core.clean_display_text("  trop   d'espaces  ") == "trop d'espaces"
    assert core.clean_display_text(None) == "" and core.clean_display_text(ZWSP) == ""


def test_default_import_writes_a_sanitized_name_inside_songs(tmp_path):
    """Le titre vient d'un autre joueur : le fichier atterrit dans songs/ sous un nom sur."""
    player = FakePlayer(str(tmp_path))
    svc = online.OnlineService.__new__(online.OnlineService)
    svc.player = player
    src = str(tmp_path / "recu.mid")
    make_midi(src)
    base = os.path.realpath(player.songs_folder)
    for titre, attendu in [("../../evil", "evil.mid"), ("CON", "_CON.mid"),
                           (f"in{BIDI}nocent.exe", "innocent.exe.mid"), ("normal", "normal.mid")]:
        sid = svc._default_import(src, {"title": titre, "sha256": "a" * 64, "online_id": 1})
        assert sid == attendu, titre
        assert os.path.realpath(os.path.join(player.songs_folder, sid)).startswith(base + os.sep)
    # deuxieme import du meme titre : suffixe « (2) », toujours dans songs/
    assert svc._default_import(src, {"title": "normal"}) == "normal (2).mid"
    assert sorted(os.listdir(player.songs_folder)) == [
        "_CON.mid", "evil.mid", "innocent.exe.mid", "normal (2).mid", "normal.mid"]


# ---------------------------------------------------------------- sha256 reverifie
class _Srv:
    """Serveur minimal : sert `data` pour n'importe quel chemin, annonce `sha` dans la fiche du morceau."""

    def __init__(self, data, sha=None, title="Morceau"):
        self.data = data
        self.sha = hashlib.sha256(data).hexdigest() if sha is None else sha
        self.title = title
        self.downloads = []

    def get(self, path, params=None, timeout=5, auth=True):
        return {"id": 1, "sha256": self.sha, "title": self.title}

    def download(self, path, dest, expected_sha256=None, on_progress=None, timeout=60, max_bytes=None):
        self.downloads.append((path, dest))
        with open(dest, "wb") as f:
            f.write(self.data)
        got = hashlib.sha256(self.data).hexdigest()
        if expected_sha256 and got.lower() != str(expected_sha256).lower():
            online._unlink(dest)
            raise online.OnlineError("Fichier corrompu (empreinte différente de celle annoncée)")
        return got


def make_service(tmp_path, client):
    svc = online.OnlineService.__new__(online.OnlineService)
    svc.player = FakePlayer(str(tmp_path))
    svc.client = client
    svc.library = {"items": []}
    svc.jobs = {"downloads": {}, "uploads": {}}
    svc._lock = __import__("threading").RLock()
    svc.notify = lambda *a, **k: None
    svc.log = lambda *a, **k: None
    imported = []
    svc.import_file = lambda path, meta: (imported.append((path, meta)) or "importe.mid")
    svc._imported = imported
    return svc


def test_download_refuses_a_file_whose_sha256_does_not_match(tmp_path):
    """Le serveur annonce une empreinte et en envoie une autre : rien n'est importe."""
    srv = _Srv(make_midi(str(tmp_path / "vrai.mid")) and open(tmp_path / "vrai.mid", "rb").read(),
               sha="b" * 64)
    svc = make_service(tmp_path, srv)
    svc._download_run("1", svc.import_file)
    job = svc.jobs["downloads"]["1"]
    assert job["state"] == "error" and "corrompu" in job["error"]
    assert svc._imported == []
    assert not os.listdir(svc.player.songs_folder)
    assert not os.path.exists(os.path.join(online.DOWNLOADS_DIR, "b" * 64 + ".mid"))


def test_download_refuses_when_the_server_gives_no_sha256(tmp_path):
    srv = _Srv(b"MThd", sha="")
    svc = make_service(tmp_path, srv)
    svc._download_run("1", svc.import_file)
    job = svc.jobs["downloads"]["1"]
    assert job["state"] == "error" and "empreinte" in job["error"]
    assert srv.downloads == [] and svc._imported == []


def test_download_refuses_a_sha256_that_is_not_hexadecimal(tmp_path):
    """Une empreinte fantaisiste servirait aussi de nom de fichier temporaire : refusee avant tout."""
    for bogus in ("../../../evil", "a" * 63, "Z" * 64, "../" * 20 + "x"):
        srv = _Srv(b"MThd", sha=bogus)
        svc = make_service(tmp_path, srv)
        svc._download_run("1", svc.import_file)
        assert svc.jobs["downloads"]["1"]["state"] == "error"
        assert srv.downloads == []


def test_download_ok_passes_a_sanitized_title_to_the_import(tmp_path):
    make_midi(str(tmp_path / "vrai.mid"))
    data = open(tmp_path / "vrai.mid", "rb").read()
    srv = _Srv(data, title=f"../../CON{BIDI}.exe")
    svc = make_service(tmp_path, srv)
    svc._download_run("1", svc.import_file)
    assert svc.jobs["downloads"]["1"]["state"] == "done"
    path, meta = svc._imported[-1]
    assert meta["sha256"] == srv.sha and os.path.basename(path) == srv.sha + ".mid"
    # le titre transmis a l'import ne peut plus servir de chemin ni de nom de peripherique
    assert "/" not in meta["title"] and "\\" not in meta["title"] and ".." not in meta["title"]
    assert BIDI not in meta["title"] and meta["title"].upper() not in ("CON", "NUL")
    assert core.safe_song_filename(meta["title"]) == meta["title"] + ".mid"


def test_download_caps_the_file_size(tmp_path, monkeypatch):
    make_midi(str(tmp_path / "vrai.mid"))
    data = open(tmp_path / "vrai.mid", "rb").read()

    class Big(_Srv):
        def download(self, path, dest, expected_sha256=None, on_progress=None, timeout=60, max_bytes=None):
            assert max_bytes == online.SONG_MAX_BYTES, "le plafond de taille doit etre transmis"
            raise online.OnlineError("Fichier trop gros (plus de 8192 Ko)")

    svc = make_service(tmp_path, Big(data))
    svc._download_run("1", svc.import_file)
    assert svc.jobs["downloads"]["1"]["state"] == "error"
    assert "trop gros" in svc.jobs["downloads"]["1"]["error"]


def test_client_download_stops_past_max_bytes(tmp_path):
    """Plafond applique dans OnlineClient.download lui-meme (serveur bavard, Content-Length menteur)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            try:
                for _ in range(200):
                    self.wfile.write(b"\x00" * 65536)
            except OSError:
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = online.OnlineClient(f"http://127.0.0.1:{srv.server_address[1]}")
        dest = str(tmp_path / "flux.bin")
        with pytest.raises(online.OnlineError, match="trop gros"):
            c.download("/flux", dest, None, None, max_bytes=256 * 1024)
        assert not os.path.exists(dest) and not os.path.exists(dest + ".part")
    finally:
        srv.shutdown()


def test_upload_filename_is_ascii_and_quote_free(tmp_path):
    """Un nom local avec guillemet ou retour a la ligne ne doit pas casser l'en-tete multipart envoye."""
    sent = {}

    class C(online.OnlineClient):
        def request(self, method, path, json_body=None, params=None, headers=None, timeout=60, data=None):
            sent["body"] = data
            return {}

    c = C("http://x")
    for name in (chr(34) + "llemet.mid", "deux lignes.mid", "accentue.mid", "..mid", "CON.mid"):
        path = tmp_path / name
        try:
            path.write_bytes(b"MThd1234")
        except OSError:
            continue        # nom refuse par le systeme de fichiers : rien a tester ici
        c.upload("/api/songs", {"title": "t"}, "file", str(path))
        body = sent["body"].decode("latin-1")
        assert body.count(chr(34) + "filename=" + chr(34)) <= 1
        fname = body.split("filename=" + chr(34))[1].split(chr(34))[0]
        assert fname.isascii() and not set(fname) & {chr(13), chr(10), chr(34), ";"}, name
        assert fname and fname[-1] not in " ."


# ---------------------------------------------------------------- plafonds a l'ouverture
def midi_bomb(path, n_events=300_000):
    """Fichier MIDI valide mais demesure : running status, 3 octets par evenement."""
    out = bytearray(b"\x00\xff\x51\x03\x07\xa1\x20")
    for i in range(n_events // 2):
        note = 60 + i % 12
        out += b"\x00" + (b"" if i else b"\x90") + bytes([note, 80])
        out += b"\x10" + bytes([note, 0])
    out += b"\x00\xff\x2f\x00"
    data = (b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + (1).to_bytes(2, "big")
            + (480).to_bytes(2, "big") + b"MTrk" + len(out).to_bytes(4, "big") + bytes(out))
    with open(path, "wb") as f:
        f.write(data)
    return path


def test_parse_midi_refuses_a_non_midi_file(tmp_path):
    p = tmp_path / "faux.mid"
    p.write_bytes(b"MZ\x90\x00 ceci est un executable")
    with pytest.raises(core.MidiRefused, match="MThd"):
        core.parse_midi(str(p), {})
    assert core.midi_duration(str(p)) == 0.0


def test_parse_midi_refuses_too_many_events(tmp_path):
    p = midi_bomb(str(tmp_path / "bombe.mid"))
    assert os.path.getsize(p) < core.MAX_MIDI_BYTES
    with pytest.raises(core.MidiRefused, match="trop charg"):
        core.parse_midi(p, {})


def test_parse_midi_refuses_a_huge_file(tmp_path, monkeypatch):
    p = tmp_path / "enorme.mid"
    p.write_bytes(b"MThd" + b"\x00" * 5000)
    monkeypatch.setattr(core, "MAX_MIDI_BYTES", 1024)
    with pytest.raises(core.MidiRefused, match="trop gros"):
        core.parse_midi(str(p), {})


def test_parse_midi_still_reads_a_normal_file(tmp_path):
    p = make_midi(str(tmp_path / "ok.mid"))
    grouped = core.parse_midi(p, {})
    assert len(grouped) == 8 and core.midi_duration(p) > 0


def test_parse_midi_refusal_is_a_value_error(tmp_path):
    """MidiRefused derive de ValueError : les appelants qui attrapent large restent corrects."""
    p = tmp_path / "faux.mid"
    p.write_bytes(b"pas du midi")
    assert issubclass(core.MidiRefused, ValueError)
    with pytest.raises(ValueError):
        core.parse_midi(str(p), {})


# ---------------------------------------------------------------- morceau du salon
def test_room_refuses_a_song_whose_sha256_does_not_match(tmp_path):
    """Le fichier du salon est reverifie a l'arrivee : un contenu different est refuse, rien n'est importe."""
    from test_room import Env

    env = Env(tmp_path)
    try:
        env.lobby()
        vrai = env.B.client.download

        def menteur(path, dest, expected_sha256=None, on_progress=None, timeout=60, max_bytes=None):
            with open(dest, "wb") as f:      # contenu substitue, aucune erreur signalee a l'appelant
                f.write(b"MThd" + bytes(100))
            return hashlib.sha256(b"autre chose").hexdigest()

        env.B.client.download = menteur
        assert env.A.set_song("morceau.mid")
        wait_for(lambda: "indisponible" in (env.B.message or ""), timeout=5, what="B refuse le fichier")
        assert env.B._have is None
        assert os.listdir(env.pB.songs_folder) == []
        assert any("indisponible" in m for _k, m in env.notes["B"])
        env.B.client.download = vrai
    finally:
        env.close()


def test_room_refuses_an_invalid_sha256_without_downloading(tmp_path):
    from test_room import Env

    env = Env(tmp_path)
    try:
        env.lobby()
        before = list(env.B.client.downloads)
        env.B._ensure_run({"sha256": "../../evil", "name": "x", "key_shift": 0, "source": "room"},
                          env.B._ensure_gen)
        assert env.B.client.downloads == before
        assert "invalide" in (env.B.message or "")
        assert os.listdir(env.pB.songs_folder) == []
    finally:
        env.close()
