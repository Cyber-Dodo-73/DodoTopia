"""Accueil : héros illustré, bandeau de confiance, preuve sociale (au-dessus de seuils), trois activités en pleine
largeur, jouer ensemble, comment ça marche, instruments, aperçus (morceaux, galerie), FAQ courte, appel final."""
from __future__ import annotations

import logging

from .. import site
from ..i18n import t, t_items
from ..site import app_figure, app_shot, decor, esc, url_for, window_frame
from . import gallery, instruments, songs
from ._shared import cta_band, disclaimer, faq_block, section_head, steps_block

log = logging.getLogger("dodo")

# Un compteur n'apparaît qu'à partir de son seuil : « 5 téléchargements, 2 membres » dessert le projet.
STAT_MIN = {"downloads_total": 100, "songs_approved": 50, "users": 25}
STAT_LABELS = (("downloads_total", "site.home.stats_downloads"), ("songs_approved", "site.home.stats_songs"),
               ("users", "site.home.stats_users"))
TRUST = ("free", "no_account", "langs", "platforms")
PREVIEW_N = 6


def hero_actions(lang: str, latest: dict | None) -> str:
    """Une action principale (télécharger) et une secondaire ; jamais de lien mort sans version publiée."""
    if not latest:
        return (f'<div class="dl-row"><a class="btn btn--quiet" href="{url_for(lang, "download")}">'
                f'{esc(t(lang, "site.common.soon_cta"))}</a>'
                f'<a class="btn btn--quiet" href="#comment-ca-marche">{esc(t(lang, "site.home.cta_how"))}</a></div>'
                f'<p class="dl-note">{t(lang, "site.home.soon_note")}</p>')
    win = (latest.get("assets") or {}).get("windows-setup")
    lin = (latest.get("assets") or {}).get("linux-x64")
    ico = '<span class="btn__ico" aria-hidden="true"></span>'
    if win:
        main = (f'<a class="btn btn--cta btn--lg" href="/telecharger/go/windows" data-platform="windows-setup">'
                f'{ico}<span class="btn__txt">'
                f'<span>{esc(t(lang, "site.download.windows.button"))}</span>'
                f'<span class="btn__sub">{esc(t(lang, "site.download.windows.kind"))} · '
                f'{esc(site.human_size(win["size"], lang))}</span></span></a>')
    elif lin:
        main = (f'<a class="btn btn--cta btn--lg" href="/telecharger/go/linux" data-platform="linux-x64">'
                f'{ico}<span class="btn__txt">'
                f'<span>{esc(t(lang, "site.download.linux.button"))}</span>'
                f'<span class="btn__sub">{esc(t(lang, "site.download.linux.kind"))} · '
                f'{esc(site.human_size(lin["size"], lang))}</span></span></a>')
    else:
        main = (f'<a class="btn btn--cta btn--lg" href="{url_for(lang, "download")}">{ico}'
                f'{esc(t(lang, "site.common.download_cta"))}</a>')
    return (f'<div class="dl-row">{main}'
            f'<a class="btn btn--quiet btn--lg" href="#comment-ca-marche">{esc(t(lang, "site.home.cta_how"))}</a></div>'
            f'<p class="dl-note"><span class="vbadge">{t(lang, "site.home.version_badge", version=latest["version"])}'
            f'</span> <a href="{url_for(lang, "download")}">{esc(t(lang, "site.home.other_downloads"))}</a></p>')


def hero(lang: str, latest: dict | None) -> str:
    shot = app_shot("musique", t(lang, "site.home.hero_shot_alt"), "shot", eager=True,
                    sizes="(max-width: 900px) 94vw, 760px")
    return f"""<section class="hero"><span class="sky" aria-hidden="true">{decor("cloud cloud--a", "cloud cloud--b", "cloud cloud--c")}</span>
<div class="wrap hero__grid">
  <div class="hero__txt">
    <p class="eyebrow">{esc(t(lang, "site.home.eyebrow"))}</p>
    <h1>{t(lang, "site.home.h1")}</h1>
    <p class="lead">{t(lang, "site.home.lead")}</p>
    {hero_actions(lang, latest)}
  </div>
  <div class="hero__visual">
    {window_frame(shot, "r")}
    {site.dodo(lang, 200, "dodo--hero")}
    {decor("fx fx--n1", "fx fx--n2", "fx fx--n3", "fx fx--s1", "fx fx--s2")}
  </div>
</div><span class="hills" aria-hidden="true"></span></section>
"""


def trust_band(lang: str) -> str:
    items = "".join(f'<li class="trust__item trust__item--{key}"><span class="trust__ico" aria-hidden="true"></span>'
                    f'{esc(t(lang, f"site.home.trust.{key}"))}</li>' for key in TRUST)
    return f'<section class="trustband"><div class="wrap"><ul class="trust">{items}</ul></div></section>\n'


def stats_section(lang: str, ctx) -> str:
    """Preuve sociale : compteurs de /api/stats, chacun affiché seulement à partir de son seuil (`STAT_MIN`, repris
    dans `data-min`) ; un petit script les rafraîchit côté navigateur avec la même règle (la page est en cache
    quelques minutes). Sans aucun compteur au-dessus de son seuil, la section reste `hidden`."""
    stats = ctx.stats or {}

    def shown(key: str) -> bool:
        return int(stats.get(key) or 0) >= STAT_MIN[key]

    def card(key: str, label: str) -> str:
        n = int(stats.get(key) or 0)
        number = f"{n:,}".replace(",", " ")
        return (f'<li class="stat" data-stat="{key}" data-min="{STAT_MIN[key]}"{"" if shown(key) else " hidden"}>'
                f'<span class="stat__n">{number}</span><span class="stat__l">{esc(t(lang, label))}</span></li>')

    cards = "".join(card(key, label) for key, label in STAT_LABELS)
    visible = any(shown(key) for key, _ in STAT_LABELS)
    script = f"""<script nonce="{ctx.nonce}">
(function(){{var s=document.getElementById('preuve');if(!s||!window.fetch)return;
fetch('/api/stats',{{headers:{{'Accept':'application/json'}}}}).then(function(r){{return r.ok?r.json():null}}).then(function(d){{
if(!d)return;var any=false;s.querySelectorAll('[data-stat]').forEach(function(li){{var v=+d[li.dataset.stat]||0,m=+li.dataset.min||1;
if(v>=m){{li.querySelector('.stat__n').textContent=v.toLocaleString('{esc(lang)}');li.hidden=false;any=true}}else{{li.hidden=true}}}});
s.hidden=!any}}).catch(function(){{}})}})();
</script>"""
    return (f'<section class="statsband" id="preuve"{"" if visible else " hidden"}><div class="wrap">'
            f'<h2 class="sr-only">{esc(t(lang, "site.home.stats_title"))}</h2>'
            f'<ul class="stats">{cards}</ul></div></section>\n{script}\n')


def activity_section(lang: str, page_id: str, shot: str, flip: bool) -> str:
    p = f"site.home.{page_id}"
    classes = f"act theme-{site.theme_of(page_id)} wavy" + (" act--flip wavy--2" if flip else "")
    figure = app_figure(lang, shot, t(lang, f"{p}.shot_alt"), t(lang, f"{p}.shot_caption"),
                        tilt="l" if flip else "r", sizes="(max-width: 900px) 94vw, 58vw")
    return f"""<section class="{classes}"><span class="sky" aria-hidden="true">{decor("motif motif--a", "motif motif--b", "motif motif--c")}</span>
<div class="wrap wrap--wide act__grid">
  <div class="act__txt reveal">
    <span class="act__badge" aria-hidden="true"></span>
    <h3><a href="{url_for(lang, page_id)}">{esc(t(lang, f"site.nav.{page_id}"))}</a></h3>
    <p class="act__lead">{t(lang, f"{p}.lead")}</p>
    <p>{t(lang, f"{p}.text")}</p>
    <p class="act__need"><strong>{esc(t(lang, "site.common.need_label"))}</strong> {t(lang, f"{p}.need")}</p>
    <p class="more"><a href="{url_for(lang, page_id)}">{esc(t(lang, f"{p}.more"))}</a></p>
  </div>
  <div class="act__visual reveal">{figure}</div>
</div></section>
"""


def together_band(lang: str) -> str:
    return f"""<section class="roomsband theme-rooms wavy"><span class="sky" aria-hidden="true">{decor("motif motif--a", "motif motif--b")}</span>
<div class="wrap roomsband__grid reveal">
  <span class="act__badge" aria-hidden="true"></span>
  <div class="roomsband__txt">
    <h3>{esc(t(lang, "site.nav.together"))}</h3>
    <p>{t(lang, "site.home.together_text")}</p>
  </div>
  <p class="more"><a class="btn btn--quiet" href="{url_for(lang, "together")}">{esc(t(lang, "site.home.together_more"))}</a></p>
</div></section>
"""


def preview_section(lang: str, theme: str, section_id: str, key: str, page_id: str, cards: str) -> str:
    """Aperçu des derniers morceaux / dessins ; rien si la bibliothèque est encore trop petite (`cards` vide)."""
    if not cards:
        return ""
    return f"""<section class="section preview wavy plain theme-{theme}" id="{section_id}"><div class="wrap">
  {section_head(esc(t(lang, f"site.home.{key}_title")), t(lang, f"site.home.{key}_lead"))}
  {cards}
  <p class="center"><a class="btn btn--quiet" href="{url_for(lang, page_id)}">{esc(t(lang, f"site.home.{key}_more"))}</a></p>
</div></section>
"""


def _recent(module, settings, lang: str) -> str:
    try:
        return module.recent_cards(settings, lang, PREVIEW_N)
    except Exception:               # noqa - base indisponible : l'accueil reste servi, sans l'aperçu
        log.exception("aperçu de l'accueil")
        return ""


def community_section(settings, lang: str) -> str:
    url = (settings.COMMUNITY_DISCORD_URL or "").strip()
    if not url.startswith("https://"):
        return ""
    return f"""<section class="section section--tight" id="communaute"><div class="wrap">
  <div class="ctaband theme-rooms reveal">
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
    return f"""{hero(lang, latest)}
<div class="band">
{trust_band(lang)}
{stats_section(lang, ctx)}
<section class="section section--intro" id="activites"><div class="wrap">
  {section_head(esc(t(lang, "site.home.activities_title")), t(lang, "site.home.activities_lead"))}
</div></section>
</div>
{activity_section(lang, "music", "musique", False)}
{activity_section(lang, "draw", "dessin", True)}
{activity_section(lang, "cook", "cuisine", False)}
{activity_section(lang, "creations", "creations", True)}
{together_band(lang)}
<section class="section wavy wavy--2 plain" id="comment-ca-marche"><div class="wrap">
  {section_head(esc(t(lang, "site.home.steps_title")))}
  {steps_block(lang, "site.home.step", ("install", "prepare", "play"))}
  <p class="dl-note center">{t(lang, "site.home.steps_note")}</p>
</div></section>

{instruments.teaser(lang)}
{preview_section(lang, "music", "morceaux", "songs", "songs", _recent(songs, settings, lang))}
{preview_section(lang, "draw", "galerie", "gallery", "gallery", _recent(gallery, settings, lang))}
<section class="section wavy wavy--2 plain" id="questions"><div class="wrap wrap--narrow">
  {section_head(esc(t(lang, "site.home.faq_title")))}
  {faq_block(faq)}
  <p class="center"><a class="btn btn--quiet" href="{url_for(lang, "help")}">{esc(t(lang, "site.home.faq_more"))}</a></p>
</div></section>

{disclaimer(lang)}
{cta_band(lang, esc(t(lang, "site.home.final_title")), t(lang, "site.home.final_text"), latest)}
{community_section(settings, lang)}"""
