# DodoTopia Mobile, étape 1 : résultats

L'appli de test est écrite et compile. Les mesures sur un vrai téléphone, dans Heartopia, restent à faire : c'est la partie « À mesurer par Dodo » ci-dessous. Rien de l'étape 2 n'est commencé.

## Installer

```
cd mobile
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`assembleRelease` donne un APK signé avec la clé debug (provisoire). Il faut `mobile/local.properties` avec `sdk.dir=...` (Android Studio le crée tout seul).

Si l'APK est installé autrement que par `adb` ou Android Studio (téléchargé, envoyé par message), Android 13+ grise l'interrupteur du service d'accessibilité (« paramètre restreint »). Il faut alors : Infos de l'appli, menu ⋮, « Autoriser les paramètres restreints ». Le bouton « Infos de l'appli » de l'écran d'accueil y mène. À prévoir dans l'écran d'autorisations de l'étape 2, puisque la distribution se fera par APK téléchargé.

## Ce qui a été vérifié sur émulateur (Android 16, API 36)

Ces points valident le code, pas le comportement du jeu ni la latence d'un vrai téléphone.

- Le service se connecte, la bulle apparaît, se déplace et se range au bord, en portrait et en paysage.
- Panneau, viseur, repères numérotés : le repère enregistré correspond au centre du viseur à 2 px près.
- Le métronome envoie bien les gestes (ils ont cliqué sur les boutons qui se trouvaient dessous), en simple et en accord. Résumé et détail par appui écrits dans le journal.
- Arrêt en cours de mesure par appui sur la bulle.
- « Capture par le service » : 175 ms, plus 563 ms pour la copie en mémoire lisible, sur l'émulateur.
- Lint : 0 erreur.

Non vérifié à l'exécution, faute d'avoir pu le faire tourner :

- **Le test capture écran + son (`CaptureService`)**. Le code compile et suit l'ordre exigé par Android 14+, mais il n'a jamais tourné. S'il plante, le message d'erreur s'affiche dans la carte « Capture écran + son » et dans le journal.
- **L'arrêt par volume bas**. Une touche simulée par `adb` ne passe pas par le filtre d'accessibilité, donc impossible à essayer sans vraie touche. L'arrêt passe par le même chemin que l'appui sur la bulle, qui fonctionne.

## À mesurer par Dodo

Avant de commencer : fermer les applis en arrière-plan, mettre le son du jeu assez fort, ouvrir Heartopia en paysage avec un instrument ouvert.

Attention : un geste atterrit sur ce qui se trouve à cet endroit de l'écran, quelle que soit l'appli. Ne lancer le métronome que par-dessus le jeu (sur l'émulateur, des appuis tombés sur les réglages ont ouvert la boîte « Désinstaller »). Les repères sont effacés quand l'écran tourne : les placer une fois le jeu en paysage.

### 1. Les appuis sont-ils pris par le jeu ?

1. Toucher la bulle, « Placer un repère », amener le viseur sur une touche de l'instrument, « Valider ». Recommencer sur 3 à 5 touches, puis « Terminer ».
2. Laisser 120 bpm, 16 appuis, 40 ms, « Accord » décoché. « Lancer le métronome ».
3. Écouter : chaque appui doit faire sonner une note.

- Résultat : …
- Si rien ne sonne à 40 ms, réessayer à 80 puis 120 ms et noter la durée minimale qui marche : …
- Si rien ne sonne du tout : Shizuku dès l'étape 2.

### 2. Latence à 180 bpm

Régler 180 bpm, 64 appuis, « Accord » décoché. Faire trois mesures et recopier le résumé (ou partager le journal).

| Mesure | Retard d'envoi p95 | Délai système p95 | Gigue | Annulés / refusés |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

Seuils : délai système p95 < 60 ms et retard d'envoi p95 < 15 ms, c'est bon. Entre 60 et 120 ms, jouable avec compensation. Au-delà, ou gigue > 40 ms : Shizuku. Le résumé affiche ce verdict, mais c'est l'oreille qui tranche : les notes sont-elles régulières ?

Refaire une mesure à 240 bpm pour voir si des gestes sont annulés : …

Le premier appui d'une mesure est écarté des statistiques (il paie la mise en route du système : 160 ms sur l'émulateur, 2 ms ensuite). Il reste visible dans le détail du journal.

### 3. Accord de 3 notes

Garder exactement 3 repères sur 3 touches, cocher « Accord », 120 bpm, 16 appuis.

- Les trois notes sonnent-elles ensemble ? …
- Avec plus de repères (5, 10) ? …

### 4. Arrêt d'urgence

Pendant une mesure de 64 appuis :

- Volume bas arrête la mesure, sans changer le volume : …
- Appui sur la bulle (devenue rouge) arrête la mesure : …
- Hors mesure, volume bas règle bien le volume : …

### 5. Capture écran + son

Dans DodoTopia, « Lancer le test capture écran + son », accepter (choisir « Tout l'écran », pas « Une seule appli »), revenir sur Heartopia dans les 6 secondes, bouger la caméra sans arrêt et jouer des notes pendant 3 secondes. Revenir lire le résultat.

- Images par seconde (attendu : au moins 20) : …
- Luminosité centre / moyenne (0 et 0 = jeu protégé contre la capture) : …
- Son, pic et RMS (attendu : pic > 50) : …

Si le son reste à zéro alors qu'une note sonnait, la synchronisation par le son est hors périmètre sur mobile.

### 6. Capture par le service

Par-dessus le jeu : bulle, « Capture par le service ».

- Fonctionne ? Temps de capture et de copie : …
- Luminosité : …

Au-delà de 300 ms au total, ce secours est trop lent pour la cuisine.

### 7. Envoyer le journal

Dans DodoTopia, « Partager le journal » : le fichier `spike.log` contient toutes les mesures, appui par appui.

## Points à trancher après les mesures

- **Notes qui se chevauchent.** `dispatchGesture` ne joue qu'un geste à la fois : un geste envoyé pendant qu'un autre est en cours annule le premier. Le métronome borne donc la durée d'appui à l'intervalle moins 20 ms. Pour la vraie musique, deux notes rapprochées devront être regroupées dans un même geste (traits décalés par `startTime`, ou traits enchaînés). Si le jeu exige des appuis longs, cette contrainte pèsera lourd et Shizuku redevient intéressant. À regarder avec la durée minimale trouvée au point 1.
- **La bulle avale les appuis** qui tombent dessus. Le panneau prévient quand elle recouvre un repère. À l'étape 2, il faudra la rendre non tactile pendant la lecture ou l'écarter des touches.

## Écarts par rapport au brief

- Pas de bouton « Stop » dans le panneau : il se replie pendant la mesure, le bouton aurait été inatteignable. C'est la bulle qui devient le bouton Stop (rouge), en plus de volume bas.
- Curseur « durée d'appui » de 20 à 200 ms, par pas de 10.
- Les captures donnent la luminosité du pixel central et la moyenne d'une grille de 25 points : un pixel central noir peut n'être qu'un décor sombre.
- Les polices Fredoka et Nunito de `ui/fonts` (woff2 variables) sont converties en TTF statiques dans `res/font`, Android ne lisant pas le woff2.
- Le build a installé « Android SDK Build-Tools 34 » dans le SDK local (demandé par AGP 8.7).
