"""Arrangeur (arrange.py) : melodie gardee, polyphonie respectee, aucune fausse note ajoutee."""
import pytest

import arrange
import core


@pytest.fixture
def cfg():
    return core.load_config()


def _inst(cfg, id_):
    inst = core.instruments.find_instrument(cfg["_instruments"], id_)
    assert inst is not None and inst.offset_to_key, id_
    return inst


def _diatonic(cfg):
    """Un instrument a 15 notes diatoniques du catalogue (flute a bec)."""
    return _inst(cfg, "recorder")


def _play(grouped, inst, cfg):
    """(evenements, info) comme dans Player.prepare avec l'arrangeur."""
    arranged, shift, stats = arrange.arrange(grouped, inst, cfg)
    events, info = core.fit_notes(arranged, inst, cfg, shift=shift)
    return events, info, stats


def _song_melody_and_chords():
    """Melodie aigue (Do majeur, une phrase qui monte hors registre) + accords de 4 notes + basse."""
    grouped = []
    mel = [72, 74, 76, 77, 79, 81, 83, 84, 86, 88]
    for i, m in enumerate(mel):
        t = i * 0.5
        chord = [(48, 0.5, 70), (55, 0.5, 70), (60, 0.5, 70), (64, 0.5, 70)] if i % 2 == 0 else []
        grouped.append((t, chord + [(m, 0.45, 100)]))
    # deuxieme phrase apres un silence, avec une alteration (F#)
    for i, m in enumerate([67, 66, 67, 69]):
        grouped.append((6.0 + i * 0.4, [(m, 0.35, 100), (43, 0.35, 60)]))
    return grouped


def test_applies_auto_seulement_aux_instruments_non_chromatiques(cfg):
    assert arrange.applies(_diatonic(cfg), "auto")
    assert not arrange.applies(_diatonic(cfg), "off")
    piano = _inst(cfg, "piano")
    assert arrange.applies(piano, "on")
    assert arrange.applies(piano, "auto") == (not piano.chromatic)


def test_melodie_voix_superieure_sauf_sous_une_note_tenue():
    grouped = [(0.0, [(60, 0.2, 80), (72, 2.0, 100)]),     # melodie tenue 2 s
               (0.5, [(48, 0.3, 80)]),                      # basse sous la note tenue : accompagnement
               (2.5, [(71, 0.5, 100)])]
    assert arrange.melody_flags(grouped) == [1, None, 0]


def test_melodie_conservee_et_dans_le_registre(cfg):
    inst = _diatonic(cfg)
    grouped = _song_melody_and_chords()
    events, info, stats = _play(grouped, inst, cfg)
    lo, hi = inst.lowest, inst.lowest + inst.span
    flags = arrange.melody_flags(grouped)
    n_mel = sum(1 for f in flags if f is not None)
    assert stats["melody"] == n_mel
    # chaque attaque de melodie donne un evenement joue, dans le registre
    assert len(events) >= n_mel
    for _, keys, played in events:
        for n, _, _ in played:
            assert lo <= n <= hi


def test_une_phrase_se_deplace_d_une_octave_entiere(cfg):
    inst = _diatonic(cfg)
    span = inst.span
    # phrase de 5 notes conjointes qui depasse le registre d'une tierce : repli par phrase, pas note a note
    base = inst.lowest + span - 4
    grouped = [(i * 0.3, [(base + d, 0.25, 100)]) for i, d in enumerate([0, 2, 4, 5, 7])]
    cfg = dict(cfg, transpose_semitones=0)
    arranged, shift, _ = arrange.arrange(grouped, inst, cfg)
    events, _ = core.fit_notes(arranged, inst, cfg, shift=shift)
    played = [p[0][0] for _, _, p in events]
    steps = [b - a for a, b in zip(played, played[1:])]
    assert all(s > 0 for s in steps), f"la melodie doit rester montante : {played}"


def test_polyphonie_respectee_et_accompagnement_sous_la_melodie(cfg):
    inst = _diatonic(cfg)
    inst.polyphony = 3
    events, info, stats = _play(_song_melody_and_chords(), inst, cfg)
    for _, keys, played in events:
        assert len(keys) <= 3
        top = max(n for n, _, _ in played)
        assert sum(1 for n, _, _ in played if n == top) == 1


def test_aucune_fausse_note_ajoutee_a_l_accompagnement(cfg):
    inst = _diatonic(cfg)
    grouped = _song_melody_and_chords()
    arranged, shift, stats = arrange.arrange(grouped, inst, cfg)
    flags = arrange.melody_flags(arranged)
    _, info = core.fit_notes(arranged, inst, cfg, shift=shift)
    # seules des notes de melodie peuvent encore etre rapprochees d'une touche voisine
    assert info["snapped"] <= stats["melody_snapped"]
    assert info["dropped"] == 0


def test_couverture_pas_pire_que_l_original(cfg):
    inst = _diatonic(cfg)
    grouped = _song_melody_and_chords()
    _, orig = core.fit_notes(grouped, inst, cfg)
    arranged, shift, _ = arrange.arrange(grouped, inst, cfg)
    events, info = core.fit_notes(arranged, inst, cfg, shift=shift)
    exact_orig = orig["exact"] / max(1, orig["notes"] - orig["dropped"])
    exact_arr = info["exact"] / max(1, info["notes"])
    assert exact_arr >= exact_orig


def test_tonalite_imposee_en_salon(cfg):
    inst = _diatonic(cfg)
    grouped = _song_melody_and_chords()
    _, shift, _ = arrange.arrange(grouped, inst, cfg, extra_fixed=3)
    assert (shift - 3) % 12 == 0, "en salon seule l'octave est choisie"


def test_morceau_vide(cfg):
    out, shift, stats = arrange.arrange([], _diatonic(cfg), cfg)
    assert out == [] and stats["notes"] == 0
