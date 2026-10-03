"""Réglages du serveur, lus depuis l'environnement (ou un fichier .env)."""
from __future__ import annotations

import re
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
    # Clé publique Ed25519 (32 octets, base64) qui signe les manifestes de mise à jour. Définie : toute
    # publication doit porter une signature valide du `signed_payload`. Vide : signature facultative, non vérifiée.
    RELEASE_SIGNING_PUBLIC_KEY: str = ""
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
    ADMIN_SESSION_DAYS: int = 7                         # session web de l'espace admin (cookie), glissante
    SESSION_TOUCH_S: int = 3600                         # last_used_at / expires_at réécrits au plus une fois par heure
    LOGIN_TICKET_S: int = 600
    LOGIN_CODE_ATTEMPTS: int = 5                        # essais du code affiché dans l'app avant mise en erreur du ticket
    MIN_CLIENT_VERSION: str = "1.7.0"                   # en dessous : salons refusés (version_too_old)
    ROOM_GRACE_S: float = 60                            # siège gardé après perte de la WebSocket
    ROOM_EMPTY_TTL_S: float = 120                       # salon vide supprimé après ce délai
    ROOM_MAX_PLAYERS: int = 8
    ROOM_IDLE_S: float = 20                             # connexion muette fermée (le client ping toutes les 5 s)
    TMP_SONG_TTL_S: float = 2 * 3600
    # --- Site public ---
    COMMUNITY_DISCORD_URL: str = ""                     # lien d'invitation Discord (vide = section masquée)
    PLAUSIBLE_SCRIPT_URL: str = ""                      # ex. https://plausible.io/js/script.js (vide = pas de mesure)
    SITE_VERIFICATION_GOOGLE: str = ""                  # contenu de la balise google-site-verification
    SITE_VERIFICATION_BING: str = ""                    # contenu de la balise msvalidate.01
    SITE_PAGE_TTL_S: float = 300                        # cache mémoire des pages HTML rendues
    SONG_INDEX_MIN_NOTES: int = 50                      # fiche publique d'un morceau plus courte : `noindex`
    # Clé IndexNow (8 à 128 caractères parmi a-z, A-Z, 0-9 et -) : servie sur /<clé>.txt, et les URL nouvelles ou
    # modifiées (version publiée, morceau ou dessin approuvé) sont signalées à Bing, Yandex… Vide = désactivé.
    INDEXNOW_KEY: str = ""
    # --- Annonces ---
    DISCORD_ANNOUNCE_WEBHOOK: str = ""                  # webhook Discord (https) : annonce de chaque version publiée
    # Webhook des notifications d'administration (nouveaux comptes, modération, signalements, erreurs, résumé du
    # jour). Valeur par défaut : l'URL enregistrée depuis l'espace admin du site (/admin, Réglages) a priorité.
    DISCORD_ADMIN_WEBHOOK: str = ""
    # --- Import par lien (BitMidi, URL .mid) ---
    IMPORT_TIMEOUT_S: float = 10                        # par requête sortante
    IMPORT_MAX_REDIRECTS: int = 2
    IMPORT_CACHE_DAYS: float = 7                        # cache disque DATA_DIR/import_cache
    IMPORT_TOKEN_TTL_S: float = 600                     # jeton de récupération du fichier importé (usage unique)
    IMPORT_DIRECT_HOSTS: str = ""                       # URL .mid directes : hôtes autorisés (virgules) ; vide = tout hôte public
    # --- Galerie de dessins ---
    MAX_DRAWING_PNG_BYTES: int = 512 * 1024
    MAX_DRAWING_CELLS_BYTES: int = 200 * 1024
    MAX_DRAWING_PX: int = 1024                          # largeur et hauteur maximales du PNG
    DRAWING_THUMB_PX: int = 400
    MAX_DRAWING_TITLE_LEN: int = 60
    # --- Rapports de diagnostic (bouton « Envoyer un rapport » de l'app) ---
    MAX_DIAG_REPORT_BYTES: int = 8 * 1024 * 1024
    DIAG_REPORT_TTL_DAYS: float = 30

    @property
    def public_url(self) -> str:
        return self.PUBLIC_URL.rstrip("/")

    @property
    def indexnow_key(self) -> str:
        """Clé IndexNow si elle est bien formée, sinon "" (IndexNow désactivé)."""
        key = self.INDEXNOW_KEY.strip()
        return key if re.fullmatch(r"[A-Za-z0-9-]{8,128}", key) else ""

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def admin_cookie(self) -> str:
        """`__Host-` (Secure, Path=/, sans Domain) en HTTPS ; nom simple en développement HTTP."""
        return "__Host-dodo_admin" if self.secure_cookies else "dodo_admin"

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
    def drawings_dir(self) -> Path:
        return self.data_dir / "drawings"

    @property
    def diag_reports_dir(self) -> Path:
        return self.data_dir / "diag_reports"

    @property
    def import_cache_dir(self) -> Path:
        return self.data_dir / "import_cache"

    @property
    def og_cache_dir(self) -> Path:
        return self.data_dir / "og_cache"

    @property
    def direct_import_hosts(self) -> set[str]:
        return {x.strip().lower() for x in self.IMPORT_DIRECT_HOSTS.split(",") if x.strip()}

    @property
    def max_request_bytes(self) -> int:
        """Taille maximale du corps d'une requête ordinaire (les envois de binaires de release sont exemptés)."""
        return (max(self.MAX_MIDI_BYTES, self.ROOM_SONG_MAX_BYTES,
                    self.MAX_DRAWING_PNG_BYTES + self.MAX_DRAWING_CELLS_BYTES) + self.REQUEST_OVERHEAD_BYTES)
