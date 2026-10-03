# DodoTopia Mobile : journal des versions

Les versions Android ont leur propre numérotation, à part de l'appli PC (`CHANGELOG.md` à la racine).
Changer `versionName` dans `mobile/app/build.gradle.kts` et pousser sur `main` construit, signe et publie la version
(`.github/workflows/mobile-release.yml`).

## 0.7.2

- **Peinture avec les 126 nuances** : quand les flèches ne mènent pas à la bonne page de nuances, l'appli repasse par
  la palette principale (famille, puis bouton des nuances) au lieu d'insister et de s'arrêter ; les appuis sur les
  flèches sont aussi plus espacés.
- **Cuisine** : le bouton « Cuisiner » est cherché par sa couleur quand l'écran n'est pas en 16:9 (il n'était ni
  reconnu ni touché sur les téléphones plus allongés).
- **Bulle** : elle ne disparaît plus quand une fenêtre passagère (barre de jeu du téléphone, boîte de dialogue)
  passe par-dessus Heartopia.
- **Choix de l'instrument** : sur l'accueil, choisis l'instrument que tu tiens dans le jeu (piano, harpe, luth,
  flûte, violon, xylophone…). Son clavier est sélectionné tout seul et c'est lui qui est annoncé aux autres joueurs
  en salon, pour la répartition des pistes de l'orchestre. Nouveaux claviers « 8 notes, 1 rangée » pour le xylophone
  et « 8 notes, 2 rangées » pour la conque.
  Chaque instrument a son propre calibrage des touches (elles ne sont pas au même endroit d'un instrument à
  l'autre) ; le calibrage déjà fait reste valable pour le piano ou le luth.
- Les barres de calibrage (aide, Annuler, Valider) se déplacent au doigt quand elles cachent la toile, un repère ou
  une touche ; leur place est retenue.
- L'appli ne demande plus l'accès au micro ni le droit d'installer d'autres applis : ces deux permissions pesaient
  dans le classement de Play Protect. Une mise à jour s'ouvre maintenant dans le navigateur, qui télécharge l'APK ;
  Android propose ensuite de l'installer par-dessus l'appli, réglages conservés.
- Le test de capture des Réglages ne mesure plus le son du jeu (il exigeait la permission du micro).
- Quand Android garde le service d'accessibilité coché mais ne le relance pas (appli arrêtée de force, économie de
  batterie), l'appli le dit et renvoie aux réglages pour l'éteindre puis le rallumer, au lieu de rester bloquée sur
  « à activer ». L'état est relu à chaque retour dans l'appli.

## 0.7.1

- Une mise à jour disponible est proposée dès le lancement de l'appli.
- Version 0.7.0 non publiée : même contenu, détaillé ci-dessous.

## 0.7.0

Première version publiée. Tout ce qui touche au jeu a été essayé sur émulateur (BlueStacks, Android 11) seulement.

- **Musique** : import de fichiers MIDI, quatre claviers (15, 22 ou 37 notes), calibrage des touches par pastilles,
  lecture depuis la bulle avec pause et reprise, vitesse, arrangeur, choix des pistes, notes tenues en option.
- **Dessin** : image ramenée à la grille et aux couleurs de l'outil de peinture, peinte depuis la bulle, relue et
  retouchée ; nuances et pot de peinture en option ; reprise d'un dessin interrompu.
- **Cuisine** : boucle automatique devant la cuisinière (lancer le plat, ajuster le feu, récupérer), une cuisinière
  par défaut, plusieurs en option. Demande Android 11.
- **En ligne** : compte Discord, bibliothèque de morceaux (recherche, filtres, j'aime, partage), salons synchronisés
  avec les joueurs PC (rejoindre en cours de morceau, avance/retard, orchestre).
- **Appli** : bulle visible seulement par-dessus Heartopia, réglages, thème sombre, français et anglais,
  mise à jour depuis l'appli.
