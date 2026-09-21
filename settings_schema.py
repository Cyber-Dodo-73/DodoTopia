# -*- coding: utf-8 -*-
"""Schéma des réglages de DodoTopia : un seul endroit pour les bornes, les unités et les valeurs par défaut.

L'interface enregistre chaque champ dès qu'il change (`Api.set_setting(path, value)`) : ce module valide,
borne et convertit la valeur (l'interface parle en millisecondes pour tout ce qui dure moins d'une seconde,
la config reste en secondes), puis dit quel effet de bord appliquer. `Api.reset_settings(section)` remet
une section à ses valeurs par défaut sans toucher aux autres.

Chemins : "start_delay", "hotkeys.play_pause", "multi.countdown", "draw.formats.16:9.cols", "online.server_url".
"""
import copy

import cook
import core
import draw
import i18n
import sync

try:
    import online
    _ONLINE_DEFAULTS = dict(online.DEFAULT_ONLINE)
except Exception:  # noqa - module absent tant que la partie en ligne n'est pas livrée
    _ONLINE_DEFAULTS = {"server_url": "", "check_updates": True}


class SettingError(ValueError):
    """Valeur refusée : le message (traduit par i18n.t) est affiché sous le champ."""


# Raccourcis globaux, dans l'ordre du panneau Réglages ; leurs libellés sont les clés
# `settings.hotkeys.<nom>.label` du catalogue de l'interface (voir hotkey_label).
HOTKEY_NAMES = ("play_pause", "stop", "next_song", "prev_song", "speed_down", "speed_up", "next_instrument",
                "draw_point")
I18N_KEYS = ["settings.hotkeys.play_pause.label", "settings.hotkeys.stop.label", "settings.hotkeys.next_song.label",
             "settings.hotkeys.prev_song.label", "settings.hotkeys.speed_down.label", "settings.hotkeys.speed_up.label",
             "settings.hotkeys.next_instrument.label", "settings.hotkeys.draw_point.label",
             # intégrations (Discord, OBS) : champs ajoutés par l'interface à partir de leur chemin
             "settings.online.rich_presence.label", "settings.online.rich_presence.help",
             "settings.online.now_playing_file.label", "settings.online.now_playing_file.help"]


def hotkey_label(name):
    """Libellé affiché d'un raccourci (langue courante)."""
    return i18n.t(f"settings.hotkeys.{name}.label")


def hotkey_labels():
    return {name: hotkey_label(name) for name in HOTKEY_NAMES}


# ---------------------------------------------------------------- description des champs
def Num(lo, hi, unit="", scale=1.0, step=None, section="lecture", after=None):
    """Nombre réel. `scale` : valeur affichée = valeur stockée × scale (1000 pour secondes → ms)."""
    return {"type": "num", "min": lo, "max": hi, "unit": unit, "scale": scale, "step": step,
            "section": section, "after": after}


def Int(lo, hi, unit="", section="lecture", after=None):
    return {"type": "int", "min": lo, "max": hi, "unit": unit, "scale": 1, "section": section, "after": after}


def Bool(section="lecture", after=None):
    return {"type": "bool", "section": section, "after": after}


def Choice(*values, section="lecture", after=None):
    return {"type": "choice", "choices": list(values), "section": section, "after": after}


def Str(maxlen=120, section="lecture", after=None):
    return {"type": "str", "maxlen": maxlen, "section": section, "after": after}


# after : nom de la méthode de Api à appeler après l'écriture (effet de bord)
SCHEMA = {
    # ---- général
    "general.lang": Choice("auto", *i18n.LANGS, section="general", after="_on_lang"),
    # ---- lecture dans le jeu
    "start_delay": Num(0.0, 10.0, "s", step=0.5),
    "stop_on_input": Bool(),
    "hold_mode": Choice("note", "tap"),
    "hold_time": Num(0.01, 0.5, "ms", scale=1000, step=5),
    # planchers d'appui et d'écart entre deux frappes de la même touche (une image à 60 i/s = 16,7 ms)
    "min_press": Num(0.005, 0.06, "ms", scale=1000, step=1),
    "min_gap": Num(0.005, 0.06, "ms", scale=1000, step=1),
    # pédale de sustain (CC64) du fichier MIDI : prolonger les notes tenues, ou garder la durée écrite
    "sustain": Bool(),
    "input_mode": Choice("scancode", "vk"),
    # exécutable du jeu : la lecture, le dessin et la cuisine vérifient qu'il est au premier plan
    # (vide = aucune vérification)
    "game_process": Str(64),
    "transpose_semitones": Int(-24, 24, "½ ton", after="_on_transpose"),
    "preview_volume": Int(0, 100, "%", after="_on_volume"),
    # Disposition du clavier physique : ne change que les légendes affichées, jamais la position envoyée
    # au jeu. « auto » = détection système quand elle est fiable, sinon QWERTY.
    "keyboard_layout": Choice("auto", "qwerty", "azerty", after="_on_keyboard_layout"),
    # ---- raccourcis
    "hotkeys.*": {"type": "hotkey", "section": "hotkeys", "after": "_bind_hotkeys"},
    # ---- multi audio
    "multi.player_id": Int(1, sync.MAX_PLAYERS, section="multi"),
    "multi.countdown": Num(3.0, 30.0, "s", step=1, section="multi"),
    "multi.lead": Num(0.8, 3.0, "s", step=0.1, section="multi"),
    "multi.offset_ms": Int(-500, 500, "ms", section="multi"),
    "multi.device": Str(120, section="multi"),
    "multi.mode": Choice("solo", "audio", "room", section="multi", after="_on_play_mode"),
    "multi.name": Str(24, section="multi"),
    "multi.net_offset_ms": Int(-300, 300, "ms", section="multi"),
    # ---- dessin
    "draw.step_delay": Num(0.0, 0.5, "ms", scale=1000, step=5, section="draw"),
    "draw.click_delay": Num(0.0, 1.0, "ms", scale=1000, step=10, section="draw"),
    "draw.glide_speed": Num(0.2, 4.0, "×", step=0.1, section="draw"),
    "draw.fill_background": Bool(section="draw", after="_refresh_draw_stats"),
    "draw.skip_white": Bool(section="draw", after="_refresh_draw_stats"),
    "draw.verify": Bool(section="draw"),
    "draw.dense": Bool(section="draw"),
    "draw.refine": Bool(section="draw"),
    "draw.outline": Bool(section="draw", after="_refresh_draw_stats"),
    "draw.mouse_glide": Bool(section="draw"),
    # les grilles ont leur propre section : « Rétablir » du dessin ne touche pas aux calibrages
    "draw.formats.*.cols": Int(4, 400, section="grids", after="_refresh_draw_stats"),
    "draw.formats.*.rows": Int(4, 400, section="grids", after="_refresh_draw_stats"),
    # ---- cuisine
    "cook.cookers": Int(1, 4, section="cook", after="_on_cookers"),
    "cook.max_dishes": Int(0, 999, section="cook"),
    "cook.cook_timeout": Num(30.0, 900.0, "s", step=10, section="cook"),
    "cook.match": Num(0.3, 0.9, "", step=0.05, section="cook"),
    "cook.green_px": Int(10, 2000, "px", section="cook"),
    "cook.click_delay": Num(0.0, 1.0, "ms", scale=1000, step=10, section="cook"),
    # ---- en ligne
    "online.server_url": Str(200, section="online", after="_on_server_url"),
    "online.check_updates": Bool(section="online", after="_on_check_updates"),
    "online.auto_update": Bool(section="online"),
    # Discord Rich Presence (presence.py) et fichier « en cours de lecture » pour OBS (DATA_DIR/nowplaying.txt)
    "online.rich_presence": Bool(section="online", after="_on_rich_presence"),
    "online.now_playing_file": Bool(section="online", after="_on_now_playing_file"),
}

# valeurs par défaut des intégrations (absentes de online.DEFAULT_ONLINE)
INTEGRATION_DEFAULTS = {"rich_presence": True, "now_playing_file": False}

SECTIONS = ("general", "lecture", "hotkeys", "multi", "draw", "grids", "cook", "online")


# ---------------------------------------------------------------- valeurs par défaut
def defaults():
    """Dict plat chemin → valeur par défaut (seulement les chemins décrits dans SCHEMA)."""
    out = {"general.lang": "auto"}
    for k in ("start_delay", "stop_on_input", "hold_mode", "hold_time", "min_press", "min_gap", "sustain",
              "input_mode", "game_process", "transpose_semitones", "preview_volume", "keyboard_layout"):
        out[k] = core.DEFAULT_CONFIG[k]
    for k, v in core.DEFAULT_CONFIG["hotkeys"].items():
        out["hotkeys." + k] = v
    out["hotkeys.draw_point"] = "F3"
    for k in ("player_id", "countdown", "lead", "offset_ms", "device"):
        out["multi." + k] = sync.DEFAULT_MULTI[k]
    out["multi.mode"] = sync.DEFAULT_MULTI.get("mode", "solo")
    out["multi.name"] = sync.DEFAULT_MULTI.get("name", "")
    out["multi.net_offset_ms"] = sync.DEFAULT_MULTI.get("net_offset_ms", 0)
    for k in ("step_delay", "click_delay", "glide_speed", "fill_background", "skip_white", "verify",
              "dense", "refine", "outline", "mouse_glide"):
        out["draw." + k] = draw.DEFAULT_DRAW[k]
    for fmt in draw.FORMATS:
        cols, rows = draw.DEFAULT_GRIDS[fmt]
        out[f"draw.formats.{fmt}.cols"] = cols
        out[f"draw.formats.{fmt}.rows"] = rows
    for k in ("cookers", "max_dishes", "cook_timeout", "match", "green_px", "click_delay"):
        out["cook." + k] = cook.DEFAULT_COOK.get(k, 1)
    out["online.server_url"] = _ONLINE_DEFAULTS.get("server_url", "")
    out["online.check_updates"] = bool(_ONLINE_DEFAULTS.get("check_updates", True))
    out["online.auto_update"] = bool(_ONLINE_DEFAULTS.get("auto_update", True))
    for k, v in INTEGRATION_DEFAULTS.items():
        out["online." + k] = v
    return out


# ---------------------------------------------------------------- accès par chemin
def _spec(path):
    if path in SCHEMA:
        return SCHEMA[path]
    parts = path.split(".")
    for pattern, spec in SCHEMA.items():
        pp = pattern.split(".")
        if len(pp) == len(parts) and all(a == "*" or a == b for a, b in zip(pp, parts)):
            return spec
    raise SettingError(i18n.t("settings.error.unknown_path", path=path))


def _container(cfg, path, create=False):
    """(dict parent, dernière clé) pour un chemin pointé ; garantit les sous-dicts multi/draw/online."""
    parts = path.split(".")
    if parts[0] == "multi":
        sync.ensure_defaults(cfg)
    elif parts[0] == "draw":
        draw.ensure_defaults(cfg)
    elif parts[0] == "cook":
        cook.ensure_defaults(cfg)
    elif parts[0] == "online":
        cfg.setdefault("online", copy.deepcopy(_ONLINE_DEFAULTS))
    node = cfg
    for p in parts[:-1]:
        if p not in node or not isinstance(node[p], dict):
            if not create:
                raise SettingError(i18n.t("settings.error.unknown_path", path=path))
            node[p] = {}
        node = node[p]
    return node, parts[-1]


def get(cfg, path):
    """Valeur stockée, ou None si le sous-dict n'existe pas encore (format jamais calibré : draw.formats.4:3)."""
    try:
        node, key = _container(cfg, path)
    except SettingError:
        _spec(path)          # le chemin doit au moins être décrit dans SCHEMA
        return None
    return node.get(key)


def to_ui(path, stored):
    """Valeur stockée → valeur affichée (ms, %…)."""
    spec = _spec(path)
    if spec["type"] == "num" and stored is not None:
        v = float(stored) * spec["scale"]
        return round(v) if spec["scale"] != 1.0 else round(v, 3)
    return stored


def validate(path, value, cfg=None):
    """Valeur affichée → valeur stockée, bornée. Lève SettingError avec un message pour l'utilisateur."""
    spec = _spec(path)
    t = spec["type"]
    if t == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "oui", "yes")
        return bool(value)
    if t in ("num", "int"):
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise SettingError(i18n.t("settings.error.number_expected"))
        if t == "num":
            v = v / spec["scale"]
            lo, hi = spec["min"], spec["max"]
            if not lo <= v <= hi:
                raise SettingError(i18n.t("settings.error.range", lo=to_ui(path, lo), hi=to_ui(path, hi),
                                          unit=spec["unit"]).strip())
            return round(v, 4)
        v = int(round(v))
        if not spec["min"] <= v <= spec["max"]:
            raise SettingError(i18n.t("settings.error.range", lo=spec["min"], hi=spec["max"],
                                      unit=spec["unit"]).strip())
        return v
    if t == "choice":
        if value not in spec["choices"]:
            raise SettingError(i18n.t("settings.error.unknown_value"))
        return value
    if t == "str":
        s = str(value or "").strip()
        if len(s) > spec["maxlen"]:
            raise SettingError(i18n.t("settings.error.too_long", max=spec["maxlen"]))
        return s
    if t == "hotkey":
        import platform_io
        s = str(value or "").strip()
        if not s:
            # raccourci désactivé : permis pour les actions facultatives (instrument suivant), jamais pour
            # celles qui rendent la main (lecture / arrêt) ni pour le repère de calibrage
            if path.split(".")[-1] in ("play_pause", "stop", "draw_point"):
                raise SettingError(i18n.t("settings.error.key_required"))
            return ""
        try:
            platform_io.parse_hotkey(s)
        except Exception:
            raise SettingError(i18n.t("settings.error.key_unknown"))
        if core.is_note_key(s):
            # les touches des instruments sont envoyees au jeu par DodoTopia lui-meme : un raccourci global
            # pose sur l'une d'elles se declencherait tout seul pendant la lecture (arret « sans raison »)
            raise SettingError(i18n.t("settings.error.key_is_note"))
        if cfg is not None:
            mine = path.split(".")[-1]
            for name, combo in cfg.get("hotkeys", {}).items():
                if name != mine and combo and combo.lower() == s.lower():
                    label = hotkey_label(name) if name in HOTKEY_NAMES else name
                    raise SettingError(i18n.t("settings.error.hotkey_taken", label=label))
        return s
    raise SettingError(i18n.t("settings.error.unknown_type"))


def set_value(cfg, path, value):
    """Valide puis écrit ; renvoie (valeur stockée, nom de l'effet de bord ou None)."""
    spec = _spec(path)
    v = validate(path, value, cfg)
    node, key = _container(cfg, path, create=True)
    if path.startswith("draw.formats."):
        # une grille saisie à la main n'est plus « validée » par le calibrage automatique
        if node.get(key) != v:
            node["validated"] = False
    node[key] = v
    return v, spec.get("after")


def reset(cfg, section):
    """Remet tous les champs d'une section à leur défaut ; renvoie les effets de bord à appliquer."""
    if section not in SECTIONS:
        raise SettingError(i18n.t("settings.error.unknown_section", section=section))
    afters = []
    for path, dflt in defaults().items():
        if _spec(path)["section"] != section:
            continue
        node, key = _container(cfg, path, create=True)
        if path.startswith("draw.formats."):
            node.pop("validated", None)
        node[key] = copy.deepcopy(dflt)
        a = _spec(path).get("after")
        if a and a not in afters:
            afters.append(a)
    return afters


def for_ui(cfg):
    """Description des champs pour construire l'interface : bornes affichées, unité, défaut, valeur courante."""
    out = {}
    for path, dflt in defaults().items():
        spec = _spec(path)
        cur = get(cfg, path)
        item = {"type": spec["type"], "section": spec["section"], "default": to_ui(path, dflt),
                "value": to_ui(path, dflt if cur is None else cur)}   # absent = valeur effective par défaut
        if spec["type"] in ("num", "int"):
            item.update({"min": to_ui(path, spec["min"]), "max": to_ui(path, spec["max"]),
                         "unit": spec["unit"], "step": spec.get("step") or (1 if spec["type"] == "int" else 0.1)})
        if spec["type"] == "choice":
            item["choices"] = spec["choices"]
        out[path] = item
    return out

