"""Communauté : Discord (si configuré), règles, comment contribuer des morceaux MIDI."""
from __future__ import annotations

from ..i18n import t
from ..site import EDITEUR_COURRIEL, esc, page_header, url_for
from ._shared import bullet_list, disclaimer, section_head, steps_block


def render(settings, lang: str, ctx) -> str:
    url = (settings.COMMUNITY_DISCORD_URL or "").strip()
    if url.startswith("https://"):
        discord = f"""<div class="ctaband theme-rooms reveal">
    <div><h2>{esc(t(lang, "site.community.discord_title"))}</h2><p>{t(lang, "site.community.discord_text")}</p></div>
    <div class="ctaband__btn"><a class="btn" href="{esc(url)}" rel="noopener">{esc(t(lang, "site.community.discord_cta"))}</a></div>
  </div>"""
    else:
        discord = f"""<div class="notice notice--soft">
    <p><strong>{esc(t(lang, "site.community.discord_title"))}</strong> {t(lang, "site.community.discord_missing", email=EDITEUR_COURRIEL)}</p>
  </div>"""
    return f"""{page_header(lang, esc(t(lang, "site.community.eyebrow")), t(lang, "site.community.h1"), t(lang, "site.community.lead"))}
<section class="section section--first"><div class="wrap">
  {discord}
</div></section>

<section class="section"><div class="wrap">
  {section_head(esc(t(lang, "site.community.contribute_title")), t(lang, "site.community.contribute_intro"))}
  {steps_block(lang, "site.community.contribute")}
  <p class="dl-note center">{t(lang, "site.community.contribute_note")}</p>
</div></section>

<section class="section"><div class="wrap">
  <div class="twocol">
    <div class="needbox reveal">
      <h2>{esc(t(lang, "site.community.rules_title"))}</h2>
      {bullet_list(lang, "site.community.rule", "checklist")}
    </div>
    <div class="prose reveal">
      <h2>{esc(t(lang, "site.community.report_title"))}</h2>
      <p>{t(lang, "site.community.report_text", email=EDITEUR_COURRIEL)}</p>
      <h2>{esc(t(lang, "site.community.help_title"))}</h2>
      <p>{t(lang, "site.community.help_text")} <a href="{url_for(lang, "help")}">{esc(t(lang, "site.nav.help"))}</a>.</p>
    </div>
  </div>
</div></section>

{disclaimer(lang)}"""
