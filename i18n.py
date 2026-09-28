# -*- coding: utf-8 -*-
"""Traductions côté Python de DodoTopia : catalogues `ui/i18n/<lang>.json`, choix de la langue, formatage.

Le même moteur existe côté navigateur (`ui/i18n.js`) avec la même grammaire de messages, pour que les
chaînes produites par Python (erreurs, toasts, états) et par l'interface soient interchangeables :

    {name}                                   interpolation (les nombres sont formatés selon la langue)
    {n, plural, =0 {…} one {…} other {…}}    pluriel ; `#` dans une branche = le nombre formaté
    {x, select, a {…} b {…} other {…}}       sélection sur une valeur texte
    {{ et }}                                 accolades littérales (`}}` seulement hors des branches)

Les branches acceptent des messages complets (imbrication : `one {{name} a # musique}`). Une accolade
fermante simple ferme toujours la branche en cours : pour un `}` littéral, sortir de la branche.

Règles de pluriel codées en dur (catégorie parmi zero/one/two/few/many/other) :
    fr → 0 et 1 sont « one » ; en, de, es, pt-BR, it, fil → 1 est « one » ; zh-CN, ja, th, id → « other » seulement.
    (fil : la règle CLDR range aussi 0, 2, 3, 5… dans « one » pour l'usage de « mga » ; on s'en tient à 1,
    plus lisible pour les traducteurs et sans effet sur un nom philippin, qui ne s'accorde pas.)

Clé absente : valeur du catalogue de repli (fr) si elle existe, sinon `[clé]` (un avertissement par clé).

Les messages destinés à l'interface transitent par `Msg(key, params)` : Python ne traduit pas, il envoie la
clé et ses paramètres (`to_dict()`), et le navigateur traduit dans sa langue courante avec `t(key, params)`.
`t()` côté Python sert aux textes qui restent en Python (journal, ligne de commande, serveur).
"""
import json
import locale
import logging
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import NamedTuple

LANGS = ("fr", "en", "es", "de", "pt-BR", "zh-CN", "ja", "th", "id", "fil")
FALLBACK_LANG = "fr"
CATEGORIES = ("zero", "one", "two", "few", "many", "other")
# Nom de règle → catégories que la règle peut produire (« other » toujours incluse).
PLURAL_RULES = {
    "fr": ("one", "other"), "en": ("one", "other"), "de": ("one", "other"), "es": ("one", "other"),
    "pt-BR": ("one", "other"), "it": ("one", "other"), "zh-CN": ("other",), "ja": ("other",), "th": ("other",),
    "id": ("other",), "fil": ("one", "other"),
}
# LANGID primaire Windows (LCID & 0x3FF) → langue ; les sous-langues (0x080C fr-BE, 0x2C0A es-AR…) suivent.
_LCID_PRIMARY = {0x0C: "fr", 0x09: "en", 0x0A: "es", 0x07: "de", 0x16: "pt-BR", 0x04: "zh-CN", 0x11: "ja", 0x1E: "th",
                 0x21: "id", 0x64: "fil"}
# Sous-étiquette primaire BCP 47 → langue (pt → pt-BR, zh → zh-CN ; anciens codes in → id, tl → fil).
_PRIMARY_TAG = {"fr": "fr", "en": "en", "es": "es", "de": "de", "pt": "pt-BR", "zh": "zh-CN", "ja": "ja", "th": "th", "id": "id", "in": "id",
                "fil": "fil", "tl": "fil"}
# Séparateur de milliers, séparateur décimal, nombre minimal de groupes avant de grouper (es : 1234 mais 12.345),
# calqué sur Intl.NumberFormat du navigateur.
_NUMBER_STYLE = {
    "fr": (" ", ",", 1), "en": (",", ".", 1), "es": (".", ",", 2), "de": (".", ",", 1), "pt-BR": (".", ",", 1),
    "zh-CN": (",", ".", 1), "ja": (",", ".", 1), "th": (",", ".", 1), "id": (".", ",", 1), "fil": (",", ".", 1),
}
_NOTE_NAMES = {
    "letters": ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"),
    "fr": ("Do", "Do#", "Ré", "Ré#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"),
    "es": ("Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"),
    "pt-BR": ("Dó", "Dó#", "Ré", "Ré#", "Mi", "Fá", "Fá#", "Sol", "Sol#", "Lá", "Lá#", "Si"),
}
_SOLFEGE_LANGS = ("fr", "es", "pt-BR")

_log = logging.getLogger("i18n")
_NAME_RE = re.compile(r"[A-Za-z0-9_.\-]+")
_SELECTOR_RE = re.compile(r"=\d+|[A-Za-z0-9_.\-]+")


class MessageError(ValueError):
    """Message mal formé (accolade manquante, type d'argument inconnu…)."""


# ---------------------------------------------------------------- grammaire des messages
def parse(message):
    """Analyse un message et renvoie sa liste de nœuds : `str`, `("arg", nom)`,
    `("plural", nom, {sélecteur: nœuds})` ou `("select", nom, {sélecteur: nœuds})`."""
    nodes, i = _parse_body(message, 0, 0)
    if i < len(message):
        raise MessageError(f"accolade fermante en trop à la position {i}")
    return nodes


def _parse_body(s, i, depth):
    nodes, buf, n = [], [], len(s)
    while i < n:
        c = s[i]
        if c == "{":
            if s.startswith("{{", i):
                buf.append("{")
                i += 2
                continue
            if buf:
                nodes.append("".join(buf))
                buf = []
            node, i = _parse_arg(s, i + 1, depth)
            nodes.append(node)
        elif c == "}":
            if depth > 0:
                if buf:
                    nodes.append("".join(buf))
                return nodes, i + 1
            buf.append("}")
            i += 2 if s.startswith("}}", i) else 1
        else:
            buf.append(c)
            i += 1
    if depth > 0:
        raise MessageError("accolade fermante manquante")
    if buf:
        nodes.append("".join(buf))
    return nodes, i


def _skip_ws(s, i):
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def _parse_arg(s, i, depth):
    i = _skip_ws(s, i)
    m = _NAME_RE.match(s, i)
    if not m:
        raise MessageError(f"nom d'argument attendu à la position {i}")
    name, i = m.group(0), _skip_ws(s, m.end())
    if i < len(s) and s[i] == "}":
        return ("arg", name), i + 1
    if i >= len(s) or s[i] != ",":
        raise MessageError(f"« }} » ou « , » attendu après {{{name} (position {i})")
    i = _skip_ws(s, i + 1)
    m = _NAME_RE.match(s, i)
    kind = m.group(0) if m else ""
    if kind not in ("plural", "select"):
        raise MessageError(f"type d'argument inconnu « {kind} » pour {{{name}}}")
    i = _skip_ws(s, m.end())
    if i >= len(s) or s[i] != ",":
        raise MessageError(f"« , » attendu après {{{name}, {kind}")
    i += 1
    branches = {}
    while True:
        i = _skip_ws(s, i)
        if i >= len(s):
            raise MessageError(f"accolade fermante manquante pour {{{name}, {kind}")
        if s[i] == "}":
            break
        m = _SELECTOR_RE.match(s, i)
        if not m:
            raise MessageError(f"sélecteur attendu dans {{{name}, {kind}}} (position {i})")
        selector, i = m.group(0), _skip_ws(s, m.end())
        if i >= len(s) or s[i] != "{":
            raise MessageError(f"« {{ » attendu après le sélecteur « {selector} » de {{{name}, {kind}}}")
        body, i = _parse_body(s, i + 1, depth + 1)
        branches[selector] = body
    if "other" not in branches:
        raise MessageError(f"branche « other » manquante dans {{{name}, {kind}}}")
    return (kind, name, branches), i + 1


def plural(lang, n):
    """Catégorie de pluriel de `n` dans la langue (`zero|one|two|few|many|other`)."""
    rule = plural_rule(lang)
    try:
        v = abs(float(n))
    except (TypeError, ValueError):
        return "other"
    if PLURAL_RULES[rule] == ("other",):
        return "other"
    if rule == "fr":
        return "one" if int(v) in (0, 1) else "other"
    return "one" if v == 1 else "other"


def plural_rule(lang):
    """Nom de la règle de pluriel d'une langue (`_meta.plural` du catalogue chargé, sinon l'étiquette)."""
    cat = _catalogues.get(lang) if _catalogues else None
    rule = cat.plural_rule if cat else lang
    if rule in PLURAL_RULES:
        return rule
    rule = _PRIMARY_TAG.get(str(rule).split("-")[0].lower(), "en")
    return rule if rule in PLURAL_RULES else "en"


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fmt_number(n, lang=None, max_frac=3):
    """Formate un nombre comme `Intl.NumberFormat` du navigateur (séparateurs de la langue, 3 décimales max)."""
    lang = lang or current_lang()
    group, dec, min_groups = _NUMBER_STYLE.get(lang, _NUMBER_STYLE["en"])
    neg = n < 0
    v = abs(n)
    if isinstance(v, float) and not v.is_integer():
        q = Decimal(repr(v)).quantize(Decimal(1).scaleb(-max_frac), rounding=ROUND_HALF_UP)
        text = format(q, "f").rstrip("0").rstrip(".")
        ip, _, fp = text.partition(".")
    else:
        ip, fp = str(int(v)), ""
    if len(ip) >= 3 + min_groups:
        ip = f"{int(ip):,}".replace(",", group)
    out = ip + (dec + fp if fp else "")
    return "-" + out if neg else out


def _param_text(v, lang):
    if _is_number(v):
        return fmt_number(v, lang)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _render(nodes, params, lang, number=None):
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(node.replace("#", number) if number is not None else node)
            continue
        kind, name = node[0], node[1]
        value = params.get(name)
        if kind == "arg":
            out.append("{" + name + "}" if value is None else _param_text(value, lang))
            continue
        branches = node[2]
        if kind == "plural":
            if not _is_number(value):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    value = None
            body = None
            if value is not None:
                for selector, b in branches.items():
                    if selector.startswith("=") and float(selector[1:]) == value:
                        body = b
                        break
                if body is None:
                    body = branches.get(plural(lang, value))
            body = body if body is not None else branches["other"]
            out.append(_render(body, params, lang, fmt_number(value, lang) if value is not None else ""))
        else:  # select
            key = "" if value is None else ("true" if value is True else "false" if value is False else str(value))
            body = branches.get(key, branches["other"])
            out.append(_render(body, params, lang, number))
    return "".join(out)


def format_message(message, params=None, lang=None):
    """Formate un message brut avec ses paramètres dans la langue donnée (sans passer par un catalogue)."""
    return _render(parse(message), params or {}, lang or current_lang())


# ---------------------------------------------------------------- catalogues
class Catalogue:
    """Un fichier `ui/i18n/<tag>.json` : `_meta` (nom natif, bêta, règle de pluriel, notation des notes)
    et des messages à plat, `"section.cle": "message"`."""

    def __init__(self, tag, data):
        meta = data.get("_meta") or {}
        self.tag = tag
        self.name = meta.get("name") or tag
        self.beta = bool(meta.get("beta", tag not in ("fr", "en")))
        self.plural_rule = meta.get("plural") or (tag if tag in PLURAL_RULES else "en")
        self.notes = meta.get("notes") or ("solfege" if tag in _SOLFEGE_LANGS else "letters")
        self.messages = {k: v for k, v in data.items() if k != "_meta" and isinstance(v, str)}
        self._parsed = {}

    def __contains__(self, key):
        return key in self.messages

    def get(self, key):
        return self.messages.get(key)

    def nodes(self, key):
        """Nœuds analysés du message (mis en cache) ; `MessageError` si le message est mal formé."""
        if key not in self._parsed:
            self._parsed[key] = parse(self.messages[key])
        return self._parsed[key]

    def format(self, key, params=None):
        return _render(self.nodes(key), params or {}, self.tag)

    def meta(self):
        return {"tag": self.tag, "name": self.name, "beta": self.beta, "plural": self.plural_rule, "notes": self.notes}


def default_ui_dir():
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "ui")


def load_catalogues(ui_dir=None):
    """Lit `ui/i18n/*.json` et renvoie `{tag: Catalogue}` ; un fichier illisible est ignoré (journalisé)."""
    folder = os.path.join(ui_dir or default_ui_dir(), "i18n")
    result = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return result
    for name in names:
        if not name.endswith(".json"):
            continue
        tag = name[:-5]
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("le catalogue doit être un objet JSON")
            result[tag] = Catalogue(tag, data)
        except (OSError, ValueError) as e:
            _log.warning("catalogue %s ignoré : %s", name, e)
    return result


_catalogues = None
_lang = FALLBACK_LANG
_warned = set()


def catalogues():
    global _catalogues
    if _catalogues is None:
        _catalogues = load_catalogues()
    return _catalogues


def reload(ui_dir=None):
    """Recharge les catalogues (tests, changement de dossier)."""
    global _catalogues
    _catalogues = load_catalogues(ui_dir)
    _warned.clear()
    return _catalogues


def available():
    """Langues proposées à l'utilisateur : `[{tag, name, beta}]` dans l'ordre de `LANGS` (puis les autres)."""
    cats = catalogues()
    order = [t for t in LANGS if t in cats] + sorted(t for t in cats if t not in LANGS)
    return [{"tag": t, "name": cats[t].name, "beta": cats[t].beta} for t in order]


# ---------------------------------------------------------------- choix de la langue
def normalize_tag(tag):
    """`fr_FR`, `fr-CA`, `pt`, `zh_CN.UTF-8`… → langue de `LANGS`, ou None si elle n'est pas proposée."""
    if not tag:
        return None
    tag = str(tag).split(".")[0].split("@")[0].replace("_", "-").strip()
    lower = tag.lower()
    for t in LANGS:
        if t.lower() == lower:
            return t
    return _PRIMARY_TAG.get(lower.split("-")[0])


def _windows_lcid():
    return int(__import__("ctypes").windll.kernel32.GetUserDefaultUILanguage())


def system_lang():
    """Langue de l'interface du système (Windows : LCID de l'interface ; ailleurs : locale), repli `en`."""
    if sys.platform == "win32":
        try:
            lang = _LCID_PRIMARY.get(_windows_lcid() & 0x3FF)
            if lang:
                return lang
        except Exception:  # noqa - ctypes indisponible ou appel refusé
            pass
    else:
        try:
            lang = normalize_tag(locale.getlocale()[0])
        except Exception:  # noqa - locale mal configurée
            lang = None
        if not lang:
            for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
                lang = normalize_tag(os.environ.get(var))
                if lang:
                    break
        if lang:
            return lang
    return "en"


def resolve_lang(pref):
    """Préférence de la config (`auto`, `fr`, `pt-BR`, `fr-CA`…) → langue effective de `LANGS`."""
    if not pref or str(pref).lower() == "auto":
        return system_lang()
    return normalize_tag(pref) or system_lang()


def set_lang(pref):
    """Fixe la langue courante de Python à partir d'une préférence ; renvoie la langue effective."""
    global _lang
    _lang = resolve_lang(pref)
    return _lang


def current_lang():
    return _lang


# ---------------------------------------------------------------- traduction
def has(key, lang=None):
    cat = catalogues().get(lang or current_lang())
    return bool(cat and key in cat)


def t(key, lang=None, /, **params):
    """Message traduit dans `lang` (ou la langue courante), repli sur le français puis `[clé]`.
    `key` et `lang` sont positionnels seulement : tout mot-clé est un paramètre du message (`{lang}` inclus)."""
    lang = lang or current_lang()
    cats = catalogues()
    for tag in (lang, FALLBACK_LANG):
        cat = cats.get(tag)
        if cat and key in cat:
            try:
                return _render(cat.nodes(key), params, lang)
            except MessageError as e:
                if (tag, key) not in _warned:
                    _warned.add((tag, key))
                    _log.warning("i18n : message %s/%s mal formé : %s", tag, key, e)
                return cat.get(key)
    if key not in _warned:
        _warned.add(key)
        _log.warning("i18n : clé absente « %s » (%s)", key, lang)
    return f"[{key}]"


class Msg(NamedTuple):
    """Message à traduire par l'interface : clé + paramètres, sérialisable (`to_dict()`)."""
    key: str
    params: dict = {}

    def to_dict(self):
        return {"key": self.key, "params": dict(self.params)}

    def text(self, lang=None, /):
        return t(self.key, lang, **self.params)

    @classmethod
    def make(cls, key, **params):
        return cls(key, params)


def note_name(midi, lang=None):
    """Nom d'une note MIDI : solfège (Do, Ré#…) en fr/es/pt-BR, lettres (C, D#…) sinon, octave scientifique
    (60 → Do4 / C4)."""
    lang = lang or current_lang()
    cat = catalogues().get(lang)
    notation = cat.notes if cat else ("solfege" if lang in _SOLFEGE_LANGS else "letters")
    names = _NOTE_NAMES.get(lang if notation == "solfege" else "letters") or _NOTE_NAMES["fr" if notation == "solfege" else "letters"]
    midi = int(midi)
    return f"{names[midi % 12]}{midi // 12 - 1}"
