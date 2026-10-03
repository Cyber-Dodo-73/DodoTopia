# -*- coding: utf-8 -*-
"""Mes créations (creations.py + api/creations_api.py) : chiffrement du jeu, lecture des noms de fichiers,
regroupement des tailles, identifiant du joueur, vignettes, remplacement avec sauvegarde, restauration, export."""
import io
import os
import threading
from collections import deque

import pytest
from PIL import Image

import core
import creations
import terms

MY = "54a72h7q"
OTHER = "zz9x1abc"
TICKS_PHOTO = 134354551507837507          # FILETIME : 2026-10-02 22:52:30 UTC
TICKS_DRAW = 134354449656984106


def _png(w, h, color=(200, 40, 40, 255)):
    im = Image.new("RGBA", (w, h), color)
    im.putpixel((0, 0), (0, 0, 0, 0))            # un pixel transparent : l'alpha doit survivre
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _jpg(w, h, color=(40, 90, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _put(root, sub, name, data):
    d = os.path.join(root, sub)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "wb") as f:
        f.write(creations.encrypt_bytes(data))
    return os.path.join(d, name)


@pytest.fixture
def tree(tmp_path):
    """Un dossier ScreenCapture miniature (tailles réelles petites, formats et noms du jeu)."""
    root = str(tmp_path / "Heartopia" / "ScreenCapture")
    files = {
        "photo_big": _put(root, "Photo", f"{TICKS_PHOTO}_64_36.jpg", _jpg(64, 36)),
        "photo_small": _put(root, "Photo", f"{TICKS_PHOTO}_32_18.jpg", _jpg(32, 18)),
        "draw_mine": _put(root, "Draw", f"normal+{MY}+DrawManual+{TICKS_DRAW}@{TICKS_DRAW - 200}#30#30.png_30_30.png", _png(30, 30)),
        "draw_other": _put(root, "Draw", f"normal+{OTHER}+DrawManual+{TICKS_DRAW + 5}@1#30#30.png_30_30.png", _png(30, 30, (0, 200, 0, 255))),
        "frame": _put(root, "Limit", f"normal+{MY}+PhotoFrame+134200666834642217@134197135289994974.png_64_36.jpg", _jpg(64, 36)),
        # une pochette gardée en deux tailles dans deux dossiers différents : une seule création
        "cover_small": _put(root, "Limit", f"normal+{MY}+RecordCover+134332894628762385@134332894231269977.png_32_18.jpg", _jpg(32, 18)),
        "cover_big": _put(root, "Photo", f"normal+{MY}+RecordCover+134332894628762385@134332894231269977.png_64_36.jpg", _jpg(64, 36)),
        "nobg": _put(root, "NoBgPhoto", "Record_13500_134203319114149483_64_64.png", _png(64, 64)),
        "ann": _put(root, "Announcement", "1F0vfmAh0_32_32.jpg", _jpg(32, 32)),
        "other_photo": _put(root, "Photo", f"normal+{OTHER}+TakePhoto+134148789803426126.png_32_18.jpg", _jpg(32, 18)),
    }
    # bruit : pas une image du jeu, et un fichier au bon nom mais pas chiffré
    with open(os.path.join(root, "Photo", "lisezmoi.txt"), "w") as f:
        f.write("x")
    with open(os.path.join(root, "Draw", "normal+abc1234+DrawManual+134100000000000000@1#30#30.png_30_30.png"), "wb") as f:
        f.write(b"pas chiffre du tout, 31 octets!")
    with open(os.path.join(os.path.dirname(root), "Player.log"), "w", encoding="utf-8") as f:
        f.write("[GUI][Log] HeadIconWidget >> SetIcon >> normal/7ky0mne/Other/1.png\n"
                f"[GameLogic][Log] 上传图片 : normal/{MY}/RecordCover/1@2.png\n"
                f"[GameLogic][Log] 上传成功 : normal/{MY}/RecordCover/1@2.png\n"
                f"[GameLogic][Log] 上传图片 : index/20261003/Standalone/{MY}/3.idx\n")
    return {"root": root, "files": files}


# ---------------------------------------------------------------- chiffrement et noms
def test_chiffrement_aller_retour():
    for data in (b"", b"a", b"x" * 15, b"y" * 16, b"z" * 1000 + b"\x00\x01"):
        assert creations.decrypt_bytes(creations.encrypt_bytes(data)) == data
    assert len(creations.encrypt_bytes(b"x" * 16)) == 32            # bourrage PKCS7 : un bloc entier ajouté
    with pytest.raises(creations.CreationsError):
        creations.decrypt_bytes(b"123")
    assert creations.image_ext(_png(2, 2)) == ".png" and creations.image_ext(_jpg(2, 2)) == ".jpg"
    assert creations.image_ext(b"bonjour") is None


def test_filetime():
    t = creations.filetime_to_epoch(TICKS_PHOTO)
    assert abs(t - 1790981550.78) < 1             # 2026-10-02 22:52:30 UTC
    assert creations.filetime_to_epoch("pas un nombre") is None


@pytest.mark.parametrize("sub,name,expect", [
    ("Photo", f"normal+{MY}+TakePhoto+134148789803426126.png_256_144.jpg",
     {"kind": "TakePhoto", "cat": "photo", "player": MY, "w": 256, "h": 144, "ext": ".jpg"}),
    ("Draw", f"normal+{MY}+DrawManual+{TICKS_DRAW}@{TICKS_DRAW - 1}#150#84.png_150_84.png",
     {"kind": "DrawManual", "cat": "draw", "player": MY, "w": 150, "h": 84, "ext": ".png"}),
    ("Limit", f"normal+{MY}+MicroHomeland+1cf04861-d587-4159-8627-212e3b3182ec+134340697318032459.png_256_144.jpg",
     {"kind": "MicroHomeland", "cat": "home", "player": MY, "w": 256, "h": 144}),
    ("Limit", f"normal+{MY}+HomeEvaluate+134345004690140691.png_1564_880.jpg", {"cat": "home"}),
    ("Limit", f"normal+{MY}+Other+134349074380988746.png_300_300.jpg", {"cat": "other", "kind": "Other"}),
    ("Photo", "134354551507837507_1920_1080.jpg", {"kind": "Photo", "cat": "photo", "player": None, "w": 1920, "h": 1080}),
    ("Photo", "DressSuit134350968070010000_400_400.jpg", {"kind": "DressSuit", "cat": "dress"}),
    ("NoBgPhoto", "Record_13500_134203319114149483_256_256.png", {"kind": "Record", "cat": "cover", "ext": ".png"}),
    ("NoBgPhoto", "PaintCloth_14091001_134198128121007185#128#128_256_256.png", {"kind": "PaintCloth", "cat": "paint"}),
    ("NoBgPhoto", "Book_200159999_book_official_cover_1_256_256.png", {"kind": "Book", "cat": "book"}),
    ("Announcement", "1F0vfmAh0_128_128.jpg", {"kind": "Announcement", "cat": "announcement", "player": None}),
])
def test_parse_name(sub, name, expect):
    info = creations.parse_name(sub, name)
    assert info is not None
    for k, v in expect.items():
        assert info[k] == v, k
    assert info["base"] + f"_{info['w']}_{info['h']}" + (".jpg" if name.lower().endswith(("jpg", "jpeg")) else ".png") == name.replace(".jpeg", ".jpg")


def test_parse_name_ignore_le_reste():
    assert creations.parse_name("Photo", "lisezmoi.txt") is None
    assert creations.parse_name("Photo", "image.png") is None
    assert creations.parse_name("Photo", "x_12_34.gif") is None


def test_created_dans_le_nom():
    info = creations.parse_name("Photo", f"{TICKS_PHOTO}_1920_1080.jpg")
    assert abs(info["created"] - creations.filetime_to_epoch(TICKS_PHOTO)) < 1
    assert creations.parse_name("Announcement", "1F0vfmAh0_128_128.jpg")["created"] is None


def test_identifiant_du_joueur(tree, tmp_path):
    assert creations.my_player_id(creations.log_path(tree["root"])) == MY
    assert creations.my_player_id(str(tmp_path / "absent.log")) is None
    assert creations.my_player_id(None) is None


def test_dossier(tree, tmp_path):
    assert creations.looks_like_folder(tree["root"])
    assert not creations.looks_like_folder(str(tmp_path))
    assert not creations.looks_like_folder("")
    assert creations.find_folder(tree["root"]) == tree["root"]


# ---------------------------------------------------------------- lecture et regroupement
def test_scan_regroupe_les_tailles(tree):
    items = creations.scan(tree["root"], MY)
    by_kind = {(it["kind"], it["player"]): it for it in items}
    # 10 fichiers au nom du jeu = 9 créations (photo ×2 tailles, pochette ×2 dossiers) ; le fichier non
    # chiffré est listé (la lecture ne déchiffre rien), sa vignette échouera
    assert len(items) == 9
    photo = by_kind[("Photo", None)]
    assert photo["mine"] is True and photo["cat"] == "photo"
    assert [(v["w"], v["h"]) for v in photo["variants"]] == [(32, 18), (64, 36)]
    assert photo["largest"] == tree["files"]["photo_big"] and photo["w"] == 64
    assert abs(photo["created"] - creations.filetime_to_epoch(TICKS_PHOTO)) < 1
    cover = by_kind[("RecordCover", MY)]
    assert {v["folder"] for v in cover["variants"]} == {"Limit", "Photo"}
    assert cover["mine"] is True and cover["cat"] == "cover"
    assert by_kind[("DrawManual", MY)]["mine"] is True
    assert by_kind[("DrawManual", OTHER)]["mine"] is False
    assert by_kind[("TakePhoto", OTHER)]["mine"] is False
    assert by_kind[("Record", None)]["mine"] is None and by_kind[("Announcement", None)]["mine"] is None
    # vignette : la plus petite variante encore nette, sinon la plus grande (ici tout est petit)
    assert photo["thumb"] == tree["files"]["photo_big"]
    # tri : plus récentes d'abord (dates du nom), le dessin de l'autre joueur a un tick plus grand
    assert items[0]["kind"] == "Photo" and items[1]["player"] == OTHER and items[1]["kind"] == "DrawManual"
    assert items[-2]["player"] == "abc1234"                        # date de janvier 2026 dans le nom : avant-dernier
    assert items[-1]["kind"] == "Announcement" and items[-1]["created"] is None   # sans date : en fin de liste
    assert len({it["id"] for it in items}) == 9 and all(len(it["id"]) == 16 for it in items)
    # sans identifiant de joueur : seules les photos prises ici sont « à moi »
    items2 = creations.scan(tree["root"], None)
    assert {it["mine"] for it in items2 if it["player"]} == {None}
    assert next(it for it in items2 if it["kind"] == "Photo")["mine"] is True


def test_empreinte_du_dossier(tree):
    s1 = creations.folder_signature(tree["root"])
    assert s1 == creations.folder_signature(tree["root"])
    _put(tree["root"], "Draw", f"normal+{MY}+DrawManual+1@1#30#30.png_30_30.png", _png(30, 30))
    assert creations.folder_signature(tree["root"]) != s1


def test_vignette_et_image(tree):
    data, w, h = creations.thumbnail(tree["files"]["photo_big"], 240)
    assert data.startswith("data:image/jpeg;base64,") and (w, h) == (64, 36)
    data, w, h = creations.thumbnail(tree["files"]["nobg"], 32)
    assert data.startswith("data:image/png;base64,") and (w, h) == (32, 32)
    with pytest.raises(creations.CreationsError):
        creations.read_image(os.path.join(tree["root"], "Draw", "normal+abc1234+DrawManual+134100000000000000@1#30#30.png_30_30.png"))


# ---------------------------------------------------------------- remplacement, restauration, export
def _decoded(path):
    data = creations.read_image(path)
    return creations.image_ext(data), Image.open(io.BytesIO(data))


def test_remplacement_sauvegarde_et_restauration(tree, tmp_path):
    items = creations.scan(tree["root"], MY)
    photo = next(it for it in items if it["kind"] == "Photo")
    src = str(tmp_path / "moi.png")
    Image.new("RGB", (100, 100), (255, 255, 0)).save(src)      # carré : sera recadré en 16:9
    backup = str(tmp_path / "backup")
    originals = {v["path"]: open(v["path"], "rb").read() for v in photo["variants"]}

    assert creations.replace_item(photo, src, backup) == 2
    for v in photo["variants"]:
        ext, im = _decoded(v["path"])
        assert ext == ".jpg" and im.size == (v["w"], v["h"])
        r, g, b = im.convert("RGB").getpixel((v["w"] // 2, v["h"] // 2))
        assert r > 200 and g > 200 and b < 80                     # jaune, plus bleu
        bk = creations.backup_path(backup, v)
        assert open(bk, "rb").read() == originals[v["path"]]
    assert creations.has_backup(photo, backup)

    # second remplacement : la première sauvegarde (l'original du jeu) n'est jamais écrasée
    src2 = str(tmp_path / "moi2.png")
    Image.new("RGB", (64, 36), (0, 0, 255)).save(src2)
    assert creations.replace_item(photo, src2, backup) == 2
    for v in photo["variants"]:
        assert open(creations.backup_path(backup, v), "rb").read() == originals[v["path"]]

    assert creations.restore_item(photo, backup) == 2
    for v in photo["variants"]:
        assert open(v["path"], "rb").read() == originals[v["path"]]
    assert not creations.has_backup(photo, backup)
    assert creations.restore_item(photo, backup) == 0


def test_remplacement_png_garde_la_transparence(tree, tmp_path):
    items = creations.scan(tree["root"], MY)
    draw = next(it for it in items if it["kind"] == "DrawManual" and it["player"] == MY)
    src = str(tmp_path / "pixel.png")
    im = Image.new("RGBA", (15, 15), (10, 20, 30, 255))
    im.putpixel((0, 0), (0, 0, 0, 0))
    im.save(src)
    assert creations.replace_item(draw, src, str(tmp_path / "bk")) == 1
    ext, out = _decoded(draw["largest"])
    assert ext == ".png" and out.size == (30, 30) and out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((15, 15)) == (10, 20, 30, 255)   # ×2 au voisin le plus proche


def test_remplacement_ajuster(tree, tmp_path):
    """fit=contain : toute l'image est gardée, bandes blanches de chaque côté."""
    items = creations.scan(tree["root"], MY)
    photo = next(it for it in items if it["kind"] == "Photo")          # 64×36 et 32×18
    src = str(tmp_path / "carre.png")
    Image.new("RGB", (100, 100), (0, 0, 255)).save(src)
    assert creations.replace_item(photo, src, str(tmp_path / "bk"), fit="contain") == 2
    ext, im = _decoded(photo["largest"])
    im = im.convert("RGB")
    assert im.size == (64, 36)
    assert im.getpixel((32, 18))[2] > 200 and im.getpixel((32, 18))[0] < 60         # centre : bleu
    assert all(c > 230 for c in im.getpixel((2, 18)))                                # bande gauche : blanche
    assert all(c > 230 for c in im.getpixel((61, 18)))


# ---------------------------------------------------------------- dessins du jeu : indices de palette
def test_table_des_dessins():
    to_rgb, entries = creations._draw_tables()
    assert len(to_rgb) == 126 and len(entries) == 126
    assert to_rgb[248] == (254, 255, 255) and to_rgb[124] == (5, 22, 22)             # blanc, noir
    assert to_rgb[249] == (249, 246, 236) and to_rgb[252] == (65, 69, 69)            # crème, gris foncé
    assert to_rgb[128] == (207, 53, 77) and to_rgb[137] == (117, 94, 94)             # famille rouge : nuances 0 et 9
    assert to_rgb[138] == (233, 94, 43) and to_rgb[247] == (114, 94, 102)            # orange 0, rose 9
    assert 253 not in to_rgb and 127 not in to_rgb


def test_dessin_decode_encode():
    im = Image.new("RGB", (4, 1))
    im.putdata([(248, 248, 248), (124, 124, 124), (128, 128, 128), (250, 250, 250)])
    assert creations.is_indexed_drawing(im)
    dec = creations.decode_drawing(im)
    assert list(dec.getdata()) == [(254, 255, 255), (5, 22, 22), (207, 53, 77), (190, 191, 191)]
    assert not creations.is_indexed_drawing(Image.new("RGB", (4, 4), (200, 30, 30)))
    assert not creations.is_indexed_drawing(Image.new("RGB", (4, 4), (100, 100, 100)))          # gris inconnu
    # retour : couleur la plus proche, transparent = toile vierge (blanc)
    col = Image.new("RGBA", (4, 1))
    col.putdata([(255, 255, 255, 255), (0, 0, 0, 255), (210, 50, 80, 255), (0, 0, 0, 0)])
    assert list(creations.encode_drawing(col).getdata()) == [248, 124, 128, 248]


def test_remplacement_dessin_reencode_en_indices(tree, tmp_path):
    """Un dessin du jeu remplacé reste un PNG gris d'indices ; la vignette est rendue en couleurs."""
    items = creations.scan(tree["root"], MY)
    drawing = next(it for it in items if it["kind"] == "DrawManual" and it["player"] == MY)
    assert drawing["indexed"] is True
    # le dessin de test est un PNG couleur ordinaire : pas d'indices -> vignette telle quelle
    assert not creations.is_indexed_drawing(Image.open(io.BytesIO(creations.read_image(drawing["largest"]))))
    # on écrit d'abord un vrai dessin en indices (noir, blanc, rouge) à la place
    idx = Image.new("RGB", (30, 30), (248, 248, 248))
    for x in range(15):
        for y in range(30):
            idx.putpixel((x, y), (124, 124, 124) if y < 15 else (128, 128, 128))
    buf = io.BytesIO(); idx.save(buf, format="PNG")
    with open(drawing["largest"], "wb") as f:
        f.write(creations.encrypt_bytes(buf.getvalue()))
    data, w, h = creations.thumbnail(drawing["largest"], 240, drawing=True)
    assert data.startswith("data:image/png;base64,") and (w, h) == (30, 30)
    thumb = Image.open(io.BytesIO(__import__("base64").b64decode(data.split(",", 1)[1]))).convert("RGB")
    assert thumb.getpixel((5, 5)) == (5, 22, 22) and thumb.getpixel((5, 20)) == (207, 53, 77) and thumb.getpixel((25, 5)) == (254, 255, 255)
    # remplacement par une image couleur : réencodée en indices (bleu -> famille bleue, blanc -> 248)
    src = str(tmp_path / "bleu.png")
    pic = Image.new("RGB", (30, 30), (255, 255, 255))
    for x in range(15):
        for y in range(30):
            pic.putpixel((x, y), (5, 94, 166))
    pic.save(src)
    assert creations.replace_item(drawing, src, str(tmp_path / "bk")) == 1
    ext, out = _decoded(drawing["largest"])
    out = out.convert("RGB")
    # (5, 94, 166) = nuance 0 de la famille bleue, 9e famille de couleur -> 128 + 8×10
    assert ext == ".png" and out.getpixel((5, 5)) == (208, 208, 208) and out.getpixel((25, 5)) == (248, 248, 248)
    # export : en couleurs
    exp = creations.export_item(drawing, str(tmp_path / "dessin.png"))
    assert Image.open(exp).convert("RGB").getpixel((5, 5)) == (5, 94, 166)


def test_remplacement_erreurs(tree, tmp_path):
    items = creations.scan(tree["root"], MY)
    photo = next(it for it in items if it["kind"] == "Photo")
    with pytest.raises(creations.CreationsError):
        creations.replace_item(photo, str(tmp_path / "absent.png"), str(tmp_path / "bk"))
    bad = tmp_path / "pas-une-image.png"
    bad.write_bytes(b"nope")
    with pytest.raises(creations.CreationsError):
        creations.replace_item(photo, str(bad), str(tmp_path / "bk"))
    # rien n'a été écrit : les fichiers du jeu sont intacts
    assert creations.image_ext(creations.read_image(photo["largest"])) == ".jpg"


def test_export(tree, tmp_path):
    items = creations.scan(tree["root"], MY)
    photo = next(it for it in items if it["kind"] == "Photo")
    out = creations.export_item(photo, str(tmp_path / "sortie" / "photo.png"))   # extension corrigée
    assert out.endswith("photo.jpg") and creations.image_ext(open(out, "rb").read()) == ".jpg"
    assert Image.open(out).size == (64, 36)
    name = creations.suggested_export_name(photo)
    assert name.startswith("heartopia-photo-") and name.endswith("-64x36")


# ---------------------------------------------------------------- Api
@pytest.fixture
def api(tree, monkeypatch):
    import app
    a = object.__new__(app.Api)
    a._cfg = core.load_config()
    terms.accept(a._cfg, terms.TERMS_VERSION, "fr")
    a._cfg["creations"] = {"folder": tree["root"]}
    a._logs = deque(maxlen=50)
    a._toasts = deque(maxlen=10)
    a._toast_seq = 0
    a._ui_lock = threading.RLock()
    a._window = None
    a.folders = []
    import platform_io
    monkeypatch.setattr(platform_io, "open_folder", lambda path: a.folders.append(path))
    return a


def test_api_liste_vignette_et_vue(api, tree):
    r = api.creations_list()
    # par défaut : seulement ce que le joueur a fait (album photo, peintures), pas le cache du jeu
    assert r["ok"] and r["show_cache"] is False and r["cats"] == {}
    assert {x["section"] for x in r["items"]} <= {"photo", "painting", "music"}
    assert r["sections"].get("photo") == 1 and r["sections"].get("painting", 0) >= 1
    api._cfg["creations"]["show_cache"] = True
    r = api.creations_list()
    assert r["show_cache"] is True and r["sections"]["cache"] == sum(r["cats"].values())
    assert r["ok"] and r["found"] and r["folder"] == tree["root"] and r["my_id"] == MY
    assert r["total"] == 9 and r["cats"]["photo"] == 1 and r["cats"]["draw"] == 2
    bogus = next(x for x in r["items"] if x["player"] == "abc1234")
    assert api.creations_thumb(bogus["id"])["ok"] is False              # pas chiffré : vignette impossible
    it = next(x for x in r["items"] if x["kind"] == "Photo")
    assert it["mine"] is True and it["backup"] is False and len(it["variants"]) == 2
    assert "path" not in it["variants"][0]                       # jamais de chemin absolu vers l'interface
    th = api.creations_thumb(it["id"])
    assert th["ok"] and th["data"].startswith("data:image/") and (th["w"], th["h"]) == (64, 36)
    assert api.creations_thumb(it["id"])["data"] == th["data"]   # cache
    v = api.creations_view(it["id"])
    assert v["ok"] and v["item"]["id"] == it["id"]
    assert api.creations_thumb("inconnu") == {"ok": False, "id": "inconnu", "error": "unknown"}
    assert api.creations_open_folder() is True and api.folders == [tree["root"]]


def test_api_remplace_puis_restaure(api, tree, tmp_path):
    api._cfg["creations"]["show_cache"] = True
    r = api.creations_list()
    it = next(x for x in r["items"] if x["kind"] == "RecordCover")
    src = str(tmp_path / "cover.jpg")
    Image.new("RGB", (200, 100), (0, 255, 0)).save(src)
    out = api.creations_replace(it["id"], src)
    assert out["ok"] and out["files"] == 2 and out["item"]["backup"] is True
    bk = os.path.join(core.DATA_DIR, "creations_backup")
    assert os.path.isfile(os.path.join(bk, "Limit", it["variants"][0]["name"]))
    assert any(t["kind"] == "ok" for t in api._toasts)
    assert next(x for x in api.creations_list()["items"] if x["id"] == it["id"])["backup"] is True
    out = api.creations_restore(it["id"])
    assert out["ok"] and out["files"] == 2 and out["item"]["backup"] is False
    assert api.creations_restore(it["id"]) == {"ok": False, "error": "no_backup"}
    assert api.creations_replace("inconnu", src) == {"ok": False, "error": "unknown"}
    assert api.creations_replace(it["id"], str(tmp_path / "absent.png"))["error"] == "not_image"


def test_api_peinture_non_remplacable(api, tree, tmp_path):
    """Le fichier local d'une peinture n'est qu'un aperçu : le remplacement est refusé, rien n'est écrit."""
    it = next(x for x in api.creations_list()["items"] if x["section"] == "painting")
    src = str(tmp_path / "img.png")
    Image.new("RGB", (30, 30), (0, 0, 255)).save(src)
    before = open(tree["draw_mine"], "rb").read() if "draw_mine" in tree else None
    assert api.creations_replace(it["id"], src) == {"ok": False, "error": "painting_readonly"}
    if before is not None:
        assert open(tree["draw_mine"], "rb").read() == before
    assert api.creations_list()["items"][0] is not None


def test_api_dossier(api, tree, tmp_path, monkeypatch):
    assert api.creations_set_folder(str(tmp_path)) == {"ok": False, "error": "bad_folder"}
    assert api._cfg["creations"]["folder"] == tree["root"]
    api._cfg["creations"] = {"folder": str(tmp_path / "nulle-part")}
    monkeypatch.setattr(creations, "candidate_folders", lambda: [])
    r = api.creations_list(refresh=True)
    assert r["ok"] and not r["found"] and r["items"] == []
    assert api.creations_open_folder() is False
    assert api.creations_set_folder(tree["root"])["ok"] and api.creations_list()["found"]


def test_api_sans_cryptography(api, monkeypatch):
    monkeypatch.setattr(creations, "available", lambda: False)
    r = api.creations_list()
    assert not r["ok"] and r["available"] is False and r["error"] == "no_crypto"


def test_config_livree_sans_dossier_perso():
    import make_default_config
    clean = make_default_config.sanitize({"creations": {"folder": "C:\\quelque\\part"}})
    assert "creations" not in clean


# ---------------------------------------------------------------- musiques du jeu (game_music.py), ajouts
import base64

import game_music

UID = 176436626679


def _record_events():
    """Do3, Do#3 puis Do6 au piano : touches 10001, 10201, 10022."""
    ev = []
    for i, key in enumerate((10001, 10201, 10022)):
        ev.append((i * 0.5, UID, 1, 1, key, 4.2))
        ev.append((i * 0.5 + 0.25, UID, 1, 0, key, 4.2))
    return ev


def _midi(path, notes=(60, 64, 67, 100)):
    import mido
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    for n in notes:
        tr.append(mido.Message("note_on", note=n, velocity=90, time=0))
        tr.append(mido.Message("note_off", note=n, velocity=0, time=240))
    mid.save(path)
    return path


@pytest.fixture
def music_tree(tree):
    """Dossier `record` à côté de ScreenCapture : une musique du joueur, une d'un autre (remote)."""
    d = os.path.join(os.path.dirname(tree["root"]), "record", MY)
    os.makedirs(os.path.join(d, "remote"))
    data = game_music.build(_record_events())
    mine = os.path.join(d, "Ma chanson_20261002214732749_1250.bin")
    other = os.path.join(d, "remote", "Autre_20260207201802184_1250.bin")
    for p in (mine, other):
        with open(p, "wb") as f:
            f.write(data)
    return dict(tree, music=mine, music_other=other, record_dir=d)


def test_musique_format_aller_retour():
    data = game_music.build(_record_events())
    assert data[:4] == b"DCER" and len(data) == 10 + 6 * 26 + 4
    rec = game_music.parse(data)
    assert len(rec["events"]) == 6 and rec["duration"] == pytest.approx(1.25)
    assert game_music.build(rec["events"]) == data
    assert game_music.summary(rec) == {"notes": 3, "duration": pytest.approx(1.25), "players": 1, "instruments": [1]}
    with pytest.raises(game_music.MusicError):
        game_music.parse(b"RIFFxxxxxxxxxxxx")
    with pytest.raises(game_music.MusicError):
        game_music.parse(data[:40])


def test_musique_touches_et_noms():
    assert [game_music.key_to_midi(k) for k in (10001, 10008, 10022, 10201, 10215)] == [48, 60, 84, 49, 82]
    assert game_music.key_to_midi(11088, 11086) == 64                  # 3e touche d'un instrument à 15 notes
    info = game_music.parse_name("Young nd Beautiful_20260908221633739_223794.bin")
    assert info["name"] == "Young nd Beautiful" and info["ms"] == 223794 and info["created"]
    assert game_music.parse_name("notes.txt") is None
    assert game_music.safe_title("AC/DC: Back_in_Black (live) [2024] version longue") == "AC DC Back in Black live"
    name = game_music.file_name("Été & co", 12.3456, now=1790000000.5)
    assert game_music.parse_name(name)["ms"] == 12346 and name.startswith("Été co_")


def test_musique_midi_dans_les_deux_sens(tmp_path):
    import mido
    out = game_music.to_midi(game_music.parse(game_music.build(_record_events())), str(tmp_path / "x.mid"))
    notes = [m.note for tr in mido.MidiFile(out).tracks for m in tr if m.type == "note_on" and m.velocity]
    assert notes == [48, 49, 84]
    ev = game_music.from_midi(_midi(str(tmp_path / "in.mid")), core.load_config(), UID, 4.2)
    assert all(e[1] == UID and e[2] == 1 and e[5] == pytest.approx(4.2) for e in ev)
    assert [e[0] for e in ev] == sorted(e[0] for e in ev) and ev[0][0] == 0
    downs = [e[4] for e in ev if e[3]]
    assert len(downs) == 4 and all(10001 <= k <= 10022 or 10201 <= k <= 10215 for k in downs)
    assert len([e for e in ev if not e[3]]) == 4
    assert game_music.parse(game_music.build(ev))["events"][-1][3] == 0


def test_musique_liste(music_tree):
    root = game_music.root_of(music_tree["root"])
    items = game_music.scan(root, MY)
    mine = next(i for i in items if not i["remote"])
    assert mine["section"] == "music" and mine["name"] == "Ma chanson" and mine["notes"] == 3
    assert mine["duration"] == pytest.approx(1.25) and mine["mine"] is True
    assert next(i for i in items if i["remote"])["section"] == "cache"
    assert creations.player_id_from_dirs(music_tree["root"]) == MY


def test_api_musique_remplace_exporte_restaure(api, music_tree, tmp_path):
    r = api.creations_list()
    assert r["sections"]["music"] == 1                                    # celle des autres reste dans le cache
    it = next(x for x in r["items"] if x["cat"] == "music")
    assert it["name"] == "Ma chanson" and it["added"] is False
    v = api.creations_view(it["id"])
    assert v["ok"] and v["data"] is None and v["music"]["notes"] == 3
    before = open(music_tree["music"], "rb").read()
    out = api.creations_replace(it["id"], _midi(str(tmp_path / "in.mid")))
    assert out["ok"] and out["item"]["backup"] is True and out["item"]["notes"] == 4
    rec = game_music.read(music_tree["music"])
    assert {e[1] for e in rec["events"]} == {UID}                         # numéro du joueur repris de ses musiques
    out = api.creations_restore(it["id"])
    assert out["ok"] and open(music_tree["music"], "rb").read() == before
    (tmp_path / "faux.mid").write_bytes(b"pas un fichier MIDI")
    assert api.creations_replace(it["id"], str(tmp_path / "faux.mid"))["ok"] is False
    assert open(music_tree["music"], "rb").read() == before


def test_api_ajoute_puis_supprime(api, music_tree, tmp_path):
    n0 = api.creations_list()["sections"]
    src = str(tmp_path / "nouvelle.png")
    Image.new("RGB", (400, 400), (10, 200, 90)).save(src)
    out = api.creations_add("photo", src, "contain")
    assert out["ok"] and out["item"]["section"] == "photo" and out["item"]["added"] is True
    assert sorted((v["w"], v["h"]) for v in out["item"]["variants"]) == sorted(creations.PHOTO_SIZES)
    base = out["item"]["variants"][0]["name"].split("_")[0]
    big = os.path.join(music_tree["root"], "Photo", f"{base}_1920_1080.jpg")
    assert Image.open(io.BytesIO(creations.read_image(big))).size == (1920, 1080)
    info = os.path.join(creations.info_dir(music_tree["root"], MY), base)
    raw = open(info, "rb").read()
    assert raw[:3] == b"\xef\xbb\xbf" and MY in base64.b64decode(raw[3:]).decode()
    out2 = api.creations_add("music", _midi(str(tmp_path / "Mon morceau.mid")))
    assert out2["ok"] and out2["item"]["name"] == "Mon morceau" and out2["item"]["added"] is True
    n1 = api.creations_list()["sections"]
    assert n1["photo"] == n0["photo"] + 1 and n1["music"] == n0["music"] + 1
    # suppression : seulement les ajouts, jamais un fichier du jeu
    game_item = next(x for x in api.creations_list()["items"] if x["cat"] == "music" and not x["added"])
    assert api.creations_delete(game_item["id"])["ok"] is False and os.path.isfile(music_tree["music"])
    assert api.creations_delete(out["item"]["id"]) == {"ok": True, "files": 5}
    assert not os.path.exists(big) and not os.path.exists(info)
    assert api.creations_delete(out2["item"]["id"]) == {"ok": True, "files": 1}
    assert api.creations_list()["sections"] == n0
    assert api.creations_add("painting", src)["error"] == "bad_section"


def test_api_ecoute_une_musique_du_jeu_sans_doublon(api, music_tree, monkeypatch):
    """« Écouter sur cet ordinateur » : convertie en MIDI dans la bibliothèque, sélectionnée, préécoutée."""
    import mido

    class FakeLibrary:
        def meta(self, sid):
            return {}

    class FakePlayer:
        def __init__(self, folder):
            self.songs_folder, self.songs, self.state, self.played, self.index = folder, [], "stopped", [], 0
            self.library = FakeLibrary()

        def refresh_songs(self):
            self.songs = sorted(os.path.join(self.songs_folder, f) for f in os.listdir(self.songs_folder))

        def select(self, i):
            self.index = i

        def play(self, target):
            self.played.append((target, os.path.basename(self.songs[self.index])))

        def stop(self, join=False):
            self.state = "stopped"

    folder = os.path.join(os.path.dirname(music_tree["root"]), "songs")
    os.makedirs(folder)
    api._player = FakePlayer(folder)
    api.get_state = lambda: {}
    it = next(x for x in api.creations_list()["items"] if x["cat"] == "music")
    for _ in range(2):                                                # deux écoutes : un seul fichier
        out = api.creations_listen(it["id"])
        assert out["ok"] and out["song"] == "Heartopia - Ma chanson.mid"
    assert os.listdir(folder) == ["Heartopia - Ma chanson.mid"]
    assert api._player.played == [("preview", "Heartopia - Ma chanson.mid")] * 2
    notes = [m.note for tr in mido.MidiFile(os.path.join(folder, out["song"])).tracks for m in tr
             if m.type == "note_on" and m.velocity]
    assert notes == [48, 49, 84]
    photo = next(x for x in api.creations_list()["items"] if x["section"] == "photo")
    assert api.creations_listen(photo["id"])["ok"] is False           # une image ne s'écoute pas
