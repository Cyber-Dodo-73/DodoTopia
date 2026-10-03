# DodoTopia Mobile : journal des versions

Les versions Android ont leur propre numérotation, à part de l'appli PC (`CHANGELOG.md` à la racine).
Changer `versionName` dans `mobile/app/build.gradle.kts` et pousser sur `main` construit, signe et publie la version
(`.github/workflows/mobile-release.yml`).

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
