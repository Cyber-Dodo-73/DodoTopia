"""Accueil : promesse, preuve sociale, trois activités, comment ça marche, FAQ courte, communauté."""
from __future__ import annotations

from .. import site
from ..i18n import t, t_items
from ..site import app_figure, esc, url_for
from . import instruments
from ._shared import disclaimer, faq_block, steps_block


def hero_actions(lang: str, latest: dict | None) -> str:
    """Une action principale (télécharger) et une secondaire ; jamais de lien mort sans version publiée."""
    if not latest:
        return (f'<div class="dl-row"><a class="btn btn--quiet" href="{url_for(lang, "download")}">'
                f'{esc(t(lang, "site.common.soon_cta"))}</a>'
                f'<a class="btn btn--quiet" href="#comment-ca-marche">{esc(t(lang, "site.home.cta_how"))}</a></div>'
                f'<p class="dl-note">{t(lang, "site.home.soon_note")}</p>')
    win = (latest.get("assets") or {}).get("windows-setup")
    lin = (latest.get("assets") or {}).get("linux-x64")
    if win:
        main = (f'<a class="btn btn--cta" href="/telecharger/go/windows" data-platform="windows-setup">'
                f'<span class="btn__ico" aria-hidden="true">⬇</span><span class="btn__txt">'
                f'<span>{esc(t(lang, "site.download.windows.button"))}</span>'
                f'<span class="btn__sub">{esc(t(lang, "site.download.windows.kind"))} · '
                f'{esc(site.human_size(win["size"], lang))}</span></span></a>')
    elif lin:
        main = (f'<a class="btn btn--cta" href="/telecharger/go/linux" data-platform="linux-x64">'
                f'<span class="btn__ico" aria-hidden="true">⬇</span><span class="btn__txt">'
                f'<span>{esc(t(lang, "site.download.linux.button"))}</span>'
                f'<span class="btn__sub">{esc(t(lang, "site.download.linux.kind"))} · '
                f'{esc(site.human_size(lin["size"], lang))}</span></span></a>')
    else:
        main = f'<a class="btn btn--cta" href="{url_for(lang, "download")}">{esc(t(lang, "site.common.download_cta"))}</a>'
    return (f'<div class="dl-row">{main}'
            f'<a class="btn btn--quiet" href="#comment-ca-marche">{esc(t(lang, "site.home.cta_how"))}</a></div>'
            f'<p class="dl-note">{t(lang, "site.home.version_note", version=latest["version"])} · '
            f'<a href="{url_for(lang, "download")}">{esc(t(lang, "site.home.other_downloads"))}</a></p>')


def stats_section(lang: str, ctx) -> str:
    """Preuve sociale : compteurs de /api/stats, affichés seulement s'ils sont > 0 ; un petit script les
    rafraîchit côté navigateur (la page est en cache quelques minutes)."""
    stats = ctx.stats or {}
    entries = [("downloads_total", "site.home.stats_downloads"), ("songs_approved", "site.home.stats_songs"),
               ("users", "site.home.stats_users")]
    def card(key: str, label: str) -> str:
        n = int(stats.get(key) or 0)
        number = f"{n:,}".replace(",", " ")
        return (f'<li class="stat" data-stat="{key}"{"" if n > 0 else " hidden"}>'
                f'<span class="stat__n">{number}</span><span class="stat__l">{esc(t(lang, label))}</span></li>')

    cards = "".join(card(key, label) for key, label in entries)
    visible = any(int(stats.get(k) or 0) > 0 for k, _ in entries)
    script = f"""<script nonce="{ctx.nonce}">
(function(){{var s=document.getElementById('preuve');if(!s||!window.fetch)return;
fetch('/api/stats',{{headers:{{'Accept':'application/json'}}}}).then(function(r){{return r.ok?r.json():null}}).then(function(d){{
if(!d)return;var any=false;s.querySelectorAll('[data-stat]').forEach(function(li){{var v=+d[li.dataset.stat]||0;
if(v>0){{li.querySelector('.stat__n').textContent=v.toLocaleString('{esc(lang)}');li.hidden=false;any=true}}else{{li.hidden=true}}}});
s.hidden=!any}}).catch(function(){{}})}})();
</script>"""
    return (f'<section class="section section--tight" id="preuve"{"" if visible else " hidden"}><div class="wrap">'
            f'<h2 class="sr-only">{esc(t(lang, "site.home.stats_title"))}</h2>'
            f'<ul class="stats">{cards}</ul></div></section>\n{script}\n')


def activity_card(lang: str, page_id: str, shot: str) -> str:
    p = f"site.home.{page_id}"
    return f"""<article class="card">
      {app_figure(lang, shot, t(lang, f"{p}.shot_alt"), t(lang, f"{p}.shot_caption"))}
      <h3><a href="{url_for(lang, page_id)}">{esc(t(lang, f"site.nav.{page_id}"))}</a></h3>
      <p class="card__lead">{t(lang, f"{p}.lead")}</p>
      <p>{t(lang, f"{p}.text")}</p>
      <p class="card__need"><strong>{esc(t(lang, "site.common.need_label"))}</strong> {t(lang, f"{p}.need")}</p>
      <p class="card__more"><a href="{url_for(lang, page_id)}">{esc(t(lang, f"{p}.more"))}</a></p>
    </article>"""


def community_section(settings, lang: str) -> str:
    url = (settings.COMMUNITY_DISCORD_URL or "").strip()
    if not url.startswith("https://"):
        return ""
    return f"""<section class="section" id="communaute"><div class="wrap">
  <div class="ctaband ctaband--soft">
    <div><h2>{esc(t(lang, "site.home.community_title"))}</h2><p>{t(lang, "site.home.community_text")}</p></div>
    <div class="ctaband__btn"><a class="btn" href="{esc(url)}" rel="noopener">{esc(t(lang, "site.home.community_cta"))}</a>
      <p class="dl-note"><a href="{url_for(lang, "community")}">{esc(t(lang, "site.home.community_more"))}</a></p></div>
  </div>
</div></section>
"""


def render(settings, lang: str, ctx) -> str:
    latest = ctx.latest
    ctx.head.append(site.ld_script(site.software_ld(settings, lang, latest)))
    faq = t_items(lang, "site.help.faq")[:4]
    if faq:
        ctx.head.append(site.ld_script(site.faq_ld(faq)))
    return f"""<section class="section hero"><div class="wrap">
  <div class="hero__txt">
    <p class="eyebrow">{esc(t(lang, "site.home.eyebrow"))}</p>
    <h1>{t(lang, "site.home.h1")}</h1>
    <p class="lead">{t(lang, "site.home.lead")}</p>
    {hero_actions(lang, latest)}
  </div>
  {app_figure(lang, "musique", t(lang, "site.home.hero_shot_alt"), t(lang, "site.home.hero_shot_caption"), "shot shot--hero", eager=True)}
</div></section>

{stats_section(lang, ctx)}
<section class="section" id="activites"><div class="wrap">
  <h2>{esc(t(lang, "site.home.activities_title"))}</h2>
  <p class="lead">{t(lang, "site.home.activities_lead")}</p>
  <div class="cards">
    {activity_card(lang, "music", "musique")}
    {activity_card(lang, "draw", "dessin")}
    {activity_card(lang, "cook", "cuisine")}
  </div>
  <div class="notice notice--soft">
    <p><strong>{esc(t(lang, "site.nav.together"))}.</strong> {t(lang, "site.home.together_text")}
       <a href="{url_for(lang, "together")}">{esc(t(lang, "site.home.together_more"))}</a></p>
  </div>
</div></section>

{instruments.teaser(lang)}
<section class="section" id="comment-ca-marche"><div class="wrap">
  <h2>{esc(t(lang, "site.home.steps_title"))}</h2>
  {steps_block(lang, "site.home.step")}
  <p class="dl-note">{t(lang, "site.home.steps_note")}</p>
</div></section>

<section class="section" id="questions"><div class="wrap">
  <h2>{esc(t(lang, "site.home.faq_title"))}</h2>
  {faq_block(faq)}
  <p><a class="btn btn--quiet" href="{url_for(lang, "help")}">{esc(t(lang, "site.home.faq_more"))}</a></p>
</div></section>

{disclaimer(lang)}
{community_section(settings, lang)}"""
