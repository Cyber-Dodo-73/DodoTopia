# -*- coding: utf-8 -*-
"""Version console de DodoTopia (sans interface). Lance app.py pour l'interface graphique."""
import os
import sys
import time

import core


def main():
    cfg = core.load_config()
    player = core.Player(cfg, log=lambda m: print("  " + m))
    if len(sys.argv) > 1:
        ids = [i.id for i in player.instruments]
        if sys.argv[1].lower() in ids:
            player.set_instrument(ids.index(sys.argv[1].lower()))
    core.bind_hotkeys(player, cfg)
    hk = cfg["hotkeys"]
    print("=" * 60)
    print(" DodoTopia (console)")
    print("=" * 60)
    print(f" Instrument : {player.instrument.name}   (autres : "
          f"{', '.join(i.id for i in player.instruments if i is not player.instrument)})")
    print(f" Dossier chansons : {player.songs_folder}")
    for i, s in enumerate(player.songs):
        print(f"  {'>' if i == player.index else ' '} {os.path.basename(s)}")
    print()
    for name, label in (("play_pause", "lecture / pause"), ("stop", "stop"),
                        ("next_song", "chanson suivante"), ("prev_song", "chanson precedente"),
                        ("speed_down", "vitesse -"), ("speed_up", "vitesse +"),
                        ("next_instrument", "instrument suivant")):
        print(f" {hk.get(name, '-'):>4} : {label}")
    print(" Ctrl+C ici pour quitter")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()


if __name__ == "__main__":
    main()
