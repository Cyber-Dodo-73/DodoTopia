# Catalogue visuel DodoTopia — instruments Heartopia

Recherche du 15 septembre 2026. **19 familles regroupées par nos soins, 63 entrées et variantes dans le catalogue consulté.** Cette liste n’est pas garantie exhaustive pour toutes les versions du jeu. Les traductions françaises restent à comparer aux libellés du jeu.

[Source du catalogue et des icônes](https://build-heartopia.com/items). Les icônes sont fournies comme références visuelles, avec leur provenance dans le JSON.

| Visuel représentatif | Famille | Entrées/variantes | Profil de touches |
|---|---|---:|---|
| ![Piano](images/50001.png) | Piano — Piano | 9 | Piano : 15 / 22 / 37 notes documentés |
| ![Flûte à bec](images/50601.png) | Flûte à bec — Recorder | 4 | 15 notes documentées, 2 ou 3 rangées |
| ![Xiao en bambou](images/50656.png) | Xiao en bambou — Bamboo Xiao | 1 | 15 notes documentées, 2 ou 3 rangées |
| ![Luth](images/50501.png) | Luth — Lute | 5 | 15 notes documentées, 2 ou 3 rangées |
| ![Basse en bois](images/50551.png) | Basse en bois — Wooden Bass | 4 | 15 notes documentées, 2 ou 3 rangées |
| ![Cornemuse](images/50681.png) | Cornemuse — Bagpipe | 2 | 15 notes documentées, 2 ou 3 rangées |
| ![Concertina](images/50651.png) | Concertina — Concertina | 4 | 15 notes documentées, 2 ou 3 rangées |
| ![Mbira](images/50661.png) | Mbira — Mbira | 2 | 15 notes documentées, 2 ou 3 rangées |
| ![Lyre](images/50671.png) | Lyre — Lyre | 5 | 15 notes documentées, 2 ou 3 rangées |
| ![Violon](images/50711.png) | Violon — Violin | 2 | 15 notes documentées, 2 ou 3 rangées |
| ![Violoncelle](images/50691.png) | Violoncelle — Cello | 4 | 15 notes documentées, 2 ou 3 rangées |
| ![Conga](images/50051.png) | Conga — Conga | 4 | 15 notes documentées, 2 ou 3 rangées |
| ![Cajón](images/50071.png) | Cajón — Cajón | 3 | 15 notes documentées, 2 ou 3 rangées |
| ![Xylophone à 8 notes](images/50091.png) | Xylophone à 8 notes — 8-Note Xylophone w/ Stand | 2 | À relever en jeu |
| ![Saxophone](images/50721.png) | Saxophone — Saxophone | 2 | À relever en jeu |
| ![Harpe](images/50121.png) | Harpe — Harp | 4 | À relever en jeu |
| ![Tambour à langues métalliques](images/50101.png) | Tambour à langues métalliques — Steel Tongue Drum | 2 | À relever en jeu |
| ![Ocarina](images/50751.png) | Ocarina — Ocarina | 2 | À relever en jeu |
| ![Conque](images/50741.png) | Conque — Conch | 2 | À relever en jeu |

Les profils documentés proviennent de [AutoMidiPlayer](https://github.com/Jed556/AutoMidiPlayer/wiki/Support). Pour la conga et le cajón, ce logiciel fournit une correspondance MIDI ; cela ne prouve pas que leurs frappes produisent les hauteurs mélodiques indiquées. Ne pas les traiter automatiquement comme un piano.

Les skins d’une famille sont regroupés pour la navigation ; leur équivalence fonctionnelle reste à vérifier. Les 63 icônes individuelles se trouvent dans `images/`, les noms et liens dans `instruments-catalogue.json`.

## Tables notes → touches

Référence QWERTY US, sans déduction d’un mapping universel. Les numéros MIDI servent de référence stable. Les touches changent avec la disposition musicale choisie dans le jeu.

### diatonic-15-2row

| Note | MIDI | Touche QWERTY |
|---|---:|---|
| Do4 (C4) | 60 | `A` |
| Ré4 (D4) | 62 | `S` |
| Mi4 (E4) | 64 | `D` |
| Fa4 (F4) | 65 | `F` |
| Sol4 (G4) | 67 | `G` |
| La4 (A4) | 69 | `H` |
| Si4 (B4) | 71 | `J` |
| Do5 (C5) | 72 | `Q` |
| Ré5 (D5) | 74 | `W` |
| Mi5 (E5) | 76 | `E` |
| Fa5 (F5) | 77 | `R` |
| Sol5 (G5) | 79 | `T` |
| La5 (A5) | 81 | `Y` |
| Si5 (B5) | 83 | `U` |
| Do6 (C6) | 84 | `I` |

Source : [référence](https://github.com/DonElf/Heartopia-Midi-Player/blob/main/HeartopiaMidiPlayer.cpp).

### diatonic-15-3row

| Note | MIDI | Touche QWERTY |
|---|---:|---|
| Do4 (C4) | 60 | `Y` |
| Ré4 (D4) | 62 | `U` |
| Mi4 (E4) | 64 | `I` |
| Fa4 (F4) | 65 | `O` |
| Sol4 (G4) | 67 | `P` |
| La4 (A4) | 69 | `H` |
| Si4 (B4) | 71 | `J` |
| Do5 (C5) | 72 | `K` |
| Ré5 (D5) | 74 | `L` |
| Mi5 (E5) | 76 | `;` |
| Fa5 (F5) | 77 | `N` |
| Sol5 (G5) | 79 | `M` |
| La5 (A5) | 81 | `,` |
| Si5 (B5) | 83 | `.` |
| Do6 (C6) | 84 | `/` |

Source : [référence](https://github.com/Jed556/AutoMidiPlayer/wiki/Support).

### piano-diatonic-22

| Note | MIDI | Touche QWERTY |
|---|---:|---|
| Do3 (C3) | 48 | `Z` |
| Ré3 (D3) | 50 | `X` |
| Mi3 (E3) | 52 | `C` |
| Fa3 (F3) | 53 | `V` |
| Sol3 (G3) | 55 | `B` |
| La3 (A3) | 57 | `N` |
| Si3 (B3) | 59 | `M` |
| Do4 (C4) | 60 | `A` |
| Ré4 (D4) | 62 | `S` |
| Mi4 (E4) | 64 | `D` |
| Fa4 (F4) | 65 | `F` |
| Sol4 (G4) | 67 | `G` |
| La4 (A4) | 69 | `H` |
| Si4 (B4) | 71 | `J` |
| Do5 (C5) | 72 | `Q` |
| Ré5 (D5) | 74 | `W` |
| Mi5 (E5) | 76 | `E` |
| Fa5 (F5) | 77 | `R` |
| Sol5 (G5) | 79 | `T` |
| La5 (A5) | 81 | `Y` |
| Si5 (B5) | 83 | `U` |
| Do6 (C6) | 84 | `I` |

Source : [référence](https://github.com/Jed556/AutoMidiPlayer/wiki/Support).

### piano-chromatic-37

| Note | MIDI | Touche QWERTY |
|---|---:|---|
| Do3 (C3) | 48 | `,` |
| Do♯3 (C#3) | 49 | `L` |
| Ré3 (D3) | 50 | `.` |
| Ré♯3 (D#3) | 51 | `;` |
| Mi3 (E3) | 52 | `/` |
| Fa3 (F3) | 53 | `O` |
| Fa♯3 (F#3) | 54 | `0` |
| Sol3 (G3) | 55 | `P` |
| Sol♯3 (G#3) | 56 | `-` |
| La3 (A3) | 57 | `[` |
| La♯3 (A#3) | 58 | `=` |
| Si3 (B3) | 59 | `]` |
| Do4 (C4) | 60 | `Z` |
| Do♯4 (C#4) | 61 | `S` |
| Ré4 (D4) | 62 | `X` |
| Ré♯4 (D#4) | 63 | `D` |
| Mi4 (E4) | 64 | `C` |
| Fa4 (F4) | 65 | `V` |
| Fa♯4 (F#4) | 66 | `G` |
| Sol4 (G4) | 67 | `B` |
| Sol♯4 (G#4) | 68 | `H` |
| La4 (A4) | 69 | `N` |
| La♯4 (A#4) | 70 | `J` |
| Si4 (B4) | 71 | `M` |
| Do5 (C5) | 72 | `Q` |
| Do♯5 (C#5) | 73 | `2` |
| Ré5 (D5) | 74 | `W` |
| Ré♯5 (D#5) | 75 | `3` |
| Mi5 (E5) | 76 | `E` |
| Fa5 (F5) | 77 | `R` |
| Fa♯5 (F#5) | 78 | `5` |
| Sol5 (G5) | 79 | `T` |
| Sol♯5 (G#5) | 80 | `6` |
| La5 (A5) | 81 | `Y` |
| La♯5 (A#5) | 82 | `7` |
| Si5 (B5) | 83 | `U` |
| Do6 (C6) | 84 | `I` |

Source : [référence](https://github.com/DonElf/Heartopia-Midi-Player/blob/main/HeartopiaMidiPlayer.cpp), [référence](https://github.com/sp0oby/heartopia-midi#heartopia-key-mapping).
