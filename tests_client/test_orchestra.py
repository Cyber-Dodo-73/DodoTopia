"""Orchestre : résumé des pistes, répartition automatique, et chaque joueur ne prépare que sa partie."""
import os

import mido
import pytest

import orchestra
from helpers import FakeInstrument, wait_for
from test_room import Env


def multi_track_midi(path):
    """Type 1 : piste 0 = tempo, 1 = mélodie aiguë, 2 = basse, 3 = batterie (canal 10)."""
    mid = mido.MidiFile(type=1)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    mid.tracks.append(t0)
    for name, notes, ch in (("Melodie", (76, 79, 81, 84), 0), ("Basse", (36, 40, 43, 36), 1), ("Batterie", (36, 38), 9)):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        for n in notes:
            tr.append(mido.Message("note_on", note=n, velocity=90, channel=ch, time=0))
            tr.append(mido.Message("note_off", note=n, velocity=0, channel=ch, time=240))
        mid.tracks.append(tr)
    mid.save(path)
    return path


def test_resume_des_pistes(tmp_path):
    tracks = orchestra.track_summary(multi_track_midi(str(tmp_path / "o.mid")))
    assert [t["index"] for t in tracks] == [1, 2, 3], "la piste de tempo sans note n'apparait pas"
    mel, bass, drums = tracks
    assert mel["name"] == "Melodie" and (mel["low"], mel["high"]) == (76, 84) and mel["mean"] == 80.0
    assert bass["notes"] == 4 and not bass["drums"] and drums["drums"]


TRACKS = [{"index": 1, "name": "Mélodie", "notes": 100, "mean": 80.0},
          {"index": 2, "name": "Contrechant", "notes": 80, "mean": 67.0},
          {"index": 3, "name": "Basse", "notes": 60, "mean": 43.0},
          {"index": 4, "name": "Batterie", "notes": 200, "drums": True}]


def seat(i, lo, hi, perc=False):
    return {"id": i, "low": lo, "high": hi, "percussive": perc}


def test_la_piste_la_plus_aigue_au_registre_le_plus_aigu():
    parts = orchestra.propose(TRACKS, [seat(1, 36, 60), seat(2, 60, 96), seat(3, 48, 72)])
    assert parts[2]["tracks"] == [1] and parts[3]["tracks"] == [2] and parts[1]["tracks"] == [3]
    assert all(p["octave"] is None for p in parts.values())


def test_moins_de_joueurs_que_de_pistes_tout_est_joue():
    parts = orchestra.propose(TRACKS, [seat(1, 60, 96), seat(2, 36, 60)])
    played = sorted(i for p in parts.values() for i in p["tracks"])
    assert played == [1, 2, 3], "chaque piste mélodique est jouée, jamais la batterie par un instrument à hauteur"
    assert parts[1]["tracks"][0] == 1 and parts[2]["tracks"][-1] == 3


def test_plus_de_joueurs_que_de_pistes_doublage():
    two = TRACKS[:1] + TRACKS[2:3]
    parts = orchestra.propose(two, [seat(i, 40 + 6 * i, 70 + 6 * i) for i in range(1, 6)])
    assert {tuple(p["tracks"]) for p in parts.values()} == {(1,), (3,)}
    assert len(parts) == 5


def test_percussions_et_morceau_sans_piste():
    parts = orchestra.propose(TRACKS, [seat(1, 60, 96), seat(2, 0, 0, perc=True)])
    assert parts[2]["tracks"] == [4]
    assert orchestra.propose([], [seat(1, 60, 96)]) == {}


def test_libelle_de_partie():
    assert orchestra.part_label(TRACKS, {"tracks": [1, 3]}) == "Mélodie + Basse"
    assert orchestra.part_label([{"index": 5, "name": ""}], {"tracks": [5]}, "Piste {n}") == "Piste 6"


# ---------------------------------------------------------------- de bout en bout contre le faux serveur
@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    multi_track_midi(e.song)                    # remplace le morceau de test par un fichier à trois pistes
    e.pA.library.sha256(os.path.basename(e.song), e.song)
    yield e
    e.close()


def test_chacun_prepare_sa_partie(env):
    env.lobby()
    env.pB.instrument = FakeInstrument("bass")
    env.choose_song()
    tracks = env.A.song["tracks"]
    assert [t["index"] for t in tracks] == [1, 2, 3]
    assert env.A.set_parts({"enabled": True, "parts": {"1": {"tracks": [1]}, "2": {"tracks": [2], "octave": -1}}})
    wait_for(lambda: env.A.my_part() and env.B.my_part(), what="parties reçues")
    assert env.A.my_part() == {"tracks": [1], "octave": None}
    assert env.B.my_part_label() == "Basse"
    wait_for(lambda: env.B._prepared and env.B._prepared.get("skip_tracks") is not None, what="B repréparé")
    assert sorted(env.B._prepared["skip_tracks"]) == [0, 1, 3] and env.B._prepared["octave"] == -1
    assert sorted(env.A._prepare(env.A._song_path, *env.A._have)["skip_tracks"]) == [0, 2, 3]
    assert env.B.status()["room"]["my_part"] == "Basse"

    # Orchestre désactivé : tout le monde rejoue tout le morceau
    env.A.set_parts({"enabled": False, "parts": {}})
    wait_for(lambda: env.B.my_part() is None, what="orchestre coupé")
    assert env.B._prepare(env.B._song_path, *env.B._have).get("skip_tracks") is None


def test_seul_le_chef_repartit(env):
    env.lobby()
    env.choose_song()
    assert env.B.set_parts({"enabled": True, "parts": {}}) is False
    assert env.A.propose_parts([])
    wait_for(lambda: env.A.parts and env.A.parts.get("enabled"), what="répartition proposée")
    assert set(env.A.parts["parts"]) == {"1", "2"}
