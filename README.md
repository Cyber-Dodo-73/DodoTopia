# DodoTopia

Boîte à outils pour Heartopia, en trois activités :

- **Musique** : joue tes fichiers `.mid` dans le jeu en simulant les touches du clavier de l'instrument, avec écoute dans le logiciel avant.
- **Dessin** : importe une image, DodoTopia la transforme en dessin case par case sur la palette du jeu, puis la peint à ta place dans l'outil de dessin d'Heartopia.
- **Cuisine** : refait en boucle la dernière recette cuisinée sur ta cuisinière, ajuste le feu à temps et récupère les plats.

## Installer

- **`release\DodoTopia-x.y.z-Setup.exe`** : installeur classique (raccourci bureau, désinstallation). Pour mettre à jour, lance simplement le nouvel installeur : il écrase l'ancienne version. Tes musiques et réglages sont conservés dans `%APPDATA%\DodoTopia`.
- **`release\DodoTopia-x.y.z-portable.zip`** : version sans installation. Dézippe et lance `DodoTopia.exe`. Pour mettre à jour, dézippe la nouvelle version par-dessus.

Sans exe, depuis les sources : double-clique sur `DodoTopia.bat` (Python 3 requis, voir Dépendances).

## Utiliser

1. Activité **Musique**, vue **Ma bibliothèque** : importe tes `.mid` (bouton **Importer un fichier MIDI** ou glisser-déposer dans la fenêtre). La vue **Découvrir des morceaux** propose le catalogue partagé.
2. Bloc **Jouer dans Heartopia** : ligne **Instrument**, bouton **Changer**, choisis l'instrument que tu as ouvert dans le jeu (19 types, voir *Instruments*).
3. Bloc **Préécouter sur cet ordinateur** : écoute la musique dans le logiciel (son Windows) pour vérifier le rendu. Rien n'est envoyé au jeu.
4. Va dans Heartopia, ouvre l'instrument et appuie sur **F6** : la musique est jouée dans le jeu avec les touches du clavier.

Dès que tu touches au clavier ou fais un clic gauche pendant la lecture dans le jeu, elle s'arrête pour te rendre la main (option désactivable dans Réglages). Le clic droit est permis : tu peux tourner la caméra pendant que ça joue.

Si le jeu ne reçoit pas les touches, lance le programme en administrateur (clic droit, Exécuter en tant qu'administrateur).

## Raccourcis (globaux, même quand le jeu est au premier plan)

| Touche | Action |
|--------|--------|
| F6 | Activité Musique : jouer dans le jeu / pause. Activité Dessin : lancer / arrêter le dessin. Activité Cuisine : lancer / arrêter la cuisine |
| F7 | Stop (musique, dessin et cuisine) |
| F8 / F9 | Musique suivante / précédente |
| F10 / F11 | Vitesse - / + (s'applique en cours de morceau, sans rafale ni silence) |
| (aucune) | Instrument suivant : désactivé par défaut (F12 est la capture d'écran Steam) ; assignable dans Réglages |
| F3 | Enregistrer une position pendant la configuration du dessin ou de la cuisine |

Les raccourcis suivent l'activité ouverte dans DodoTopia : avec l'activité Dessin affichée, F6 ne lance jamais la musique. Modifiables dans **Réglages** (icône ⚙) : clique dans le champ et appuie sur la touche voulue.

## Jouer à plusieurs (synchronisation par le son)

Le choix **Jouer à plusieurs** du bloc « Jouer dans Heartopia » (Seul · Synchronisation par le son · Salon en ligne) change ce que fait F6.

- **Seul** : lecture immédiate, comme avant.
- **Synchronisation par le son** : F6 lance un compte à rebours (10 s) pendant lequel DodoTopia **écoute le son du jeu** (la sortie audio du PC). Le premier joueur dont le compte à rebours se termine devient **meneur** : son DodoTopia joue un court motif repère (DO5, SOL4, puis sa **note d'identité**) avec son instrument dans le jeu, puis démarre la musique 1,5 s plus tard. Les autres, encore en attente, **détectent** le motif dans le son du jeu, deviennent **suiveurs** et démarrent au même instant. Tout le monde joue la même musique, chacun sur son instrument, dans la même tonalité (transposition commune, vitesse ×1).

Chaque joueur choisit un **numéro** (1 à 5, tous différents) dans le panneau **Synchronisation par le son** du lecteur : sa note d'identité (LA4, FA4, RÉ4, MI4 ou DO4, jouable sur toutes les dispositions documentées) permet de reconnaître qui a joué le motif, et décale son compte à rebours de 1,2 s par numéro pour éviter deux meneurs simultanés (le joueur 1 est meneur en priorité ; si deux motifs partent quand même en même temps, tout le monde se cale sur le plus petit numéro).

Procédure : tous au même endroit dans le jeu, chacun avec son instrument ouvert et la même musique choisie ; chacun appuie sur F6 dans une fenêtre de 10 s. Le compte à rebours, le rôle et le numéro du meneur s'affichent dans l'activité Musique. F7, une touche ou un clic gauche annulent.

**Calibrer (tout le monde se cale)** : bouton « Calibrer ensemble » du panneau Synchronisation par le son, à cliquer tous ensemble (10 s) dans le jeu, instrument ouvert. Le meneur (premier compte à rebours écoulé) joue son motif ; chaque suiveur répond avec le sien dans un créneau lié à son numéro (joueur 1 à +1,5 s, joueur 2 à +3,1 s, etc.) ; le meneur renvoie aussitôt un écho du motif de chaque joueur entendu. Chaque suiveur mesure ainsi l'aller-retour par le jeu et enregistre la moitié comme **décalage** : au prochain top départ il jouera d'autant plus tôt, de sorte que tout le monde joue au même instant ; chacun (joueurs et spectateurs) n'entend plus les autres qu'avec le seul délai du jeu. Le meneur voit la liste des joueurs entendus. À refaire quand le lieu, le réseau ou les joueurs changent. Deux joueurs avec le même numéro se mélangent : numéros différents obligatoires.

À faire une fois, dans **Réglages › Musique et audio › Synchronisation par le son** (bouton « Source audio et test… » du panneau) : choisir la **sortie audio écoutée** (celle où le jeu joue) et cliquer **Tester la détection** (dans le jeu, instrument ouvert) : DodoTopia joue ton motif et mesure le délai entre l'appui et la détection sur ton PC, l'accord du jeu et la hauteur réelle des notes. **Écouter 30 s** dit quels motifs sont reconnus : pendant l'écoute, un autre joueur lance « Tester la détection » sur son PC (son motif est joué dans le jeu) et l'écoute doit afficher « motif reconnu (joueur N) » ; sans personne, elle compte les faux signaux de la musique du jeu (s'il y en a, baisse la musique du jeu et garde le son des instruments). Chaque écoute ou top départ écrit `multi.log` et l'audio écouté `multi_ecoute.wav` dans le dossier de données (`%APPDATA%\DodoTopia`), utiles pour comprendre un motif non reconnu. L'écoute dans le logiciel est coupée pendant l'attente (elle serait recapturée).

## Dessin : dessiner dans Heartopia

1. Activité **Dessin**, importe un `.png` / `.jpg` (bouton ou glisser-déposer). Les réglages sont groupés à droite : **Toile et cadrage**, **Couleurs et rendu**, **Options avancées**.
2. Choisis le **format** du dessin (16:9, 4:3, 1:1, 3:4, 9:16, ou Auto selon les proportions de l'image), le **cadrage** (Ajuster laisse des cases vides, Remplir recadre), le nombre de **couleurs** (jusqu'aux 126 nuances du jeu : chaque pastille de la palette en cache 10, 6 pour le noir), le **tramage**, la luminosité, le contraste et la saturation. Les couleurs sont comparées dans l'espace perceptuel CIELAB pour que les teintes ternes (peau, bois, murs) gardent leur couleur. L'aperçu montre exactement ce qui sera peint.
3. **Configurer la zone du jeu** (une fois par format et par écran) : l'assistant montre une étape à la fois, avec un schéma qui désigne la cible ; « ← Étape précédente » revient en arrière et le récapitulatif replié permet de reprendre n'importe quelle étape déjà faite. Une annulation conserve la configuration précédente. dans le jeu, ouvre un dessin dans ce format, **finesse des détails au maximum**. L'assistant demande de survoler dans le jeu les coins haut-gauche et bas-droit de la zone rayée, la première et la dernière pastille de la palette, le bouton « palette » (icône à gauche des pastilles, qui affiche les nuances), puis, nuances ouvertes, la pastille centrale de la bande des familles (celle encadrée), les flèches < et > de cette bande, et la nuance en haut à gauche et celle en bas à droite du bloc de nuances, le crayon, le pot de peinture et le bouton Annuler, en appuyant sur **F3** à chaque fois. DodoTopia lit alors les vraies couleurs de la palette à l'écran. Les 6 étapes « nuances » sont nécessaires pour dessiner : l'aperçu utilise toujours les 126 nuances. Les coins n'ont pas besoin d'être au pixel près : la géométrie exacte est mesurée à chaque dessin.
4. **Mesurer automatiquement** (conseillé, une fois par format ; menu « Calibrage et journal… ») : ouvre un dessin **vide** dans le jeu, crayon sélectionné, zoom au minimum, puis clique sur le bouton. DodoTopia remplit le fond, peint une pastille de chaque couleur (pour apprendre les couleurs telles qu'elles sont peintes), cinq repères dans les coins et au centre (pour mesurer la taille et la position exactes des cases), un trait zigzag de test (pour trouver le rythme que le jeu suit sans perdre de positions), puis trois points de validation. Si tout tombe dans la bonne case, le format est marqué ✓✓ et les réglages sont enregistrés. Le canevas de test est annulé avec le bouton Annuler s'il est calibré, sinon ouvre un nouveau dessin ensuite.
5. Dans le jeu, ouvre un dessin vide dans le même format (finesse max, zoom au minimum, crayon sélectionné), puis **F6**. DodoTopia remplit le fond au pot de peinture avec la couleur la plus présente, mesure sur l'écran le rectangle rempli pour connaître la taille et la position exactes des cases, puis peint les autres couleurs au crayon en traits zigzag (pour chaque nuance : ouverture des nuances si besoin, lecture de la page affichée sur la bande des familles, flèches suivant/précédent jusqu'à la bonne page (1 noir, 2 rouge, … 13 rose), puis la nuance). Après chaque couleur, elle relit l'écran et repeint les cases manquantes (jusqu'à 5 passes). Toute touche du clavier, F7 ou un mouvement de souris arrête le dessin.

**Mode contours + pot de peinture** (option « Contours au crayon, puis pot de peinture » dans Réglages, cochée par défaut) : au lieu de peindre chaque zone case par case, DodoTopia ne trace au crayon que le bord de chaque zone de couleur, vérifie à l'écran que les contours sont fermés, puis remplit l'intérieur de chaque zone d'un seul clic au pot de peinture. Entre deux couleurs voisines, une seule des deux trace la frontière (la moins présente), ce qui suffit pour que le pot ne déborde jamais ; les zones de moins de 4 cases sont peintes au crayon. Après chaque remplissage, l'écran est relu : si le pot a débordé (contour troué), le bouton Annuler est cliqué et la zone est peinte au crayon à la fin. Ce mode demande le crayon, le pot de peinture et, pour la détection des fuites, le bouton Annuler calibrés. Il est très efficace sur les images « à plat » (peu de couleurs, tramage désactivé : quelques dizaines de zones) et n'apporte rien sur une image tramée, où presque toutes les cases sont des contours. La ligne « Contours » sous la palette de l'aperçu indique combien de cases seront peintes au crayon et combien de zones au pot. Dans les deux modes, les traits enchaînent maintenant les lignes voisines sans lever le crayon (en se décalant de côté, en descendant puis en remontant), ce qui réduit nettement le nombre d'appuis souris ; le réglage « Délai après un clic » espace les clics isolés si le jeu les trouve trop rapprochés. Avec « Souris qui glisse comme une main » (coché par défaut), le curseur se déplace jusqu'à chaque cible en accélérant puis en freinant, par une trajectoire légèrement courbe et tremblée dont la forme, la durée et la cadence changent à chaque déplacement (l'arrivée reste exacte), pour le dessin comme pour le calibrage auto, au lieu de sauter d'un point à l'autre ; « Durée des glissements » règle la vitesse moyenne. Les temps de pose et d'appui des clics varient aussi légèrement.

Sans remplissage du fond (option dans Réglages), la mesure se fait par un remplissage temporaire suivi d'un clic sur Annuler, d'où l'étape Annuler du calibrage. Sans elle, DodoTopia se rabat sur deux cases repères, moins fiable. Le rythme s'adapte tout seul : si le jeu perd des positions de souris (par exemple quand il tourne à 30 images/s), DodoTopia espace davantage les points, puis envoie un point par case si ça ne suffit pas. Le détail de chaque dessin (mesure du canevas, sonde, réparations, cases restantes) est dans `%APPDATA%\DodoTopia\dessin.log`, ouvrable par le lien **Journal du dessin** en bas de l'activité Dessin. Si les traits restent en pointillés malgré tout, coche **Mode précis** dans Réglages. Le nombre de cases de chaque format est connu (16:9 : 140×84, 4:3 : 150×114, 1:1 : 150×150, 3:4 : 114×150, 9:16 : 84×150) et modifiable dans Réglages ; il est aussi détecté au calibrage quand la grille du jeu est visible.

## Cuisine : cuisiner en boucle

L'activité **Cuisine** refait la **dernière recette cuisinée** (première tuile « Utilisation récente » du menu Recettes) autant de fois que demandé, sans toucher à rien : clic sur la bulle « cuisiner » de la cuisinière, tuile récente, bouton Cuisiner ; pendant la cuisson, dès que la bulle montre la **spatule entourée d'un anneau vert** (« Ajuste le feu de la cuisinière… », une à trois fois par plat), clic dessus ; quand la bulle montre les **gants**, clic pour récupérer le plat ; si l'animation d'un plat amélioré s'affiche, un clic sur un coin d'herbe vide la ferme ; et on recommence.

1. **Calibrer** (une fois par écran) : devant la cuisinière dans le jeu, l'assistant demande, avec **F3** à chaque étape, les deux coins de la **zone de recherche** (là où la bulle peut apparaître, sans les icônes du jeu ; la bulle bouge un peu d'un plat à l'autre, DodoTopia la cherche dans cette zone), le centre de la **bulle « cuisiner »** (la forme de son icône blanche est mémorisée), puis, menu Recettes ouvert, la **première tuile récente** et le bouton **Cuisiner** (sa couleur indique si le menu est ouvert), puis, pendant une cuisson, la bulle **spatule avec l'anneau vert** (facultatif mais conseillé : la couleur exacte de l'anneau est lue ; sinon un vert vif standard est cherché), la bulle **gants** à la fin de la cuisson, et enfin un **coin d'herbe vide** où cliquer pour fermer les animations.
2. **Tester la détection** : devant la cuisinière, dit quelle bulle est reconnue et avec quels scores (utile si la boucle ne démarre pas).
3. Place-toi devant la cuisinière, bulle « cuisiner » visible, avec les ingrédients de la recette, puis **F6** (ou le bouton, qui laisse 3 s pour revenir dans le jeu). La quantité est dans l'activité Cuisine, bloc « Cette session » : **Quantité définie** (avec un nombre de plats) ou **En continu** — la boucle s'arrête alors d'elle-même quand le menu reste ouvert, faute d'ingrédients. En interne, « en continu » reste `cook.max_dishes = 0`. **F7**, une touche ou un mouvement de souris arrêtent tout.

Comment ça marche : l'écran est lu avec Pillow seulement. La bulle est reconnue par la forme de son icône blanche (masque des pixels blancs comparé aux références du calibrage, score de Jaccard, seuil réglable) et par le disque gris qui l'entoure (il ne doit pas contenir de blanc : un texte ou une tache blanche ne sont pas pris pour la bulle) ; suivi rapide autour de la dernière position, recherche dans toute la zone quand elle est perdue. L'anneau de la spatule est reconnu par ses pixels verts autour de la bulle. Chaque changement d'état, avec les scores, est dans `%APPDATA%\DodoTopia\cuisine.log` (bouton **Voir le journal de la cuisine**, dans le détail de la configuration) ; en cas d'échec, la dernière capture de la zone est dans `cuisine_echec.png`, et les icônes capturées au calibrage dans `cuisine_ref_*.png`. Réglages › Cuisine : durée maximale d'une cuisson, seuil de reconnaissance, pixels verts de l'anneau, délai après un clic. La quantité de plats et le nombre de cuisinières se règlent dans l'activité Cuisine. Le glissement de la souris (Réglages › Dessin et calibrage) s'applique aussi à la cuisine.

## Instruments

### Le catalogue

19 types d'instruments : Piano, Flûte à bec, Xiao en bambou, Luth, Basse en bois, Cornemuse, Concertina, Mbira, Lyre, Violon, Violoncelle, Conga, Cajón, Xylophone à 8 notes, Saxophone, Harpe, Tambour à langues métalliques, Ocarina, Conque.

**Une carte par type, une image par type.** Les couleurs et les styles d'un même instrument ne sont pas des entrées séparées : ils sonnent pareil et se jouent pareil, donc les 63 objets du catalogue consulté sont regroupés en 19 types. Il n'y a ni sous-menu de skins, ni choix d'apparence.

Le catalogue vient du site communautaire [Build Heartopia](https://build-heartopia.com/items), consulté le 15 septembre 2026. Ce n'est pas une liste officielle exhaustive, et les noms français sont des traductions proposées, pas les libellés du jeu. Données dans `assets/instruments/catalogue.json`, images dans `ui/instruments/` (chargées localement : la sélection fonctionne hors ligne), provenance et droits dans [`assets/instruments/CREDITS.md`](assets/instruments/CREDITS.md).

Dans le bloc **Jouer dans Heartopia**, la ligne « Instrument · *nom* · Changer » ouvre le sélecteur : recherche par nom français, nom anglais ou alias, filtres par famille (Cordes, Vents, Claviers, Percussions), favoris, et une fiche par instrument avec son état. Une image manquante ne casse rien : la carte affiche une pastille de famille.

**Choisir un instrument ici ne l'équipe pas dans Heartopia** : ouvre-le toi-même dans le jeu. DodoTopia choisit seulement quelles touches il enverra.

### Les quatre dispositions

Le nombre de notes dépend de la disposition ouverte **dans le jeu**, pas du nom de l'instrument.

| Disposition | Notes | Registre | Altérations | Transposition automatique |
|---|---|---|---|---|
| 15 notes, 2 rangées | 15 | Do4 → Do6 | aucune | tonalité |
| 15 notes, 3 rangées | 15 | Do4 → Do6 | aucune | tonalité |
| 22 notes | 22 | Do3 → Do6 | aucune | tonalité |
| 37 notes, chromatique | 37 | Do3 → Do6 | toutes | octave |

Les deux profils à 15 notes ont les **mêmes notes mais pas les mêmes touches** : choisis celui qui correspond à ce que le jeu affiche. Sur une disposition diatonique, l'appli cherche la tonalité qui met le plus de notes sur la gamme, puis rapproche les dièses restants de la note la plus proche ; sur la disposition chromatique, elle ne déplace que l'octave. Convention d'affichage : **Do4 = C4 = MIDI 60**.

Les tables viennent de projets communautaires ([AutoMidiPlayer](https://github.com/Jed556/AutoMidiPlayer/wiki/Support), [Heartopia-Midi-Player](https://github.com/DonElf/Heartopia-Midi-Player/blob/main/HeartopiaMidiPlayer.cpp), [heartopia-midi](https://github.com/sp0oby/heartopia-midi#heartopia-key-mapping)) et sont dans `assets/instruments/layouts.json`. Plusieurs dispositions d'un même instrument restent des réglages de sa fiche, jamais des cartes de plus.

### Ce qui est vérifié, et ce qui ne l'est pas

Chaque instrument porte un état, visible sur sa carte :

| État | Ce que ça veut dire |
|---|---|
| **Touches à configurer** | aucune table connue : l'instrument n'est pas jouable tant qu'il n'est pas configuré |
| **Profil documenté · à vérifier** | une source communautaire donne une table ; elle n'a été testée dans le jeu par personne ici |
| **Touches personnalisées · à vérifier** | table saisie ou modifiée sur cet ordinateur |
| **Test rapide réussi · vérification partielle** | quelques touches vérifiées dans le jeu, pas toutes |
| **Confirmé sur cet ordinateur** | toutes les associations vérifiées une par une, ici (bouton « Validation intégrale… » de la fiche ou du panneau « Voir les touches ») |

Aucun profil livré n'est « confirmé » : les tables sont documentées, pas testées. La procédure pour les vérifier est dans [`RECETTE-Instruments.md`](RECETTE-Instruments.md).

**Touches à relever** (six types, non jouables pour l'instant) : Xylophone à 8 notes, Saxophone, Harpe, Tambour à langues métalliques, Ocarina, Conque. Leur présence au catalogue ne documente pas leurs touches, et ils n'héritent jamais du profil du piano : un instrument sans profil mène à la configuration, pas à une mélodie fausse.

**Conga et cajón** : les sources leur associent une table de 15 notes, mais une frappe de percussion n'est pas une hauteur. Leur profil reste candidat — l'instrument n'est jouable qu'après le test des frappes de l'assistant.

### Clavier AZERTY ou QWERTY

DodoTopia envoie une **position** de touche, pas une lettre : la position `q` est la touche marquée **A** sur un clavier français. Seul le libellé affiché change avec la disposition, jamais ce qui part vers le jeu.

- **Disposition du clavier** : `Auto` (déduite de Windows), `QWERTY` ou `AZERTY`, réglable depuis le panneau « Voir les touches » comme dans les Réglages.
- Changer de disposition **n'efface pas** les touches personnalisées, mais fait repasser les profils « confirmé » et « test rapide » en « à vérifier » : la conclusion dépendait de l'ancien réglage.
- Les lettres posent rarement problème ; ce sont les chiffres et la ponctuation de la disposition à 37 notes (`0 2 3 5 6 7 - = [ ] ; , . /`) qui départagent les deux modes d'**Envoi des touches**. En `Lettre affichée`, la rangée des chiffres d'un clavier français demande Maj : DodoTopia le signale, sans jamais ajouter un Maj tout seul.

### Configurer et vérifier

« Configurer les touches » ouvre un assistant en cinq étapes : ouvrir l'instrument dans le jeu, indiquer la disposition visible, associer les touches (chaque touche se saisit en l'appuyant, sans l'envoyer au jeu ni déclencher de raccourci), tester, enregistrer. Les doublons, les touches non injectables et les collisions avec les raccourcis sont signalés à côté de la ligne concernée ; **un mapping qui prendrait la touche d'arrêt ou de lecture est refusé**.

Le test dans le jeu est volontaire et court : trois touches au maximum, annoncées, avec un compte à rebours pour revenir dans Heartopia. Il s'arrête à tout moment par le bouton **Arrêter le test** de l'assistant ou par le raccourci d'arrêt (F7), qui coupe réellement l'envoi. Il donne « Test rapide réussi », jamais une validation complète.

La **validation intégrale** (bouton « Validation intégrale… » dans la fiche de l'instrument et dans le panneau « Voir les touches ») rejoue le même test par groupes de trois touches, en reprenant à chaque fois là où tu t'es arrêté, jusqu'à ce que **toutes** les associations soient vérifiées : c'est la seule procédure qui écrit « Confirmé sur cet ordinateur ».

Les profils s'exportent et s'importent en JSON depuis « Détails techniques et sources » de la fiche de l'instrument (schéma validé, rien n'est exécuté ; un profil vérifié ailleurs redevient « à vérifier » ici).

### Avant de jouer

Le panneau **Voir les touches** liste, pour chaque note : nom français, nom international, registre, touche sur ton clavier et état d'affectation. Les numéros MIDI et les positions QWERTY de référence sont dans la section avancée.

Avant la lecture, DodoTopia compare le morceau au profil actif et affiche ce qui ne passe pas : notes hors registre, altérations absentes de la disposition, pistes de percussion ignorées. Les adaptations (transposition, déplacement d'octave, omission) sont **proposées avec leur effet réel sur la couverture**, jamais appliquées en douce : chaque option ouvre un aperçu chiffré avant d'être appliquée, et chacune se défait (la transposition s'ajoute à celle des « Réglages du morceau », l'omission se rétablit par « Replier les notes hors registre »).

L'écoute dans le logiciel joue exactement les notes qui seront envoyées (après transposition). C'est un **aperçu sonore indicatif** : un timbre MIDI général, pas le son de l'instrument du jeu.

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
- **Envoi des touches** : `Position` (par défaut) ou `Lettre affichée`. Si les notes sont fausses sur un clavier AZERTY, essaie l'autre.
- **Disposition du clavier** : `Auto`, `QWERTY` ou `AZERTY` (aussi réglable depuis le panneau « Voir les touches »). Ne change que les libellés affichés, jamais la position envoyée au jeu (voir *Instruments*).
- **Transposition** : demi-tons ajoutés en plus de l'automatique.
- **Volume** : volume de l'écoute dans le logiciel (curseur sous la vitesse).
- **Appui minimal / écart minimal** (Avancé) : planchers de 20 ms et 12 ms pour que le jeu voie chaque frappe même à 60 images/s ; à monter si des notes répétées manquent.
- **Pédale de sustain** (Avancé) : prolonge les notes tenues par la pédale (CC64) du fichier MIDI.
- **Programme du jeu** (Avancé) : `Heartopia.exe` par défaut. La lecture, le dessin et la cuisine s'arrêtent dès que ce programme n'est plus au premier plan (sinon les touches et les clics partiraient dans une autre application). Vide = pas de vérification. L'état du jeu (trouvé, au premier plan, lancé en administrateur) est dans `game_window` de l'état, et **Tester une note** envoie une touche au jeu pour vérifier que les frappes arrivent.
- **Pistes** : chaque morceau peut ignorer des pistes MIDI (choix mémorisé dans `library.json`, clé `tracks_off`) ; la piste de tempo est toujours lue.

## Conditions d'utilisation obligatoires

Personne ne peut utiliser DodoTopia sans avoir accepté les CGU (`legal/CGU-fr.md`, traduction `legal/CGU-en.md`, la version française fait foi) :

- l'installeur les présente (page « Accord de licence » d'Inno Setup, `LicenseFile`, RTF générés par `.tools/make_legal.py`) ;
- l'application les redemande au premier lancement et à chaque changement de `TERMS_VERSION` (`terms.py`), version portable comprise : écran bloquant, acceptation enregistrée dans `config.json` (`terms_accepted_version`, `terms_accepted_at`) et dans `dodotopia.log` ;
- toutes les méthodes de l'API qui agissent (jouer, dessiner, cuisiner, importer, en ligne, mise à jour) sont refusées tant que l'acceptation manque (`TERMS_GATED` dans `app.py`), pas seulement l'interface.

Pour publier une nouvelle version des CGU : modifier `legal/CGU-<lang>.md`, changer la ligne `Version :` et `terms.TERMS_VERSION` (un test vérifie qu'ils correspondent), régénérer les RTF. Relecture par un juriste conseillée avant publication.

## Journal et fichiers de données

`%APPDATA%\DodoTopia\dodotopia.log` (1 Mo × 3, rotation) reçoit tout : démarrage, réglages, arrêts, et **toute exception non rattrapée** (fil principal et fils de fond), avec un toast « Erreur interne » dans l'application. `config.json` et `library.json` sont écrits de façon atomique ; un `config.json` illisible est mis de côté (`config.json.broken-<date>`) et l'application démarre avec les réglages par défaut au lieu de planter.

## Logo

Remplace `assets\logo.png` par ton logo (carré, PNG). `build.bat` en fait l'icône de l'exe et de l'installeur ; la fenêtre l'affiche en haut à gauche.

## Construire l'exe et l'installeur

```
build.bat
```

Produit `dist\DodoTopia\` (exe et fichiers), puis dans `release\` l'installeur `DodoTopia-x.y.z-Setup.exe` et le zip portable. La version est dans `version.py` : change-la avant chaque mise à jour.

Outils : Python 3, PyInstaller et Pillow (installés par le script), Inno Setup 6 (`winget install JRSoftware.InnoSetup`). Variable `PYTHON` pour choisir l'interpréteur (défaut `py`).

Ce qui est livré : `ui/`, `legal/` (CGU), `config.default.json`, `assets/logo.ico`, `assets/logo-256.png` (logo de l'interface généré par `make_icon.py`, le PNG source de 1,2 Mo n'est plus embarqué) et le catalogue des instruments (sans l'archive `source/`).

**Signature Authenticode** (facultative, supprime l'avertissement SmartScreen) : définir `DODO_SIGN_PFX` (chemin du certificat .pfx) et `DODO_SIGN_PWD` avant `build.bat`, ou `DODO_SIGN_CMD` (commande complète qui reçoit le fichier à signer, par exemple Azure Trusted Signing). L'exe et l'installeur sont signés. Sans certificat, rien ne change.

## Antivirus : « Windows a protégé votre ordinateur »

Windows affiche un avertissement, et Defender peut mettre l'exe en quarantaine. Ce n'est pas un virus, mais
ce n'est pas non plus arbitraire ; trois raisons se cumulent.

1. **L'exécutable n'est pas signé.** Sans certificat de signature de code, SmartScreen affiche
   « éditeur inconnu » pour tout fichier qu'il n'a pas encore vu, et chaque nouvelle version repart de zéro.
2. **C'est un binaire PyInstaller.** Le lanceur de PyInstaller est aussi utilisé par des logiciels
   malveillants : les moteurs le reconnaissent et sortent des détections génériques (`Wacatac`, `Sabsik`…).
3. **DodoTopia fait vraiment ce que fait un logiciel espion** : il installe un hook clavier global, injecte
   des frappes, pilote la souris et capture l'écran. Pour une analyse comportementale, c'est indiscernable
   d'un enregistreur de frappes. C'est le facteur aggravant propre à ce projet.

**Ce qui est déjà fait dans le build** : pas de compression UPX (`--noupx`, `upx=False` dans le `.spec` :
un binaire compressé multiplie les détections), mode un dossier plutôt qu'un fichier unique (pas de
décompression dans `%TEMP%` au lancement), et des métadonnées d'éditeur complètes
(`make_version_info.py` → `--version-file`), visibles dans les propriétés du fichier.

**Ce qui réglerait vraiment le problème** : signer l'exe *et* l'installeur avec un certificat de signature
de code. Depuis juin 2023 la clé doit être sur un support matériel ou un HSM, y compris pour un particulier.
Un certificat OV coûte de l'ordre de 200 à 400 € par an et supprime le « éditeur inconnu », la réputation
SmartScreen se construisant ensuite sur quelques centaines de téléchargements ; un certificat EV, de l'ordre
de 400 à 700 € par an, donne cette réputation immédiatement. La signature s'ajouterait dans `build.bat`
(`signtool sign /fd sha256 /tr <horodateur> ...`) sur `DodoTopia.exe` puis sur le `-Setup.exe`.

**En attendant, gratuit et efficace** : signale chaque version en faux positif sur
<https://www.microsoft.com/en-us/wdsi/filesubmission> (compte Microsoft, réponse en un à trois jours,
l'empreinte est mise en liste sûre). Publie aussi le lien VirusTotal de la release pour que les joueurs
puissent vérifier. Un joueur bloqué peut ajouter une exclusion : *Sécurité Windows* > *Protection contre les
virus et menaces* > *Gérer les paramètres* > *Exclusions* > le dossier d'installation de DodoTopia.

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

- **Archive** : `DodoTopia-x.y.z-linux-x64.tar.gz`. Extraction et lancement :
  ```bash
  tar -xzf DodoTopia-x.y.z-linux-x64.tar.gz
  ./DodoTopia/DodoTopia.sh
  ```
  Réglages, musiques et journal (`dodotopia.log`) dans `~/.config/DodoTopia`. Si `tar` répond « not in gzip format » ou s'il faut décompresser deux fois, le téléchargement a été recompressé en route : `bash .tools/check_linux_bundle.sh <archive>` le dit.
- **Installation pour tous les comptes** (facultatif) :
  ```bash
  sudo mkdir -p /opt/dodotopia
  sudo tar -xzf DodoTopia-x.y.z-linux-x64.tar.gz -C /opt/dodotopia --strip-components=1
  sudo ln -s /opt/dodotopia/DodoTopia.sh /usr/local/bin/dodotopia      # DodoTopia.sh suit les liens symboliques
  dodotopia
  ```
- **Liens `dodotopia://`** : au premier lancement, `DodoTopia.sh` écrit `~/.local/share/applications/dodotopia.desktop`. Pour que le navigateur ouvre DodoTopia (une fois) : `xdg-mime default dodotopia.desktop x-scheme-handler/dodotopia`.
- **Prérequis système** (Debian / Ubuntu) :
  ```bash
  sudo apt install libgl1 libegl1 libgl1-mesa-dri libgbm1 libdrm2 libx11-xcb1 libxcb-cursor0 libxkbcommon-x11-0 \
    libnss3 libasound2 libglib2.0-0 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxi6 libxkbfile1 \
    libfontconfig1 libdbus-1-3 libpulse0 xdg-utils
  ```
  Sur **Debian 13 / Ubuntu 24.04** et suivantes, deux paquets ont changé de nom : `libasound2t64` et `libglib2.0-0t64` (à la place de `libasound2` et `libglib2.0-0`). Pour l'écoute dans le logiciel (facultatif) : `sudo apt install fluidsynth fluid-soundfont-gm`.
- **Pourquoi Mesa et libstdc++ ne sont plus dans l'archive** : le pilote graphique (Mesa : `libGL`, `libEGL`, `libgbm`, `libdrm`, `libglapi`, Vulkan, Wayland, et les `libxcb` liées à DRI) et la bibliothèque C++ (`libstdc++`, `libgcc_s`) forment un tout avec la machine qui exécute. L'archive 2.0.0 embarquait ceux d'Ubuntu 22.04 : sur une distribution récente, le pilote Mesa du système réclamait une `libstdc++` plus neuve que celle du bundle (`GLIBCXX_3.4.31`), plus de contexte OpenGL, QtWebEngine plantait ou la fenêtre restait vide. `build.sh` les retire donc après PyInstaller, et `.tools/check_linux_bundle.sh` refuse une archive qui en contient. Qt, ICU, NSS et `libxkbcommon` restent embarqués.
- **Fenêtre vide, écran noir ou plantage au démarrage** : `DODO_SOFTWARE_RENDER=1 ./DodoTopia.sh` force le rendu logiciel (`QT_QUICK_BACKEND=software`, `QT_OPENGL=software`, `LIBGL_ALWAYS_SOFTWARE=1`, `--disable-gpu` pour Chromium). Les erreurs de l'interface sont relayées dans `~/.config/DodoTopia/dodotopia.log` (lignes `UI: …`).
- **Depuis les sources** : `./DodoTopia.sh` (Python 3.10+, `python3-venv`). L'interface utilise GTK/WebKit2 si `python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1` sont installés, sinon Qt (installé automatiquement dans le venv).
- **Construire l'archive** — règle : toujours construire sur la distribution **la plus ancienne** prise en charge (Ubuntu 22.04, glibc 2.35), puis vérifier sur une récente. Un binaire construit sur une distribution récente ne démarre pas sur une ancienne ; l'inverse fonctionne.
  - Windows (Docker Desktop lancé) : `build-linux.bat`. Équivalent à la main :
    ```bash
    docker build -f docker/Dockerfile.linux -t dodotopia-linux .
    docker run --rm -v "%cd%\release:/out" dodotopia-linux
    ```
    L'image compile sous Ubuntu 22.04 avec PyInstaller, contrôle l'archive, vérifie que le binaire démarre, puis **rejoue le tout sur Debian 13** (étape `verify` : paquets d'exécution seulement, `ldd -r` des pilotes Mesa du système avec les bibliothèques du bundle, démarrage réel sans `--disable-gpu`, lien `/usr/local/bin/dodotopia`). Autre cible : `--build-arg VERIFY_IMAGE=ubuntu:24.04`.
  - Linux ou WSL2 : `bash build.sh` (paquets : `python3-venv binutils libpython3.x`), qui termine par le contrôle de l'archive.
  - Vérifier une archive, où qu'elle ait été construite ou téléchargée :
    ```bash
    bash .tools/check_linux_bundle.sh release/DodoTopia-x.y.z-linux-x64.tar.gz          # --list : affiche les .so embarqués
    docker run --rm -v "%cd%:/w" -w /w debian:trixie-slim bash .tools/check_linux_bundle.sh release/DodoTopia-x.y.z-linux-x64.tar.gz
    ```
- Le mode d'envoi « Position physique » suppose la disposition détectée par Wine/Proton ; si les notes sont fausses, passe en « Lettre affichée ».

## Fichiers

- `app.py` : interface graphique (fenêtre WebView2) et API. `terms.py` : CGU (version, texte, acceptation). `logging_setup.py` : journal `dodotopia.log` et capture des exceptions. `i18n.py` + `ui/i18n.js` + `ui/i18n/<lang>.json` : traductions (`.tools/i18n_check.py` vérifie les clés).
- `legal/` : CGU en Markdown (source) et RTF (installeur), `.tools/make_legal.py` pour régénérer.
- `ui/index.html` : la page de l'interface (style Heartopia).
- `core.py` : moteur musique (lecture MIDI, transposition, envoi des touches, écoute, interruption).
- `instruments.py` : catalogue des instruments, dispositions de touches, profils de l'utilisateur, migration des anciens réglages, libellés AZERTY/QWERTY et détection des conflits de touches.
- `assets/instruments/` : catalogue (`catalogue.json`), dispositions (`layouts.json`), crédits des visuels (`CREDITS.md`) et archive de provenance (`source/`, jamais chargée). Images affichées : `ui/instruments/`.
- `draw.py` : moteur dessin (calibrage, lecture de la palette et de la grille à l'écran, peinture à la souris, mode contours + pot de peinture).
- `sync.py` : mode Multi (capture de la sortie audio, détection de la note repère, session meneur / suiveur, test de détection).
- `cook.py` : cuisine en boucle (calibrage, reconnaissance de la bulle et de l'anneau vert à l'écran, boucle cuisiner / feu / récupérer).
- `bot.py` : base commune du dessin et de la cuisine (journal, attente interruptible, souris qui glisse, clic, arrêt si clavier ou souris touchés).
- `platform_io.py` : couche plateforme ; `_win_io.py` (SendInput, `keyboard`, winmm, Pillow) et `_linux_io.py` (X11 : XTEST, XRECORD, mss, rtmidi).
- `config.json` : réglages et profils de touches. Le catalogue des instruments, lui, vient d'`assets/instruments`. Une fois installé, la config utilisée est dans `%APPDATA%\DodoTopia\config.json` (Linux : `~/.config/DodoTopia`).
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
