"""Briques HTML communes aux pages (FAQ, étapes, appels à l'action)."""
from __future__ import annotations

from .. import site
from ..i18n import t, t_items
from ..site import esc, url_for


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
    return f"""<section class="section" id="{section_id}"><div class="wrap">
  <h2>{title}</h2>
  {faq_block(items)}
  {more}
</div></section>
"""


def steps_block(lang: str, prefix: str) -> str:
    items = t_items(lang, prefix, ("title", "text"))
    return '<ol class="steps">' + "".join(
        f'<li class="step"><span class="step__num" aria-hidden="true">{i}</span>'
        f'<h3>{item["title"]}</h3><p>{item["text"]}</p></li>'
        for i, item in enumerate(items, 1)) + "</ol>"


def bullet_list(lang: str, prefix: str, cls: str = "") -> str:
    items = []
    n = 1
    while site.i18n.has("fr", f"{prefix}.{n}", strict=True):
        items.append(f"<li>{t(lang, f'{prefix}.{n}')}</li>")
        n += 1
    cls_attr = f' class="{cls}"' if cls else ""
    return f"<ul{cls_attr}>{''.join(items)}</ul>"


def cta_band(lang: str, title: str, text: str, latest: dict | None) -> str:
    """Bandeau d'appel à l'action : vers la page de téléchargement (jamais un lien mort)."""
    button = (f'<a class="btn btn--cta" href="{url_for(lang, "download")}">{esc(t(lang, "site.common.download_cta"))}</a>'
              if latest else
              f'<a class="btn btn--quiet" href="{url_for(lang, "download")}">{esc(t(lang, "site.common.soon_cta"))}</a>')
    return f"""<section class="section"><div class="wrap">
  <div class="ctaband">
    <div><h2>{title}</h2><p>{text}</p></div>
    <div class="ctaband__btn">{button}</div>
  </div>
</div></section>
"""


def disclaimer(lang: str) -> str:
    return f"""<section class="section section--tight"><div class="wrap">
  <div class="notice">
    <p><strong>{t(lang, 'site.common.unofficial_title')}</strong> {t(lang, 'site.common.unofficial_text')}</p>
  </div>
</div></section>
"""
