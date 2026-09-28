"""Conga : la batterie du fichier sur les 8 pads (roles relevés à l'écoute), le rythme à défaut de batterie."""
import os

import mido
import pytest

import core
import instruments
import percussion


@pytest.fixture
def conga():
    cfg = core.load_config()
    inst = instruments.find_instrument(cfg["_instruments"], "conga")
    assert inst.ready, inst.blocked_reason
    return cfg, inst


def midi(path, drums=(), melody=()):
    mid = mido.MidiFile(type=1)
    for ch, notes in ((9, drums), (0, melody)):
        if not notes:
            continue
        tr = mido.MidiTrack()
        for n in notes:
            tr.append(mido.Message("note_on", note=n, velocity=100, channel=ch, time=0))
            tr.append(mido.Message("note_off", note=n, velocity=0, channel=ch, time=240))
        mid.tracks.append(tr)
    mid.save(path)
    return path


def test_pads_de_la_conga(conga):
    cfg, inst = conga
    assert inst.percussive and inst.layout_id == "conga-8"
    assert sorted(inst.bindings.values()) == sorted("yuiohjkl")


def test_la_batterie_va_sur_les_bons_pads(conga, tmp_path):
    cfg, inst = conga
    path = midi(str(tmp_path / "b.mid"), drums=(36, 38, 42, 64, 62, 99), melody=(60, 64, 67))
    p = core.Player(cfg, log=lambda m: None)
    try:
        prep = p.prepare(path, inst, "game")
    finally:
        p.stop(join=True)
    keys = [e[1][0] for e in prep["events"]]
    assert keys[:5] == ["h", "y", "i", "k", "o"], "grosse caisse, caisse claire, charleston, conga grave, étouffée"
    assert prep["info"]["percussion"] == "drums" and prep["info"]["shift"] == 0
    assert len(prep["events"]) == 6, "la mélodie n'est pas jouée quand il y a une batterie"


def test_sans_batterie_le_rythme_des_notes(conga, tmp_path):
    cfg, inst = conga
    path = midi(str(tmp_path / "m.mid"), melody=(40, 52, 64, 76))
    p = core.Player(cfg, log=lambda m: None)
    try:
        prep = p.prepare(path, inst, "game")
    finally:
        p.stop(join=True)
    keys = [e[1][0] for e in prep["events"]]
    assert prep["info"]["percussion"] == "rhythm"
    assert keys[0] == "h" and keys[-1] == "y", "les graves sur le pad grave, les aigus sur le claqué"


def test_role_des_notes_rares():
    assert percussion.role_of(36) == "kick" and percussion.role_of(49) == "cymbal"
    assert percussion.role_of(33) == "low" and percussion.role_of(80) == "cymbal"
