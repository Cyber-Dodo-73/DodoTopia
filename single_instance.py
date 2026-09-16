# -*- coding: utf-8 -*-
"""Instance unique de DodoTopia : un deuxieme lancement (double clic, lien dodotopia://) transmet ses
arguments a la fenetre deja ouverte puis se termine.

Fonctionnement portable (Windows et Linux, sans verrou systeme) :
  - l'instance principale ecoute sur 127.0.0.1, port choisi par le systeme
    (multiprocessing.connection.Listener) et publie `DATA_DIR/instance.json` {port, pid, secret_hash} ;
  - le secret partage (32 octets aleatoires) est dans `DATA_DIR/instance.key`, lisible par l'utilisateur
    seulement (le dossier de donnees est deja prive sous Windows ; 0600 sous Linux) ;
  - une connexion n'est acceptee qu'apres le defi HMAC de multiprocessing (les deux sens) ; le message est
    du JSON {"argv": [...]} (jamais pickle), borne a 64 Kio ; chaque echange est limite dans le temps ;
  - fichier perime (processus mort, port ferme, secret different) : on devient l'instance principale.
"""
import hashlib
import json
import logging
import os
import secrets
import socket
import sys
import threading
from multiprocessing import connection as mpc

log = logging.getLogger("instance")

INFO_NAME = "instance.json"
KEY_NAME = "instance.key"
EXCHANGE_TIMEOUT = 3.0
MAX_MESSAGE = 64 * 1024


def pid_alive(pid):
    """Vrai si un processus de ce pid existe (sans jamais lui envoyer de signal sous Windows)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5           # acces refuse : il existe
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259                      # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _hash(secret):
    return hashlib.sha256(secret).hexdigest()


def _with_deadline(conn, timeout, fn):
    """Execute fn() ; si l'echange depasse `timeout`, la connexion est fermee (la lecture bloquee echoue)."""
    timer = threading.Timer(timeout, _close_quiet, (conn,))
    timer.daemon = True
    timer.start()
    try:
        return fn()
    finally:
        timer.cancel()


def _close_quiet(conn):
    try:
        conn.close()
    except Exception:  # noqa
        pass


class SingleInstance:
    def __init__(self, data_dir, on_message=None, log_fn=None):
        self.data_dir = data_dir
        self.info_path = os.path.join(data_dir, INFO_NAME)
        self.key_path = os.path.join(data_dir, KEY_NAME)
        self._handler = on_message
        self._backlog = []                 # messages recus avant set_handler()
        self._lock = threading.Lock()
        self._listener = None
        self._thread = None
        self._closed = threading.Event()
        self._secret = None
        self._log_fn = log_fn
        self.port = None

    def log(self, msg):
        if self._log_fn:
            try:
                self._log_fn(msg)
                return
            except Exception:  # noqa
                pass
        log.info("%s", msg)

    # ---------------------------------------------------------------- secret partage
    def _load_secret(self):
        os.makedirs(self.data_dir, exist_ok=True)
        for _ in range(3):
            try:
                with open(self.key_path, "rb") as f:
                    data = f.read(256).strip()
                secret = bytes.fromhex(data.decode("ascii"))
                if len(secret) >= 16:
                    return secret
            except FileNotFoundError:
                pass
            except (OSError, ValueError, UnicodeDecodeError):
                try:
                    os.remove(self.key_path)          # illisible ou tronque : on le refait
                except OSError:
                    pass
            secret = secrets.token_bytes(32)
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            except FileExistsError:
                continue                              # cree en meme temps par un autre lancement : relire
            with os.fdopen(fd, "wb") as f:
                f.write(secret.hex().encode("ascii"))
            return secret
        raise OSError("secret d'instance illisible")

    # ---------------------------------------------------------------- client (deuxieme lancement)
    def _read_info(self):
        try:
            with open(self.info_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    def _forward(self, info, argv):
        """Transmet argv a l'instance decrite par `info` ; True si elle a accuse reception."""
        try:
            port = int(info.get("port"))
        except (TypeError, ValueError):
            return False
        if not 0 < port < 65536 or info.get("secret_hash") != _hash(self._secret) or not pid_alive(info.get("pid")):
            return False
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=EXCHANGE_TIMEOUT)
        except OSError:
            return False
        sock.setblocking(True)
        conn = mpc.Connection(sock.detach())

        def exchange():
            mpc.answer_challenge(conn, self._secret)
            mpc.deliver_challenge(conn, self._secret)
            conn.send_bytes(json.dumps({"argv": [str(a) for a in argv]}).encode("utf-8"))
            return conn.recv_bytes(64) == b"ok"
        try:
            return bool(_with_deadline(conn, EXCHANGE_TIMEOUT, exchange))
        except (OSError, EOFError, mpc.AuthenticationError, ValueError) as e:
            self.log(f"instance : transmission impossible ({e!r})")
            return False
        finally:
            _close_quiet(conn)

    # ---------------------------------------------------------------- serveur (instance principale)
    def acquire(self, argv=()):
        """True : cette instance est la principale (elle ecoute) ; False : arguments transmis a l'instance
        deja ouverte, il faut quitter. Toute erreur inattendue laisse demarrer normalement (True)."""
        try:
            self._secret = self._load_secret()
        except OSError as e:
            self.log(f"instance : secret indisponible ({e}), instance unique désactivée")
            return True
        info = self._read_info()
        if info and self._forward(info, argv):
            self.log(f"instance : arguments transmis à l'instance ouverte (pid {info.get('pid')})")
            return False
        if info:
            self.log("instance : fichier d'instance périmé, on prend la main")
        try:
            self._listen()
        except OSError as e:
            self.log(f"instance : écoute impossible ({e}), instance unique désactivée")
        return True

    def _listen(self):
        self._listener = mpc.Listener(("127.0.0.1", 0), family="AF_INET")
        self.port = self._listener.address[1]
        data = {"port": self.port, "pid": os.getpid(), "secret_hash": _hash(self._secret)}
        tmp = f"{self.info_path}.tmp-{os.getpid()}-{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.info_path)
        self._thread = threading.Thread(target=self._accept_loop, name="single-instance", daemon=True)
        self._thread.start()

    def _accept_loop(self):
        while not self._closed.is_set():
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                if self._closed.is_set():
                    return
                continue
            except Exception as e:  # noqa
                if self._closed.is_set():
                    return
                self.log(f"instance : accept : {e!r}")
                continue
            threading.Thread(target=self._serve, args=(conn,), name="single-instance-conn", daemon=True).start()

    def _serve(self, conn):
        def exchange():
            mpc.deliver_challenge(conn, self._secret)
            mpc.answer_challenge(conn, self._secret)
            raw = conn.recv_bytes(MAX_MESSAGE)
            msg = json.loads(raw.decode("utf-8"))
            argv = msg.get("argv") if isinstance(msg, dict) else None
            if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv) or len(argv) > 32:
                raise ValueError("message invalide")
            conn.send_bytes(b"ok")
            return argv
        try:
            argv = _with_deadline(conn, EXCHANGE_TIMEOUT, exchange)
        except Exception as e:  # noqa : defi refuse, delai depasse, message invalide
            self.log(f"instance : connexion refusée ({type(e).__name__})")
            return
        finally:
            _close_quiet(conn)
        self._dispatch(argv)

    def _dispatch(self, argv):
        with self._lock:
            handler = self._handler
            if handler is None:
                self._backlog.append(argv)
                return
        try:
            handler(argv)
        except Exception as e:  # noqa
            self.log(f"instance : traitement des arguments : {e!r}")

    def set_handler(self, fn):
        """Branche le traitement des arguments recus (apres la creation de l'Api) ; rejoue ceux deja recus."""
        with self._lock:
            self._handler = fn
            backlog, self._backlog = self._backlog, []
        for argv in backlog:
            self._dispatch(argv)

    def close(self):
        """Arrete l'ecoute et retire instance.json s'il nous designe encore."""
        if self._closed.is_set():
            return
        self._closed.set()
        lst, self._listener = self._listener, None
        if lst is not None:
            try:
                lst.close()
            except Exception:  # noqa
                pass
            info = self._read_info()
            if info and info.get("port") == self.port and info.get("pid") == os.getpid():
                try:
                    os.remove(self.info_path)
                except OSError:
                    pass
