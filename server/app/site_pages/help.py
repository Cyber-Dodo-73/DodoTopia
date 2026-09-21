"""Aide : FAQ complète, dépannage (SmartScreen, touches non reçues, jeu au premier plan, AZERTY), contact."""
from __future__ import annotations

from .. import site
from ..i18n import t, t_items
from ..site import EDITEUR_COURRIEL, esc, page_header, url_for
from ._shared import disclaimer, faq_block, section_head


def render(settings, lang: str, ctx) -> str:
    faq = t_items(lang, "site.help.faq")
    trouble = t_items(lang, "site.help.trouble")
    ctx.head.append(site.ld_script(site.faq_ld(faq + trouble)))
    nav = f"""<nav class="family-nav" aria-label="{esc(t(lang, "site.help.sections_label"))}">
    <a href="#questions">{esc(t(lang, "site.help.faq_title"))}</a>
    <a href="#depannage">{esc(t(lang, "site.help.trouble_title"))}</a>
    <a href="#contact">{esc(t(lang, "site.help.contact_title"))}</a>
  </nav>"""
    return f"""{page_header(lang, esc(t(lang, "site.help.eyebrow")), t(lang, "site.help.h1"), t(lang, "site.help.lead"), nav)}
<section class="section section--first" id="questions"><div class="wrap wrap--narrow">
  {section_head(esc(t(lang, "site.help.faq_title")))}
  {faq_block(faq)}
</div></section>

<section class="section" id="depannage"><div class="wrap wrap--narrow">
  {section_head(esc(t(lang, "site.help.trouble_title")), t(lang, "site.help.trouble_lead"))}
  {faq_block(trouble)}
</div></section>

<section class="section" id="contact"><div class="wrap wrap--narrow">
  <div class="needbox needbox--tint theme-rooms reveal">
    <span class="contactbox__ico" aria-hidden="true"></span>
    <h2>{esc(t(lang, "site.help.contact_title"))}</h2>
    <p>{t(lang, "site.help.contact_text", email=EDITEUR_COURRIEL)}</p>
    <p>{t(lang, "site.help.logs_text")}</p>
    <p class="more"><a href="{url_for(lang, "community")}">{esc(t(lang, "site.help.community_link"))}</a></p>
  </div>
</div></section>

{disclaimer(lang)}"""
