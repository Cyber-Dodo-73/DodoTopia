"""Pages d'activité : Musique, Dessin, Cuisine, Jouer ensemble. Même structure, textes différents."""
from __future__ import annotations

from ..i18n import t
from ..site import app_figure, esc, url_for
from ._shared import bullet_list, cta_band, disclaimer, faq_section, steps_block


def _render(page_id: str, shot: str, settings, lang: str, ctx) -> str:
    p = f"site.activity.{page_id}"
    # « Jouer ensemble » n'a pas de capture dédiée : elle montre celle de la musique, avec sa description exacte.
    shot_keys = p if shot != "musique" or page_id == "music" else "site.activity.music"
    faq = faq_section(lang, ctx, f"{p}.faq", esc(t(lang, "site.common.faq_title")))
    return f"""<section class="section hero hero--page"><div class="wrap">
  <div class="hero__txt">
    <p class="eyebrow">{esc(t(lang, f"{p}.eyebrow"))}</p>
    <h1>{t(lang, f"{p}.h1")}</h1>
    <p class="lead">{t(lang, f"{p}.lead")}</p>
    <div class="dl-row">
      <a class="btn btn--cta" href="{url_for(lang, "download")}">{esc(t(lang, "site.common.download_cta"))}</a>
      <a class="btn btn--quiet" href="#etapes">{esc(t(lang, "site.common.how_it_works"))}</a>
    </div>
  </div>
  {app_figure(lang, shot, t(lang, f"{shot_keys}.shot_alt"), t(lang, f"{shot_keys}.shot_caption"), "shot shot--hero", eager=True)}
</div></section>

<section class="section"><div class="wrap">
  <div class="twocol">
    <div>
      <h2>{esc(t(lang, f"{p}.what_title"))}</h2>
      {t(lang, f"{p}.what_body")}
    </div>
    <aside class="needbox">
      <h2>{esc(t(lang, "site.common.need_title"))}</h2>
      {bullet_list(lang, f"{p}.need", "checklist")}
    </aside>
  </div>
</div></section>

<section class="section" id="etapes"><div class="wrap">
  <h2>{esc(t(lang, "site.common.how_it_works"))}</h2>
  {steps_block(lang, f"{p}.step")}
  <p class="dl-note">{t(lang, f"{p}.step_note")}</p>
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
