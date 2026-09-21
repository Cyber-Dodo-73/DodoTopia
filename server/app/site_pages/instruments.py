"""Instruments : catalogue des types connus de l'application, avec l'état réel de chaque profil de touches.

Source de données : la MÊME que l'application, `assets/instruments/catalogue.json` (+ `layouts.json`).

Accès choisi : une COPIE BUILD-TIME sous `server/static/instruments/` (les deux JSON et une image PNG par type,
reprise de `ui/instruments/`). Raison : le conteneur ne contient que `server/app` et `server/static` (voir
`server/Dockerfile`), le dossier `assets/` du dépôt n'y est pas. La copie est donc la seule qui existe en
production, et c'est elle que le site sert aux navigateurs : aucun hotlink, tout vient de /static.

Anti-dérive : `server/tests/test_site.py` compare octet par octet la copie et les fichiers du dépôt. Hors
conteneur, si la copie manque, on retombe sur les fichiers du dépôt pour que le site reste affichable.

Mise à jour de la copie (depuis la racine du dépôt) :
    cp assets/instruments/catalogue.json assets/instruments/layouts.json server/static/instruments/
    cp ui/instruments/*.png server/static/instruments/
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

from ..i18n import t
from ..site import EDITEUR_COURRIEL, STATIC_DIR, esc, human_date, page_header, png_size, url_for

log = logging.getLogger("dodo")

INST_DIR = STATIC_DIR / "instruments"
REPO_ROOT = STATIC_DIR.parent.parent
REPO_INST_DIR = REPO_ROOT / "assets" / "instruments"
REPO_IMG_DIR = REPO_ROOT / "ui" / "instruments"

# Trois états seulement, et aucun ne vaut « vérifié » : la vérification se fait sur l'ordinateur du joueur, dans
# l'application. Ne jamais ajouter ici un état « confirmé » alimenté par le catalogue : il ne confirme rien.
STATE_ORDER = ("documented", "candidate", "unknown")

# Pastille de repli quand l'image d'un type manque : générique par famille, jamais l'icône d'un autre instrument.
FAMILY_FALLBACK = {"strings": "🎻", "winds": "🎶", "keys": "🎹", "percussion": "🥁"}

SAFE_IMAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.png$")
MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}

_CATALOGUE: dict | None = None


def state_label(lang: str, state: str) -> str:
    return t(lang, f"site.instruments.state.{state}.label")


def state_text(lang: str, state: str) -> str:
    return t(lang, f"site.instruments.state.{state}.text")


def _instrument_json(name: str) -> dict:
    """Copie servie d'abord (seule présente en production), fichier du dépôt en secours."""
    for base in (INST_DIR, REPO_INST_DIR):
        path = base / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(name)


def _state_of(inst: dict) -> str:
    if not inst.get("supportedLayoutIds") or inst.get("mappingStatus") in (None, "", "unknown"):
        return "unknown"
    return "candidate" if inst.get("percussive") else "documented"


def _describe_layout(layout: dict) -> dict:
    """Données d'affichage déduites des notes elles-mêmes (les libellés du JSON ne sont pas affichés)."""
    notes = layout.get("notes") or []
    midis = [n["midi"] for n in notes if isinstance(n.get("midi"), int)]
    count = layout.get("noteCount") or len(notes)
    rows = len(layout.get("rows") or []) or 1
    chromatic = len(midis) > 1 and all(b - a == 1 for a, b in zip(midis, midis[1:]))
    if chromatic:
        accidentals = "all"
    elif midis and {m % 12 for m in midis} <= MAJOR_SCALE:
        accidentals = "major"
    else:
        accidentals = "partial"
    return {"range": f"{notes[0].get('solfege', '')} → {notes[-1].get('solfege', '')}" if notes else "",
            "rows": rows, "chromatic": chromatic, "accidentals": accidentals, "count": count}


def _build_catalogue() -> dict:
    raw = _instrument_json("catalogue.json")
    layouts_raw = _instrument_json("layouts.json")
    layouts = {lay["layoutId"]: lay for lay in layouts_raw.get("layouts", [])}
    types = []
    used: dict[str, int] = {}
    for inst in raw.get("instruments", []):
        name = Path(str(inst.get("image") or "")).name
        image = None
        if SAFE_IMAGE_NAME.match(name) and (INST_DIR / name).is_file():
            size = png_size(INST_DIR / name) or (160, 160)
            image = {"url": f"/static/instruments/{quote(name)}", "w": size[0], "h": size[1]}
        layout = layouts.get(inst.get("defaultLayoutId") or "")
        for lid in inst.get("supportedLayoutIds") or []:
            used[lid] = used.get(lid, 0) + 1
        types.append({
            "id": inst["instrumentId"],
            "label_fr": inst.get("labelFr") or inst["instrumentId"],
            "label_en": inst.get("labelEn") or "",
            "category": inst.get("category") or "",
            "image": image,
            "state": _state_of(inst),
            "layout": _describe_layout(layout) if layout else None,
            "variant_count": int(inst.get("variantCount") or 1),
            "item_url": next((u for u in (inst.get("sourceUrls") or [])
                              if str(u).startswith("https://build-heartopia.com/items/")), ""),
        })
    ordered_layouts = [{"id": lay["layoutId"], "used_by": used.get(lay["layoutId"], 0), **_describe_layout(lay)}
                       for lay in layouts_raw.get("layouts", [])]
    sources: list[str] = []
    for url in list(raw.get("sourceUrls") or []) + [u for lay in layouts_raw.get("layouts", [])
                                                    for u in (lay.get("sourceUrls") or [])]:
        url = str(url)
        if url.startswith("https://") and url not in sources:
            sources.append(url)
    return {
        "types": types,
        "layouts": ordered_layouts,
        "counts": {state: sum(1 for x in types if x["state"] == state) for state in STATE_ORDER},
        "total": len(types),
        "categories": [c["id"] for c in raw.get("categories", [])],
        "retrieved_at": raw.get("retrievedAt") or "",
        "octave_convention": raw.get("octaveConvention") or "",
        "source_urls": sources,
    }


EMPTY_CATALOGUE = {"types": [], "layouts": [], "counts": dict.fromkeys(STATE_ORDER, 0), "total": 0,
                   "categories": [], "retrieved_at": "", "octave_convention": "", "source_urls": []}


def instrument_catalogue() -> dict:
    """Catalogue préparé, gardé en mémoire. Un fichier absent ou illisible ne doit pas tuer le site : catalogue
    vide (la section de l'accueil disparaît, la page le dit), nouvel essai au coup suivant."""
    global _CATALOGUE
    if _CATALOGUE is None:
        try:
            _CATALOGUE = _build_catalogue()
        except (OSError, ValueError, KeyError, TypeError):
            log.exception("catalogue d'instruments illisible")
            return dict(EMPTY_CATALOGUE)
    return _CATALOGUE


def labels(inst: dict, lang: str) -> tuple[str, str]:
    """(nom principal, nom secondaire) : français d'abord en fr, anglais d'abord ailleurs."""
    if lang == "fr":
        return inst["label_fr"], inst["label_en"]
    return inst["label_en"] or inst["label_fr"], inst["label_fr"]


def layout_summary(lang: str, lay: dict | None) -> str:
    if not lay:
        return t(lang, "site.instruments.summary_unknown")
    kind = t(lang, "site.instruments.chromatic" if lay["chromatic"] else "site.instruments.diatonic")
    return f"{t(lang, 'site.instruments.notes_n', n=lay['count'])} · {esc(lay['range'])} · {kind}"


def inst_media(inst: dict, lang: str = "fr") -> str:
    """Visuel d'un type : fichier local servi depuis /static, pastille de famille si l'image manque."""
    image = inst.get("image")
    name = labels(inst, lang)[0]
    if not image:
        emoji = FAMILY_FALLBACK.get(inst.get("category", ""), "🎵")
        return (f'<span class="inst__media inst__media--none" role="img"'
                f' aria-label="{esc(t(lang, "site.instruments.no_image", name=name))}">{emoji}</span>')
    alt = t(lang, "site.instruments.image_alt", name=name)
    return (f'<span class="inst__media"><img src="{esc(image["url"])}" width="{image["w"]}"'
            f' height="{image["h"]}" loading="lazy" decoding="async" alt="{alt}"></span>')


def state_pill(lang: str, state: str) -> str:
    """Pastille d'état : le texte porte l'information, la forme et la couleur ne font que l'appuyer."""
    return (f'<p class="pill pill--{state}"><span class="pill__dot" aria-hidden="true"></span>'
            f'{esc(state_label(lang, state))}</p>')


def inst_card(inst: dict, lang: str) -> str:
    main, second = labels(inst, lang)
    other = f' · <span class="inst__en">{esc(second)}</span>' if second and second != main else ""
    return f"""<li class="inst">
        {inst_media(inst, lang)}
        <h3>{esc(main)}</h3>
        <p class="inst__meta">{esc(t(lang, f"site.instruments.family.{inst['category']}"))}{other}</p>
        {state_pill(lang, inst['state'])}
        <p class="inst__sum">{layout_summary(lang, inst['layout'])}</p>
      </li>"""


RAIL = ("piano", "violin", "lute", "harp", "recorder", "ocarina", "saxophone", "cello", "conga", "xylophone",
        "lyre", "mbira")


def teaser(lang: str) -> str:
    """Section « Choisis ton instrument » de l'accueil : un rail défilant de douze vrais visuels (accrochage au
    défilement, utilisable au clavier) et un lien vers la liste complète."""
    from ._shared import section_head
    cat = instrument_catalogue()
    if not cat["types"]:
        return ""
    by_id = {x["id"]: x for x in cat["types"]}
    sample = [by_id[i] for i in RAIL if i in by_id]
    sample += [x for x in cat["types"] if x not in sample][:max(0, len(RAIL) - len(sample))]

    def card(x: dict) -> str:
        family = t(lang, "site.instruments.family." + x["category"])
        return (f'<li class="instrail__item">{inst_media(x, lang)}'
                f'<span class="instrail__name">{esc(labels(x, lang)[0])}</span>'
                f'<span class="instrail__fam">{esc(family)}</span></li>')

    cards = "".join(card(x) for x in sample)
    c = cat["counts"]
    return f"""<section class="section tinted wavy" id="choisir-instrument"><div class="wrap">
  {section_head(esc(t(lang, "site.instruments.teaser_title")), t(lang, "site.instruments.teaser_lead", total=cat["total"]))}
</div>
<div class="instrail reveal" tabindex="0" role="region" aria-label="{esc(t(lang, "site.instruments.rail_label"))}">
  <ul class="instrail__list">{cards}</ul>
</div>
<div class="wrap">
  <p class="dl-note center">{t(lang, "site.instruments.teaser_counts", total=cat["total"], documented=c["documented"],
        candidate=c["candidate"], unknown=c["unknown"])}</p>
  <p class="center"><a class="btn btn--quiet" href="{url_for(lang, "instruments")}">{esc(t(lang, "site.instruments.teaser_link"))}</a></p>
</div></section>
"""


def render(settings, lang: str, ctx) -> str:
    cat = instrument_catalogue()
    c = cat["counts"]
    total = cat["total"]
    if not cat["types"]:
        return f"""{page_header(lang, esc(t(lang, "site.instruments.eyebrow")), t(lang, "site.instruments.h1"), "")}
<section class="section section--first"><div class="wrap">
  <div class="notice"><p>{t(lang, "site.instruments.unavailable")}</p></div>
</div></section>
"""
    legend = "".join(
        f'<li class="statecard statecard--{state}">{state_pill(lang, state)}'
        f'<p class="statecard__n">{esc(t(lang, "site.instruments.types_of", n=c[state], total=total))}</p>'
        f'<p class="statecard__txt">{esc(state_text(lang, state))}</p></li>'
        for state in STATE_ORDER)

    groups = []
    for cat_id in cat["categories"]:
        items = [x for x in cat["types"] if x["category"] == cat_id]
        if not items:
            continue
        groups.append(f'<h2 id="famille-{esc(cat_id)}">{esc(t(lang, f"site.instruments.family.{cat_id}"))}'
                      f' <span class="h2count">{esc(t(lang, "site.instruments.types_n", n=len(items)))}</span></h2>'
                      f'<ul class="instgrid">{"".join(inst_card(x, lang) for x in items)}</ul>')
    family_nav = "".join(f'<a href="#famille-{esc(key)}">{esc(t(lang, f"site.instruments.family.{key}"))}</a>'
                         for key in cat["categories"] if any(x["category"] == key for x in cat["types"]))

    th = {k: esc(t(lang, f"site.instruments.th.{k}")) for k in ("layout", "notes", "range", "accidentals", "rows", "types")}
    rows = "".join(
        f'<tr><td data-label="{th["layout"]}"><strong>{layout_summary(lang, lay)}</strong><br>'
        f'<span class="mono">{esc(lay["id"])}</span></td>'
        f'<td data-label="{th["notes"]}">{esc(lay["count"])}</td>'
        f'<td data-label="{th["range"]}">{esc(lay["range"])}</td>'
        f'<td data-label="{th["accidentals"]}">{esc(t(lang, f"site.instruments.accidentals.{lay['accidentals']}"))}</td>'
        f'<td data-label="{th["rows"]}">{esc(t(lang, "site.instruments.rows_n", n=lay["rows"]))}</td>'
        f'<td data-label="{th["types"]}">{esc(t(lang, "site.instruments.types_of", n=lay["used_by"], total=total))}</td></tr>'
        for lay in cat["layouts"])

    sources = "".join(f'<li><a href="{esc(u)}" rel="nofollow noopener" target="_blank">{esc(u)}</a></li>'
                      for u in cat["source_urls"])
    per_type = "".join(
        f'<li><strong>{esc(labels(x, lang)[0])}</strong> — '
        + (f'<a href="{esc(x["item_url"])}" rel="nofollow noopener" target="_blank">'
           f'{esc(t(lang, "site.instruments.item_sheet"))}</a>' if x["item_url"] else esc(t(lang, "site.instruments.no_source")))
        + " · " + esc(t(lang, "site.instruments.variants_n", n=x["variant_count"]) if x["variant_count"] > 1
                      else t(lang, "site.instruments.single_entry"))
        + "</li>"
        for x in cat["types"])
    retrieved = human_date(cat["retrieved_at"], lang) or cat["retrieved_at"]

    nav = (f'<nav class="family-nav" aria-label="{esc(t(lang, "site.instruments.families_label"))}">'
           f'{family_nav}</nav>')
    header = page_header(lang, esc(t(lang, "site.instruments.eyebrow")), t(lang, "site.instruments.h1"),
                         t(lang, "site.instruments.lead", total=total), nav)
    return f"""{header}
<section class="section section--first"><div class="wrap">
  <div class="notice notice--soft">
    <p><strong>{t(lang, "site.instruments.notice_title")}</strong> {t(lang, "site.instruments.notice_text")}</p>
  </div>
  <ul class="states">{legend}</ul>
</div></section>

<section class="section"><div class="wrap">
  {"".join(groups)}
  <p class="dl-note">{t(lang, "site.instruments.one_card_note")}</p>
</div></section>

<section class="section"><div class="wrap">
  <h2>{esc(t(lang, "site.instruments.layouts_title"))}</h2>
  <p>{t(lang, "site.instruments.layouts_text")}</p>
  <div class="table-scroll">
  <table class="layouts">
    <thead><tr><th>{th["layout"]}</th><th>{th["notes"]}</th><th>{th["range"]}</th><th>{th["accidentals"]}</th>
      <th>{th["rows"]}</th><th>{th["types"]}</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
  <p class="dl-note">{t(lang, "site.instruments.layouts_note", convention=cat["octave_convention"])}</p>
</div></section>

<section class="section section--tight"><div class="wrap">
  <h2>{esc(t(lang, "site.instruments.sources_title"))}</h2>
  <p>{t(lang, "site.instruments.sources_text", date=retrieved)}</p>
  <ul>{sources}</ul>
  <details class="news">
    <summary>{esc(t(lang, "site.instruments.provenance_title"))}</summary>
    <div class="faq__body">
      <p>{t(lang, "site.instruments.provenance_text", email=EDITEUR_COURRIEL)}</p>
      <ul class="prov">{per_type}</ul>
    </div>
  </details>
</div></section>

<section class="section section--tight"><div class="wrap">
  <div class="notice">
    <p><strong>{t(lang, "site.instruments.whatnot_title")}</strong> {t(lang, "site.instruments.whatnot_text")}</p>
  </div>
</div></section>
"""
