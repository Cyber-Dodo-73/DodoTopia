# -*- coding: utf-8 -*-
"""Mes créations : les images qu'Heartopia garde sur cet ordinateur (photos, dessins, cadres, pochettes…).

Le jeu les range dans `…/AppData/LocalLow/xd/Heartopia/ScreenCapture/<Photo|Draw|Limit|NoBgPhoto|Announcement>`,
chiffrées en AES-256-CBC (PKCS7) avec une clé et un vecteur FIXES (classe IL2CPP `EncryptUtil` du jeu, relevée
le 2026-10-03 : un fichier = AES-CBC(PKCS7(octets PNG ou JPEG)), rien autour). Une même image existe en
plusieurs tailles (`<base>_<l>_<h>.<ext>`) : ce module les regroupe en une seule « création ».

Noms rencontrés :
    normal+<joueur>+<Genre>+<reste>.png_<l>_<h>.<ext>    image attachée à un joueur (TakePhoto, DrawManual,
                                                           PhotoFrame, RecordCover, MicroHomeland, Book…)
    <chiffres>_<l>_<h>.jpg                                 photo prise par CE joueur (dossier Photo)
    <Genre>_<id>_<reste>_<l>_<h>.png                        rendu sans fond (Record, Book, PaintCloth…)
    <code>_<l>_<h>.jpg                                     annonces du jeu
Les grands nombres des noms sont des FILETIME Windows (centaines de ns depuis 1601) : la date de création.

Rien ici ne touche à l'interface : `api/creations_api.py` fait le lien. Dépendances : `cryptography` (AES),
Pillow (vignettes, recadrage). Sans `cryptography`, `available()` est faux et tout le reste refuse poliment."""
import base64
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time

KEY = bytes.fromhex("1234567890abcdeffedcba98765432101234567890abcdeffedcba9876543210")
IV = bytes.fromhex("0123456789abcdeffedcba9876543210")

STEAM_APPID = "4025700"
SUBFOLDERS = ("Photo", "Draw", "Limit", "NoBgPhoto", "Announcement")
IMAGE_EXTS = (".png", ".jpg", ".jpeg")
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_JPG = b"\xff\xd8\xff"
SECTIONS = ("photo", "painting", "music", "cache")     # music : game_music.py ; cache : tout le reste
# tailles que le jeu garde d'une photo de l'album (dossier Photo, nom = FILETIME de la prise de vue)
PHOTO_SIZES = ((1920, 1080), (1564, 880), (512, 288), (256, 144))
ADDED_FILE = "added.json"   # dans le dossier de sauvegarde : fichiers créés par DodoTopia (ajouts)
THUMB_PX = 240          # vignette : plus grand côté
VIEW_PX = 1920          # affichage en grand : plafond (les photos font 1920×1080 au plus)
MAX_FILE_BYTES = 32 * 1024 * 1024
FILETIME_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)

# genre (dans le nom du fichier) -> catégorie affichée ; tout le reste tombe dans « other »
CATEGORIES = ("photo", "draw", "frame", "cover", "book", "home", "paint", "dress", "announcement", "other")
KIND_CATEGORY = {
    "takephoto": "photo", "photo": "photo", "album": "book", "book": "book",
    "drawmanual": "draw", "draw": "draw",
    "photoframe": "frame",
    "recordcover": "cover", "record": "cover",
    "microhomeland": "home", "homeevaluate": "home",
    "paintcloth": "paint", "paintfurniture": "paint",
    "dresssuit": "dress",
    "announcement": "announcement",
}

_NAME_PLAYER = re.compile(r"^normal\+(?P<player>[0-9a-z]+)\+(?P<kind>[A-Za-z]+)\+(?P<rest>.+?)(?:\.png)?$")
_NAME_SIZE = re.compile(r"^(?P<base>.+)_(?P<w>\d{1,5})_(?P<h>\d{1,5})\.(?P<ext>png|jpe?g)$", re.IGNORECASE)
_NAME_NOBG = re.compile(r"^(?P<kind>[A-Za-z]+)_(?P<rest>.+)$")
_NAME_KINDNUM = re.compile(r"^(?P<kind>[A-Za-z]+)(?P<num>\d{6,})$")
_FILETIME = re.compile(r"(?<!\d)(1[0-9]{17})(?!\d)")
# Player.log : « 上传图片 : normal/<joueur>/... » et « .../Standalone/<joueur>/... » = envois de CE joueur
_LOG_UPLOAD = re.compile(r"(?:normal|Standalone)/([0-9a-z]{5,12})/")


class CreationsError(Exception):
    """Erreur lisible (message déjà formé) : dossier illisible, image illisible, écriture refusée…"""


# ---------------------------------------------------------------- chiffrement
def available():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _cipher():
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher(algorithms.AES(KEY), modes.CBC(IV))


def _pkcs7_pad(data, block=16):
    n = block - (len(data) % block)
    return data + bytes([n]) * n


def _pkcs7_unpad(data):
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data.endswith(bytes([n]) * n):
        return data[:-n]
    return data      # pas de bourrage reconnaissable : octets rendus tels quels


def encrypt_bytes(plaintext):
    e = _cipher().encryptor()
    return e.update(_pkcs7_pad(bytes(plaintext))) + e.finalize()


def decrypt_bytes(ciphertext):
    if len(ciphertext) % 16:
        raise CreationsError("taille de fichier incompatible avec AES-CBC")
    d = _cipher().decryptor()
    return _pkcs7_unpad(d.update(bytes(ciphertext)) + d.finalize())


def image_ext(data):
    """Extension d'après les premiers octets (le nom du fichier ment : `….png_256_144.jpg` contient un JPEG)."""
    if data[:8] == MAGIC_PNG:
        return ".png"
    if data[:3] == MAGIC_JPG:
        return ".jpg"
    return None


def read_image(path):
    """Octets déchiffrés d'un fichier du jeu, ou CreationsError si ce n'est pas une image chiffrée."""
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            raise CreationsError("fichier trop gros")
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise CreationsError(str(e)) from e
    data = decrypt_bytes(raw)
    if image_ext(data) is None:
        raise CreationsError("contenu déchiffré non reconnu comme image")
    return data


# ---------------------------------------------------------------- dossiers
def candidate_folders():
    """Emplacements possibles du dossier ScreenCapture : Windows, puis Proton/Wine sous Linux."""
    out = []
    tail = os.path.join("AppData", "LocalLow", "xd", "Heartopia", "ScreenCapture")
    if sys.platform == "win32":
        prof = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        out.append(os.path.join(prof, tail))
    else:
        home = os.path.expanduser("~")
        for steam in (os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam"),
                      os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")):
            out.append(os.path.join(steam, "steamapps", "compatdata", STEAM_APPID, "pfx", "drive_c", "users",
                                    "steamuser", tail))
        out.append(os.path.join(home, ".wine", "drive_c", "users", os.environ.get("USER", "user"), tail))
    return out


def looks_like_folder(path):
    """Vrai si `path` contient au moins un des sous-dossiers du jeu."""
    if not path or not os.path.isdir(path):
        return False
    return any(os.path.isdir(os.path.join(path, sub)) for sub in SUBFOLDERS)


def find_folder(preferred=None):
    """Dossier ScreenCapture : celui indiqué dans la configuration s'il existe, sinon le premier candidat trouvé."""
    if preferred and looks_like_folder(preferred):
        return preferred
    for c in candidate_folders():
        if looks_like_folder(c):
            return c
    return None


def log_path(folder):
    """Player.log du jeu (à côté de ScreenCapture) : il nomme le joueur dans ses lignes d'envoi d'images."""
    return os.path.join(os.path.dirname(os.path.abspath(folder)), "Player.log") if folder else None


def my_player_id(path):
    """Identifiant de CE joueur d'après les envois d'images du journal du jeu (le plus fréquent), ou None."""
    counts = {}
    for name in (path, (path[:-4] + "-prev.log") if path and path.endswith(".log") else None):
        if not name or not os.path.isfile(name):
            continue
        try:
            with open(name, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "上传" not in line and "upload" not in line.lower():
                        continue
                    for m in _LOG_UPLOAD.finditer(line):
                        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        except OSError:
            continue
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def game_root(folder):
    """Dossier du jeu (…/LocalLow/xd/Heartopia) qui contient ScreenCapture, Configs, record, Player.log."""
    return os.path.dirname(os.path.abspath(folder)) if folder else None


def info_dir(folder, player):
    """Dossier des fiches de photos de l'album (une par photo, nommée par son FILETIME)."""
    return os.path.join(game_root(folder), "Configs", "InfoConfig", player)


def player_id_from_dirs(folder):
    """Identifiant de CE joueur d'après les dossiers que le jeu nomme avec (fiches des photos, musiques) :
    le plus récemment modifié. Sert quand le journal du jeu ne dit rien (aucun envoi d'image récent)."""
    root = game_root(folder)
    best = None
    for parent in (os.path.join(root, "Configs", "InfoConfig"), os.path.join(root, "record")) if root else ():
        try:
            names = os.listdir(parent)
        except OSError:
            continue
        for n in names:
            p = os.path.join(parent, n)
            if os.path.isdir(p) and re.fullmatch(r"[0-9a-z]{5,12}", n):
                mt = os.path.getmtime(p)
                if best is None or mt > best[0]:
                    best = (mt, n)
    return best[1] if best else None


def guess_player_id(folder):
    """Journal du jeu d'abord (envois d'images), sinon les dossiers au nom du joueur."""
    return my_player_id(log_path(folder)) or player_id_from_dirs(folder)


def now_filetime(now=None):
    return int(((time.time() if now is None else now) + 11644473600) * 10_000_000)


# ---------------------------------------------------------------- noms de fichiers
def filetime_to_epoch(ticks):
    try:
        return (FILETIME_EPOCH + datetime.timedelta(microseconds=int(ticks) // 10)).timestamp()
    except (OverflowError, ValueError, TypeError):
        return None


def _created_from(text):
    """Première valeur FILETIME plausible (années 2020-2040) trouvée dans un nom."""
    for m in _FILETIME.finditer(text):
        t = filetime_to_epoch(m.group(1))
        if t and 1577836800 < t < 2208988800:
            return t
    return None


def category(kind):
    return KIND_CATEGORY.get(str(kind or "").lower(), "other")


def parse_name(subfolder, filename):
    """Décrit un fichier du jeu : {base, kind, cat, player, w, h, ext, created} ou None (pas une image)."""
    m = _NAME_SIZE.match(filename)
    if not m:
        return None
    base, w, h = m.group("base"), int(m.group("w")), int(m.group("h"))
    ext = "." + m.group("ext").lower().replace("jpeg", "jpg")
    info = {"base": base, "w": w, "h": h, "ext": ext, "player": None, "kind": None, "created": _created_from(base)}
    pm = _NAME_PLAYER.match(base)
    if pm:
        info["player"], info["kind"] = pm.group("player"), pm.group("kind")
    elif base.isdigit():
        # photo prise par ce joueur (dossier Photo) ; ailleurs un simple numéro = contenu du jeu
        info["kind"] = "Photo" if subfolder == "Photo" else subfolder
    else:
        km = _NAME_KINDNUM.match(base)
        nm = _NAME_NOBG.match(base)
        if km:
            info["kind"] = km.group("kind")
        elif nm and subfolder == "NoBgPhoto":
            info["kind"] = nm.group("kind")
        else:
            info["kind"] = subfolder
    if subfolder == "Announcement":
        info["kind"] = "Announcement"
    info["cat"] = category(info["kind"])
    return info


# ---------------------------------------------------------------- lecture du dossier
def _item_id(base):
    """Identifiant stable et sûr pour l'interface (le nom de base contient +, @, #)."""
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def scan(folder, my_id=None):
    """Liste des créations du dossier, une entrée par image (toutes tailles regroupées), plus récentes d'abord.
    Chaque entrée : {id, base, kind, cat, player, mine, created, w, h, variants: [{path, folder, name, w, h,
    ext, bytes, mtime}], thumb (chemin de la variante à vignetter), largest (chemin de la plus grande)}."""
    groups = {}
    for sub in SUBFOLDERS:
        d = os.path.join(folder, sub)
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            info = parse_name(sub, name)
            if info is None:
                continue
            path = os.path.join(d, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            key = info["base"]
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"id": _item_id(key), "base": key, "kind": info["kind"], "cat": info["cat"],
                                   "player": info["player"], "created": info["created"], "variants": []}
                if my_id and info["player"]:
                    g["mine"] = info["player"] == my_id
                elif info["player"] is None and sub == "Photo" and key.isdigit():
                    g["mine"] = True              # photo prise ici : pas d'identifiant, mais c'est la nôtre
                else:
                    g["mine"] = None
            g["variants"].append({"path": path, "folder": sub, "name": name, "w": info["w"], "h": info["h"],
                                  "ext": info["ext"], "bytes": st.st_size, "mtime": st.st_mtime})
    items = []
    for g in groups.values():
        vs = sorted(g["variants"], key=lambda v: (v["w"] * v["h"], v["name"]))
        g["variants"] = vs
        g["w"], g["h"] = vs[-1]["w"], vs[-1]["h"]
        g["largest"] = vs[-1]["path"]
        # vignette : la plus petite variante encore nette (≥ 128 px), sinon la plus grande
        pick = next((v for v in vs if min(v["w"], v["h"]) >= 128), vs[-1])
        g["thumb"] = pick["path"]
        g["modified"] = max(v["mtime"] for v in vs)
        g["indexed"] = any(v["folder"] == "Draw" for v in vs)      # dessin stocké en indices de palette
        # section affichée : l'album photo de ce joueur, ses peintures, ou « cache » (copies d'envoi, cadres,
        # pochettes, images des autres joueurs, annonces : tout ce que le jeu a téléchargé ou dérivé)
        if g["base"].isdigit() and any(v["folder"] == "Photo" for v in vs):
            g["section"] = "photo"
        elif g["indexed"] and g["mine"] is True:
            g["section"] = "painting"
        else:
            g["section"] = "cache"
        # created reste None sans date dans le nom (annonces, contenu du jeu) : ces entrées vont en fin de
        # liste plutôt que de passer pour « récentes » à chaque fois que le jeu les retélécharge
        items.append(g)
    items.sort(key=lambda g: (-(g["created"] or 0), g["base"]))
    return items


def folder_signature(folder):
    """Empreinte du contenu : change quand un fichier apparaît, disparaît ou est réécrit."""
    sig = []
    for sub in SUBFOLDERS:
        d = os.path.join(folder, sub)
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        st = e.stat()
                    except OSError:
                        continue
                    sig.append((sub, e.name, st.st_size, int(st.st_mtime)))
        except OSError:
            continue
    sig.sort()
    return hashlib.sha1(repr(sig).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- images (Pillow)
def _pil():
    from PIL import Image, ImageOps
    return Image, ImageOps


# ---------------------------------------------------------------- dessins du jeu : palette stockée en gris
# Un dessin (dossier Draw) est un PNG « gris » : chaque pixel R=G=B porte l'INDICE d'une couleur de la palette
# du jeu, pas sa couleur. Relevé le 2026-10-03 sur les dessins faits par DodoTopia (couleurs connues) :
#   128 + 10×k + j  → nuance j (0-9) de la k-ième famille de couleur (rouge, orange, jaune, vert-jaune, vert,
#                     turquoise, cyan, bleu, indigo, violet, magenta, rose : l'ordre des pastilles du jeu)
#   248 blanc · 249 crème · 250 gris clair · 251 gris · 252 gris foncé · 124 noir   (famille du noir)
# Le blanc (248) est aussi la toile vierge : le jeu ne distingue pas « non peint » et « peint en blanc ».
DRAW_WHITE = 248
DRAW_SPECIAL = {124: (0, 0), 248: (0, 4), 249: (0, 5), 250: (0, 3), 251: (0, 2), 252: (0, 1)}   # valeur -> (famille, nuance)


def _draw_tables():
    """(valeur -> rgb, liste [(rgb, valeur)]) depuis la palette de draw.py ; None sans ce module."""
    cached = globals().get("_DRAW_TABLES")
    if cached is not None:
        return cached
    try:
        import draw
    except ImportError:
        return None
    fams = dict(draw.SHADE_FAMILIES)
    to_rgb = {}
    for k, fam in enumerate(f for f, _ in draw.SHADE_FAMILIES if f != 0):
        for j, rgb in enumerate(fams[fam]):
            to_rgb[128 + 10 * k + j] = tuple(rgb)
    for value, (fam, j) in DRAW_SPECIAL.items():
        to_rgb[value] = tuple(fams[fam][j])
    globals()["_DRAW_TABLES"] = (to_rgb, [(rgb, v) for v, rgb in to_rgb.items()])
    return globals()["_DRAW_TABLES"]


def is_indexed_drawing(im):
    """Vrai si l'image est un dessin du jeu stocké en indices (tous les pixels gris, valeurs connues)."""
    tables = _draw_tables()
    if tables is None:
        return False
    rgb = im.convert("RGB")
    known = tables[0]
    bad = 0
    for r, g, b in rgb.getdata():
        if r != g or g != b or r not in known:
            bad += 1
            if bad > 4:                      # tolérance : quelques pixels inconnus, pas une vraie image couleur
                return False
    return True


def decode_drawing(im):
    """Dessin en indices -> image RGB aux vraies couleurs de la palette (inconnu -> gris moyen)."""
    tables = _draw_tables()
    Image, _ = _pil()
    src = im.convert("L")
    to_rgb = tables[0] if tables else {}
    lut = []
    for v in range(256):
        lut.extend(to_rgb.get(v, (v, v, v)))
    return Image.merge("RGB", [src.point(lut[c::3]) for c in range(3)])


def encode_drawing(im):
    """Image couleur -> dessin en indices (couleur de palette la plus proche ; transparent = toile vierge)."""
    tables = _draw_tables()
    Image, _ = _pil()
    rgba = im.convert("RGBA")
    out = Image.new("L", rgba.size, DRAW_WHITE)
    if not tables:
        return out
    entries = tables[1]
    cache = {}
    src, dst = rgba.load(), out.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = src[x, y]
            if a < 128:
                continue
            key = (r >> 2, g >> 2, b >> 2)
            v = cache.get(key)
            if v is None:
                v = min(entries, key=lambda e: (e[0][0] - r) ** 2 + (e[0][1] - g) ** 2 + (e[0][2] - b) ** 2)[1]
                cache[key] = v
            dst[x, y] = v
    return out


def _data_url(data, ext):
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def image_data_url(path, max_px=None, drawing=False):
    """Image déchiffrée en data URL, réduite à `max_px` sur son plus grand côté si demandé ; `drawing` :
    dessin du jeu en indices, rendu avec les couleurs de la palette. Renvoie (data_url, largeur, hauteur)."""
    data = read_image(path)
    ext = image_ext(data)
    Image, _ = _pil()
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa - image corrompue
        raise CreationsError(f"image illisible : {e}") from e
    w, h = im.size
    if drawing and is_indexed_drawing(im):
        im = decode_drawing(im)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        data, ext = buf.getvalue(), ".png"
    if max_px and max(w, h) > max_px:
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        if ext == ".png" or im.mode in ("RGBA", "LA", "P"):
            im.convert("RGBA").save(buf, format="PNG", optimize=True)
            ext = ".png"
        else:
            im.convert("RGB").save(buf, format="JPEG", quality=85)
            ext = ".jpg"
        data, (w, h) = buf.getvalue(), im.size
    return _data_url(data, ext), w, h


def thumbnail(path, max_px=THUMB_PX, drawing=False):
    return image_data_url(path, max_px, drawing)


FITS = ("cover", "contain")


def render_replacement(src_path, w, h, ext, keep_alpha=False, fit="cover", drawing=False):
    """Octets (PNG ou JPEG, non chiffrés) de l'image `src_path` amenée à `w`×`h` : `cover` recadre au centre
    pour remplir, `contain` garde toute l'image avec des bandes (blanches, transparentes pour un PNG avec alpha).
    `drawing` : la sortie est un dessin du jeu en indices de palette (couleur la plus proche)."""
    Image, ImageOps = _pil()
    try:
        im = Image.open(src_path)
        im.load()
    except Exception as e:  # noqa
        raise CreationsError(f"image illisible : {e}") from e
    im = ImageOps.exif_transpose(im) or im
    alpha = keep_alpha or im.mode in ("RGBA", "LA", "P")
    if im.size != (w, h):
        # Agrandissement d'un petit dessin : voisin le plus proche (les cases restent nettes) ; sinon Lanczos
        up = im.width < w and im.height < h
        method = Image.NEAREST if up and (w % im.width == 0) and (h % im.height == 0) else Image.LANCZOS
        if fit == "contain":
            im = im.convert("RGBA")
            im.thumbnail((w, h), method) if not up else None
            if up:
                s = min(w / im.width, h / im.height)
                im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), method)
            bg = Image.new("RGBA", (w, h), (255, 255, 255, 0) if (alpha and ext == ".png" and not drawing) else (255, 255, 255, 255))
            bg.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
            im = bg
        else:
            im = ImageOps.fit(im, (w, h), method, centering=(0.5, 0.5))
    buf = io.BytesIO()
    if drawing:
        encode_drawing(im).convert("RGB").save(buf, format="PNG", optimize=True)
    elif ext == ".png":
        im.convert("RGBA" if alpha else "RGB").save(buf, format="PNG", optimize=True)
    else:
        im.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------- remplacement, sauvegarde, export
def backup_path(backup_dir, variant):
    return os.path.join(backup_dir, variant["folder"], variant["name"])


def has_backup(item, backup_dir):
    return any(os.path.isfile(backup_path(backup_dir, v)) for v in item["variants"])


def _write_atomic(path, data):
    tmp = path + ".dodotmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def replace_item(item, src_path, backup_dir, fit="cover"):
    """Remplace chaque variante de `item` par `src_path` (amenée à sa taille selon `fit`, même format,
    rechiffrée ; un dessin du jeu est réencodé en indices de palette). L'original de chaque fichier est copié
    une seule fois dans `backup_dir` (la première sauvegarde est l'original du jeu, jamais écrasée).
    Renvoie le nombre de fichiers écrits."""
    if not os.path.isfile(src_path):
        raise CreationsError("fichier source introuvable")
    fit = fit if fit in FITS else "cover"
    plans = []
    for v in item["variants"]:
        indexed = False
        try:
            original = read_image(v["path"])
            ext = image_ext(original)
            Image, _ = _pil()
            im = Image.open(io.BytesIO(original))
            w, h = im.size
            alpha = im.mode in ("RGBA", "LA", "P")
            indexed = v["folder"] == "Draw" and is_indexed_drawing(im)
        except CreationsError:
            # fichier du jeu illisible : on s'en tient au nom (taille) et à l'extension
            original, ext, w, h, alpha = None, (".png" if v["ext"] == ".png" else ".jpg"), v["w"], v["h"], v["ext"] == ".png"
            indexed = v["folder"] == "Draw"
        plans.append((v, render_replacement(src_path, w, h, ext, keep_alpha=alpha, fit=fit, drawing=indexed), original))
    written = 0
    for v, data, original in plans:
        bk = backup_path(backup_dir, v)
        try:
            if not os.path.isfile(bk):
                os.makedirs(os.path.dirname(bk), exist_ok=True)
                shutil.copy2(v["path"], bk)
            _write_atomic(v["path"], encrypt_bytes(data))
        except OSError as e:
            raise CreationsError(str(e)) from e
        written += 1
    return written


def restore_item(item, backup_dir):
    """Remet les originaux sauvegardés ; renvoie le nombre de fichiers restaurés (0 = pas de sauvegarde)."""
    restored = 0
    for v in item["variants"]:
        bk = backup_path(backup_dir, v)
        if not os.path.isfile(bk):
            continue
        try:
            with open(bk, "rb") as f:
                data = f.read()
            _write_atomic(v["path"], data)
            os.remove(bk)
        except OSError as e:
            raise CreationsError(str(e)) from e
        restored += 1
    return restored


def export_item(item, dest):
    """Écrit la plus grande variante déchiffrée dans `dest` (l'extension est corrigée d'après le contenu ;
    un dessin du jeu est exporté en couleurs). Renvoie le chemin écrit."""
    data = read_image(item["largest"])
    ext = image_ext(data)
    if item.get("indexed"):
        Image, _ = _pil()
        im = Image.open(io.BytesIO(data))
        if is_indexed_drawing(im):
            buf = io.BytesIO()
            decode_drawing(im).save(buf, format="PNG", optimize=True)
            data, ext = buf.getvalue(), ".png"
    root, cur = os.path.splitext(dest)
    if cur.lower() not in (ext, ".jpeg" if ext == ".jpg" else ext):
        dest = root + ext
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        _write_atomic(dest, data)
    except OSError as e:
        raise CreationsError(str(e)) from e
    return dest


def suggested_export_name(item):
    """Nom de fichier proposé à l'export : catégorie, date, taille."""
    when = time.strftime("%Y%m%d-%H%M%S", time.localtime(item.get("created") or time.time()))
    return f"heartopia-{item['cat']}-{when}-{item['w']}x{item['h']}"


# ---------------------------------------------------------------- ajouts (fichiers créés par DodoTopia)
def added_load(backup_dir):
    """Chemins (absolus) des fichiers ajoutés par DodoTopia."""
    try:
        with open(os.path.join(backup_dir, ADDED_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    return {p for p in data if isinstance(p, str)} if isinstance(data, list) else set()


def _added_save(backup_dir, paths):
    os.makedirs(backup_dir, exist_ok=True)
    _write_atomic(os.path.join(backup_dir, ADDED_FILE),
                  json.dumps(sorted(paths), ensure_ascii=False, indent=1).encode("utf-8"))


def added_record(backup_dir, paths):
    cur = {p for p in added_load(backup_dir) if os.path.exists(p)}
    cur.update(os.path.abspath(p) for p in paths)
    _added_save(backup_dir, cur)


def is_added(item, added):
    return bool(added) and any(os.path.abspath(v["path"]) in added for v in item["variants"])


def delete_added(item, backup_dir, extra_paths=()):
    """Supprime une création AJOUTÉE par DodoTopia (jamais un fichier écrit par le jeu) ; renvoie le nombre de
    fichiers supprimés. `extra_paths` : fichiers liés (fiche de la photo), supprimés s'ils sont aussi des ajouts."""
    added = added_load(backup_dir)
    if not is_added(item, added):
        raise CreationsError("cette création n'a pas été ajoutée par DodoTopia")
    n = 0
    for v in list(item["variants"]) + [{"path": p} for p in extra_paths]:
        ap = os.path.abspath(v["path"])
        if ap not in added:
            continue
        try:
            if os.path.isfile(ap):
                os.remove(ap)
                n += 1
        except OSError as e:
            raise CreationsError(str(e)) from e
        added.discard(ap)
        if "folder" in v:                           # sauvegarde d'un remplacement fait sur l'ajout : inutile
            try:
                os.remove(backup_path(backup_dir, v))
            except OSError:
                pass
    _added_save(backup_dir, added)
    return n


PHOTO_INFO = {"staticId": 0, "clothesId": None, "actionId": 0, "buffId": None, "id": 0, "name": None, "shortId": 0,
              "expressionId": 0, "areaId": [1, 100, 400, 410, 411, 401], "date": "", "periodId": 4, "weatherId": 101,
              "entityType": 0, "cameraId": 0, "guid": "00000000-0000-0000-0000-000000000000", "EncodeShortIds": []}


def photo_info_bytes(player, now=None):
    """Fiche d'une photo de l'album, comme le jeu l'écrit (« WritePhotoInfo ») : BOM UTF-8 + base64 d'un JSON."""
    info = dict(PHOTO_INFO)
    info["date"] = time.strftime("%Y/%m/%d", time.localtime(now))
    info["EncodeShortIds"] = [{"EncodeShortId": player, "State": 1}] if player else []
    raw = json.dumps(info, separators=(",", ":")).encode("utf-8")
    return b"\xef\xbb\xbf" + base64.b64encode(raw)


def add_photo(folder, src_path, backup_dir, player=None, fit="cover", now=None):
    """Ajoute `src_path` à l'album photo du jeu : les quatre tailles que le jeu garde (JPEG chiffrés, nommés par
    un FILETIME neuf) et, si le joueur est connu, la fiche de la photo. Rien d'existant n'est touché ; les
    fichiers créés sont notés pour pouvoir être supprimés. Renvoie le nom de base (FILETIME) de la photo."""
    if not os.path.isfile(src_path):
        raise CreationsError("fichier source introuvable")
    fit = fit if fit in FITS else "cover"
    d = os.path.join(folder, "Photo")
    ticks = now_filetime(now)
    while any(os.path.exists(os.path.join(d, f"{ticks}_{w}_{h}.jpg")) for w, h in PHOTO_SIZES):
        ticks += 1
    plans = [(os.path.join(d, f"{ticks}_{w}_{h}.jpg"), render_replacement(src_path, w, h, ".jpg", fit=fit))
             for w, h in PHOTO_SIZES]
    written = []
    try:
        os.makedirs(d, exist_ok=True)
        for path, data in plans:
            _write_atomic(path, encrypt_bytes(data))
            written.append(path)
        if player:
            idir = info_dir(folder, player)
            os.makedirs(idir, exist_ok=True)
            ipath = os.path.join(idir, str(ticks))
            _write_atomic(ipath, photo_info_bytes(player, now))
            written.append(ipath)
    except OSError as e:
        for p in written:                           # ajout à moitié fait : on ne laisse rien derrière
            try:
                os.remove(p)
            except OSError:
                pass
        raise CreationsError(str(e)) from e
    added_record(backup_dir, written)
    return str(ticks)
