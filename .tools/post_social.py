# -*- coding: utf-8 -*-
"""Annonce d'une version de DodoTopia sur X et Bluesky, à partir de `version.py` et de la section du CHANGELOG.

    py .tools/post_social.py --dry-run            affiche les messages, ne poste rien
    py .tools/post_social.py                      poste sur chaque réseau dont les secrets sont définis
    py .tools/post_social.py --version 1.9.0 --only bluesky

Secrets (variables d'environnement ; un réseau sans ses secrets est ignoré, jamais une erreur) :
  X (API v2, OAuth 1.0a utilisateur) : X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
  Bluesky : BSKY_HANDLE, BSKY_APP_PASSWORD (mot de passe d'application), BSKY_PDS (facultatif, défaut bsky.social)

Bibliothèque standard seulement (lancé tel quel par la CI). Code de retour 1 si un envoi a échoué.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_URL = "https://dodotopia.cyber-dodo.fr/fr/telecharger"
X_TWEETS_URL = "https://api.twitter.com/2/tweets"
X_LIMIT = 280
X_URL_WEIGHT = 23                     # X compte toute URL pour 23 caractères
BSKY_LIMIT = 300
USER_AGENT = "DodoTopia-release-bot (+https://dodotopia.cyber-dodo.fr)"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# --- Contenu ---------------------------------------------------------------------------------------------------

def read_version(root: Path = ROOT) -> str:
    text = (root / "version.py").read_text(encoding="utf-8")
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("VERSION introuvable dans version.py")
    return m.group(1)


def changelog_section(text: str, version: str) -> str | None:
    """Section `## <version>` du CHANGELOG (même règle que publish_release.notes_for_version)."""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
    for n, i in enumerate(heads):
        m = re.match(r"\[?v?([0-9]+(?:\.[0-9]+){1,3})\]?", lines[i][3:].strip())
        if m and m.group(1) == version:
            end = heads[n + 1] if n + 1 < len(heads) else len(lines)
            return "\n".join(lines[i + 1:end]).strip()
    return None


def highlights(section: str, max_items: int = 6) -> list[str]:
    """Titres courts des puces : le passage en gras s'il existe, sinon le début de la phrase."""
    out = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith(("- ", "* ")):
            continue
        body = line[2:].strip()
        m = re.match(r"\*\*(.+?)\*\*", body)
        if m:
            item = m.group(1)
        else:
            item = re.split(r"\s[:—–]\s|\. |\s\(", body, maxsplit=1)[0]
        item = re.sub(r"[`*_]", "", item).strip(" .:;")
        if len(item) > 70:
            item = item[:69].rstrip() + "…"
        if item:
            out.append(item)
        if len(out) >= max_items:
            break
    return out


def compose(version: str, section: str | None, url: str, limit: int, url_weight: int | None = None) -> str:
    """Message le plus riche qui tient dans `limit` caractères (l'URL comptée `url_weight` si donné)."""
    head = f"DodoTopia {version} est disponible !"
    items = highlights(section or "")
    url_len = url_weight if url_weight is not None else len(url)

    def size(parts: list[str]) -> int:
        text = "\n".join([head, *parts, ""])
        return len(text) + 1 + url_len

    kept: list[str] = []
    for item in items:
        if size([*[f"• {k}" for k in kept], f"• {item}"]) <= limit:
            kept.append(item)
    body = "\n".join([head, *[f"• {k}" for k in kept]])
    return f"{body}\n\n{url}" if kept else f"{head}\n{url}"


# --- X (OAuth 1.0a) ------------------------------------------------------------------------------------------------

def _pct(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def oauth1_header(method: str, url: str, consumer_key: str, consumer_secret: str, token: str, token_secret: str,
                  nonce: str | None = None, timestamp: str | None = None) -> str:
    """En-tête `Authorization: OAuth …` signé HMAC-SHA1 (le corps JSON n'entre pas dans la signature)."""
    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    base_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    pairs = sorted((_pct(k), _pct(v)) for k, v in [*params.items(), *query])
    param_str = "&".join(f"{k}={v}" for k, v in pairs)
    base = "&".join((method.upper(), _pct(base_url), _pct(param_str)))
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    params["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(params.items()))


def _request(url: str, payload: dict, headers: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8") or "{}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {e.code} sur {urllib.parse.urlsplit(url).netloc} : {detail}") from None
    return json.loads(body)


def post_x(text: str, env) -> str:
    auth = oauth1_header("POST", X_TWEETS_URL, env["X_API_KEY"], env["X_API_SECRET"], env["X_ACCESS_TOKEN"],
                         env["X_ACCESS_SECRET"])
    body = _request(X_TWEETS_URL, {"text": text}, {"Authorization": auth})
    return str((body.get("data") or {}).get("id", "?"))


# --- Bluesky ----------------------------------------------------------------------------------------------------------

def link_facets(text: str) -> list[dict]:
    """Facettes de lien (positions en octets UTF-8) pour chaque URL https du texte."""
    facets = []
    for m in re.finditer(r"https://[^\s]+", text):
        start = len(text[:m.start()].encode("utf-8"))
        end = start + len(m.group(0).encode("utf-8"))
        facets.append({"index": {"byteStart": start, "byteEnd": end},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
    return facets


def post_bluesky(text: str, env) -> str:
    pds = (env.get("BSKY_PDS") or "https://bsky.social").rstrip("/")
    if not pds.startswith("https://"):
        raise RuntimeError("BSKY_PDS doit commencer par https://")
    session = _request(f"{pds}/xrpc/com.atproto.server.createSession",
                       {"identifier": env["BSKY_HANDLE"], "password": env["BSKY_APP_PASSWORD"]}, {})
    record = {"$type": "app.bsky.feed.post", "text": text, "langs": ["fr"], "facets": link_facets(text),
              "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")}
    body = _request(f"{pds}/xrpc/com.atproto.repo.createRecord",
                    {"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
                    {"Authorization": f"Bearer {session['accessJwt']}"})
    return str(body.get("uri", "?"))


NETWORKS = {
    "x": (("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"), post_x, X_LIMIT, X_URL_WEIGHT),
    "bluesky": (("BSKY_HANDLE", "BSKY_APP_PASSWORD"), post_bluesky, BSKY_LIMIT, None),
}


def main(argv: list[str] | None = None, env=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", default="", help="version annoncée (défaut : version.py)")
    ap.add_argument("--changelog", default=str(ROOT / "CHANGELOG.md"))
    ap.add_argument("--url", default=DOWNLOAD_URL)
    ap.add_argument("--only", choices=sorted(NETWORKS), action="append", help="limiter à ce réseau (répétable)")
    ap.add_argument("--dry-run", action="store_true", help="afficher les messages sans rien poster")
    args = ap.parse_args(argv)
    env = os.environ if env is None else env

    version = args.version or read_version()
    path = Path(args.changelog)
    section = changelog_section(path.read_text(encoding="utf-8"), version) if path.is_file() else None
    if section is None:
        print(f"Section « {version} » absente du CHANGELOG : message court.")
    failures = 0
    for name in args.only or sorted(NETWORKS):
        keys, poster, limit, url_weight = NETWORKS[name]
        text = compose(version, section, args.url, limit, url_weight)
        missing = [k for k in keys if not env.get(k)]
        if args.dry_run:
            state = "secrets présents" if not missing else f"ignoré en vrai (manque {', '.join(missing)})"
            print(f"--- {name} ({len(text)} car., {state}) ---\n{text}\n")
            continue
        if missing:
            print(f"{name} : ignoré (secrets absents : {', '.join(missing)}).")
            continue
        try:
            ref = poster(text, env)
            print(f"{name} : publié ({ref}).")
        except Exception as e:  # noqa - un réseau en panne n'empêche pas l'autre
            failures += 1
            print(f"{name} : échec — {e}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
