#!/usr/bin/env bash
# DodoTopia - bundle Linux (PyInstaller one-folder + tar.gz dans release/).
# Depuis Windows : build-linux.bat (Docker). Sur Linux ou WSL2 : bash build.sh
# Toujours construire sur la distribution la plus ancienne prise en charge (Ubuntu 22.04, glibc 2.35).
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION *= *"\([^"]*\)".*/\1/p' version.py)
echo "============================================================"
echo " DodoTopia $VERSION - construction du bundle Linux"
echo "============================================================"

# hors du depot : ne touche pas build/, dist/ et DodoTopia.spec de la version Windows
BUILD="${DODO_BUILD_DIR:-$HOME/.cache/dodotopia-build}"
VENV="${DODO_VENV:-$HOME/.venv-dodotopia}"
mkdir -p "$BUILD" release

echo "[1/4] Dependances Python (venv $VENV)..."
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
if [ ! -f "$VENV/.deps-ok" ] || [ requirements-linux.txt -nt "$VENV/.deps-ok" ]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet --upgrade -r requirements-linux.txt
  touch "$VENV/.deps-ok"
fi

echo "[2/4] Config livree (sans calibrage perso)..."
"$VENV/bin/python" "$PWD/make_default_config.py"

echo "[2/4] PyInstaller ($BUILD/dist/DodoTopia)..."
"$VENV/bin/pyinstaller" --noconfirm --clean --windowed --name DodoTopia --noupx \
  --workpath "$BUILD/work" --distpath "$BUILD/dist" --specpath "$BUILD" \
  --add-data "$PWD/ui:ui" --add-data "$PWD/assets:assets" --add-data "$PWD/legal:legal" \
  --add-data "$PWD/config.default.json:." \
  --hidden-import mido --collect-all rtmidi --collect-all mss --collect-submodules Xlib \
  --hidden-import numpy --hidden-import soundcard --collect-data soundcard \
  --hidden-import websocket --collect-data certifi --hidden-import pypresence \
  --hidden-import webview.platforms.qt --hidden-import qtpy \
  --hidden-import PyQt6.QtWebEngineWidgets --hidden-import PyQt6.QtWebEngineCore --hidden-import PyQt6.QtWebChannel \
  --collect-all webview \
  --exclude-module _win_io --exclude-module keyboard --exclude-module tkinter \
  app.py

# Bibliotheques qui doivent venir de la machine cible, jamais du bundle :
#  - libstdc++ / libgcc_s : celles d'Ubuntu 22.04 sont plus anciennes que celles qu'attend le pilote Mesa d'une
#    distribution recente (GLIBCXX_3.4.31 demande par libz3/LLVM) -> plus de contexte OpenGL, QtWebEngine plante ;
#  - Mesa / libglvnd / libdrm / libgbm / Vulkan / Wayland et les libxcb liees a DRI : depuis Mesa 24 elles forment
#    un tout avec le pilote du systeme (fenetre vide si on les melange).
# On garde Qt (libQt6*, dont libQt6OpenGL), ICU, NSS, libxkbcommon* et les
# libxcb-cursor/icccm/image/keysyms/render*/xkb/randr/shape/xinerama.
# La meme liste est verifiee par .tools/check_linux_bundle.sh : garder les deux en phase.
echo "[3/4] Retrait des bibliotheques systeme (libstdc++, Mesa, DRM, Wayland...)..."
BUNDLE="$BUILD/dist/DodoTopia"
EXCLUDED_LIBS=(
  'libstdc++.so*' 'libgcc_s.so*'
  'libgbm.so*' 'libglapi.so*' 'libdrm.so*' 'libdrm_*.so*'
  'libEGL.so*' 'libEGL_*.so*' 'libGL.so*' 'libGLX.so*' 'libGLX_*.so*' 'libGLdispatch.so*' 'libOpenGL.so*'
  'libGLESv*.so*' 'libvulkan.so*' 'libwayland-*.so*'
  'libxcb-glx.so*' 'libxcb-present.so*' 'libxcb-sync.so*' 'libxcb-dri*.so*' 'libxcb-shm.so*' 'libxcb-xfixes.so*'
  'libX11-xcb.so*' 'libxshmfence.so*'
)
FIND_EXPR=()
for pat in "${EXCLUDED_LIBS[@]}"; do
  [ ${#FIND_EXPR[@]} -eq 0 ] || FIND_EXPR+=(-o)
  FIND_EXPR+=(-name "$pat")
done
find "$BUNDLE" \( -type f -o -type l \) \( "${FIND_EXPR[@]}" \) -print -delete | sed "s|^$BUNDLE/|  retire : |"
find "$BUNDLE" -xtype l -print -delete | sed "s|^$BUNDLE/|  lien orphelin retire : |"

install -m 755 DodoTopia.sh "$BUNDLE/DodoTopia.sh"
chmod 755 "$BUNDLE/DodoTopia"
find "$BUNDLE" -type f -name QtWebEngineProcess -exec chmod 755 {} +

ARCHIVE="release/DodoTopia-$VERSION-linux-x64.tar.gz"
echo "[4/4] Archive $ARCHIVE..."
tar -C "$BUILD/dist" -czf "$ARCHIVE" --owner=0 --group=0 --numeric-owner DodoTopia
ls -la "$ARCHIVE"

echo "Controle du bundle..."
bash .tools/check_linux_bundle.sh "$ARCHIVE"
echo "Termine. Decompresse l'archive (tar -xzf) et lance DodoTopia/DodoTopia.sh."
