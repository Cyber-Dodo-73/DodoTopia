#!/usr/bin/env bash
# Lance DodoTopia depuis les sources sous Linux (equivalent de DodoTopia.bat).
# Interface : GTK/WebKit2 si python3-gi + gir1.2-webkit2-4.1 sont installes, sinon Qt (pip, dans le venv).
#
# Liens dodotopia:// : au lancement, ce script (re)ecrit ~/.local/share/applications/dodotopia.desktop
# (MimeType=x-scheme-handler/dodotopia, Exec=... --url %u) si le chemin a change. Pour que le navigateur
# ouvre DodoTopia sur un lien, rendre ce fichier gestionnaire par defaut (une fois) :
#     xdg-mime default dodotopia.desktop x-scheme-handler/dodotopia
# DODO_NO_DESKTOP=1 : ne pas ecrire le fichier .desktop.
cd "$(dirname "$0")"
HERE="$(pwd)"

install_desktop() {   # $1 = commande absolue a lancer
  [ -n "${DODO_NO_DESKTOP:-}" ] && return 0
  local apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  local file="$apps/dodotopia.desktop"
  local icon="$HERE/assets/logo-256.png"
  [ -f "$icon" ] || icon="$HERE/_internal/assets/logo-256.png"
  local content
  content="[Desktop Entry]
Type=Application
Name=DodoTopia
Comment=Musique, dessin et cuisine pour Heartopia
Exec=\"$1\" --url %u
Icon=$icon
Terminal=false
Categories=Game;Utility;
MimeType=x-scheme-handler/dodotopia;
"
  if [ -f "$file" ] && [ "$(cat "$file")" = "$(printf '%s' "$content")" ]; then
    return 0
  fi
  mkdir -p "$apps" 2>/dev/null || return 0
  printf '%s' "$content" > "$file" 2>/dev/null || return 0
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" >/dev/null 2>&1
  echo "Liens dodotopia:// : $file ecrit. Pour l'activer : xdg-mime default dodotopia.desktop x-scheme-handler/dodotopia"
  return 0
}

if [ -x "./_internal/../DodoTopia" ] && [ ! -f app.py ]; then
  install_desktop "$HERE/DodoTopia"
  exec ./DodoTopia "$@"          # copie du script dans le bundle : lance le binaire
fi
VENV="${DODO_VENV:-$HOME/.venv-dodotopia}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv --system-site-packages "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade mido pillow python-xlib mss python-rtmidi pywebview pypresence
  if ! "$VENV/bin/python" -c "import gi; gi.require_version('WebKit2', '4.1')" 2>/dev/null; then
    echo "WebKit2GTK absent : installation du backend Qt (pywebview[qt])..."
    "$VENV/bin/pip" install --quiet --upgrade "pywebview[qt]"
  fi
fi
install_desktop "$HERE/DodoTopia.sh"
exec "$VENV/bin/python" app.py "$@"
