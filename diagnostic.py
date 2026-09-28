"""DodoTopia : rapport de diagnostic (bouton « Envoyer un rapport »).

Rassemble dans un zip ce qu'il faut pour comprendre un problème sans aller-retour : les fins des journaux, les
captures de la cuisine, la configuration et une fiche système. Le joueur voit la liste avant l'envoi.

Jamais dans le zip : account.json (jeton de connexion), instance.key, la bibliothèque de morceaux. Le chemin
du dossier personnel et le nom de la session Windows sont remplacés par « ~ » / « <utilisateur> » dans tous les
textes ; le pseudo du joueur (multi.name) est retiré de la configuration.
"""
import getpass
import io
import json
import os
import platform
import re
import sys
import time
import zipfile

LOG_TAIL_BYTES = 1024 * 1024
LOGS = ("dodotopia.log", "multi.log", "salon.log", "online.log", "dessin.log", "cuisine.log")
IMAGES_RE = re.compile(r"^cuisine_(ref_[a-z]+|echec)\.png$")
AUDIO = ("multi_ecoute.wav",)
NEVER = {"account.json", "instance.key"}
MAX_TOTAL = 7 * 1024 * 1024          # sous la limite du serveur (8 Mo)


def _home_patterns():
    pats = []
    home = os.path.expanduser("~")
    if home and home not in ("~", "/"):
        pats.append((re.compile(re.escape(home), re.I), "~"))
        pats.append((re.compile(re.escape(home.replace("\\", "/")), re.I), "~"))
        pats.append((re.compile(re.escape(home.replace("\\", "\\\\")), re.I), "~"))
    try:
        user = getpass.getuser()
    except Exception:  # noqa
        user = ""
    if user and len(user) >= 3:
        pats.append((re.compile(r"(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])", re.I), "<utilisateur>"))
    return pats


def scrub(text):
    """Retire le dossier personnel et le nom de session d'un texte."""
    for pat, rep in _home_patterns():
        text = pat.sub(rep, text)
    return text


def _tail(path, limit=LOG_TAIL_BYTES):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > limit:
            f.seek(size - limit)
            f.readline()                        # ligne coupée au début de la fenêtre
        data = f.read()
    return data.decode("utf-8", errors="replace")


def _clean_config(raw):
    try:
        cfg = json.loads(raw)
    except ValueError:
        return scrub(raw)
    if isinstance(cfg.get("multi"), dict):
        cfg["multi"].pop("name", None)
    if isinstance(cfg.get("online"), dict):
        cfg["online"] = {k: v for k, v in cfg["online"].items() if k in ("server_url", "check_updates", "auto_install")}
    return scrub(json.dumps(cfg, ensure_ascii=False, indent=2))


def candidates(data_dir, include_audio=False, include_images=False):
    """[(nom dans le zip, chemin, genre)] des fichiers existants : log | image | config | audio. Les captures
    d'écran (cuisine) et l'audio ne partent que sur demande explicite du joueur."""
    out = []
    for name in LOGS:
        p = os.path.join(data_dir, name)
        if os.path.isfile(p):
            out.append((name, p, "log"))
    try:
        names = sorted(os.listdir(data_dir))
    except OSError:
        names = []
    for name in names:
        if include_images and IMAGES_RE.match(name):
            out.append((name, os.path.join(data_dir, name), "image"))
    p = os.path.join(data_dir, "config.json")
    if os.path.isfile(p):
        out.append(("config.json", p, "config"))
    if include_audio:
        for name in AUDIO:
            p = os.path.join(data_dir, name)
            if os.path.isfile(p):
                out.append((name, p, "audio"))
    return [c for c in out if os.path.basename(c[1]) not in NEVER]


def preview(data_dir):
    """Ce qui partira (tailles réelles, journaux tronqués à 1 Mo) et si un enregistrement audio existe."""
    files = []
    for name, path, kind in candidates(data_dir, include_audio=True, include_images=True):
        size = os.path.getsize(path)
        if kind == "log":
            size = min(size, LOG_TAIL_BYTES)
        files.append({"name": name, "size": size, "kind": kind})
    return {"files": files, "audio": any(f["kind"] == "audio" for f in files),
            "images": any(f["kind"] == "image" for f in files)}


def build(data_dir, system=None, note="", include_audio=False, include_images=False):
    """-> (octets du zip, [{name, size}]). `system` : fiche système (dict) ajoutée en systeme.json."""
    buf = io.BytesIO()
    listing = []
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def put(name, data):
            nonlocal total
            if isinstance(data, str):
                data = data.encode("utf-8")
            if total + len(data) > MAX_TOTAL:
                listing.append({"name": name, "size": len(data), "skipped": True})
                return
            total += len(data)
            zf.writestr(name, data)
            listing.append({"name": name, "size": len(data)})

        sysinfo = dict(system or {})
        sysinfo.setdefault("os", f"{platform.system()} {platform.release()} ({platform.version()})")
        sysinfo.setdefault("python", sys.version.split()[0])
        sysinfo["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
        put("systeme.json", scrub(json.dumps(sysinfo, ensure_ascii=False, indent=2, default=str)))
        if note:
            put("description.txt", scrub(str(note))[:4000])
        for name, path, kind in candidates(data_dir, include_audio, include_images):
            try:
                if kind == "log":
                    put(name, scrub(_tail(path)))
                elif kind == "config":
                    with open(path, encoding="utf-8", errors="replace") as f:
                        put(name, _clean_config(f.read()))
                else:
                    with open(path, "rb") as f:
                        put(name, f.read())
            except OSError as e:
                put(name + ".erreur.txt", f"illisible : {e}")
    return buf.getvalue(), listing
