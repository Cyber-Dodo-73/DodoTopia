"""Nouveautés : journal des versions publiées (notes de `releases.notes`, vingt dernières)."""
from __future__ import annotations

from ..i18n import t
from ..site import esc, human_date, notes_html, page_header
from ._shared import download_button


def render(settings, lang: str, ctx) -> str:
    items = []
    for i, rel in enumerate(ctx.releases):
        body = notes_html(rel.get("notes")) or f'<p class="dl-note">{esc(t(lang, "site.news.no_notes"))}</p>'
        date = human_date(rel.get("published_at"), lang)
        meta = f'<time datetime="{esc((rel.get("published_at") or "")[:10])}">{esc(date)}</time>' if date else ""
        badge = f' <span class="pill pill--candidate">{esc(t(lang, "site.news.mandatory"))}</span>' if rel.get("mandatory") else ""
        latest = f' <span class="pill pill--documented">{esc(t(lang, "site.news.latest"))}</span>' if i == 0 else ""
        # Frise : pas de <div> dans l'article (les notes suivent directement le titre et la date).
        items.append(f"""<li class="timeline__item"><span class="timeline__v" aria-hidden="true">{esc(rel["version"])}</span>
    <article class="newsitem" id="v{esc(rel["version"]).replace(".", "-")}">
      <h2>{esc(t(lang, "site.news.version", version=rel["version"]))}{latest}{badge}</h2>
      <p class="newsitem__date">{meta}</p>
      {body}
    </article></li>""")
    if items:
        listing = f'<ol class="timeline">{"".join(items)}</ol>'
        cta = f'<div class="actions">{download_button(lang, ctx.latest, "btn btn--cta")}</div>'
    else:
        listing = f'<div class="soon"><h2>{esc(t(lang, "site.news.empty_title"))}</h2><p>{t(lang, "site.news.empty_text")}</p></div>'
        cta = ""
    return f"""{page_header(lang, esc(t(lang, "site.news.eyebrow")), t(lang, "site.news.h1"), t(lang, "site.news.lead"), cta)}
<section class="section section--first"><div class="wrap wrap--narrow">
  {listing}
</div></section>
"""
