# -*- coding: utf-8 -*-
"""Version console de DodoTopia (sans interface). Lance app.py pour l'interface graphique."""
import os
import sys
import time

import core
import platform_io


def bind_hotkeys(player, cfg):
    """Raccourcis globaux + crochet d'interruption (version console seulement ; l'interface a les siens)."""
    actions = {
        "play_pause": lambda: player.play_pause("game"), "stop": player.stop,
        "next_song": player.next_song, "prev_song": player.prev_song,
        "speed_down": player.speed_down, "speed_up": player.speed_up,
        "next_instrument": player.next_instrument,
    }
    handles = []
    for name, fn in actions.items():
        combo = cfg["hotkeys"].get(name)
        if combo:
            try:
                handles.append(platform_io.add_hotkey(combo, fn))
            except Exception as e:  # noqa
                player.log(f"raccourci invalide {combo!r} : {e}")
    if player._hook is None:
        player._hook = platform_io.hook(player._on_key_event)
    return handles


def main():
    cfg = core.load_config()
    player = core.Player(cfg, log=lambda m: print("  " + m))
    if len(sys.argv) > 1:
        ids = [i.id for i in player.instruments]
        if sys.argv[1].lower() in ids:
            player.set_instrument(ids.index(sys.argv[1].lower()))
    bind_hotkeys(player, cfg)
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
