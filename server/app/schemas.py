"""Modèles pydantic des corps de requête et des messages WebSocket."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SHA256_RE = r"^[0-9a-f]{64}$"


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
    title: str | None = Field(None, min_length=1, max_length=120)
    artist: str | None = Field(None, max_length=120)


class ReportIn(Lenient):
    reason: str = Field(min_length=1, max_length=500)


class RejectIn(Lenient):
    reason: str = Field("", max_length=500)


class ResolveIn(Lenient):
    action: Literal["dismiss", "remove_song"]


class PublishIn(Lenient):
    notes: str = Field("", max_length=20000)
    mandatory: bool = False


# --- WebSocket des salons (client -> serveur) ---------------------------------

class WsCreate(Lenient):
    token: str = Field(min_length=1, max_length=256)        # session Discord
    name: str = Field("", max_length=24)
    instrument: str = Field("piano", max_length=32)
    version: str = Field("0", max_length=32)
    max_players: int | None = None


class WsJoin(Lenient):
    token: str = Field(min_length=1, max_length=256)        # session Discord
    room_code: str = Field(min_length=1, max_length=16)
    name: str = Field("", max_length=24)
    instrument: str = Field("piano", max_length=32)
    version: str = Field("0", max_length=32)
    seat_token: str | None = Field(None, max_length=128)    # reprise d'un siège après coupure


class WsPing(Lenient):
    t0: float


class WsSetSong(Lenient):
    sha256: str = Field(pattern=SHA256_RE)
    name: str = Field("", max_length=200)
    duration_ms: int = Field(gt=0, le=3_600_000)
    key_shift: int = Field(0, ge=-36, le=36)
    source: Literal["library", "room"]
    online_id: int | None = None


class WsSongStatus(Lenient):
    sha256: str = Field(pattern=SHA256_RE)
    have: bool


class WsSetInstrument(Lenient):
    instrument: str = Field(max_length=32)


class WsReady(Lenient):
    ready: bool


class WsStart(Lenient):
    countdown_s: int | None = None
    force: bool = False


class WsPlayerState(Lenient):
    status: Literal["armed", "playing", "ended", "aborted", "no_song"]
    reason: str | None = Field(None, max_length=200)
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
