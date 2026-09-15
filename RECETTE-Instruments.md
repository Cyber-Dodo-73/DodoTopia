# Recette des instruments — passer de « documenté » à « confirmé »

Cette procédure se fait **dans Heartopia**, à la main, devant l'écran. Elle n'a pas été exécutée depuis ce
dépôt : aucun profil livré n'a été entendu dans le jeu. Les tables de touches embarquées viennent de projets
communautaires (`assets/instruments/layouts.json`, champ `sourceUrls`) ; ce sont des **hypothèses
documentées**, pas des mesures.

Le but : pour chaque instrument, établir sur **cet ordinateur** que la touche envoyée par DodoTopia produit
bien la note attendue dans le jeu, et le consigner.

## 1. Les cinq statuts

| Statut interne | Affiché dans DodoTopia | Ce que ça veut dire | Jouable |
|---|---|---|---|
| `unknown` | « Touches à configurer » | aucune table connue pour ce type | non |
| `documented` | « Profil documenté · à vérifier » | une source communautaire donne une table ; personne ne l'a vérifiée ici | oui (sauf percussions) |
| `custom` | « Touches personnalisées · à vérifier » | table saisie ou modifiée sur cet ordinateur, pas encore testée | oui |
| `quick-tested` | « Test rapide réussi · vérification partielle » | quelques touches vérifiées dans le jeu (échantillon) | oui |
| `confirmed` | « Confirmé sur cet ordinateur » | **toutes** les associations ont été vérifiées une par une | oui |

Un test de trois notes ne vaut jamais validation de 15, 22 ou 37 touches : il donne `quick-tested`. Seule la
section 5 donne `confirmed`.

Cas des percussions (`conga`, `cajon`) : tant que le statut vaut `documented`, le profil est **candidat** et
l'instrument n'est pas jouable. Voir la section 7.

## 2. Où vivent les profils

- Version installée : `%APPDATA%\DodoTopia\config.json` (Linux : `~/.config/DodoTopia/config.json`).
- En mode source : `config.json` à la racine du dépôt (non versionné).

Les profils sont dans la clé `instruments`, un objet par identifiant de type
(`{"layoutId": …, "bindings": …, "verificationStatus": …, "verifiedAt": …}`). L'instrument actif est dans
`instrument`, la disposition du clavier physique dans `keyboard_layout`.

**Copie le fichier avant de commencer** (`config.json` → `config.json.bak`). La recette ne casse rien, mais
une sauvegarde évite de recommencer un relevé de 37 touches.

## 3. Avant de commencer

1. Lance Heartopia et **équipe l'instrument dans le jeu**. Choisir un instrument dans DodoTopia ne l'équipe
   pas dans Heartopia : ce sont deux choses séparées, et DodoTopia ne sait pas le faire à ta place.
2. Mets le jeu en **plein écran fenêtré** si possible : basculer entre les deux fenêtres est plus rapide et
   plus sûr qu'en plein écran exclusif.
3. Vérifie que **F7** (arrêt) fonctionne : c'est la sortie de secours de toute cette procédure. F6 lance et
   met en pause, F12 passe à l'instrument suivant.
4. Ferme les logiciels qui capturent le clavier (macros, overlays, autres joueurs MIDI).
5. Coupe la musique du jeu ou baisse-la : tu dois entendre les notes de l'instrument, pas la bande-son.
6. Repère le clavier de l'instrument **affiché dans le jeu** : combien de touches, combien de rangées, et si
   des altérations (touches noires) existent. C'est ce qui départage les quatre dispositions.
7. Si Heartopia propose un réglage de disposition pour cet instrument, mets-le sur celle que tu vas tester.
   **L'emplacement de ce réglage dans les menus du jeu n'est pas confirmé** : ce document ne donne pas de
   chemin de menus inventé. Repère-le toi-même, puis note-le dans ton suivi (section 9).
8. Fais la vérification clavier de la section 4 **une fois**, avant le premier instrument.

## 4. Étape préalable — le clavier physique

DodoTopia envoie une **position** de touche, pas une lettre. Les noms internes (`a`, `;`, `2`…) désignent
les positions du clavier QWERTY US. Sur un clavier AZERTY, la position `q` est la touche marquée **A**.

1. Ouvre le panneau « Voir les touches » de l'instrument courant.
2. Règle la disposition sur **AZERTY** ou **QWERTY** selon ton clavier réel. En « Auto », DodoTopia se fie à
   la disposition déclarée par Windows ; si elle est ambiguë, il retombe sur QWERTY — choisis alors
   explicitement.
3. Vérifie que les libellés affichés correspondent à ce qui est **imprimé sur tes touches**. Si la note Do4
   du profil 15 notes (2 rangées) t'affiche `Q` et que ta touche porte bien Q, le libellé est bon.
4. Note le réglage **Envoi des touches** (Réglages › Musique et audio, réglage avancé) : `Position`
   (défaut, `input_mode: "scancode"`) ou `Lettre affichée` (`input_mode: "vk"`). Il change ce qui part
   vers le jeu, donc il fait partie de ce que tu valides : si tu en changes plus tard, refais la recette.

Ce que cette étape **ne prouve pas** : taper correctement dans le Bloc-notes ne prouve rien pour Heartopia.
Le jeu peut lire les entrées autrement qu'un champ de texte. Seule la section 5 tranche.

La section 8 liste ce qui reste spécifiquement à vérifier en AZERTY (chiffres et ponctuation).

## 5. Recette d'un instrument au profil documenté

Concerne les 13 types qui ont déjà une table : piano, flûte à bec, xiao en bambou, luth, basse en bois,
cornemuse, concertina, mbira, lyre, violon, violoncelle — et, avec la réserve de la section 7, conga et
cajón.

### 5.1 Choisir la bonne disposition

Compare ce que tu vois dans le jeu aux quatre dispositions (annexe, section 10) :

- **15 notes** : Do4 → Do6, gamme de do majeur, aucune altération. Deux variantes qui **n'ont pas les mêmes
  touches** : 2 rangées (`a s d f g h j` puis `q w e r t y u i`) ou 3 rangées (`y u i o p`, `h j k l ;`,
  `n m , . /`). Le nombre de rangées affiché dans le jeu tranche ; en cas de doute, teste une touche de la
  première rangée : `A` (position `a`) sur la variante 2 rangées, `Y` (position `y`) sur la variante 3.
- **22 notes** : Do3 → Do6, gamme de do majeur, trois rangées.
- **37 notes** : Do3 → Do6, **toutes les altérations**, trois rangées. C'est la seule disposition chromatique.

Si le jeu montre un clavier qui ne correspond à aucune des quatre, passe à la section 6 (relevé complet) :
n'essaie pas de faire entrer l'instrument dans une table voisine.

### 5.2 Test rapide (donne `quick-tested`)

1. Dans la fiche de l'instrument, lance l'assistant (« Configurer les touches ») et choisis le test.
2. L'assistant annonce la note attendue et la touche attendue, puis laisse un délai pour revenir dans le
   jeu ; il réduit sa fenêtre comme le test de la synchronisation par le son. **Trois touches au maximum**
   sont envoyées.
3. Reviens dans Heartopia avant la fin du compte à rebours, instrument ouvert, et **écoute**.
4. Réponds : les notes entendues sont-elles celles annoncées ? En cas de doute, refais le test : une note
   ratée parce que la fenêtre n'avait pas la main n'est pas une erreur de profil.
5. Si oui, le profil passe à « Test rapide réussi · vérification partielle ». C'est suffisant pour jouer,
   **pas** pour déclarer l'instrument vérifié.

Si une note est fausse : note laquelle et ce que tu as entendu à la place. Deux cas typiques —
*toutes les notes sont décalées du même intervalle* (mauvaise octave ou mauvaise disposition choisie dans le
jeu), ou *une seule note est fausse* (une position mal associée : corrige-la en section 5.3).

### 5.3 Validation intégrale (donne `confirmed`)

C'est la seule procédure qui autorise le statut « Confirmé sur cet ordinateur ». Elle se fait
**association par association**, sans exception : 15, 22 ou 37 vérifications.

1. Ouvre le panneau « Voir les touches » et garde-le visible : il donne, pour chaque note, le nom français,
   le nom international, le numéro MIDI et la touche à presser sur ton clavier.
2. Passe dans Heartopia, instrument ouvert.
3. **Toi-même, au clavier** (pas d'envoi automatique), presse les touches dans l'ordre de la table, de la
   plus grave à la plus aiguë, une par une, en écoutant.
4. Pour chaque note, vérifie deux choses : le jeu réagit (la touche est bien lue) et la hauteur monte d'un
   degré à chaque fois, sans trou ni répétition. Une touche qui ne déclenche rien est aussi importante
   qu'une touche qui joue faux.
5. Coche au fur et à mesure dans la table de suivi (section 9). Note toute anomalie avec sa note MIDI.
6. Refais ensuite le même parcours **par l'assistant**, en mode validation intégrale : bouton
   « Validation intégrale… » dans la fiche de l'instrument (sélecteur « Changer ») ou dans le panneau
   « Voir les touches ». L'assistant envoie alors les touches **par groupes de trois**, en reprenant à
   chaque passage là où tu t'es arrêté ; l'étape « Test » affiche le compte des associations déjà
   vérifiées. Recommence jusqu'à ce que le compteur atteigne le total. C'est ce passage-là qui teste la
   chaîne complète (envoi des touches, position, fenêtre au premier plan), et c'est lui qui compte.
   Le bouton « Arrêter le test » et le raccourci d'arrêt (F7) coupent l'envoi à tout moment.
7. Aucune anomalie sur l'ensemble du parcours → enregistre : statut « Confirmé sur cet ordinateur »,
   avec la date. Ce statut n'est écrit que si **toutes** les associations ont été vérifiées ; tant qu'il en
   reste une, l'assistant annonce « Test rapide réussi · vérification partielle », et c'est ce statut-là
   qui sera enregistré. Une seule anomalie non corrigée → reste en « Test rapide » ou « personnalisé », et
   note précisément laquelle.

Corriger une association : dans l'assistant, sélectionne la ligne de la note, appuie sur la touche voulue,
elle est capturée telle quelle (la capture n'envoie rien au jeu et ne déclenche aucun raccourci global).
Les conflits sont signalés à côté de la ligne : doublon de touche, position non injectable, collision avec
un raccourci. **Une collision avec l'arrêt (F7) ou la lecture (F6) bloque l'enregistrement** : change la
touche de la note, jamais le raccourci d'arrêt.

Dès qu'une seule touche diffère de la table documentée, le profil devient « personnalisé » : c'est normal,
et c'est l'état correct — tes touches sont conservées telles quelles, elles ne seront jamais réécrites par
la table communautaire.

### 5.4 Contrôle final avec un morceau

1. Choisis un morceau connu, court, dans le registre de l'instrument.
2. Regarde le bandeau de compatibilité : notes hors registre, altérations absentes, pistes de percussion.
   Sur une disposition diatonique (15 ou 22 notes), il est normal que des dièses manquent.
3. Lance dans le jeu et écoute la mélodie entière : c'est le seul contrôle qui teste les notes tenues, les
   notes répétées et les accords.
4. Arrête avec F7 et vérifie qu'**aucune touche ne reste enfoncée** (le personnage ne doit pas continuer à
   jouer, et le clavier doit répondre normalement).

## 6. Relever un instrument dont les touches sont inconnues

Six types n'ont **aucune** table documentée. Leur statut est « Touches à configurer », ils ne peuvent pas
lancer un morceau, et ils n'héritent jamais du profil du piano.

| Type | Identifiant | À relever |
|---|---|---|
| Xylophone à 8 notes | `xylophone` | nombre réel de notes, registre, ordre des touches. Le nom « 8 notes » ne prouve ni 8 touches ni un registre |
| Saxophone | `saxophone` | tout : nombre de notes, altérations, registre |
| Harpe | `harp` | tout ; vérifier si plusieurs rangées coexistent |
| Tambour à langues métalliques | `steel-tongue-drum` | tout ; gamme possiblement non diatonique (pentatonique ?) |
| Ocarina | `ocarina` | tout ; registre probablement court |
| Conque | `conch` | tout ; vérifier s'il produit plus d'une hauteur |

Procédure, instrument ouvert dans le jeu :

1. **Compte** les emplacements de notes affichés par le jeu et leur découpage en rangées. Note-le avant
   toute manipulation.
2. **Balaye le clavier** : presse une à une les touches que le jeu met en avant, dans l'ordre affiché, et
   note quelle position produit quelle case. Si le jeu n'affiche pas de touche, essaie les positions des
   dispositions connues (rangée du haut, rangée du milieu…) et note celles qui répondent.
3. **Détermine les hauteurs**. Deux méthodes, dans cet ordre de fiabilité :
   - comparer à l'oreille avec la préécoute de DodoTopia (« Préécouter sur cet ordinateur ») en jouant la
     même note supposée : si ça sonne à l'unisson, la hauteur est la bonne ;
   - utiliser un accordeur (application de téléphone) devant le haut-parleur, note par note.
   Ne suppose pas que la note la plus grave est un Do4, et ne déduis pas le registre du nom de l'instrument.
4. **Saisis** les associations dans l'assistant : pour chaque note trouvée, sélectionne la ligne et appuie
   sur la touche. Laisse vides les notes que tu n'as pas identifiées — un profil partiel vaut mieux qu'un
   profil inventé.
5. **Enregistre** : le profil devient « Touches personnalisées · à vérifier ».
6. Applique ensuite la section 5.2 puis 5.3 (test rapide, puis validation intégrale) pour aller jusqu'à
   « Confirmé sur cet ordinateur ».
7. Consigne dans ton suivi : nombre de notes, note la plus grave, note la plus aiguë, altérations présentes
   ou non, rangées. Ces informations, une fois vérifiées, peuvent devenir une nouvelle disposition dans
   `assets/instruments/layouts.json`. Tant qu'elles viennent d'une seule installation, elles restent un
   profil local.

Si le relevé montre une disposition **identique** à l'une des quatre connues, dis-le : l'instrument gagne
alors `supportedLayoutIds` et un statut documenté, sans invention.

## 7. Cas particulier : conga et cajón

Les sources communautaires listent conga et cajón avec une correspondance MIDI de 15 notes. **Cela ne prouve
pas** que ces instruments produisent une gamme : ce sont des percussions, et une frappe n'est pas une
hauteur. DodoTopia les traite donc comme *candidats* : au statut « Profil documenté », ils ne sont **pas**
jouables, et l'assistant demande un test adapté.

Procédure :

1. Ouvre la conga (ou le cajón) dans le jeu.
2. Presse une à une les positions du profil candidat, dans l'ordre.
3. Pour chaque touche, l'assistant ne demande pas « as-tu entendu un Do ? » mais **quelle frappe** a été
   produite : par exemple grave (centre), claire (bord), claquée, étouffée, ou aucune. Réponds ce que tu
   entends réellement ; « je ne sais pas » est une réponse acceptable, et elle laisse la ligne non validée.
4. Note combien de sons **distincts** l'instrument produit. Si trois touches donnent le même son, ce sont
   trois positions pour une seule frappe : l'instrument n'a pas 15 sons.
5. Enregistre : le profil passe en « Test rapide réussi » ou « personnalisé » selon ce que tu as réellement
   fait. Il devient jouable — en sachant ce qu'il joue.

À ne pas faire : déclarer la conga mélodiquement équivalente au piano, ou lui envoyer une mélodie en
espérant une gamme. Tant qu'une prise en charge des pistes rythmiques n'existe pas, une mélodie jouée sur
une percussion reste une mélodie transformée en frappes, et le bandeau de compatibilité doit le dire.

## 8. AZERTY : ce qui reste à vérifier séparément

Deux choses différentes, à tester séparément :

- **Le libellé affiché** — ce que DodoTopia écrit sur son clavier et dans le panneau « Voir les touches ».
  Il vient d'une table de correspondance (position QWERTY US → légende imprimée sur un clavier français).
  Il se vérifie en regardant ton clavier.
- **L'événement réellement injecté** — ce qui part vers le jeu. Il ne se vérifie que dans Heartopia.

Un libellé correct ne prouve pas que l'événement est correct, et l'inverse est vrai aussi.

### 8.1 Les positions à risque

Les lettres posent rarement problème. Ce sont les **chiffres** et la **ponctuation** qui décident, et ils
n'apparaissent que dans deux dispositions.

Profil 15 notes, 3 rangées — 4 positions non alphabétiques :

| Note | MIDI | Position (QWERTY) | Touche AZERTY à presser |
|---|---:|---|---|
| Mi5 | 76 | `;` | M |
| La5 | 81 | `,` | ; |
| Si5 | 83 | `.` | : |
| Do6 | 84 | `/` | ! |

Profil 37 notes — 14 positions non alphabétiques :

| Note | MIDI | Position (QWERTY) | Touche AZERTY à presser |
|---|---:|---|---|
| Do3 | 48 | `,` | ; |
| Ré3 | 50 | `.` | : |
| Ré♯3 | 51 | `;` | M |
| Mi3 | 52 | `/` | ! |
| Fa♯3 | 54 | `0` | à |
| Sol♯3 | 56 | `-` | ) |
| La3 | 57 | `[` | ^ |
| La♯3 | 58 | `=` | = |
| Si3 | 59 | `]` | $ |
| Do♯5 | 73 | `2` | é |
| Ré♯5 | 75 | `3` | " |
| Fa♯5 | 78 | `5` | ( |
| Sol♯5 | 80 | `6` | - |
| La♯5 | 82 | `7` | è |

### 8.2 Le test

Instrument ouvert dans le jeu, profil 37 notes (c'est celui qui couvre tous les cas) :

1. Presse toi-même les 14 touches ci-dessus, dans l'ordre, et vérifie que chacune joue la note annoncée.
2. Recommence par l'assistant, par groupes de trois, pour tester l'envoi automatique.
3. Si les lettres marchent mais que **les chiffres jouent faux ou ne jouent rien**, c'est le symptôme
   caractéristique d'un problème d'envoi : passe de `Position` à `Lettre affichée` (ou l'inverse) dans les
   Réglages, puis refais ces 14 touches.

### 8.3 « Position » ou « Lettre affichée »

- **Position** (`input_mode: "scancode"`, défaut) : c'est le code matériel de la touche qui part.
  La disposition du clavier ne change rien à ce que reçoit le jeu ; seul le libellé affiché change. Aucun
  Maj n'est nécessaire.
- **Lettre affichée** (`input_mode: "vk"`) : c'est le code virtuel qui part, et il est interprété selon la
  disposition active. Sur un clavier français, la rangée des chiffres demande alors Maj pour produire un
  chiffre, et la ponctuation ne tombe pas au même endroit. DodoTopia **avertit** de ce cas, il n'injecte
  jamais un Maj de son propre chef.

Ce qui reste inconnu et qu'il faut trancher par l'observation : **comment Heartopia lit les entrées**. Ce
document ne le suppose pas. Consigne ce qui a marché sur ton installation, avec le réglage d'envoi utilisé.

Changer la disposition de clavier (ou l'envoi des touches) après coup **invalide** les conclusions : les profils
« confirmé » et « test rapide » repassent à « personnalisé », tes touches sont conservées, et la recette est
à refaire. C'est voulu.

## 9. Tableau de suivi

À remplir au fur et à mesure. État de départ tel que livré : aucun profil confirmé, six profils absents.

| Instrument | Identifiant | Statut livré | Disposition testée | Statut atteint | Date | Remarques |
|---|---|---|---|---|---|---|
| Piano | `piano` | documenté (37 notes) | | | | |
| Flûte à bec | `recorder` | documenté (15 notes) | | | | |
| Xiao en bambou | `xiao` | documenté (15 notes) | | | | |
| Luth | `lute` | documenté (15 notes) | | | | |
| Basse en bois | `wooden-bass` | documenté (15 notes) | | | | |
| Cornemuse | `bagpipe` | documenté (15 notes) | | | | |
| Concertina | `concertina` | documenté (15 notes) | | | | |
| Mbira | `mbira` | documenté (15 notes) | | | | |
| Lyre | `lyre` | documenté (15 notes) | | | | |
| Violon | `violin` | documenté (15 notes) | | | | |
| Violoncelle | `cello` | documenté (15 notes) | | | | |
| Conga | `conga` | candidat (percussion) | | | | section 7 |
| Cajón | `cajon` | candidat (percussion) | | | | section 7 |
| Xylophone à 8 notes | `xylophone` | **à relever** | | | | section 6 |
| Saxophone | `saxophone` | **à relever** | | | | section 6 |
| Harpe | `harp` | **à relever** | | | | section 6 |
| Tambour à langues métalliques | `steel-tongue-drum` | **à relever** | | | | section 6 |
| Ocarina | `ocarina` | **à relever** | | | | section 6 |
| Conque | `conch` | **à relever** | | | | section 6 |

Pour partager un profil vérifié : utilise l'export de profil de la fiche (JSON validé contre le schéma) et
joins tes notes de relevé. Un profil importé n'est jamais exécuté : ses identifiants et ses touches sont
filtrés avant d'être appliqués.

## 10. Annexe — les quatre dispositions

Positions QWERTY US telles que DodoTopia les envoie, rangée par rangée, et les touches correspondantes sur
un clavier AZERTY. Les tables complètes note par note sont dans le panneau « Voir les touches » et dans
`assets/instruments/source/Catalogue-et-touches.md`.

**15 notes, 2 rangées** (`diatonic-15-2row`) — Do4 → Do6, do majeur, transposition automatique par tonalité.

| Rangée | Notes | Positions | AZERTY |
|---|---|---|---|
| 1 | Do4 → Si4 | `a s d f g h j` | Q S D F G H J |
| 2 | Do5 → Do6 | `q w e r t y u i` | A Z E R T Y U I |

**15 notes, 3 rangées** (`diatonic-15-3row`) — mêmes notes, **touches différentes**.

| Rangée | Notes | Positions | AZERTY |
|---|---|---|---|
| 1 | Do4 → Sol4 | `y u i o p` | Y U I O P |
| 2 | La4 → Mi5 | `h j k l ;` | H J K L M |
| 3 | Fa5 → Do6 | `n m , . /` | N , ; : ! |

**22 notes** (`piano-diatonic-22`) — Do3 → Do6, do majeur, trois rangées.

| Rangée | Notes | Positions | AZERTY |
|---|---|---|---|
| 1 | Do3 → Si3 | `z x c v b n m` | W X C V B N , |
| 2 | Do4 → Si4 | `a s d f g h j` | Q S D F G H J |
| 3 | Do5 → Do6 | `q w e r t y u i` | A Z E R T Y U I |

**37 notes** (`piano-chromatic-37`) — Do3 → Do6, toutes les altérations, transposition automatique par
octave. Seule disposition chromatique.

| Rangée | Notes | Positions | AZERTY |
|---|---|---|---|
| 1 | Do3 → Si3 | `, l . ; / o 0 p - [ = ]` | ; L : M ! O à P ) ^ = $ |
| 2 | Do4 → Si4 | `z s x d c v g b h n j m` | W S X D C V G B H N J , |
| 3 | Do5 → Do6 | `q 2 w 3 e r 5 t 6 y 7 u i` | A é Z " E R ( T - Y è U I |

Convention d'affichage : **Do4 = C4 = MIDI 60**. Un logiciel qui numérote les octaves autrement n'est pas
une raison de décaler la musique.

## 11. Quand refaire la recette

- **Mise à jour de Heartopia** qui touche aux instruments ou aux claviers en jeu : un profil confirmé sur
  une version du jeu ne l'est plus sur la suivante. Note la version du jeu dans ton suivi.
- **Changement de clavier physique** ou de disposition système.
- **Changement de l'envoi des touches** (`Position` ↔ `Lettre affichée`).
- **Changement de la disposition musicale** choisie dans le jeu pour cet instrument.
- Installation sur un autre ordinateur : « Confirmé sur cet ordinateur » ne se transporte pas. Importe le
  profil, puis refais au minimum le test rapide de la section 5.2.
