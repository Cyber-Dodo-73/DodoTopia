# -*- coding: utf-8 -*-
"""Mode Multi : top depart partage par une note repere jouee dans le jeu, sans reseau.

Chaque joueur appuie sur F6 ; pendant un compte a rebours son DodoTopia ecoute la sortie audio du PC (ce que
le jeu joue). Le premier dont le compte a rebours se termine (meneur) joue un court motif (DO5 SOL4 + sa note
d'identite) avec son instrument, puis demarre la musique ; les autres (suiveurs) detectent le motif dans le
son capture et demarrent au meme instant.

Calibrage (« Calibrer », tous ensemble) : le meneur joue son motif, chaque suiveur repond par le sien dans un
creneau propre a son numero, le meneur renvoie un echo du motif de chaque suiveur ; le suiveur mesure
l'aller-retour par le jeu et enregistre la moitie comme decalage (il jouera d'autant plus tot)."""
import math
import queue
import sys
import threading
import time
from collections import deque

import i18n
from platform_io import mouse_button_down


def _stop_text(code):
    """Phrase d'arret pour un code (core.stop_reason_text ; import a l'appel : core importe sync a la demande)."""
    from core import stop_reason_text
    return stop_reason_text(code)

MAX_PLAYERS = 5
PATTERN_NOTES = [72, 67]                 # DO5, SOL4 : debut commun de tous les motifs
ID_NOTES = [69, 65, 62, 64, 60]          # 3e note = identite du joueur 1..5 : LA4, FA4, RE4, MI4, DO4
                                         # (toutes jouables par piano, flute et luth sans transposition ; jamais
                                         # DO5 ni SOL4 : une note qui resonne encore (piano) masquerait sa
                                         # propre repetition ; aucune harmonique de DO5 / SOL4 ne tombe dessus)
NOTE_NAMES = {72: "DO5", 67: "SOL4", 69: "LA4", 65: "FA4", 62: "RÉ4", 64: "MI4", 60: "DO4"}
REPLY_BASE, REPLY_STEP, ECHO_DELAY = 1.5, 1.6, 0.8   # calibrage : reponse du joueur k a t0 + 1,5 + 1,6 (k-1) ;
                                                     # echo du meneur 0,8 s apres la reponse
COUNTDOWN_STEP = 1.2       # secondes de compte a rebours en plus par numero de joueur : le joueur 1 devient meneur
                           # le premier ; l'ecart couvre le trajet par le jeu (~0,6 s) + le motif (0,36 s), sinon
                           # deux joueurs qui appuient sur F6 en meme temps deviennent tous deux meneurs
MAX_EXTEND = 2.0           # prolongation maximale du compte a rebours quand on entend des attaques (musique du jeu)
PLAY_MODES = ("solo", "audio", "room")
DEFAULT_MULTI = {
    "enabled": False,          # interrupteur Solo / Multi audio de l'onglet Musique (ancien ; voir `mode`)
    "mode": "solo",            # solo | audio (note repere, ce module) | room (salon en ligne, room.py) ;
                               # derive de `enabled` pour les anciennes configs (ensure_defaults)
    "name": "",                # pseudo affiche dans les salons (vide = nom Discord ou « Joueur »)
    "net_offset_ms": 0,        # salon : avance (negatif) / retard du joueur en ms (-300..300)
    "room_minimize": False,    # salon : reduire DodoTopia au depart (sinon il faut passer sur le jeu a la main)
    "last_room": "",           # salon : dernier code rejoint (pre-rempli dans l'interface)
    "player_id": 1,            # numero du joueur 1..5 : note d'identite du motif, creneau de compte a rebours
    "countdown": 10.0,         # secondes d'ecoute avant de devenir meneur (+0,3 s par numero)
    "lead": 1.5,               # secondes entre le motif repere et le depart de la musique
    "offset_ms": 0,            # decalage du suiveur (negatif = plus tot) ; fixe par le calibrage
    "latency": None,           # delai appui -> detection sur ce PC, mesure par « Tester la detection »
    "beacon_freqs": None,      # frequences mesurees des 3 notes du motif (test)
    "tune": 1.0,               # accord du jeu par rapport au la 440 (mesure par le test)
    "beacon_gap": 0.25,        # secondes entre deux attaques du motif (0,18 avant : trop serre pour les notes
                               # des autres joueurs, qui arrivent par le reseau du jeu avec de la gigue)
    "beacon_hold": 0.12,       # duree d'appui de chaque note du motif
    "device": "",              # nom (partiel) du peripherique de sortie a ecouter ; vide = sortie par defaut
    "calib": None,             # dernier calibrage : {"role", "leader", "rtt_ms", "offset_ms", "players", "when"}
}
C_MAJOR = {0, 2, 4, 5, 7, 9, 11}


def note_freq(note, tune=1.0):
    return 440.0 * 2 ** ((int(note) - 69) / 12) * float(tune or 1.0)


def ensure_defaults(cfg):
    m = cfg.setdefault("multi", {})
    if "player_id" not in m and "slot" in m:
        try:
            m["player_id"] = max(1, min(MAX_PLAYERS, int(m["slot"])))
        except (TypeError, ValueError):
            pass
    m.pop("slot", None)
    m.pop("beacon_notes", None)
    if abs(float(m.get("beacon_gap") or 0) - 0.18) < 1e-6:
        m["beacon_gap"] = DEFAULT_MULTI["beacon_gap"]     # ancienne valeur par defaut : on suit la nouvelle
    if m.get("mode") not in PLAY_MODES:
        # ancienne config (interrupteur Solo / Multi) ou valeur inconnue : derive de `enabled`
        m["mode"] = "audio" if m.get("enabled") else "solo"
    if m["mode"] == "room":
        # 2.1 : le salon n'est plus un mode memorise (il se deduit du salon rejoint) ; l'ancien reglage
        # detournait F6 vers un salon deja quitte
        m["mode"] = "solo"
    for k, v in DEFAULT_MULTI.items():
        m.setdefault(k, list(v) if isinstance(v, list) else v)
    try:
        m["net_offset_ms"] = max(-300, min(300, int(m.get("net_offset_ms") or 0)))
    except (TypeError, ValueError):
        m["net_offset_ms"] = 0
    return m


def choose_common_extra(all_notes):
    """Decalage en demi-tons (-6..5) qui met le plus de notes sur la gamme de do majeur : ne depend ni de
    l'instrument ni de l'octave, donc identique chez tous les joueurs pour le meme fichier."""
    if not all_notes:
        return 0
    return max(range(-6, 6), key=lambda e: (sum(1 for n in all_notes if (n + e) % 12 in C_MAJOR), -abs(e)))


def beacon_notes(player_id):
    pid = max(1, min(MAX_PLAYERS, int(player_id or 1)))
    return PATTERN_NOTES + [ID_NOTES[pid - 1]]


def beacon_keys(inst, notes):
    """Touches d'un motif sur l'instrument (sans transposition)."""
    keys = []
    for n in notes:
        k = inst.key_for(int(n))
        if k is None:
            raise RuntimeError(f"la note repère {NOTE_NAMES.get(n, n)} n'est pas jouable sur {inst.name}")
        keys.append(k)
    return keys


# ---------------------------------------------------------------- capture de la sortie audio
class LoopbackCapture:
    """Sortie audio du PC (loopback WASAPI sous Windows, moniteur PulseAudio sous Linux) en blocs mono float32.
    soundcard d'abord ; PyAudioWPatch en secours sous Windows. Import paresseux (a faire dans le thread de capture)."""

    def __init__(self, samplerate=48000, blocksize=1024, device=""):
        self.sr = samplerate
        self.block = blocksize
        self.device_pref = (device or "").strip().lower()
        self.device_name = ""
        self.error = ""
        self._backend = None
        self._rec = None
        self._pa = None
        self._stream = None
        self._ch = 1

    @staticmethod
    def list_devices():
        """Noms des sorties audio que l'on peut ecouter (pour les reglages)."""
        try:
            import soundcard as sc
            return [m.name for m in sc.all_microphones(include_loopback=True) if getattr(m, "isloopback", False)]
        except Exception:  # noqa
            return []

    def open(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.error = "numpy manquant"
            return False
        try:
            import soundcard as sc
            mics = [m for m in sc.all_microphones(include_loopback=True) if getattr(m, "isloopback", False)]
            mic = None
            if self.device_pref:
                mic = next((m for m in mics if self.device_pref in m.name.lower()), None)
            if mic is None:
                try:
                    spk = sc.default_speaker()
                    mic = next((m for m in mics if m.id == spk.id or spk.name in m.name), None)
                except Exception:  # noqa
                    mic = None
            if mic is None and mics:
                mic = mics[0]
            if mic is None:
                raise RuntimeError("aucune sortie audio à écouter (loopback / monitor)")
            self._rec = mic.recorder(samplerate=self.sr, channels=1, blocksize=self.block)
            self._rec.__enter__()
            self._backend, self.device_name = "soundcard", mic.name
            return True
        except Exception as e:  # noqa
            self.error = f"soundcard : {e}"
        if sys.platform == "win32":
            try:
                import pyaudiowpatch as pa
                self._pa = pa.PyAudio()
                dev = self._pa.get_default_wasapi_loopback()
                self.sr, self._ch = int(dev["defaultSampleRate"]), max(1, int(dev["maxInputChannels"]))
                self._stream = self._pa.open(format=pa.paFloat32, channels=self._ch, rate=self.sr, input=True,
                                             input_device_index=dev["index"], frames_per_buffer=self.block)
                self._backend, self.device_name = "pyaudiowpatch", dev["name"]
                return True
            except Exception as e:  # noqa
                self.error += f" ; pyaudiowpatch : {e}"
        return False

    def read(self):
        """Bloque jusqu'a `block` trames ; float32 mono (zeros si rien ne joue)."""
        import numpy as np
        if self._backend == "soundcard":
            data = self._rec.record(numframes=self.block)
            return np.asarray(data, dtype=np.float32)[:, 0] if data.ndim == 2 else np.asarray(data, dtype=np.float32)
        raw = self._stream.read(self.block, exception_on_overflow=False)
        arr = np.frombuffer(raw, np.float32)
        if self._ch > 1:
            arr = arr.reshape(-1, self._ch).mean(axis=1)
        return arr

    def close(self):
        try:
            if self._backend == "soundcard" and self._rec is not None:
                self._rec.__exit__(None, None, None)
            elif self._backend == "pyaudiowpatch":
                if self._stream is not None:
                    self._stream.stop_stream()
                    self._stream.close()
                if self._pa is not None:
                    self._pa.terminate()
        except Exception:  # noqa
            pass
        self._rec = self._stream = self._pa = None
        self._backend = None


# ---------------------------------------------------------------- detection des motifs
class BeaconDetector:
    """Detecte les motifs DO5 -> SOL4 -> note d'identite dans un flux audio et renvoie (t_premiere_attaque, numero).
    Fenetre de Hann de 4096 echantillons glissant par pas de 1024 ; a chaque pas, energie a la fondamentale
    et a la 2e harmonique de chaque note suivie (DFT a bin unique), rapportee a l'energie du bloc ; une attaque
    est une montee nette au-dessus du plancher de bruit (25e percentile sur ~2 s), plus selective que les
    demi-tons voisins. Un motif est reconnu quand trois attaques s'enchainent avec les bons ecarts."""
    N, HOP = 4096, 1024

    def __init__(self, sr, gap, tune=1.0, log=None):
        import numpy as np
        self.np = np
        self.sr = float(sr)
        self.gap = float(gap)
        self.log = log or (lambda m: None)
        # canaux : 0 = DO5 (debut + identite 1), 1 = SOL4, puis les autres notes d'identite
        self.notes = list(PATTERN_NOTES) + [n for n in ID_NOTES if n not in PATTERN_NOTES]
        self.id_channel = {i + 1: self.notes.index(n) for i, n in enumerate(ID_NOTES)}
        self.freqs = [note_freq(n, tune) for n in self.notes]
        n = np.arange(self.N)
        w = np.hanning(self.N).astype(np.float32)
        self.w = w
        self.G = float(w.sum() ** 2 / (2 * (w * w).sum()))     # sinusoide pure d'amplitude a : rapport = 1
        rows = []
        for f in self.freqs:
            for m in (1.0, 2.0, 2 ** (-1 / 12), 2 ** (1 / 12)):   # fondamentale, 2e harmonique, demi-tons voisins
                rows.append(w * np.exp(-2j * np.pi * f * m * n / self.sr))
        self.K = np.array(rows, dtype=np.complex64)
        self.ring = np.zeros(self.N, np.float32)
        self.pending = np.zeros(0, np.float32)
        nc = len(self.freqs)
        self.hist = [deque(maxlen=94) for _ in range(nc)]        # ~2 s de rapports (plancher de bruit)
        self.prev = [[0.0, 0.0] for _ in range(nc)]
        self.on = [False] * nc
        self.peak = [0.0] * nc
        self.onsets = deque(maxlen=256)                          # (canal, t, rapport)
        self.masks = []                                          # [(t0, t1, canal)] : nos propres notes
        self.lock_until = 0.0
        self.total_onsets = [0] * nc
        self.matches = 0
        self.matched = []                                        # (t1, numero) des motifs reconnus
        self.tol = max(0.07, 0.5 * self.gap)                     # gigue admise sur chaque ecart (±0,125 s)

    def mask(self, t0, t1, note=None):
        """Ignore les attaques entre t0 et t1 sur le canal de `note` (toutes les notes si None) : nos propres
        notes ne doivent pas etre prises pour celles d'un autre joueur, mais celles des autres, jouees en meme
        temps sur d'autres hauteurs, restent entendues."""
        ch = self.notes.index(int(note)) if note is not None and int(note) in self.notes else None
        self.masks.append((t0, t1, ch))
        if len(self.masks) > 64:
            del self.masks[:-64]

    def recent_onset(self, now, window):
        return any(now - window <= t <= now for _, t, _ in self.onsets)

    def summary(self, t_ref, limit=60):
        """Attaques entendues (note@seconde(force)) et motifs reconnus, pour le journal."""
        names = [NOTE_NAMES.get(n, str(n)) for n in self.notes]
        ons = list(self.onsets)[-limit:]
        txt = " ".join(f"{names[k]}@{t - t_ref:.2f}({r:.2f})" for k, t, r in ons) or "aucune"
        mt = ", ".join(f"joueur {pid} à {t - t_ref:.2f} s" for t, pid in self.matched) or "aucun"
        return f"attaques ({sum(self.total_onsets)} au total, {len(ons)} dernières) : {txt} ; motifs reconnus : {mt}"

    def push(self, block, t_arrival):
        """Ajoute un bloc (float32) arrive a t_arrival (perf_counter). Renvoie (t1, numero) si un motif vient
        d'etre reconnu (t1 : instant de sa premiere attaque), sinon None."""
        np = self.np
        found = None
        self.pending = np.concatenate((self.pending, block)) if len(self.pending) else block
        n_hops = len(self.pending) // self.HOP
        for h in range(n_hops):
            chunk = self.pending[h * self.HOP:(h + 1) * self.HOP]
            t_on = t_arrival - (len(self.pending) - h * self.HOP) / self.sr     # debut de ce pas
            r = self._step(chunk, t_on)
            if r is not None:
                found = r
        self.pending = self.pending[n_hops * self.HOP:]
        return found

    def _step(self, chunk, t_on):
        np = self.np
        self.ring = np.concatenate((self.ring[len(chunk):], chunk))
        xw = self.ring * self.w
        E = float(np.dot(xw, xw)) + 1e-9
        P = np.abs(self.K @ self.ring) ** 2
        for k in range(len(self.freqs)):
            p0, p2, pl, ph = (float(v) for v in P[4 * k:4 * k + 4])
            r = (p0 + p2) / (E * self.G)
            sel = p0 / max(pl, ph, 1e-12)
            # plancher : 25e percentile des 2 dernieres secondes (robuste a une note tenue de la meme hauteur
            # dans la musique) ; seuil plafonne pour qu'un motif franc reste detectable
            floor = float(np.percentile(self.hist[k], 25)) if len(self.hist[k]) > 10 else 0.0
            self.hist[k].append(r)
            rise = r > 2.0 * max(self.prev[k][0], 1e-6)
            self.prev[k] = [self.prev[k][1], r]
            # nouvelle attaque : montee nette au-dessus du plancher ; ou, sur une note qui resonne encore
            # (piano), remontee franche (x2,5 en deux pas) au-dessus de la moitie du dernier pic
            fresh = not self.on[k] and r > max(0.04, min(0.4, 3 * floor)) and rise and sel >= 2.5
            again = self.on[k] and r > 2.5 * max(self.prev[k][0], 1e-6) and r > 0.5 * self.peak[k] and sel >= 2.5
            if fresh or again:
                self.on[k] = True
                self.peak[k] = r
                self.total_onsets[k] += 1
                if not any(a <= t_on <= b and (c is None or c == k) for a, b, c in self.masks):
                    self.onsets.append((k, t_on, r))
            elif self.on[k] and r < 0.5 * self.peak[k]:
                self.on[k] = False
            elif self.on[k] and r > self.peak[k]:
                self.peak[k] = r
        return self._match(t_on)

    def _match(self, now):
        if now < self.lock_until:
            return None
        lo, hi = self.gap - self.tol, self.gap + self.tol
        for k3, t3, r3 in reversed(self.onsets):
            if abs(t3 - now) > 1e-9:
                break
            pid = next((i for i, c in self.id_channel.items() if c == k3), None)
            if pid is None:
                continue
            for k2, t2, r2 in reversed(self.onsets):
                if k2 != 1 or not (lo <= t3 - t2 <= hi):
                    continue
                for k1, t1, r1 in reversed(self.onsets):
                    if k1 != 0 or not (lo <= t2 - t1 <= hi):
                        continue
                    if max(r1, r3) / max(1e-9, min(r1, r3)) > 6.0:
                        continue
                    self.matches += 1
                    self.matched.append((t1, pid))
                    self.lock_until = now + 1.0
                    self.log(f"motif du joueur {pid} reconnu (écarts {t2 - t1:.3f} / {t3 - t2:.3f} s)")
                    return t1, pid
        return None


# ---------------------------------------------------------------- session
class _Aborted(Exception):
    pass


class SyncSession:
    """Machine a etats du mode Multi.
    Top depart : idle -> listening -> beacon (meneur) | armed (suiveur) -> playing -> idle.
    Calibrage : idle -> listening -> calibrating -> idle. Test : idle -> test -> idle."""

    def __init__(self, player, cfg, log=print, notify=None, logfile=None):
        self.player = player
        self.cfg = cfg
        self._ui_log = log
        self.logfile = logfile
        self._t0 = time.perf_counter()
        self.notify = notify or (lambda msg, kind="info": None)
        ensure_defaults(cfg)
        self.state = "idle"
        self.mode = ""              # start | calibrate | test
        self.role = ""
        self.message = ""
        self.last_error = ""        # message d'une session terminee sur une erreur (capture audio, sortie...)
        self.device = ""
        self.deadline = None
        self.countdown_end = None
        self.last_test = None
        self.leader_id = None
        self.players = []           # numeros des joueurs entendus (meneur, calibrage)
        self.abort_reason = ""
        self._abort = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._t_f6 = 0.0
        self._rec = None            # blocs captures pendant l'ecoute (diagnostic), None = pas d'enregistrement

    def log(self, msg):
        """Journal de l'interface + fichier multi.log (horodate depuis le F6) pour comprendre une seance ratee."""
        self._ui_log(msg)
        if self.logfile:
            try:
                with open(self.logfile, "a", encoding="utf-8") as f:
                    f.write(f"[{time.perf_counter() - self._t0:7.2f}s] {msg}\n")
            except Exception:  # noqa
                pass

    def _log_header(self, mode):
        if not self.logfile:
            return
        try:
            import os
            if os.path.exists(self.logfile) and os.path.getsize(self.logfile) > 512 * 1024:
                os.remove(self.logfile)
        except Exception:  # noqa
            pass
        m = self.cfg.get("multi", {})
        self._t0 = time.perf_counter()
        self.log(f"DodoTopia multi {time.strftime('%Y-%m-%d %H:%M:%S')} {mode} : joueur {self.player_id()}, "
                 f"latence {m.get('latency')}, décalage {m.get('offset_ms')} ms, accord {m.get('tune')}, "
                 f"compte à rebours {m.get('countdown')} s + {COUNTDOWN_STEP} s × (n − 1)")

    # ---- API
    def active(self):
        return self.state != "idle"

    def player_id(self):
        return max(1, min(MAX_PLAYERS, int(self.cfg["multi"].get("player_id", 1) or 1)))

    def toggle(self):
        if self.state == "idle":
            return self.start()
        self.abort("stop")
        return False

    def start(self):
        """F6 en mode Multi : ecoute + compte a rebours, puis top depart."""
        return self._begin("start", self._run)

    def calibrate(self):
        """Calibrage a plusieurs : motif du meneur, reponses des suiveurs, echos, decalage enregistre."""
        return self._begin("calibrate", self._run)

    def _begin(self, mode, target):
        with self._lock:
            if self.state != "idle" or (self._thread and self._thread.is_alive()):
                return False
            p = self.player
            if p.state != "stopped":
                p.stop(join=True)
            song = p.current()
            if mode == "start" and not song:
                self.notify(i18n.t("multi.no_song"), "warn")
                return False
            self._t_f6 = time.perf_counter()
            self._log_header(mode)
            self._abort.clear()
            self.abort_reason = ""
            self.state = "listening"
            self.mode = mode
            self.role = ""
            self.leader_id = None
            self.players = []
            self.message = i18n.t("multi.state.listening")
            self.last_error = ""
            self.deadline = None
            self.countdown_end = None
            with p._lock:
                p.state = "sync"
                p.target = "game"
                p._expected = {}
                p.last_stop_reason = ""
            self._thread = threading.Thread(target=target, args=(song,), name="multi", daemon=True)
            self._thread.start()
            return True

    def abort(self, reason=""):
        if self.state != "idle":
            self.abort_reason = reason or self.abort_reason
            self._abort.set()

    def status(self):
        now = time.perf_counter()
        left = None
        if self.state == "listening" and self.countdown_end:
            left = max(0.0, self.countdown_end - now)
        elif self.state in ("beacon", "armed") and self.deadline:
            left = max(0.0, self.deadline - now)
        m = self.cfg.get("multi", {})
        return {"enabled": bool(m.get("enabled")), "state": self.state, "mode": self.mode, "role": self.role,
                "seconds_left": round(left, 1) if left is not None else None, "message": self.message,
                "error": self.last_error, "device": self.device, "latency": m.get("latency"), "test": self.last_test,
                "player_id": self.player_id(), "leader_id": self.leader_id, "players": list(self.players),
                "calib": m.get("calib")}

    # ---- outils
    def _sleep_until(self, t):
        while True:
            if self._abort.is_set():
                raise _Aborted()
            rem = t - time.perf_counter()
            if rem <= 0:
                return
            time.sleep(min(rem, 0.005))

    def _check_abort(self):
        if self._abort.is_set():
            raise _Aborted()

    def _capture_thread(self, cap, q, stop):
        if not cap.open():
            q.put(("fail", cap.error))
            return
        q.put(("ok", cap.device_name))
        try:
            while not stop.is_set():
                block = cap.read()
                q.put((block, time.perf_counter()))
        except Exception as e:  # noqa
            q.put(("fail", i18n.t("multi.error.capture_interrupted", error=e)))
        finally:
            cap.close()

    def _open_capture(self, m):
        """Lance le thread de capture ; renvoie (capture, file, evenement d'arret)."""
        cap = LoopbackCapture(device=m.get("device", ""))
        q = queue.Queue()
        stop = threading.Event()
        threading.Thread(target=self._capture_thread, args=(cap, q, stop), name="multi-capture", daemon=True).start()
        try:
            first = q.get(timeout=6)
        except queue.Empty:
            first = ("fail", i18n.t("multi.error.capture_start"))
        if first[0] == "fail":
            raise RuntimeError(i18n.t("multi.error.no_audio", error=first[1]))
        self.device = first[1]
        self.log(f"multi : écoute de « {self.device} »")
        return cap, q, stop

    def _pump(self, q, det, timeout=0.02):
        """Traite le prochain bloc capture ; renvoie le motif reconnu (t1, numero) ou None."""
        try:
            item = q.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item[0], str):
            if item[0] == "fail":
                raise RuntimeError(i18n.t("multi.error.capture", error=item[1]))
            return None
        self._record(item[0])
        return det.push(item[0], item[1])

    def _record(self, block):
        if self._rec is not None and len(self._rec) < 2400:      # ~50 s a 48 kHz par blocs de 1024
            self._rec.append(block)

    def _save_capture(self, sr, name="multi_ecoute.wav"):
        """Ecrit l'audio capture pendant l'ecoute a cote du journal (16 bits mono) ; ecrase le precedent."""
        blocks, self._rec = self._rec, None
        if not blocks or not self.logfile:
            return
        try:
            import os
            import wave
            import numpy as np
            data = np.concatenate(blocks)
            peak = float(np.abs(data).max()) if len(data) else 0.0
            pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
            path = os.path.join(os.path.dirname(self.logfile), name)
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(sr))
                w.writeframes(pcm.tobytes())
            self.log(f"multi : écoute enregistrée dans {name} ({len(data) / sr:.1f} s, crête {peak:.3f})")
        except Exception as e:  # noqa
            self.log(f"multi : enregistrement de l'écoute impossible ({e})")

    def _play_pattern(self, notes, keys, det, latency, gap, hold):
        """Joue un motif dans le jeu, masque ses propres attaques (sur le canal de chaque note seulement) ;
        renvoie l'instant du premier appui."""
        t0 = None
        for i, k in enumerate(keys):
            tk = self.player.play_keys([k], hold)
            if t0 is None:
                t0 = tk
            det.mask(tk + latency - 0.08, tk + latency + hold + 0.10, notes[i])
            if i < len(keys) - 1:
                self._sleep_until(t0 + (i + 1) * gap)
        return t0

    def _end(self, reason=None):
        """Retour a l'etat idle (le joueur retrouve l'etat stopped s'il etait en attente)."""
        p = self.player
        with p._lock:
            if p.state == "sync":
                p.state = "stopped"
                if reason:
                    p.last_stop_reason = reason
        self.state = "idle"
        self.deadline = None
        self.countdown_end = None

    # ---- top depart et calibrage
    def _run(self, song):
        p, cfg = self.player, self.cfg
        m = ensure_defaults(cfg)
        me = self.player_id()
        stop_cap = None
        reason = None
        try:
            cap, q, stop_cap = self._open_capture(m)
            self._check_abort()
            inst = p.instrument
            my_notes = beacon_notes(me)
            my_keys = beacon_keys(inst, my_notes)
            prepared = p.prepare(song, inst, "game", common_key=True) if self.mode == "start" else None
            self._check_abort()
            latency = m.get("latency")
            if latency is None:
                latency = 0.25
                self.notify(i18n.t("multi.no_latency"), "warn")
            gap, hold, lead = float(m["beacon_gap"]), float(m["beacon_hold"]), float(m["lead"])
            offset = float(m.get("offset_ms", 0)) / 1000.0
            det = BeaconDetector(cap.sr, gap, m.get("tune", 1.0), log=self.log)
            self._rec = []
            self.countdown_end = self._t_f6 + float(m["countdown"]) + (me - 1) * COUNTDOWN_STEP
            extend_until = self.countdown_end + MAX_EXTEND
            self.message = i18n.t("multi.state.listening_start" if self.mode == "start" else "multi.calib.listening")
            t0 = None
            stop_on_input = cfg.get("stop_on_input", True)
            mouse_check = 0.0
            # 1. ecoute : devenir suiveur (motif entendu) ou meneur (compte a rebours ecoule)
            while True:
                self._check_abort()
                now = time.perf_counter()
                found = self._pump(q, det)
                if found is not None:
                    t1, pid = found
                    if self.state == "listening":
                        self.leader_id = pid
                        self.role = "follower"
                        if self.mode == "calibrate":
                            self.state = "calibrating"
                            self._calibrate_follower(q, det, t1, pid, my_notes, my_keys, latency, gap, hold, me)
                            return
                        self.state = "armed"
                        self.deadline = t1 - latency + lead + offset
                        self.message = i18n.t("multi.state.follower", player=pid)
                        self.log(f"multi : suiveur du joueur {pid}, départ dans {self.deadline - now:.2f} s")
                    elif self.state == "armed" and pid != me and pid < (self.leader_id or me):
                        # deux motifs presque en meme temps (F6 simultanes) : tout le monde se cale sur le plus
                        # petit numero, regle identique chez tous, donc coherente ; le meneur ignore les numeros
                        # plus grands (eux se rallient a lui)
                        old = self.deadline
                        self.deadline = t1 - latency + lead + offset
                        self.role = "follower"
                        self.leader_id = pid
                        self.message = i18n.t("multi.state.rally", player=pid)
                        self.log(f"multi : motif du joueur {pid} pendant l'attente, ralliement "
                                 f"(départ {self.deadline - old:+.2f} s)")
                    elif self.state == "armed":
                        self.log(f"multi : motif du joueur {pid} ignoré (meneur {self.leader_id})")
                if self.state == "listening" and now >= self.countdown_end:
                    if det.recent_onset(now, 0.25) and now < extend_until:
                        self.countdown_end = now + 0.5      # quelqu'un commence son motif : on le laisse finir
                        self.log("multi : attaque entendue à la fin du compte à rebours, on attend 0,5 s")
                        continue
                    self.role = "leader"
                    self.leader_id = me
                    if self.mode == "calibrate":
                        self.state = "calibrating"
                        self._calibrate_leader(q, det, my_notes, my_keys, latency, gap, hold, me)
                        return
                    self.state = "beacon"
                    self.message = i18n.t("multi.state.leader_beacon")
                    t0 = self._play_pattern(my_notes, my_keys, det, latency, gap, hold)
                    self.deadline = t0 + lead + offset
                    self.state = "armed"
                    self.message = i18n.t("multi.state.leader_armed")
                    self.log(f"multi : meneur (joueur {me}), note repère envoyée, départ dans {self.deadline - time.perf_counter():.2f} s")
                if self.state == "armed":
                    if stop_on_input and now - mouse_check > 0.03:
                        mouse_check = now
                        if mouse_button_down():
                            raise _Aborted("mouse")
                    if now >= self.deadline - 0.12:
                        break
            # 2. lecture synchronisee
            stop_cap.set()
            self.log("multi : " + det.summary(self._t_f6))
            self._save_capture(cap.sr)
            p.speed = 1.0
            p.lock_speed = True
            if self.deadline < time.perf_counter():
                self.log("multi : analyse trop longue, départ immédiat avec rattrapage")
            p.play_at(self.deadline, prepared, "game")
            self.state = "playing"
            self.message = i18n.t("multi.state.playing", role=self.role, leader=self.leader_id)
            while p.state in ("playing", "paused") and not self._abort.is_set():
                time.sleep(0.1)
        except _Aborted as e:
            reason = str(e) or self.abort_reason or "stop"
            self.log(f"multi : annulé ({reason})")
            self.message = _stop_text(reason)
        except Exception as e:  # noqa
            reason = "error"
            self.log(f"multi : {e}")
            self.message = self.last_error = str(e)
            self.notify(str(e), "warn")
        finally:
            if stop_cap is not None:
                stop_cap.set()
            if self._rec is not None:                    # ecoute interrompue ou calibrage : diagnostic quand meme
                try:
                    self.log("multi : " + det.summary(self._t_f6))
                    self._save_capture(cap.sr)
                except Exception:  # noqa
                    self._rec = None
            if p.state in ("playing", "paused") and self._abort.is_set():
                p.stop()
            self._end(reason)

    def _calibrate_leader(self, q, det, my_notes, my_keys, latency, gap, hold, me):
        """Meneur du calibrage : motif, puis echo de chaque reponse dans son creneau."""
        m = self.cfg["multi"]
        inst = self.player.instrument
        self.message = i18n.t("multi.calib.leader_beacon", player=me)
        t0 = self._play_pattern(my_notes, my_keys, det, latency, gap, hold)
        self.log(f"multi : calibrage, meneur joueur {me}")
        end = t0 + REPLY_BASE + REPLY_STEP * MAX_PLAYERS + 1.0
        heard = {}
        while time.perf_counter() < end:
            self._check_abort()
            left = end - time.perf_counter()
            self.message = i18n.t("multi.calib.leader_waiting", seconds=int(round(left)))
            found = self._pump(q, det)
            if found is None:
                continue
            t1, pid = found
            if pid == me or pid in heard:
                continue
            heard[pid] = t1
            self.players = sorted(heard)
            self.log(f"multi : réponse du joueur {pid}, écho")
            # echo : motif du joueur pid, 0,8 s apres son appui estime
            notes = beacon_notes(pid)
            keys = beacon_keys(inst, notes)
            self._sleep_until(t1 - latency + ECHO_DELAY)
            self._play_pattern(notes, keys, det, latency, gap, hold)
        names = ", ".join(str(k) for k in sorted(heard)) or i18n.t("multi.calib.nobody")
        m["calib"] = {"role": "leader", "leader": me, "players": sorted(heard), "when": time.time()}
        self._save()
        self.message = i18n.t("multi.calib.done", names=names)
        self.notify(self.message, "ok" if heard else "warn")
        self.log("multi : " + self.message)

    def _calibrate_follower(self, q, det, t1, leader, my_notes, my_keys, latency, gap, hold, me):
        """Suiveur du calibrage : reponse dans son creneau, attente de l'echo, decalage = aller-retour / 2."""
        m = self.cfg["multi"]
        if leader == me:
            self.message = i18n.t("multi.calib.same_id", player=me)
            self.notify(self.message, "warn")
            self.log("multi : " + self.message)
            return
        t_leader = t1 - latency                      # appui estime du meneur
        reply_at = t_leader + REPLY_BASE + REPLY_STEP * (me - 1)
        self.message = i18n.t("multi.calib.follower_reply", leader=leader,
                              seconds=round(max(0.0, reply_at - time.perf_counter()), 1))
        self.log(f"multi : calibrage, suiveur du joueur {leader}, réponse dans le créneau {me}")
        # on continue a lire la capture en attendant notre creneau
        while time.perf_counter() < reply_at - 0.02:
            self._check_abort()
            self._pump(q, det)
        self._sleep_until(reply_at)
        S = self._play_pattern(my_notes, my_keys, det, latency, gap, hold)
        self.message = i18n.t("multi.calib.follower_echo")
        end = S + ECHO_DELAY + 3.0
        echo = None
        while time.perf_counter() < end:
            self._check_abort()
            found = self._pump(q, det)
            if found is not None and found[1] == me:
                echo = found[0]
                break
        if echo is None:
            m["calib"] = {"role": "follower", "leader": leader, "rtt_ms": None, "offset_ms": None, "when": time.time()}
            self._save()
            self.message = i18n.t("multi.calib.no_echo", leader=leader)
            self.notify(self.message, "warn")
            self.log("multi : " + self.message)
            return
        rtt = (echo - latency) - S - ECHO_DELAY          # aller-retour par le jeu (moins nos latences locales)
        rtt = max(0.0, rtt)
        offset_ms = -int(round(rtt / 2 * 1000))
        m["offset_ms"] = max(-500, min(500, offset_ms))
        m["calib"] = {"role": "follower", "leader": leader, "rtt_ms": int(round(rtt * 1000)),
                      "offset_ms": m["offset_ms"], "when": time.time()}
        self._save()
        self.message = i18n.t("multi.calib.locked", leader=leader, rtt=int(round(rtt * 1000)), ms=-m["offset_ms"])
        self.notify(self.message, "ok")
        self.log("multi : " + self.message)

    def _save(self):
        try:
            from core import save_config
            save_config(self.cfg)
        except Exception:  # noqa
            pass

    # ---- test de detection (Reglages)
    def selftest(self):
        """Joue son motif dans le jeu et mesure le delai appui -> detection, l'accord et la frequence des notes.
        Lance dans un thread ; resultat dans status()['test']."""
        with self._lock:
            if self.state != "idle":
                return False
            p = self.player
            if p.state != "stopped":
                p.stop(join=True)
            self._abort.clear()
            self.abort_reason = ""
            self.state = "test"
            self.mode = "test"
            self.role = ""
            self.message = i18n.t("multi.test.go")
            self.last_error = ""
            self.last_test = None
            with p._lock:
                p.state = "sync"
                p.target = "game"
                p._expected = {}
            self._thread = threading.Thread(target=self._selftest_run, name="multi-test", daemon=True)
            self._thread.start()
            return True

    def _selftest_run(self):
        import numpy as np
        p, cfg = self.player, self.cfg
        m = ensure_defaults(cfg)
        me = self.player_id()
        stop_cap = None
        result = {"ok": False, "message": ""}
        try:
            cap, q, stop_cap = self._open_capture(m)
            notes = beacon_notes(me)
            keys = beacon_keys(p.instrument, notes)
            gap, hold = float(m["beacon_gap"]), float(m["beacon_hold"])
            det = BeaconDetector(cap.sr, gap, 1.0, log=self.log)
            blocks = []                      # (bloc, t_arrival) des dernieres secondes

            def pump(until):
                found = None
                while time.perf_counter() < until:
                    self._check_abort()
                    try:
                        item = q.get(timeout=0.02)
                    except queue.Empty:
                        continue
                    if isinstance(item[0], str):
                        raise RuntimeError(f"capture audio : {item[1]}")
                    blocks.append(item)
                    r = det.push(item[0], item[1])
                    if r is not None and found is None:
                        found = r
                return found

            self._sleep_until(time.perf_counter() + 3.0)     # le temps de passer sur le jeu
            self.message = i18n.t("multi.test.listening")
            pump(time.perf_counter() + 1.0)
            spurious = sum(det.total_onsets)
            self.message = i18n.t("multi.test.beacon")
            presses = []
            t0 = None
            for i, k in enumerate(keys):
                tk = p.play_keys([k], hold)
                presses.append(tk)
                if t0 is None:
                    t0 = tk
                if i < len(keys) - 1:
                    self._sleep_until(t0 + (i + 1) * gap)
            found = pump(time.perf_counter() + 2.5)
            stop_cap.set()
            if found is None:
                onsets = sum(det.total_onsets) - spurious
                result["message"] = i18n.t("multi.test.nothing", onsets=onsets)
                result["device"] = self.device
                return
            t1, pid = found
            latency = t1 - presses[0]
            # frequence reelle de chaque note : fenetre de 4096 echantillons a t_appui + latence + 30 ms
            sr = cap.sr
            stream = np.concatenate([b for b, _ in blocks]) if blocks else np.zeros(0, np.float32)
            t_end = blocks[-1][1] if blocks else 0.0
            freqs, cents = [], []
            w = np.hanning(4096)
            for i, tk in enumerate(presses):
                t_win = tk + latency + 0.03
                idx = int(round(len(stream) - (t_end - t_win) * sr))
                seg = stream[max(0, idx):max(0, idx) + 4096]
                nominal = note_freq(notes[i])
                if len(seg) < 4096:
                    freqs.append(nominal)
                    cents.append(0.0)
                    continue
                spec = np.abs(np.fft.rfft(seg * w, n=32768))
                fbin = sr / 32768
                lo, hi = int(nominal * 0.94 / fbin), int(nominal * 1.06 / fbin)
                k = lo + int(np.argmax(spec[lo:hi]))
                if 0 < k < len(spec) - 1:
                    a, b, c = spec[k - 1], spec[k], spec[k + 1]
                    d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
                else:
                    d = 0.0
                f = (k + d) * fbin
                freqs.append(round(float(f), 2))
                cents.append(round(1200 * math.log2(f / nominal), 1))
            ratios = [f / note_freq(n) for f, n in zip(freqs, notes)]
            tune = float(sorted(ratios)[len(ratios) // 2]) if ratios else 1.0
            m["latency"] = round(latency, 3)
            m["beacon_freqs"] = freqs
            m["tune"] = round(tune, 5) if 0.9 < tune < 1.1 else 1.0
            self._save()
            worst = max(abs(c) for c in cents) if cents else 0.0
            msg = i18n.t("multi.test.detected", player=pid, ms=int(round(latency * 1000)))
            if pid != me:
                msg += i18n.t("multi.test.wrong_player", player=pid, me=me)
            if abs(1200 * math.log2(tune)) > 5:
                msg += i18n.t("multi.test.tune", cents=f"{1200 * math.log2(tune):+.0f}")
            if worst > 25:
                msg += i18n.t("multi.test.off_pitch", cents=int(round(worst)))
            if spurious:
                msg += i18n.t("multi.test.spurious", n=spurious)
            result.update({"ok": pid == me, "message": msg, "latency": round(latency, 3), "freqs": freqs,
                           "cents": cents, "tune": m["tune"], "device": self.device, "spurious": spurious})
            self.log(f"multi : test ok, latence {latency * 1000:.0f} ms, fréquences {freqs} Hz, accord {m['tune']}")
        except _Aborted:
            result["message"] = i18n.t("multi.test.cancelled")
        except Exception as e:  # noqa
            result["message"] = self.last_error = str(e)
            self.log(f"multi : test : {e}")
        finally:
            if stop_cap is not None:
                stop_cap.set()
            self.last_test = result
            self.message = result.get("message", "")
            self._end()

    def listen_test(self, seconds=30.0):
        """Ecoute seule pendant `seconds` : compte les attaques et motifs parasites (faux signaux)."""
        with self._lock:
            if self.state != "idle":
                return False
            self._abort.clear()
            self.abort_reason = ""
            self.state = "test"
            self.mode = "test"
            self.message = i18n.t("multi.listen.start", seconds=int(round(seconds)))
            self.last_error = ""
            self.last_test = None
            self._thread = threading.Thread(target=self._listen_run, args=(float(seconds),), name="multi-listen", daemon=True)
            self._thread.start()
            return True

    def _listen_run(self, seconds):
        m = ensure_defaults(self.cfg)
        stop_cap = None
        result = {"ok": False, "message": ""}
        try:
            cap, q, stop_cap = self._open_capture(m)
            det = BeaconDetector(cap.sr, float(m["beacon_gap"]), m.get("tune", 1.0), log=self.log)
            self._log_header("écoute")
            self._rec = []
            end = time.perf_counter() + seconds
            t_ref = time.perf_counter()
            peak = 0.0
            while time.perf_counter() < end:
                self._check_abort()
                self.message = i18n.t("multi.listen.progress", seconds=int(round(end - time.perf_counter())))
                try:
                    item = q.get(timeout=0.02)
                except queue.Empty:
                    continue
                if isinstance(item[0], str):
                    raise RuntimeError(i18n.t("multi.error.capture", error=item[1]))
                peak = max(peak, float(abs(item[0]).max()) if len(item[0]) else 0.0)
                self._record(item[0])
                det.push(item[0], item[1])
            n = sum(det.total_onsets)
            if det.matched:
                who = ", ".join(i18n.t("multi.listen.who", player=pid, seconds=round(t - t_ref, 1)) for t, pid in det.matched)
                msg = i18n.t("multi.listen.matched", matches=det.matches, who=who, n=n, seconds=int(round(seconds)))
            else:
                msg = i18n.t("multi.listen.none", n=n, seconds=int(round(seconds)))
            msg += i18n.t("multi.listen.silent") if peak < 1e-4 else ""
            result.update({"ok": True, "message": msg, "matches": det.matches, "onsets": n,
                           "matched": [pid for _, pid in det.matched], "device": self.device, "peak": round(peak, 4)})
            self.log(f"multi : écoute test : {msg}")
            self.log("multi : " + det.summary(t_ref))
            self._save_capture(cap.sr)
        except _Aborted:
            result["message"] = i18n.t("multi.listen.cancelled")
        except Exception as e:  # noqa
            result["message"] = self.last_error = str(e)
        finally:
            if stop_cap is not None:
                stop_cap.set()
            self._rec = None
            self.last_test = result
            self.message = result.get("message", "")
            self.state = "idle"
