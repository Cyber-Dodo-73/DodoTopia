#!/usr/bin/env bash
# DodoTopia - bundle Linux (PyInstaller one-folder + tar.gz dans release/).
# Depuis Windows : build-linux.bat (Docker). Sur Linux ou WSL2 : bash build.sh
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

echo "[1/3] Dependances Python (venv $VENV)..."
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
if [ ! -f "$VENV/.deps-ok" ] || [ requirements-linux.txt -nt "$VENV/.deps-ok" ]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet --upgrade -r requirements-linux.txt
  touch "$VENV/.deps-ok"
fi

echo "[2/3] Config livree (sans calibrage perso)..."
"$VENV/bin/python" "$PWD/make_default_config.py"

echo "[2/3] PyInstaller ($BUILD/dist/DodoTopia)..."
"$VENV/bin/pyinstaller" --noconfirm --clean --windowed --name DodoTopia \
  --workpath "$BUILD/work" --distpath "$BUILD/dist" --specpath "$BUILD" \
  --add-data "$PWD/ui:ui" --add-data "$PWD/assets:assets" --add-data "$PWD/config.default.json:." \
  --hidden-import mido --collect-all rtmidi --collect-all mss --collect-submodules Xlib \
  --hidden-import numpy --hidden-import soundcard --collect-data soundcard \
  --hidden-import websocket --collect-data certifi \
  --hidden-import webview.platforms.qt --hidden-import qtpy \
  --hidden-import PyQt6.QtWebEngineWidgets --hidden-import PyQt6.QtWebEngineCore --hidden-import PyQt6.QtWebChannel \
  --collect-all webview \
  --exclude-module _win_io --exclude-module keyboard --exclude-module tkinter \
  app.py
cp DodoTopia.sh "$BUILD/dist/DodoTopia/" 2>/dev/null || true

echo "[3/3] Archive release/DodoTopia-$VERSION-linux-x64.tar.gz..."
tar -C "$BUILD/dist" -czf "release/DodoTopia-$VERSION-linux-x64.tar.gz" --owner=0 --group=0 DodoTopia
ls -la "release/DodoTopia-$VERSION-linux-x64.tar.gz"
echo "Termine. Decompresse l'archive et lance DodoTopia/DodoTopia."
