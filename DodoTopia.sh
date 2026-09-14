#!/usr/bin/env bash
# Lance DodoTopia depuis les sources sous Linux (equivalent de DodoTopia.bat).
# Interface : GTK/WebKit2 si python3-gi + gir1.2-webkit2-4.1 sont installes, sinon Qt (pip, dans le venv).
cd "$(dirname "$0")"
if [ -x "./_internal/../DodoTopia" ] && [ ! -f app.py ]; then
  exec ./DodoTopia "$@"          # copie du script dans le bundle : lance le binaire
fi
VENV="${DODO_VENV:-$HOME/.venv-dodotopia}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv --system-site-packages "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade mido pillow python-xlib mss python-rtmidi pywebview
  if ! "$VENV/bin/python" -c "import gi; gi.require_version('WebKit2', '4.1')" 2>/dev/null; then
    echo "WebKit2GTK absent : installation du backend Qt (pywebview[qt])..."
    "$VENV/bin/pip" install --quiet --upgrade "pywebview[qt]"
  fi
fi
exec "$VENV/bin/python" app.py "$@"
