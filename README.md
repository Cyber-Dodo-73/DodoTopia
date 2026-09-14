# DodoTopia

Boîte à outils pour Heartopia, en trois onglets :

- **Musique** : joue tes fichiers `.mid` dans le jeu en simulant les touches du clavier de l'instrument, avec écoute dans le logiciel avant.
- **Image** : importe une image, DodoTopia la transforme en dessin case par case sur la palette du jeu, puis la peint à ta place dans l'outil de dessin d'Heartopia.
- **Cuisine** : refait en boucle la dernière recette cuisinée sur ta cuisinière, ajuste le feu à temps et récupère les plats.

## Installer

- **`release\DodoTopia-x.y.z-Setup.exe`** : installeur classique (raccourci bureau, désinstallation). Pour mettre à jour, lance simplement le nouvel installeur : il écrase l'ancienne version. Tes musiques et réglages sont conservés dans `%APPDATA%\DodoTopia`.
- **`release\DodoTopia-x.y.z-portable.zip`** : version sans installation. Dézippe et lance `DodoTopia.exe`. Pour mettre à jour, dézippe la nouvelle version par-dessus.

Sans exe, depuis les sources : double-clique sur `DodoTopia.bat` (Python 3 requis, voir Dépendances).

## Utiliser

1. Importe tes `.mid` (bouton **Importer** ou glisser-déposer dans la fenêtre).
2. Choisis l'instrument en haut : Piano, Flûte ou Luth.
3. **▶ Écouter** joue la musique dans le logiciel (son Windows), pour vérifier le rendu.
4. Va dans Heartopia, ouvre l'instrument et appuie sur **F6** : la musique est jouée dans le jeu avec les touches du clavier.

Dès que tu touches au clavier ou fais un clic gauche pendant la lecture dans le jeu, elle s'arrête pour te rendre la main (option désactivable dans Réglages). Le clic droit est permis : tu peux tourner la caméra pendant que ça joue.

Si le jeu ne reçoit pas les touches, lance le programme en administrateur (clic droit, Exécuter en tant qu'administrateur).

## Raccourcis (globaux, même quand le jeu est au premier plan)

| Touche | Action |
|--------|--------|
| F6 | Onglet Musique : jouer dans le jeu / pause. Onglet Image : lancer / arrêter le dessin. Onglet Cuisine : lancer / arrêter la cuisine |
| F7 | Stop (musique, dessin et cuisine) |
| F8 / F9 | Musique suivante / précédente |
| F10 / F11 | Vitesse - / + |
| F12 | Instrument suivant |
| F3 | Capturer un point pendant le calibrage du dessin ou de la cuisine |

Les raccourcis suivent l'onglet ouvert dans DodoTopia : avec l'onglet Image affiché, F6 ne lance jamais la musique. Modifiables dans **Réglages** (icône ⚙) : clique dans le champ et appuie sur la touche voulue.

## Jouer à plusieurs (mode Multi)

L'interrupteur **Solo / Multi** sous le bouton « Jouer dans Heartopia » change ce que fait F6.

- **Solo** : lecture immédiate, comme avant.
- **Multi** : F6 lance un compte à rebours (10 s) pendant lequel DodoTopia **écoute le son du jeu** (la sortie audio du PC). Le premier joueur dont le compte à rebours se termine devient **meneur** : son DodoTopia joue un court motif repère (DO5, SOL4, puis sa **note d'identité**) avec son instrument dans le jeu, puis démarre la musique 1,5 s plus tard. Les autres, encore en attente, **détectent** le motif dans le son du jeu, deviennent **suiveurs** et démarrent au même instant. Tout le monde joue la même musique, chacun sur son instrument, dans la même tonalité (transposition commune, vitesse ×1).

Chaque joueur choisit un **numéro** (1 à 5, tous différents) dans Réglages › Multi : sa note d'identité (LA4, FA4, RÉ4, MI4 ou DO4, jouable sur les trois instruments) permet de reconnaître qui a joué le motif, et décale son compte à rebours de 1,2 s par numéro pour éviter deux meneurs simultanés (le joueur 1 est meneur en priorité ; si deux motifs partent quand même en même temps, tout le monde se cale sur le plus petit numéro).

Procédure : tous au même endroit dans le jeu, chacun avec son instrument ouvert et la même musique choisie ; chacun appuie sur F6 dans une fenêtre de 10 s. Le compte à rebours, le rôle et le numéro du meneur s'affichent dans l'onglet Musique. F7, une touche ou un clic gauche annulent.

**Calibrer (tout le monde se cale)** : bouton « Calibrer » de l'onglet Musique, à cliquer tous ensemble (10 s) dans le jeu, instrument ouvert. Le meneur (premier compte à rebours écoulé) joue son motif ; chaque suiveur répond avec le sien dans un créneau lié à son numéro (joueur 1 à +1,5 s, joueur 2 à +3,1 s, etc.) ; le meneur renvoie aussitôt un écho du motif de chaque joueur entendu. Chaque suiveur mesure ainsi l'aller-retour par le jeu et enregistre la moitié comme **décalage** : au prochain top départ il jouera d'autant plus tôt, de sorte que tout le monde joue au même instant ; chacun (joueurs et spectateurs) n'entend plus les autres qu'avec le seul délai du jeu. Le meneur voit la liste des joueurs entendus. À refaire quand le lieu, le réseau ou les joueurs changent. Deux joueurs avec le même numéro se mélangent : numéros différents obligatoires.

À faire une fois, dans **Réglages › Multi** : choisir la **sortie audio écoutée** (celle où le jeu joue) et cliquer **Tester la détection** (dans le jeu, instrument ouvert) : DodoTopia joue ton motif et mesure le délai entre l'appui et la détection sur ton PC, l'accord du jeu et la hauteur réelle des notes. **Écouter 30 s** dit quels motifs sont reconnus : pendant l'écoute, un autre joueur lance « Tester la détection » sur son PC (son motif est joué dans le jeu) et l'écoute doit afficher « motif reconnu (joueur N) » ; sans personne, elle compte les faux signaux de la musique du jeu (s'il y en a, baisse la musique du jeu et garde le son des instruments). Chaque écoute ou top départ écrit `multi.log` et l'audio écouté `multi_ecoute.wav` dans le dossier de données (`%APPDATA%\DodoTopia`), utiles pour comprendre un motif non reconnu. L'écoute dans le logiciel est coupée pendant l'attente (elle serait recapturée).

## Image : dessiner dans Heartopia

1. Onglet **Image**, importe un `.png` / `.jpg` (bouton ou glisser-déposer).
2. Choisis le **format** du dessin (16:9, 4:3, 1:1, 3:4, 9:16, ou Auto selon les proportions de l'image), le **cadrage** (Ajuster laisse des cases vides, Remplir recadre), le nombre de **couleurs** (jusqu'aux 126 nuances du jeu : chaque pastille de la palette en cache 10, 6 pour le noir), le **tramage**, la luminosité, le contraste et la saturation. Les couleurs sont comparées dans l'espace perceptuel CIELAB pour que les teintes ternes (peau, bois, murs) gardent leur couleur. L'aperçu montre exactement ce qui sera peint.
3. **Calibrer** (une fois par format et par écran) : dans le jeu, ouvre un dessin dans ce format, **finesse des détails au maximum**. L'assistant demande de survoler dans le jeu les coins haut-gauche et bas-droit de la zone rayée, la première et la dernière pastille de la palette, le bouton « palette » (icône à gauche des pastilles, qui affiche les nuances), puis, nuances ouvertes, la pastille centrale de la bande des familles (celle encadrée), les flèches < et > de cette bande, et la nuance en haut à gauche et celle en bas à droite du bloc de nuances, le crayon, le pot de peinture et le bouton Annuler, en appuyant sur **F3** à chaque fois. DodoTopia lit alors les vraies couleurs de la palette à l'écran. Les 6 étapes « nuances » sont nécessaires pour dessiner : l'aperçu utilise toujours les 126 nuances. Les coins n'ont pas besoin d'être au pixel près : la géométrie exacte est mesurée à chaque dessin.
4. **Calibrage auto** (conseillé, une fois par format) : ouvre un dessin **vide** dans le jeu, crayon sélectionné, zoom au minimum, puis clique sur le bouton. DodoTopia remplit le fond, peint une pastille de chaque couleur (pour apprendre les couleurs telles qu'elles sont peintes), cinq repères dans les coins et au centre (pour mesurer la taille et la position exactes des cases), un trait zigzag de test (pour trouver le rythme que le jeu suit sans perdre de positions), puis trois points de validation. Si tout tombe dans la bonne case, le format est marqué ✓✓ et les réglages sont enregistrés. Le canevas de test est annulé avec le bouton Annuler s'il est calibré, sinon ouvre un nouveau dessin ensuite.
5. Dans le jeu, ouvre un dessin vide dans le même format (finesse max, zoom au minimum, crayon sélectionné), puis **F6**. DodoTopia remplit le fond au pot de peinture avec la couleur la plus présente, mesure sur l'écran le rectangle rempli pour connaître la taille et la position exactes des cases, puis peint les autres couleurs au crayon en traits zigzag (pour chaque nuance : ouverture des nuances si besoin, lecture de la page affichée sur la bande des familles, flèches suivant/précédent jusqu'à la bonne page (1 noir, 2 rouge, … 13 rose), puis la nuance). Après chaque couleur, elle relit l'écran et repeint les cases manquantes (jusqu'à 5 passes). Toute touche du clavier, F7 ou un mouvement de souris arrête le dessin.

**Mode contours + pot de peinture** (option « Contours au crayon, puis pot de peinture » dans Réglages, cochée par défaut) : au lieu de peindre chaque zone case par case, DodoTopia ne trace au crayon que le bord de chaque zone de couleur, vérifie à l'écran que les contours sont fermés, puis remplit l'intérieur de chaque zone d'un seul clic au pot de peinture. Entre deux couleurs voisines, une seule des deux trace la frontière (la moins présente), ce qui suffit pour que le pot ne déborde jamais ; les zones de moins de 4 cases sont peintes au crayon. Après chaque remplissage, l'écran est relu : si le pot a débordé (contour troué), le bouton Annuler est cliqué et la zone est peinte au crayon à la fin. Ce mode demande le crayon, le pot de peinture et, pour la détection des fuites, le bouton Annuler calibrés. Il est très efficace sur les images « à plat » (peu de couleurs, tramage désactivé : quelques dizaines de zones) et n'apporte rien sur une image tramée, où presque toutes les cases sont des contours. La ligne « Contours » sous la palette de l'aperçu indique combien de cases seront peintes au crayon et combien de zones au pot. Dans les deux modes, les traits enchaînent maintenant les lignes voisines sans lever le crayon (en se décalant de côté, en descendant puis en remontant), ce qui réduit nettement le nombre d'appuis souris ; le réglage « Délai après un clic » espace les clics isolés si le jeu les trouve trop rapprochés. Avec « Souris qui glisse comme une main » (coché par défaut), le curseur se déplace jusqu'à chaque cible en accélérant puis en freinant, par une trajectoire légèrement courbe et tremblée dont la forme, la durée et la cadence changent à chaque déplacement (l'arrivée reste exacte), pour le dessin comme pour le calibrage auto, au lieu de sauter d'un point à l'autre ; « Durée des glissements » règle la vitesse moyenne. Les temps de pose et d'appui des clics varient aussi légèrement.

Sans remplissage du fond (option dans Réglages), la mesure se fait par un remplissage temporaire suivi d'un clic sur Annuler, d'où l'étape Annuler du calibrage. Sans elle, DodoTopia se rabat sur deux cases repères, moins fiable. Le rythme s'adapte tout seul : si le jeu perd des positions de souris (par exemple quand il tourne à 30 images/s), DodoTopia espace davantage les points, puis envoie un point par case si ça ne suffit pas. Le détail de chaque dessin (mesure du canevas, sonde, réparations, cases restantes) est dans `%APPDATA%\DodoTopia\dessin.log`, ouvrable par le lien **Journal du dessin** en bas de l'onglet Image. Si les traits restent en pointillés malgré tout, coche **Mode précis** dans Réglages. Le nombre de cases de chaque format est connu (16:9 : 140×84, 4:3 : 150×114, 1:1 : 150×150, 3:4 : 114×150, 9:16 : 84×150) et modifiable dans Réglages ; il est aussi détecté au calibrage quand la grille du jeu est visible.

## Cuisine : cuisiner en boucle

L'onglet **Cuisine** refait la **dernière recette cuisinée** (première tuile « Utilisation récente » du menu Recettes) autant de fois que demandé, sans toucher à rien : clic sur la bulle « cuisiner » de la cuisinière, tuile récente, bouton Cuisiner ; pendant la cuisson, dès que la bulle montre la **spatule entourée d'un anneau vert** (« Ajuste le feu de la cuisinière… », une à trois fois par plat), clic dessus ; quand la bulle montre les **gants**, clic pour récupérer le plat ; si l'animation d'un plat amélioré s'affiche, un clic sur un coin d'herbe vide la ferme ; et on recommence.

1. **Calibrer** (une fois par écran) : devant la cuisinière dans le jeu, l'assistant demande, avec **F3** à chaque étape, les deux coins de la **zone de recherche** (là où la bulle peut apparaître, sans les icônes du jeu ; la bulle bouge un peu d'un plat à l'autre, DodoTopia la cherche dans cette zone), le centre de la **bulle « cuisiner »** (la forme de son icône blanche est mémorisée), puis, menu Recettes ouvert, la **première tuile récente** et le bouton **Cuisiner** (sa couleur indique si le menu est ouvert), puis, pendant une cuisson, la bulle **spatule avec l'anneau vert** (facultatif mais conseillé : la couleur exacte de l'anneau est lue ; sinon un vert vif standard est cherché), la bulle **gants** à la fin de la cuisson, et enfin un **coin d'herbe vide** où cliquer pour fermer les animations.
2. **Tester la détection** : devant la cuisinière, dit quelle bulle est reconnue et avec quels scores (utile si la boucle ne démarre pas).
3. Place-toi devant la cuisinière, bulle « cuisiner » visible, avec les ingrédients de la recette, puis **F6** (ou le bouton, qui laisse 3 s pour revenir dans le jeu). Le nombre de plats est dans Réglages › Cuisine (0 = sans fin : la boucle s'arrête d'elle-même quand le menu reste ouvert, faute d'ingrédients). **F7**, une touche ou un mouvement de souris arrêtent tout.

Comment ça marche : l'écran est lu avec Pillow seulement. La bulle est reconnue par la forme de son icône blanche (masque des pixels blancs comparé aux références du calibrage, score de Jaccard, seuil réglable) et par le disque gris qui l'entoure (il ne doit pas contenir de blanc : un texte ou une tache blanche ne sont pas pris pour la bulle) ; suivi rapide autour de la dernière position, recherche dans toute la zone quand elle est perdue. L'anneau de la spatule est reconnu par ses pixels verts autour de la bulle. Chaque changement d'état, avec les scores, est dans `%APPDATA%\DodoTopia\cuisine.log` (lien **Journal de la cuisine** en bas de l'onglet) ; en cas d'échec, la dernière capture de la zone est dans `cuisine_echec.png`, et les icônes capturées au calibrage dans `cuisine_ref_*.png`. Réglages › Cuisine : nombre de plats, durée maximale d'une cuisson, seuil de reconnaissance, pixels verts de l'anneau, délai après un clic. Le glissement de la souris (Réglages › Dessin) s'applique aussi à la cuisine.

## Instruments

- **Piano** : 37 touches chromatiques (3 octaves + DO aigu). La transposition automatique ne change que l'octave.
- **Flûte / Luth** : 15 touches diatoniques (DO RÉ MI FA SOL LA SI sur 2 octaves + DO aigu). L'appli cherche la tonalité qui met le plus de notes sur la gamme, puis rapproche les dièses restants de la note la plus proche.

Le clavier affiché dans la fenêtre montre les touches envoyées au jeu. L'écoute dans le logiciel joue exactement les notes qui seront envoyées (après transposition), avec un son de piano, de flûte ou de guitare nylon.

## Bibliothèque

- **Renommer** : crayon au survol, ou double-clic sur le nom. Entrée valide, Échap annule. Le fichier `.mid` n'est pas renommé, seul le nom affiché change.
- **Favoris** : étoile à droite de chaque musique. Les favoris sont toujours en haut de la liste ; le bouton ★ de la barre n'affiche qu'eux.
- **Recherche** : la loupe filtre en direct sur le nom affiché et le nom du fichier.
- **Tri** : nom, ajout récent, plus écoutées, dernière écoute.
- **Noms nettoyés à l'import** : les suffixes de sites, « Anonymous », dates et doubles extensions sont retirés du nom affiché.
- Chaque ligne indique la durée et le nombre d'écoutes. Ces infos sont dans `library.json`, à côté du dossier `songs`.

## Réglages

- **Arrêter si je touche au clavier ou à la souris** : mode jeu uniquement.
- **Délai avant lecture** : secondes entre F6 et la première note.
- **Durée d'appui** : durée de chaque frappe de touche.
- **Mode d'envoi** : `Position physique` (par défaut) ou `Lettre affichée`. Si les notes sont fausses sur un clavier AZERTY, essaie l'autre.
- **Transposition** : demi-tons ajoutés en plus de l'automatique.
- **Volume** : volume de l'écoute dans le logiciel (curseur sous la vitesse).

## Logo

Remplace `assets\logo.png` par ton logo (carré, PNG). `build.bat` en fait l'icône de l'exe et de l'installeur ; la fenêtre l'affiche en haut à gauche.

## Construire l'exe et l'installeur

```
build.bat
```

Produit `dist\DodoTopia\` (exe et fichiers), puis dans `release\` l'installeur `DodoTopia-x.y.z-Setup.exe` et le zip portable. La version est dans `version.py` : change-la avant chaque mise à jour.

Outils : Python 3, PyInstaller et Pillow (installés par le script), Inno Setup 6 (`winget install JRSoftware.InnoSetup`). Variable `PYTHON` pour choisir l'interpréteur (défaut `py`).

## Publier une version (GitHub Actions)

Le dépôt GitHub construit et publie les versions ; les DodoTopia installés se mettent alors à jour tout seuls (toast « Version x.y.z disponible »).

1. Mets à jour `version.py` (`VERSION = "1.7.1"`) et ajoute une section `## 1.7.1` avec des puces dans `CHANGELOG.md` (ce sont les notes affichées aux joueurs).
2. `git push` sur `main`. Comme `version.py` a changé, le workflow **Release** (`.github/workflows/release.yml`) enchaîne : lecture de la version → `build.bat` sur un runner Windows (exe + installeur Inno Setup + zip portable) et `docker/Dockerfile.linux` sur un runner Ubuntu (archive Linux) en parallèle → **release GitHub** (tag `vX.Y.Z`, binaires attachés, notes tirées du `CHANGELOG.md`) → `publish_release.py` qui dépose les trois fichiers sur le serveur (sha256 vérifié) et publie la version. Compte 15 à 25 minutes. Les artefacts restent 14 jours dans l'onglet Actions, la release GitHub est permanente.
3. Vérifie `https://dodotopia.cyber-dodo.fr/api/releases/latest` : la version doit être `latest`. Les binaires sont aussi téléchargeables sur la page *Releases* du dépôt.

**Secrets à créer une fois** sur GitHub (*Settings* > *Secrets and variables* > *Actions* > *New repository secret*) :
`PUBLISH_URL` = `https://dodotopia.cyber-dodo.fr` (sans `/` final) et `PUBLISH_TOKEN` = la valeur `PUBLISH_TOKEN` du `.env` du serveur (Dokploy > Environment).

**À la main** : onglet *Actions* > *Release* > *Run workflow* (branche `main` ; le champ *version* est facultatif et doit être égal à `version.py`). Sans la CI : `build.bat`, `build-linux.bat` puis `publish.bat` avec un fichier `publish.env` (`PUBLISH_URL=…`, `PUBLISH_TOKEN=…`, ignoré par git) ; `publish.bat --force` republie une version déjà en ligne, `--mandatory` la rend obligatoire.

Un push qui ne touche pas `version.py` ne publie rien, mais tout push sur `main` redéploie le serveur (Dokploy, webhook GitHub) et lance les tests du serveur si `server/` a changé (`.github/workflows/server-tests.yml`, SQLite puis PostgreSQL).

**Dépôt git** : `.gitignore` exclut les sorties de build, `songs/`, `library.json`, `account.json`, les journaux, `publish.env`, `server/.env` et `server/.venv/`. `config.json` **n'est pas versionné** : en mode source c'est ta configuration personnelle, avec les calibrages de ton écran (palette, outils, grilles, cuisine). C'est `config.default.json` qui est versionné et livré dans l'installeur ; `make_default_config.py` le régénère au début de chaque build en retirant tout calibrage. Sur un runner sans `config.json`, le `config.default.json` du dépôt est conservé tel quel.

## Serveur en ligne (Dokploy)

Le backend (`server/`) tourne sur un VPS avec **Dokploy** en service *Compose* (`server/docker-compose.yml` : API FastAPI + PostgreSQL 16 ; Traefik et le certificat HTTPS sont fournis par Dokploy). Procédure complète, variables, sauvegarde et dépannage : `server/README.md`.

## Linux

DodoTopia fonctionne aussi sous Linux (session **X11 / Xorg** conseillée ; le jeu sous Steam/Proton est une fenêtre X, donc les touches et la souris l'atteignent aussi sous Wayland via XWayland, mais la lecture d'écran du dessin peut alors renvoyer une image noire). Pas besoin de root : les touches et la souris passent par l'extension XTEST, les raccourcis globaux par XRECORD.

- **Archive** : `release/DodoTopia-x.y.z-linux-x64.tar.gz`. Décompresse, puis lance `DodoTopia/DodoTopia`. Réglages, musiques et journal dans `~/.config/DodoTopia`.
- **Bibliothèques nécessaires** (Ubuntu/Debian) : `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libnss3 libasound2 libgl1 libegl1 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxi6 libfontconfig1 libpulse0 xdg-utils`. Pour l'écoute dans le logiciel (facultatif) : `sudo apt install fluidsynth fluid-soundfont-gm`.
- **Depuis les sources** : `./DodoTopia.sh` (Python 3.10+, `python3-venv`). L'interface utilise GTK/WebKit2 si `python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1` sont installés, sinon Qt (installé automatiquement dans le venv).
- **Construire l'archive depuis Windows** : `build-linux.bat` (Docker Desktop lancé). L'image `docker/Dockerfile.linux` (Ubuntu 22.04) compile avec PyInstaller, vérifie que le binaire démarre, et copie l'archive dans `release\`. Sur Linux ou WSL2 : `bash build.sh` (paquets : `python3-venv binutils libpython3.x`).
- Le mode d'envoi « Position physique » suppose la disposition détectée par Wine/Proton ; si les notes sont fausses, passe en « Lettre affichée ». Si le pilote graphique fait planter l'interface : `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu ./DodoTopia/DodoTopia`.

## Fichiers

- `app.py` : interface graphique (fenêtre WebView2) et API.
- `ui/index.html` : la page de l'interface (style Heartopia).
- `core.py` : moteur musique (lecture MIDI, transposition, envoi des touches, écoute, interruption).
- `draw.py` : moteur dessin (calibrage, lecture de la palette et de la grille à l'écran, peinture à la souris, mode contours + pot de peinture).
- `sync.py` : mode Multi (capture de la sortie audio, détection de la note repère, session meneur / suiveur, test de détection).
- `cook.py` : cuisine en boucle (calibrage, reconnaissance de la bulle et de l'anneau vert à l'écran, boucle cuisiner / feu / récupérer).
- `bot.py` : base commune du dessin et de la cuisine (journal, attente interruptible, souris qui glisse, clic, arrêt si clavier ou souris touchés).
- `platform_io.py` : couche plateforme ; `_win_io.py` (SendInput, `keyboard`, winmm, Pillow) et `_linux_io.py` (X11 : XTEST, XRECORD, mss, rtmidi).
- `config.json` : réglages et instruments par défaut. Une fois installé, la config utilisée est dans `%APPDATA%\DodoTopia\config.json` (Linux : `~/.config/DodoTopia`).
- `heartopia_player.py` : version console, sans interface.
- `build.bat`, `installer.iss`, `version.py` : construction Windows. `build.sh`, `build-linux.bat`, `docker/Dockerfile.linux`, `requirements-linux.txt`, `DodoTopia.sh` : construction et lancement Linux.
- `server/` : backend (FastAPI + PostgreSQL, déployé avec Dokploy, voir `server/README.md`). `publish_release.py`, `publish.bat`, `CHANGELOG.md` : publication d'une version. `.github/workflows/` : CI (tests du serveur, construction et publication des versions).

## Dépendances

Windows :

```
py -m pip install mido keyboard pywebview Pillow numpy soundcard
```

Linux : `pip install -r requirements-linux.txt` (mido, Pillow, python-xlib, mss, python-rtmidi, numpy, soundcard, pywebview[qt], PyInstaller). numpy et soundcard servent au mode Multi (capture de la sortie audio : WASAPI sous Windows, moniteur PulseAudio / PipeWire sous Linux, paquet `libpulse0`).

Pillow sert à lire l'écran pour le calibrage du dessin (couleurs de la palette, comptage de la grille). Sans lui, le dessin fonctionne avec la palette et les grilles par défaut.
