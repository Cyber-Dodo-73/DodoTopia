"""Import d'un MIDI par lien : BitMidi, ou URL https directe d'un `.mid`.

Le serveur va chercher le fichier à la place du client, le valide avec le même scanner que la bibliothèque, le
garde en cache disque 7 jours et rend un jeton de téléchargement à usage unique (10 min). **Rien n'est publié
dans la bibliothèque** : le joueur récupère le fichier, puis décide lui-même de le déposer.

Anti-SSRF, à chaque requête sortante (redirections comprises, 2 au plus) : https seul, port 443, hôte sur liste
blanche pour BitMidi (et pour les URL directes si IMPORT_DIRECT_HOSTS est défini), résolution DNS et refus
de toute adresse non publique (privée, loopback, link-local, réservée, multicast…), pas de proxy d'environnement,
délai de 10 s, taille plafonnée pendant la lecture. Limite connue : l'adresse est résolue une seconde fois par
httpx au moment de la connexion (fenêtre de « DNS rebinding » très courte).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from . import stats
from .auth import api_error, get_current_user, settings_of
from .config import SERVER_VERSION, Settings
from .library import MidiError, clean_title, content_disposition, safe_ascii_filename, validate_midi
from .ratelimit import limit
from .schemas import ImportIn, clean_text

log = logging.getLogger("dodo.import")
router = APIRouter()

USER_AGENT = f"DodoTopia/{SERVER_VERSION} (+https://dodotopia.cyber-dodo.fr)"
BITMIDI_HOSTS = frozenset({"bitmidi.com", "www.bitmidi.com"})
MAX_PAGE_BYTES = 1024 * 1024                    # page HTML de BitMidi lue pour trouver le lien du fichier
MAX_TOKENS = 5000
_BITMIDI_SLUG = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9._~-]{0,200})/?$")
_BITMIDI_UPLOAD = re.compile(r"""["'](?:https://(?:www\.)?bitmidi\.com)?(/uploads/\d{1,12}\.midi?)["']""", re.I)
_BITMIDI_TITLE = re.compile(r"<h1[^>]*>([^<]{1,300})</h1>", re.I)
REDIRECT_CODES = (301, 302, 303, 307, 308)

# Transport httpx : None en production ; les tests y mettent un `httpx.MockTransport` (aucun appel réseau réel).
TRANSPORT: httpx.BaseTransport | None = None


class ImportFailure(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Source:
    kind: str                                   # bitmidi | direct
    key: str                                    # identifiant dans la source (slug, URL)
    source_url: str                             # page d'origine, affichable
    source_name: str
    fetch_url: str                              # URL du fichier (BitMidi : de la page, résolue ensuite)
    allowed_hosts: frozenset[str] | None        # None = tout hôte public
    filename: str = "morceau.mid"
    author: str | None = None
    extra: dict = field(default_factory=dict)


# --- Résolution du lien ---------------------------------------------------------------------------------------

def resolve_source(url_text: str, settings: Settings) -> Source:
    text = (url_text or "").strip()
    if re.search(r"[\s\x00-\x1f\x7f]", text):
        raise ImportFailure(422, "bad_url", "Lien invalide.")
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        raise ImportFailure(422, "bad_url", "Lien invalide.")
    if parts.scheme.lower() != "https":
        raise ImportFailure(422, "https_required", "Seuls les liens https:// sont acceptés.")
    if not host or parts.username or parts.password or port not in (None, 443):
        raise ImportFailure(422, "bad_url", "Lien invalide.")
    if host in BITMIDI_HOSTS:
        path = unquote(parts.path)
        m = _BITMIDI_SLUG.match(path)
        if parts.path.startswith("/uploads/") and re.match(r"^/uploads/\d{1,12}\.midi?$", parts.path, re.I):
            stem = parts.path.rsplit("/", 1)[-1]
            return Source("bitmidi", stem, f"https://bitmidi.com{parts.path}", "BitMidi",
                          f"https://bitmidi.com{parts.path}", BITMIDI_HOSTS, filename=stem)
        if not m:
            raise ImportFailure(422, "unsupported_url", "Lien BitMidi non reconnu (attendu bitmidi.com/<morceau>).")
        slug = m.group(1)
        stem = re.sub(r"-midi?$", "", slug, flags=re.I) or slug
        return Source("bitmidi", slug, f"https://bitmidi.com/{slug}", "BitMidi", "", BITMIDI_HOSTS,
                      filename=f"{stem}.mid", extra={"page_url": f"https://bitmidi.com/{slug}"})
    if parts.path.lower().endswith((".mid", ".midi")):
        allowed = frozenset(settings.direct_import_hosts) or None
        if allowed is not None and host not in allowed:
            raise ImportFailure(422, "host_not_allowed", "Ce site n'est pas autorisé pour l'import direct.")
        name = unquote(parts.path.rsplit("/", 1)[-1]) or "morceau.mid"
        return Source("direct", text, text, clean_text(host, 60), text, allowed, filename=name)
    raise ImportFailure(422, "host_not_allowed",
                        "Lien non pris en charge : BitMidi ou lien direct vers un fichier .mid.")


# --- Réseau ------------------------------------------------------------------------------------------------------

def resolve_host(host: str) -> list[str]:
    """Adresses IP d'un nom d'hôte (remplacé dans les tests)."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or not ip.is_global)


def check_url(url: str, allowed_hosts: frozenset[str] | None) -> None:
    """https, port 443, hôte autorisé, et toutes ses adresses publiques — sinon ImportFailure."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        raise ImportFailure(422, "bad_url", "Lien invalide.")
    if parts.scheme.lower() != "https":
        raise ImportFailure(422, "https_required", "Seuls les liens https:// sont acceptés (redirection comprise).")
    if not host or parts.username or parts.password or port not in (None, 443):
        raise ImportFailure(422, "bad_url", "Lien invalide.")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ImportFailure(422, "host_not_allowed", "Redirection vers un site non autorisé.")
    try:
        ipaddress.ip_address(host.strip("[]"))
        addresses = [host.strip("[]")]
    except ValueError:
        try:
            addresses = resolve_host(host)
        except (OSError, UnicodeError):
            raise ImportFailure(502, "dns_error", "Nom de domaine introuvable.")
    if not addresses or not all(is_public_ip(a) for a in addresses):
        raise ImportFailure(403, "private_address", "Adresse interne ou réservée refusée.")


def fetch(url: str, settings: Settings, allowed_hosts: frozenset[str] | None, max_bytes: int) -> tuple[bytes, str]:
    """GET borné (taille, délai, redirections vérifiées une par une). Renvoie (octets, URL finale)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    current = url
    try:
        with httpx.Client(transport=TRANSPORT, timeout=settings.IMPORT_TIMEOUT_S, follow_redirects=False,
                          trust_env=False) as client:
            for _ in range(settings.IMPORT_MAX_REDIRECTS + 1):
                check_url(current, allowed_hosts)
                with client.stream("GET", current, headers=headers) as r:
                    if r.status_code in REDIRECT_CODES:
                        location = r.headers.get("location")
                        if not location:
                            raise ImportFailure(502, "upstream_error", "Redirection sans destination.")
                        current = urljoin(current, location)
                        continue
                    if r.status_code in (404, 410):
                        raise ImportFailure(404, "not_found", "Fichier introuvable sur le site d'origine.")
                    if r.status_code != 200:
                        raise ImportFailure(502, "upstream_error", f"Le site d'origine a répondu {r.status_code}.")
                    declared = r.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > max_bytes:
                        raise ImportFailure(413, "too_large", f"Fichier trop gros (max {max_bytes // 1024} Ko).")
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            raise ImportFailure(413, "too_large", f"Fichier trop gros (max {max_bytes // 1024} Ko).")
                    return bytes(buf), current
            raise ImportFailure(502, "too_many_redirects", "Trop de redirections.")
    except ImportFailure:
        raise
    except httpx.TimeoutException:
        raise ImportFailure(504, "timeout", "Le site d'origine ne répond pas.")
    except httpx.HTTPError as e:
        log.info("import : erreur réseau %s sur %s", type(e).__name__, current)
        raise ImportFailure(502, "upstream_error", "Le site d'origine est injoignable.")


# --- Cache ----------------------------------------------------------------------------------------------------------

def cache_paths(settings: Settings, source: Source) -> tuple[Path, Path]:
    digest = hashlib.sha256(f"{source.kind}\n{source.key}".encode("utf-8")).hexdigest()[:40]
    base = settings.import_cache_dir / f"{source.kind}-{digest}"
    return base.with_suffix(".mid"), base.with_suffix(".json")


def read_cache(settings: Settings, source: Source) -> tuple[bytes, dict] | None:
    mid, meta = cache_paths(settings, source)
    try:
        if time.time() - mid.stat().st_mtime > settings.IMPORT_CACHE_DAYS * 86400:
            return None
        return mid.read_bytes(), json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_cache(settings: Settings, source: Source, data: bytes, meta: dict) -> Path:
    mid, meta_path = cache_paths(settings, source)
    mid.parent.mkdir(parents=True, exist_ok=True)
    tmp = mid.with_suffix(".part")
    tmp.write_bytes(data)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    tmp.replace(mid)
    return mid


def purge_cache(settings: Settings) -> None:
    """Fichiers de plus de IMPORT_CACHE_DAYS jours (tâche de nettoyage)."""
    cutoff = time.time() - settings.IMPORT_CACHE_DAYS * 86400
    for p in settings.import_cache_dir.glob("*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


# --- Import -------------------------------------------------------------------------------------------------------

def import_midi(url_text: str, settings: Settings) -> tuple[bytes, dict, Path]:
    """Résout, télécharge (ou lit le cache), valide. Renvoie (octets, métadonnées publiques, fichier en cache)."""
    source = resolve_source(url_text, settings)
    cached = read_cache(settings, source)
    if cached is not None:
        data, meta = cached
        return data, meta, cache_paths(settings, source)[0]
    if source.kind == "bitmidi" and not source.fetch_url:
        page, _ = fetch(source.extra["page_url"], settings, source.allowed_hosts, MAX_PAGE_BYTES)
        html = page.decode("utf-8", errors="replace")
        m = _BITMIDI_UPLOAD.search(html)
        if not m:
            raise ImportFailure(404, "not_found", "Aucun fichier MIDI trouvé sur cette page BitMidi.")
        source.fetch_url = f"https://bitmidi.com{m.group(1)}"
        t = _BITMIDI_TITLE.search(html)
        if t:
            title = clean_text(t.group(1).replace("&amp;", "&"), 120)
            if title:
                source.filename = f"{title}.mid"
    data, _ = fetch(source.fetch_url, settings, source.allowed_hosts, settings.MAX_MIDI_BYTES)
    if not data:
        raise ImportFailure(422, "invalid_midi", "Fichier vide.")
    try:
        validate_midi(data, settings)
    except MidiError as e:
        raise ImportFailure(422, "invalid_midi", str(e))
    stem = clean_title(source.filename) or "morceau"
    meta = {"filename": safe_ascii_filename(stem, fallback="morceau"), "title": clean_text(stem, 120),
            "source_url": source.source_url, "source_name": source.source_name, "source_author": source.author}
    path = write_cache(settings, source, data, meta)
    return data, meta, path


def _tokens(request: Request) -> dict:
    tokens = getattr(request.app.state, "import_tokens", None)
    if tokens is None:
        tokens = request.app.state.import_tokens = {}
    now = time.monotonic()
    for k in [k for k, v in tokens.items() if v["expires"] <= now]:
        del tokens[k]
    return tokens


@router.post("/api/import", dependencies=[Depends(limit("import", 10, 60, by="user"))])
def import_by_link(body: ImportIn, request: Request, user=Depends(get_current_user)):
    """`{url}` -> `{ok, filename, size, sha256, source_url, source_name, source_author, download_token}`."""
    settings = settings_of(request)
    try:
        data, meta, path = import_midi(body.url, settings)
    except ImportFailure as e:
        raise api_error(e.status, e.code, e.message)
    sha = hashlib.sha256(data).hexdigest()
    stats.hit(request.app, "import", meta.get("source_name") or "?")
    tokens = _tokens(request)
    if len(tokens) >= MAX_TOKENS:
        tokens.pop(next(iter(tokens)))
    token = secrets.token_urlsafe(32)
    tokens[token] = {"expires": time.monotonic() + settings.IMPORT_TOKEN_TTL_S, "path": str(path), "sha256": sha,
                     "title": meta.get("title") or "morceau", "user_id": user["id"]}
    return {"ok": True, "filename": meta["filename"], "size": len(data), "sha256": sha,
            "source_url": meta["source_url"], "source_name": meta["source_name"],
            "source_author": meta.get("source_author"), "download_token": token,
            "download_url": f"{settings.public_url}/api/import/{token}",
            "expires_in": int(settings.IMPORT_TOKEN_TTL_S)}


@router.get("/api/import/{token}", dependencies=[Depends(limit("import_get", 30, 60))])
def import_download(token: str, request: Request):
    """Le fichier importé, une seule fois (jeton de 10 min)."""
    entry = _tokens(request).pop(token[:128], None)
    if entry is None:
        raise api_error(404, "not_found", "Jeton inconnu, expiré ou déjà utilisé.")
    try:
        data = Path(entry["path"]).read_bytes()
    except OSError:
        raise api_error(410, "gone", "Le fichier importé n'est plus disponible : relance l'import.")
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise api_error(410, "gone", "Le fichier importé a changé : relance l'import.")
    return Response(data, media_type="audio/midi",
                    headers={"Content-Disposition": content_disposition(entry["title"], entry["sha256"]),
                             "X-Sha256": entry["sha256"], "Cache-Control": "no-store",
                             "X-Content-Type-Options": "nosniff"})
