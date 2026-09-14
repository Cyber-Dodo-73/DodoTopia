"""Réglages du serveur, lus depuis l'environnement (ou un fichier .env)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PUBLIC_URL: str = "http://localhost:8000"          # base des liens (auth, /dl/...), sans / final
    DATABASE_URL: str = ""                              # vide = SQLite DATA_DIR/dodo.db ; postgresql://user:pw@host/db
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""
    ADMIN_DISCORD_IDS: str = ""                         # IDs Discord séparés par des virgules
    PUBLISH_TOKEN: str = ""                             # jeton de publish_release.py (vide = publication désactivée)
    DATA_DIR: str = "/data"                             # volume : songs/, tmp/, releases/ (+ dodo.db en SQLite)
    MAX_MIDI_BYTES: int = 2 * 1024 * 1024               # bibliothèque
    ROOM_SONG_MAX_BYTES: int = 512 * 1024               # morceau éphémère d'un salon
    # Plafonds de validation d'un fichier MIDI (voir library.scan_midi). Un fichier hostile de 2 Mo en
    # running status contient des centaines de milliers d'évènements : sans plafond, le parsing fige le
    # serveur comme le client.
    MAX_MIDI_TRACKS: int = 64                           # SMF type 1 réaliste : < 32 pistes
    MAX_MIDI_EVENTS: int = 100_000                      # gros morceau orchestral : 30 000 à 60 000
    MAX_MIDI_NOTES: int = 50_000                        # 30 min de piano dense : ~20 000 notes
    MIN_MIDI_NOTES: int = 10
    MIN_MIDI_DURATION_S: float = 1.0
    MAX_MIDI_DURATION_S: float = 30 * 60
    MAX_TEXT_LEN: int = 120                             # titre, artiste, pseudo affichés dans l'interface
    MAX_REASON_LEN: int = 500                           # motif de signalement / de refus
    REQUEST_OVERHEAD_BYTES: int = 64 * 1024             # en-têtes multipart autour du fichier
    RATE_LIMIT: int = 1                                 # 0 = limitation désactivée (tests)
    SESSION_DAYS: int = 90
    LOGIN_TICKET_S: int = 600
    MIN_CLIENT_VERSION: str = "1.7.0"                   # en dessous : salons refusés (version_too_old)
    ROOM_GRACE_S: float = 60                            # siège gardé après perte de la WebSocket
    ROOM_EMPTY_TTL_S: float = 120                       # salon vide supprimé après ce délai
    ROOM_MAX_PLAYERS: int = 8
    ROOM_IDLE_S: float = 20                             # connexion muette fermée (le client ping toutes les 5 s)
    TMP_SONG_TTL_S: float = 2 * 3600

    @property
    def public_url(self) -> str:
        return self.PUBLIC_URL.rstrip("/")

    @property
    def admin_ids(self) -> set[str]:
        return {x.strip() for x in self.ADMIN_DISCORD_IDS.split(",") if x.strip()}

    @property
    def data_dir(self) -> Path:
        return Path(self.DATA_DIR)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "dodo.db"

    @property
    def songs_dir(self) -> Path:
        return self.data_dir / "songs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def releases_dir(self) -> Path:
        return self.data_dir / "releases"

    @property
    def max_request_bytes(self) -> int:
        """Taille maximale du corps d'une requête ordinaire (les envois de binaires de release sont exemptés)."""
        return max(self.MAX_MIDI_BYTES, self.ROOM_SONG_MAX_BYTES) + self.REQUEST_OVERHEAD_BYTES
