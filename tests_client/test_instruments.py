# -*- coding: utf-8 -*-
"""Instruments : catalogue, dispositions, profils, migration, transformation MIDI, collisions, touches tenues.

Ces tests n'envoient RIEN au clavier réel : `platform_io.send_keys` (et son alias `core.send_keys`) sont
remplacés par un enregistreur pour toute la durée du module. Ils n'écrivent pas non plus dans le projet :
`tests_client/conftest.py` redirige `core.DATA_DIR` / `core.CONFIG_PATH` vers un dossier temporaire et
vérifie après chaque test que `config.json` du dépôt est intact.

Ce qu'ils ne font PAS : rejouer les composants visuels, et surtout prouver quoi que ce soit dans Heartopia.
Les tables de touches viennent de sources communautaires ; « documenté par une source » n'est pas
« confirmé sur cette installation ». Aucun test ici ne lance le jeu.
"""
import json
import os
import threading
import time
from collections import deque

import pytest

import app
import core
import instruments
import platform_io
from helpers import add_song, make_midi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ce que l'installation du dépôt contenait avant cette version (ancien format « keys + lowest_note »).
# Le luth y est la disposition à 15 notes descendue d'une octave : c'est le cas décisif de la migration.
LEGACY_KEYS_15 = ["y", "u", "i", "o", "p", "h", "j", "k", "l", ";", "n", "m", ",", ".", "/"]
LEGACY_SCALE_15 = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23, 24]
LEGACY_PIANO_KEYS = [",", "l", ".", ";", "/", "o", "0", "p", "-", "[", "=", "]", "z", "s", "x", "d", "c",
                     "v", "g", "b", "h", "n", "j", "m", "q", "2", "w", "3", "e", "r", "5", "t", "6", "y",
                     "7", "u", "i"]


def legacy_config():
    """Ancienne config.json du dépôt, réduite à ce que la migration doit traiter."""
    return {
        "instrument": "luth",
        "hotkeys": {"play_pause": "F6", "stop": "F7", "next_instrument": "F12"},
        "instruments": {
            "piano": {"name": "Piano", "lowest_note": 48, "auto_transpose": "octave",
                      "keys": list(LEGACY_PIANO_KEYS), "gm_program": 0},
            "flute": {"name": "Flûte", "lowest_note": 60, "auto_transpose": "key",
                      "scale": list(LEGACY_SCALE_15), "keys": list(LEGACY_KEYS_15), "gm_program": 73},
            "luth": {"name": "Luth", "lowest_note": 48, "auto_transpose": "key",
                     "scale": list(LEGACY_SCALE_15), "keys": list(LEGACY_KEYS_15), "gm_program": 24},
        },
    }


# ---------------------------------------------------------------- garde-fous et fixtures
@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch):
    """Aucune frappe ne part vers le système : send_keys est enregistré, jamais exécuté."""
    sent = []

    def fake_send_keys(keys, up=False, mode="scancode"):
        sent.append((list(keys), bool(up), mode))

    monkeypatch.setattr(platform_io, "send_keys", fake_send_keys)
    monkeypatch.setattr(core, "send_keys", fake_send_keys)          # alias importe dans core
    monkeypatch.setattr(platform_io, "mouse_button_down", lambda: False)
    return sent


@pytest.fixture
def cat():
    return instruments.load_catalogue(ROOT)


@pytest.fixture
def a_relever(monkeypatch):
    """Tous les types du catalogue ont maintenant une disposition (la conque a été relevée dans le jeu le
    2026-10-03). Les garde-fous d'un type « à relever » restent testés : cette fixture remet la conque dans cet
    état le temps du test. À demander AVANT `cfg`, `player` ou `api_stub`, qui construisent les instruments."""
    t = next(t for t in instruments.load_catalogue(ROOT).types if t.id == "conch")
    monkeypatch.setattr(t, "supported_layout_ids", [])
    monkeypatch.setattr(t, "default_layout_id", None)
    monkeypatch.setattr(t, "mapping_status", "unknown")
    return t.id


@pytest.fixture
def cfg():
    """Config utilisateur neuve (config.default.json copiée dans le dossier temporaire, puis migrée)."""
    return core.load_config()


@pytest.fixture
def player(cfg):
    p = core.Player(cfg, log=lambda m: None)
    yield p
    p.stop(join=True)


def raw_catalogue():
    with open(os.path.join(ROOT, "assets", "instruments", "catalogue.json"), "r", encoding="utf-8") as f:
        return f.read()


def inst_of(cfg_or_player, instrument_id):
    insts = cfg_or_player.instruments if hasattr(cfg_or_player, "instruments") else cfg_or_player["_instruments"]
    return instruments.find_instrument(insts, instrument_id)


# ================================================================ 1. catalogue
def test_catalogue_dix_neuf_types_un_seul_piano(cat):
    assert len(cat.types) == 19
    ids = [t.id for t in cat.types]
    assert len(set(ids)) == 19, "un identifiant de type apparaît deux fois"
    assert ids.count("piano") == 1
    labels = [t.label_fr for t in cat.types]
    assert len(set(labels)) == 19, "deux types portent le même nom affiché"
    assert {c[0] for c in cat.categories} == {"strings", "winds", "keys", "percussion"}
    for t in cat.types:
        assert t.category in dict(cat.categories), f"{t.id} : catégorie inconnue"


def test_catalogue_sans_variante_esthetique(cat):
    """Une carte par type : ni skin, ni couleur, ni variante sélectionnable, nulle part."""
    texte = raw_catalogue()
    for interdit in ("skinId", "selectedVariantId", "variants\"", "colorId"):
        assert interdit not in texte, f"le catalogue applicatif contient « {interdit} »"
    for t in cat.types:
        # les identifiants d'objets sources servent UNIQUEMENT a la tracabilite de l'image
        assert t.variant_count >= 1
        assert isinstance(t.catalog_item_ids, list)
    total_variantes = sum(t.variant_count for t in cat.types)
    assert total_variantes > 19, "les variantes brutes doivent rester tracées, mais regroupées"


def test_catalogue_une_image_par_type_presente_hors_ligne(cat):
    images = {}
    for t in cat.types:
        assert t.image, f"{t.id} : aucune image"
        assert not t.image.startswith(("http://", "https://")), f"{t.id} : image en hotlink"
        chemin = os.path.join(ROOT, "ui", t.image.replace("/", os.sep))
        assert os.path.isfile(chemin), f"{t.id} : {t.image} absent du dossier ui/"
        assert os.path.getsize(chemin) > 0
        images.setdefault(t.image, []).append(t.id)
    doublons = {img: ids for img, ids in images.items() if len(ids) > 1}
    assert not doublons, f"une image représentative est partagée par plusieurs types : {doublons}"
    assert len(images) == 19


def test_catalogue_provenance_sans_pretendre_avoir_teste(cat):
    """Les statuts disent d'où vient la table : documentée par la communauté, ou famille confirmée par le
    propriétaire dans le jeu (piano, « comme le luth »)."""
    for t in cat.types:
        if t.supported_layout_ids:
            assert t.mapping_status in ("community-documented-not-tested-in-game", "owner-confirmed-in-game")
            assert t.default_layout_id in t.supported_layout_ids
        else:
            assert t.mapping_status == "unknown"
            assert t.default_layout_id is None
    a_relever = {t.id for t in cat.types if not t.supported_layout_ids}
    assert a_relever == set(), "plus aucun type à relever : xylophone et conque ont été relevés dans le jeu"
    percussifs = {t.id for t in cat.types if t.percussive}
    assert percussifs == {"conga", "cajon"}


# ================================================================ 2. dispositions
def test_dispositions_quinze_quinze_vingt_deux_trente_sept(cat):
    attendu = {"lute-15-3row": 15, "diatonic-15-2row": 15, "diatonic-15-3row": 15,
               "piano-diatonic-22": 22, "piano-chromatic-37": 37, "conga-8": 8, "xylophone-8": 8, "conch-8": 8}
    assert set(cat.layouts) == set(attendu)
    for lid, n in attendu.items():
        lay = cat.layouts[lid]
        assert lay.note_count == n, f"{lid} : noteCount {lay.note_count} au lieu de {n}"
        assert len(lay.notes) == n, f"{lid} : {len(lay.notes)} notes décrites au lieu de {n}"
        assert sum(lay.rows) == n, f"{lid} : les rangées d'affichage ne totalisent pas {n}"


def test_dispositions_sans_doublon_et_entierement_injectables(cat):
    for lid, lay in cat.layouts.items():
        midis = [n["midi"] for n in lay.notes]
        touches = [n["key"] for n in lay.notes]
        assert len(set(midis)) == len(midis), f"{lid} : une note MIDI apparaît deux fois"
        assert len(set(touches)) == len(touches), f"{lid} : une touche porte deux notes"
        assert midis == sorted(midis), f"{lid} : les notes ne sont pas dans l'ordre"
        absentes = [k for k in touches if k not in platform_io.SCANCODES]
        assert not absentes, f"{lid} : touches non injectables {absentes}"
        assert len(lay.bindings()) == lay.note_count


def test_dispositions_registre_coherent_avec_do4_60(cat):
    assert instruments.note_name(60) == "C4"
    assert instruments.solfege(60) == "Do4"
    assert instruments.solfege(48) == "Do3"
    assert instruments.solfege(84) == "Do6"
    for lid, lay in cat.layouts.items():
        for n in lay.notes:
            assert n["note"] == instruments.note_name(n["midi"]), f"{lid} : nom international décalé"
            assert n["solfege"] == instruments.solfege(n["midi"]), f"{lid} : nom français décalé"
        assert 36 <= lay.notes[0]["midi"] <= 72, f"{lid} : note la plus grave invraisemblable"
        assert lay.notes[-1]["midi"] <= 96
    # le profil chromatique couvre tous les demi-tons, les profils diatoniques non
    chroma = cat.layouts["piano-chromatic-37"]
    midis = [n["midi"] for n in chroma.notes]
    assert midis == list(range(midis[0], midis[0] + 37))
    diato = cat.layouts["diatonic-15-3row"]
    manquantes = set(range(60, 85)) - {n["midi"] for n in diato.notes}
    assert 61 in manquantes and 63 in manquantes, "une disposition diatonique n'a pas les altérations"


# ================================================================ 3. types distincts / dispositions distinctes
def test_deux_types_partageant_une_disposition_restent_distincts(cfg, cat):
    recorder = inst_of(cfg, "recorder")
    lute = inst_of(cfg, "lute")
    assert recorder is not None and lute is not None
    assert recorder is not lute
    assert recorder.layout_id == lute.layout_id == "lute-15-3row"
    assert recorder.bindings == lute.bindings, "même disposition : mêmes positions envoyées au jeu"
    # ... mais deux identites sonores, deux cartes, deux images, deux apercus
    assert recorder.id != lute.id
    assert recorder.name != lute.name
    assert recorder.image != lute.image
    assert recorder.gm_program != lute.gm_program
    assert recorder.category != lute.category
    assert recorder.fingerprint != lute.fingerprint, "l'empreinte doit distinguer les deux profils"


def test_deux_dispositions_d_un_meme_type_ne_partagent_pas_leurs_touches(cat):
    piano = cat.by_id["piano"]
    assert len(piano.supported_layout_ids) >= 2
    tables = {lid: cat.layouts[lid].bindings() for lid in piano.supported_layout_ids}
    vus = []
    for lid, table in tables.items():
        assert table not in vus, f"{lid} : disposition identique à une autre du même type"
        vus.append(table)
    a, b = cat.layouts["diatonic-15-2row"], cat.layouts["diatonic-15-3row"]
    assert a.note_count == b.note_count == 15
    assert [n["key"] for n in a.notes] != [n["key"] for n in b.notes], \
        "les deux profils à 15 notes diffèrent par leurs touches, pas seulement par leurs rangées"
    # le nombre de rangees ne permet pas de deduire les touches : la majorite des notes change de position
    communes = {m for m in a.bindings() if a.bindings()[m] == b.bindings().get(m)}
    assert len(communes) < 4, ("les deux profils à 15 notes seraient interchangeables : "
                               f"{len(communes)} notes sur 15 tombent sur la même touche")
    assert set(a.bindings().values()) != set(b.bindings().values()), \
        "les deux profils n'utilisent pas le même jeu de positions"


# ================================================================ 4. migration
def test_migration_anciens_identifiants_et_profils_documentes(cat):
    cfg = legacy_config()
    log = instruments.migrate_config(cfg, cat)
    insts = cfg["instruments"]
    assert "flute" not in insts and "luth" not in insts and "guitare" not in insts
    assert cfg["instrument"] == "lute", "l'instrument actif suit le renommage"

    piano = insts["piano"]
    assert piano["layoutId"] == "piano-chromatic-37"
    assert piano["verificationStatus"] == "documented"
    assert "bindings" not in piano, "table identique à la disposition : rien à stocker"

    recorder = insts["recorder"]
    assert recorder["layoutId"] == "lute-15-3row", "la flûte suit la famille du luth"
    assert recorder["verificationStatus"] == "documented"
    assert "bindings" not in recorder

    assert any("recorder" in ligne for ligne in log)
    assert all(t.id in insts for t in cat.types), "chaque type du catalogue reçoit un profil"
    for t in cat.types:
        if not t.supported_layout_ids:
            assert insts[t.id]["layoutId"] is None
            assert insts[t.id]["verificationStatus"] == "unknown"
            assert "bindings" not in insts[t.id], "aucune touche inventée pour un profil à relever"


def test_migration_luth_une_octave_plus_bas_devient_la_famille(cat):
    """Le luth de cette installation (mêmes positions que la table documentée, une octave plus bas) est
    exactement la disposition « comme le luth » : il redevient la disposition de sa famille, sans rien perdre."""
    cfg = legacy_config()
    instruments.migrate_config(cfg, cat)
    lute = cfg["instruments"]["lute"]
    assert lute["layoutId"] == "lute-15-3row" and "bindings" not in lute
    attendu = {48 + o: k for o, k in zip(LEGACY_SCALE_15, LEGACY_KEYS_15)}
    assert cat.layouts["lute-15-3row"].bindings() == attendu, "les touches du luth ont changé"
    resolu = instruments.Instrument(cat.by_id["lute"], instruments.profile_of(cfg, "lute", cat),
                                    cat.layouts["lute-15-3row"])
    assert resolu.lowest == 48 and resolu.ready is True


def test_migration_touche_personnalisee_conservee(cat):
    cfg = legacy_config()
    cfg["instruments"]["flute"]["keys"][0] = "b"        # une seule touche déplacée par l'utilisateur
    instruments.migrate_config(cfg, cat)
    recorder = cfg["instruments"]["recorder"]
    assert recorder["verificationStatus"] == "custom"
    assert recorder["bindings"]["60"] == "b"
    assert len(recorder["bindings"]) == 15


def test_migration_idempotente_et_identifiant_inconnu_conserve(cat):
    cfg = legacy_config()
    cfg["instruments"]["theremine-maison"] = {"schemaVersion": 1, "layoutId": None,
                                              "verificationStatus": "custom",
                                              "bindings": {"60": "a", "62": "s"}}
    instruments.migrate_config(cfg, cat)
    premier = json.dumps(cfg["instruments"], sort_keys=True, ensure_ascii=False)
    log2 = instruments.migrate_config(cfg, cat)
    second = json.dumps(cfg["instruments"], sort_keys=True, ensure_ascii=False)
    assert premier == second, "la migration n'est pas idempotente"
    assert log2 == [], "rien à migrer la deuxième fois"
    assert cfg["instruments"]["theremine-maison"]["bindings"] == {"60": "a", "62": "s"}, \
        "le travail de l'utilisateur sur un identifiant inconnu doit survivre"
    assert instruments.find_instrument(instruments.build_instruments(cfg, ROOT), "theremine-maison") is None


def test_migration_retire_les_variantes_esthetiques(cat):
    cfg = legacy_config()
    cfg["skinId"] = "piano-rose"
    cfg["instruments"]["piano"]["selectedVariantId"] = "piano-rose-2"
    instruments.migrate_config(cfg, cat)
    assert "skinId" not in cfg
    texte = json.dumps(cfg, ensure_ascii=False)
    assert "skinId" not in texte and "selectedVariantId" not in texte


# ================================================================ 5. profil inconnu
def test_profil_inconnu_n_herite_jamais_du_piano(a_relever, cfg):
    for ident in ("conch",):
        inst = inst_of(cfg, ident)
        assert inst is not None
        assert inst.status == "unknown"
        assert inst.keys == [] and inst.scale == [] and inst.bindings == {}
        assert inst.ready is False and inst.blocked_reason
        assert inst.lowest == 60 and inst.span == 0 and inst.chromatic is False
        assert inst.snap(3) is None and inst.key_for(60) is None
        assert inst.available_notes == [] and inst.missing_notes == []
        assert inst.note_rows() == []
        piano = inst_of(cfg, "piano")
        assert inst.keys != piano.keys, f"{ident} a hérité du mapping du piano"


def test_profil_inconnu_ne_lance_pas_de_lecture(a_relever, cfg, player, no_real_keys, tmp_path):
    add_song(player, "essai.mid")
    player.refresh_songs()
    ok, msg = player.set_instrument("conch")
    assert ok, msg
    assert player.instrument.ready is False
    player.play("game")
    player._thread and player._thread.join(timeout=2)
    assert player.state == "stopped", "une lecture a démarré sur un profil à configurer"
    assert no_real_keys == [], "des touches ont été envoyées avec un profil inconnu"


def test_fit_notes_sur_profil_sans_touche_ne_devine_rien(a_relever, cfg):
    inst = inst_of(cfg, "conch")
    grouped = [(0.0, [(60, 0.5, 90)]), (0.5, [(62, 0.5, 90)])]
    events, info = core.fit_notes(grouped, inst, cfg)
    assert events == []
    assert info["dropped"] == 2 and info["hits"] == 0 and info["coverage"] == 0


# ================================================================ 6. percussions
def test_cajon_candidat_tant_que_ses_frappes_ne_sont_pas_relevees(cfg):
    for ident in ("cajon",):
        inst = inst_of(cfg, ident)
        assert inst.percussive is True
        assert inst.status == "documented"
        assert inst.bindings, "la correspondance documentée existe bien"
        assert inst.ready is False, f"{ident} ne doit pas être jouable sur la seule foi d'une source"
        assert "frappe" in inst.blocked_reason.lower()


def test_conga_jouable_apres_le_test_des_frappes(cfg):
    instruments.set_profile(cfg, "conga", status=instruments.STATUS_QUICK,
                            verified_at="2026-09-15T10:00:00")
    cfg["_instruments"] = instruments.build_instruments(cfg, ROOT)
    conga = inst_of(cfg, "conga")
    assert conga.status == "quick-tested"
    assert conga.ready is True and conga.blocked_reason == ""
    # un instrument melodique documente, lui, est jouable tout de suite
    assert inst_of(cfg, "recorder").ready is True


def test_un_type_percussif_ne_devient_pas_melodiquement_equivalent_au_piano(cfg, cat):
    conga = inst_of(cfg, "conga")
    piano = inst_of(cfg, "piano")
    assert conga.keys != piano.keys
    assert conga.polyphony is None and conga.sounding_pitch_offset is None, \
        "aucune capacité supposée : seules les valeurs mesurées sont renseignées"
    assert cat.by_id["cajon"].mapping_status == "community-documented-not-tested-in-game"


# ================================================================ 7. transformation MIDI
def test_fit_notes_identifie_les_alterations_absentes(cfg):
    inst = inst_of(cfg, "recorder")                     # diatonique : pas de dièse
    assert inst.kind == "diatonique"
    grouped = [(i * 0.5, [(n, 0.4, 90)]) for i, n in enumerate([60, 61, 62, 63, 64, 65])]
    events, info = core.fit_notes(grouped, inst, cfg, shift=0)
    assert info["notes"] == 6
    assert info["missing_accidental"] == info["snapped"] >= 2, "les dièses absents doivent être comptés"
    assert info["exact"] + info["snapped"] + info["dropped"] == info["notes"]
    assert 0 <= info["coverage"] <= 100
    assert info["coverage"] == round(100 * info["exact"] / info["notes"])
    # cles historiques (sync.py, room.py, interface) preservees
    for cle in ("shift", "folded", "snapped", "dropped", "hits", "notes"):
        assert cle in info
    assert 61 in inst.missing_notes and 63 in inst.missing_notes
    assert 62 not in inst.missing_notes


def test_fit_notes_compte_les_notes_hors_registre(cfg):
    inst = inst_of(cfg, "recorder")
    grouped = [(0.0, [(36, 0.4, 90)]), (0.5, [(100, 0.4, 90)]), (1.0, [(60, 0.4, 90)])]
    events, info = core.fit_notes(grouped, inst, cfg, shift=0)
    assert info["out_of_range"] == 2
    assert info["folded"] == 2 and info["dropped"] == 0
    sans_repli = dict(cfg)
    sans_repli["fold_out_of_range"] = False
    _, info2 = core.fit_notes(grouped, inst, sans_repli, shift=0)
    assert info2["dropped"] == 2 and info2["folded"] == 0


def test_compat_report_propose_une_option_qui_ameliore_reellement(cfg, tmp_path):
    inst = inst_of(cfg, "recorder")
    chemin = str(tmp_path / "gamme.mid")
    # gamme de Ré bémol majeur : sur un profil diatonique de Do, presque tout tombe sur une alteration
    make_midi(chemin, notes=(61, 63, 65, 66, 68, 70, 72, 73))
    stats = {}
    grouped = core.parse_midi(chemin, cfg, stats)
    rapport = core.compat_report(grouped, inst, cfg, stats=stats)
    for cle in ("notes", "playable", "out_of_range", "missing_accidental", "dropped", "drums",
                "shift", "coverage", "options"):
        assert cle in rapport
    assert rapport["notes"] == 8
    assert 0 <= rapport["coverage"] <= 100
    for opt in rapport["options"]:
        assert opt["kind"] in ("transpose", "octave", "omit")
        assert opt["coverage"] > rapport["coverage"], "une option annoncée doit réellement améliorer"
        if opt["kind"] in ("transpose", "octave"):
            mesure = core.coverage_at(grouped, inst, cfg, rapport["shift"] + opt["value"])
            assert mesure == opt["coverage"], "la couverture annoncée doit être celle réellement mesurée"
        assert opt["label"]


def test_compat_report_signale_les_pistes_de_percussion(cfg, tmp_path):
    import mido
    chemin = str(tmp_path / "batterie.mid")
    mid = mido.MidiFile(type=0)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    for n in (60, 62, 64):
        tr.append(mido.Message("note_on", note=n, velocity=90, time=0))
        tr.append(mido.Message("note_off", note=n, velocity=0, time=240))
    for n in (36, 38, 42, 42):
        tr.append(mido.Message("note_on", note=n, velocity=100, channel=9, time=0))
        tr.append(mido.Message("note_off", note=n, velocity=0, channel=9, time=120))
    mid.save(chemin)
    stats = {}
    grouped = core.parse_midi(chemin, cfg, stats)
    assert stats["drums"] == 4 and 9 in stats["channels"]
    rapport = core.compat_report(grouped, inst_of(cfg, "recorder"), cfg, stats=stats)
    assert rapport["drums"] == 4, "les frappes ignorées doivent être annoncées, pas transformées en mélodie"
    assert rapport["notes"] == 3


# ================================================================ 8. collisions
def test_deux_notes_sur_la_meme_touche_sont_refusees(cfg):
    problemes = instruments.conflicts({60: "a", 62: "a", 64: "s"}, cfg)
    doublons = [c for c in problemes if c["kind"] == "duplicate"]
    assert len(doublons) == 1
    assert doublons[0]["midi"] == 62 and doublons[0]["key"] == "a"
    assert doublons[0]["severity"] == "error"
    assert instruments.blocking(problemes) is True


def test_collision_avec_l_arret_refusee_et_raccourci_jamais_supprime(cfg):
    cfg["hotkeys"] = dict(cfg.get("hotkeys") or {})
    cfg["hotkeys"]["stop"] = "k"
    cfg["hotkeys"]["next_song"] = "n"
    problemes = instruments.conflicts({60: "k", 62: "n"}, cfg)
    arret = [c for c in problemes if c["kind"] == "hotkey" and c["key"] == "k"]
    autre = [c for c in problemes if c["kind"] == "hotkey" and c["key"] == "n"]
    assert arret and arret[0]["severity"] == "error", "l'arrêt doit rester accessible"
    assert autre and autre[0]["severity"] == "warn", "un raccourci non vital n'interdit pas le mapping"
    assert instruments.blocking(problemes) is True
    assert cfg["hotkeys"]["stop"] == "k", "un raccourci d'arrêt n'est jamais supprimé pour un mapping"


def test_touche_non_injectable_refusee(cfg):
    problemes = instruments.conflicts({60: "f13", 62: "s"}, cfg)
    mauvaise = [c for c in problemes if c["kind"] == "not-injectable"]
    assert mauvaise and mauvaise[0]["severity"] == "error"
    assert instruments.blocking(problemes) is True


def test_avertissement_maj_seulement_en_azerty_et_mode_code_virtuel(cfg):
    cfg["keyboard_layout"] = "azerty"
    cfg["input_mode"] = "vk"
    problemes = instruments.conflicts({60: "2", 62: "s"}, cfg)
    maj = [c for c in problemes if c["kind"] == "shift"]
    assert maj and maj[0]["severity"] == "warn", "on avertit, on n'injecte pas un Maj automatique"
    assert instruments.blocking(problemes) is False
    cfg["input_mode"] = "scancode"
    assert [c for c in instruments.conflicts({60: "2"}, cfg) if c["kind"] == "shift"] == [], \
        "en mode scancode c'est la position qui part : rien à compenser"


def test_l_assistant_refuse_d_enregistrer_un_mapping_en_conflit(api_stub):
    api, cfg = api_stub
    cfg["hotkeys"]["stop"] = "b"                        # position absente de la disposition à 15 notes
    api.instrument_wizard_start("recorder", "setup")
    assert api._wizard is not None
    api.instrument_wizard_bind(60, "b")                 # la note prend la touche d'arrêt
    avant = json.dumps(cfg["instruments"]["recorder"], sort_keys=True)
    api.instrument_wizard_save()
    assert api._wizard is not None, "l'assistant reste ouvert tant que le conflit n'est pas réglé"
    assert json.dumps(cfg["instruments"]["recorder"], sort_keys=True) == avant, \
        "un profil en conflit avec l'arrêt a été enregistré"
    assert any("refus" in t["msg"].lower() for t in api._toasts)
    assert cfg["hotkeys"]["stop"] == "b", "le raccourci d'arrêt n'est jamais sacrifié à un mapping"
    api.instrument_wizard_bind(60, "k")                 # correction : la touche de la disposition
    api.instrument_wizard_save()
    assert api._wizard is None
    assert cfg["instruments"]["recorder"]["verificationStatus"] in instruments.STATUSES


# ================================================================ 9. notes tenues
def test_deux_notes_sur_une_meme_touche_ne_relachent_pas_trop_tot(cfg):
    inst = inst_of(cfg, "recorder")
    assert inst.key_for(60) == inst.bindings[60]
    # 60 et 61 tombent sur la meme touche (61 est une alteration absente, repliee sur 60)
    grouped = [(0.0, [(60, 1.2, 90)]), (2.0, [(61, 0.8, 90)])]
    events, _ = core.fit_notes(grouped, inst, cfg, shift=0)
    touches = {k for _, ks, _ in events for k in ks}
    assert len(events) == 2 and len(touches) == 1, "les deux notes doivent viser la même position"
    timeline = core.build_timeline(events, "game", 0.04, "note", 4.0)
    ouvertes = {}
    for t, _, kind, data in timeline:
        for k in data:
            if kind == "on":
                assert ouvertes.get(k) is None, f"{k} pressée deux fois sans relâchement"
                ouvertes[k] = t
            else:
                assert ouvertes.get(k) is not None, f"{k} relâchée sans avoir été pressée"
                assert t > ouvertes[k], f"{k} relâchée avant d'être pressée"
                ouvertes[k] = None
    assert all(v is None for v in ouvertes.values()), "une touche reste enfoncée à la fin"
    premier_off = next(t for t, _, kind, _ in timeline if kind == "off")
    assert premier_off >= 1.0, "la première note a été coupée par la seconde, pourtant bien plus tard"


def test_notes_rapprochees_sur_une_meme_touche_restent_deux_frappes(cfg):
    inst = inst_of(cfg, "recorder")
    grouped = [(0.0, [(60, 1.5, 90)]), (0.30, [(61, 0.5, 90)])]
    events, _ = core.fit_notes(grouped, inst, cfg, shift=0)
    timeline = core.build_timeline(events, "game", 0.04, "note", 4.0)
    ons = [t for t, _, kind, _ in timeline if kind == "on"]
    offs = [t for t, _, kind, _ in timeline if kind == "off"]
    assert len(ons) == 2 and len(offs) == 2
    assert offs[0] < ons[1], "la touche doit être relâchée avant d'être re-frappée"
    assert ons[1] - offs[0] > 0, "sans relâchement, le jeu ne verrait qu'une seule frappe"
    assert offs[0] > ons[0]


def test_silence_relache_toutes_les_touches_tenues(cfg, player, no_real_keys):
    player._held = ["y", "u"]
    player._silence()
    assert player._held == []
    montees = [c for c in no_real_keys if c[1] is True]
    assert montees, "aucun relâchement envoyé"
    assert set(montees[-1][0]) == {"y", "u"}


def test_stop_relache_les_touches_a_l_arret(cfg, player, no_real_keys, monkeypatch):
    add_song(player, "essai.mid")
    player.refresh_songs()
    monkeypatch.setitem(player.cfg, "start_delay", 0.05)
    monkeypatch.setitem(player.cfg, "stop_on_input", False)
    player.play("game")
    import time as _t
    fin = _t.perf_counter() + 3.0
    while _t.perf_counter() < fin and not [c for c in no_real_keys if c[1] is False]:
        _t.sleep(0.01)
    player.stop(join=True)
    assert player.state == "stopped"
    assert player._held == [], "des touches restent tenues après l'arrêt"
    bas, haut = {}, {}
    for touches, up, _ in no_real_keys:
        for k in touches:
            cible = haut if up else bas
            cible[k] = cible.get(k, 0) + 1
    assert bas, "la lecture n'a envoyé aucune touche : le test ne prouve rien"
    for k in bas:
        assert haut.get(k, 0) >= 1, f"la touche {k} a été enfoncée sans jamais être relâchée"


# ================================================================ 10. changement de profil pendant une lecture
def test_changement_d_instrument_refuse_pendant_la_lecture(cfg, player, no_real_keys, monkeypatch):
    add_song(player, "essai.mid")
    player.refresh_songs()
    monkeypatch.setitem(player.cfg, "start_delay", 0.05)
    monkeypatch.setitem(player.cfg, "stop_on_input", False)
    assert player.set_instrument("piano")[0]
    player.play("game")
    import time as _t
    fin = _t.perf_counter() + 3.0
    while _t.perf_counter() < fin and player.state != "playing":
        _t.sleep(0.01)
    assert player.state == "playing"
    ok, msg = player.set_instrument("recorder")
    assert ok is False
    assert "arrête la lecture" in msg.lower()
    assert player.instrument.id == "piano"
    player.stop(join=True)
    ok, msg = player.set_instrument("recorder")
    assert ok is True and msg == ""
    assert player.instrument.id == "recorder"
    assert cfg["instrument"] == "recorder"


def test_next_instrument_ne_passe_que_sur_des_profils_prets(a_relever, cfg, player):
    assert player.set_instrument("piano")[0]
    vus = set()
    for _ in range(len(player.instruments) + 2):
        ok, _msg = player.next_instrument()
        assert ok
        assert player.instrument.ready is True
        vus.add(player.instrument.id)
    assert "conch" not in vus and "cajon" not in vus
    assert {"piano", "recorder", "lute"} <= vus


def test_changement_de_disposition_refuse_pendant_la_lecture(api_stub, monkeypatch, no_real_keys):
    api, cfg = api_stub
    player = api._player
    add_song(player, "essai.mid")
    player.refresh_songs()
    monkeypatch.setitem(cfg, "start_delay", 0.05)
    monkeypatch.setitem(cfg, "stop_on_input", False)
    assert player.set_instrument("wooden-bass")[0]
    avant = dict(cfg["instruments"]["wooden-bass"])
    player.play("game")
    import time as _t
    fin = _t.perf_counter() + 3.0
    while _t.perf_counter() < fin and player.state != "playing":
        _t.sleep(0.01)
    assert player.state == "playing"
    api.set_instrument_layout("wooden-bass", "diatonic-15-2row")
    assert cfg["instruments"]["wooden-bass"] == avant, "la disposition a changé sous une note tenue"
    player.stop(join=True)
    api.set_instrument_layout("wooden-bass", "diatonic-15-2row")
    assert cfg["instruments"]["wooden-bass"]["layoutId"] == "diatonic-15-2row"


# ================================================================ 11. libellés AZERTY / QWERTY
def test_key_label_lettres_chiffres_et_ponctuation():
    # lettres : majuscules, et la position US traduite en legende francaise
    assert instruments.key_label("q", "qwerty") == "Q"
    assert instruments.key_label("q", "azerty") == "A"
    assert instruments.key_label("a", "azerty") == "Q"
    assert instruments.key_label("z", "azerty") == "W"
    assert instruments.key_label("w", "azerty") == "Z"
    # chiffres : traites separement, jamais passes en majuscule
    assert instruments.key_label("2", "qwerty") == "2"
    assert instruments.key_label("2", "azerty") == "é"
    assert instruments.key_label("7", "azerty") == "è"
    assert instruments.key_label("0", "azerty") == "à"
    # ponctuation : traitee separement des lettres
    assert instruments.key_label(";", "azerty") == "M"
    assert instruments.key_label("m", "azerty") == ","
    assert instruments.key_label(",", "azerty") == ";"
    assert instruments.key_label("/", "azerty") == "!"
    assert instruments.key_label("'", "azerty") == "ù"
    assert instruments.key_label("[", "azerty") == "^"
    assert instruments.key_label("/", "qwerty") == "/"
    assert instruments.key_label("", "azerty") == ""


def test_libelles_azerty_couvrent_toutes_les_positions_injectables():
    assert set(instruments.AZERTY_LABELS) == set(platform_io.SCANCODES), \
        "chaque position injectable doit avoir une légende AZERTY"
    legendes = list(instruments.AZERTY_LABELS.values())
    assert len(set(legendes)) == len(legendes), "deux positions portent la même légende AZERTY"


def test_key_needs_shift_avertit_sans_rien_injecter():
    assert instruments.key_needs_shift("2", "azerty") is True
    assert instruments.key_needs_shift("0", "azerty") is True
    assert instruments.key_needs_shift("2", "qwerty") is False
    assert instruments.key_needs_shift("q", "azerty") is False
    assert instruments.key_needs_shift(";", "azerty") is False
    assert instruments.key_needs_shift("", "azerty") is False


def test_la_position_envoyee_ne_depend_pas_de_la_disposition_du_clavier(cfg):
    """Le libellé change, la position envoyée au jeu non."""
    qwerty = instruments.build_instruments(cfg, ROOT)
    cfg["keyboard_layout"] = "azerty"
    azerty = instruments.build_instruments(cfg, ROOT)
    for a, b in zip(qwerty, azerty):
        assert a.id == b.id
        assert a.bindings == b.bindings, f"{a.id} : les positions envoyées ont changé avec le clavier"
    piano = instruments.find_instrument(azerty, "piano")
    assert piano.bindings[60] == "z"
    assert instruments.key_label("z", "azerty") == "W", "seul le libellé affiché change"


def test_resolve_keyboard_layout():
    assert instruments.resolve_keyboard_layout("azerty") == "azerty"
    assert instruments.resolve_keyboard_layout("qwerty") == "qwerty"
    assert instruments.resolve_keyboard_layout("auto") in instruments.KEYBOARD_LAYOUTS
    assert instruments.resolve_keyboard_layout("klingon") in instruments.KEYBOARD_LAYOUTS


# ================================================================ assistant : harnais léger
class _FakeRoom:
    """Salon inerte : l'assistant prévient le salon d'un changement d'instrument, rien de plus ici."""

    def __init__(self):
        self.state = "idle"
        self.changes = []

    def on_instrument_change(self, inst):
        self.changes.append(getattr(inst, "id", inst))

    def active(self):
        return False

    def stop_request(self, reason=""):
        return False


class _FakeSync:
    def active(self):
        return False

    def abort(self, reason=""):
        return None


@pytest.fixture
def api_stub(cfg, no_real_keys):
    """`app.Api` sans fenêtre, sans raccourcis globaux et sans service en ligne.

    On ne construit pas l'Api complète (elle ouvre une WebView, des fils réseau et des raccourcis système) :
    on pose juste ce dont les méthodes « instruments » ont besoin. `get_state()` est neutralisé, les tests
    regardent la config écrite et les toasts, pas l'état d'affichage."""
    api = object.__new__(app.Api)
    cfg["terms_accepted_version"] = __import__("terms").TERMS_VERSION   # CGU acceptées : les actions passent
    api._cfg = cfg
    api._cat = instruments.load_catalogue(ROOT)
    api._logs = deque(maxlen=50)
    api._toasts = deque(maxlen=10)
    api._toast_seq = 0
    api._ui_lock = threading.RLock()
    api._error = None
    api._last_sync_msg = ""
    api._songs_cache = None
    api._game_window = ({"found": None, "foreground": None, "elevated": None}, 0.0)
    api._window = None
    api._minimized = False
    api._wizard = None
    api._hotkeys_off = 0
    api._capture_since = 0.0
    api._kb_layout = instruments.resolve_keyboard_layout(cfg.get("keyboard_layout", "auto"))
    api._compat = None
    api._compat_key = None
    api._compat_notes = None
    api._room = _FakeRoom()
    api._sync = _FakeSync()
    api._player = core.Player(cfg, log=lambda m: None)
    api._player.room = api._room
    api._player.sync = api._sync
    api.get_state = lambda: {}
    yield api, cfg
    api._player.stop(join=True)


def test_assistant_ne_devine_aucune_touche_pour_un_type_a_relever(a_relever, api_stub):
    api, cfg = api_stub
    api.instrument_wizard_start("conch", "setup")
    w = api._wizard
    assert w is not None and w["bindings"] == {}
    assert all(c["documented"] is False for c in w["layouts"]), \
        "aucune disposition n'est documentée pour ce type"
    api.instrument_wizard_layout("diatonic-15-3row", prefill=True)
    assert api._wizard["bindings"] == {}, "des touches ont été héritées d'un autre instrument"
    etat = api.instrument_wizard_state()
    assert etat["total"] == 15 and etat["bound"] == 0
    assert etat["can_save"] is False


def test_assistant_enregistre_la_disposition_reellement_choisie(api_stub, cat):
    """Changer de disposition dans l'assistant doit changer la table enregistrée, pas seulement l'affichage."""
    api, cfg = api_stub
    api.instrument_wizard_start("wooden-bass", "setup")
    assert api._wizard["layout_id"] == "diatonic-15-3row"
    api.instrument_wizard_layout("diatonic-15-2row", prefill=True)
    assert api._wizard["layout_id"] == "diatonic-15-2row"
    assert api._wizard["bindings"] == cat.layouts["diatonic-15-2row"].bindings()
    api.instrument_wizard_save()
    prof = cfg["instruments"]["wooden-bass"]
    assert prof["layoutId"] == "diatonic-15-2row"
    assert "bindings" not in prof, "table identique à la disposition : rien à stocker"
    bass = instruments.find_instrument(api._player.instruments, "wooden-bass")
    assert bass.keys == [n["key"] for n in cat.layouts["diatonic-15-2row"].notes]


def test_assistant_test_rapide_ne_vaut_pas_validation_integrale(api_stub):
    api, cfg = api_stub
    api.instrument_wizard_start("conga", "setup")
    w = api._wizard
    assert w["percussive"] is True
    assert w["bindings"], "la table candidate sert de point de départ"
    midis = sorted(w["bindings"])[:3]
    w["test"] = {"state": "answer", "midis": midis, "keys": [w["bindings"][m] for m in midis]}
    api.instrument_wizard_answer(True, "frappe grave au centre de la peau")
    assert api._wizard["tested"] is True
    etat = api.instrument_wizard_state()
    assert etat["next_status"] == "quick-tested", "trois frappes ne confirment pas 15 associations"
    assert etat["next_status_label"] == instruments.status_label("quick-tested")
    api.instrument_wizard_save()
    prof = cfg["instruments"]["conga"]
    assert prof["verificationStatus"] == "quick-tested"
    assert prof["verifiedAt"]
    conga = instruments.find_instrument(api._player.instruments, "conga")
    assert conga.ready is True, "après le test des frappes, la conga devient jouable"


def test_assistant_annule_sans_ecraser_un_profil_valide(api_stub):
    api, cfg = api_stub
    avant = json.dumps(cfg["instruments"]["recorder"], sort_keys=True)
    api.instrument_wizard_start("recorder", "setup")
    api.instrument_wizard_bind(60, "b")
    api.instrument_wizard_cancel()
    assert api._wizard is None
    assert json.dumps(cfg["instruments"]["recorder"], sort_keys=True) == avant


def test_assistant_refuse_une_touche_non_injectable(api_stub):
    api, _cfg = api_stub
    api.instrument_wizard_start("recorder", "setup")
    api.instrument_wizard_bind(60, "F13")
    assert api._wizard["bindings"][60] != "f13"
    assert "envoyée au jeu" in api._wizard["message"]


def test_changement_de_clavier_invalide_les_conclusions_sans_perdre_les_touches(api_stub):
    api, cfg = api_stub
    instruments.set_profile(cfg, "recorder", bindings={60: "b", 62: "n"},
                            status=instruments.STATUS_CONFIRMED, verified_at="2026-09-15T10:00:00")
    api._rebuild_instruments()
    # on bascule vers l'AUTRE disposition que celle en vigueur : le test ne dépend pas du clavier de la machine
    autre = "qwerty" if api._keyboard_layout() == "azerty" else "azerty"
    cfg["keyboard_layout"] = autre
    api._on_keyboard_layout()
    prof = cfg["instruments"]["recorder"]
    assert prof["verificationStatus"] == "custom", "une conclusion prise sur l'ancien clavier n'est plus garantie"
    assert prof["verifiedAt"] is None
    assert prof["bindings"] == {"60": "b", "62": "n"}, "les touches personnalisées ont été supprimées"


def test_import_de_profil_ne_rejoue_pas_une_validation_faite_ailleurs(api_stub):
    api, cfg = api_stub
    charge = {"format": "dodotopia-instrument-profile", "schemaVersion": 1, "instrumentId": "lute",
              "layoutId": "diatonic-15-3row", "verificationStatus": "confirmed",
              "verifiedAt": "2026-01-01T00:00:00",
              "bindings": {"60": "y", "62": "u", "64": "i", "999": "z", "65": "f13"}}
    api.import_instrument_profile(json.dumps(charge, ensure_ascii=False))
    prof = cfg["instruments"]["lute"]
    assert prof["verificationStatus"] == "custom", "un « confirmé » ailleurs reste à vérifier ici"
    assert prof["verifiedAt"] is None
    assert set(prof["bindings"]) == {"60", "62", "64"}, "les entrées invalides doivent être filtrées"


def test_export_de_profil_ne_contient_que_des_donnees(api_stub):
    api, _cfg = api_stub
    r = api.export_instrument_profile("piano", path=None)
    assert r["ok"] is True
    charge = r["payload"]
    assert charge["instrumentId"] == "piano"
    assert charge["format"] == "dodotopia-instrument-profile"
    assert all(k in platform_io.SCANCODES for k in charge["bindings"].values())
    assert json.loads(r["text"])["layoutId"] == "piano-chromatic-37"
    for interdit in ("skinId", "selectedVariantId", "path", "command"):
        assert interdit not in charge


# ================================================================ état renvoyé à l'interface
def test_to_dict_leger_et_stable(cfg):
    inst = inst_of(cfg, "piano")
    d = inst.to_dict()
    attendu = {"id", "name", "label_en", "category", "image", "kind", "keys", "count", "layout_id",
               "layout_label", "status", "ready", "percussive", "custom", "blocked_reason",
               "lowest", "span", "aliases", "variant_count"}
    assert set(d) == attendu, "le contrat d'état léger a changé (app.py / ui/ le lisent à chaque tick)"
    assert "notes" not in d and "rows" not in d, "pas de table de notes dans l'état de chaque tick"
    assert d["count"] == len(d["keys"]) == 37
    assert d["kind"] == "chromatique"
    assert json.dumps(d)                                   # serialisable tel quel vers l'interface


def test_empreinte_change_avec_le_profil(cfg, cat):
    avant = inst_of(cfg, "recorder").fingerprint
    instruments.set_profile(cfg, "recorder", bindings={60: "b", 62: "n"},
                            status=instruments.STATUS_CUSTOM)
    cfg["_instruments"] = instruments.build_instruments(cfg, ROOT)
    apres = inst_of(cfg, "recorder").fingerprint
    assert avant != apres, "la chronologie d'un salon serait rejouée avec l'ancien profil"


def test_build_instruments_suit_l_ordre_du_catalogue(cfg, cat):
    assert [i.id for i in cfg["_instruments"]] == [t.id for t in cat.types]
    assert len(cfg["_instruments"]) == 19


# ================================================================ 12. régressions corrigées après revue
# Un test par défaut confirmé. Ils ne rejouent aucun composant visuel : ceux qui touchent à `ui/` vérifient
# uniquement le CONTRAT entre Python et l'interface (nom de clé, méthode appelée), pas une mise en page.

UI_DIR = os.path.join(ROOT, "ui")


def ui_source(name):
    with open(os.path.join(UI_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def _wizard_ready(api, instrument_id="recorder", mode="setup"):
    """Ouvre l'assistant sur un type déjà documenté (table de départ non vide)."""
    api.instrument_wizard_start(instrument_id, mode)
    assert api._wizard is not None and api._wizard["bindings"]
    return api._wizard


# ---- défauts 1 et 12 : le compte à rebours du test
def test_la_validation_integrale_couvre_toutes_les_associations(api_stub, cfg):
    api, cfg = api_stub
    w = _wizard_ready(api, "recorder", "full")
    total = len(w["bindings"])
    groupes = []
    for _ in range(total):                       # borne large : 15 notes par groupes de 3
        etat = api.instrument_wizard_state()
        if etat["next_status"] == instruments.STATUS_CONFIRMED:
            break
        api.instrument_wizard_test()             # aucun midi imposé : c'est le moteur qui échantillonne
        test = api._wizard["test"]
        groupes.append(tuple(test["midis"]))
        test["state"] = "answer"                 # le fil s'arrête de lui-même, aucune touche n'est envoyée
        api.instrument_wizard_answer(True)
    etat = api.instrument_wizard_state()
    assert etat["next_status"] == instruments.STATUS_CONFIRMED
    assert len(groupes) == len(set(groupes)), "deux passages ont rejoué exactement le même groupe"
    assert sorted(m for g in groupes for m in g) == sorted(w["bindings"]), \
        "toutes les associations doivent être passées, sans doublon"
    api.instrument_wizard_save()
    assert cfg["instruments"]["recorder"]["verificationStatus"] == instruments.STATUS_CONFIRMED
    assert "openInstrumentWizard(id, 'full')" in ui_source("instruments.js"), \
        "sans point d'entrée dans l'interface, le statut « confirmé » resterait inatteignable"


def test_un_seul_groupe_ne_donne_jamais_confirme(api_stub):
    api, _ = api_stub
    w = _wizard_ready(api, "recorder", "full")
    api.instrument_wizard_test()
    api._wizard["test"]["state"] = "answer"
    api.instrument_wizard_answer(True)
    etat = api.instrument_wizard_state()
    assert etat["next_status"] == instruments.STATUS_QUICK
    assert len(etat["verified"]) < len(w["bindings"])


# ---- défaut 3 : une erreur d'injection ne laisse ni touche enfoncée ni lecteur bloqué
def test_une_erreur_d_injection_ne_bloque_pas_le_lecteur(cfg, monkeypatch):
    p = core.Player(cfg, log=lambda m: None)
    envois = {"n": 0}

    def send_qui_casse(keys, up=False, mode="scancode"):
        envois["n"] += 1
        if envois["n"] >= 2:
            raise OSError("injection impossible")

    monkeypatch.setattr(core, "send_keys", send_qui_casse)
    timeline = [(0.0, 0, "on", ["a"]), (0.01, 1, "on", ["s"]), (0.02, 2, "off", ["a"])]
    prepared = {"song": "essai.mid", "events": [], "timeline": timeline, "duration": 0.1,
                "info": {"shift": 0, "folded": 0, "snapped": 0, "dropped": 0, "hits": 3, "notes": 3,
                         "out_of_range": 0, "missing_accidental": 0, "exact": 3, "coverage": 100}}
    p.state, p.target = "playing", "game"
    p._stop.clear()
    p._pause.clear()
    p._held = []
    p._run("essai.mid", p.instrument, "game", deadline=time.perf_counter(), prepared=prepared)
    assert p.state == "stopped", "le lecteur resterait « playing » pour toujours"
    assert p._held == [], "une touche serait restée enfoncée dans le jeu"
    assert p.set_instrument("recorder")[0] is True, "changer d'instrument redevient possible"


def test_une_vitesse_illisible_ne_fait_pas_mourir_le_fil(cfg):
    cfg["speed"] = 0
    p = core.Player(cfg, log=lambda m: None)
    assert p.speed >= core.SPEED_MIN, "speed = 0 provoquait une division par zéro dans la boucle"
    p.set_speed(99)
    assert p.speed == core.SPEED_MAX


# ---- défaut 4 : sortie anticipée de _start (instrument non prêt armé par un salon)
def test_un_instrument_non_pret_ne_fige_pas_le_lecteur_en_sync(a_relever, cfg):
    p = core.Player(cfg, log=lambda m: None)
    ids = [i.id for i in p.instruments]
    p.inst_index = ids.index("conch")
    assert p.instrument.ready is False
    with p._lock:                                  # room._arm force « sync » puis appelle play_at
        p.state = "sync"
        p._start("game", time.perf_counter() + 0.5, {"song": "x.mid", "events": [], "timeline": [],
                                                     "info": {}, "duration": 0.0})
    assert p.state == "stopped", "l'état « sync » restait figé : plus aucun changement d'instrument possible"
    assert p.set_instrument("piano")[0] is True


def test_stop_debloque_un_etat_sync_sans_fil(cfg):
    p = core.Player(cfg, log=lambda m: None)
    p.state = "sync"
    p.stop()
    assert p.state == "stopped" and p._held == []


# ---- défaut 5 : pas d'écriture de profil pendant la lecture de cet instrument
def test_enregistrer_un_profil_pendant_la_lecture_est_refuse(api_stub):
    api, cfg = api_stub
    _wizard_ready(api, "piano")
    api.instrument_wizard_bind(60, "f")
    avant = json.dumps(cfg["instruments"]["piano"], sort_keys=True)
    api._player.state = "playing"                  # la lecture a démarré depuis l'assistant ouvert (F6)
    try:
        r = api.instrument_wizard_save()
    finally:
        api._player.state = "stopped"
    assert r["ok"] is False and "lecture" in r["error"].lower()
    assert json.dumps(cfg["instruments"]["piano"], sort_keys=True) == avant, \
        "le profil de l'instrument en cours de lecture a été réécrit sous ses pieds"
    assert api._wizard is not None, "l'assistant reste ouvert : rien n'est perdu"
    r = api.instrument_wizard_save()
    assert r["ok"] is True
    assert json.dumps(cfg["instruments"]["piano"], sort_keys=True) != avant


# ---- défaut 6 : le verdict d'enregistrement est explicite
def test_instrument_wizard_save_renvoie_un_verdict(api_stub):
    api, cfg = api_stub
    api._wizard = None
    r = api.instrument_wizard_save()
    assert set(r) == {"ok", "error", "state"} and r["ok"] is False and r["error"]
    cfg["hotkeys"]["stop"] = "b"
    _wizard_ready(api, "recorder")
    api.instrument_wizard_bind(60, "b")
    r = api.instrument_wizard_save()
    assert r["ok"] is False and "refus" in r["error"].lower()
    src = ui_source("instruments.js")
    assert "r.ok === false" in src, "l'interface doit lire le verdict avant d'annoncer « Profil enregistré »"


# ---- défaut 7 : missing_notes suit le contrat (liste d'entiers)
def test_missing_notes_est_une_liste_d_entiers(api_stub):
    api, _ = api_stub
    d = api.get_instrument_detail("recorder")
    assert d["missing_notes"], "une disposition diatonique a des altérations absentes"
    assert all(isinstance(m, int) for m in d["missing_notes"]), \
        "des dicts ici donnaient « NaN, NaN » dans la fiche du sélecteur"
    assert all(isinstance(x, dict) for x in d["missing_notes_detail"])


# ---- défauts 8 et 9 : les options de compatibilité sont des écarts, appliqués par song_compat_apply
def _grouped_hors_registre():
    """Morceau de test : quelques notes dans le registre, quelques-unes très au-dessus."""
    notes = [36, 38, 60, 62, 64, 96, 98, 100]
    return [(0.5 * i, [(n, 0.4, 100)]) for i, n in enumerate(notes)]


def test_les_options_de_transposition_sont_des_ecarts(api_stub):
    api, cfg = api_stub
    inst = api._player.instrument
    grouped = _grouped_hors_registre()
    cfg["transpose_semitones"] = -3
    rapport = core.compat_report(grouped, inst, cfg)
    opts = [o for o in rapport["options"] if o["kind"] in ("transpose", "octave")]
    assert opts, "ce morceau doit produire au moins une adaptation proposée"
    o = opts[0]
    assert core.coverage_at(grouped, inst, cfg, rapport["shift"] + o["value"]) == o["coverage"], \
        "la couverture annoncée est celle de l'ÉCART ajouté au décalage retenu, pas d'une valeur absolue"
    api.song_compat_apply(o["kind"], o["value"])
    assert cfg["transpose_semitones"] == max(-24, min(24, -3 + o["value"])), \
        "écrire la valeur brute écraserait la transposition manuelle de l'utilisateur"
    bloc = ui_source("music.js").split("function applyCompatOption(")[1].split("\nfunction ")[0]
    assert "api('song_compat_apply', kind, v)" in bloc, \
        "l'interface doit passer par la méthode qui additionne l'écart à la transposition en cours"
    assert "set_setting" not in bloc, "écrire une valeur absolue ici écraserait la transposition manuelle"


def test_l_option_omettre_est_applicable_et_reversible(api_stub):
    api, cfg = api_stub
    inst = api._player.instrument
    grouped = _grouped_hors_registre()
    rapport = core.compat_report(grouped, inst, cfg)
    assert rapport["out_of_range"] and rapport["folded"], \
        "par défaut les notes hors registre sont REPLIÉES, pas passées"
    assert any(o["kind"] == "omit" for o in rapport["options"]), "l'omission doit être proposée"
    api.song_compat_apply("omit")
    assert cfg["fold_out_of_range"] is False
    retour = core.compat_report(grouped, inst, cfg)
    assert retour["dropped"] and not retour["folded"]
    assert any(o["kind"] == "fold" for o in retour["options"]), \
        "un réglage à sens unique serait invisible dans les Réglages : le retour doit être proposé"
    api.song_compat_apply("fold")
    assert cfg["fold_out_of_range"] is True


# ---- défaut 10 : le focus entre dans l'assistant et le piège de focus se rattrape
def test_l_assistant_prend_le_focus_et_le_piege_se_rattrape():
    inst_src = ui_source("instruments.js")
    assert "$('wizBody'); if(b && $('wizOverlay').classList.contains('open')) b.focus();" in inst_src, \
        "sans focus explicite, la tabulation repartait dans les commandes du lecteur"
    core_src = ui_source("core.js")
    assert "!box.contains(document.activeElement)" in core_src, \
        "le piège de focus doit ramener le focus quand il est resté hors de la modale"


# ---- défaut 11 : l'arrêt annoncé coupe vraiment le test
def test_sous_880px_le_selecteur_defile_au_lieu_d_ecraser_la_grille():
    css = ui_source("app.css")
    bloc = css.split("@media (max-width:880px){")[1].split("@media")[0]
    assert "overflow:auto" in bloc, "le corps doit défiler d'un seul bloc"
    assert "max-height:none" in bloc, \
        "la fiche plafonnée à 46vh réduisait la grille des 19 cartes à quelques pixels"
    assert "grid-template-rows:auto minmax(0,1fr)" not in bloc


# ---- défaut 15 : l'export / import de profil est atteignable
def test_l_export_et_l_import_de_profil_ont_un_point_d_entree(api_stub):
    api, _ = api_stub
    r = api.export_instrument_profile("recorder")
    assert r["ok"] and r["payload"]["instrumentId"] == "recorder" and r["payload"]["bindings"]
    src = ui_source("instruments.js")
    assert "export_instrument_profile" in src and "import_instrument_profile" in src, \
        "README annonce l'export/import : il doit exister un point d'entrée dans l'interface"
