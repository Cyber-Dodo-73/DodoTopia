# Journal des versions

Une section `## x.y.z` par version : la CI envoie la section de la version publiée comme notes de mise à jour
(affichées dans DodoTopia quand une mise à jour est proposée).

La section du haut est la version **en préparation** : tant que `version.py` ne change pas, rien n'est publié.

## 2.2.1
- **Studio** (Mes créations › Musiques › « Ajouter une musique ») : un éditeur sur une ligne de temps pour faire une musique à plusieurs instruments depuis un fichier MIDI. Chaque piste est une ligne où l'on voit ses notes ; avec les ciseaux tu la coupes en passages, tu tires la limite entre deux passages, et chaque passage a son instrument et son octave (le couplet au violon, le refrain au piano). **Lecture intégrée** : lire, mettre en pause, cliquer sur la règle du temps pour reprendre d'où tu veux (Espace : lecture ou pause), avec un son de synthèse, et ce que tu entends suit tes modifications. Toutes les pistes restent dans la même tonalité et le studio indique la part de notes jouées à la bonne hauteur. « Ajouter à Heartopia » écrit la musique dans le jeu sans rien remplacer.
- **Tous les instruments à notes du jeu sont connus d'avance** dans le studio (piano, harpe, luth, flûte à bec, lyre, violon, violoncelle, saxophone, ocarina, xylophone, conque…) : rien à apprendre. L'export en MIDI d'une musique du jeu retrouve aussi les bonnes notes et le bon timbre pour chacun.
- **Écouter une musique du jeu sur l'ordinateur** : dans Mes créations › Musiques, « Écouter sur cet ordinateur » convertit l'enregistrement d'Heartopia et le joue avec le son de synthèse, sans retourner dans le jeu. Pratique pour vérifier une musique ajoutée ou remplacée ; elle est rangée dans ta bibliothèque sous « Heartopia - titre ».
- **Conque** : jouable, avec ses touches du jeu (Y U I O pour do, ré, mi, fa ; H J K L pour sol, la, si, do). Tous les instruments du catalogue ont maintenant leur disposition.
- **Connexion Discord sans code à recopier** : après « Se connecter avec Discord », tu autorises DodoTopia dans le navigateur et tu es connecté dans l'application, sans rien saisir. Le navigateur rapporte la connexion directement à DodoTopia sur ton ordinateur, ce qui garde la protection contre les liens piégés. Le code reste disponible pour se connecter depuis un autre appareil (« Me connecter depuis un autre appareil »).

- **Import par lien** : Online Sequencer n'est plus proposé, le site bloque désormais les téléchargements automatiques. Télécharge le fichier .mid depuis ton navigateur puis ouvre-le dans DodoTopia ; BitMidi et les liens directs vers un fichier .mid marchent toujours.

## 2.2.0
- **Mes créations**, nouvelle activité : tes photos, tes peintures et tes musiques enregistrées dans Heartopia, lues directement dans les fichiers que le jeu garde sur ton ordinateur, rangées en trois onglets (Photos, Peintures, Musiques) et triées par date.
- **Importer dans le jeu** : « Ajouter une photo » met ton image dans l'album d'Heartopia (aux quatre tailles que le jeu garde, chiffrée comme les siennes, avec sa fiche) et « Ajouter une musique » convertit un fichier MIDI en enregistrement du jeu joué au piano, sans rien remplacer. « Supprimer cet ajout » retire ce que DodoTopia a ajouté, jamais ce que le jeu a créé. Fonction récente : relance Heartopia pour voir l'ajout.
- **Remplacer** une photo ou une musique : l'image est amenée à chaque taille que le jeu garde (« Remplir » ou « Ajuster »), un fichier MIDI (ou un enregistrement `.bin`) prend la place d'une musique en gardant son titre. L'original est sauvegardé et « Remettre l'original » le restaure. Les peintures s'exportent seulement : le jeu garde le vrai dessin sur ses serveurs (pour peindre une image, c'est l'activité Dessin).
- **Exporter** : photos et peintures en image aux vraies couleurs, musiques en fichier MIDI (une piste par joueur et par instrument), relisible dans l'activité Musique.
- Par défaut, seules tes propres créations sont affichées. Le reste de ce que le jeu garde (images et musiques des autres joueurs, cadres, pochettes, annonces) apparaît dans une section « Cache du jeu » avec le réglage **Réglages › Apparence › Mes créations : afficher aussi le cache du jeu**.
- Le dossier du jeu est détecté tout seul (Windows ; Proton/Wine sous Linux) et peut être choisi à la main. Nouvelle dépendance : `cryptography`.
- **Xylophone à 8 notes** : jouable, avec ses touches du jeu (A S D F G H J K, de do à do). Les morceaux sont ramenés sur son octave par l'arrangeur.
- **Connexion Discord plus visible** : tant que tu n'es pas connecté, le bouton de l'en-tête prend les couleurs de Discord, « Mon compte » liste ce que la connexion apporte (partager, jouer en salon, aimer, importer par lien) et une invitation apparaît en haut de chaque activité ; « Plus tard » la masque deux semaines. La découverte du premier lancement a une étape « Discord », facultative. Tout fonctionne toujours sans compte.
- Site : nouvelle page « Mes créations » dans les 10 langues (menu, accueil, plan du site, image de partage).

## 2.1.0
- **Jouer ensemble, plus simple.** Le salon n'est plus un « mode » à activer puis à désactiver : on est en salon tant qu'on y est, et le quitter ramène au jeu en solo. Une barre en haut de la Musique montre le salon (code, joueurs, morceau) et son action principale (« Je suis prêt » / « Lancer la session ») depuis la bibliothèque comme depuis « Découvrir ». Le bouton du lecteur et F6 font l'action du salon au lieu de disparaître.
- **Choisir le morceau du salon sans quitter le salon** : un sélecteur réunit ta bibliothèque et les morceaux partagés ; « Jouer dans le salon » dans le menu de chaque morceau, et « Proposer au salon » dans le lecteur pour le chef.
- « Jouer ensemble » propose directement deux cartes : créer ou rejoindre un salon, ou activer la synchro par le son.
- **L'Orchestre** : le chef répartit les pistes du fichier MIDI entre les joueurs (la mélodie au piano, la basse à la basse en bois…), automatiquement d'après l'instrument de chacun ou à la main, avec l'octave de chaque partie. Chacun ne joue que sa partie, dans la tonalité commune. Les joueurs d'une version plus ancienne jouent tout le morceau, comme avant.
- **Arrangement automatique** pour les instruments à 15 notes : la mélodie est toujours gardée et déplacée par phrase entière (plus de sauts d'octave au milieu d'une phrase), les accords sont allégés et les notes sans touche juste sont omises au lieu de sonner faux. Réglable pour tous les morceaux (Réglages › Musique et audio) ou morceau par morceau (« Version jouée » : Original / Arrangé, avec la comparaison des deux).
- **Instruments par famille** : chaque instrument joue comme le piano (harpe) ou comme le luth (flûte à bec, xiao, saxophone, violon, violoncelle, ocarina, concertina, lyre, tambour à langues métalliques), avec ses vraies touches du jeu. Plus de test, de calibrage ni de statut « à vérifier » : les instruments de ces familles sont jouables directement.
- **Envoyer un rapport** (Aide, Réglages › À propos, messages d'erreur) : DodoTopia rassemble ses journaux, montre la liste avant l'envoi, et donne un code à coller sur Discord. Les captures de la cuisine et le dernier enregistrement audio ne partent que si tu coches leur case. Jamais envoyés : le jeton de connexion, la bibliothèque, le pseudo ; le dossier personnel est masqué. Le zip peut aussi être enregistré sans connexion.
- **Deux nouvelles langues : indonésien et philippin** (bêta), dans l'application et sur le site. Les traductions existantes sont complétées partout, y compris les mentions légales et la politique de confidentialité du site dans toutes les langues.
- Les conditions d'utilisation sont maintenant traduites dans les 10 langues (la version française fait toujours foi) ; leur article sur les données mentionne le rapport de diagnostic. Pas de nouvelle acceptation à donner.

## 2.0.2
- Cuisine à plusieurs cuisinières : l'anneau vert (« Ajuste le feu ») est maintenant cherché dans toute la zone et toujours cliqué, même quand l'icône de la spatule est animée ou que la bulle vient de bouger ; la deuxième cuisinière est reconnue même si ses bulles n'apparaissent qu'une à la fois.
- Mises à jour silencieuses : au démarrage, la nouvelle version se télécharge, s'installe sans aucune fenêtre d'installeur ni bouton à cliquer, puis DodoTopia redémarre tout seul (désactivable dans Réglages › En ligne).
- Cuisine plus rapide : « Cuisiner » est cliqué directement (le jeu présélectionne la dernière recette), le menu Recettes reste ouvert moins longtemps.

## 2.0.1
- **F6 rejoue dans le jeu.** La 2.0.0 refusait de jouer avec « le jeu n'est pas au premier plan » : elle cherchait un programme nommé Heartopia.exe, alors que le jeu tourne sous xdt.exe. Le jeu est maintenant reconnu par son programme ou par le titre de sa fenêtre, et si DodoTopia ne le trouve pas du tout, il ne bloque plus rien.
- **Cuisine à plusieurs cuisinières réparée.** Quand le personnage rejoint une cuisinière, la caméra le suit et toutes les bulles glissent à l'écran : DodoTopia les perdait ou les confondait (une seule cuisinière servie, plats prêts oubliés, anneau vert cliqué à côté). Les bulles sont maintenant suivies ensemble, l'anneau est cliqué en son centre, une bulle qui bouge encore n'est pas cliquée, et la deuxième cuisinière n'attend plus 8 secondes après chaque lancement et chaque feu ajusté.
- Les boutons « Importer un MIDI », « Importer une image » et l'export/import de profils d'instrument refonctionnent (ils ne faisaient rien en 2.0.0).
- Un raccourci posé sur une touche de note (par exemple Arrêter = B) arrêtait la lecture tout seul : c'est maintenant refusé dans les Réglages, et réparé automatiquement au démarrage.
- Linux : l'archive n'embarque plus les bibliothèques graphiques ni libstdc++ du système de construction (crash au lancement et fenêtre vide sur les distributions récentes), les conditions d'utilisation sont bien livrées, le lanceur est exécutable, et `DODO_SOFTWARE_RENDER=1` force le rendu logiciel. Chaque archive est contrôlée automatiquement et démarrée sur une Debian récente avant publication.
- Les erreurs de l'interface sont écrites dans `dodotopia.log` au lieu de disparaître.
- Site : les fichiers téléchargés ne sont plus recompressés par le serveur (l'archive Linux arrivait « compressée deux fois » avec Firefox), la taille et la reprise du téléchargement reviennent ; les moteurs de recherche peuvent lire le plan du site ; les nouveautés s'affichent mises en forme.

## 2.0.0
- **Huit langues** : français, anglais, et en bêta espagnol, allemand, portugais du Brésil, chinois simplifié, japonais et thaï. La langue du système est choisie automatiquement, modifiable dans Réglages › Apparence, sans redémarrer.
- **Nouvelle interface** : un seul système de couleurs, **thème sombre**, icônes dessinées à la place des emojis, textes jamais sous 12 px, cibles plus grandes, polices adaptées au chinois, japonais et thaï.
- **Découverte guidée** au premier lancement (langue et thème, état du jeu, premier morceau avec « Tester une note »), relançable depuis l'Aide.
- **État du jeu** dans l'en-tête (détecté, non lancé, lancé en administrateur) ; la lecture, le dessin et la cuisine s'arrêtent si Heartopia quitte le premier plan, et l'envoi de touches refusé par Windows est signalé.
- **Conditions d'utilisation obligatoires** : présentées par l'installeur, puis redemandées au premier lancement et à chaque nouvelle version des CGU. Tant qu'elles ne sont pas acceptées, rien ne peut agir.
- **Bibliothèque partagée** : tags, « j'aime », tri Tendance et Les plus aimés, source et licence de chaque morceau ; **import par lien** depuis Online Sequencer, BitMidi ou un lien vers un fichier .mid.
- **Galerie de dessins** : exporter un dessin en image, le publier (après modération), reproduire le dessin d'un autre joueur.
- **Partage** : lien public de chaque morceau, dessin et salon, copiable pour Discord ; liens `dodotopia://` qui ouvrent DodoTopia (toujours avec confirmation) ; Discord Rich Presence ; fichier « en cours de lecture » pour OBS.
- Lecteur : F10/F11 en cours de morceau sans rafale ni silence, notes tenues ré-enfoncées après une pause, appui minimal de 20 ms, pédale de sustain, choix des pistes MIDI, polyphonie de l'instrument respectée ; le jargon technique passe sous « Détails ».
- Dessin et cuisine : un changement d'écran (résolution, mise à l'échelle, écrans) depuis la configuration est détecté au lieu de cliquer à côté ; lecture d'écran bien plus légère.
- Réglages : recherche, nouvelles sections, raisons affichées sous les boutons désactivés, suppression du compte en ligne.
- Fiabilité : journal `dodotopia.log` avec toute erreur interne, réglages écrits sans risque de corruption (un fichier illisible est mis de côté au lieu d'empêcher le démarrage), une seule instance ouverte à la fois.
- Serveur et site : site public en huit langues (pages par activité, téléchargement, aide, nouveautés, morceaux, galerie), connexion Discord protégée par un code, mises à jour signées, annonce des versions sur Discord.
- F12 n'est plus le raccourci « instrument suivant » par défaut (capture d'écran de Steam).
- Inclut toutes les corrections de la 1.9.1 ci-dessous (dessin au pixel près, réajustement et reprise d'un dessin, cuisine à plusieurs cuisinières).

## 1.9.1
- **Dessin : la souris tombait 1 à 2 px à côté** de la position demandée (formule de conversion SendInput fausse, mesurée sur 154 positions) : avec des cases de 4 px, une bonne partie des clics manquaient leur case. Corrigé, exact au pixel.
- **Dessin : réajustement en direct.** Le calibrage et le rectangle rempli donnent le bord de la toile, pas l'endroit exact où le jeu place ses cases : un décalage d'un tiers de case suffisait pour que des centaines de clics tombent dans la case voisine (cinq passes de réparation à chaque couleur, des cases perdues quand même, et un dessin ralenti ×4 parce que la « sonde » prenait ces cases décalées pour des positions perdues). Dès la première couleur, quelques cases repères sont peintes et retrouvées à l'écran pour mesurer l'origine et la taille réelles des cases ; la mesure est refaite si une couleur montre encore trop de manques, et un décalage qui répare nettement mieux que le centre est adopté pour toute la suite. La réparation ne ralentit plus jamais le tracé (une passe inefficace au même rythme prouve que ce n'est pas le rythme), la sonde repeint le même trait pour distinguer géométrie et rythme, et la dernière passe de réparation est enfin relue (ses cases étaient annoncées manquantes à tort).
- **Dessin : reprise d'un dessin interrompu.** Au lancement, DodoTopia lit la toile et ne peint que ce qui manque : un dessin arrêté (touche, souris) reprend là où il en était en le relançant sur la même toile, le fond n'est pas rempli deux fois, et une vérification finale repasse sur toutes les couleurs. Les teintes de la toile vide sont mémorisées pour lire une toile déjà entamée.
- Dessin : lecture de l'écran par vote sur cinq pixels au centre de chaque case (la ligne de grille du jeu faisait passer une case bien peinte pour manquante).
- Cuisine à plusieurs cuisinières : un menu Recettes ouvert hors lancement (bulle « gants » cliquée deux fois) est utilisé pour lancer la recette au lieu d'être cliqué dans l'herbe en boucle muette ; l'anneau vert autour d'une bulle suivie suffit pour cliquer la spatule même si son icône n'est pas reconnue ; arrêt explicite si le menu ne se ferme pas après trois essais.
- Tests : faux jeu de dessin (`tests_draw`, grille décalée, pot, nuances, Annuler) et scénarios de reprise.

## 1.9.0
- **Instruments** : 19 types au lieu de trois (piano, flûte à bec, xiao en bambou, luth, basse en bois, cornemuse, concertina, mbira, lyre, violon, violoncelle, conga, cajón, xylophone à 8 notes, saxophone, harpe, tambour à langues métalliques, ocarina, conque). Une carte et une image par type — pas de couleurs ni d'apparences à choisir — avec recherche par nom français ou anglais, filtres par famille et favoris. Choisir ici n'équipe pas l'instrument dans Heartopia.
- Quatre dispositions de touches documentées (15 notes en 2 ou 3 rangées, 22 notes, 37 notes chromatiques) et un état affiché pour chaque instrument : « profil documenté · à vérifier », « touches personnalisées », « test rapide réussi » ou « confirmé sur cet ordinateur ». Aucun profil livré n'a été testé dans le jeu.
- Six instruments dont les touches restent à relever (xylophone, saxophone, harpe, tambour à langues métalliques, ocarina, conque) mènent à la configuration au lieu de jouer avec les touches du piano. Conga et cajón restent candidats jusqu'au test des frappes : une frappe de percussion n'est pas une hauteur. Procédure de vérification complète dans `RECETTE-Instruments.md`.
- Assistant de configuration en cinq étapes : chaque touche se saisit en l'appuyant, sans l'envoyer au jeu ; doublons, touches non envoyables et collisions avec les raccourcis sont signalés à côté de la ligne, et un mapping qui prendrait la touche d'arrêt est refusé. Le test dans le jeu reste court et annoncé, et ne vaut jamais validation intégrale.
- Clavier AZERTY ou QWERTY : les libellés suivent le clavier, la position envoyée au jeu ne change pas. Les anciens réglages sont repris automatiquement (flûte → flûte à bec, luth), et les touches personnalisées sont conservées telles quelles.
- Avant de jouer, le morceau est comparé à l'instrument : notes hors registre, altérations absentes de la disposition, pistes de percussion. Les adaptations (transposition, octave, omission) sont proposées avec leur effet réel, jamais appliquées en douce. Changer d'instrument pendant une lecture est refusé plutôt que de laisser une touche enfoncée.
- Trois activités au lieu de quatre onglets : **Musique**, **Dessin** et **Cuisine**. Le catalogue partagé devient la vue « Découvrir des morceaux » de la Musique, le compte s'ouvre depuis l'avatar, et les mises à jour vivent dans Réglages › À propos et mises à jour.
- Musique : « Préécouter sur cet ordinateur » et « Jouer dans Heartopia » sont deux blocs distincts, le lancement dans le jeu est l'action principale. « Multi audio » devient « Synchronisation par le son », expliquée avant ses réglages, et « Top départ » devient « Lancer la session ».
- Dessin : l'écran vide propose une seule zone d'import, l'aperçu occupe la zone centrale et les réglages sont groupés en « Toile et cadrage », « Couleurs et rendu » et « Options avancées ». « Auto » affiche le format réellement retenu.
- Configuration de la zone du jeu : une étape à la fois, avec un schéma qui désigne la cible, le retour à l'étape précédente et un récapitulatif repliable. Une annulation conserve la configuration précédente.
- Cuisine : la quantité se choisit dans l'activité — « Quantité définie » ou « En continu » — avec le nombre de cuisinières ; la configuration est résumée en une ligne, son détail et le journal sont en accès secondaire.
- Réglages : sept sections claires, « Musique et audio » regroupe la lecture et la synchronisation, et chaque réinitialisation annonce sa portée exacte.
- Une aide dans l'application : raccourcis, vocabulaire et dépannage. Un indicateur d'en-tête mène à l'activité qui travaille quand on la quitte.
- Une seule mesure par carte : l'en-tête, la barre d'état et chaque activité partagent les mêmes bords, et le contenu occupe sa carte au lieu d'être tassé à gauche. Les paragraphes gardent une largeur lisible, les curseurs leur course.
- Moins de texte répété : les rappels qui redisaient le réglage juste au-dessus ont été retirés, le détail de la Cuisine et le déroulement d'un salon passent derrière un repli. Les diagnostics techniques (scores de reconnaissance, coordonnées) ne s'affichent qu'en mode debug.
- Sélecteur d'instrument allégé : une image et un nom par carte, une ligne de faits dans la fiche, et « Utiliser cet instrument » referme la fenêtre.
- Salon : l'instrument se change depuis le salon, sans le quitter.
- Découvrir : une seule action par ligne, et ajouter un morceau amène directement au lecteur avec le morceau choisi.
- La page de retour de la connexion Discord affiche le logo et sa favicon.
- Site : la proposition de valeur et une vraie capture de l'application passent devant, le journal des nouveautés descend dans la zone de téléchargement, et les questions fréquentes couvrent plateformes, formats, configuration et arrêt.

## 1.8.3
- Les mentions légales, la politique de confidentialité et les conditions d'utilisation du site sont complètes et publiées.

## 1.8.2
- Un site public sur dodotopia.cyber-dodo.fr : présentation, téléchargement, questions fréquentes, mentions légales, confidentialité et conditions d'utilisation.
- Réglages › À propos renvoie vers le site et ses pages légales, et rappelle ce qui est envoyé au serveur.
- L'icône de la barre des tâches suit enfin le logo après une mise à jour : l'application déclare son identité à Windows.
- Liste des musiques : le titre occupe toute la ligne, les actions apparaissent au survol.

## 1.8.1
- Nouveau logo : un dodo qui tient une note de musique, aux couleurs d'Heartopia.
- L'icône Windows est générée proprement à chaque taille, jusqu'à 16 pixels.
- Démarrage plus rapide : le logo envoyé à l'interface passe de 1,6 Mo à 16 Ko.

## 1.8.0
- Cuisine : plusieurs cuisinières à la fois (réglage « Cuisinières » de 1 à 4). L'anneau vert passe avant tout, les cuisinières sont servies à tour de rôle.
- Mise à jour automatique au démarrage : la nouvelle version s'installe seule et DodoTopia redémarre (désactivable dans Réglages › En ligne).
- Salon : quand le chef arrête, tout le monde s'arrête. F7 et le bouton Arrêter suivaient l'inverse de F6.
- Sécurité : les fichiers MIDI reçus d'autres joueurs sont analysés avant d'être ouverts (plafonds d'évènements et de notes, en-tête vérifié, empreinte obligatoire), et les noms de fichiers comme les textes affichés sont assainis.
- La file « À valider » se remplit toute seule pour les administrateurs, et le bouton Actualiser reprend tout.
- Interface : le lecteur occupe toute la largeur, et les actions d'une musique n'apparaissent qu'au survol.

## 1.7.0
- Serveur en ligne : mise à jour automatique de l'app (Windows installeur/portable, Linux).
- Connexion Discord et bibliothèque MIDI partagée (dépôt, modération, téléchargement).
- Salons : jouer ensemble avec un top départ synchronisé par le serveur (le mode Multi audio reste disponible).
- Interface repensée : réglages par sections avec sauvegarde automatique, bloc « Dans Heartopia », bandeau de session.
