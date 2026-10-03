"""Modèles pydantic des corps de requête et des messages WebSocket, et nettoyage des textes affichés."""
from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

SHA256_RE = r"^[0-9a-f]{64}$"

# Caractères retirés de tout texte affiché dans l'interface (titre, artiste, pseudo, motif) :
#   - commandes C0/C1 (dont \n et \r : injection d'en-tête HTTP, faux affichage sur plusieurs lignes) ;
#   - marques de formatage invisibles et surtout les surcharges bidirectionnelles U+202A..U+202E et
#     U+2066..U+2069, qui permettent de déguiser un nom de fichier ("innocent" + U+202E + "dim.exe") ;
#   - largeurs nulles U+200B..U+200F, U+2060..U+2064, U+FEFF (doublons visuels d'un titre existant) ;
#   - séparateurs de ligne et de paragraphe U+2028/U+2029.
_INVISIBLE = re.compile("[\u0000-\u001f\u007f-\u009f\u00ad\u061c\u180e"
                        "\u200b-\u200f\u202a-\u202e\u2060-\u2064"
                        "\u2066-\u206f\ufeff\ufff9-\ufffb]")
# Coupures de ligne et tabulations : remplacées par une espace (et non supprimées) pour ne pas
# souder deux mots, "copie\r\nillégale" devant rester "copie illégale".
_LINES = re.compile("[\t\n\v\f\r\u0085\u2028\u2029]")
_SPACES = re.compile("[ \u00a0\u1680\u2000-\u200a\u205f\u3000]+")


def clean_text(value: str | None, max_len: int = 120) -> str:
    """Texte sûr à stocker puis à afficher : NFC, sans caractère de contrôle ni de formatage invisible,
    espaces normalisés, longueur bornée. Renvoie "" si rien ne reste."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFC", str(value))
    s = _LINES.sub(" ", s)
    s = _INVISIBLE.sub("", s)
    s = _SPACES.sub(" ", s).strip()
    return s[:max_len].strip()


def _clean120(v: str | None) -> str | None:
    if v is None:
        return None
    return clean_text(v, 120) or None


def _clean500(v: str | None) -> str:
    return clean_text(v, 500)


def _clean24(v: str | None) -> str:
    return clean_text(v, 24)


def _clean32(v: str | None) -> str:
    return clean_text(v, 32)


def _clean200(v: str | None) -> str:
    return clean_text(v, 200)


class Lenient(BaseModel):
    """Les champs inconnus sont ignorés (compatibilité entre versions du client)."""
    model_config = ConfigDict(extra="ignore")


# --- REST ---------------------------------------------------------------------

class AuthStart(Lenient):
    verifier_hash: str = Field(pattern=SHA256_RE)
    # Port où l'appli écoute sur 127.0.0.1 : connexion sans code à recopier (voir auth.py). Absent : code à saisir.
    loopback_port: int | None = Field(default=None, ge=1024, le=65535)


class AuthPoll(Lenient):
    login_id: str = Field(min_length=1, max_length=64)
    verifier: str = Field(min_length=1, max_length=256)
    grant: str | None = Field(default=None, max_length=128)      # bon rapporté par le navigateur (retour local)


# --- Métadonnées de la bibliothèque (tags, licence, source) ----------------------------

# Liste blanche des tags d'un morceau (identifiants stables, traduits à l'affichage : `site.tags.<tag>`).
SONG_TAGS = ("piano", "flute", "lute", "violin", "harp", "percussion", "pop", "rock", "classique", "jeu-video",
             "anime", "film", "folk", "noel", "calme", "rapide", "facile", "difficile")
MAX_TAGS = 8
MAX_TAG_LEN = 24
LICENSES = ("own", "public_domain", "cc", "unknown")
MAX_SOURCE_URL_LEN = 500
MAX_SOURCE_NAME_LEN = 60
_URL_BAD_CHARS = re.compile(r"[\s\x00-\x1f\x7f<>\"'`\\]")


class MetaError(ValueError):
    """Métadonnée refusée : `code` stable pour le client, message en français."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_tag(value: str) -> str:
    """« Jeu vidéo » -> `jeu-video` : minuscules, sans accents, espaces et soulignés en tirets."""
    s = unicodedata.normalize("NFKD", clean_text(value, 200)).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[\s_]+", "-", s.strip())
    return re.sub(r"-{2,}", "-", s).strip("-")


def normalize_tags(value) -> list[str]:
    """Liste JSON, ou texte séparé par des virgules -> tags normalisés, dédoublonnés, dans l'ordre. MetaError si un
    tag est inconnu, trop long ou s'il y en a plus de MAX_TAGS."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            import json
            try:
                value = json.loads(text)
            except ValueError:
                raise MetaError("bad_tags", "Tags illisibles (liste JSON ou texte séparé par des virgules).")
        else:
            value = text.split(",")
    if not isinstance(value, (list, tuple)) or len(value) > 64:
        raise MetaError("bad_tags", "Tags illisibles (liste JSON ou texte séparé par des virgules).")
    out: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise MetaError("bad_tags", "Chaque tag est un texte.")
        tag = normalize_tag(raw)
        if not tag:
            continue
        if len(tag) > MAX_TAG_LEN or tag not in SONG_TAGS:
            raise MetaError("bad_tags", f"Tag inconnu : {tag[:MAX_TAG_LEN]!r} (autorisés : {', '.join(SONG_TAGS)}).")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise MetaError("bad_tags", f"Au plus {MAX_TAGS} tags.")
    return out


def normalize_license(value: str | None) -> str:
    v = (value or "").strip().lower() or "unknown"
    if v not in LICENSES:
        raise MetaError("bad_license", f"Licence inconnue (attendu : {', '.join(LICENSES)}).")
    return v


def normalize_source_url(value: str | None) -> str | None:
    """URL https absolue, sans espace, identifiants ni caractère de contrôle ; "" -> None."""
    from urllib.parse import urlsplit
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if len(v) > MAX_SOURCE_URL_LEN or _URL_BAD_CHARS.search(v):
        raise MetaError("bad_source_url", "Lien source invalide.")
    try:
        parts = urlsplit(v)
        host = parts.hostname
    except ValueError:
        raise MetaError("bad_source_url", "Lien source invalide.")
    if parts.scheme.lower() != "https":
        raise MetaError("bad_source_url", "Le lien source doit commencer par https://.")
    if not host or "@" in parts.netloc or "." not in host:
        raise MetaError("bad_source_url", "Lien source invalide.")
    return v


def normalize_source_name(value: str | None) -> str | None:
    return clean_text(value, MAX_SOURCE_NAME_LEN) or None


class SongPatch(Lenient):
    # max_length généreux à l'entrée : clean_text retire l'invisible puis coupe à 120.
    title: Annotated[str | None, Field(None, min_length=1, max_length=400), AfterValidator(_clean120)] = None
    artist: Annotated[str | None, Field(None, max_length=400), AfterValidator(_clean120)] = None
    # Métadonnées : absentes = inchangées ; "" (ou liste vide) = effacées. Validées par la route (codes d'erreur).
    tags: list[str] | str | None = Field(None)
    instrument: str | None = Field(None, max_length=64)
    source_url: str | None = Field(None, max_length=2000)
    source_name: str | None = Field(None, max_length=400)
    license: str | None = Field(None, max_length=32)


class ReportIn(Lenient):
    reason: Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(_clean500)]


class RejectIn(Lenient):
    reason: Annotated[str, Field("", max_length=2000), AfterValidator(_clean500)] = ""


class ResolveIn(Lenient):
    # remove_song / remove_drawing / remove_target : supprime la cible du signalement (quel que soit son type).
    action: Literal["dismiss", "remove_song", "remove_drawing", "remove_target"]


class ImportIn(Lenient):
    url: str = Field(min_length=1, max_length=2000)


class PublishIn(Lenient):
    notes: str = Field("", max_length=20000)
    mandatory: bool = False
    # Signature Ed25519 (base64) du `signed_payload` du manifeste ; `published_at` (ISO 8601) est alors l'horodatage
    # signé, qui devient celui de la publication. Sans signature, le serveur horodate lui-même.
    signature: str | None = Field(None, min_length=1, max_length=200)
    published_at: str | None = Field(None, min_length=1, max_length=40)


# --- WebSocket des salons (client -> serveur) ---------------------------------

class WsCreate(Lenient):
    token: str = Field(min_length=1, max_length=256)        # session Discord
    name: Annotated[str, Field("", max_length=200), AfterValidator(_clean24)] = ""
    instrument: Annotated[str, Field("piano", max_length=64), AfterValidator(_clean32)] = "piano"
    version: Annotated[str, Field("0", max_length=64), AfterValidator(_clean32)] = "0"
    max_players: int | None = None


class WsJoin(Lenient):
    token: str = Field(min_length=1, max_length=256)        # session Discord
    room_code: str = Field(min_length=1, max_length=16)
    name: Annotated[str, Field("", max_length=200), AfterValidator(_clean24)] = ""
    instrument: Annotated[str, Field("piano", max_length=64), AfterValidator(_clean32)] = "piano"
    version: Annotated[str, Field("0", max_length=64), AfterValidator(_clean32)] = "0"
    seat_token: str | None = Field(None, max_length=128)    # reprise d'un siège après coupure


class WsPing(Lenient):
    t0: float


def _clean60(v: str | None) -> str:
    return clean_text(v, 60)


class WsTrack(Lenient):
    """Résumé d'une piste du fichier MIDI (Orchestre : le chef répartit les pistes entre les sièges)."""
    index: int = Field(ge=0, le=255)
    name: Annotated[str, Field("", max_length=200), AfterValidator(_clean60)] = ""
    notes: int = Field(0, ge=0, le=1_000_000)
    low: int | None = Field(None, ge=0, le=127)
    high: int | None = Field(None, ge=0, le=127)
    mean: float | None = Field(None, ge=0, le=127)
    drums: bool = False


class WsSetSong(Lenient):
    sha256: str = Field(pattern=SHA256_RE)
    name: Annotated[str, Field("", max_length=400), AfterValidator(_clean200)] = ""
    duration_ms: int = Field(gt=0, le=3_600_000)
    key_shift: int = Field(0, ge=-36, le=36)
    source: Literal["library", "room"]
    online_id: int | None = None
    tracks: list[WsTrack] = Field(default_factory=list, max_length=64)


class WsPart(Lenient):
    tracks: list[Annotated[int, Field(ge=0, le=255)]] = Field(default_factory=list, max_length=64)
    octave: int | None = Field(None, ge=-2, le=2)     # None = octave choisie par le client pour son instrument


class WsSetParts(Lenient):
    """Orchestre : `parts` {id de siège (texte) : partie} ; enabled=False = tout le monde joue tout."""
    enabled: bool = False
    parts: dict[Annotated[str, Field(max_length=8)], WsPart] = Field(default_factory=dict, max_length=32)


class WsSongStatus(Lenient):
    sha256: str = Field(pattern=SHA256_RE)
    have: bool


class WsSetInstrument(Lenient):
    instrument: Annotated[str, Field(max_length=64), AfterValidator(_clean32)]


class WsReady(Lenient):
    ready: bool


class WsStart(Lenient):
    countdown_s: int | None = None
    force: bool = False


class WsPlayerState(Lenient):
    status: Literal["armed", "playing", "ended", "aborted", "no_song"]
    reason: Annotated[str | None, Field(None, max_length=400), AfterValidator(_clean200)] = None
    clock: dict | None = None


class WsKick(Lenient):
    player_id: int


class WsEmpty(Lenient):
    pass


WS_MODELS: dict[str, type[Lenient]] = {
    "create": WsCreate,
    "join": WsJoin,
    "leave": WsEmpty,
    "ping": WsPing,
    "set_song": WsSetSong,
    "song_status": WsSongStatus,
    "set_instrument": WsSetInstrument,
    "ready": WsReady,
    "start": WsStart,
    "cancel": WsEmpty,
    "stop": WsEmpty,
    "player_state": WsPlayerState,
    "kick": WsKick,
    "set_parts": WsSetParts,
}
