# -*- coding: utf-8 -*-
"""Lecteur (core.Player) et fondations : horloge de lecture (vitesse en cours de morceau), pause / reprise en
mode « note », planchers d'appui, polyphonie, sustain, pistes ignorees, injection refusee, fenetre du jeu,
configuration corrompue et ecriture atomique.

Le temps est simule : `core.time` est remplace par une horloge virtuelle que `sleep` fait avancer, donc les
tests sont deterministes et instantanes. Les touches ne partent jamais vers le systeme."""
import json
import os
import threading

import mido
import pytest

import core
import platform_io
from helpers import make_midi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- horloge virtuelle
class VirtualClock:
    """Remplace le module `time` dans core : perf_counter/time avancent seulement par sleep(). Un crochet
    `at(t, fn)` execute fn quand l'horloge franchit t (pour changer la vitesse « pendant » la lecture)."""

    def __init__(self):
        self._t = 1000.0
        self._lock = threading.Lock()
        self._hooks = []
        self.strftime = __import__("time").strftime

    def perf_counter(self):
        return self._t

    def time(self):
        return self._t

    def monotonic(self):
        return self._t

    def sleep(self, s):
        with self._lock:
            self._t += max(0.0, float(s))
            due = [h for h in self._hooks if h[0] <= self._t]
            self._hooks = [h for h in self._hooks if h[0] > self._t]
        for _, fn in due:
            fn()

    def at(self, t, fn):
        with self._lock:
            self._hooks.append((t, fn))


@pytest.fixture
def clock(monkeypatch):
    vc = VirtualClock()
    monkeypatch.setattr(core, "time", vc)
    return vc


@pytest.fixture
def sent(monkeypatch):
    """Frappes envoyees : (touches, up, instant virtuel)."""
    log = []

    def fake_send_keys(keys, up=False, mode="scancode"):
        log.append((list(keys), bool(up), core.time.perf_counter()))

    monkeypatch.setattr(core, "send_keys", fake_send_keys)
    monkeypatch.setattr(platform_io, "send_keys", fake_send_keys)
    monkeypatch.setattr(core, "mouse_button_down", lambda: False)
    return log


@pytest.fixture
def cfg():
    return core.load_config()


@pytest.fixture
def player(cfg, clock):
    cfg["start_delay"] = 0.0
    cfg["stop_on_input"] = False
    cfg["game_process"] = ""
    p = core.Player(cfg, log=lambda m: None)
    yield p
    p.stop(join=True)


def _song(player, name, notes_at):
    """Fichier MIDI : notes_at = [(t_secondes, note, duree_s)], tempo 120 (480 ticks/s)."""
    path = os.path.join(player.songs_folder, name)
    mid = mido.MidiFile(type=0, ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    events = []
    for t, note, dur in notes_at:
        events.append((t, "note_on", note))
        events.append((t + dur, "note_off", note))
    events.sort(key=lambda e: (e[0], e[1] == "note_on"))
    last = 0.0
    for t, kind, note in events:
        tr.append(mido.Message(kind, note=note, velocity=90 if kind == "note_on" else 0,
                               time=int(round((t - last) * 960))))
        last = t
    mid.save(path)
    player.refresh_songs()
    player.index = player.songs.index(path)
    return path


def _run_to_end(player, clock, budget=60.0):
    """Fait avancer l'horloge jusqu'a la fin de la lecture (le fil de lecture dort par petits pas)."""
    import time as real
    deadline = real.perf_counter() + 10
    while player.state != "stopped" and real.perf_counter() < deadline:
        real.sleep(0.002)
    assert player.state == "stopped", "la lecture ne s'est pas terminée"


# ================================================================ 1. vitesse en cours de lecture
def test_changer_la_vitesse_en_cours_de_lecture_ne_fait_ni_rafale_ni_silence(player, clock, sent):
    player.set_instrument("piano")
    player.cfg["hold_mode"] = "tap"
    _song(player, "quatre.mid", [(0.0, 60, 0.2), (1.0, 62, 0.2), (2.0, 64, 0.2), (3.0, 65, 0.2)])
    t0 = clock.perf_counter()
    clock.at(t0 + 1.5, lambda: player.set_speed(2.0))
    player.play("game")
    _run_to_end(player, clock)
    ons = [t - t0 for keys, up, t in sent if not up]
    assert len(ons) == 4
    # notes a 0 et 1 s a vitesse 1 ; a 1,5 s on passe x2 : la note de 2 s (0,5 s de musique restante) tombe
    # a 1,5 + 0,25 = 1,75 et celle de 3 s a 1,5 + 0,75 = 2,25
    assert abs(ons[0] - 0.0) < 0.03
    assert abs(ons[1] - 1.0) < 0.03
    assert abs(ons[2] - 1.75) < 0.03, f"rafale ou silence après le changement de vitesse : {ons}"
    assert abs(ons[3] - 2.25) < 0.03, f"la nouvelle vitesse ne s'applique pas : {ons}"


def test_ralentir_ne_provoque_pas_de_silence(player, clock, sent):
    player.set_instrument("piano")
    player.cfg["hold_mode"] = "tap"
    _song(player, "deux.mid", [(0.0, 60, 0.2), (1.0, 62, 0.2), (2.0, 64, 0.2)])
    t0 = clock.perf_counter()
    clock.at(t0 + 1.5, lambda: player.set_speed(0.5))
    player.play("game")
    _run_to_end(player, clock)
    ons = [t - t0 for keys, up, t in sent if not up]
    assert len(ons) == 3
    # a 1,5 s on est a la position 1,5 ; la note de 2 s est a 0,5 s de musique = 1,0 s reelle a x0,5
    assert abs(ons[2] - 2.5) < 0.03, f"silence anormal après un ralentissement : {ons}"


# ================================================================ 2. pause / reprise
def test_reprise_apres_pause_re_enfonce_les_touches_tenues(player, clock, sent):
    player.set_instrument("piano")
    player.cfg["hold_mode"] = "note"
    _song(player, "tenue.mid", [(0.0, 60, 3.0), (1.0, 64, 0.5)])
    t0 = clock.perf_counter()

    def do_pause():
        player.pause()
        clock.at(clock.perf_counter() + 0.5, lambda: player.play("game"))

    clock.at(t0 + 0.5, do_pause)
    player.play("game")
    _run_to_end(player, clock)
    seq = [(tuple(k), up, round(t - t0, 2)) for k, up, t in sent]
    downs = [(k, t) for k, up, t in seq if not up]
    ups = [(k, t) for k, up, t in seq if up]
    # la touche de la note tenue est enfoncee au depart, relachee a la pause, re-enfoncee a la reprise
    first_key = downs[0][0]
    assert any(k == first_key and 0.45 <= t <= 0.6 for k, t in ups), f"pas de relâchement à la pause : {seq}"
    assert sum(1 for k, _ in downs if k == first_key) >= 2, f"la touche tenue n'est pas ré-enfoncée : {seq}"
    assert player._held == []


# ================================================================ 3. planchers, polyphonie, sustain, pistes
def test_planchers_d_appui_et_d_ecart():
    events = [(0.0, ["y"], [(60, 0.003, 90)]), (0.01, ["y"], [(60, 0.5, 90)])]
    tl = core.build_timeline(events, "game", 0.004, "note", 4.0, min_press=0.02, min_gap=0.012)
    ons = [t for t, _, kind, _ in tl if kind == "on"]
    offs = [t for t, _, kind, _ in tl if kind == "off"]
    assert offs[0] - ons[0] >= 0.02 - 1e-9, "appui plus court que le plancher"
    tl_tap = core.build_timeline([(0.0, ["y"], [(60, 0.1, 90)])], "game", 0.004, "tap", 4.0, min_press=0.02)
    assert tl_tap[1][0] - tl_tap[0][0] >= 0.02 - 1e-9


def test_la_polyphonie_de_l_instrument_est_appliquee(cfg):
    inst = core.instruments.find_instrument(cfg["_instruments"], "piano")
    inst.polyphony = 2
    grouped = [(0.0, [(60, 1.0, 90), (64, 1.0, 90), (67, 1.0, 90), (72, 1.0, 90)])]
    events, info = core.fit_notes(grouped, inst, cfg, shift=0)
    assert len(events[0][1]) == 2, "plus de touches que la polyphonie"
    played = sorted(n for n, _, _ in events[0][2])
    assert played[0] == 60 and played[-1] == 72, "on garde la basse et la note la plus aiguë"
    assert info["dropped_poly"] == 2 and info["dropped"] == 2


def _midi_with_pedal(path):
    mid = mido.MidiFile(type=0, ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    tr.append(mido.Message("control_change", control=64, value=127, time=0))
    tr.append(mido.Message("note_on", note=60, velocity=90, time=0))
    tr.append(mido.Message("note_off", note=60, velocity=0, time=240))        # 0,25 s ecrit
    tr.append(mido.Message("control_change", control=64, value=0, time=1440))  # pedale relachee a 1,75 s
    mid.save(path)


def test_sustain_prolonge_les_notes_jusqu_au_relachement_de_la_pedale(tmp_path):
    path = str(tmp_path / "pedale.mid")
    _midi_with_pedal(path)
    sans = core.parse_midi(path, {"ignore_drums": True, "chord_window": 0.02, "sustain": False})
    avec = core.parse_midi(path, {"ignore_drums": True, "chord_window": 0.02, "sustain": True})
    assert abs(sans[0][1][0][1] - 0.25) < 0.01
    assert abs(avec[0][1][0][1] - 1.75) < 0.01


def test_pistes_ignorees_sans_perdre_le_tempo(tmp_path):
    path = str(tmp_path / "pistes.mid")
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    tempo = mido.MidiTrack()
    tempo.append(mido.MetaMessage("track_name", name="Tempo", time=0))
    tempo.append(mido.MetaMessage("set_tempo", tempo=250000, time=0))   # 240 bpm
    melodie = mido.MidiTrack()
    melodie.append(mido.MetaMessage("track_name", name="Mélodie", time=0))
    melodie.append(mido.Message("note_on", note=72, velocity=90, time=480))   # 1 temps = 0,25 s a 240 bpm
    melodie.append(mido.Message("note_off", note=72, velocity=0, time=480))
    basse = mido.MidiTrack()
    basse.append(mido.MetaMessage("track_name", name="Basse", time=0))
    basse.append(mido.Message("note_on", note=36, velocity=90, time=0))
    basse.append(mido.Message("note_off", note=36, velocity=0, time=480))
    mid.tracks.extend([tempo, melodie, basse])
    mid.save(path)
    tracks = core.midi_tracks(path)
    assert [t["name"] for t in tracks] == ["Tempo", "Mélodie", "Basse"]
    assert [t["notes"] for t in tracks] == [0, 1, 1]
    cfg = {"ignore_drums": True, "chord_window": 0.02}
    tout = core.parse_midi(path, cfg)
    assert sorted(n for _, ns in tout for n, _, _ in ns) == [36, 72]
    sans_basse = core.parse_midi(path, cfg, skip_tracks=[2])
    assert [n for _, ns in sans_basse for n, _, _ in ns] == [72]
    # ignorer la piste de tempo ne change pas la chronologie : la melodie reste a 0,25 s (a 120 bpm par
    # defaut, tempo perdu, elle tomberait a 0,5 s)
    sans_tempo = core.parse_midi(path, cfg, skip_tracks=[0])
    t_melodie = [t for t, ns in sans_tempo if any(n == 72 for n, _, _ in ns)][0]
    assert abs(t_melodie - 0.25) < 0.01


def test_library_tracks_off(tmp_path):
    lib = core.Library(str(tmp_path / "library.json"))
    assert lib.set_tracks_off("x.mid", [2, 0, 2]) == [0, 2]
    assert lib.meta("x.mid")["tracks_off"] == [0, 2]
    assert lib.set_tracks_off("x.mid", []) == []
    assert "tracks_off" not in lib.meta("x.mid")


# ================================================================ 4. injection refusee, fenetre du jeu
def test_injection_refusee_arrete_proprement(player, clock, monkeypatch):
    player.set_instrument("piano")
    _song(player, "une.mid", [(0.0, 60, 0.5)])

    def refuse(keys, up=False, mode="scancode"):
        raise platform_io.InjectionError("refusé", 5)

    monkeypatch.setattr(core, "send_keys", refuse)
    monkeypatch.setattr(core, "mouse_button_down", lambda: False)
    player.play("game")
    _run_to_end(player, clock)
    assert player.last_stop_reason == "injection_denied"
    assert player._held == []


def _front(monkeypatch, proc, title, found=True):
    """Fenetre au premier plan simulee, et jeu present (ou non) ailleurs sur le bureau."""
    monkeypatch.setattr(platform_io, "foreground_window", lambda: (proc, title))
    monkeypatch.setattr(platform_io, "game_window_info",
                        lambda names, titles=(): {"found": found, "foreground": False, "elevated": False})
    platform_io._found_cache.update(at=0.0, key=None, found=None)


def test_autre_fenetre_devant_annule_la_lecture(player, clock, sent, monkeypatch):
    player.set_instrument("piano")
    player.cfg["game_process"] = platform_io.DEFAULT_GAME_PROCESS
    _front(monkeypatch, "Discord.exe", "#general - Discord", found=True)
    _song(player, "une.mid", [(0.0, 60, 0.5)])
    player.play("game")
    _run_to_end(player, clock)
    assert player.last_stop_reason == "game_not_focused"
    assert not [k for k, up, t in sent if not up], "des touches sont parties vers une autre application"


def test_heartopia_tourne_sous_xdt_exe(player, clock, sent, monkeypatch):
    """Le processus du jeu est xdt.exe : la 2.0.0 attendait Heartopia.exe et refusait de jouer chez tout le monde."""
    player.set_instrument("piano")
    player.cfg["game_process"] = platform_io.DEFAULT_GAME_PROCESS
    _front(monkeypatch, "C:\\Jeux\\Heartopia\\xdt.exe", "Heartopia")
    _song(player, "une.mid", [(0.0, 60, 0.5)])
    player.play("game")
    _run_to_end(player, clock)
    assert player.last_stop_reason == ""
    assert [k for k, up, t in sent if not up]


def test_fenetre_titree_heartopia_reconnue_meme_si_l_executable_change(player, clock, sent, monkeypatch):
    player.set_instrument("piano")
    player.cfg["game_process"] = "autre.exe"
    _front(monkeypatch, "launcher_renomme.exe", "Heartopia", found=False)
    _song(player, "une.mid", [(0.0, 60, 0.5)])
    player.play("game")
    _run_to_end(player, clock)
    assert player.last_stop_reason == ""
    assert [k for k, up, t in sent if not up]


def test_jeu_introuvable_ne_bloque_pas(player, clock, sent, monkeypatch):
    """Si aucune fenetre du jeu n'est reconnue (executable inconnu), on ne bloque pas tout le monde."""
    player.set_instrument("piano")
    player.cfg["game_process"] = platform_io.DEFAULT_GAME_PROCESS
    _front(monkeypatch, "jeu_inconnu.exe", "Une fenêtre", found=False)
    _song(player, "une.mid", [(0.0, 60, 0.5)])
    player.play("game")
    _run_to_end(player, clock)
    assert player.last_stop_reason == ""
    assert [k for k, up, t in sent if not up]


def test_un_onglet_de_navigateur_nomme_heartopia_n_est_pas_le_jeu():
    names = platform_io.game_names(platform_io.DEFAULT_GAME_PROCESS)
    assert names == {"xdt.exe", "heartopia.exe"}
    assert platform_io.is_game_window("zen.exe", "Heartopia wiki - Zen Browser", names) is False
    assert platform_io.is_game_window("xdt.exe", "", names) is True
    assert platform_io.is_game_window(None, " Heartopia ", names) is True
    assert platform_io.game_names(' "C:\\x\\XDT.exe" ; autre.exe ') == {"xdt.exe", "autre.exe"}
    assert platform_io.game_in_front("") is None


def test_l_ancien_defaut_heartopia_exe_est_migre():
    import json as _json
    with open(core.CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump({"game_process": "Heartopia.exe"}, f)
    assert core.load_config()["game_process"] == platform_io.DEFAULT_GAME_PROCESS
    with open(core.CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump({"game_process": "mon_jeu.exe"}, f)
    assert core.load_config()["game_process"] == "mon_jeu.exe", "un choix de l'utilisateur est conservé"
    with open(core.CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump({"game_process": ""}, f)
    assert core.load_config()["game_process"] == "", "vérification désactivée : on n'y touche pas"


# ================================================================ 5. compteur des frappes attendues (verrou)
def test_compteur_des_frappes_attendues_est_sur_sous_concurrence(cfg, clock):
    p = core.Player(cfg, log=lambda m: None)

    class Ev:
        def __init__(self, sc, et):
            self.scan_code, self.event_type, self.name = sc, et, "y"

    sc = core.scan_code_for("y", "scancode")
    n = 2000
    errors = []

    def producer():
        for _ in range(n):
            p._expect(["y"], False)

    def consumer():
        seen = 0
        import time as real
        deadline = real.perf_counter() + 5
        while seen < n and real.perf_counter() < deadline:
            if p._consume_expected(Ev(sc, "down")):
                seen += 1
        if seen != n:
            errors.append(seen)

    t1, t2 = threading.Thread(target=producer), threading.Thread(target=consumer)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not errors, f"frappes perdues ou comptées deux fois : {errors}"
    assert p._expected.get((sc, "down"), 0) == 0


# ================================================================ 6. configuration : atomique, recuperation
def test_ecriture_atomique_ne_laisse_pas_de_fichier_tronque(tmp_path, monkeypatch):
    path = str(tmp_path / "c.json")
    core.write_json_atomic(path, {"a": 1})
    assert json.load(open(path, encoding="utf-8")) == {"a": 1}
    real_replace = os.replace

    def boom(src, dst):
        raise OSError("coupure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        core.write_json_atomic(path, {"a": 2})
    monkeypatch.setattr(os, "replace", real_replace)
    assert json.load(open(path, encoding="utf-8")) == {"a": 1}, "l'ancien fichier doit rester intact"
    assert not [f for f in os.listdir(tmp_path) if ".tmp-" in f], "fichier temporaire abandonné"


def test_config_corrompue_est_mise_de_cote_et_l_app_demarre():
    with open(core.CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write('{"instrument": "piano", "hotk')   # tronque
    cfg = core.load_config()
    assert cfg["_recovered"] is True
    assert cfg["_instruments"], "les instruments doivent venir du catalogue"
    data_dir = os.path.dirname(core.CONFIG_PATH)
    assert [f for f in os.listdir(data_dir) if f.startswith("config.json.broken-")]
    core.save_config(cfg)
    assert core.load_config()["_recovered"] is False


def test_f12_par_defaut_est_retire_une_seule_fois():
    with open(core.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"hotkeys": {"next_instrument": "F12"}}, f)
    cfg = core.load_config()
    assert cfg["hotkeys"]["next_instrument"] == ""
    assert cfg["hotkeys_migrated_f12"] is True
    cfg["hotkeys"]["next_instrument"] = "F12"       # choix explicite de l'utilisateur ensuite
    core.save_config(cfg)
    assert core.load_config()["hotkeys"]["next_instrument"] == "F12"


def test_sortie_midi_indisponible_arrete_l_ecoute_avec_une_raison(player, clock, monkeypatch):
    class DeadMidi:
        ok = False
        error = "midiOutOpen a échoué (code 4)"
        sounding = set()

        def all_off(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(core, "MidiOut", DeadMidi)
    player.set_instrument("piano")
    _song(player, "une.mid", [(0.0, 60, 0.5)])
    player.play("preview")
    _run_to_end(player, clock)
    assert player.last_stop_reason == "midi_out_unavailable"
