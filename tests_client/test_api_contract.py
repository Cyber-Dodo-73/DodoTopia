# -*- coding: utf-8 -*-
"""Contrat de l'Api exposee a l'interface (pywebview expose toutes les methodes publiques de l'objet).

La classe est composee de mixins (api/*.py) : ce test fige la liste des methodes pour qu'un decoupage ou
une refonte ne fasse jamais disparaitre silencieusement un appel que le JavaScript utilise. Ajouter une
methode = l'ajouter ici (volontairement) ; en retirer une = verifier ui/*.js d'abord."""
import inspect
import os
import re

import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECTED = set("""
accept_terms cook_calibrate cook_calibrate_back cook_calibrate_cancel cook_calibrate_goto cook_calibrate_point
cook_calibrate_skip cook_start cook_stop cook_test dismiss_toast draw_auto_calibrate draw_calibrate
draw_calibrate_back draw_calibrate_cancel draw_calibrate_goto draw_calibrate_point draw_calibrate_skip
draw_set_grid draw_start draw_stop export_instrument_profile get_instrument_catalogue get_instrument_detail
get_i18n get_logo get_settings_schema get_state get_terms import_dialog import_image_dialog import_instrument_profile
import_paths instrument_wizard_answer instrument_wizard_back instrument_wizard_bind instrument_wizard_cancel
instrument_wizard_capture_begin instrument_wizard_capture_end instrument_wizard_clear instrument_wizard_goto
instrument_wizard_layout instrument_wizard_save instrument_wizard_set_layout instrument_wizard_start
instrument_wizard_state instrument_wizard_test instrument_wizard_test_stop load_image multi_calibrate
multi_devices multi_listen_test multi_test next_song online_delete_account online_download online_login online_login_cancel
online_logout online_moderate online_pending online_refresh online_reports online_resolve_report
online_search online_share open_cook_log open_data_folder open_draw_log open_log open_site open_songs_folder
play_game prev_song preview quit remove_song rename_song reset_settings room_cancel room_create room_join
room_leave room_ready room_set_offset room_set_song room_start room_stop room_stop_local save_settings
select_song set_draw_job set_instrument set_instrument_layout set_keyboard_layout set_multi set_play_mode
set_setting set_song_tracks set_speed set_tab song_compat_apply song_compat_preview song_tracks stop test_key
toggle_favorite toggle_instrument_favorite update_check update_dismiss update_download update_install
update_open_folder
deeplink_confirm deeplink_dismiss handle_deeplink protocol_status register_protocol
online_like_song online_import_url gallery_list gallery_share gallery_open gallery_take gallery_like gallery_delete
gallery_report room_exists open_external save_drawing_png
""".split())


def _public_methods():
    return {n for n, v in inspect.getmembers(app.Api) if not n.startswith("_") and callable(v)}


def test_les_methodes_publiques_sont_celles_attendues():
    have = _public_methods()
    missing = EXPECTED - have
    extra = have - EXPECTED
    assert not missing, f"méthodes disparues de l'Api : {sorted(missing)}"
    assert not extra, f"nouvelles méthodes non déclarées dans ce test : {sorted(extra)}"


def test_chaque_appel_du_javascript_existe():
    """Tout `api('nom'…)` des fichiers ui/*.js doit correspondre a une methode publique."""
    have = _public_methods()
    calls = set()
    for name in os.listdir(os.path.join(ROOT, "ui")):
        if name.endswith(".js") and name != "mock.js":
            with open(os.path.join(ROOT, "ui", name), "r", encoding="utf-8") as f:
                calls |= set(re.findall(r"\bapi\(\s*['\"]([A-Za-z_]\w*)['\"]", f.read()))
    unknown = calls - have
    assert not unknown, f"appels JS sans méthode Python : {sorted(unknown)}"


def test_les_mixins_ne_se_marchent_pas_dessus():
    """Une meme methode definie dans deux mixins serait resolue par l'ordre d'heritage sans prevenir."""
    seen = {}
    for cls in app.Api.__mro__[1:]:
        if cls is object:
            continue
        for n, v in vars(cls).items():
            if callable(v) and not n.startswith("__"):
                assert n not in seen, f"{n} défini dans {seen[n].__name__} et {cls.__name__}"
                seen[n] = cls
