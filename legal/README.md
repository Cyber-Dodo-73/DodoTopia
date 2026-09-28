# Dossier `legal/` — conditions générales d'utilisation

Ce dossier contient le texte des CGU de DodoTopia et les fichiers dérivés que l'installeur affiche.

| Fichier | Rôle |
|---|---|
| `CGU-fr.md` | **Source qui fait foi.** Texte français des CGU, en Markdown. C'est le seul fichier à rédiger. |
| `CGU-en.md` | Traduction anglaise, à tenir à jour après chaque changement du français. |
| `CGU-es.md`, `CGU-de.md`, `CGU-pt-BR.md`, `CGU-zh-CN.md`, `CGU-ja.md`, `CGU-th.md`, `CGU-id.md`, `CGU-fil.md` | Traductions (une par langue de l'application et du site, `terms.LANGS`), même structure que l'anglais et même avertissement « la version française fait foi ». Non relues par un juriste. À tenir à jour comme l'anglais. |
| `CGU-<lang>.rtf` | Générés par `.tools/make_legal.py`. Ne pas les modifier à la main. Inno Setup n'accepte que `.txt` ou `.rtf` pour `LicenseFile` ; seuls `fr` et `en` servent à l'installeur. |
| `README.md` | Ce mode d'emploi. |

## Modifier les CGU

1. Modifie `CGU-fr.md` d'abord, puis reporte le changement dans `CGU-en.md` et dans chaque traduction (garde l'avertissement « The French version prevails » en tête de l'anglais).
2. Si le changement est de fond (pas une coquille), **change la version** : voir ci-dessous.
3. Régénère les RTF (voir ci-dessous) et vérifie-les.
4. Fais relire par un juriste avant toute mise en production : le commentaire HTML en fin de fichier est là pour le rappeler ; enlève-le une fois la relecture faite.

Markdown accepté par le convertisseur (volontairement limité, sans dépendance) :

- titres `#`, `##`, `###` ;
- paragraphes séparés par une ligne vide ;
- listes à puces (`- ` ou `* `) et listes numérotées (`1. `) ;
- `**gras**`, `*italique*` ou `_italique_` ;
- liens `[texte](url)`, rendus « texte (url) » puisque le RTF de l'installeur n'est pas cliquable ;
- commentaires HTML `<!-- … -->`, supprimés à la conversion (non visibles dans le RTF).

Les tableaux, les images et le HTML brut ne sont pas pris en charge : évite-les dans ces fichiers.

## Versionner

La ligne `Version : 2026-10` (`Version: 2026-10` en anglais) en tête des deux fichiers doit correspondre **exactement** à la constante `TERMS_VERSION` du code de l'application. L'application mémorise la version acceptée par l'utilisateur ; au lancement, si `TERMS_VERSION` diffère de la version mémorisée, elle réaffiche les CGU et **redemande l'acceptation**. Autrement dit :

- changer la version dans les `.md` **et** dans `TERMS_VERSION` = tous les utilisateurs doivent réaccepter à la prochaine mise à jour ;
- corriger une coquille sans changer la version = personne n'est redérangé.

Format retenu : `AAAA-MM` (année-mois de l'entrée en vigueur). Si deux versions sortent le même mois, ajoute un suffixe (`2026-10b`). Mets aussi à jour la ligne « Dernière mise à jour / entrée en vigueur » sous la version, dans les deux langues. Ne rétrograde jamais une version : la comparaison est une simple égalité de chaînes, mais un numéro qui recule sème la confusion dans l'historique.

## Régénérer les RTF

Depuis la racine du dépôt :

```
py .tools/make_legal.py
```

Le script lit chaque `legal/CGU-<lang>.md`, écrit `legal/CGU-<lang>.rtf` à côté, puis vérifie que chaque RTF commence par `{\rtf1`, se termine par `}`, a ses accolades équilibrées et que les accents y sont bien encodés (`\'e9` pour « é », etc.). Il s'arrête avec un code de retour non nul si un contrôle échoue. Aucune dépendance externe : Python 3 standard suffit.

Pour vérifier visuellement, ouvre le `.rtf` avec WordPad ou Word, ou compile l'installeur : Inno Setup affiche la page de licence avec le RTF déclaré dans `installer.iss` (`LicenseFile=legal\CGU-fr.rtf` dans `[Setup]`, et `LicenseFile: "legal\CGU-en.rtf"` sur la ligne de la langue anglaise dans `[Languages]`).

Les RTF étant générés, ils peuvent être commités (pour que le build CI n'ait rien à faire) ou régénérés dans le workflow de release avant `iscc` : dans les deux cas, ne les édite jamais directement.
