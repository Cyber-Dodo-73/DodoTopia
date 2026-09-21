"""Pages d'activité : Musique, Dessin, Cuisine, Jouer ensemble. Même structure, textes différents."""
from __future__ import annotations

from ..i18n import t
from ..site import app_figure, esc, page_header
from ._shared import bullet_list, cta_band, disclaimer, download_button, faq_section, section_head, steps_block


def _render(page_id: str, shot: str, settings, lang: str, ctx) -> str:
    p = f"site.activity.{page_id}"
    # « Jouer ensemble » n'a pas de capture dédiée : elle montre celle de la musique, avec sa description exacte.
    shot_keys = p if shot != "musique" or page_id == "music" else "site.activity.music"
    faq = faq_section(lang, ctx, f"{p}.faq", esc(t(lang, "site.common.faq_title")))
    actions = (f'<div class="dl-row">{download_button(lang, ctx.latest)}'
               f'<a class="btn btn--quiet btn--lg" href="#etapes">{esc(t(lang, "site.common.how_it_works"))}</a></div>')
    art = app_figure(lang, shot, t(lang, f"{shot_keys}.shot_alt"), t(lang, f"{shot_keys}.shot_caption"), eager=True,
                     tilt="r", sizes="(max-width: 900px) 94vw, 640px")
    return f"""{page_header(lang, esc(t(lang, f"{p}.eyebrow")), t(lang, f"{p}.h1"), t(lang, f"{p}.lead"), actions, art)}
<section class="section section--first"><div class="wrap">
  <div class="twocol">
    <div class="prose reveal">
      <h2>{esc(t(lang, f"{p}.what_title"))}</h2>
      {t(lang, f"{p}.what_body")}
    </div>
    <aside class="needbox needbox--tint reveal">
      <h2>{esc(t(lang, "site.common.need_title"))}</h2>
      {bullet_list(lang, f"{p}.need", "checklist")}
    </aside>
  </div>
</div></section>

<section class="section tinted wavy" id="etapes"><div class="wrap">
  {section_head(esc(t(lang, "site.common.how_it_works")))}
  {steps_block(lang, f"{p}.step")}
  <p class="dl-note center">{t(lang, f"{p}.step_note")}</p>
</div></section>

{faq}
{cta_band(lang, esc(t(lang, "site.common.cta_title")), t(lang, "site.common.cta_text"), ctx.latest)}
{disclaimer(lang)}"""


class _Activity:
    def __init__(self, page_id: str, shot: str):
        self.page_id = page_id
        self.shot = shot

    def render(self, settings, lang: str, ctx) -> str:
        return _render(self.page_id, self.shot, settings, lang, ctx)


Music = _Activity("music", "musique")
Draw = _Activity("draw", "dessin")
Cook = _Activity("cook", "cuisine")
Together = _Activity("together", "musique")
