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
   `POSTGRES_PASSWORD`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `ADMIN_DISCORD_IDS`, `PUBLISH_TOKEN`,
   et de préférence `RELEASE_SIGNING_PUBLIC_KEY` (manifestes signés, §5) ; `FORWARDED_ALLOW_IPS` seulement si
   Traefik n'est pas sur un réseau Docker (§8)
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
acceptées pour la reprise, `Cache-Control: max-age=3600`). Chaque asset compte ses téléchargements (`downloads` dans le
manifeste ; une requête entière ou `Range: bytes=0-` compte, une reprise partielle non) ; `GET /api/stats` publie les
totaux (cache 60 s).
Retirer une version : `curl -X DELETE -H "X-Publish-Token: …" https://dodotopia.cyber-dodo.fr/api/admin/releases/<version>`.

**Appli Android : un canal à part** (`app/mobile_releases.py`, table `mobile_releases`). Numérotation propre, un seul
fichier par version (l'APK), aucun manifeste signé : rien de ce canal n'apparaît dans `/api/releases/*`, donc rien ne
change pour l'Updater PC. Publication : `py publish_mobile.py` (même `publish.env` ; version par défaut = `versionName`
de `mobile/app/build.gradle.kts`, fichier par défaut `mobile/dist/DodoTopia-Mobile-<version>.apk` ; `--dry-run`,
`--force`, `--notes`, `--notes-file`). Le script fait `PUT /api/admin/mobile/releases/{v}/apk` (corps brut, en-têtes
`X-Publish-Token`, `X-Sha256`, `X-Filename` en `.apk`) puis `POST /api/admin/mobile/releases/{v}/publish {notes}`.
L'appli interroge `GET /api/mobile/latest?current=<version>` (404 `no_release` tant que rien n'est publié) et l'APK est
servi par `GET /dl/android/<version>/<fichier>` (`application/vnd.android.package-archive`, `Range`, compteur
`downloads`) ; le site passe par `/telecharger/go/android`. Fichiers dans `releases/android/<version>/`. Retirer une
version : `DELETE /api/admin/mobile/releases/<version>`. Les téléchargements Android sont comptés dans les statistiques
de l'admin (plateforme `android`) mais pas dans `downloads_total` de `GET /api/stats`.

**Manifeste signé (Ed25519).** Le manifeste expose `signed_payload` (JSON canonique, `sort_keys`, sans espace, de
`{version, assets{platform:{sha256, size, filename}}, mandatory, published_at}`) et `signature` (base64, 64 octets).
`publish_release.py` construit ce même texte à partir des assets déposés, de `mandatory` et d'un `published_at` qu'il
choisit, le signe avec la clé privée (secret GitHub), puis envoie `{notes, mandatory, published_at, signature}` à
`POST /api/admin/releases/{v}/publish`. Si `RELEASE_SIGNING_PUBLIC_KEY` est renseignée dans le `.env`, le serveur
vérifie la signature et refuse toute publication non signée (422 `signature_required`) ou mal signée
(400 `bad_signature`) ; sans clé, la signature est facultative et stockée telle quelle. Le client vérifie
`signature` contre `signed_payload` avec la clé publique embarquée (`RELEASE_SIGNING_PUBLIC_KEY` dans `online.py`),
puis compare `signed_payload` au manifeste reçu ; toute divergence → aucune mise à jour proposée.
Génération de la paire : `py publish_release.py --gen-key` (ou voir `.env.example`). La clé privée (base64) va dans
le secret GitHub `RELEASE_SIGNING_KEY` (ou `RELEASE_SIGNING_KEY=` dans `publish.env` pour une publication à la main,
avec `pip install pynacl`) ; la clé publique va à la fois dans le `.env` du serveur et dans `online.py`. Sans secret,
la CI publie sans signature et l'indique en avertissement.

## 6. Modération de la bibliothèque

Tout utilisateur connecté peut déposer un `.mid` (≤ 2 Mo, type 0/1, 1 s à 30 min, ≥ 10 notes hors percussions,
10 dépôts/heure). Le morceau reste **en attente** (invisible) jusqu'à validation par un administrateur
(`ADMIN_DISCORD_IDS`), depuis l'onglet En ligne de DodoTopia ou en direct :

| Action | Requête (en-tête `Authorization: Bearer <token de session>`) |
|---|---|
| File d'attente | `GET /api/admin/songs?status=pending` |
| Valider / refuser | `POST /api/admin/songs/{id}/approve` · `POST /api/admin/songs/{id}/reject {"reason": "…"}` |
| Dessins en attente | `GET /api/admin/drawings?status=pending` · `POST /api/admin/drawings/{id}/approve` · `…/reject {"reason": "…"}` |
| Signalements ouverts | `GET /api/admin/reports?open=1&target_type=song\|drawing` (chaque ligne : `target_type`, `target_id`, `target_title`, `target_status`) |
| Traiter un signalement | `POST /api/admin/reports/{id}/resolve {"action": "dismiss" \| "remove_song" \| "remove_drawing" \| "remove_target"}` (tout `remove_*` supprime la cible) |
| Bannir | `POST /api/admin/users/{id}/ban` (sessions révoquées, morceaux et dessins en attente refusés) |

Le token de session d'un admin se trouve dans `account.json` du dossier de données de DodoTopia.

### Espace admin du site (`/admin`)

**https://dodotopia.cyber-dodo.fr/admin** : connexion par Discord directement dans le navigateur (bouton « Se
connecter avec Discord »), réservée aux comptes de `ADMIN_DISCORD_IDS`. Même application Discord et même URL de
redirection (`/auth/discord/callback`) que l'app : rien à changer dans le portail développeur Discord. Session web
dans un cookie `HttpOnly` (`__Host-dodo_admin` en HTTPS, `SameSite=Lax`, 7 jours glissants, `ADMIN_SESSION_DAYS`) ;
toute écriture exige en plus l'en-tête `X-Dodo-Admin: 1` (pas de CSRF). Les routes `/api/admin/*` acceptent aussi le
Bearer d'un admin (app).

Sections : tableau de bord ; audience du site (visiteurs, pages vues, pages, référents, langues, appareils,
navigateurs, systèmes, robots, carte heure × jour) ; app et téléchargements (installations actives par jour et par
version/système, téléchargements par plateforme, version et origine) ; communauté (comptes, dépôts, likes, tops,
contributeurs, instruments, étiquettes, licences, durées, délais et taux de modération) ; salons et serveur en direct
(salons, joueurs, courbe des 24 h, temps de réponse p50/p95/p99, erreurs 5xx, stockage, sessions) ; modération des
morceaux et dessins ; signalements ; comptes (recherche, fiche, bannir/débannir, déconnecter partout) ; versions ;
journal des actions admin ; réglages du webhook. Export CSV : `GET /api/admin/stats.csv?days=90`.

**Statistiques** (`app/stats.py`) : collectées en mémoire par un middleware et par le code métier, écrites en base
chaque minute (`stat_daily`, une ligne par jour × clé × dimension), jamais de cookie côté visiteur. Visiteur unique =
sha256(sel aléatoire du jour + IP + User-Agent), le sel et les empreintes sont effacés le lendemain (seul le compte
reste) : aucune donnée personnelle conservée, cohérent avec l'article des CGU sur la mesure d'audience. Le client
DodoTopia est reconnu à son User-Agent `DodoTopia/<version> (<système>)`. Les stats démarrent au déploiement : il n'y
a pas d'historique avant (sauf ce qui se déduit des tables : comptes, dépôts, likes, signalements).

**Notifications Discord** (`app/notify.py`) : webhook réglé depuis `/admin` → Réglages (ou `DISCORD_ADMIN_WEBHOOK`
par défaut) ; évènements au choix : nouveau compte, morceau/dessin à valider, signalement, version publiée, erreur 5xx
(une alerte par chemin toutes les 10 min), résumé quotidien à 9 h (heure de Paris), partie lancée, action d'un admin,
connexion à l'espace admin ; mention facultative d'un rôle sur ce qui demande une action. Envoi par un thread dédié
(respect des 429 de Discord), jamais bloquant pour une requête. Distinct de `DISCORD_ANNOUNCE_WEBHOOK` (annonces
publiques des versions).

Suppression d'un compte par son titulaire : `DELETE /api/me` (sessions, tickets et signalements effacés ; morceaux
en attente ou refusés supprimés avec leurs fichiers ; morceaux approuvés conservés mais anonymisés, `uploader_id`
NULL et « Compte supprimé » comme déposant ; mêmes règles pour les dessins ; « J'aime » du compte retirés et
compteurs recalculés ; puis la ligne `users`).

**Galerie de dessins.** `POST /api/drawings` (multipart `png` ≤ 512 Ko, `title` ≤ 60, `cells` JSON facultatif
≤ 200 Ko, 5 dépôts/heure) : signature et dimensions (≤ 1024×1024) lues dans l'en-tête, décodage complet par Pillow
(PNG tronqué, animé ou bombe de décompression refusés), puis **ré-encodage** depuis les pixels seuls (aucune
métadonnée ni donnée après `IEND` ne survit) et vignette de 400 px. Fichiers dans `DATA_DIR/drawings/<sha256>.png`
(+ `.thumb.png`). Même cycle que les morceaux : en attente, puis validé ou refusé par un administrateur.

**Import par lien.** `POST /api/import {url}` récupère un MIDI sur Online Sequencer, BitMidi ou une URL https en
`.mid` (anti-SSRF : https et port 443 seulement, hôtes sur liste blanche pour les deux sites et, si
`IMPORT_DIRECT_HOSTS` est renseigné, pour les liens directs ; résolution DNS et refus de toute adresse non publique à
chaque redirection, 2 au plus ; 10 s ; `MAX_MIDI_BYTES`). Le fichier est validé comme un dépôt, gardé 7 jours dans
`DATA_DIR/import_cache/`, puis rendu une seule fois par `GET /api/import/{token}` (10 min). **Rien n'est publié dans
la bibliothèque** : le joueur dépose ensuite le fichier s'il le souhaite.

**Annonces.** Avec `DISCORD_ANNOUNCE_WEBHOOK` (URL https d'un webhook de salon Discord), chaque publication de
version envoie, après la réponse, un embed « DodoTopia x.y.z » (notes tronquées à 1 500 caractères, lien
`/fr/telecharger`). `releases.announced_at` garantit une seule annonce par version (remis à vide si Discord refuse,
pour réessayer à la publication suivante). X et Bluesky sont annoncés par la CI (`.tools/post_social.py`, dernier
step de `release.yml`, secrets GitHub `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`,
`BSKY_HANDLE`, `BSKY_APP_PASSWORD` ; chaque réseau est ignoré si ses secrets manquent ; `--dry-run` pour relire).

**Présentation dans les résultats.** Le nom du site vient du nœud JSON-LD `WebSite` (`name` DodoTopia, `url` = la
racine `PUBLIC_URL/`), servi identique sur toutes les pages : la racine redirige (302, `Vary: Accept-Language`) vers
un accueil traduit, et Google lit le nom sur la page d'accueil du sous-domaine après redirection. L'éditeur est un
nœud `Organization` séparé (Cyber-Dodo), référencé par `publisher` et par l'auteur de `SoftwareApplication`. Les
icônes (`/favicon.ico` 16-48 px, `/static/favicon-96.png`, `/static/favicon-192.png`, `/static/apple-touch-icon.png`)
sont générées depuis `logo.png` par `.tools/make_favicons.py` et déclarées avec leurs vraies dimensions, à des URL
stables sans empreinte. Les pages indexables portent `max-image-preview:large`. Après un changement de ces
éléments, redemander l'exploration de la racine et des accueils traduits dans Search Console : Google décide seul du
nom, du titre, de l'extrait et de la vignette affichés, et ne les met pas à jour tout de suite.

**Moteurs de recherche.** `/sitemap.xml` est un index : il liste `/sitemap-pages.xml` et, seulement s'ils ont au
moins une URL, `/sitemap-songs.xml` (morceaux approuvés d'au moins `SONG_INDEX_MIN_NOTES` notes) et
`/sitemap-gallery.xml` (dessins approuvés), chacun avec son `<lastmod>` ; un sitemap vide listé dans l'index est
signalé en erreur par Google et Bing. Tout le site (pages, `robots.txt`, sitemaps, redirections) et `/api/health`
répondent à `HEAD` comme à `GET`, sans corps ; le reste de l'API garde ses méthodes. Les fichiers (`/dl/…`, morceaux,
dessins, import) ne sont jamais compressés en gzip : ils gardent `Content-Length` et `Accept-Ranges` (progression,
reprise, et pas de `.tar.gz` doublement compressé). **IndexNow** : avec `INDEXNOW_KEY` (8 à 128 caractères parmi
a-z, A-Z, 0-9 et `-` ; `python -c "import secrets; print(secrets.token_hex(16))"`), la clé est servie sur
`<PUBLIC_URL>/<clé>.txt` et un `POST https://api.indexnow.org/indexnow` part en tâche de fond à chaque version
publiée (accueil, téléchargement et nouveautés, toutes langues) et à chaque morceau ou dessin approuvé (sa fiche,
toutes langues). Un échec est journalisé (`dodo.indexnow`) et n'affecte jamais la requête. Vide = désactivé.

## 7. Sauvegarde et restauration

Sur le VPS (les noms de conteneurs se trouvent avec `docker ps` ; `<compose>` est le nom donné par Dokploy) :

```bash
# base Postgres (cohérente même pendant l'utilisation)
docker exec <compose>-db-1 pg_dump -U dodo -Fc dodo > dodo-$(date +%F).dump
# fichiers (morceaux, dessins, binaires publiés ; import_cache et og_cache se régénèrent)
docker run --rm -v <compose>_dodo_data:/data -v "$PWD":/out alpine tar czf /out/dodo-data-$(date +%F).tgz -C /data songs drawings releases
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
  `--proxy-headers` : l'IP réelle (limitation de débit) vient de `X-Forwarded-For`, mais seulement quand la requête
  arrive d'un proxy listé dans **`FORWARDED_ALLOW_IPS`** (défaut `172.16.0.0/12`, les réseaux Docker où vit Traefik).
  Si Traefik tourne ailleurs (autre réseau, autre hôte), mets son adresse ou son réseau dans cette variable ;
  `*` ferait confiance à n'importe quel client, qui forgerait alors son IP.
- Limites de débit (429 + `Retry-After`, par IP sauf mention) : 10 `auth/start`/min, 60 `auth/poll`/min,
  20 confirmations de code/min, 3 suppressions de compte/h, 10 dépôts/h (par compte), 20 signalements/j (par compte),
  60 téléchargements de morceau/min, 30 `releases/latest`/min, 10 `/dl/*`/min, 20 ouvertures de WebSocket/min,
  10 salons créés/min, 20 `join`/min, 20 messages WebSocket/s par connexion. `RATE_LIMIT=0` les désactive (tests).
- WebSocket : le premier message (`create`/`join`) doit arriver sous 10 s, sinon fermeture 1008 ; messages
  limités à 64 Ko par uvicorn (`--ws-max-size`) et à 16 Ko par l'application.
- Réponses HTTP : `Strict-Transport-Security`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff` sur tout (pas encore de CSP).
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
Nouvelle migration = nouvelle entrée dans `db.MIGRATIONS` (placeholders `{ID}`, `{REAL}` pour les types qui diffèrent ;
un dict `{"sqlite": …, "postgres": …}` quand les deux dialectes divergent). Sous Postgres, `db.POSTGRES_OPTIONAL`
tente au démarrage `CREATE EXTENSION pg_trgm` et deux index GIN trigrammes (recherche `LIKE '%mot%'` sur titre et
artiste) ; un échec est journalisé et ignoré.

## 10. Référence rapide de l'API

- Auth : `POST /api/auth/start {verifier_hash}` → `{login_id, url, expires_in, user_code}` ; l'app affiche
  `user_code` (5 caractères) et ouvre `url` ; la page demande de recopier le code (5 essais, formulaire
  `POST /auth/discord/confirm`), puis redirige vers Discord ; `POST /api/auth/poll {login_id, verifier}` →
  `{status: pending}` | `{status: ok, token, user}` (session créée à cet instant, livrée une seule fois, 410 ensuite) |
  `{status: error, error}` (`denied`, `discord`, `banned`, `code` = trop d'essais, `expired`) ; `GET /api/me` ;
  `DELETE /api/me` ; `POST /api/auth/logout`.
- Bibliothèque : `GET /api/songs?q&tag&instrument&page&per_page&sort=recent|trending|popular|likes|title`
  (`trending` = (téléchargements + 3 × likes) / (âge en heures + 2)^1,5, calculé sur les 500 plus récents),
  `GET /api/songs/{id}` (champs `tags`, `instrument`, `source_url`, `source_name`, `license`, `likes`, `updated_at`,
  et `liked_by_me` si session), `GET /api/songs/{id}/download` (`ETag` = sha256), `POST /api/songs` (multipart `file`,
  `title?`, `artist?`, `tags?` (JSON ou virgules, ≤ 8 parmi `schemas.SONG_TAGS`), `instrument?`, `source_url?`
  (https), `source_name?`, `license?` = `own|public_domain|cc|unknown`) → 201 / 409
  `{detail:{code:"duplicate", existing_id}}` / 413 / 422 (`bad_tags`, `bad_instrument`, `bad_source_url`,
  `bad_license`, `invalid_midi`), `PATCH`/`DELETE /api/songs/{id}`, `POST`/`DELETE /api/songs/{id}/like`
  (idempotent, 60/min) → `{ok, id, liked, likes}`, `POST /api/songs/{id}/report {reason}`.
- Import : `POST /api/import {url}` (session, 10/min) → `{ok, filename, size, sha256, source_url, source_name,
  source_author, download_token, download_url, expires_in}` ; `GET /api/import/{token}` → fichier, une fois.
- Galerie : `GET /api/drawings?page&per_page&sort=recent|popular`, `GET /api/drawings/{id}`,
  `GET /api/drawings/{id}.png`, `GET /api/drawings/{id}/thumb.png`, `GET /api/drawings/{id}/cells` →
  `{format, w, h, cells}`, `POST /api/drawings` (multipart `png`, `title?`, `cells?`),
  `POST`/`DELETE /api/drawings/{id}/like`, `DELETE /api/drawings/{id}` (auteur ou admin),
  `POST /api/drawings/{id}/report {reason}`.
- Site public : `/{lang}/morceaux` (`songs`, `canciones`, `lieder`, `musicas`) et la fiche
  `/{lang}/morceaux/{id}-{slug}` (301 si le slug est faux, `noindex` sous `SONG_INDEX_MIN_NOTES` notes, image
  `/og/song/{id}.png` en cache disque `DATA_DIR/og_cache`), `/{lang}/galerie[/{id}]`, `/{lang}/salon/{CODE}`
  (`noindex`, ouvre `dodotopia://room/{CODE}`), `/sitemap-songs.xml`, `/sitemap-gallery.xml`. Liens profonds :
  `dodotopia://song/{id}`, `dodotopia://drawing/{id}`, `dodotopia://room/{code}`.
- Versions : `GET /api/releases`, `/api/releases/{version}`, `/api/releases/latest?current&platform` →
  manifeste `{version, published_at, notes, mandatory, assets{platform:{url, filename, sha256, size, downloads}},
  signature, signed_payload, update_available, asset}` ; `GET /dl/{version}/{filename}` (Range OK) ;
  `GET /api/stats` → `{downloads_total, songs_approved, users, rooms_open}` ; publication :
  `PUT /api/admin/releases/{v}/assets/{platform}` (en-têtes `X-Publish-Token`, `X-Sha256`, `X-Filename`),
  `POST /api/admin/releases/{v}/publish {notes, mandatory, published_at?, signature?}`.
- Salons : WebSocket `wss://dodotopia.cyber-dodo.fr/ws` (protocole documenté en tête de `app/rooms.py`) ;
  `POST /api/rooms/{code}/song` (chef, multipart ≤ 512 Ko) ; `GET /api/rooms/{code}/song/{sha256}` (membres) ;
  `GET /api/rooms/{code}/exists` → `{code, exists, full}` (sans compte, 30/min par IP).
- Erreurs : `{"detail": {"code": "...", "message": "..."}}` (les erreurs de validation FastAPI gardent leur format).
