"""Galerie publique des dessins approuvés : grille paginée (récents / populaires) et fiche d'un dessin
(`/{lang}/<galerie>/{id}`) avec « Reproduire ce dessin dans DodoTopia » (`dodotopia://drawing/{id}`)."""
from __future__ import annotations

import math

from .. import db, gallery
from ..i18n import LANGS, t
from ..site import esc, human_date, ld_script, page_header, url_for
from ._listing import app_buttons, page_int, pager, plain, shorten
from ._shared import cta_band

PER_PAGE = 24
LIST_SORTS = ("recent", "popular")


def normalize_query(params) -> dict:
    out: dict = {}
    sort = (params.get("sort") or "").strip().lower()
    if sort in LIST_SORTS and sort != "recent":
        out["sort"] = sort
    page = page_int(params.get("page"), 1)
    if page > 1:
        out["page"] = page
    return out


def drawing_url(lang: str, drawing_id: int) -> str:
    return f"{url_for(lang, 'gallery')}/{int(drawing_id)}"


def fetch_public_drawing(settings, drawing_id: int) -> db.Row | None:
    conn = db.connect(settings)
    try:
        row = gallery.fetch_drawing_row(conn, drawing_id)
    finally:
        conn.close()
    return row if row is not None and row["status"] == "approved" else None


def draw_card(settings, lang: str, r, heading: str = "h2") -> str:
    tw, th = gallery.thumb_size(r["w"], r["h"], settings.DRAWING_THUMB_PX)
    href = esc(drawing_url(lang, r["id"]))
    likes = f' · {t(lang, "site.songs.likes_n", n=r["likes"])}' if r["likes"] else ""      # jamais « 0 j'aime »
    return (f'<li class="drawcard"><a class="drawcard__img" href="{href}">'
            f'<img src="/api/drawings/{int(r["id"])}/thumb.png" width="{tw}" height="{th}" loading="lazy" '
            f'decoding="async" alt="{esc(plain(lang, "site.gallery.image_alt", title=r["title"]))}"></a>'
            f'<{heading} class="drawcard__title"><a href="{href}">{esc(r["title"])}</a></{heading}>'
            f'<p class="drawcard__meta">{t(lang, "site.gallery.by", name=r["uploader_name"])}{likes}</p></li>')


def recent_cards(settings, lang: str, n: int = 6, minimum: int = 3) -> str:
    """Les `n` derniers dessins approuvés, en cartes (accueil). Chaîne vide sous `minimum` dessins."""
    conn = db.connect(settings)
    try:
        rows, _total = gallery.query_drawings(conn, "recent", 1, n)
    finally:
        conn.close()
    if len(rows) < minimum:
        return ""
    return f'<ul class="gallerygrid gallerygrid--preview reveal">{"".join(draw_card(settings, lang, r, "h3") for r in rows)}</ul>'


def render(settings, lang: str, ctx) -> str:
    query = ctx.query
    if query:
        ctx.robots = "noindex, follow"
    page = query.get("page", 1)
    conn = db.connect(settings)
    try:
        rows, total = gallery.query_drawings(conn, query.get("sort", "recent"), page, PER_PAGE)
    finally:
        conn.close()
    pages = max(1, math.ceil(total / PER_PAGE))
    sort_now = query.get("sort", "recent")
    sort_opts = "".join(f'<option value="{s}"{" selected" if sort_now == s else ""}>'
                        f'{esc(t(lang, f"site.gallery.sort.{s}"))}</option>' for s in LIST_SORTS)
    filters = f"""<form class="filters filters--compact" method="get" action="{url_for(lang, 'gallery')}">
    <label class="filters__field"><span>{esc(t(lang, "site.listing.sort_label"))}</span>
      <select name="sort">{sort_opts}</select></label>
    <button class="btn btn--quiet" type="submit">{esc(t(lang, "site.gallery.apply"))}</button>
  </form>"""
    if rows:
        cards = [draw_card(settings, lang, r) for r in rows]
        listing = (f'<p class="dl-note" role="status">{t(lang, "site.gallery.results_n", n=total)}</p>'
                   f'<ul class="gallerygrid">{"".join(cards)}</ul>{pager(lang, "gallery", query, page, pages)}')
    else:
        listing = (f'<div class="soon"><h2>{esc(t(lang, "site.gallery.empty_title"))}</h2>'
                   f'<p>{t(lang, "site.gallery.empty_text")}</p></div>')
    return f"""{page_header(lang, esc(t(lang, "site.gallery.eyebrow")), t(lang, "site.gallery.h1"), t(lang, "site.gallery.lead"))}
<section class="section section--first"><div class="wrap">
  {filters}
  {listing}
</div></section>
{cta_band(lang, t(lang, "site.gallery.cta_title"), t(lang, "site.gallery.cta_text"), ctx.latest)}"""


def render_detail(settings, lang: str, ctx, row) -> str:
    did = int(row["id"])
    title = row["title"]
    base = settings.public_url
    ctx.paths = {code: drawing_url(code, did) for code in LANGS}
    ctx.title = plain(lang, "site.gallery.detail_title", title=shorten(title, 40))
    ctx.description = shorten(plain(lang, "site.gallery.detail_description", title=shorten(title, 60),
                                    name=shorten(row["uploader_name"], 40), w=row["w"], h=row["h"]), 160)
    tw, th = gallery.thumb_size(row["w"], row["h"], settings.DRAWING_THUMB_PX)
    alt = plain(lang, "site.gallery.image_alt", title=title)
    ctx.og = (f"{base}/api/drawings/{did}/thumb.png", tw, th, alt)
    ctx.crumb = (title, ctx.paths[lang])
    ctx.head.append(ld_script({
        "@context": "https://schema.org", "@type": "VisualArtwork", "name": title,
        "url": f"{base}{ctx.paths[lang]}", "image": f"{base}/api/drawings/{did}.png",
        "thumbnailUrl": f"{base}/api/drawings/{did}/thumb.png", "artMedium": "Pixel art",
        "width": {"@type": "QuantitativeValue", "value": row["w"], "unitText": "px"},
        "height": {"@type": "QuantitativeValue", "value": row["h"], "unitText": "px"},
        "creator": {"@type": "Person", "name": row["uploader_name"]},
        "dateCreated": (row["created_at"] or "")[:10]}))
    meta = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in (
        (t(lang, "site.gallery.author"), esc(row["uploader_name"])),
        (t(lang, "site.songs.added_on"),
         f'<time datetime="{esc((row["created_at"] or "")[:10])}">{esc(human_date(row["created_at"], lang))}</time>'),
        (t(lang, "site.gallery.size"), esc(f'{row["w"]} × {row["h"]}')),
        *(((t(lang, "site.songs.likes"), esc(row["likes"])),) if row["likes"] else ()),
    ))
    replay = (app_buttons(lang, f"dodotopia://drawing/{did}", "site.gallery.open_app", ctx.latest)
              if row["has_cells"] else
              f'<p class="dl-note">{t(lang, "site.gallery.no_cells")}</p>')
    back = f'<p class="backlink"><a href="{url_for(lang, "gallery")}">{esc(t(lang, "site.gallery.back"))}</a></p>'
    header = page_header(lang, esc(t(lang, "site.gallery.eyebrow")), esc(title),
                         t(lang, "site.gallery.by", name=row["uploader_name"]), back=back, cls="pagehead--detail")
    return f"""{header}
<section class="section section--first"><div class="wrap">
  <article class="detail detail--drawing">
    <figure class="drawing"><img src="/api/drawings/{did}.png" width="{int(row["w"])}" height="{int(row["h"])}"
      decoding="async" alt="{esc(alt)}"></figure>
    {replay}
    <dl class="dlmeta detail__meta">{meta}</dl>
  </article>
</div></section>
"""
