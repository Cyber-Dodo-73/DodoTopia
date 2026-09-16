# -*- coding: utf-8 -*-
"""Detection du motif repere du mode « synchronisation par le son » sur un signal synthetique : trois notes
(DO5, SOL4, note d'identite) avec l'ecart attendu doivent etre reconnues avec le bon numero de joueur et un
instant de premiere attaque precis ; un motif masque (nos propres notes) ou aux mauvais ecarts ne l'est pas."""
import pytest

np = pytest.importorskip("numpy")

import sync  # noqa: E402

SR = 48000
GAP = 0.25


def _tone(freq, dur, amp=0.4):
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(1.0, t / 0.005) * np.exp(-t * 3.0)          # attaque nette, decroissance de piano
    return (amp * env * (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t))).astype(np.float32)


def _pattern(player_id, t_start=1.0, gap=GAP, total=3.0, noise=0.003):
    """Signal mono : bruit de fond + les trois notes du joueur `player_id` a t_start, +gap, +2*gap."""
    rng = np.random.default_rng(1)
    sig = (rng.standard_normal(int(total * SR)) * noise).astype(np.float32)
    for i, note in enumerate(sync.beacon_notes(player_id)):
        tone = _tone(sync.note_freq(note), 0.6)
        a = int((t_start + i * gap) * SR)
        sig[a:a + len(tone)] += tone[:len(sig) - a]
    return sig


def _feed(det, sig, block=1024, t0=100.0):
    """Pousse le signal par blocs comme la capture audio ; renvoie le premier motif reconnu."""
    found = None
    for i in range(0, len(sig), block):
        chunk = sig[i:i + block]
        t_arrival = t0 + (i + len(chunk)) / SR
        r = det.push(chunk, t_arrival)
        if r is not None and found is None:
            found = r
    return found


@pytest.mark.parametrize("pid", [1, 2, 3, 4, 5])
def test_motif_reconnu_avec_le_bon_joueur_et_l_instant(pid):
    det = sync.BeaconDetector(SR, GAP)
    found = _feed(det, _pattern(pid, t_start=1.0))
    assert found is not None, f"motif du joueur {pid} non reconnu : {det.summary(100.0)}"
    t1, who = found
    assert who == pid
    assert abs((t1 - 100.0) - 1.0) < 0.03, f"instant de la première attaque imprécis : {t1 - 100.0:.3f}"


def test_mauvais_ecarts_non_reconnus():
    det = sync.BeaconDetector(SR, GAP)
    assert _feed(det, _pattern(2, gap=0.8)) is None


def test_nos_propres_notes_masquees():
    det = sync.BeaconDetector(SR, GAP)
    notes = sync.beacon_notes(1)
    for i, note in enumerate(notes):
        tk = 100.0 + 1.0 + i * GAP
        det.mask(tk - 0.08, tk + 0.25, note)
    assert _feed(det, _pattern(1, t_start=1.0)) is None


def test_silence_ne_declenche_rien():
    det = sync.BeaconDetector(SR, GAP)
    sig = (np.random.default_rng(3).standard_normal(SR * 2) * 0.003).astype(np.float32)
    assert _feed(det, sig) is None
    assert det.matches == 0
