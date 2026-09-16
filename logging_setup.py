# -*- coding: utf-8 -*-
"""Journal principal de DodoTopia : fichier tournant `dodotopia.log` dans le dossier de donnees, tampon
memoire pour l'interface, et capture de toute exception non rattrapee (fil principal et fils de fond).

Avant ce module, une exception dans un appel de l'interface ou dans un fil daemon disparaissait sans trace
en version fenetree (pas de console). A appeler en tete de main(), avant tout chargement de configuration."""
import logging
import logging.handlers
import os
import sys
import threading
import traceback
from collections import deque

LOG_NAME = "dodotopia.log"
MAX_BYTES = 1_000_000
BACKUPS = 3
MEMORY_LINES = 200

_memory = deque(maxlen=MEMORY_LINES)
_crash_hooks = []          # callables(msg) prevenus a chaque exception non rattrapee (toast de l'interface)
_installed = False


class _MemoryHandler(logging.Handler):
    """Garde les dernieres lignes formatees pour la carte « Journal » de l'interface."""

    def emit(self, record):
        try:
            _memory.append(self.format(record))
        except Exception:  # noqa : un journal ne doit jamais faire tomber l'application
            pass


def setup(data_dir, debug=False):
    """Installe le journal fichier + memoire et les crochets d'exception. Idempotent."""
    global _installed
    if _installed:
        return logging.getLogger("dodotopia")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s : %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(data_dir, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(os.path.join(data_dir, LOG_NAME), maxBytes=MAX_BYTES,
                                                  backupCount=BACKUPS, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass  # dossier en lecture seule : on garde au moins le tampon memoire
    mh = _MemoryHandler()
    mh.setFormatter(fmt)
    root.addHandler(mh)
    if debug:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    _installed = True
    log = logging.getLogger("dodotopia")
    log.info("journal ouvert (%s)", "debug" if debug else "normal")
    return log


def on_crash(fn):
    """Enregistre un callable(msg) appele a chaque exception non rattrapee."""
    _crash_hooks.append(fn)


def recent(n=50):
    """Dernieres lignes du journal (les plus recentes en dernier)."""
    return list(_memory)[-n:]


def log_path(data_dir):
    return os.path.join(data_dir, LOG_NAME)


def _report(kind, exc_type, exc, tb, thread_name=None):
    text = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
    where = f" (fil {thread_name})" if thread_name else ""
    logging.getLogger("dodotopia").error("exception non rattrapée%s :\n%s", where, text)
    msg = f"{exc_type.__name__}: {exc}"
    for fn in list(_crash_hooks):
        try:
            fn(msg)
        except Exception:  # noqa
            pass


def _excepthook(exc_type, exc, tb):
    _report("main", exc_type, exc, tb)


def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    _report("thread", args.exc_type, args.exc_value, args.exc_traceback,
            getattr(args.thread, "name", None))
