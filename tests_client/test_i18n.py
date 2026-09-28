# -*- coding: utf-8 -*-
"""Moteur de traduction : grammaire des messages (Python), repli, noms de notes, choix de la langue,
cohérence des catalogues du dépôt (`.tools/i18n_check.py`) et parité avec `ui/i18n.js` (si `node` existe)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def fresh_catalogues():
    i18n.reload(os.path.join(ROOT, "ui"))
    i18n.set_lang("fr")
    yield


# ---------------------------------------------------------------- grammaire
def test_interpolation():
    assert i18n.format_message("Lecture de {title}", {"title": "Für Elise"}, "fr") == "Lecture de Für Elise"
    assert i18n.format_message("{a} et {b}", {"a": 1, "b": "x"}, "fr") == "1 et x"
    assert i18n.format_message("Taille {size}", {"size": 1234}, "fr") == "Taille 1 234"
    assert i18n.format_message("Size {size}", {"size": 1234.5}, "en") == "Size 1,234.5"
    assert i18n.format_message("{v}", {"v": 2.0005}, "fr") == "2,001"
    # paramètre absent : le nom reste visible pour repérer l'oubli
    assert i18n.format_message("Salut {name}", {}, "fr") == "Salut {name}"


def test_plural_rules():
    assert [i18n.plural("fr", n) for n in (0, 1, 1.5, 2, 21)] == ["one", "one", "one", "other", "other"]
    assert [i18n.plural("en", n) for n in (0, 1, 2)] == ["other", "one", "other"]
    assert [i18n.plural("de", n) for n in (0, 1, 2)] == ["other", "one", "other"]
    assert [i18n.plural("ja", n) for n in (0, 1, 2)] == ["other", "other", "other"]
    assert i18n.plural("zh-CN", 1) == "other" and i18n.plural("th", 1) == "other"
    assert [i18n.plural("id", n) for n in (0, 1, 2)] == ["other", "other", "other"]
    assert [i18n.plural("fil", n) for n in (0, 1, 2)] == ["other", "one", "other"]
    assert i18n.plural("fr-CA", 0) == "one"  # sous-langue inconnue → règle de la langue primaire
    assert i18n.plural("fr", "abc") == "other"


def test_plural_messages():
    msg = "{n, plural, =0 {Aucune musique} one {# musique} other {# musiques}}"
    assert i18n.format_message(msg, {"n": 0}, "fr") == "Aucune musique"
    assert i18n.format_message(msg, {"n": 1}, "fr") == "1 musique"
    assert i18n.format_message(msg, {"n": 1234}, "fr") == "1 234 musiques"
    assert i18n.format_message(msg, {"n": 1}, "en") == "1 musique"
    assert i18n.format_message(msg, {"n": 0}, "en") == "Aucune musique"
    assert i18n.format_message("{n, plural, other {# 曲}}", {"n": 1}, "ja") == "1 曲"
    assert i18n.format_message("{n, plural, one {une} other {# fois}}", {"n": "3"}, "fr") == "3 fois"
    assert i18n.format_message("{n, plural, one {une} other {aucune}}", {}, "fr") == "aucune"


def test_select():
    msg = "{mode, select, note {Tenir la note} tap {Frappe brève} other {Mode {mode}}}"
    assert i18n.format_message(msg, {"mode": "note"}, "fr") == "Tenir la note"
    assert i18n.format_message(msg, {"mode": "tap"}, "fr") == "Frappe brève"
    assert i18n.format_message(msg, {"mode": "xyz"}, "fr") == "Mode xyz"
    assert i18n.format_message("{ok, select, true {oui} other {non}}", {"ok": True}, "fr") == "oui"


def test_nesting():
    msg = "{n, plural, =0 {{name} n'a rien} one {{name} a # musique} other {{name} a # musiques}}"
    assert i18n.format_message(msg, {"n": 0, "name": "Dodo"}, "fr") == "Dodo n'a rien"
    assert i18n.format_message(msg, {"n": 5, "name": "Dodo"}, "fr") == "Dodo a 5 musiques"
    msg = "{n, plural, one {# {kind, select, a {pomme} other {poire}}} other {# {kind, select, a {pommes} other {poires}}}}"
    assert i18n.format_message(msg, {"n": 3, "kind": "a"}, "fr") == "3 pommes"
    assert i18n.format_message(msg, {"n": 1, "kind": "b"}, "fr") == "1 poire"


def test_literal_braces():
    assert i18n.format_message("{{x}} vaut {x}", {"x": 4}, "fr") == "{x} vaut 4"
    assert i18n.format_message("a {{ b }} c", {}, "fr") == "a { b } c"
    assert i18n.format_message("{{{n, plural, other {#}}}}", {"n": 2}, "fr") == "{2}"
    # dans une branche, `{{` reste littéral mais un `}` simple ferme toujours la branche
    assert i18n.format_message("{n, plural, other {{{#}}", {"n": 2}, "fr") == "{2"
    assert i18n.format_message("# hors pluriel", {}, "fr") == "# hors pluriel"


def test_malformed():
    with pytest.raises(i18n.MessageError):
        i18n.parse("{n, plural, one {x}")
    with pytest.raises(i18n.MessageError):
        i18n.parse("{n, plural, one {x}}")  # « other » manquante
    with pytest.raises(i18n.MessageError):
        i18n.parse("{n, foo, a {x} other {y}}")


# ---------------------------------------------------------------- catalogues et repli
def test_t_and_fallback(monkeypatch):
    assert i18n.t("music.count", "fr", n=0) == "Aucune musique"
    assert i18n.t("music.count", "en", n=2) == "2 songs"
    assert i18n.t("room.members", "de", n=3, code="ABCD") == "3 Teilnehmer im Raum ABCD"
    i18n.set_lang("ja")
    assert i18n.t("common.cancel") == "キャンセル"
    # clé absente d'un catalogue → français ; absente partout → [clé]
    i18n.catalogues()["ja"].messages.pop("common.cancel")
    assert i18n.t("common.cancel", "ja") == "Annuler"
    assert i18n.t("nope.missing", "ja") == "[nope.missing]"
    assert i18n.has("common.ok", "fr") and not i18n.has("nope.missing", "fr")


def test_available_and_meta():
    tags = [a["tag"] for a in i18n.available()]
    assert tags == list(i18n.LANGS)
    by_tag = {a["tag"]: a for a in i18n.available()}
    assert by_tag["fr"] == {"tag": "fr", "name": "Français", "beta": False}
    assert by_tag["ja"]["beta"] is True and by_tag["pt-BR"]["name"] == "Português (Brasil)"
    assert i18n.catalogues()["fr"].meta()["notes"] == "solfege"


def test_msg():
    m = i18n.Msg.make("music.count", n=3)
    assert m.to_dict() == {"key": "music.count", "params": {"n": 3}}
    assert m.text("en") == "3 songs" and m.text("fr") == "3 musiques"
    assert i18n.Msg("common.ok").to_dict() == {"key": "common.ok", "params": {}}


def test_note_name():
    assert i18n.note_name(60, "fr") == "Do4"
    assert i18n.note_name(61, "fr") == "Do#4"
    assert i18n.note_name(62, "es") == "Re4"
    assert i18n.note_name(69, "pt-BR") == "Lá4"
    assert i18n.note_name(60, "en") == "C4"
    assert i18n.note_name(59, "ja") == "B3"
    assert i18n.note_name(21, "de") == "A0"
    i18n.set_lang("en")
    assert i18n.note_name(66) == "F#4"


# ---------------------------------------------------------------- choix de la langue
def test_resolve_lang_windows(monkeypatch):
    monkeypatch.setattr(i18n.sys, "platform", "win32")
    for lcid, expected in ((0x040C, "fr"), (0x080C, "fr"), (0x0409, "en"), (0x0809, "en"), (0x0C0A, "es"),
                           (0x2C0A, "es"), (0x0407, "de"), (0x0416, "pt-BR"), (0x0804, "zh-CN"), (0x0411, "ja"),
                           (0x041E, "th"), (0x0421, "id"), (0x0464, "fil"), (0x0419, "en")):
        monkeypatch.setattr(i18n, "_windows_lcid", lambda v=lcid: v)
        assert i18n.resolve_lang("auto") == expected, hex(lcid)
    monkeypatch.setattr(i18n, "_windows_lcid", lambda: (_ for _ in ()).throw(OSError("pas de kernel32")))
    assert i18n.resolve_lang("auto") == "en"
    assert i18n.resolve_lang("de") == "de"
    assert i18n.resolve_lang("fr-CA") == "fr"
    assert i18n.resolve_lang("pt") == "pt-BR"
    assert i18n.resolve_lang("zh_CN") == "zh-CN"
    assert i18n.resolve_lang("xx") == "en"


def test_resolve_lang_linux(monkeypatch):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("ja_JP", "UTF-8"))
    assert i18n.resolve_lang("auto") == "ja"
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (None, None))
    monkeypatch.setenv("LC_ALL", "")
    monkeypatch.setenv("LC_MESSAGES", "")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.resolve_lang("auto") == "pt-BR"
    monkeypatch.setenv("LANG", "C")
    assert i18n.resolve_lang(None) == "en"
    assert i18n.set_lang("es") == "es" and i18n.current_lang() == "es"


# ---------------------------------------------------------------- outil de vérification
def _load_check():
    path = os.path.join(ROOT, ".tools", "i18n_check.py")
    spec = importlib.util.spec_from_file_location("i18n_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_repo():
    check = _load_check()
    errors = check.run(ROOT)
    assert errors == []
    text, errors2 = check.report(ROOT)
    assert errors2 == [] and "== fr" in text and "== ja" in text


def test_check_detects_problems(tmp_path):
    check = _load_check()
    ui = tmp_path / "ui" / "i18n"
    ui.mkdir(parents=True)
    (tmp_path / "ui" / "index.html").write_text(
        '<b data-i18n="a.title"></b><i data-i18n-attr="title:a.tip;aria-label:a.label"></i>', encoding="utf-8")
    (tmp_path / "ui" / "app.js").write_text("t('a.js'); split('nope.split'); I18N.t('a.js2')", encoding="utf-8")
    (tmp_path / "mod.py").write_text(
        'I18N_KEYS = ["a.dyn"]\nx = cfg.get("nope.get")\ny = t("a.py")\nz = Msg("a.msg", n=1)\n', encoding="utf-8")
    shutil.copy(os.path.join(ROOT, "i18n.py"), tmp_path / "i18n.py")
    fr = {"_meta": {"name": "Français", "plural": "fr"}, "a.title": "T", "a.tip": "{n, plural, one {#} other {#}}",
          "a.label": "L", "a.js": "J", "a.js2": "J2", "a.dyn": "D", "a.py": "P", "a.msg": "{n} m", "a.orphan": "O"}
    en = {"_meta": {"name": "English", "plural": "en"}, "a.title": "T", "a.tip": "{n, plural, other {#}}",
          "a.label": "L", "a.js": "J", "a.js2": "J2", "a.dyn": "D", "a.py": "P", "a.msg": "{m} m"}
    ja = {"_meta": {"name": "日本語", "beta": True, "plural": "ja"}, "a.title": "T", "a.bad": "{n, plural, one {x}"}
    (ui / "fr.json").write_text(json.dumps(fr), encoding="utf-8")
    (ui / "en.json").write_text(json.dumps(en), encoding="utf-8")
    (ui / "ja.json").write_text(json.dumps(ja), encoding="utf-8")
    (ui / "de.json").write_text("{pas du json", encoding="utf-8")
    res = check.analyse(str(tmp_path))
    usages = res["usages"]
    assert set(usages) == {"a.title", "a.tip", "a.label", "a.js", "a.js2", "a.dyn", "a.py", "a.msg"}
    assert "nope.split" not in usages and "nope.get" not in usages
    errors, warnings = "\n".join(res["errors"]), "\n".join(res["warnings"])
    assert "en : « a.tip » : branches plural manquantes ['one']" in errors
    assert "en : « a.msg » : paramètres différents du français" in errors
    assert "en : clé manquante « a.orphan »" in errors
    assert "de : JSON invalide" in errors
    assert "ja : « a.bad » : message mal formé" in errors
    assert "ja : clé manquante « a.js »" in warnings and "ja : clé manquante « a.js »" not in errors
    assert "ja : clé « a.bad » absente du catalogue français" in warnings
    assert "fr : clé orpheline « a.orphan »" in warnings
    # tout nettoyé : plus d'erreur
    (ui / "de.json").unlink()
    (ui / "ja.json").unlink()
    en["a.tip"], en["a.msg"], en["a.orphan"] = fr["a.tip"], "{n} m", "O"
    (ui / "en.json").write_text(json.dumps(en), encoding="utf-8")
    assert check.run(str(tmp_path)) == []


# ---------------------------------------------------------------- parité JS / Python
HARNESS = r"""
const fs = require('fs'), vm = require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = input.cases.map(c => {
  const cat = input.catalogues[c.lang];
  I18N.load({lang: c.lang, catalogue: cat, fallback: input.catalogues.fr, meta: cat._meta});
  const r = c.key !== undefined ? t(c.key, c.params) : I18N.format(c.message, c.params);
  return [r, I18N.plural(c.lang, c.params.n === undefined ? 1 : c.params.n)];
});
process.stdout.write(JSON.stringify(out));
"""

PARITY_CASES = [
    {"lang": "fr", "key": "music.count", "params": {"n": 0}},
    {"lang": "fr", "key": "music.count", "params": {"n": 1}},
    {"lang": "fr", "key": "music.count", "params": {"n": 1234}},
    {"lang": "en", "key": "music.count", "params": {"n": 0}},
    {"lang": "en", "key": "music.count", "params": {"n": 1}},
    {"lang": "en", "key": "music.count", "params": {"n": 1234567}},
    {"lang": "ja", "key": "music.count", "params": {"n": 2}},
    {"lang": "es", "key": "music.count", "params": {"n": 12345}},
    {"lang": "es", "key": "music.count", "params": {"n": 1234}},
    {"lang": "de", "key": "room.members", "params": {"n": 3, "code": "ABCD"}},
    {"lang": "zh-CN", "key": "room.members", "params": {"n": 1, "code": "Z9"}},
    {"lang": "fr", "key": "instrument.hold_mode", "params": {"mode": "note"}},
    {"lang": "en", "key": "instrument.hold_mode", "params": {"mode": "xyz"}},
    {"lang": "pt-BR", "key": "music.playing", "params": {"title": "Für Elise"}},
    {"lang": "th", "key": "lang.beta_hint", "params": {"lang": "ไทย"}},
    {"lang": "ja", "key": "absent.key", "params": {}},
    {"lang": "fr", "message": "{{x}} = {x}", "params": {"x": 1.5}},
    {"lang": "fr", "message": "{v} et {w}", "params": {"v": 2.0005, "w": -1234.5}},
    {"lang": "en", "message": "{n, plural, =0 {none} one {{name} has # item} other {{name} has # items}}",
     "params": {"n": 1, "name": "Dodo"}},
    {"lang": "fr", "message": "{a, select, yes {Oui} other {Non}} {n, plural, one {# fois} other {# fois}}",
     "params": {"a": "yes", "n": 0}},
    {"lang": "fr", "message": "{n, plural, one {# {kind, select, a {pomme} other {poire}}} other {# {kind, select, a {pommes} other {poires}}}}",
     "params": {"n": 21, "kind": "a"}},
    {"lang": "de", "message": "Salut {name} et {{{n, plural, other {#}}}}", "params": {"n": 7}},
]


def test_js_parity(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent : parité JS/Python non vérifiée")
    folder = os.path.join(ROOT, "ui", "i18n")
    catalogues = {}
    for name in os.listdir(folder):
        if name.endswith(".json"):
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                catalogues[name[:-5]] = json.load(f)
    harness = tmp_path / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    data = tmp_path / "cases.json"
    data.write_text(json.dumps({"catalogues": catalogues, "cases": PARITY_CASES}), encoding="utf-8")
    proc = subprocess.run([node, str(harness), os.path.join(ROOT, "ui", "i18n.js"), str(data)],
                          capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    js = json.loads(proc.stdout.decode("utf-8"))
    assert len(js) == len(PARITY_CASES)
    for case, (js_text, js_plural) in zip(PARITY_CASES, js):
        if "key" in case:
            py_text = i18n.t(case["key"], case["lang"], **case["params"])
        else:
            py_text = i18n.format_message(case["message"], case["params"], case["lang"])
        assert py_text == js_text, case
        assert i18n.plural(case["lang"], case["params"].get("n", 1)) == js_plural, case


def test_catalogues_assembles_a_jour():
    """`ui/i18n/<lang>.json` doit être le résultat exact de `py .tools/i18n_merge.py` (sources par domaine)."""
    import importlib.util
    path = os.path.join(ROOT, ".tools", "i18n_merge.py")
    spec = importlib.util.spec_from_file_location("i18n_merge", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.run(check=True) == []
