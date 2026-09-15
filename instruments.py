# -*- coding: utf-8 -*-
"""Catalogue des instruments de Heartopia, dispositions de touches et profils utilisateur.

Quatre objets distincts, volontairement separes :
  - le TYPE d'instrument (identite sonore, une carte, une image) : assets/instruments/catalogue.json ;
  - la DISPOSITION musicale du jeu (nombre de notes, rangees, touches) : assets/instruments/layouts.json ;
  - la DISPOSITION du clavier physique (AZERTY / QWERTY) : simple affaire de libelles ;
  - le PROFIL utilisateur (disposition retenue, touches personnalisees, statut) : config.json.

Les touches internes ("a", ";", "2"...) sont des POSITIONS physiques nommees d'apres le clavier QWERTY US :
c'est la semantique de platform_io.SCANCODES (scancodes set 1). Le libelle affiche depend de la disposition
du clavier de l'utilisateur et ne change jamais la position envoyee au jeu.

Provenance : les correspondances viennent de projets communautaires. « documente par une source » n'est pas
« confirme sur cette installation », et aucun profil n'a ete teste dans Heartopia depuis ce depot.

Ce module n'importe que la bibliotheque standard et platform_io : c'est core.py qui importe instruments.
"""
import hashlib
import json
import os
import sys

from platform_io import SCANCODES

SCHEMA_VERSION = 1

# Anciens identifiants de config.json -> identifiants du catalogue.
LEGACY_IDS = {"piano": "piano", "flute": "recorder", "luth": "lute", "guitare": "lute"}

# Statuts de verification d'un profil, du moins sur au plus sur.
STATUS_UNKNOWN = "unknown"
STATUS_DOCUMENTED = "documented"
STATUS_CUSTOM = "custom"
STATUS_QUICK = "quick-tested"
STATUS_CONFIRMED = "confirmed"
STATUSES = (STATUS_UNKNOWN, STATUS_DOCUMENTED, STATUS_CUSTOM, STATUS_QUICK, STATUS_CONFIRMED)
STATUS_LABELS = {
    STATUS_UNKNOWN: "Touches à configurer",
    STATUS_DOCUMENTED: "Profil documenté · à vérifier",
    STATUS_CUSTOM: "Touches personnalisées · à vérifier",
    STATUS_QUICK: "Test rapide réussi · vérification partielle",
    STATUS_CONFIRMED: "Confirmé sur cet ordinateur",
}
# Statuts qui autorisent la lecture (un instrument percussif au statut « documented » reste candidat :
# une source communautaire donne une correspondance MIDI, cela ne prouve pas ce que produit chaque frappe).
PLAYABLE_STATUSES = (STATUS_DOCUMENTED, STATUS_CUSTOM, STATUS_QUICK, STATUS_CONFIRMED)

# Noms de notes, convention d'affichage du dossier : Do4 / C4 = MIDI 60.
NOTE_NAMES_EN = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# Alterations notees avec le diese typographique « ♯ », comme dans layouts.json et dans l'interface
# (ui/instruments.js) : une seule orthographe pour une meme note, d'un bout a l'autre.
NOTE_NAMES_FR = ("Do", "Do♯", "Ré", "Ré♯", "Mi", "Fa", "Fa♯", "Sol", "Sol♯", "La", "La♯", "Si")

RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


class InstrumentDataError(RuntimeError):
    """Catalogue ou dispositions illisibles : message pret a afficher."""


# ---------------------------------------------------------------- notes
def note_name(midi):
    """Nom international d'une note MIDI (C4 = 60)."""
    m = int(midi)
    return f"{NOTE_NAMES_EN[m % 12]}{m // 12 - 1}"


def solfege(midi):
    """Nom francais d'une note MIDI (Do4 = 60)."""
    m = int(midi)
    return f"{NOTE_NAMES_FR[m % 12]}{m // 12 - 1}"


# ---------------------------------------------------------------- clavier physique
KEYBOARD_LAYOUTS = ("qwerty", "azerty")

# Position QWERTY US -> legende imprimee sur un clavier AZERTY francais. La position envoyee au jeu ne
# change pas : seule l'etiquette affichee change.
AZERTY_LABELS = {
    "1": "&", "2": "é", "3": '"', "4": "'", "5": "(", "6": "-", "7": "è", "8": "_", "9": "ç", "0": "à",
    "-": ")", "=": "=",
    "q": "A", "w": "Z", "e": "E", "r": "R", "t": "T", "y": "Y", "u": "U", "i": "I", "o": "O", "p": "P",
    "[": "^", "]": "$",
    "a": "Q", "s": "S", "d": "D", "f": "F", "g": "G", "h": "H", "j": "J", "k": "K", "l": "L",
    ";": "M", "'": "ù",
    "z": "W", "x": "X", "c": "C", "v": "V", "b": "B", "n": "N", "m": ",", ",": ";", ".": ":", "/": "!",
}

# Identifiants de langue Windows dont la disposition est connue. Hors de ces listes, la detection ne
# conclut pas (elle renvoie None) : l'utilisateur choisit lui-meme dans les reglages.
_AZERTY_LANGIDS = {0x040C, 0x080C}                                   # francais (France), francais (Belgique)
_QWERTY_LANGIDS = {0x0409, 0x0809, 0x0C09, 0x1009, 0x1409, 0x0C0C,   # anglais, francais (Canada)
                   0x040A, 0x0C0A, 0x0410, 0x0416, 0x0816}           # espagnol, italien, portugais


def detect_keyboard_layout():
    """Disposition du clavier systeme : "azerty", "qwerty", ou None si la detection n'est pas fiable."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        hkl = ctypes.windll.user32.GetKeyboardLayout(0)
    except Exception:  # noqa : pas de detection, pas de conclusion
        return None
    langid = int(hkl) & 0xFFFF
    if langid in _AZERTY_LANGIDS:
        return "azerty"
    if langid in _QWERTY_LANGIDS:
        return "qwerty"
    return None


def resolve_keyboard_layout(value):
    """Disposition effective a partir de la preference ("auto" | "qwerty" | "azerty")."""
    v = str(value or "auto").lower()
    if v in KEYBOARD_LAYOUTS:
        return v
    return detect_keyboard_layout() or "qwerty"


def key_label(key, keyboard_layout="qwerty"):
    """Legende affichee pour une position de touche, sur la disposition demandee."""
    k = str(key or "").lower()
    if not k:
        return ""
    if str(keyboard_layout or "").lower() == "azerty":
        label = AZERTY_LABELS.get(k, k)
    else:
        label = k
    # Les lettres s'affichent en majuscule ; chiffres, ponctuation et lettres accentuees restent tels
    # qu'ils sont imprimes sur la touche.
    return label.upper() if len(label) == 1 and label.isascii() and label.isalpha() else label


def key_needs_shift(key, keyboard_layout="qwerty"):
    """Vrai si la position demande Maj sur cette disposition (chiffres en AZERTY).

    Pertinent seulement en mode d'entree "vk" : c'est alors le code virtuel qui part, et VK_2 non modifie
    produit « é » sur un clavier francais. En mode "scancode" (defaut) c'est la position qui part : rien a
    compenser. Sert a AVERTIR, jamais a injecter un Maj automatique."""
    k = str(key or "").lower()
    return str(keyboard_layout or "").lower() == "azerty" and k in "0123456789" and len(k) == 1


# ---------------------------------------------------------------- catalogue
class Layout:
    """Disposition musicale du jeu : les notes offertes et la position de chaque touche."""

    def __init__(self, raw):
        self.id = str(raw.get("layoutId") or "")
        self.label = raw.get("labelFr") or self.id
        self.description = raw.get("descriptionFr") or ""
        self.note_count = int(raw.get("noteCount") or 0)
        self.rows = [int(n) for n in (raw.get("rows") or [])]
        self.auto_transpose = raw.get("autoTranspose") or "key"
        self.keyboard_reference = raw.get("keyboardReference") or "QWERTY US"
        self.status = raw.get("status") or "unknown"
        self.source_urls = list(raw.get("sourceUrls") or [])
        self.must_match = bool(raw.get("inGameLayoutMustMatch", True))
        self.notes = []
        for n in raw.get("notes") or []:
            midi = int(n["midi"])
            self.notes.append({"midi": midi,
                               "note": n.get("note") or note_name(midi),
                               "solfege": n.get("solfege") or solfege(midi),
                               "key": str(n.get("key") or "").lower(),
                               "position": n.get("position") or ""})
        self._bindings = {n["midi"]: n["key"] for n in self.notes}

    def bindings(self):
        """{note MIDI : position de touche} de la disposition."""
        return dict(self._bindings)

    def note_rows(self):
        """Notes decoupees en rangees d'affichage, suivant `rows`."""
        return _split_rows(self.notes, self.rows)

    def to_dict(self, with_notes=True):
        d = {"layoutId": self.id, "labelFr": self.label, "descriptionFr": self.description,
             "noteCount": self.note_count, "rows": list(self.rows), "autoTranspose": self.auto_transpose,
             "keyboardReference": self.keyboard_reference, "status": self.status,
             "sourceUrls": list(self.source_urls), "inGameLayoutMustMatch": self.must_match}
        if with_notes:
            d["notes"] = [dict(n) for n in self.notes]
        return d


class InstrumentType:
    """Type d'instrument : une identite sonore, une carte, une image. Jamais une variante esthetique."""

    def __init__(self, raw):
        self.id = str(raw.get("instrumentId") or "")
        self.label_fr = raw.get("labelFr") or self.id
        self.label_fr_status = raw.get("labelFrStatus") or ""
        self.label_en = raw.get("labelEn") or self.id
        self.aliases = [str(a) for a in (raw.get("aliases") or [])]
        self.category = raw.get("category") or ""
        self.image = raw.get("image") or ""
        self.supported_layout_ids = [str(x) for x in (raw.get("supportedLayoutIds") or [])]
        self.default_layout_id = raw.get("defaultLayoutId") or None
        self.mapping_status = raw.get("mappingStatus") or "unknown"
        self.percussive = bool(raw.get("percussive", False))
        self.preview_program = int(raw.get("previewProgram") or 0)
        self.polyphony = raw.get("polyphony")
        self.sounding_pitch_offset = raw.get("soundingPitchOffset")
        self.game_version = raw.get("gameVersion")
        self.source_urls = list(raw.get("sourceUrls") or [])
        self.catalog_item_ids = [str(x) for x in (raw.get("catalogItemIds") or [])]
        self.variant_count = int(raw.get("variantCount") or 1)
        self.image_source_url = raw.get("imageSourceUrl") or ""
        self.grouping_status = raw.get("groupingStatus") or ""

    def __repr__(self):  # pragma: no cover - confort de debogage
        return f"<InstrumentType {self.id}>"


class Catalogue:
    """Le catalogue charge : les types dans l'ordre du fichier, les dispositions, les categories."""

    def __init__(self, raw, layouts_raw):
        self.schema_version = int(raw.get("schemaVersion") or 1)
        self.retrieved_at = raw.get("retrievedAt") or ""
        self.octave_convention = raw.get("octaveConvention") or "C4 = MIDI 60"
        self.notes = list(raw.get("notes") or [])
        self.source_urls = list(raw.get("sourceUrls") or [])
        self.categories = [(c.get("id"), c.get("labelFr")) for c in (raw.get("categories") or [])]
        self.types = [InstrumentType(t) for t in (raw.get("instruments") or [])]
        self.by_id = {t.id: t for t in self.types}
        self.layouts = {}
        for lay in layouts_raw.get("layouts") or []:
            layout = Layout(lay)
            self.layouts[layout.id] = layout

    def layouts_for(self, instrument_id):
        """Dispositions candidates d'un type (objets Layout, dans l'ordre du catalogue)."""
        t = self.by_id.get(instrument_id)
        if t is None:
            return []
        return [self.layouts[lid] for lid in t.supported_layout_ids if lid in self.layouts]

    def category_label(self, category_id):
        for cid, label in self.categories:
            if cid == category_id:
                return label
        return category_id or ""


def data_dir(res_dir=None):
    """Dossier des donnees d'instruments : <res_dir>/assets/instruments."""
    return os.path.join(res_dir or RES_DIR, "assets", "instruments")


_CACHE = {}


def load_catalogue(res_dir=None):
    """Catalogue + dispositions, mis en cache par dossier. Leve InstrumentDataError si illisible."""
    folder = os.path.abspath(data_dir(res_dir))
    cached = _CACHE.get(folder)
    if cached is not None:
        return cached
    cat_path = os.path.join(folder, "catalogue.json")
    lay_path = os.path.join(folder, "layouts.json")
    try:
        with open(cat_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        with open(lay_path, "r", encoding="utf-8") as f:
            layouts_raw = json.load(f)
    except OSError as e:
        raise InstrumentDataError(f"catalogue des instruments illisible ({e.strerror or e})") from None
    except ValueError as e:
        raise InstrumentDataError(f"catalogue des instruments invalide ({e})") from None
    if not raw.get("instruments"):
        raise InstrumentDataError("catalogue des instruments vide")
    if not layouts_raw.get("layouts"):
        raise InstrumentDataError("aucune disposition de touches dans layouts.json")
    cat = Catalogue(raw, layouts_raw)
    _CACHE[folder] = cat
    return cat


def clear_cache():
    """Vide le cache du catalogue (tests, rechargement a chaud)."""
    _CACHE.clear()


def _split_rows(items, rows):
    """Decoupe une liste selon des tailles de rangees ; le reste part dans une derniere rangee."""
    out, i = [], 0
    for n in rows or []:
        if i >= len(items):
            break
        out.append(list(items[i:i + n]))
        i += n
    if i < len(items):
        out.append(list(items[i:]))
    return out


# ---------------------------------------------------------------- profils utilisateur
def _int_bindings(bindings):
    """{note MIDI (int) : position} a partir d'une table dont les cles peuvent etre des chaines."""
    out = {}
    for midi, key in (bindings or {}).items():
        try:
            m = int(midi)
        except (TypeError, ValueError):
            continue
        k = str(key or "").lower()
        if k and 0 <= m <= 127:
            out[m] = k
    return out


def _str_bindings(bindings):
    """Table prete pour JSON : cles MIDI en chaines, triees."""
    b = _int_bindings(bindings)
    return {str(m): b[m] for m in sorted(b)}


def default_profile(itype):
    """Profil livre d'un type : sa disposition par defaut, ou « touches a configurer »."""
    layout_id = itype.default_layout_id if itype.supported_layout_ids else None
    return {"schemaVersion": SCHEMA_VERSION,
            "layoutId": layout_id,
            "keyboardLayout": None,
            "verificationStatus": STATUS_DOCUMENTED if layout_id else STATUS_UNKNOWN,
            "verifiedAt": None,
            "gameVersion": None,
            "polyphony": None,
            "soundingPitchOffset": None}


def default_profiles(catalogue=None):
    """Profils par defaut des types du catalogue, dans l'ordre du fichier."""
    cat = catalogue or load_catalogue()
    return {t.id: default_profile(t) for t in cat.types}


def _normalize_profile(raw, itype, catalogue):
    """Profil au format courant, complet et coherent. N'invente jamais de touches."""
    raw = raw if isinstance(raw, dict) else {}
    bindings = _int_bindings(raw.get("bindings"))
    layout_id = raw.get("layoutId") or None
    if layout_id not in catalogue.layouts:
        layout_id = None
    status = raw.get("verificationStatus")
    if status not in STATUSES:
        status = None
    if status is None or status == STATUS_UNKNOWN:
        # un profil qui possede reellement des touches n'est pas « a configurer »
        if bindings:
            status = STATUS_CUSTOM
        elif layout_id:
            status = STATUS_DOCUMENTED
        else:
            status = STATUS_UNKNOWN
    if not bindings and not layout_id:
        status = STATUS_UNKNOWN
    kb = raw.get("keyboardLayout")
    kb = kb if kb in KEYBOARD_LAYOUTS else None
    prof = {"schemaVersion": SCHEMA_VERSION,
            "layoutId": layout_id,
            "keyboardLayout": kb,
            "verificationStatus": status,
            "verifiedAt": raw.get("verifiedAt") or None,
            "gameVersion": raw.get("gameVersion") if raw.get("gameVersion") is not None
            else (itype.game_version if itype is not None else None),
            "polyphony": raw.get("polyphony") if raw.get("polyphony") is not None
            else (itype.polyphony if itype is not None else None),
            "soundingPitchOffset": raw.get("soundingPitchOffset") if raw.get("soundingPitchOffset") is not None
            else (itype.sounding_pitch_offset if itype is not None else None)}
    if bindings:
        prof["bindings"] = _str_bindings(bindings)
    return prof


def profile_of(cfg, instrument_id, catalogue=None):
    """Profil normalise d'un type (jamais None ; le profil livre si la config n'en a pas)."""
    cat = catalogue or load_catalogue()
    itype = cat.by_id.get(instrument_id)
    raw = (cfg.get("instruments") or {}).get(instrument_id)
    if raw is None:
        return default_profile(itype) if itype is not None else {
            "schemaVersion": SCHEMA_VERSION, "layoutId": None, "keyboardLayout": None,
            "verificationStatus": STATUS_UNKNOWN, "verifiedAt": None, "gameVersion": None,
            "polyphony": None, "soundingPitchOffset": None}
    return _normalize_profile(raw, itype, cat)


_KEEP = object()


def set_profile(cfg, instrument_id, *, layout_id=_KEEP, bindings=_KEEP, status=_KEEP, verified_at=_KEEP,
                keyboard_layout=_KEEP, catalogue=None):
    """Ecrit (et renvoie) le profil d'un type dans cfg["instruments"]. Les champs absents sont conserves.

    `bindings=None` efface les touches personnalisees (retour aux touches de la disposition)."""
    cat = catalogue or load_catalogue()
    prof = profile_of(cfg, instrument_id, cat)
    if layout_id is not _KEEP:
        prof["layoutId"] = layout_id if layout_id in cat.layouts else None
    if bindings is not _KEEP:
        b = _int_bindings(bindings)
        lay = cat.layouts.get(prof.get("layoutId") or "")
        if not b or (lay is not None and lay.bindings() == b):
            prof.pop("bindings", None)      # identiques a la disposition : rien a stocker
        else:
            prof["bindings"] = _str_bindings(b)
    if keyboard_layout is not _KEEP:
        prof["keyboardLayout"] = keyboard_layout if keyboard_layout in KEYBOARD_LAYOUTS else None
    if status is not _KEEP and status in STATUSES:
        prof["verificationStatus"] = status
    if verified_at is not _KEEP:
        prof["verifiedAt"] = verified_at
    itype = cat.by_id.get(instrument_id)
    prof = _normalize_profile(prof, itype, cat)
    cfg.setdefault("instruments", {})[instrument_id] = prof
    return prof


# ---------------------------------------------------------------- migration
def _is_legacy(spec):
    """Ancien format de config.json : une liste de touches et une note la plus grave."""
    return isinstance(spec, dict) and "keys" in spec and "lowest_note" in spec


def _legacy_bindings(spec):
    keys = [str(k).lower() for k in (spec.get("keys") or [])]
    scale = list(spec.get("scale") or range(len(keys)))
    lowest = int(spec.get("lowest_note", 60))
    return {lowest + int(o): k for o, k in zip(scale, keys) if k}


def _octave_delta(bindings, other):
    """Ecart en demi-tons si `bindings` est `other` transpose d'un nombre entier d'octaves, sinon None.

    Les anciens profils du depot posaient parfois une octave de reference differente pour les memes
    touches : les positions envoyees au jeu sont alors identiques, seule la hauteur supposee change."""
    if not bindings or len(bindings) != len(other):
        return None
    a = sorted(bindings.items())
    b = sorted(other.items())
    if [k for _, k in a] != [k for _, k in b]:
        return None
    delta = a[0][0] - b[0][0]
    if delta % 12 != 0:
        return None
    if any(x[0] - y[0] != delta for x, y in zip(a, b)):
        return None
    return delta


def _match_layout(bindings, itype, catalogue):
    """layout_id si les touches sont EXACTEMENT celles d'une disposition candidate, sinon None.

    Une table transposee d'une octave n'est pas la table documentee : les positions envoyees au jeu sont
    les memes, mais l'octave de reference est un reglage de l'utilisateur (il a accorde son profil sur son
    installation). La remplacer par la table externe deplacerait la musique d'une octave en silence, ce que
    la migration n'a pas le droit de faire. Ce cas part donc en profil « personnalise », touches conservees."""
    for lid in itype.supported_layout_ids:
        lay = catalogue.layouts.get(lid)
        if lay is not None and lay.bindings() == bindings:
            return lid
    return None


def _closest_layout(bindings, itype, catalogue):
    """Disposition la plus proche d'une table personnalisee, ou None.

    On compare d'abord les associations identiques (note ET touche), puis les positions communes, puis le
    nombre de notes : deux dispositions de 15 notes ne se confondent pas, leurs touches different."""
    best = None
    for lid in itype.supported_layout_ids:
        lay = catalogue.layouts.get(lid)
        if lay is None:
            continue
        lb = lay.bindings()
        score = (sum(1 for m, k in bindings.items() if lb.get(m) == k),
                 len(set(bindings.values()) & set(lb.values())),
                 -abs(len(lb) - len(bindings)))
        if best is None or score > best[0]:
            best = (score, lid)
    return best[1] if best else None


def migrate_config(cfg, catalogue=None):
    """Met cfg au format courant des instruments. Idempotente. Renvoie le journal des changements.

    Preserve le travail de l'utilisateur : des touches personnalisees ne sont jamais remplacees par une
    table externe, et un identifiant inconnu du catalogue est conserve tel quel."""
    cat = catalogue or load_catalogue()
    log = []
    raw_insts = cfg.get("instruments")
    if not isinstance(raw_insts, dict):
        raw_insts = {}
    # aucune variante esthetique nulle part
    for key in ("skinId", "selectedVariantId"):
        if cfg.pop(key, None) is not None:
            log.append(f"clé « {key} » retirée (aucune variante esthétique)")

    migrated = {}
    unknown = {}
    for ident, spec in raw_insts.items():
        new_id = LEGACY_IDS.get(ident, ident)
        itype = cat.by_id.get(new_id)
        if isinstance(spec, dict):
            for key in ("skinId", "selectedVariantId"):
                if spec.pop(key, None) is not None:
                    log.append(f"{new_id} : « {key} » retiré (aucune variante esthétique)")
        if itype is None:
            unknown[ident] = spec          # travail de l'utilisateur : conserve, ignore a la resolution
            continue
        if new_id != ident:
            log.append(f"« {ident} » devient « {new_id} »")
        if not _is_legacy(spec):
            prof = _normalize_profile(spec, itype, cat)
        else:
            bindings = _legacy_bindings(spec)
            lid = _match_layout(bindings, itype, cat)
            if lid is not None:
                prof = {"schemaVersion": SCHEMA_VERSION, "layoutId": lid, "keyboardLayout": None,
                        "verificationStatus": STATUS_DOCUMENTED, "verifiedAt": None, "gameVersion": None,
                        "polyphony": None, "soundingPitchOffset": None}
                log.append(f"{new_id} : touches identiques à « {lid} », profil documenté")
            else:
                closest = _closest_layout(bindings, itype, cat)
                lay = cat.layouts.get(closest or "")
                delta = _octave_delta(bindings, lay.bindings()) if lay is not None else None
                prof = {"schemaVersion": SCHEMA_VERSION, "layoutId": closest, "keyboardLayout": None,
                        "verificationStatus": STATUS_CUSTOM, "verifiedAt": None, "gameVersion": None,
                        "polyphony": None, "soundingPitchOffset": None,
                        "bindings": _str_bindings(bindings)}
                if delta:
                    log.append(f"{new_id} : mêmes positions que « {closest} » à {delta // 12:+d} octave(s) "
                               f"près ; les {len(bindings)} touches réglées ici sont conservées telles quelles "
                               f"(statut « personnalisé »)")
                else:
                    log.append(f"{new_id} : {len(bindings)} touches personnalisées conservées "
                               f"(statut « personnalisé »)")
        old = migrated.get(new_id)
        if old is not None:
            # deux anciens identifiants vers le meme type (luth + guitare) : on garde le plus renseigne
            if old.get("bindings") and not prof.get("bindings"):
                prof = old
            else:
                log.append(f"{new_id} : deux anciens profils fusionnés")
        migrated[new_id] = prof

    for t in cat.types:
        if t.id not in migrated:
            migrated[t.id] = default_profile(t)
            log.append(f"{t.id} : profil par défaut ajouté "
                       f"({'disposition ' + t.default_layout_id if t.default_layout_id else 'touches à configurer'})")
    migrated.update(unknown)
    cfg["instruments"] = migrated

    wanted = cfg.get("instrument")
    if isinstance(wanted, str):
        new_id = LEGACY_IDS.get(wanted, wanted)
        if new_id != wanted:
            log.append(f"instrument actif « {wanted} » devient « {new_id} »")
        cfg["instrument"] = new_id
    else:
        cfg["instrument"] = "piano"

    favs = cfg.get("instrument_favorites")
    if not isinstance(favs, list):
        favs = []
    clean_favs = []
    for f in favs:
        fid = LEGACY_IDS.get(str(f), str(f))
        if fid not in clean_favs:
            clean_favs.append(fid)
    cfg["instrument_favorites"] = clean_favs

    kb = cfg.get("keyboard_layout")
    if kb not in ("auto",) + KEYBOARD_LAYOUTS:
        cfg["keyboard_layout"] = "auto"
    return log


# ---------------------------------------------------------------- instrument resolu
class Instrument:
    """Un type d'instrument + le profil de l'utilisateur : ce que le lecteur manipule reellement.

    Un profil sans touche construit quand meme un objet valide (aucune note, `ready` faux) : un instrument
    inconnu n'herite jamais du profil du piano."""

    def __init__(self, itype, profile=None, layout=None):
        self.type = itype
        self.id = itype.id
        self.name = itype.label_fr
        self.label_en = itype.label_en
        self.aliases = list(itype.aliases)
        self.category = itype.category
        self.image = itype.image
        self.percussive = itype.percussive
        self.source_urls = list(itype.source_urls)
        self.variant_count = itype.variant_count
        self.image_source_url = itype.image_source_url
        self.catalog_item_ids = list(itype.catalog_item_ids)

        prof = profile or default_profile(itype)
        self.profile = prof
        self.layout = layout
        self.layout_id = prof.get("layoutId") or (layout.id if layout is not None else None)
        self.layout_label = layout.label if layout is not None else ""
        self.status = prof.get("verificationStatus") or STATUS_UNKNOWN
        self.verified_at = prof.get("verifiedAt")
        self.game_version = prof.get("gameVersion")
        self.polyphony = prof.get("polyphony")
        self.sounding_pitch_offset = prof.get("soundingPitchOffset")
        self.gm_program = int(itype.preview_program or 0)
        self.preview_program = self.gm_program

        custom = _int_bindings(prof.get("bindings"))
        self.custom = bool(custom)
        bindings = custom if custom else (layout.bindings() if layout is not None else {})
        # une position absente de SCANCODES ne peut pas etre envoyee au jeu : elle est ecartee et signalee
        self.unsendable = sorted(m for m, k in bindings.items() if k not in SCANCODES)
        self.bindings = {m: k for m, k in bindings.items() if k in SCANCODES}

        notes = sorted(self.bindings)
        self.lowest = notes[0] if notes else 60
        self.scale = [m - self.lowest for m in notes]
        self.keys = [self.bindings[m] for m in notes]
        self.offset_to_key = dict(zip(self.scale, self.keys))
        self.span = self.scale[-1] if self.scale else 0
        self.chromatic = bool(self.scale) and len(self.scale) == self.span + 1
        if layout is not None and not self.custom:
            self.auto = layout.auto_transpose
        else:
            self.auto = "octave" if self.chromatic else "key"

        self.ready, self.blocked_reason = self._readiness()
        self.fingerprint = self._fingerprint()

    # ---- etat
    def _readiness(self):
        if not self.bindings:
            return False, "Les touches de cet instrument restent à configurer."
        if self.status not in PLAYABLE_STATUSES:
            return False, "Les touches de cet instrument restent à configurer."
        if self.percussive and self.status == STATUS_DOCUMENTED:
            return False, ("Profil de percussion candidat : fais le test des frappes avant de jouer "
                           "(une correspondance MIDI documentée ne prouve pas ce que produit chaque frappe).")
        return True, ""

    def _fingerprint(self):
        payload = json.dumps([[m, self.bindings[m]] for m in sorted(self.bindings)], separators=(",", ":"))
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self.id}:{self.layout_id or '-'}:{digest}"

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def kind(self):
        return "chromatique" if self.chromatic else "diatonique"

    @property
    def available_notes(self):
        """Notes MIDI reellement disponibles, triees."""
        return sorted(self.bindings)

    @property
    def missing_notes(self):
        """Notes chromatiques absentes entre la plus grave et la plus aigue (alterations manquantes)."""
        if not self.bindings:
            return []
        return [m for m in range(self.lowest, self.lowest + self.span + 1) if m not in self.bindings]

    # ---- musique
    def snap(self, offset):
        """Demi-ton de gamme le plus proche (egalite : le plus bas), ou None sans aucune touche."""
        if not self.scale:
            return None
        if offset in self.offset_to_key:
            return offset
        return min(self.scale, key=lambda o: (abs(o - offset), o))

    def key_for(self, note):
        """Touche qui joue exactement la note MIDI `note` (sans transposition), ou None."""
        return self.bindings.get(int(note))

    # ---- affichage
    def note_entry(self, midi):
        m = int(midi)
        return {"midi": m, "solfege": solfege(m), "note": note_name(m), "key": self.bindings.get(m, "")}

    def note_rows(self):
        """Lignes d'affichage des notes, suivant les rangees de la disposition (12 par ligne si personnalise)."""
        notes = [self.note_entry(m) for m in self.available_notes]
        if self.layout is not None and not self.custom and len(notes) == len(self.layout.notes):
            return _split_rows(notes, self.layout.rows)
        return _split_rows(notes, [12] * (len(notes) // 12 + 1)) if notes else []

    def to_dict(self):
        """Etat leger renvoye a chaque tick (19 fois) : pas de table de notes ici."""
        return {"id": self.id, "name": self.name, "label_en": self.label_en, "category": self.category,
                "image": self.image, "kind": self.kind, "keys": list(self.keys), "count": len(self.keys),
                "layout_id": self.layout_id, "layout_label": self.layout_label, "status": self.status,
                "ready": self.ready, "percussive": self.percussive, "custom": self.custom,
                "blocked_reason": self.blocked_reason, "lowest": self.lowest, "span": self.span,
                "aliases": list(self.aliases), "variant_count": self.variant_count}

    def __repr__(self):  # pragma: no cover - confort de debogage
        return f"<Instrument {self.id} {len(self.keys)} touches {self.status}>"


def build_instruments(cfg, res_dir=None):
    """Les instruments resolus, dans l'ordre du catalogue (les 19 types, prets ou non)."""
    cat = load_catalogue(res_dir)
    out = []
    for t in cat.types:
        prof = profile_of(cfg, t.id, cat)
        layout = cat.layouts.get(prof.get("layoutId") or "")
        out.append(Instrument(t, prof, layout))
    return out


def find_instrument(instruments, instrument_id):
    """Instrument d'identifiant donne dans une liste deja construite, ou None."""
    for inst in instruments:
        if inst.id == instrument_id:
            return inst
    return None


# ---------------------------------------------------------------- conflits de touches
def _hotkey_parts(cfg):
    """{position de touche : nom du raccourci} pour les raccourcis globaux d'une seule touche."""
    out = {}
    for name, combo in (cfg.get("hotkeys") or {}).items():
        for part in str(combo or "").lower().replace(" ", "").split("+"):
            if len(part) == 1:
                out.setdefault(part, name)
    return out


# Raccourcis qu'un mapping ne peut jamais prendre : l'arret et la lecture restent accessibles.
PROTECTED_HOTKEYS = ("stop", "play_pause")


def conflicts(bindings, cfg):
    """Problemes d'une table de touches en cours d'edition, prets a afficher a cote de la ligne.

    Chaque element : {"kind", "midi", "key", "message", "severity"}. severity "error" = sauvegarde refusee."""
    b = _int_bindings(bindings)
    out = []
    hotkeys = _hotkey_parts(cfg)
    kb = resolve_keyboard_layout(cfg.get("keyboard_layout", "auto"))
    vk = str(cfg.get("input_mode", "scancode")).lower() == "vk"
    seen = {}
    for midi in sorted(b):
        key = b[midi]
        if key in seen:
            out.append({"kind": "duplicate", "midi": midi, "key": key, "severity": "error",
                        "message": f"La touche {key_label(key, kb)} joue déjà {solfege(seen[key])} : "
                                   f"une position ne peut pas porter deux notes."})
        else:
            seen[key] = midi
        if key not in SCANCODES:
            out.append({"kind": "not-injectable", "midi": midi, "key": key, "severity": "error",
                        "message": "Cette touche ne peut pas être envoyée au jeu."})
        name = hotkeys.get(key)
        if name:
            protected = name in PROTECTED_HOTKEYS
            out.append({"kind": "hotkey", "midi": midi, "key": key,
                        "severity": "error" if protected else "warn",
                        "message": (f"La touche {key_label(key, kb)} est le raccourci « {name} » : "
                                    + ("choisis une autre touche, l'arrêt doit rester accessible."
                                       if protected else "le raccourci ne fonctionnera plus pendant la lecture."))})
        if vk and key_needs_shift(key, kb):
            out.append({"kind": "shift", "midi": midi, "key": key, "severity": "warn",
                        "message": (f"En AZERTY, {key_label(key, kb)} demande Maj pour produire « {key} » : "
                                    "le mode d'entrée « code virtuel » peut envoyer le mauvais caractère.")})
    return out


def blocking(items):
    """Vrai si la liste de conflits interdit la sauvegarde."""
    return any(c.get("severity") == "error" for c in items or [])
