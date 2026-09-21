#!/usr/bin/env bash
# Controle de l'archive Linux de DodoTopia avant publication (appele par build.sh, docker/Dockerfile.linux et
# .github/workflows/release.yml). Sans dependance : bash, gzip, tar, grep, head, od.
#
#   bash .tools/check_linux_bundle.sh release/DodoTopia-x.y.z-linux-x64.tar.gz
#   bash .tools/check_linux_bundle.sh --list <archive>     # affiche aussi les .so de premier niveau de _internal/
#   bash .tools/check_linux_bundle.sh --self-test          # verifie l'expression des bibliotheques interdites
#
# Verifie : gzip valide et pas de double compression, tar lisible, aucune bibliotheque systeme embarquee
# (libstdc++, libgcc_s, Mesa, libglvnd, DRM, Vulkan, Wayland, libxcb liees a DRI : memes motifs que build.sh),
# fichiers de donnees presents (CGU, interface, config, assets), binaires executables, NSS complet.
# Code de sortie : 0 = tout est bon, 1 = au moins une erreur (toutes celles du groupe sont listees), 2 = usage.

# Bibliotheques qui doivent venir de la machine cible (garder en phase avec EXCLUDED_LIBS de build.sh).
FORBIDDEN_RE='/lib(stdc\+\+|gcc_s|gbm|glapi|drm(_[^/]*)?|EGL(_[^/]*)?|GL|GLX(_[^/]*)?|GLdispatch|OpenGL|GLESv[^/]*|vulkan|wayland-[^/]*|xcb-(glx|present|sync|dri[^/]*|shm|xfixes)|X11-xcb|xshmfence)\.so(\.[^/]*)?$'

REQUIRED_FILES=(
  DodoTopia/DodoTopia
  DodoTopia/DodoTopia.sh
  DodoTopia/_internal/legal/CGU-fr.md
  DodoTopia/_internal/legal/CGU-en.md
  DodoTopia/_internal/ui/index.html
  DodoTopia/_internal/ui/i18n/fr.json
  DodoTopia/_internal/config.default.json
  DodoTopia/_internal/assets/logo.png
  DodoTopia/_internal/assets/instruments/catalogue.json
  DodoTopia/_internal/assets/instruments/layouts.json
)

self_test() {
  local bad=0 n
  local refused=(
    a/libstdc++.so.6 a/libstdc++.so.6.0.30 a/libgcc_s.so.1 a/libgbm.so.1 a/libglapi.so.0 a/libdrm.so.2
    a/libdrm_amdgpu.so.1 a/libEGL.so.1 a/libEGL_mesa.so.0 a/libGL.so.1 a/libGLX.so.0 a/libGLX_mesa.so.0
    a/libGLdispatch.so.0 a/libOpenGL.so.0 a/libGLESv2.so.2 a/libvulkan.so.1 a/libwayland-client.so.0
    a/libwayland-egl.so.1 a/libxcb-glx.so.0 a/libxcb-present.so.0 a/libxcb-sync.so.1 a/libxcb-dri2.so.0
    a/libxcb-dri3.so.0 a/libxcb-shm.so.0 a/libxcb-xfixes.so.0 a/libX11-xcb.so.1 a/libxshmfence.so.1
    a/PyQt6/Qt6/lib/libGL.so a/b/libgbm.so
  )
  local accepted=(
    a/libQt6OpenGL.so.6 a/libQt6OpenGLWidgets.so.6 a/libQt6Core.so.6 a/libQt6WaylandClient.so.6
    a/libGLib.so a/libglib-2.0.so.0 a/libGLU.so.1 a/libGLEW.so.2 a/libgio-2.0.so.0
    a/libxcb-cursor.so.0 a/libxcb-icccm.so.4 a/libxcb-image.so.0 a/libxcb-keysyms.so.1 a/libxcb-render.so.0
    a/libxcb-render-util.so.0 a/libxcb-xkb.so.1 a/libxcb-randr.so.0 a/libxcb-shape.so.0 a/libxcb-xinerama.so.0
    a/libxcb.so.1 a/libX11.so.6 a/libxkbcommon.so.0 a/libxkbcommon-x11.so.0 a/libicudata.so.73 a/libnss3.so
    a/libsoftokn3.so a/libdrmfoo.so a/libEGLfoo.so a/libgcc_s.so.1/autre
  )
  for n in "${refused[@]}"; do
    if ! printf '%s\n' "$n" | grep -Eq -- "$FORBIDDEN_RE"; then echo "  AUTOTEST : devrait etre refusee : $n"; bad=1; fi
  done
  for n in "${accepted[@]}"; do
    if printf '%s\n' "$n" | grep -Eq -- "$FORBIDDEN_RE"; then echo "  AUTOTEST : refusee a tort : $n"; bad=1; fi
  done
  if [ "$bad" -eq 0 ]; then echo "Autotest de l'expression : OK"; fi
  return "$bad"
}

LIST=0
ARCHIVE=""
for arg in "$@"; do
  case "$arg" in
    --list) LIST=1 ;;
    --self-test) self_test; exit $? ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) echo "Option inconnue : $arg" >&2; exit 2 ;;
    *) ARCHIVE="$arg" ;;
  esac
done
if [ -z "$ARCHIVE" ]; then
  echo "Usage : bash .tools/check_linux_bundle.sh [--list] <archive.tar.gz>" >&2
  exit 2
fi
if [ ! -f "$ARCHIVE" ]; then
  echo "ERREUR : archive introuvable : $ARCHIVE" >&2
  exit 1
fi

ERRORS=()
err() { ERRORS+=("$1"); }
flush_errors() {   # $1 = nom du groupe ; sort en 1 si le groupe a des erreurs
  if [ ${#ERRORS[@]} -eq 0 ]; then return 0; fi
  echo ""
  echo "ECHEC du controle de $ARCHIVE ($1) : ${#ERRORS[@]} erreur(s)"
  local e
  for e in "${ERRORS[@]}"; do echo "  - $e"; done
  exit 1
}

echo "Controle de $ARCHIVE"

# ------------------------------------------------------------------ groupe 1 : integrite de l'archive
NAMES=""
VERBOSE=""
if ! gzip -t "$ARCHIVE" 2>/dev/null; then
  err "gzip -t echoue : le fichier n'est pas un gzip valide (telechargement tronque ou mauvais format)"
else
  MAGIC=$(gzip -dc "$ARCHIVE" 2>/dev/null | head -c 2 | od -An -tx1 | tr -d ' \n')
  if [ "$MAGIC" = "1f8b" ]; then
    err "double compression : le contenu decompresse est encore un gzip (octets 1f 8b), un serveur ou un outil a recompresse l'archive"
  elif ! NAMES=$(tar -tzf "$ARCHIVE" 2>/dev/null); then
    err "tar -tzf echoue : le contenu n'est pas une archive tar lisible"
  elif ! VERBOSE=$(tar -tzvf "$ARCHIVE" 2>/dev/null); then
    err "tar -tzvf echoue : le contenu n'est pas une archive tar lisible"
  fi
fi
flush_errors "integrite"
echo "  ok : gzip valide, pas de double compression, tar lisible ($(printf '%s\n' "$NAMES" | wc -l | tr -d ' ') entrees)"

if [ "$LIST" -eq 1 ]; then
  echo "Bibliotheques de premier niveau de DodoTopia/_internal/ :"
  printf '%s\n' "$NAMES" | grep -E '^DodoTopia/_internal/[^/]+\.so(\.[^/]*)?$' | sed 's|^DodoTopia/_internal/|  |' | sort
fi

# ------------------------------------------------------------------ groupe 2 : contenu
if ! self_test >/dev/null; then
  err "l'expression des bibliotheques interdites est cassee (bash .tools/check_linux_bundle.sh --self-test)"
fi

FORBIDDEN=$(printf '%s\n' "$NAMES" | grep -E -- "$FORBIDDEN_RE")
if [ -n "$FORBIDDEN" ]; then
  while IFS= read -r line; do
    err "bibliotheque systeme embarquee (doit venir de la machine cible) : $line"
  done <<< "$FORBIDDEN"
else
  echo "  ok : ni libstdc++/libgcc_s, ni Mesa/GL/DRM/Vulkan/Wayland dans le bundle"
fi

MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
  if ! printf '%s\n' "$NAMES" | grep -Fxq -- "$f"; then
    err "fichier absent : $f"
    MISSING=1
  fi
done
if [ "$MISSING" -eq 0 ]; then echo "  ok : CGU, interface, config et assets presents"; fi

# droits : la premiere colonne de tar -tzvf doit commencer par -rwx (fichier ordinaire, executable par son proprietaire)
check_exec() {   # $1 = chemin exact dans l'archive
  local line perms found=""
  while IFS= read -r line; do
    case "$line" in
      *" $1") found=$line; break ;;
    esac
  done <<< "$(printf '%s\n' "$VERBOSE" | grep -F -- " $1")"
  if [ -z "$found" ]; then return 0; fi     # absence deja signalee plus haut
  perms=${found%% *}
  case "$perms" in
    -rwx*) return 0 ;;
  esac
  err "non executable ($perms) : $1"
  return 1
}
EXEC_BAD=0
check_exec DodoTopia/DodoTopia || EXEC_BAD=1
check_exec DodoTopia/DodoTopia.sh || EXEC_BAD=1
WEBENGINE=$(printf '%s\n' "$NAMES" | grep -E '/QtWebEngineProcess$')
if [ -z "$WEBENGINE" ]; then
  err "QtWebEngineProcess absent du bundle (backend Qt incomplet)"
  EXEC_BAD=1
else
  while IFS= read -r p; do
    check_exec "$p" || EXEC_BAD=1
  done <<< "$WEBENGINE"
fi
if [ "$EXEC_BAD" -eq 0 ]; then echo "  ok : DodoTopia, DodoTopia.sh et QtWebEngineProcess executables"; fi

if printf '%s\n' "$NAMES" | grep -Eq '/libnss3\.so$'; then
  if printf '%s\n' "$NAMES" | grep -Eq '/libsoftokn3\.so$'; then
    echo "  ok : NSS complet (libnss3.so + libsoftokn3.so)"
  else
    err "libnss3.so est embarquee sans libsoftokn3.so : NSS ne s'initialise pas (QtWebEngine plante au demarrage)"
  fi
fi

flush_errors "contenu"
echo "Archive conforme : $ARCHIVE"
exit 0
