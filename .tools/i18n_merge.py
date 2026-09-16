# -*- coding: utf-8 -*-
"""Assemble les catalogues de traduction livrés (`ui/i18n/<lang>.json`) à partir de leurs sources par
domaine (`ui/i18n/src/<lang>/<domaine>.json`).

Pourquoi des sources par domaine : plusieurs personnes (ou agents) traduisent des écrans différents en même
temps sans se marcher dessus, et un traducteur relit `music.json` sans ouvrir 1 500 clés. Le moteur (`i18n.py`,
`ui/i18n.js`) ne lit que le fichier assemblé ; ce script est lancé avant un build (`build.bat`) et par les
tests (`tests_client/test_i18n.py`) en mode `--check`, qui échoue si l'assemblage n'est pas à jour.

Règles : `_meta` vient de `src/<lang>/_meta.json` ; une clé définie dans deux domaines avec des valeurs
différentes est une erreur ; les clés sont triées par domaine puis par ordre alphabétique.

Usage : py .tools/i18n_merge.py [--check]
"""
import json
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N_DIR = os.path.join(ROOT, "ui", "i18n")
SRC_DIR = os.path.join(I18N_DIR, "src")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{os.path.relpath(path, ROOT)} : un objet JSON est attendu")
    return data


def build(lang):
    """(catalogue assemblé, erreurs) pour une langue."""
    folder = os.path.join(SRC_DIR, lang)
    errors = []
    out = {}
    meta_path = os.path.join(folder, "_meta.json")
    if os.path.isfile(meta_path):
        out["_meta"] = _read(meta_path)
    else:
        errors.append(f"{lang} : _meta.json absent")
    origin = {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or name == "_meta.json":
            continue
        try:
            data = _read(os.path.join(folder, name))
        except (OSError, ValueError) as e:
            errors.append(f"{lang}/{name} : {e}")
            continue
        for key in sorted(data):
            if key == "_meta":
                continue
            if key in out and out[key] != data[key]:
                errors.append(f"{lang} : clé « {key} » définie dans {origin[key]} et {name} avec des valeurs différentes")
                continue
            out[key] = data[key]
            origin.setdefault(key, name)
    return out, errors


def dump(cat):
    return json.dumps(cat, ensure_ascii=False, indent=2) + "\n"


def langs():
    try:
        return sorted(d for d in os.listdir(SRC_DIR) if os.path.isdir(os.path.join(SRC_DIR, d)))
    except OSError:
        return []


def run(check=False):
    """Assemble (ou vérifie) chaque langue ; renvoie la liste des erreurs."""
    errors = []
    for lang in langs():
        cat, errs = build(lang)
        errors.extend(errs)
        target = os.path.join(I18N_DIR, f"{lang}.json")
        text = dump(cat)
        current = ""
        if os.path.isfile(target):
            with open(target, "r", encoding="utf-8") as f:
                current = f.read()
        if check:
            if current != text:
                errors.append(f"{lang}.json n'est pas à jour : lance py .tools/i18n_merge.py")
        elif current != text:
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"{lang}.json assemblé : {len(cat) - ('_meta' in cat)} clés")
    return errors


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    errors = run(check="--check" in argv)
    for e in errors:
        print("ERREUR :", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
