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


class AuthPoll(Lenient):
    login_id: str = Field(min_length=1, max_length=64)
    verifier: str = Field(min_length=1, max_length=256)


class SongPatch(Lenient):
    # max_length généreux à l'entrée : clean_text retire l'invisible puis coupe à 120.
    title: Annotated[str | None, Field(None, min_length=1, max_length=400), AfterValidator(_clean120)] = None
    artist: Annotated[str | None, Field(None, max_length=400), AfterValidator(_clean120)] = None


class ReportIn(Lenient):
    reason: Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(_clean500)]


class RejectIn(Lenient):
    reason: Annotated[str, Field("", max_length=2000), AfterValidator(_clean500)] = ""


class ResolveIn(Lenient):
    action: Literal["dismiss", "remove_song"]


class PublishIn(Lenient):
    notes: str = Field("", max_length=20000)
    mandatory: bool = False


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


class WsSetSong(Lenient):
    sha256: str = Field(pattern=SHA256_RE)
    name: Annotated[str, Field("", max_length=400), AfterValidator(_clean200)] = ""
    duration_ms: int = Field(gt=0, le=3_600_000)
    key_shift: int = Field(0, ge=-36, le=36)
    source: Literal["library", "room"]
    online_id: int | None = None


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
}
