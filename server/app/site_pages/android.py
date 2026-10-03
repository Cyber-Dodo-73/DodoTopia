"""Android : l'application mobile (musique seulement pour l'instant). Ce qu'elle fait, les trois étapes (autoriser,
calibrer, jouer), ce qui arrive plus tard, prérequis, confidentialité, pourquoi pas le Play Store, téléchargement.

Canal de publication à part des versions PC (`mobile_releases.py`, `ctx.mobile`) : sans APK publié, la page reste
servie, sans aucun lien de téléchargement."""
from __future__ import annotations

from .. import site
from ..i18n import t
from ..site import esc, human_date, page_header, url_for
from ._shared import bullet_list, disclaimer, faq_section, section_head, steps_block
from .download import android_button


def render(settings, lang: str, ctx) -> str:
    p = "site.android"
    mobile = ctx.mobile
    ctx.head.append(site.ld_script(site.android_ld(settings, lang, mobile)))
    install = (f'<a href="{url_for(lang, "download", "apk")}">{esc(t(lang, f"{p}.install_link"))}</a>')
    how = f'<a class="btn btn--quiet btn--lg" href="#etapes">{esc(t(lang, "site.common.how_it_works"))}</a>'
    if mobile:
        badges = f'<span class="vbadge">{t(lang, "site.download.version_line", version=mobile["version"])}</span>'
        date = human_date(mobile.get("published_at"), lang)
        if date:
            badges += f' <span class="vbadge vbadge--soft">{t(lang, "site.download.published_on", date=date)}</span>'
        actions = (f'<div class="dl-row">{android_button(lang, mobile)}{how}</div>'
                   f'<p class="vbadges">{badges}</p>')
        final = f'<div class="dl-row">{android_button(lang, mobile)}</div>'
    else:
        soon = (f'<a class="btn btn--quiet" href="{url_for(lang, "download", "android")}">'
                f'{esc(t(lang, "site.common.soon_cta"))}</a>')
        actions = f'<div class="dl-row">{soon}{how}</div>'
        final = f'<p>{t(lang, "site.download.android.soon")}</p>'
    faq = faq_section(lang, ctx, f"{p}.faq", esc(t(lang, "site.common.faq_title")))
    return f"""{page_header(lang, esc(t(lang, f"{p}.eyebrow")), t(lang, f"{p}.h1"), t(lang, f"{p}.lead"), actions)}
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
  <p class="dl-note center">{t(lang, f"{p}.step_note")} {install}</p>
</div></section>

<section class="section"><div class="wrap wrap--narrow">
  <div class="prose reveal">
    <h2>{esc(t(lang, f"{p}.later_title"))}</h2>
    <p>{t(lang, f"{p}.later_text")}</p>
    <h2>{esc(t(lang, f"{p}.privacy_title"))}</h2>
    <p>{t(lang, f"{p}.privacy_text")}</p>
    <h2>{esc(t(lang, f"{p}.store_title"))}</h2>
    <p>{t(lang, f"{p}.store_text")}</p>
  </div>
</div></section>

{faq}
<section class="section" id="telecharger"><div class="wrap wrap--narrow">
  <div class="needbox needbox--tint reveal">
    <h2>{esc(t(lang, f"{p}.get_title"))}</h2>
    {final}
    <p class="more">{install}</p>
  </div>
</div></section>

{disclaimer(lang)}"""
