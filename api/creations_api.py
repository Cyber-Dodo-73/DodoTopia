# -*- coding: utf-8 -*-
"""Mes créations : les photos, peintures (creations.py) et musiques (game_music.py) du jeu gardées sur cet
ordinateur — liste, vignettes, affichage, remplacement avec sauvegarde, restauration, export, ajout (photo,
musique) et suppression d'un ajout. Rien n'est lu dans get_state() : l'onglet demande la liste quand il s'ouvre,
puis les vignettes une à une (celles qui sont visibles).

Par défaut la liste ne contient que ce que CE joueur a fait (album photo, peintures, musiques enregistrées) ;
le réglage `creations.show_cache` y ajoute le cache du jeu (images des autres joueurs, cadres, pochettes…)."""
import os
import shutil
import threading
import time

import webview

import core
import creations
import game_music
import i18n
import platform_io
import studio

from ._common import log

THUMB_CACHE_MAX = 1500      # vignettes gardées en mémoire (≈ 10 Ko chacune)
LIST_TTL = 20.0             # secondes avant de revérifier l'empreinte du dossier


class CreationsMixin:
    # ---------------------------------------------------------- outils internes
    def _creations_state(self):
        """État interne créé à la demande (les tests construisent l'Api sans __init__)."""
        st = getattr(self, "_creations", None)
        if st is None:
            st = self._creations = {"lock": threading.RLock(), "folder": None, "sig": None, "at": 0.0,
                                    "items": [], "by_id": {}, "my_id": None, "thumbs": {}}
        return st

    def _creations_folder(self):
        pref = ((self._cfg.get("creations") or {}).get("folder") if isinstance(self._cfg.get("creations"), dict) else None)
        return creations.find_folder(pref)

    def _creations_backup_dir(self):
        return os.path.join(core.DATA_DIR, "creations_backup")

    def _creations_show_cache(self):
        node = self._cfg.get("creations")
        return bool(node.get("show_cache")) if isinstance(node, dict) else False

    def _creations_music_refs(self, st):
        """(numéro du joueur, valeur f32) à écrire dans une musique convertie depuis un MIDI."""
        mine = [it["path"] for it in st["items"] if it.get("section") == "music"]
        return game_music.reference_values(mine, game_music.my_uid(st["folder"]))

    def _creations_scan(self, refresh=False):
        """Liste à jour (relue si le dossier a changé, au plus toutes les LIST_TTL secondes)."""
        st = self._creations_state()
        with st["lock"]:
            folder = self._creations_folder()
            now = time.time()
            if folder != st["folder"]:
                refresh = True
            if not refresh and st["folder"] and now - st["at"] < LIST_TTL:
                return st
            music_root = game_music.root_of(folder)
            sig = (creations.folder_signature(folder) + game_music.signature(music_root)) if folder else None
            if refresh or sig != st["sig"]:
                if folder:
                    my_id = creations.guess_player_id(folder)
                    items = creations.scan(folder, my_id) + game_music.scan(music_root, my_id)
                    items.sort(key=lambda g: (-(g["created"] or 0), g["base"]))
                else:
                    my_id, items = None, []
                st.update(folder=folder, sig=sig, items=items, by_id={it["id"]: it for it in items}, my_id=my_id)
            st["at"] = now
            return st

    def _creations_item(self, item_id):
        st = self._creations_scan()
        it = st["by_id"].get(str(item_id or ""))
        if it is None:
            # le dossier a peut-être changé depuis la liste affichée : une relecture avant d'abandonner
            st = self._creations_scan(refresh=True)
            it = st["by_id"].get(str(item_id or ""))
        return it

    def _creations_public(self, it, backup_dir, added=None):
        out = {"id": it["id"], "section": it.get("section", "cache"), "cat": it["cat"], "kind": it["kind"],
               "player": it["player"], "mine": it["mine"],
               "created": it["created"], "modified": it["modified"], "w": it["w"], "h": it["h"],
               "variants": [{"folder": v["folder"], "name": v["name"], "w": v["w"], "h": v["h"], "bytes": v["bytes"]}
                            for v in it["variants"]],
               "indexed": bool(it.get("indexed")), "backup": creations.has_backup(it, backup_dir),
               "added": creations.is_added(it, creations.added_load(backup_dir) if added is None else added)}
        if it["cat"] == "music":
            out.update(name=it["name"], duration=it["duration"], notes=it["notes"], remote=it["remote"])
        return out

    def _creations_forget_thumbs(self, it):
        st = self._creations_state()
        with st["lock"]:
            for v in it["variants"]:
                st["thumbs"].pop(v["path"], None)

    # ---------------------------------------------------------- liste et images
    def creations_list(self, refresh=False):
        """{ok, available, folder, found, my_id, show_cache, total, items, sections:{section: n},
        cats:{cat: n} (catégories du cache), error}. Sans le réglage `creations.show_cache`, seules les
        créations de ce joueur sont renvoyées (album photo, peintures, musiques)."""
        show_cache = self._creations_show_cache()
        empty = {"ok": False, "folder": None, "found": False, "my_id": None, "show_cache": show_cache,
                 "total": 0, "items": [], "sections": {}, "cats": {}}
        if not creations.available():
            return dict(empty, available=False, error="no_crypto")
        try:
            st = self._creations_scan(refresh=bool(refresh))
        except Exception as e:  # noqa - dossier illisible : l'interface affiche le message
            log.exception("mes créations : lecture du dossier")
            return dict(empty, available=True, error=str(e))
        backup_dir = self._creations_backup_dir()
        added = creations.added_load(backup_dir)
        with st["lock"]:
            items = [self._creations_public(it, backup_dir, added) for it in st["items"]
                     if show_cache or it.get("section") != "cache"]
            folder, my_id = st["folder"], st["my_id"]
        sections, cats = {}, {}
        for it in items:
            sections[it["section"]] = sections.get(it["section"], 0) + 1
            if it["section"] == "cache":
                cats[it["cat"]] = cats.get(it["cat"], 0) + 1
        return {"ok": True, "available": True, "folder": folder, "found": bool(folder), "my_id": my_id,
                "show_cache": show_cache, "total": len(items), "items": items, "sections": sections,
                "cats": cats, "error": None}

    def creations_thumb(self, item_id):
        """Vignette (data URL) d'une création : {ok, id, data, w, h} ; mise en cache tant que le fichier ne change pas."""
        it = self._creations_item(item_id)
        if it is None:
            return {"ok": False, "id": item_id, "error": "unknown"}
        st = self._creations_state()
        path = it["thumb"]
        if not path:                                # musique : pas d'image
            return {"ok": False, "id": item_id, "error": "no_image"}
        try:
            key = (path, os.path.getmtime(path), os.path.getsize(path))
        except OSError:
            return {"ok": False, "id": item_id, "error": "unknown"}
        with st["lock"]:
            cached = st["thumbs"].get(path)
            if cached and cached[0] == key:
                data, w, h = cached[1]
                return {"ok": True, "id": it["id"], "data": data, "w": w, "h": h}
        try:
            data, w, h = creations.thumbnail(path, drawing=bool(it.get("indexed")))
        except creations.CreationsError as e:
            return {"ok": False, "id": item_id, "error": str(e)}
        with st["lock"]:
            if len(st["thumbs"]) >= THUMB_CACHE_MAX:
                st["thumbs"].clear()
            st["thumbs"][path] = (key, (data, w, h))
        return {"ok": True, "id": it["id"], "data": data, "w": w, "h": h}

    def creations_view(self, item_id):
        """Plus grande variante en data URL pour l'affichage en grand : {ok, id, data, w, h, item}."""
        it = self._creations_item(item_id)
        if it is None:
            return {"ok": False, "id": item_id, "error": "unknown"}
        if it["cat"] == "music":
            # pas d'image : le détail de l'enregistrement (notes, joueurs, instruments)
            try:
                info = game_music.summary(game_music.read(it["path"]))
            except game_music.MusicError as e:
                return {"ok": False, "id": item_id, "error": str(e)}
            return {"ok": True, "id": it["id"], "data": None, "w": 0, "h": 0, "music": info,
                    "item": self._creations_public(it, self._creations_backup_dir())}
        try:
            data, w, h = creations.image_data_url(it["largest"], creations.VIEW_PX, drawing=bool(it.get("indexed")))
        except creations.CreationsError as e:
            return {"ok": False, "id": item_id, "error": str(e)}
        return {"ok": True, "id": it["id"], "data": data, "w": w, "h": h,
                "item": self._creations_public(it, self._creations_backup_dir())}

    # ---------------------------------------------------------- actions (gardées par les CGU)
    def creations_replace_dialog(self, item_id, fit="cover"):
        """Choisit une image sur le disque puis la met à la place de la création (`fit` : cover = remplir en
        recadrant, contain = ajuster avec des bandes)."""
        it = self._creations_item(item_id)
        if it is None:
            self._notify(i18n.t("api.creations.unknown"), "warn")
            return {"ok": False, "error": "unknown"}
        if not self._window:
            return {"ok": False, "error": "no_window"}
        path = self._creations_pick("music" if it["cat"] == "music" else "photo")
        if not path:
            return {"ok": False, "error": "cancelled"}
        return self.creations_replace(item_id, path, fit)

    def _creations_pick(self, section):
        """Fichier choisi par l'utilisateur : un MIDI (ou un enregistrement du jeu) pour une musique, sinon une image."""
        kinds = (i18n.t("api.dialog.game_music"), i18n.t("api.dialog.all_files")) if section == "music" \
            else (i18n.t("api.dialog.images"), i18n.t("api.dialog.all_files"))
        files = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=kinds)
        return str(files[0]) if files else None

    def _creations_replace_music(self, it, path):
        """Écrit `path` (MIDI converti pour le piano, ou .bin du jeu) à la place de l'enregistrement, original
        sauvegardé une seule fois. Le nom du fichier ne change pas (il porte le titre affiché dans le jeu)."""
        st = self._creations_state()
        uid, extra = self._creations_music_refs(st)
        data, _ = game_music.render_source(path, self._cfg, uid, extra)
        v = it["variants"][0]
        bk = creations.backup_path(self._creations_backup_dir(), v)
        try:
            if not os.path.isfile(bk):
                os.makedirs(os.path.dirname(bk), exist_ok=True)
                shutil.copy2(v["path"], bk)
            creations._write_atomic(v["path"], data)
        except OSError as e:
            raise creations.CreationsError(str(e)) from e
        return 1

    def creations_replace(self, item_id, path, fit="cover"):
        """Remplace toutes les tailles de la création par l'image `path` (amenée à chaque taille selon `fit`,
        rechiffrée, original sauvegardé)."""
        it = self._creations_item(item_id)
        if it is None:
            self._notify(i18n.t("api.creations.unknown"), "warn")
            return {"ok": False, "error": "unknown"}
        if it.get("section") == "painting":
            # le fichier local d'une peinture n'est que son aperçu : le vrai dessin est sur les serveurs du jeu
            # (constaté en jeu le 2026-10-03 : l'aperçu changeait, pas la toile)
            self._notify(i18n.t("api.creations.painting_readonly"), "warn")
            return {"ok": False, "error": "painting_readonly"}
        path = str(path or "")
        if not os.path.isfile(path):
            self._notify(i18n.t("api.image.not_image", name=os.path.basename(path)), "warn")
            return {"ok": False, "error": "not_image"}
        try:
            if it["cat"] == "music":
                n = self._creations_replace_music(it, path)
            else:
                n = creations.replace_item(it, path, self._creations_backup_dir(), fit=str(fit or "cover"))
        except (creations.CreationsError, game_music.MusicError) as e:
            msg = i18n.t("api.creations.write_failed", error=e) if "denied" in str(e).lower() or "refus" in str(e).lower() \
                else i18n.t("api.creations.failed", error=e)
            self._notify(msg, "danger")
            return {"ok": False, "error": str(e)}
        self._creations_forget_thumbs(it)
        self._creations_scan(refresh=True)
        it2 = self._creations_item(item_id) or it
        self._notify(i18n.t("api.creations.replaced", n=n, name=os.path.basename(path)), "ok")
        return {"ok": True, "files": n, "item": self._creations_public(it2, self._creations_backup_dir())}

    def creations_restore(self, item_id):
        """Remet les fichiers d'origine (sauvegardés au premier remplacement)."""
        it = self._creations_item(item_id)
        if it is None:
            self._notify(i18n.t("api.creations.unknown"), "warn")
            return {"ok": False, "error": "unknown"}
        try:
            n = creations.restore_item(it, self._creations_backup_dir())
        except creations.CreationsError as e:
            self._notify(i18n.t("api.creations.write_failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        if not n:
            self._notify(i18n.t("api.creations.no_backup"), "warn")
            return {"ok": False, "error": "no_backup"}
        self._creations_forget_thumbs(it)
        self._creations_scan(refresh=True)
        it2 = self._creations_item(item_id) or it
        self._notify(i18n.t("api.creations.restored", n=n), "ok")
        return {"ok": True, "files": n, "item": self._creations_public(it2, self._creations_backup_dir())}

    def creations_export(self, item_id):
        """Enregistre la plus grande taille, déchiffrée, où l'utilisateur veut."""
        it = self._creations_item(item_id)
        if it is None:
            self._notify(i18n.t("api.creations.unknown"), "warn")
            return {"ok": False, "error": "unknown"}
        if not self._window:
            return {"ok": False, "error": "no_window"}
        music = it["cat"] == "music"
        try:
            ext = ".mid" if music else (creations.image_ext(creations.read_image(it["largest"])) or ".png")
        except creations.CreationsError as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        name = (game_music.safe_title(it["name"]) if music else creations.suggested_export_name(it)) + ext
        dest = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=name)
        if isinstance(dest, (list, tuple)):
            dest = dest[0] if dest else None
        if not dest:
            return {"ok": False, "error": "cancelled"}
        try:
            if music:
                dest = str(dest)
                out = game_music.to_midi(game_music.read(it["path"]),
                                         dest if dest.lower().endswith((".mid", ".midi")) else dest + ".mid")
            else:
                out = creations.export_item(it, str(dest))
        except (creations.CreationsError, game_music.MusicError) as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        self._notify(i18n.t("api.creations.exported", name=os.path.basename(out)), "ok")
        return {"ok": True, "path": out}

    def creations_choose_folder(self):
        """Indique à la main le dossier ScreenCapture (jeu installé ailleurs, autre compte Windows)."""
        if not self._window:
            return {"ok": False, "error": "no_window"}
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if isinstance(res, (list, tuple)):
            res = res[0] if res else None
        if not res:
            return {"ok": False, "error": "cancelled"}
        return self.creations_set_folder(str(res))

    def creations_set_folder(self, path):
        path = str(path or "").strip()
        if not creations.looks_like_folder(path):
            self._notify(i18n.t("api.creations.folder_bad"), "warn")
            return {"ok": False, "error": "bad_folder"}
        node = self._cfg.get("creations")
        if not isinstance(node, dict):
            node = self._cfg["creations"] = {}
        node["folder"] = path
        core.save_config(self._cfg)
        self._creations_scan(refresh=True)
        self._notify(i18n.t("api.creations.folder_set", path=path), "ok")
        return {"ok": True, "folder": path}

    def creations_open_folder(self):
        folder = self._creations_folder()
        if not folder:
            self._notify(i18n.t("api.creations.folder_missing"), "warn")
            return False
        platform_io.open_folder(folder)
        return True

    # ---------------------------------------------------------- ajout / suppression d'un ajout
    def creations_add_dialog(self, section, fit="cover"):
        """Choisit un fichier puis l'AJOUTE aux créations du jeu, sans rien remplacer : `photo` (image -> album
        photo) ou `music` (MIDI -> enregistrement au piano). Une peinture ne peut pas être ajoutée : c'est un
        objet de l'inventaire, créé par le serveur du jeu."""
        section = str(section or "")
        if section not in ("photo", "music"):
            return {"ok": False, "error": "bad_section"}
        if not self._window:
            return {"ok": False, "error": "no_window"}
        path = self._creations_pick(section)
        if not path:
            return {"ok": False, "error": "cancelled"}
        return self.creations_add(section, path, fit)

    def creations_add(self, section, path, fit="cover"):
        section, path = str(section or ""), str(path or "")
        if section not in ("photo", "music"):
            return {"ok": False, "error": "bad_section"}
        if not os.path.isfile(path):
            self._notify(i18n.t("api.image.not_image", name=os.path.basename(path)), "warn")
            return {"ok": False, "error": "not_found"}
        st = self._creations_scan()
        folder, my_id = st["folder"], st["my_id"]
        if not folder:
            self._notify(i18n.t("api.creations.folder_missing"), "warn")
            return {"ok": False, "error": "no_folder"}
        backup_dir = self._creations_backup_dir()
        try:
            if section == "photo":
                base = creations.add_photo(folder, path, backup_dir, player=my_id, fit=str(fit or "cover"))
            else:
                if not my_id:
                    raise creations.CreationsError(i18n.t("api.creations.no_player"))
                uid, extra = self._creations_music_refs(st)
                data, duration = game_music.render_source(path, self._cfg, uid, extra)
                d = os.path.join(creations.game_root(folder), "record", my_id)
                title = os.path.splitext(os.path.basename(path))[0]
                base = game_music.file_name(title, duration)
                try:
                    os.makedirs(d, exist_ok=True)
                    creations._write_atomic(os.path.join(d, base), data)
                except OSError as e:
                    raise creations.CreationsError(str(e)) from e
                creations.added_record(backup_dir, [os.path.join(d, base)])
        except (creations.CreationsError, game_music.MusicError) as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        st = self._creations_scan(refresh=True)
        with st["lock"]:
            it = next((x for x in st["items"] if x["base"] == base), None)
        self._notify(i18n.t("api.creations.added", name=os.path.basename(path)), "ok")
        return {"ok": True, "section": section, "item": self._creations_public(it, backup_dir) if it else None}

    def creations_delete(self, item_id):
        """Supprime une création ajoutée par DodoTopia (refusé pour tout fichier écrit par le jeu)."""
        it = self._creations_item(item_id)
        if it is None:
            self._notify(i18n.t("api.creations.unknown"), "warn")
            return {"ok": False, "error": "unknown"}
        st = self._creations_state()
        extra = []
        if it.get("section") == "photo" and st["my_id"] and st["folder"]:
            extra.append(os.path.join(creations.info_dir(st["folder"], st["my_id"]), it["base"]))
        try:
            n = creations.delete_added(it, self._creations_backup_dir(), extra)
        except creations.CreationsError as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        self._creations_forget_thumbs(it)
        self._creations_scan(refresh=True)
        self._notify(i18n.t("api.creations.deleted"), "ok")
        return {"ok": True, "files": n}

    # ---------------------------------------------------------- écoute sur cet ordinateur
    def creations_listen(self, item_id):
        """Écoute une musique du jeu sans retourner dans Heartopia : elle est convertie en MIDI, rangée dans la
        bibliothèque sous « Heartopia - <titre> » (réécrite si elle y est déjà : pas de doublon à chaque écoute),
        sélectionnée, puis préécoutée avec le son de synthèse. Rien n'est envoyé au jeu."""
        it = self._creations_item(item_id)
        if it is None or it["cat"] != "music":
            self._notify(i18n.t("api.creations.unknown"), "warn")
            return {"ok": False, "error": "unknown"}
        try:
            rec = game_music.read(it["path"])
        except game_music.MusicError as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        return self._creations_preview(rec, it["name"])

    def _creations_preview(self, rec, title):
        """Range `rec` (événements du jeu) en MIDI dans la bibliothèque sous « Heartopia - <titre> » et lance la
        préécoute. Le fichier est réécrit s'il existe déjà."""
        p = self._player
        try:
            dst = core.safe_join(p.songs_folder, "Heartopia - " + game_music.safe_title(title))
            if p.state != "stopped":
                p.stop(join=True)
            game_music.to_midi(rec, dst)
        except (ValueError, game_music.MusicError) as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        sid = os.path.basename(dst)
        p.library.meta(sid)
        p.refresh_songs()
        names = [os.path.basename(s) for s in p.songs]
        if sid not in names:
            return {"ok": False, "error": "not_listed"}
        p.select(names.index(sid))
        p.play("preview")
        self._notify(i18n.t("api.creations.listening", name=title), "ok")
        return {"ok": True, "song": sid, "state": self.get_state()}

    # ---------------------------------------------------------- studio : pistes, instruments, enregistrement
    def _studio_instruments(self):
        """({identifiant: Instrument}, tables apprises) : les instruments à notes de DodoTopia."""
        insts = {i.id: i for i in self._player.instruments if i.bindings and not i.percussive}
        return insts, studio.learned_tables(self._cfg)

    def creations_studio_instruments(self):
        """[{id, name, notes, available, learned}] : ce que le studio sait écrire, et ce qui reste à apprendre."""
        insts, tables = self._studio_instruments()
        return {"ok": True, "instruments": [
            {"id": i.id, "name": i.name, "notes": len(i.bindings),
             "learned": i.id in tables and tables[i.id] != studio.BUILTIN_TABLES.get(i.id),
             "available": studio.is_available(i, tables)} for i in insts.values()]}

    def creations_studio_open(self):
        """Choisit un fichier MIDI et renvoie de quoi ouvrir le studio : {ok, path, title, tracks, instruments,
        parts (répartition de départ)}."""
        if not self._window:
            return {"ok": False, "error": "no_window"}
        path = self._creations_pick("music")
        if not path:
            return {"ok": False, "error": "cancelled"}
        try:
            listing, duration = studio.describe(path, self._cfg)
        except studio.StudioError as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        if not listing:
            self._notify(i18n.t("api.creations.failed", error=i18n.t("api.creations.studio_no_tracks")), "warn")
            return {"ok": False, "error": "no_tracks"}
        title = game_music.safe_title(os.path.splitext(os.path.basename(path))[0])
        return {"ok": True, "path": path, "title": title, "tracks": listing, "duration": duration,
                "instruments": self.creations_studio_instruments()["instruments"],
                "parts": studio.suggest(listing, duration)}

    def _studio_build(self, spec):
        """(événements, rapport) pour la demande de l'interface {path, title, parts:[{track, instrument, octave, on}]}."""
        spec = spec if isinstance(spec, dict) else {}
        path = str(spec.get("path") or "")
        if not os.path.isfile(path):
            raise studio.StudioError(i18n.t("api.image.not_image", name=os.path.basename(path)))
        parts = [p for p in (spec.get("parts") or []) if isinstance(p, dict) and p.get("on", True)]
        st = self._creations_scan()
        uid, extra = self._creations_music_refs(st)
        insts, tables = self._studio_instruments()
        return studio.build(path, self._cfg, parts, insts, tables, uid, extra)

    def creations_studio_check(self, spec):
        """Rapport sans rien écrire : {ok, report:{parts:[{track, coverage, played, notes}], duration}}."""
        try:
            _events, report = self._studio_build(spec)
        except (studio.StudioError, game_music.MusicError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "report": report}

    def creations_studio_listen(self, spec):
        """Préécoute de la répartition du studio sur cet ordinateur (rien n'est écrit dans le jeu)."""
        try:
            events, _report = self._studio_build(spec)
        except (studio.StudioError, game_music.MusicError) as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        title = "Studio " + game_music.safe_title((spec or {}).get("title"))
        return self._creations_preview({"events": events, "duration": events[-1][0]}, title)

    def creations_studio_add(self, spec):
        """Écrit la répartition du studio comme une nouvelle musique d'Heartopia (rien n'est remplacé)."""
        st = self._creations_scan()
        folder, my_id = st["folder"], st["my_id"]
        if not folder or not my_id:
            self._notify(i18n.t("api.creations.folder_missing" if not folder else "api.creations.no_player"), "warn")
            return {"ok": False, "error": "no_folder"}
        try:
            events, report = self._studio_build(spec)
            data = game_music.build(events)
            d = os.path.join(creations.game_root(folder), "record", my_id)
            base = game_music.file_name((spec or {}).get("title"), events[-1][0])
            os.makedirs(d, exist_ok=True)
            creations._write_atomic(os.path.join(d, base), data)
        except (studio.StudioError, game_music.MusicError, OSError) as e:
            self._notify(i18n.t("api.creations.failed", error=e), "danger")
            return {"ok": False, "error": str(e)}
        backup_dir = self._creations_backup_dir()
        creations.added_record(backup_dir, [os.path.join(d, base)])
        st = self._creations_scan(refresh=True)
        with st["lock"]:
            it = next((x for x in st["items"] if x["base"] == base), None)
        self._notify(i18n.t("api.creations.added", name=game_music.parse_name(base)["name"]), "ok")
        return {"ok": True, "report": report, "item": self._creations_public(it, backup_dir) if it else None}

    def creations_learn(self, item_id, instrument_id):
        """Apprend les numéros du jeu d'un instrument à partir d'une musique où toutes ses touches ont été jouées."""
        it = self._creations_item(item_id)
        insts, _tables = self._studio_instruments()
        inst = insts.get(str(instrument_id or ""))
        if it is None or it["cat"] != "music" or inst is None:
            self._notify(i18n.t("api.creations.unknown"), "warn")
            return {"ok": False, "error": "unknown"}
        st = self._creations_state()
        try:
            table = studio.learn(it["path"], inst, game_music.my_uid(st["folder"]))
        except studio.StudioError as e:
            self._notify(i18n.t("api.creations.failed", error=e), "warn")
            return {"ok": False, "error": str(e)}
        node = self._cfg.get("creations")
        if not isinstance(node, dict):
            node = self._cfg["creations"] = {}
        node.setdefault("game_instruments", {})[inst.id] = table
        core.save_config(self._cfg)
        self._notify(i18n.t("api.creations.learned", name=inst.name, n=len(table["keys"])), "ok")
        return {"ok": True, "instrument": inst.id, "type": table["type"], "keys": len(table["keys"])}
