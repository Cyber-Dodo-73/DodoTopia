# Journal des versions

Une section `## x.y.z` par version : la CI envoie la section de la version publiée comme notes de mise à jour
(affichées dans DodoTopia quand une mise à jour est proposée).

La section du haut est la version **en préparation** : tant que `version.py` ne change pas, rien n'est publié.

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
