"""Publie une version de l'appli Android de DodoTopia sur le serveur (stdlib uniquement).

    py publish_mobile.py [--version 0.3.0] [--apk mobile/dist/DodoTopia-Mobile-0.3.0.apk]
                         [--notes "..." | --notes-file mobile/CHANGELOG.md] [--dry-run] [--force]

Canal à part des versions PC (`publish_release.py`) : numérotation propre, un seul fichier, pas de manifeste signé
(l'APK porte déjà la signature Android de l'éditeur, et Android refuse une mise à jour signée par une autre clé).
Rien de ce que fait ce script ne change ce que voit l'Updater PC.

PUBLISH_URL et PUBLISH_TOKEN sont lus comme pour `publish_release.py` : environnement, sinon `publish.env`.
La version par défaut est le `versionName` de `mobile/app/build.gradle.kts`, le fichier par défaut
`mobile/dist/DodoTopia-Mobile-<version>.apk`. Étapes : sha256 de l'APK, PUT du fichier, POST publish, puis
GET latest. Code de sortie 0 seulement si la version publiée est bien devenue `latest`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from publish_release import (ROOT, Api, _detail, load_publish_env, notes_for_version, sha256_file, version_key)

GRADLE = ROOT / "mobile" / "app" / "build.gradle.kts"
DIST = ROOT / "mobile" / "dist"
APK_MAGIC = b"PK\x03\x04"               # un APK est une archive zip


def read_gradle_version() -> str:
    """`versionName = "0.3.0"` dans mobile/app/build.gradle.kts."""
    try:
        text = GRADLE.read_text(encoding="utf-8")
    except OSError:
        raise SystemExit(f"{GRADLE} introuvable : précise --version.")
    m = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit(f"versionName introuvable dans {GRADLE.name} : précise --version.")
    return m.group(1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publie une version de l'appli Android de DodoTopia sur le serveur.")
    ap.add_argument("--version", help="version à publier (défaut : versionName de mobile/app/build.gradle.kts)")
    ap.add_argument("--apk", default=None, help="fichier APK (défaut : mobile/dist/DodoTopia-Mobile-<version>.apk)")
    ap.add_argument("--notes", default=None, help="notes de version")
    ap.add_argument("--notes-file", default=None, help="fichier de notes (section `## <version>` si elle existe)")
    ap.add_argument("--dry-run", action="store_true", help="vérifie tout sans rien envoyer")
    ap.add_argument("--force", action="store_true", help="republie même si la version existe déjà sur le serveur")
    ap.add_argument("--url", default=None, help="PUBLISH_URL (sinon env / publish.env)")
    ap.add_argument("--token", default=None, help="PUBLISH_TOKEN (sinon env / publish.env)")
    args = ap.parse_args(argv)

    version = args.version or read_gradle_version()
    try:
        version_key(version)
    except ValueError as e:
        print(f"ERREUR : {e}")
        return 2

    env = load_publish_env()
    url = args.url or env.get("PUBLISH_URL")
    token = args.token or env.get("PUBLISH_TOKEN")
    if not url or not token:
        print("ERREUR : PUBLISH_URL et PUBLISH_TOKEN manquants (environnement ou publish.env).")
        return 2

    notes = args.notes or ""
    if args.notes_file:
        p = Path(args.notes_file)
        if p.is_file():
            section = notes_for_version(p.read_text(encoding="utf-8-sig"), version)   # -sig : BOM Windows ignoré
            if section is None:
                print(f"Avertissement : aucune section '## {version}' dans {p.name} ; "
                      + (f"notes = {notes!r}." if notes else "publication sans notes."))
            else:
                notes = section
        else:
            print(f"Avertissement : notes introuvables ({p}), publication sans notes.")

    apk = Path(args.apk) if args.apk else DIST / f"DodoTopia-Mobile-{version}.apk"
    if not apk.is_absolute():
        apk = ROOT / apk
    if not apk.is_file():
        print(f"ERREUR : APK manquant : {apk}")
        return 2
    if apk.suffix.lower() != ".apk":
        print(f"ERREUR : {apk.name} n'est pas un fichier .apk.")
        return 2
    with open(apk, "rb") as f:
        if f.read(4) != APK_MAGIC:
            print(f"ERREUR : {apk.name} n'est pas une archive APK valide.")
            return 2
    if version not in apk.name:
        print(f"Avertissement : le nom {apk.name} ne contient pas la version {version}.")
    print(f"sha256 de {apk.name} ...", end=" ", flush=True)
    sha = sha256_file(apk)
    print(sha[:16], f"({apk.stat().st_size / 1_048_576:.1f} Mo)")

    api = Api(url, token)
    print(f"Serveur : {api.url}")
    status, health = api.request("GET", "/api/health")
    if status != 200:
        print(f"ERREUR : /api/health -> {status} {_detail(health)}")
        return 1
    print(f"  serveur {health.get('version')} ok")
    status, body = api.request("GET", "/api/admin/releases/check")
    if status != 200:
        print(f"ERREUR : jeton de publication refusé ({status} {_detail(body)}). Vérifie PUBLISH_TOKEN.")
        return 1

    status, latest = api.request("GET", "/api/mobile/latest")
    if status == 200 and not args.force:
        if latest.get("version") == version:
            print(f"ERREUR : la version Android {version} est déjà publiée (le {latest.get('published_at')}). "
                  "Utilise --force pour la republier.")
            return 1
        if version_key(latest["version"]) > version_key(version):
            print(f"ERREUR : le serveur sert déjà une version Android plus récente ({latest['version']}). "
                  "Utilise --force si c'est voulu (elle ne deviendra pas latest).")
            return 1
    elif status not in (200, 404):
        print(f"ERREUR : /api/mobile/latest -> {status} {_detail(latest)} (serveur sans canal Android ?)")
        return 1

    if args.dry_run:
        print(f"[dry-run] Publierait la version Android {version}, {len(notes)} caractères de notes :")
        print(f"  PUT /api/admin/mobile/releases/{version}/apk  {apk.name}  {sha}")
        print(f"  POST /api/admin/mobile/releases/{version}/publish")
        print("[dry-run] Rien n'a été envoyé.")
        return 0

    print(f"Envoi de {apk.name} ...", flush=True)
    status, body = api.put_file(f"/api/admin/mobile/releases/{version}/apk", apk, sha)
    if status != 200:
        print(f"ERREUR : PUT apk -> {status} {_detail(body)}")
        return 1
    print(f"  ok -> {body.get('url')}")
    status, body = api.json("POST", f"/api/admin/mobile/releases/{version}/publish", {"notes": notes})
    if status != 200:
        print(f"ERREUR : publish -> {status} {_detail(body)}")
        return 1
    print(f"Version Android {version} publiée ({body.get('published_at')}).")

    status, latest = api.request("GET", "/api/mobile/latest")
    if status != 200 or latest.get("version") != version:
        print(f"ERREUR : latest = {latest.get('version') if status == 200 else status}, attendu {version}")
        return 1
    if latest.get("sha256") != sha:
        print(f"ERREUR : le serveur annonce l'empreinte {latest.get('sha256')}, attendu {sha}")
        return 1
    print(f"OK : {version} est maintenant la dernière version Android servie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
