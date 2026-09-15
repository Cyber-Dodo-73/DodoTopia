# Visuels des instruments — provenance et crédits

Les 19 images servies par le sélecteur d'instruments (`ui/instruments/<instrumentId>.png`) proviennent du
catalogue communautaire **Build Heartopia**. Cette page dit d'où vient chaque fichier, ce que cela autorise
ou non, et comment retirer un visuel sans casser la sélection.

## Source

| | |
|---|---|
| Catalogue | <https://build-heartopia.com/items> |
| Données brutes | <https://build-heartopia.com/data/catalog.json> |
| Date de consultation | 15 septembre 2026 (`retrievedAt` de `catalogue.json`) |
| Empreinte du JSON consulté | `sha256:728f5a79c75317a036c87e991c597b5cd402d5acfebb175dc4bad17b54724405` |

Build Heartopia est un catalogue **communautaire**, pas le site officiel du jeu. Les icônes qu'il publie sont
des extractions d'objets du jeu : l'auteur des visuels reste l'éditeur de Heartopia.

## Ce qui est conservé dans le dépôt

- `assets/instruments/catalogue.json` — une entrée par type. Le champ `imageSourceUrl` garde l'URL exacte du
  fichier d'origine, `catalogItemIds` la liste des objets du catalogue regroupés sous ce type, et
  `sourceUrls` les pages de référence. C'est la trace de provenance de chaque image.
- `assets/instruments/source/` — archive du pack d'origine (`instruments-catalogue.json` avec les 63 entrées
  et variantes, `keyboard-layouts.json`, `Catalogue-et-touches.md`). **Jamais chargée par l'application** :
  elle ne sert qu'à la provenance et aux vérifications. Elle est embarquée dans la construction avec le reste
  d'`assets/` (`DodoTopia.spec`), sans être lue.
- `ui/instruments/*.png` — les 19 images réellement affichées, une par type. PNG RGBA à fond réellement
  transparent, rognés au contenu, au plus 230 px de côté (aucun damier ajouté, aucun cadre repeint).

Les 63 icônes du catalogue brut ne sont **pas** embarquées : une variante esthétique n'est pas un type
d'instrument, et 63 icônes ne prouveraient pas 63 instruments jouables.

## Une image par type

| Type | Identifiant | Fichier embarqué | Variantes regroupées | URL d'origine |
|---|---|---|---:|---|
| Piano | `piano` | `ui/instruments/piano.png` | 9 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrument_piano_1.png?v=21b5c76bf4d5> |
| Flûte à bec | `recorder` | `ui/instruments/recorder.png` | 4 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_recorder_1.png?v=73cd72919767> |
| Xiao en bambou | `xiao` | `ui/instruments/xiao.png` | 1 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_xiao_2.png?v=22ab12e0f2eb> |
| Luth | `lute` | `ui/instruments/lute.png` | 5 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_lute_1.png?v=1cb4920eab79> |
| Basse en bois | `wooden-bass` | `ui/instruments/wooden-bass.png` | 4 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_wbass_1.png?v=e64952c4f4a4> |
| Cornemuse | `bagpipe` | `ui/instruments/bagpipe.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_bagpipes_1.png?v=f65458f71439> |
| Concertina | `concertina` | `ui/instruments/concertina.png` | 4 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_concertina_1.png?v=02e6a6b8368e> |
| Mbira | `mbira` | `ui/instruments/mbira.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_kalimba_1.png?v=c3a339634095> |
| Lyre | `lyre` | `ui/instruments/lyre.png` | 5 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_lila_1.png?v=bd9b92ee0d88> |
| Violon | `violin` | `ui/instruments/violin.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_violin_1.png?v=e0cf93f2ab44> |
| Violoncelle | `cello` | `ui/instruments/cello.png` | 4 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_cello_5.png?v=b5ca152399de> |
| Conga | `conga` | `ui/instruments/conga.png` | 4 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrument_conga_1.png?v=ae0e90c319ca> |
| Cajón | `cajon` | `ui/instruments/cajon.png` | 3 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrument_cajon_2.png?v=63902ac17b40> |
| Xylophone à 8 notes | `xylophone` | `ui/instruments/xylophone.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrument_cylinder_1.png?v=4598d3be261e> |
| Saxophone | `saxophone` | `ui/instruments/saxophone.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_saxophone_1.png?v=c59ada334b0e> |
| Harpe | `harp` | `ui/instruments/harp.png` | 4 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrument_harp_1.png?v=c06a3990eee8> |
| Tambour à langues métalliques | `steel-tongue-drum` | `ui/instruments/steel-tongue-drum.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrument_eterealdrum_1.png?v=037184c5d8a0> |
| Ocarina | `ocarina` | `ui/instruments/ocarina.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_ocarina_1.png?v=94c1d6b4511b> |
| Conque | `conch` | `ui/instruments/conch.png` | 2 | <https://build-heartopia.com/catalog_assets/icons/ui_item_normal_p_instrumenthanded_conch_1.png?v=8ae8a504f573> |

La colonne « Variantes regroupées » compte les objets du catalogue brut rangés sous ce type (couleurs,
finitions, éditions). Ce regroupement est **éditorial**, fait sur les noms : il n'établit pas que toutes les
variantes se commandent exactement pareil dans le jeu (champ `groupingStatus` de `catalogue.json`).

## Droits : ce que cette provenance n'accorde pas

**La présence publique d'une image ne vaut pas licence libre.** Ces icônes sont accessibles sur un site
communautaire ; ni ce site, ni ce dépôt, n'accordent de licence de redistribution. Elles sont utilisées ici
comme **références visuelles** pour reconnaître un instrument dans une liste, à petite taille, sans
modification, et sans être présentées comme une création de DodoTopia.

Conséquences pratiques :

- aucun droit n'est cédé aux utilisateurs de DodoTopia sur ces fichiers ;
- ne pas les réutiliser hors de ce contexte (communication, produits dérivés, autres logiciels) ;
- ne pas les modifier ni les recolorer pour en faire des « variantes » : une image par type, point ;
- ne pas remplacer une image manquante par un instrument approchant (une conque n'est pas un saxophone), ni
  par une image générée censée montrer l'objet réel du jeu ;
- ne pas pointer vers <https://build-heartopia.com/> depuis l'application ni depuis le site pour afficher une
  icône : les fichiers sont servis localement, la sélection fonctionne hors ligne ;
- si l'éditeur du jeu ou l'auteur du catalogue demande le retrait d'un visuel, appliquer la marche à suivre
  ci-dessous. C'est un retrait de fichier, pas une refonte.

## Retirer un visuel

L'identité d'un instrument, ses dispositions et ses touches ne dépendent **pas** de son image : le catalogue
les relie par `instrumentId`. Retirer une image ne retire donc pas l'instrument et ne touche à aucun profil.

1. Supprimer le PNG correspondant dans `ui/instruments/` (par exemple `ui/instruments/harp.png`).
2. Ne rien changer d'autre : ni `catalogue.json`, ni les profils enregistrés dans `config.json`. Le champ
   `image` peut pointer vers un fichier absent, c'est prévu.
3. L'interface affiche alors la **pastille générique de la famille** (Cordes, Vents, Claviers, Percussions)
   à la place de l'image : même taille, même emplacement, la grille ne bouge pas, la carte reste
   sélectionnable et configurable, et l'instrument continue de jouer.
4. Si le site vitrine publie une copie du visuel (`server/static/`), supprimer aussi cette copie.
5. Reconstruire (`build.bat`) pour que la version distribuée ne contienne plus le fichier : `ui/` est
   embarqué tel quel par `DodoTopia.spec`.

Pour remplacer plutôt que retirer : déposer un PNG **au même nom de fichier**, rogné au contenu, à fond
réellement transparent, sans cadre ni damier. Changer l'image ne change jamais l'identifiant ni les touches
de l'instrument.

## Autres sources créditées

Les tables notes → touches ne viennent pas de Build Heartopia mais de projets communautaires ; elles sont
créditées dans `assets/instruments/layouts.json` (champ `sourceUrls`) et rappelées dans `README.md` :

- <https://github.com/Jed556/AutoMidiPlayer/wiki/Support>
- <https://github.com/DonElf/Heartopia-Midi-Player/blob/main/HeartopiaMidiPlayer.cpp>
- <https://github.com/sp0oby/heartopia-midi#heartopia-key-mapping>

Ces tables sont **documentées par une source** ; elles n'ont pas été testées dans le jeu depuis ce dépôt.
Voir `RECETTE-Instruments.md` pour la procédure qui fait passer un profil à « confirmé sur cet ordinateur ».
