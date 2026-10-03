# -*- coding: utf-8 -*-
"""Liens `dodotopia://` : analyse et validation stricte, sans aucun effet de bord.

Un lien vient d'une page web, d'un message Discord ou de n'importe quel programme : il n'est jamais digne
de confiance. `parse()` n'accepte que quatre formes exactes et renvoie None pour tout le reste ; l'Api
demande ensuite une confirmation avant d'agir (voir api/integrations.py).

    dodotopia://song/<id entier>          morceau de la bibliotheque partagee
    dodotopia://room/<code>               salon (6 caracteres de room.CODE_ALPHABET)
    dodotopia://drawing/<id entier>       dessin partage
    dodotopia://import?url=<https://...>  fichier MIDI distant (bitmidi.com, ou .mid/.midi)

Une barre oblique finale est toleree (certains navigateurs l'ajoutent). Le nom de l'action et le code de
salon sont insensibles a la casse ; tout le reste (port, identifiants, fragment, parametres en trop,
encodage dans le chemin, caracteres de controle ou non ASCII) est refuse.
"""
import re
import urllib.parse

SCHEME = "dodotopia"
MAX_LEN = 2048
# meme alphabet que room.CODE_ALPHABET (pas de I, O, 0, 1) : recopie pour ne pas importer le client reseau
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 6
MAX_ID = 2 ** 53 - 1                      # identifiant representable en JavaScript
IMPORT_HOSTS = ("bitmidi.com",)
ACTIONS = ("song", "room", "drawing", "import")

_ID_RE = re.compile(r"^[1-9][0-9]{0,15}$")
_CODE_RE = re.compile("^[" + CODE_ALPHABET + "]{%d}$" % CODE_LEN)
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PATH_CHARS_RE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@/%-]*$")
_QUERY_CHARS_RE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@/?%-]*$")


def _clean_ascii(s):
    """Vrai si `s` ne contient que de l'ASCII imprimable sans espace."""
    return all(0x21 <= ord(c) <= 0x7E for c in s)


def _parse_id(segment):
    if not _ID_RE.match(segment):
        return None
    v = int(segment)
    return v if 0 < v <= MAX_ID else None


def _valid_host(host):
    """Nom de domaine DNS ordinaire (pas d'adresse IP, pas de nom sans point, pas de port ni d'identifiants)."""
    if not host or len(host) > 253:
        return False
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL_RE.match(lb) for lb in labels):
        return False
    return bool(re.search(r"[a-z]", labels[-1]))       # 127.0.0.1 -> refuse


def validate_import_url(url):
    """URL https d'un fichier MIDI distant, normalisee ; (url, hote) ou None."""
    if not isinstance(url, str) or not url or len(url) > MAX_LEN or not _clean_ascii(url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or parts.fragment:
        return None
    netloc = parts.netloc
    if not netloc or "@" in netloc or "\\" in url:
        return None
    host = netloc.lower()
    if host.endswith(":443"):
        host = host[:-4]
    if ":" in host or not _valid_host(host):
        return None
    path = parts.path or "/"
    if not _PATH_CHARS_RE.match(path) or not _QUERY_CHARS_RE.match(parts.query or ""):
        return None
    # chemin : aucun segment « . » ou « .. », meme encode (une ou deux fois)
    for seg in path.split("/"):
        dec = urllib.parse.unquote(urllib.parse.unquote(seg))
        if dec in (".", "..") or "/" in dec or "\\" in dec or not all(0x20 <= ord(c) <= 0x7E for c in dec):
            return None
    known = any(host == d or host.endswith("." + d) for d in IMPORT_HOSTS)
    if not known and not path.lower().endswith((".mid", ".midi")):
        return None
    norm = urllib.parse.urlunsplit(("https", host, path, parts.query, ""))
    return norm, host


def parse(url):
    """`{"action": "song", "id": 12}`, `{"action": "room", "code": "K7P2QD"}`, `{"action": "drawing", "id": 3}`,
    `{"action": "import", "url": "https://...", "host": "bitmidi.com"}` ; None si le lien n'est pas exactement
    l'une de ces formes."""
    if not isinstance(url, str) or not url or len(url) > MAX_LEN:
        return None
    if not _clean_ascii(url):
        return None
    prefix = SCHEME + "://"
    if url[:len(prefix)].lower() != prefix:
        return None
    rest = url[len(prefix):]
    if "#" in rest or "\\" in rest:
        return None
    head, sep, query = rest.partition("?")
    if sep and not query:
        return None
    if head.endswith("/"):
        head = head[:-1]
    segs = head.split("/")
    action = segs[0].lower()
    if action not in ACTIONS:
        return None
    if action == "import":
        if len(segs) != 1 or not query:
            return None
        try:
            pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True,
                                           max_num_fields=1)
        except ValueError:
            return None
        if len(pairs) != 1 or pairs[0][0] != "url":
            return None
        checked = validate_import_url(pairs[0][1])
        if not checked:
            return None
        return {"action": "import", "url": checked[0], "host": checked[1]}
    if sep or len(segs) != 2:
        return None
    arg = segs[1]
    if action == "room":
        code = arg.upper()
        return {"action": "room", "code": code} if _CODE_RE.match(code) else None
    oid = _parse_id(arg)
    return {"action": action, "id": oid} if oid is not None else None


def urls_from_argv(argv):
    """Liens passes en ligne de commande : `--url <lien>` (installeur, .desktop) ou un argument qui commence
    directement par dodotopia:. Les liens sont renvoyes tels quels (parse() les valide ensuite)."""
    out = []
    args = list(argv or [])
    i = 0
    while i < len(args):
        a = str(args[i])
        if a == "--url" and i + 1 < len(args):
            out.append(str(args[i + 1]))
            i += 2
            continue
        if a.startswith("--url="):
            out.append(a[len("--url="):])
        elif a[:len(SCHEME) + 1].lower() == SCHEME + ":":
            out.append(a)
        i += 1
    return out
