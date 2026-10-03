"""Téléchargement : l'installeur Windows en carte principale, portable et Linux en secondaires, détails techniques
(fichier, SHA-256, VirusTotal) repliés, la carte de l'appli Android (canal à part, `ctx.mobile`), notes de version,
puis prérequis et questions d'installation en accordéon (dont « Installer un APK », ancre `#apk`)."""
from __future__ import annotations

from .. import site
from ..i18n import t
from ..site import esc, human_date, human_size, page_header, url_for
from ._shared import bullet_list, disclaimer, section_head

# (identifiant d'asset, segment de /telecharger/go/, préfixe de clés, carte principale ?)
PLATFORMS = (("windows-setup", "windows", "site.download.windows", True),
             ("windows-portable", "portable", "site.download.portable", False),
             ("linux-x64", "linux", "site.download.linux", False))


def platform_card(lang: str, asset_id: str, go: str, prefix: str, primary: bool, latest: dict) -> str:
    asset = (latest.get("assets") or {}).get(asset_id)
    if not asset:
        return (f'<li class="dlcard dlcard--none"><h3>{esc(t(lang, f"{prefix}.title"))}</h3>'
                f'<p>{t(lang, f"{prefix}.missing")}</p></li>')
    sha = str(asset.get("sha256") or "")
    vt = (f'<a href="https://www.virustotal.com/gui/file/{esc(sha)}" rel="noopener nofollow" target="_blank">'
          f'{esc(t(lang, "site.download.virustotal"))}</a>') if len(sha) == 64 else ""
    btn_cls = "btn btn--cta btn--lg" if primary else "btn btn--quiet"
    ribbon = f'<p class="dlcard__ribbon">{esc(t(lang, "site.download.recommended"))}</p>' if primary else ""
    return f"""<li class="dlcard{' dlcard--primary' if primary else ''} dlcard--{go}">
      {ribbon}<span class="dlcard__ico" aria-hidden="true"></span>
      <h3>{esc(t(lang, f"{prefix}.title"))}</h3>
      <p class="dlcard__desc">{t(lang, f"{prefix}.desc")}</p>
      <p class="dlcard__go"><a class="{btn_cls}" href="/telecharger/go/{go}" data-platform="{asset_id}">
        <span class="btn__ico" aria-hidden="true"></span>
        <span class="btn__txt"><span>{esc(t(lang, f"{prefix}.button"))}</span>
          <span class="btn__sub">{esc(t(lang, f"{prefix}.kind"))} · {esc(human_size(asset["size"], lang))}</span></span></a></p>
      <details class="dlcard__tech"><summary>{esc(t(lang, "site.download.tech_details"))}</summary>
      <dl class="dlmeta">
        <dt>{esc(t(lang, "site.download.file"))}</dt><dd><code>{esc(asset["filename"])}</code></dd>
        <dt>SHA-256</dt><dd><code class="sha">{esc(sha)}</code></dd>
        <dt>{esc(t(lang, "site.download.check"))}</dt><dd>{vt}</dd>
      </dl></details>
    </li>"""


def android_button(lang: str, mobile: dict, cls: str = "btn btn--cta btn--lg") -> str:
    """Bouton de téléchargement de l'APK (lien compteur), avec son type et sa taille. Aussi sur la page Android."""
    return (f'<a class="{cls}" href="/telecharger/go/android" data-platform="android">'
            f'<span class="btn__ico" aria-hidden="true"></span>'
            f'<span class="btn__txt"><span>{esc(t(lang, "site.download.android.button"))}</span>'
            f'<span class="btn__sub">{esc(t(lang, "site.download.android.kind"))} · '
            f'{esc(human_size(mobile["size"], lang))}</span></span></a>')


def android_card(lang: str, mobile: dict | None) -> str:
    """Carte de l'appli Android, hors de la grille des versions PC : elle a sa propre version et existe même quand
    aucune version PC n'est publiée. Sans APK publié : état « bientôt », aucun lien de téléchargement."""
    title = esc(t(lang, "site.download.android.title"))
    more = (f'<p class="more"><a href="{url_for(lang, "android")}">'
            f'{esc(t(lang, "site.download.android.more"))}</a></p>')
    if not mobile:
        return (f'<div class="dlcard dlcard--none dlcard--android" id="android"><h3>{title}</h3>'
                f'<p>{t(lang, "site.download.android.soon")}</p>{more}</div>')
    sha = str(mobile.get("sha256") or "")
    vt = (f'<a href="https://www.virustotal.com/gui/file/{esc(sha)}" rel="noopener nofollow" target="_blank">'
          f'{esc(t(lang, "site.download.virustotal"))}</a>') if len(sha) == 64 else ""
    badges = f'<span class="vbadge">{t(lang, "site.download.version_line", version=mobile["version"])}</span>'
    date = human_date(mobile.get("published_at"), lang)
    if date:
        badges += f' <span class="vbadge vbadge--soft">{t(lang, "site.download.published_on", date=date)}</span>'
    return f"""<div class="dlcard dlcard--android reveal" id="android">
      <span class="dlcard__ico" aria-hidden="true"></span>
      <h3>{title}</h3>
      <p class="dlcard__desc">{t(lang, "site.download.android.desc")}</p>
      <p class="vbadges">{badges}</p>
      <p class="dlcard__go">{android_button(lang, mobile)}</p>
      <details class="dlcard__tech"><summary>{esc(t(lang, "site.download.tech_details"))}</summary>
      <dl class="dlmeta">
        <dt>{esc(t(lang, "site.download.file"))}</dt><dd><code>{esc(mobile["filename"])}</code></dd>
        <dt>SHA-256</dt><dd><code class="sha">{esc(sha)}</code></dd>
        <dt>{esc(t(lang, "site.download.check"))}</dt><dd>{vt}</dd>
      </dl></details>
      {more}
    </div>"""


NOTES_MAX_LINES = 12                # au-delà : lien « la suite » vers la page Nouveautés


def release_notes(lang: str, latest: dict) -> str:
    raw = latest.get("notes") or ""
    notes = site.notes_html(raw, max_items=NOTES_MAX_LINES)     # Markdown du CHANGELOG -> HTML sûr
    if not notes:
        return ""
    more_key = "site.download.notes_more" if site.notes_line_count(raw) > NOTES_MAX_LINES else "site.download.notes_all"
    more = f'<p class="more"><a href="{url_for(lang, "news")}">{esc(t(lang, more_key))}</a></p>'
    title = esc(t(lang, "site.download.notes_title", version=latest["version"]))
    return (f'<section class="section"><div class="wrap wrap--narrow">{section_head(title)}'
            f'<div class="newsitem">{notes}{more}</div></div></section>\n')


def more_section(lang: str) -> str:
    """Prérequis, mise à jour, portable ou non, SmartScreen, installation d'un APK : un accordéon (un seul volet
    ouvert à la fois). Les ancres `#smartscreen` et `#apk` sont DANS leur volet : un lien vers elles l'ouvre
    (révélation des <details> par l'ancre)."""
    def fold(summary: str, body: str, anchor: str = "", opened: bool = False) -> str:
        ident = f' id="{anchor}"' if anchor else ""
        return (f'<details name="dl-more"{" open" if opened else ""}><summary>{summary}</summary>'
                f'<div class="faq__body"{ident}>{body}</div></details>')

    folds = (
        fold(esc(t(lang, "site.download.minreq_title")), bullet_list(lang, "site.download.minreq", "checklist"),
             opened=True),
        fold(esc(t(lang, "site.download.installed_title")), f'<p>{t(lang, "site.download.installed_text")}</p>'),
        fold(esc(t(lang, "site.download.portable_title")), f'<p>{t(lang, "site.download.portable_text")}</p>'),
        fold(esc(t(lang, "site.download.smartscreen_title")),
             f'<p>{t(lang, "site.download.smartscreen_text")}</p><p>{t(lang, "site.download.smartscreen_steps")}</p>',
             anchor="smartscreen"),
        fold(esc(t(lang, "site.download.apk_title")),
             "".join(f'<p>{t(lang, f"site.download.apk_{part}")}</p>' for part in ("text", "access", "restricted")),
             anchor="apk"),
    )
    return f"""<section class="section"><div class="wrap wrap--narrow">
  {section_head(esc(t(lang, "site.download.more_title")))}
  <div class="faq">{"".join(folds)}</div>
</div></section>
"""


def render(settings, lang: str, ctx) -> str:
    latest = ctx.latest
    ctx.head.append(site.ld_script(site.software_ld(settings, lang, latest)))
    macos = f'<p class="pillnote"><span class="pillnote__ico" aria-hidden="true"></span>{t(lang, "site.download.macos_note")}</p>'
    if latest:
        date = human_date(latest.get("published_at"), lang)
        badges = f'<span class="vbadge">{t(lang, "site.download.version_line", version=latest["version"])}</span>'
        if date:
            badges += f' <span class="vbadge vbadge--soft">{t(lang, "site.download.published_on", date=date)}</span>'
        actions = f'<p class="vbadges">{badges}</p>'
        cards = "".join(platform_card(lang, *spec, latest) for spec in PLATFORMS)
        main = f"""<ul class="dlgrid reveal">{cards}</ul>
  <p class="dl-note center">{t(lang, "site.download.sha_note")}</p>"""
        notes = release_notes(lang, latest)
    else:
        actions = ""
        main = f"""<div class="soon">
    <h2>{esc(t(lang, "site.download.soon_title"))}</h2>
    <p>{t(lang, "site.download.soon_text")}</p>
  </div>"""
        notes = ""
    # « dlstack » : sur un écran tactile, la carte Android remonte devant les versions PC (site.css).
    main = f"""<div class="dlstack">{main}
  {android_card(lang, ctx.mobile)}</div>
  {macos}"""
    header = page_header(lang, esc(t(lang, "site.download.eyebrow")), t(lang, "site.download.h1"),
                         t(lang, "site.download.lead"), actions)
    return f"""{header}
<section class="section section--first section--pull"><div class="wrap">
  {main}
</div></section>

{notes}
{more_section(lang)}
{disclaimer(lang)}"""
