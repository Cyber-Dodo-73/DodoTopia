"""Morceaux de la bibliothèque partagée : liste publique (recherche, tag, tri, pagination) et fiche d'un morceau
(`/{lang}/<songs>/{id}-{slug}`), avec lien profond `dodotopia://song/{id}`, JSON-LD `MusicComposition` et image de
partage générée (`/og/song/{id}.png`)."""
from __future__ import annotations

import math

from .. import db, library
from ..i18n import LANGS, t
from ..schemas import SONG_TAGS, clean_text
from ..site import esc, human_date, ld_script, url_for
from ._listing import app_buttons, duration, page_int, pager, plain, shorten, slugify
from ._shared import cta_band

PER_PAGE = 30
LIST_SORTS = ("recent", "trending", "popular", "likes", "title")


def normalize_query(params) -> dict:
    """Paramètres d'URL reconnus et valides seulement (clé de cache bornée, rien d'autre n'atteint la base)."""
    out: dict = {}
    q = clean_text(params.get("q", ""), 100)
    if q:
        out["q"] = q
    tag = (params.get("tag") or "").strip().lower()
    if tag in SONG_TAGS:
        out["tag"] = tag
    sort = (params.get("sort") or "").strip().lower()
    if sort in LIST_SORTS and sort != "recent":
        out["sort"] = sort
    page = page_int(params.get("page"), 1)
    if page > 1:
        out["page"] = page
    return out


def song_slug(title: str) -> str:
    return slugify(title, "song")


def song_url(lang: str, song_id: int, title: str) -> str:
    return f"{url_for(lang, 'songs')}/{int(song_id)}-{song_slug(title)}"


def fetch_public_song(settings, song_id: int) -> db.Row | None:
    conn = db.connect(settings)
    try:
        row = conn.execute(f"{library.SONG_SELECT} WHERE s.id=?", (song_id,)).fetchone()
    finally:
        conn.close()
    return row if row is not None and row["status"] == "approved" else None


def tag_pills(lang: str, tags: list[str], link: bool = True) -> str:
    if not tags:
        return ""
    base = url_for(lang, "songs")
    items = "".join(
        (f'<li><a class="tag" href="{base}?tag={esc(tag)}">{esc(t(lang, f"site.tags.{tag}"))}</a></li>' if link
         else f'<li><span class="tag">{esc(t(lang, f"site.tags.{tag}"))}</span></li>') for tag in tags)
    return f'<ul class="tags">{items}</ul>'


def _meta_line(lang: str, row) -> str:
    parts = []
    if row["artist"]:
        parts.append(esc(row["artist"]))
    parts.append(esc(duration(row["duration_s"])))
    parts.append(t(lang, "site.songs.notes_n", n=row["note_count"]))
    parts.append(t(lang, "site.songs.likes_n", n=row["likes"] or 0))
    parts.append(t(lang, "site.songs.downloads_n", n=row["downloads"] or 0))
    return " · ".join(parts)


def _filters(lang: str, query: dict) -> str:
    tag_opts = "".join(f'<option value="{tag}"{" selected" if query.get("tag") == tag else ""}>'
                       f'{esc(t(lang, f"site.tags.{tag}"))}</option>' for tag in SONG_TAGS)
    sort_now = query.get("sort", "recent")
    sort_opts = "".join(f'<option value="{s}"{" selected" if sort_now == s else ""}>'
                        f'{esc(t(lang, f"site.songs.sort.{s}"))}</option>' for s in LIST_SORTS)
    return f"""<form class="filters" method="get" action="{url_for(lang, 'songs')}" role="search">
    <label class="filters__field filters__field--grow"><span>{esc(t(lang, "site.songs.search_label"))}</span>
      <input type="search" name="q" value="{esc(query.get("q", ""))}" maxlength="100"
             placeholder="{esc(t(lang, "site.songs.search_placeholder"))}"></label>
    <label class="filters__field"><span>{esc(t(lang, "site.songs.tag_label"))}</span>
      <select name="tag"><option value="">{esc(t(lang, "site.songs.tag_all"))}</option>{tag_opts}</select></label>
    <label class="filters__field"><span>{esc(t(lang, "site.listing.sort_label"))}</span>
      <select name="sort">{sort_opts}</select></label>
    <button class="btn btn--quiet" type="submit">{esc(t(lang, "site.songs.search_button"))}</button>
  </form>"""


def render(settings, lang: str, ctx) -> str:
    query = ctx.query
    if query:
        ctx.robots = "noindex, follow"          # variantes filtrées : la liste de base est la page canonique
    page = query.get("page", 1)
    conn = db.connect(settings)
    try:
        rows, total = library.query_songs(conn, query.get("q", ""), query.get("tag", ""), "",
                                          query.get("sort", "recent"), page, PER_PAGE)
    finally:
        conn.close()
    pages = max(1, math.ceil(total / PER_PAGE))
    if rows:
        items = "".join(
            f'<li class="songitem"><h2 class="songitem__title"><a href="{esc(song_url(lang, r["id"], r["title"]))}">'
            f'{esc(r["title"])}</a></h2><p class="songitem__meta">{_meta_line(lang, r)}</p>'
            f'{tag_pills(lang, library.load_tags(r["tags"]))}</li>' for r in rows)
        listing = (f'<p class="dl-note" role="status">{t(lang, "site.songs.results_n", n=total)}</p>'
                   f'<ul class="songlist">{items}</ul>{pager(lang, "songs", query, page, pages)}')
    else:
        key = "site.songs.no_match" if query else "site.songs.empty"
        listing = f'<div class="soon"><h2>{esc(t(lang, key + "_title"))}</h2><p>{t(lang, key + "_text")}</p></div>'
    return f"""<section class="section"><div class="wrap">
  <h1>{t(lang, "site.songs.h1")}</h1>
  <p class="lead">{t(lang, "site.songs.lead")}</p>
  {_filters(lang, query)}
  {listing}
</div></section>
{cta_band(lang, t(lang, "site.songs.cta_title"), t(lang, "site.songs.cta_text"), ctx.latest)}"""


def _composition_ld(settings, lang: str, row, url: str, tags: list[str]) -> dict:
    data = {"@context": "https://schema.org", "@type": "MusicComposition", "name": row["title"], "url": url,
            "inLanguage": lang, "datePublished": (row["created_at"] or "")[:10],
            "image": f"{settings.public_url}/og/song/{int(row['id'])}.png",
            "interactionStatistic": [
                {"@type": "InteractionCounter", "interactionType": "https://schema.org/DownloadAction",
                 "userInteractionCount": int(row["downloads"] or 0)},
                {"@type": "InteractionCounter", "interactionType": "https://schema.org/LikeAction",
                 "userInteractionCount": int(row["likes"] or 0)}]}
    if row["artist"]:
        data["composer"] = {"@type": "Person", "name": row["artist"]}
    if tags:
        data["keywords"] = ", ".join(plain(lang, f"site.tags.{tag}") for tag in tags)
    if row["source_url"]:
        data["isBasedOn"] = row["source_url"]
    return data


def render_detail(settings, lang: str, ctx, row) -> str:
    sid = int(row["id"])
    title = row["title"]
    tags = library.load_tags(row["tags"])
    ctx.paths = {code: song_url(code, sid, title) for code in LANGS}
    url = f"{settings.public_url}{ctx.paths[lang]}"
    ctx.title = plain(lang, "site.songs.detail_title", title=shorten(title, 40))
    who = row["artist"] or plain(lang, "site.songs.artist_unknown")
    ctx.description = shorten(plain(lang, "site.songs.detail_description", title=shorten(title, 60),
                                    artist=shorten(who, 40), notes=row["note_count"],
                                    duration=duration(row["duration_s"])), 160)
    ctx.og = (f"{settings.public_url}/og/song/{sid}.png", 1200, 630, plain(lang, "site.songs.og_alt", title=title))
    ctx.crumb = (title, ctx.paths[lang])
    if int(row["note_count"] or 0) < settings.SONG_INDEX_MIN_NOTES:
        ctx.robots = "noindex, follow"
    ctx.head.append(ld_script(_composition_ld(settings, lang, row, url, tags)))

    rows = [(t(lang, "site.songs.uploaded_by"), esc(row["uploader_name"])),
            (t(lang, "site.songs.added_on"),
             f'<time datetime="{esc((row["created_at"] or "")[:10])}">{esc(human_date(row["created_at"], lang))}</time>'),
            (t(lang, "site.songs.duration"), esc(duration(row["duration_s"]))),
            (t(lang, "site.songs.notes"), esc(row["note_count"])),
            (t(lang, "site.songs.downloads"), esc(row["downloads"] or 0)),
            (t(lang, "site.songs.likes"), esc(row["likes"] or 0))]
    if row["instrument"]:
        rows.append((t(lang, "site.songs.instrument"), esc(_instrument_label(row["instrument"], lang))))
    if tags:
        rows.append((t(lang, "site.songs.tags"), tag_pills(lang, tags)))
    if row["source_url"]:
        name = row["source_name"] or row["source_url"]
        rows.append((t(lang, "site.songs.source"),
                     f'<a href="{esc(row["source_url"])}" rel="nofollow noopener ugc external">{esc(name)}</a>'))
    elif row["source_name"]:
        rows.append((t(lang, "site.songs.source"), esc(row["source_name"])))
    rows.append((t(lang, "site.songs.license"), esc(t(lang, f"site.songs.license_{row['license'] or 'unknown'}"))))
    meta = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    artist = f'<p class="lead">{esc(row["artist"])}</p>' if row["artist"] else ""
    return f"""<section class="section"><div class="wrap">
  <p class="backlink"><a href="{url_for(lang, "songs")}">{esc(t(lang, "site.songs.back"))}</a></p>
  <article class="detail">
    <p class="eyebrow">{esc(t(lang, "site.songs.eyebrow"))}</p>
    <h1>{esc(title)}</h1>
    {artist}
    {app_buttons(lang, f"dodotopia://song/{sid}", "site.songs.open_app", ctx.latest)}
    <dl class="dlmeta detail__meta">{meta}</dl>
    <p class="dl-note">{t(lang, "site.songs.rights_note")}</p>
  </article>
</div></section>
"""


def _instrument_label(inst_id: str, lang: str) -> str:
    from .instruments import instrument_catalogue, labels
    for inst in instrument_catalogue().get("types", []):
        if inst.get("id") == inst_id:
            return labels(inst, lang)[0]
    return inst_id


__all__ = ["render", "render_detail", "normalize_query", "song_url", "song_slug", "fetch_public_song"]
