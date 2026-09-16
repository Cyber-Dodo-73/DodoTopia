"""Publie une version de DodoTopia sur le serveur (stdlib, + PyNaCl pour signer le manifeste).

    py publish_release.py --version 1.7.0 [--notes-file CHANGELOG.md | --notes "..."] [--mandatory]
                          [--dry-run] [--force] [--skip-linux] [--release-dir release]
    py publish_release.py --gen-key        # imprime une paire de clés Ed25519 (privée + publique, base64)

PUBLISH_URL, PUBLISH_TOKEN et RELEASE_SIGNING_KEY sont lus dans l'environnement, sinon dans `publish.env`
(lignes CLE=valeur). Étapes : sha256 de chaque artefact, PUT de chaque asset (streamé, timeout 600 s), POST publish,
puis GET latest. Code de sortie 0 seulement si la version publiée est bien devenue `latest`.

Manifeste signé : RELEASE_SIGNING_KEY (clé privée Ed25519, 32 octets en base64, secret CI) signe le texte canonique
`{"assets":{platform:{"filename","sha256","size"}},"mandatory":bool,"published_at":iso,"version":v}` (json.dumps
sort_keys, sans espace : exactement ce que reconstruit server/app/releases.py et que vérifie online.py). Sans clé,
la publication part sans signature (rétro-compatibilité ; refusée par un serveur qui exige une signature).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")
CHUNK = 1024 * 1024
ROOT = Path(__file__).resolve().parent


def version_key(v: str) -> tuple[int, ...]:
    """Même règle que server/app/releases.py : '1.10.0' -> (1, 10, 0)."""
    if not VERSION_RE.match(v or ""):
        raise ValueError(f"Version invalide : {v!r}")
    return tuple(int(x) for x in v.split("."))


def read_version_py() -> str:
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', (ROOT / "version.py").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("VERSION introuvable dans version.py")
    return m.group(1)


def load_publish_env() -> dict:
    """PUBLISH_URL / PUBLISH_TOKEN / RELEASE_SIGNING_KEY : environnement d'abord, puis publish.env à côté du script."""
    values = {}
    p = ROOT / "publish.env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("PUBLISH_URL", "PUBLISH_TOKEN", "RELEASE_SIGNING_KEY"):
        if os.environ.get(k):
            values[k] = os.environ[k]
    return values


# --- signature du manifeste (Ed25519) --------------------------------------------

def signed_payload(version: str, assets: dict, mandatory: bool, published_at: str) -> str:
    """Même texte que server/app/releases.py.signed_payload : JSON canonique de
    {version, assets{platform:{sha256, size, filename}}, mandatory, published_at}."""
    doc = {
        "version": version,
        "assets": {p: {"sha256": a["sha256"], "size": a["size"], "filename": a["filename"]}
                   for p, a in sorted(assets.items())},
        "mandatory": bool(mandatory),
        "published_at": published_at,
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def now_iso_utc() -> str:
    """Horodatage ISO 8601 UTC à la seconde, suffixe Z (ex. 2026-09-16T10:04:05Z)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sign_payload(private_key_b64: str, payload: str) -> str:
    """Signature Ed25519 (base64, 64 octets) de `payload` avec la clé privée base64 (32 octets)."""
    try:
        from nacl.signing import SigningKey
    except ImportError:
        raise SystemExit("PyNaCl manquant pour signer le manifeste : pip install pynacl")
    try:
        raw = base64.b64decode(private_key_b64.strip(), validate=True)
    except ValueError:
        raise SystemExit("RELEASE_SIGNING_KEY : base64 invalide")
    if len(raw) != 32:
        raise SystemExit(f"RELEASE_SIGNING_KEY : {len(raw)} octets au lieu de 32")
    sig = SigningKey(raw).sign(payload.encode("utf-8")).signature
    return base64.b64encode(sig).decode("ascii")


def gen_key() -> int:
    """Imprime une nouvelle paire Ed25519 : la privée va dans le secret CI RELEASE_SIGNING_KEY (jamais dans git),
    la publique dans RELEASE_SIGNING_PUBLIC_KEY (.env du serveur) ET dans online.RELEASE_SIGNING_PUBLIC_KEY."""
    try:
        from nacl.signing import SigningKey
    except ImportError:
        print("PyNaCl manquant : pip install pynacl")
        return 2
    k = SigningKey.generate()
    priv = base64.b64encode(bytes(k)).decode("ascii")
    pub = base64.b64encode(bytes(k.verify_key)).decode("ascii")
    print("Clé privée  (secret GitHub RELEASE_SIGNING_KEY, ou RELEASE_SIGNING_KEY= dans publish.env ; ne la commite jamais) :")
    print(f"  {priv}")
    print("Clé publique (RELEASE_SIGNING_PUBLIC_KEY dans le .env du serveur ET dans online.py) :")
    print(f"  {pub}")
    return 0


def notes_for_version(text: str, version: str) -> str | None:
    """Section `## <version>` d'un CHANGELOG multi-versions (titres acceptés : `## 1.7.0`, `## [1.7.0]`,
    `## v1.7.0 - 2026-09-13`). Sans titre `## ` : tout le texte. Version absente : None."""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
    if not heads:
        return text.strip()
    for n, i in enumerate(heads):
        m = re.match(r"\[?v?([0-9]+(?:\.[0-9]+){1,3})\]?", lines[i][3:].strip())
        if m and m.group(1) == version:
            end = heads[n + 1] if n + 1 < len(heads) else len(lines)
            return "\n".join(lines[i + 1:end]).strip()
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


class Api:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
                timeout: float = 30, retries: int = 4) -> tuple[int, dict]:
        """Un envoi de plusieurs centaines de Mo peut saturer le serveur juste avant : le reverse proxy
        repond alors 502/503/504 le temps qu'il redevienne joignable. On reessaie avant d'abandonner."""
        last = (0, {})
        for attempt in range(retries):
            req = urllib.request.Request(self.url + path, data=body, method=method)
            req.add_header("Accept", "application/json")
            if self.token:
                req.add_header("X-Publish-Token", self.token)
            for k, v in (headers or {}).items():
                req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, _json(r.read())
            except urllib.error.HTTPError as e:
                last = (e.code, _read_error(e))
                if e.code not in (502, 503, 504):
                    return last
            except (urllib.error.URLError, OSError) as e:
                last = (0, {"detail": {"code": "network", "message": str(getattr(e, "reason", e))}})
            if attempt < retries - 1:
                delay = 3 * (attempt + 1)
                print(f"  passerelle indisponible ({last[0] or 'reseau'}), nouvelle tentative dans {delay} s...")
                time.sleep(delay)
        return last

    def json(self, method: str, path: str, obj: dict) -> tuple[int, dict]:
        return self.request(method, path, json.dumps(obj).encode("utf-8"), {"Content-Type": "application/json"})

    def put_file(self, path: str, file: Path, sha: str) -> tuple[int, dict]:
        size = file.stat().st_size
        with open(file, "rb") as f:
            req = urllib.request.Request(self.url + path, data=f, method="PUT")
            req.add_header("X-Publish-Token", self.token)
            req.add_header("X-Sha256", sha)
            req.add_header("X-Filename", file.name)
            req.add_header("Content-Type", "application/octet-stream")
            req.add_header("Content-Length", str(size))
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    return r.status, _json(r.read())
            except urllib.error.HTTPError as e:
                return e.code, _read_error(e)


def _read_error(e: urllib.error.HTTPError) -> dict:
    """Le serveur peut refuser (403, 413) sans lire tout le corps envoyé : la lecture de la réponse peut échouer."""
    try:
        return _json(e.read())
    except OSError:
        return {"detail": {"code": "http_error", "message": e.reason}}


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        return {"raw": raw[:300].decode("utf-8", "replace")}


def _detail(body: dict) -> str:
    d = body.get("detail", body)
    return d.get("message", json.dumps(d, ensure_ascii=False)) if isinstance(d, dict) else str(d)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publie une version de DodoTopia sur le serveur.")
    ap.add_argument("--version", help="version à publier (défaut : VERSION de version.py)")
    ap.add_argument("--release-dir", default="release", help="dossier des artefacts (défaut : release/)")
    ap.add_argument("--notes", default=None, help="notes de version")
    ap.add_argument("--notes-file", default=None, help="fichier de notes (ex. CHANGELOG.md)")
    ap.add_argument("--mandatory", action="store_true", help="mise à jour obligatoire")
    ap.add_argument("--dry-run", action="store_true", help="vérifie tout sans rien envoyer")
    ap.add_argument("--force", action="store_true", help="republie même si la version existe déjà sur le serveur")
    ap.add_argument("--skip-linux", action="store_true", help="ne pas exiger ni envoyer l'archive Linux")
    ap.add_argument("--url", default=None, help="PUBLISH_URL (sinon env / publish.env)")
    ap.add_argument("--token", default=None, help="PUBLISH_TOKEN (sinon env / publish.env)")
    ap.add_argument("--gen-key", action="store_true", help="imprime une paire de clés Ed25519 et s'arrête")
    args = ap.parse_args(argv)

    if args.gen_key:
        return gen_key()

    version = args.version or read_version_py()
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
    signing_key = (env.get("RELEASE_SIGNING_KEY") or "").strip()
    if signing_key:
        sign_payload(signing_key, "test")      # clé et PyNaCl vérifiés avant d'envoyer des centaines de Mo
    else:
        print("Avertissement : RELEASE_SIGNING_KEY absente, le manifeste sera publié SANS signature "
              "(refusé par un serveur qui l'exige ; `py publish_release.py --gen-key` pour créer la paire).")

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

    rd = Path(args.release_dir)
    if not rd.is_absolute():
        rd = ROOT / rd
    wanted = [
        ("windows-setup", rd / f"DodoTopia-{version}-Setup.exe", True),
        ("windows-portable", rd / f"DodoTopia-{version}-portable.zip", True),
        ("linux-x64", rd / f"DodoTopia-{version}-linux-x64.tar.gz", False),
    ]
    assets = []
    for platform, path, required in wanted:
        if platform == "linux-x64" and args.skip_linux:
            continue
        if not path.is_file():
            if required:
                print(f"ERREUR : artefact manquant : {path}")
                return 2
            print(f"Avertissement : {path.name} absent, la plateforme {platform} ne sera pas publiée.")
            continue
        print(f"sha256 de {path.name} ...", end=" ", flush=True)
        sha = sha256_file(path)
        print(sha[:16], f"({path.stat().st_size / 1_048_576:.1f} Mo)")
        assets.append((platform, path, sha))

    api = Api(url, token)
    print(f"Serveur : {api.url}")
    status, health = api.request("GET", "/api/health")
    if status != 200:
        print(f"ERREUR : /api/health -> {status} {_detail(health)}")
        return 1
    print(f"  serveur {health.get('version')} ok, min_client {health.get('min_client')}")
    status, body = api.request("GET", "/api/admin/releases/check")
    if status != 200:
        print(f"ERREUR : jeton de publication refusé ({status} {_detail(body)}). Vérifie PUBLISH_TOKEN.")
        return 1

    status, existing = api.request("GET", f"/api/releases/{version}")
    if status == 200 and not args.force:
        print(f"ERREUR : la version {version} est déjà publiée (publiée le {existing.get('published_at')}). "
              "Utilise --force pour la republier.")
        return 1
    status, latest = api.request("GET", "/api/releases/latest")
    if status == 200 and version_key(latest["version"]) > version_key(version) and not args.force:
        print(f"ERREUR : le serveur sert déjà une version plus récente ({latest['version']}). "
              "Utilise --force si c'est voulu (elle ne deviendra pas latest).")
        return 1

    if args.dry_run:
        print(f"[dry-run] Publierait {version} ({'obligatoire' if args.mandatory else 'facultative'}, "
              f"{'manifeste signé' if signing_key else 'sans signature'}), {len(notes)} caractères de notes, assets :")
        for platform, path, sha in assets:
            print(f"  PUT /api/admin/releases/{version}/assets/{platform}  {path.name}  {sha}")
        print(f"  POST /api/admin/releases/{version}/publish")
        print("[dry-run] Rien n'a été envoyé.")
        return 0

    uploaded = {}
    for platform, path, sha in assets:
        print(f"Envoi de {path.name} ({platform}) ...", flush=True)
        status, body = api.put_file(f"/api/admin/releases/{version}/assets/{platform}", path, sha)
        if status != 200:
            print(f"ERREUR : PUT {platform} -> {status} {_detail(body)}")
            return 1
        print(f"  ok -> {body.get('url')}")
        # Le manifeste signé décrit ce que le serveur a enregistré (sa réponse), pas ce qu'on croit avoir envoyé.
        uploaded[platform] = {"sha256": body.get("sha256") or sha, "size": int(body.get("size") or path.stat().st_size),
                              "filename": body.get("filename") or path.name}

    publish_body = {"notes": notes, "mandatory": bool(args.mandatory)}
    if signing_key:
        published_at = now_iso_utc()
        payload = signed_payload(version, uploaded, bool(args.mandatory), published_at)
        publish_body.update({"published_at": published_at, "signature": sign_payload(signing_key, payload)})
        print(f"Manifeste signé ({published_at}) : {payload}")
    status, body = api.json("POST", f"/api/admin/releases/{version}/publish", publish_body)
    if status != 200:
        print(f"ERREUR : publish -> {status} {_detail(body)}")
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        if signing_key and detail.get("code") == "bad_signature":
            print("  Le serveur a signé un autre jeu d'assets que celui envoyé : une plateforme déposée lors d'une "
                  "publication précédente (ex. --skip-linux avec une archive Linux déjà présente) ? Republie-la, ou "
                  "supprime la version (DELETE /api/admin/releases/<v>) avant de recommencer.")
        return 1
    if signing_key and not body.get("signature"):
        print("Avertissement : le serveur n'a pas renvoyé la signature dans le manifeste.")
    print(f"Version {version} publiée ({body.get('published_at')}), plateformes : {', '.join(sorted(body['assets']))}")

    status, latest = api.request("GET", "/api/releases/latest")
    if status != 200 or latest.get("version") != version:
        print(f"ERREUR : latest = {latest.get('version') if status == 200 else status}, attendu {version}")
        return 1
    print(f"OK : {version} est maintenant la dernière version servie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
