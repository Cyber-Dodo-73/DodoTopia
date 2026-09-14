# Serveur DodoTopia

Backend de DodoTopia : mise à jour automatique de l'app, bibliothèque MIDI en ligne, connexion Discord et salons
synchronisés. FastAPI + uvicorn (un seul worker), **PostgreSQL** en production (SQLite en développement), déployé avec
**Dokploy** (type Compose) qui fournit Traefik et le certificat HTTPS. Le dépôt GitHub redéploie le serveur à chaque
push sur `main` et publie les versions de l'app (voir le README racine, « Publier une version »).

```
server/
  app/            main.py config.py db.py auth.py library.py releases.py rooms.py ratelimit.py schemas.py
  tests/          pytest (TestClient, Discord simulé, SQLite ou Postgres selon DATABASE_URL)
  Dockerfile  docker-compose.yml  .env.example  requirements.txt
```

Données persistantes : volume `dodo_data` (monté en `/data`) pour `songs/<sha256>.mid`, `tmp/<sha256>.mid`
(morceaux éphémères des salons, purgés après 2 h) et `releases/<version>/<fichier>` ; volume `pg_data` pour Postgres.

## 1. Prérequis

- Un VPS Linux avec **Dokploy** installé (`curl -sSL https://dokploy.com/install.sh | sh`), ports 80/443 ouverts.
- Un nom de domaine (ex. `dodo.example.org`) avec un enregistrement **A** (et AAAA si IPv6) vers l'IP du VPS.
- Le projet poussé sur **GitHub** (dossier `server/` à la racine du dépôt).

## 2. Application Discord

1. https://discord.com/developers/applications > **New Application**, nom « DodoTopia ».
2. Onglet **OAuth2** : note le **Client ID**, génère un **Client Secret**.
3. **Redirects** : ajoute exactement `https://dodotopia.cyber-dodo.fr/auth/discord/callback`.
4. Aucun bot n'est nécessaire, seul le scope `identify` est utilisé (nom, avatar, id).

Pour trouver ton ID Discord (administrateur) : Discord > Paramètres > Avancé > Mode développeur, puis clic droit
sur ton profil > **Copier l'identifiant**.

## 3. Déploiement avec Dokploy, pas à pas

1. **Projet** : Dokploy > *Projects* > *Create Project* (« DodoTopia »).
2. **Service Compose** : dans le projet, *Create Service* > **Compose**. Nom `dodo-server`.
3. **Source** : onglet *General* > *Provider* **GitHub** (connecte ton compte GitHub à Dokploy la première fois :
   *Settings* > *Git* > *GitHub* > installer l'app Dokploy sur le dépôt). Choisis le dépôt, la branche `main`, et
   **Compose Path** = `./server/docker-compose.yml`. *Compose Type* : `Docker Compose`.
4. **Variables** : onglet *Environment* : colle le contenu de `.env.example` en remplissant `PUBLIC_URL`,
   `POSTGRES_PASSWORD`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `ADMIN_DISCORD_IDS`, `PUBLISH_TOKEN`
   (`python -c "import secrets; print(secrets.token_urlsafe(32))"` pour les secrets). Dokploy écrit ce contenu dans
   le `.env` lu par le compose (`env_file: .env` et `${POSTGRES_PASSWORD}`). Laisse `DATABASE_URL` vide : le compose
   la construit (`postgresql://dodo:${POSTGRES_PASSWORD}@db:5432/dodo`).
5. **Domaine** : onglet *Domains* > *Add Domain* : host `dodo.example.org`, **Service Name** `api`,
   **Container Port** `8000`, *HTTPS* activé, certificat **Let's Encrypt**. Dokploy configure Traefik (routage +
   TLS + WebSocket `/ws`) ; le compose ne publie aucun port. Dokploy connecte lui-même les services au réseau
   `dokploy-network` ; si le domaine renvoie 502 après le déploiement, ajoute au service `api` :
   ```yaml
       networks: [default, dokploy-network]
   networks:
     dokploy-network:
       external: true
   ```
6. **Déployer** : bouton *Deploy*. Le premier build prend 1 à 2 minutes (image `python:3.12-slim`, Postgres 16).
   Le service `db` doit être *healthy* avant `api` (`depends_on` + `pg_isready`). Les migrations de la base
   s'appliquent au démarrage de l'API (table `schema_version`).
7. **Vérifier** : `curl https://dodotopia.cyber-dodo.fr/api/health` →
   `{"status":"ok","version":"1.0.0","min_client":"1.7.0","db":"ok","db_dialect":"postgres","rooms":0}`.
   La page `https://dodotopia.cyber-dodo.fr/` affiche la dernière version publiée et les liens de téléchargement.
8. **Auto-déploiement** : onglet *Deployments* > **Auto Deploy** activé. Avec le provider GitHub, Dokploy reçoit le
   webhook de push automatiquement (app GitHub) ; sinon copie l'URL *Webhook URL* affichée dans les paramètres du
   dépôt GitHub (*Settings* > *Webhooks* > *Add webhook*, content type `application/json`, événement *push*).
   Chaque push sur `main` qui touche le dépôt redéploie le serveur (rebuild de l'image `api`, `db` reste en place).
9. **Volumes** : les volumes nommés `dodo_data` et `pg_data` sont créés par compose et survivent aux redéploiements
   (`docker volume ls` sur le VPS : ils sont préfixés du nom du service Compose). Ne les supprime jamais depuis
   Dokploy (*Advanced* > *Volumes* n'est pas nécessaire ici).

**Traefik et gros téléversements.** Les installeurs (100–150 Mo) sont envoyés par GitHub Actions à
`PUT /api/admin/releases/…` (corps streamé). Traefik n'impose **aucune limite de taille** de corps par défaut (seul le
middleware `buffering`, non utilisé, en ajoute une), et uvicorn/FastAPI lisent le corps en streaming : les 413 sont
purement applicatifs (`MAX_MIDI_BYTES`, `ROOM_SONG_MAX_BYTES`). En revanche Traefik v3 (utilisé par Dokploy) applique
un `readTimeout` de **60 s** par défaut sur l'entrée : un envoi lent pourrait être coupé. Depuis les runners GitHub
(débit élevé) l'envoi dure quelques secondes ; si tu vois des erreurs de type `client disconnected` / 499 dans les
journaux pendant la publication, augmente les délais dans Dokploy > *Settings* > *Traefik* > `traefik.yml` :

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 600s
        writeTimeout: 600s
        idleTimeout: 180s
```

puis *Reload Traefik*. Les WebSockets des salons (`/ws`, ping toutes les 5 s) ne sont pas concernées par ces délais.

## 4. Mise à jour du serveur

Push sur `main` → workflow `server-tests.yml` (pytest SQLite + Postgres) et redéploiement Dokploy en parallèle.
Pour redéployer à la main : Dokploy > service > *Deploy*. Pour revenir en arrière : *Deployments* > *Redeploy*
sur un déploiement précédent, ou `git revert` + push.

## 5. Publier une version de DodoTopia

C'est le rôle de la CI (`.github/workflows/release.yml`, voir README racine) : au push d'un `version.py` modifié,
elle construit l'exe Windows, le zip portable et l'archive Linux, puis appelle `publish_release.py` avec les secrets
GitHub `PUBLISH_URL` (= `https://dodotopia.cyber-dodo.fr`) et `PUBLISH_TOKEN` (= celui du `.env` du serveur).

À la main depuis un PC Windows : `build.bat` (+ `build-linux.bat`) puis `publish.bat`, avec `publish.env` à la
racine du projet (`PUBLISH_URL=…`, `PUBLISH_TOKEN=…`, ignoré par git et Docker). Options de `publish_release.py` :
`--dry-run`, `--mandatory`, `--force` (republier une version existante), `--skip-linux`, `--notes "…"` /
`--notes-file CHANGELOG.md` (seule la section `## <version>` est envoyée).

Les clients interrogent `GET /api/releases/latest?current=<version>&platform=windows-setup|windows-portable|linux-x64`
et téléchargent `https://dodotopia.cyber-dodo.fr/dl/<version>/<fichier>` (servi par l'API : `FileResponse`, requêtes `Range`
acceptées pour la reprise, `Cache-Control: max-age=3600`).
Retirer une version : `curl -X DELETE -H "X-Publish-Token: …" https://dodotopia.cyber-dodo.fr/api/admin/releases/<version>`.

## 6. Modération de la bibliothèque

Tout utilisateur connecté peut déposer un `.mid` (≤ 2 Mo, type 0/1, 1 s à 30 min, ≥ 10 notes hors percussions,
10 dépôts/heure). Le morceau reste **en attente** (invisible) jusqu'à validation par un administrateur
(`ADMIN_DISCORD_IDS`), depuis l'onglet En ligne de DodoTopia ou en direct :

| Action | Requête (en-tête `Authorization: Bearer <token de session>`) |
|---|---|
| File d'attente | `GET /api/admin/songs?status=pending` |
| Valider / refuser | `POST /api/admin/songs/{id}/approve` · `POST /api/admin/songs/{id}/reject {"reason": "…"}` |
| Signalements ouverts | `GET /api/admin/reports?open=1` |
| Traiter un signalement | `POST /api/admin/reports/{id}/resolve {"action": "dismiss" \| "remove_song"}` |
| Bannir | `POST /api/admin/users/{id}/ban` (sessions révoquées, dépôts en attente refusés) |

Le token de session d'un admin se trouve dans `account.json` du dossier de données de DodoTopia.

## 7. Sauvegarde et restauration

Sur le VPS (les noms de conteneurs se trouvent avec `docker ps` ; `<compose>` est le nom donné par Dokploy) :

```bash
# base Postgres (cohérente même pendant l'utilisation)
docker exec <compose>-db-1 pg_dump -U dodo -Fc dodo > dodo-$(date +%F).dump
# fichiers (morceaux + binaires publiés)
docker run --rm -v <compose>_dodo_data:/data -v "$PWD":/out alpine tar czf /out/dodo-data-$(date +%F).tgz -C /data songs releases
```

Restauration : arrêter le service dans Dokploy (*Stop*), puis
`docker run --rm -i <image postgres> …` ou plus simplement, service relancé :
`cat dodo-<date>.dump | docker exec -i <compose>-db-1 pg_restore -U dodo -d dodo --clean --if-exists` et
`docker run --rm -v <compose>_dodo_data:/data -v "$PWD":/in alpine tar xzf /in/dodo-data-<date>.tgz -C /data`.
Une sauvegarde planifiée : Dokploy > service > *Backups* (destination S3) fonctionne pour les services Postgres
« natifs » ; pour un compose, une tâche `cron` sur le VPS avec les deux commandes ci-dessus suffit.

## 8. Journaux et dépannage

Dokploy > service > *Logs* (choisir `api` ou `db`), ou sur le VPS `docker logs -f <compose>-api-1`.

- `/api/health` renvoie 503 si la base est inaccessible (`db: error`).
- **Un seul worker uvicorn** est indispensable : les salons vivent en mémoire du processus. Ne pas ajouter
  `--workers` ni `deploy.replicas`.
- Le conteneur tourne sans privilèges (utilisateur `app`), le port 8000 n'est jamais publié : seul Traefik y accède.
  `--proxy-headers --forwarded-allow-ips=*` : l'IP réelle (limitation de débit) vient de `X-Forwarded-For`.
- Limites de débit (429 + `Retry-After`) : 10 `auth/start`/min/IP, 10 dépôts/h, 20 signalements/j, 10 salons créés/min/IP,
  20 messages WebSocket/s par connexion. `RATE_LIMIT=0` les désactive (tests uniquement).
- 502 sur le domaine : le service `api` n'est pas *healthy* (voir ses logs : mot de passe Postgres, migration) ou
  n'est pas sur `dokploy-network` (§3.5).

## 9. Développement local

```bash
cd server
python -m venv .venv && .venv/Scripts/activate     # Linux : source .venv/bin/activate
pip install -r requirements.txt
pytest                                             # SQLite temporaire, Discord simulé (le test Postgres est ignoré)
DATA_DIR=./data PUBLISH_TOKEN=dev uvicorn app.main:app --reload --port 8000   # PowerShell : $env:DATA_DIR="./data"; …
```

Sans `DATABASE_URL`, l'API utilise SQLite (`DATA_DIR/dodo.db`). Pour tester sur Postgres sans rien installer :

```bash
docker run -d --name dodo-pg -e POSTGRES_USER=dodo -e POSTGRES_PASSWORD=dodo -e POSTGRES_DB=dodo_test -p 55432:5432 postgres:16-alpine
DATABASE_URL=postgresql://dodo:dodo@localhost:55432/dodo_test pytest      # PowerShell : $env:DATABASE_URL="…"; pytest
```

Toute la suite tourne alors sur Postgres (tables recréées à chaque test). La CI (`server-tests.yml`) exécute les deux.
Compose local complet : ajoute `ports: ["8000:8000"]` au service `api` et un `.env` (avec `POSTGRES_PASSWORD`),
puis `docker compose up -d --build`. Variables utiles pour les essais de salons : `ROOM_GRACE_S`, `ROOM_EMPTY_TTL_S`,
`MIN_CLIENT_VERSION=0`.

Règles pour écrire une requête (`app/db.py`) : paramètres `?` (traduits en `%s` pour psycopg), lignes = dict,
`INSERT … RETURNING id`, booléens en 0/1, horodatages ISO texte, `LOWER(col) LIKE LOWER(?)`, `ON CONFLICT … DO UPDATE`.
Nouvelle migration = nouvelle entrée dans `db.MIGRATIONS` (placeholders `{ID}`, `{REAL}` pour les types qui diffèrent).

## 10. Référence rapide de l'API

- Auth : `POST /api/auth/start {verifier_hash}` → `{login_id, url, expires_in}` ; le navigateur suit `url` ;
  `POST /api/auth/poll {login_id, verifier}` → `{status: pending}` | `{status: ok, token, user}` (une seule fois, 410
  ensuite) | `{status: error, error}` ; `GET /api/me` ; `POST /api/auth/logout`.
- Bibliothèque : `GET /api/songs?q&page&per_page&sort=recent|popular|title`, `GET /api/songs/{id}`,
  `GET /api/songs/{id}/download` (`ETag` = sha256), `POST /api/songs` (multipart `file`, `title?`, `artist?`) →
  201 / 409 `{detail:{code:"duplicate", existing_id}}` / 413 / 422, `PATCH`/`DELETE /api/songs/{id}`,
  `POST /api/songs/{id}/report {reason}`.
- Versions : `GET /api/releases`, `/api/releases/{version}`, `/api/releases/latest?current&platform` →
  manifeste `{version, published_at, notes, mandatory, assets{platform:{url, filename, sha256, size}}, update_available, asset}` ;
  `GET /dl/{version}/{filename}` (Range OK) ; publication : `PUT /api/admin/releases/{v}/assets/{platform}`
  (en-têtes `X-Publish-Token`, `X-Sha256`, `X-Filename`), `POST /api/admin/releases/{v}/publish {notes, mandatory}`.
- Salons : WebSocket `wss://dodotopia.cyber-dodo.fr/ws` (protocole documenté en tête de `app/rooms.py`) ;
  `POST /api/rooms/{code}/song` (chef, multipart ≤ 512 Ko) ; `GET /api/rooms/{code}/song/{sha256}` (membres).
- Erreurs : `{"detail": {"code": "...", "message": "..."}}` (les erreurs de validation FastAPI gardent leur format).
