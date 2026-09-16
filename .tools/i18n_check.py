# -*- coding: utf-8 -*-
"""Vérification des catalogues de traduction (`ui/i18n/<lang>.json`) contre les clés utilisées dans le code.

    py .tools/i18n_check.py [racine]      code de retour 1 s'il y a au moins une erreur
    from i18n_check import run ; run(racine) -> liste des erreurs (vide si tout va bien)

Clés utilisées : `t('cle')` / `I18N.t('cle')` dans ui/*.js, `t("cle")` / `i18n.t("cle")` / `Msg("cle")` dans
les modules Python de la racine et de api/, `data-i18n="cle"`, `data-i18n-html="cle"` et
`data-i18n-attr="title:cle;aria-label:cle2"` dans ui/index.html, et les constantes `I18N_KEYS = [...]` des
modules Python (clés construites dynamiquement : `f"instrument.{name}"` → les déclarer là).

Par langue : JSON invalide, message mal formé, clé manquante (erreur pour fr et en, avertissement pour une
langue bêta), clé orpheline (avertissement), paramètres `{x}` / arguments plural-select différents du
français (erreur), branches plural incomplètes selon la règle de la langue (erreur).
"""
import ast
import importlib.util
import json
import os
import re
import sys

# console Windows en cp1252 : les cles et libelles accentues doivent s'afficher sans planter
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

USE_RE = re.compile(r"""(?<![\w.$])(?:I18N\.|i18n\.)?(?:t|Msg)\(\s*['"]([\w.\-]+)['"]""")
HTML_RE = re.compile(r'data-i18n(?:-html)?="([\w.\-]+)"')
ATTR_RE = re.compile(r'data-i18n-attr="([^"]*)"')
KEY_RE = re.compile(r"^[\w.\-]+$")


# ---------------------------------------------------------------- collecte des clés utilisées
def _add(usages, key, where):
    usages.setdefault(key, []).append(where)


def _scan_text(path, usages, patterns):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
    except (OSError, UnicodeDecodeError):
        return
    rel = os.path.basename(path)
    for no, line in enumerate(lines, 1):
        for pat, attr in patterns:
            for m in pat.finditer(line):
                if attr:
                    for pair in m.group(1).split(";"):
                        if ":" in pair:
                            key = pair.split(":", 1)[1].strip()
                            if KEY_RE.match(key):
                                _add(usages, key, f"{rel}:{no}")
                else:
                    _add(usages, m.group(1), f"{rel}:{no}")


def _declared_keys(path):
    """Clés listées dans `I18N_KEYS = [...]` (ou tuple) au premier niveau du module ; [] si absent."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    keys = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if not any(isinstance(t, ast.Name) and t.id == "I18N_KEYS" for t in targets):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            keys.extend(e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return keys


def collect_usages(root):
    """`{cle: ["fichier:ligne", ...]}` pour tout le code du projet."""
    usages = {}
    ui = os.path.join(root, "ui")
    for name in sorted(os.listdir(ui)) if os.path.isdir(ui) else []:
        if name.endswith(".js") and name != "i18n.js":
            _scan_text(os.path.join(ui, name), usages, [(USE_RE, False)])
    index = os.path.join(ui, "index.html")
    if os.path.exists(index):
        _scan_text(index, usages, [(HTML_RE, False), (ATTR_RE, True)])
    py_dirs = [root] + ([os.path.join(root, "api")] if os.path.isdir(os.path.join(root, "api")) else [])
    for folder in py_dirs:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not name.endswith(".py") or name == "i18n.py" or not os.path.isfile(path):
                continue
            _scan_text(path, usages, [(USE_RE, False)])
            for key in _declared_keys(path):
                _add(usages, key, f"{name}:I18N_KEYS")
    return usages


# ---------------------------------------------------------------- analyse des messages
def _signature(nodes, args, plurals, selects, top=True):
    """Remplit `args` {(nom, type)}, `plurals` {nom: catégories}, `selects` {nom: sélecteurs}."""
    for node in nodes:
        if isinstance(node, str):
            continue
        kind, name = node[0], node[1]
        args.add((name, kind))
        if kind == "arg":
            continue
        branches = node[2]
        target = plurals if kind == "plural" else selects
        target.setdefault(name, set()).update(branches.keys())
        for body in branches.values():
            _signature(body, args, plurals, selects, False)


def _load_engine(root):
    """Charge le `i18n.py` de la racine analysée (grammaire et règles de pluriel) sans passer par sys.path."""
    spec = importlib.util.spec_from_file_location("_i18n_check_engine", os.path.join(root, "i18n.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyse(root=None):
    """Analyse complète : `{"errors", "warnings", "langs": {tag: {...}}, "usages"}`."""
    root = os.path.abspath(root or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    i18n = _load_engine(root)
    usages = collect_usages(root)
    folder = os.path.join(root, "ui", "i18n")
    result = {"errors": [], "warnings": [], "langs": {}, "usages": usages}
    files = sorted(n for n in os.listdir(folder) if n.endswith(".json")) if os.path.isdir(folder) else []
    if not files:
        result["errors"].append(f"aucun catalogue dans {folder}")
        return result

    catalogues, parsed = {}, {}
    for name in files:
        tag = name[:-5]
        entry = result["langs"][tag] = {"name": tag, "beta": tag not in ("fr", "en"), "errors": [], "warnings": [], "count": 0}
        try:
            data = _load_json(os.path.join(folder, name))
            if not isinstance(data, dict):
                raise ValueError("le catalogue doit être un objet JSON")
        except (OSError, ValueError) as e:
            entry["errors"].append(f"JSON invalide : {e}")
            continue
        meta = data.get("_meta") or {}
        if not isinstance(meta, dict) or not meta.get("name"):
            entry["warnings"].append("_meta.name absent")
            meta = meta if isinstance(meta, dict) else {}
        entry["name"] = meta.get("name") or tag
        entry["beta"] = bool(meta.get("beta", entry["beta"]))
        rule = meta.get("plural") or tag
        if rule not in i18n.PLURAL_RULES:
            entry["errors"].append(f"_meta.plural inconnu « {rule} » (règles : {', '.join(i18n.PLURAL_RULES)})")
            rule = "en"
        entry["rule"] = rule
        cat = {k: v for k, v in data.items() if k != "_meta"}
        entry["count"] = len(cat)
        catalogues[tag] = cat
        parsed[tag] = {}
        for key, msg in cat.items():
            if not isinstance(msg, str):
                entry["errors"].append(f"« {key} » : le message doit être une chaîne")
                continue
            try:
                parsed[tag][key] = i18n.parse(msg)
            except i18n.MessageError as e:
                entry["errors"].append(f"« {key} » : message mal formé ({e})")

    fr = catalogues.get("fr", {})
    fr_sig = {}
    for key, nodes in parsed.get("fr", {}).items():
        args, plurals, selects = set(), {}, {}
        _signature(nodes, args, plurals, selects)
        fr_sig[key] = (args, plurals, selects)

    for tag, cat in catalogues.items():
        entry = result["langs"][tag]
        required = set(i18n.PLURAL_RULES[entry["rule"]])
        strict = not entry["beta"]
        # clés manquantes : utilisées dans le code ou présentes en français
        reference = set(usages) | set(fr)
        for key in sorted(reference - set(cat)):
            where = ", ".join(usages.get(key, ["fr.json"])[:3])
            (entry["errors"] if strict else entry["warnings"]).append(f"clé manquante « {key} » (utilisée : {where})")
        for key in sorted(set(cat) - set(fr)) if tag != "fr" else []:
            entry["warnings"].append(f"clé « {key} » absente du catalogue français")
        if tag == "fr":
            for key in sorted(set(cat) - set(usages)):
                entry["warnings"].append(f"clé orpheline « {key} » (dans aucun fichier)")
        for key, nodes in parsed[tag].items():
            args, plurals, selects = set(), {}, {}
            _signature(nodes, args, plurals, selects)
            for name, cats in plurals.items():
                named = {c for c in cats if not c.startswith("=")}
                bad = sorted(named - set(i18n.CATEGORIES))
                if bad:
                    entry["errors"].append(f"« {key} » : catégorie de pluriel inconnue {bad} pour {{{name}}}")
                missing = sorted(required - named)
                if missing:
                    entry["errors"].append(f"« {key} » : branches plural manquantes {missing} pour {{{name}}} (règle {entry['rule']})")
                unused = sorted(named - required)
                if unused:
                    entry["warnings"].append(f"« {key} » : branches plural jamais choisies {unused} pour {{{name}}} (règle {entry['rule']})")
            if tag != "fr" and key in fr_sig:
                fr_args, fr_plurals, fr_selects = fr_sig[key]
                if args != fr_args:
                    diff = sorted(f"{{{n}, {k}}}" if k != "arg" else f"{{{n}}}" for n, k in args ^ fr_args)
                    entry["errors"].append(f"« {key} » : paramètres différents du français {diff}")
                for name, sels in selects.items():
                    if name in fr_selects and sels != fr_selects[name]:
                        entry["warnings"].append(f"« {key} » : sélecteurs de {{{name}, select}} différents du français {sorted(sels ^ fr_selects[name])}")
    for tag in ("fr", "en"):
        if tag not in result["langs"]:
            result["errors"].append(f"catalogue {tag}.json absent")
    for tag, entry in result["langs"].items():
        result["errors"].extend(f"{tag} : {e}" for e in entry["errors"])
        result["warnings"].extend(f"{tag} : {w}" for w in entry["warnings"])
    return result


def run(root=None):
    """Liste des erreurs (chaînes préfixées par la langue) ; vide si les catalogues sont cohérents."""
    return analyse(root)["errors"]


def report(root=None):
    """Rapport lisible groupé par langue ; renvoie `(texte, erreurs)`."""
    res = analyse(root)
    lines = [f"i18n : {len(res['usages'])} clé(s) utilisée(s) dans le code, {len(res['langs'])} catalogue(s)"]
    for tag, entry in res["langs"].items():
        badge = ", bêta" if entry["beta"] else ""
        lines.append(f"== {tag} — {entry['name']}{badge} : {entry['count']} message(s), "
                     f"{len(entry['errors'])} erreur(s), {len(entry['warnings'])} avertissement(s)")
        lines.extend(f"   ERREUR  {e}" for e in entry["errors"])
        lines.extend(f"   avert.  {w}" for w in entry["warnings"])
    for e in res["errors"]:
        if " : " not in e or e.split(" : ", 1)[0] not in res["langs"]:
            lines.append(f"ERREUR  {e}")
    lines.append(f"Résultat : {len(res['errors'])} erreur(s), {len(res['warnings'])} avertissement(s)")
    return "\n".join(lines), res["errors"]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    text, errors = report(argv[0] if argv else None)
    try:
        print(text)
    except UnicodeEncodeError:  # console Windows sans UTF-8
        print(text.encode("utf-8", "replace").decode("ascii", "replace"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
