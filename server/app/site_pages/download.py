"""Téléchargement : plateformes de la dernière version publiée, empreintes, VirusTotal, notes, prérequis."""
from __future__ import annotations

from .. import site
from ..i18n import t
from ..site import esc, human_date, human_size, url_for
from ._shared import bullet_list, disclaimer

# (identifiant d'asset, segment de /telecharger/go/, préfixe de clés, bouton principal ?)
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
    btn_cls = "btn btn--cta" if primary else "btn"
    return f"""<li class="dlcard">
      <h3>{esc(t(lang, f"{prefix}.title"))}</h3>
      <p class="dlcard__desc">{t(lang, f"{prefix}.desc")}</p>
      <p><a class="{btn_cls}" href="/telecharger/go/{go}" data-platform="{asset_id}">
        <span class="btn__ico" aria-hidden="true">⬇</span>
        <span class="btn__txt"><span>{esc(t(lang, f"{prefix}.button"))}</span>
          <span class="btn__sub">{esc(t(lang, f"{prefix}.kind"))} · {esc(human_size(asset["size"], lang))}</span></span></a></p>
      <dl class="dlmeta">
        <dt>{esc(t(lang, "site.download.file"))}</dt><dd><code>{esc(asset["filename"])}</code></dd>
        <dt>SHA-256</dt><dd><code class="sha">{esc(sha)}</code></dd>
        <dt>{esc(t(lang, "site.download.check"))}</dt><dd>{vt}</dd>
      </dl>
    </li>"""


def release_notes(lang: str, latest: dict) -> str:
    raw = (latest.get("notes") or "").strip()
    lines = [line.strip(" -•\t") for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    items = "".join(f"<li>{esc(line)}</li>" for line in lines[:12])
    more = (f'<p><a href="{url_for(lang, "news")}">{esc(t(lang, "site.download.notes_more"))}</a></p>'
            if len(lines) > 12 else f'<p><a href="{url_for(lang, "news")}">{esc(t(lang, "site.download.notes_all"))}</a></p>')
    return (f'<section class="section section--tight"><div class="wrap"><h2>'
            f'{esc(t(lang, "site.download.notes_title", version=latest["version"]))}</h2>'
            f'<div class="newsitem"><ul>{items}</ul>{more}</div></div></section>\n')


def render(settings, lang: str, ctx) -> str:
    latest = ctx.latest
    ctx.head.append(site.ld_script(site.software_ld(settings, lang, latest)))
    if latest:
        date = human_date(latest.get("published_at"), lang)
        line = t(lang, "site.download.version_line", version=latest["version"])
        if date:
            line += " · " + t(lang, "site.download.published_on", date=date)
        cards = "".join(platform_card(lang, *spec, latest) for spec in PLATFORMS)
        main = f"""<p class="dl-note dl-note--version">{line}</p>
  <ul class="dlgrid">{cards}</ul>
  <p class="dl-note">{t(lang, "site.download.sha_note")}</p>
  <p class="dl-note">{t(lang, "site.download.macos_note")}</p>"""
        notes = release_notes(lang, latest)
    else:
        main = f"""<div class="soon">
    <h2>{esc(t(lang, "site.download.soon_title"))}</h2>
    <p>{t(lang, "site.download.soon_text")}</p>
  </div>
  <p class="dl-note">{t(lang, "site.download.macos_note")}</p>"""
        notes = ""
    return f"""<section class="section"><div class="wrap">
  <h1>{t(lang, "site.download.h1")}</h1>
  <p class="lead">{t(lang, "site.download.lead")}</p>
  {main}
</div></section>

{notes}
<section class="section"><div class="wrap">
  <div class="twocol">
    <div>
      <h2>{esc(t(lang, "site.download.minreq_title"))}</h2>
      {bullet_list(lang, "site.download.minreq", "checklist")}
    </div>
    <div>
      <h2>{esc(t(lang, "site.download.installed_title"))}</h2>
      <p>{t(lang, "site.download.installed_text")}</p>
      <h2>{esc(t(lang, "site.download.portable_title"))}</h2>
      <p>{t(lang, "site.download.portable_text")}</p>
    </div>
  </div>
</div></section>

<section class="section section--tight" id="smartscreen"><div class="wrap">
  <div class="notice notice--soft">
    <p><strong>{esc(t(lang, "site.download.smartscreen_title"))}</strong> {t(lang, "site.download.smartscreen_text")}</p>
    <p>{t(lang, "site.download.smartscreen_steps")}</p>
  </div>
</div></section>

{disclaimer(lang)}"""
