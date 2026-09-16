"""Aide : FAQ complète, dépannage (SmartScreen, touches non reçues, jeu au premier plan, AZERTY), contact."""
from __future__ import annotations

from .. import site
from ..i18n import t, t_items
from ..site import EDITEUR_COURRIEL, esc, url_for
from ._shared import disclaimer, faq_block


def render(settings, lang: str, ctx) -> str:
    faq = t_items(lang, "site.help.faq")
    trouble = t_items(lang, "site.help.trouble")
    ctx.head.append(site.ld_script(site.faq_ld(faq + trouble)))
    return f"""<section class="section"><div class="wrap">
  <h1>{t(lang, "site.help.h1")}</h1>
  <p class="lead">{t(lang, "site.help.lead")}</p>
  <nav class="family-nav" aria-label="{esc(t(lang, "site.help.sections_label"))}">
    <a href="#questions">{esc(t(lang, "site.help.faq_title"))}</a>
    <a href="#depannage">{esc(t(lang, "site.help.trouble_title"))}</a>
    <a href="#contact">{esc(t(lang, "site.help.contact_title"))}</a>
  </nav>
</div></section>

<section class="section" id="questions"><div class="wrap">
  <h2>{esc(t(lang, "site.help.faq_title"))}</h2>
  {faq_block(faq)}
</div></section>

<section class="section" id="depannage"><div class="wrap">
  <h2>{esc(t(lang, "site.help.trouble_title"))}</h2>
  <p class="lead">{t(lang, "site.help.trouble_lead")}</p>
  {faq_block(trouble)}
</div></section>

<section class="section" id="contact"><div class="wrap">
  <h2>{esc(t(lang, "site.help.contact_title"))}</h2>
  <p>{t(lang, "site.help.contact_text", email=EDITEUR_COURRIEL)}</p>
  <p>{t(lang, "site.help.logs_text")}</p>
  <p><a href="{url_for(lang, "community")}">{esc(t(lang, "site.help.community_link"))}</a></p>
</div></section>

{disclaimer(lang)}"""
