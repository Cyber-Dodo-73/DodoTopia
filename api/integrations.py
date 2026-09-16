# -*- coding: utf-8 -*-
"""Integrations : liens dodotopia:// (avec confirmation), protocole Windows, instance unique (arguments
relayes), Discord Rich Presence et fichier « en cours de lecture » pour OBS."""
import os
import re
import sys
import threading
import time
import urllib.parse

import core
import deeplink
import i18n
import online
import platform_io
import presence
import settings_schema
import terms

from ._common import log

PROTOCOL_KEY = r"Software\Classes\dodotopia"
MAX_PENDING_LINKS = 5
NOWPLAYING_NAME = "nowplaying.txt"
# Adresses que l'interface peut ouvrir dans le navigateur (menu Partager, sources) : https et ces domaines (ou
# leurs sous-domaines) seulement, plus l'hote du serveur DodoTopia configure. Rien d'autre ne sort de l'app.
EXTERNAL_HOSTS = ("x.com", "twitter.com", "bsky.app", "discord.com", "discord.gg", "dodotopia.cyber-dodo.fr",
                  "onlinesequencer.net")
EXPORTS_DIR_NAME = "exports"
EXPORT_MAX_BYTES = 5 * 1024 * 1024


class IntegrationsMixin:
    # ---------------------------------------------------------- initialisation / fermeture
    def _init_integrations(self):
        self._deeplink = None               # demande de confirmation en cours (voir _deeplink_state)
        self._deeplink_seq = 0
        self._pending_links = []            # liens recus avant l'acceptation des CGU
        self._presence = None               # presence.RichPresence | None
        self._activity_key = None
        self._activity_started = None
        self._nowplaying_text = None        # dernier texte ecrit dans nowplaying.txt (None = inconnu)
        self._integrations_warned = set()
        self._on_rich_presence()

    def _integration_setting(self, name):
        o = self._cfg.get("online") or {}
        return bool(o.get(name, settings_schema.INTEGRATION_DEFAULTS[name]))

    def _integrations_close(self):
        """Fermeture : presence Discord effacee, nowplaying.txt vide. Idempotent."""
        pres, self._presence = getattr(self, "_presence", None), None
        if pres is not None:
            try:
                pres.close()
            except Exception as e:  # noqa
                log.info("Discord : fermeture : %r", e)
        if getattr(self, "_nowplaying_text", None):
            self._write_nowplaying("")

    def _warn_once(self, key, msg):
        warned = getattr(self, "_integrations_warned", None)
        if warned is None:
            warned = self._integrations_warned = set()
        if key not in warned:
            warned.add(key)
            log.warning("%s", msg)

    # ---------------------------------------------------------- liens dodotopia://
    def _deeplink_label(self, parsed):
        a = parsed["action"]
        if a == "song":
            return i18n.t("integrations.deeplink.confirm_song", id=str(parsed["id"]))
        if a == "room":
            return i18n.t("integrations.deeplink.confirm_room", code=parsed["code"])
        if a == "drawing":
            return i18n.t("integrations.deeplink.confirm_drawing", id=str(parsed["id"]))
        return i18n.t("integrations.deeplink.confirm_import", host=parsed["host"])

    def _deeplink_state(self):
        """get_state()["deeplink"] : {id, action, label, params} | None (label traduit a l'affichage)."""
        req = getattr(self, "_deeplink", None)
        if not req:
            return None
        parsed = dict(req["params"], action=req["action"])
        return {"id": req["id"], "action": req["action"], "label": self._deeplink_label(parsed),
                "params": dict(req["params"])}

    def handle_deeplink(self, url):
        """Lien dodotopia:// recu (ligne de commande, autre lancement) : valide, puis place une demande de
        confirmation dans get_state()["deeplink"]. Rien n'agit sans deeplink_confirm(id).
        Renvoie {ok, pending, error, deeplink}."""
        parsed = deeplink.parse(url)
        if not parsed:
            self._log(f"lien refusé : {str(url)[:120]!r}")
            self._notify(i18n.t("integrations.deeplink.invalid"), "warn")
            return {"ok": False, "pending": False, "error": "invalid", "deeplink": None}
        if terms.required(self._cfg):
            pending = getattr(self, "_pending_links", None)
            if pending is None:
                pending = self._pending_links = []
            if url not in pending:
                pending.append(url)
                del pending[:-MAX_PENDING_LINKS]
            self._notify(i18n.t("integrations.deeplink.pending_terms"), "info")
            return {"ok": False, "pending": True, "error": "terms.required", "deeplink": None}
        with self._ui_lock:
            self._deeplink_seq = getattr(self, "_deeplink_seq", 0) + 1
            params = {k: v for k, v in parsed.items() if k != "action"}
            self._deeplink = {"id": self._deeplink_seq, "action": parsed["action"], "params": params}
            state = self._deeplink_state()
        self._log(f"lien reçu : {parsed['action']} {params}")
        return {"ok": True, "pending": False, "error": None, "deeplink": state}

    def _flush_pending_links(self):
        """Apres l'acceptation des CGU : les liens mis en attente deviennent des demandes de confirmation."""
        links, self._pending_links = list(getattr(self, "_pending_links", None) or []), []
        for url in links:
            self.handle_deeplink(url)

    def _take_deeplink(self, req_id):
        with self._ui_lock:
            req = getattr(self, "_deeplink", None)
            try:
                same = req is not None and int(req_id) == int(req["id"])
            except (TypeError, ValueError):
                same = False
            if not same:
                return None
            self._deeplink = None
            return req

    def deeplink_dismiss(self, req_id):
        """Refus de la demande de confirmation."""
        if self._take_deeplink(req_id):
            self._log("lien ignoré par l'utilisateur")
        return self.get_state()

    def deeplink_confirm(self, req_id):
        """Execute la demande confirmee : song -> telechargement puis selection ; room -> mode salon et
        room_join ; import -> import par lien (le morceau importe est selectionne) ; drawing -> grille du
        dessin chargee dans l'activite Dessin (l'interface bascule d'elle-meme quand elle est prete)."""
        req = self._take_deeplink(req_id)
        if not req:
            self._notify(i18n.t("integrations.deeplink.expired"), "info")
            return self.get_state()
        action, params = req["action"], req["params"]
        self._log(f"lien confirmé : {action} {params}")
        if action == "song":
            oid = str(params["id"])
            self._tab = "music"
            ok, _ = self._online_call(self._online.download, oid)
            if ok:
                threading.Thread(target=self._select_when_downloaded, args=(oid,), name="deeplink-song",
                                 daemon=True).start()
            return self.get_state()
        if action == "room":
            code = params["code"]
            self._tab = "music"
            if self._room.active():
                if self._room.code == code:
                    self._notify(i18n.t("integrations.deeplink.room_already", code=code), "info")
                    return self.get_state()
                self._online_call(self._room.leave)
            if self._cfg.get("multi", {}).get("mode") != "room":
                self.set_play_mode("room")
            return self.room_join(code)
        if action == "drawing":
            self._tab = "image"
            ok, _ = self._online_call(self._online.open_drawing, params["id"], self._on_drawing_loaded)
            if ok:
                self._notify(i18n.t("integrations.deeplink.drawing_loading"), "info")
            return self.get_state()
        self._tab = "music"
        ok, _ = self._online_call(self._online.import_url, params["url"])
        if ok:
            self._notify(i18n.t("integrations.deeplink.import_started", host=params["host"]), "info")
        return self.get_state()

    # ---------------------------------------------------------- partage : navigateur et export d'image
    def _external_allowed(self, url):
        """Vrai pour une adresse https d'un domaine de EXTERNAL_HOSTS (ou du serveur configure)."""
        if (not isinstance(url, str) or not url or len(url) > 4096
                or any(ord(c) <= 0x20 or ord(c) == 0x7F or c == "\\" for c in url)):
            return False
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        if parts.scheme.lower() != "https" or "@" in parts.netloc or port not in (None, 443):
            return False
        host = (parts.hostname or "").lower().rstrip(".")
        allowed = list(EXTERNAL_HOSTS)
        server = urllib.parse.urlsplit(online.ensure_defaults(self._cfg)["server_url"])
        if server.scheme == "https" and server.hostname:
            allowed.append(server.hostname.lower())
        return any(host == d or host.endswith("." + d) for d in allowed)

    def open_external(self, url):
        """Ouvre une adresse de partage dans le navigateur (liste blanche EXTERNAL_HOSTS). {ok, error}."""
        if not self._external_allowed(url):
            self._log(f"adresse externe refusée : {str(url)[:120]!r}")
            self._notify(i18n.t("integrations.external.refused"), "warn")
            return {"ok": False, "error": "not_allowed"}
        try:
            platform_io.open_url(url)
        except Exception as e:  # noqa
            self._notify(i18n.t("api.browser_failed", error=e), "warn")
            return {"ok": False, "error": "browser"}
        return {"ok": True, "error": None}

    def save_drawing_png(self, data_url, name="dessin"):
        """Enregistre l'image exportee par l'activite Dessin (data URL PNG, 5 Mo au plus) dans
        DATA_DIR/exports/ sous un nom assaini, puis ouvre le dossier. {ok, path, name, error}."""
        try:
            data = online.decode_png_data_url(data_url, EXPORT_MAX_BYTES)
        except ValueError as e:
            self._notify(i18n.t("integrations.export.too_big") if str(e) == "size"
                         else i18n.t("integrations.export.invalid"), "warn")
            return {"ok": False, "path": None, "name": None, "error": str(e)}
        folder = os.path.join(core.DATA_DIR, EXPORTS_DIR_NAME)
        stem = re.sub(r"(?i)\.png$", "", str(name or ""))
        try:
            os.makedirs(folder, exist_ok=True)
            path = core.safe_join(folder, stem, default="dessin", ext=".png")
            base, ext = os.path.splitext(path)
            n = 2
            while os.path.exists(path):
                path = f"{base} ({n}){ext}"
                n += 1
            with open(path, "xb") as f:
                f.write(data)
        except (OSError, ValueError) as e:
            self._log(f"export du dessin : {e}")
            self._notify(i18n.t("integrations.export.failed", error=str(e)), "warn")
            return {"ok": False, "path": None, "name": None, "error": "write"}
        self._log(f"dessin exporté : {path}")
        self._notify(i18n.t("integrations.export.saved", name=os.path.basename(path)), "ok")
        try:
            platform_io.open_folder(folder)
        except Exception as e:  # noqa
            self._warn_once("exports", f"dossier des exports : {e!r}")
        return {"ok": True, "path": path, "name": os.path.basename(path), "error": None}

    def _select_when_downloaded(self, oid, timeout=180.0, poll=0.25):
        """Attend la fin du telechargement lance par un lien, puis selectionne le morceau dans la bibliotheque
        (sauf lecture ou salon en cours : on ne coupe rien)."""
        svc = self._online
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with svc._lock:
                job = dict(svc.jobs["downloads"].get(oid) or {})
            st = job.get("state")
            if st == "error":
                return None
            if st == "done":
                sid = job.get("song_id")
                p = self._player
                if sid and p.state == "stopped" and not self._room.active():
                    path = os.path.join(p.songs_folder, os.path.basename(str(sid)))
                    if path in p.songs:
                        p.select(p.songs.index(path))
                return sid
            time.sleep(poll)
        return None

    def _on_forwarded_argv(self, argv):
        """Arguments d'un deuxieme lancement (single_instance) : liens a confirmer, fenetre au premier plan."""
        for url in deeplink.urls_from_argv(argv):
            self.handle_deeplink(url)
        self._bring_to_front()

    def _bring_to_front(self):
        w = self._window
        if not w:
            return
        self._minimized = False
        for step in (lambda: w.restore(), lambda: w.show(), lambda: setattr(w, "on_top", True),
                     lambda: setattr(w, "on_top", False)):
            try:
                step()
            except Exception as e:  # noqa : methode absente selon le moteur
                self._warn_once("front", f"fenêtre au premier plan : {e!r}")

    # ---------------------------------------------------------- protocole Windows (version portable / sources)
    @staticmethod
    def _protocol_command():
        """(commande, icone) de la cle dodotopia : l'exe gele, sinon pythonw app.py."""
        if core.FROZEN:
            exe = sys.executable
            return f'"{exe}" --url "%1"', f'"{exe}",0'
        py = sys.executable
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.isfile(pyw):
            py = pyw
        app_py = os.path.join(core.RES_DIR, "app.py")
        return f'"{py}" "{app_py}" --url "%1"', os.path.join(core.RES_DIR, "assets", "logo.ico")

    def register_protocol(self):
        """Associe les liens dodotopia:// a ce DodoTopia (HKCU, sans droits administrateur). {ok, error}."""
        try:
            import winreg
        except ImportError:
            return {"ok": False, "error": i18n.t("integrations.protocol.windows_only")}
        cmd, icon = self._protocol_command()
        try:
            hk = winreg.HKEY_CURRENT_USER
            with winreg.CreateKey(hk, PROTOCOL_KEY) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:DodoTopia")
                winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(hk, PROTOCOL_KEY + r"\DefaultIcon") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, icon)
            with winreg.CreateKey(hk, PROTOCOL_KEY + r"\shell\open\command") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        except OSError as e:
            self._log(f"protocole dodotopia : écriture du registre impossible : {e}")
            return {"ok": False, "error": i18n.t("integrations.protocol.failed", error=str(e))}
        self._log(f"protocole dodotopia enregistré : {cmd}")
        self._notify(i18n.t("integrations.protocol.registered"), "ok")
        return {"ok": True, "error": None}

    def protocol_status(self):
        """{registered, command, current} : current = la cle pointe vers ce DodoTopia."""
        try:
            import winreg
        except ImportError:
            return {"registered": False, "command": "", "current": False}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROTOCOL_KEY + r"\shell\open\command") as k:
                cmd = str(winreg.QueryValueEx(k, "")[0] or "")
        except OSError:
            return {"registered": False, "command": "", "current": False}
        return {"registered": "--url" in cmd, "command": cmd,
                "current": cmd.lower() == self._protocol_command()[0].lower()}

    # ---------------------------------------------------------- activite : Discord et OBS
    def _instrument_label(self):
        inst = self._player.instrument
        if i18n.current_lang() != "fr" and getattr(inst, "label_en", ""):
            return inst.label_en
        return inst.name

    def _current_title(self, songs):
        p = self._player
        idx = p.index if p.songs else -1
        if songs and 0 <= idx < len(songs):
            return songs[idx].get("name") or ""
        cur = p.current()
        return core.clean_title(os.path.basename(cur)) if cur else ""

    def _activity_snapshot(self, songs=None, room_status=None):
        """Instantane de l'activite pour presence.build_activity (aucune E/S)."""
        p = self._player
        playing = p.state in ("playing", "paused")
        snap = {"kind": "idle", "title": "", "instrument": "", "started_at": None, "dishes": 0,
                "room_code": "", "players": 0, "max_players": 8,
                "server_url": (self._cfg.get("online") or {}).get("server_url", "")}
        if playing and p.target == "game":
            snap["title"] = self._current_title(songs)
            snap["instrument"] = self._instrument_label()
        if self._room.active():
            rs = (room_status if room_status is not None else self._room.status()).get("room") or {}
            snap.update(kind="room", room_code=rs.get("code") or "", players=len(rs.get("players") or []),
                        max_players=int(rs.get("max_players") or 8))
        elif snap["title"]:
            snap["kind"] = "play"
        elif self._drawer.state in ("drawing", "autocal"):
            snap["kind"] = "draw"
        elif self._cook.state == "cooking":
            snap["kind"] = "cook"
            snap["dishes"] = int(getattr(self._cook, "dishes", 0) or 0)
        if snap["kind"] != "idle":
            key = (snap["kind"], snap["title"], snap["room_code"])
            if key != getattr(self, "_activity_key", None):
                self._activity_key = key
                self._activity_started = int(time.time())
            snap["started_at"] = self._activity_started
        else:
            self._activity_key = None
            self._activity_started = None
        return snap

    def _integrations_tick(self, songs=None, room_status=None):
        """Appele par get_state() : presence Discord (le module limite la frequence) et nowplaying.txt."""
        pres = getattr(self, "_presence", None)
        if pres is not None:
            try:
                pres.update(self._activity_snapshot(songs, room_status))
            except Exception as e:  # noqa
                self._warn_once("presence", f"Discord : instantané impossible : {e!r}")
        if self._integration_setting("now_playing_file"):
            p = self._player
            text = ""
            if p.state in ("playing", "paused"):
                title = self._current_title(songs)
                if title:
                    text = i18n.t("integrations.now_playing.line", title=title, instrument=self._instrument_label())
            if text != getattr(self, "_nowplaying_text", None):
                self._write_nowplaying(text)

    def _nowplaying_path(self):
        return os.path.join(core.DATA_DIR, NOWPLAYING_NAME)

    def _write_nowplaying(self, text):
        """Ecriture atomique (tmp + replace) ; OBS relit le fichier de lui-meme."""
        path = self._nowplaying_path()
        tmp = f"{path}.tmp-{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            try:
                os.replace(tmp, path)
            except PermissionError:
                # fichier tenu ouvert par un autre programme sous Windows : ecriture directe
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
            self._nowplaying_text = text
        except OSError as e:
            self._nowplaying_text = text          # pas de nouvel essai a chaque tick
            self._warn_once("nowplaying", f"nowplaying.txt : écriture impossible : {e}")
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ---- effets de bord des reglages (settings_schema)
    def _on_rich_presence(self):
        on = self._integration_setting("rich_presence") and bool(presence.DISCORD_CLIENT_ID)
        pres = getattr(self, "_presence", None)
        if on and pres is None:
            self._presence = presence.RichPresence(client_id=presence.DISCORD_CLIENT_ID)
            self._presence.start()
        elif not on and pres is not None:
            self._presence = None
            pres.close()

    def _on_now_playing_file(self):
        if self._integration_setting("now_playing_file"):
            self._nowplaying_text = None          # reecrit au prochain get_state()
        elif os.path.exists(self._nowplaying_path()):
            self._write_nowplaying("")
