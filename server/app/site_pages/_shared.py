"""Briques HTML communes aux pages (titres de section, FAQ, étapes illustrées, appels à l'action).

Le décor (nuages, motifs, vagues, illustrations) est toujours porté par des `<span aria-hidden="true">` stylés
en CSS : aucun attribut `style`, aucune image décorative (CSP `style-src 'self'`, tests sur les `<img>`)."""
from __future__ import annotations

from .. import site
from ..i18n import t, t_items
from ..site import decor, esc, url_for


def section_head(title: str, lead: str = "") -> str:
    """Titre de section centré (`<h2>` sans attribut) et chapeau ; `title` et `lead` : HTML déjà sûr."""
    lead_html = f'<p class="lead">{lead}</p>' if lead else ""
    return f'<div class="sechead reveal"><h2>{title}</h2>{lead_html}</div>'


def faq_block(items: list[dict], open_first: bool = False) -> str:
    out = []
    for i, item in enumerate(items):
        opened = " open" if open_first and i == 0 else ""
        out.append(f'<details{opened}><summary>{item["q"]}</summary><div class="faq__body">{item["a"]}</div></details>')
    return f'<div class="faq">{"".join(out)}</div>'


def faq_section(lang: str, ctx, prefix: str, title: str, section_id: str = "questions",
                more: str = "") -> str:
    """Section FAQ + JSON-LD FAQPage (ajouté dans <head> par le contexte)."""
    items = t_items(lang, prefix)
    if not items:
        return ""
    ctx.head.append(site.ld_script(site.faq_ld(items)))
    return f"""<section class="section wavy wavy--2 plain" id="{section_id}"><div class="wrap wrap--narrow">
  {section_head(title)}
  {faq_block(items)}
  {more}
</div></section>
"""


def steps_block(lang: str, prefix: str, arts: tuple[str, ...] = ()) -> str:
    """Étapes numérotées. `arts` : illustrations de `static/art/step-<nom>.svg` (accueil) ; sinon une vignette au
    motif de la rubrique (note, pinceau, marmite…), colorée par le thème de la page."""
    items = t_items(lang, prefix, ("title", "text"))
    out = []
    for i, item in enumerate(items, 1):
        art = arts[i - 1] if i <= len(arts) else "motif"
        out.append(f'<li class="step"><span class="step__art step__art--{art}" aria-hidden="true"></span>'
                   f'<span class="step__num" aria-hidden="true">{i}</span>'
                   f'<h3>{item["title"]}</h3><p>{item["text"]}</p></li>')
    return f'<ol class="steps reveal">{"".join(out)}</ol>'


def bullet_list(lang: str, prefix: str, cls: str = "") -> str:
    items = []
    n = 1
    while site.i18n.has("fr", f"{prefix}.{n}", strict=True):
        items.append(f"<li>{t(lang, f'{prefix}.{n}')}</li>")
        n += 1
    cls_attr = f' class="{cls}"' if cls else ""
    return f"<ul{cls_attr}>{''.join(items)}</ul>"


def download_button(lang: str, latest: dict | None, cls: str = "btn btn--cta btn--lg") -> str:
    """Bouton vers la page de téléchargement (jamais un lien mort : « Bientôt disponible » sans version)."""
    if latest:
        return (f'<a class="{cls}" href="{url_for(lang, "download")}"><span class="btn__ico" aria-hidden="true">'
                f'</span>{esc(t(lang, "site.common.download_cta"))}</a>')
    return f'<a class="btn btn--quiet" href="{url_for(lang, "download")}">{esc(t(lang, "site.common.soon_cta"))}</a>'


def cta_band(lang: str, title: str, text: str, latest: dict | None) -> str:
    """Grand appel à l'action de fin de page : dégradé turquoise, collines, dodo."""
    return f"""<section class="section section--cta"><div class="wrap wrap--wide">
  <div class="finalcta reveal">
    <span class="sky" aria-hidden="true">{decor("cloud cloud--a", "cloud cloud--b", "fx fx--s1", "fx fx--s2")}</span>
    <span class="finalcta__hills" aria-hidden="true"></span>
    <div class="finalcta__txt">
      <h2>{title}</h2>
      <p>{text}</p>
      <div class="actions">{download_button(lang, latest, "btn btn--lg")}</div>
      <p class="finalcta__trust">{esc(t(lang, "site.footer.trust"))}</p>
    </div>
    {site.dodo(lang, 220, "dodo--cta")}
  </div>
</div></section>
"""


def disclaimer(lang: str) -> str:
    return f"""<section class="section section--tight"><div class="wrap wrap--narrow">
  <div class="notice notice--quiet">
    <p><strong>{t(lang, 'site.common.unofficial_title')}</strong> {t(lang, 'site.common.unofficial_text')}</p>
  </div>
</div></section>
"""
