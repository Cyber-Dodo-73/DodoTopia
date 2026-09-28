"""Pages légales : mentions légales et politique de confidentialité (catalogues fr/en, autres langues en
anglais), conditions d'utilisation rendues depuis `app/legal/CGU-<lang>.md` (une traduction par langue du site, repli
sur l'anglais ; la version française fait foi)."""
from __future__ import annotations

from .. import legal_md
from ..i18n import has, t
from ..site import (EDITEUR_ADRESSE, EDITEUR_COURRIEL, EDITEUR_MARQUE, EDITEUR_NOM, EDITEUR_SIRET, EDITEUR_TEL,
                    EDITEUR_TEL_INTL, HEBERGEUR_ADRESSE, HEBERGEUR_CONTACT, HEBERGEUR_NOM, LAST_UPDATE_ISO,
                    SITE_HOST, esc, last_update, page_header, url_for)


def _band(lang: str) -> str:
    """Bandeau décoratif sans titre : le <h1> est dans le document (celui des CGU vient du Markdown)."""
    return page_header(lang, esc(t(lang, "site.footer.legal")), "", "", cls="pagehead--bare")


def _updated(lang: str) -> str:
    date = last_update(lang)
    return (f'<p class="updated">{esc(t(lang, "site.legal.updated"))} '
            f'<time datetime="{LAST_UPDATE_ISO}">{esc(date)}</time></p>')


def _sections(lang: str, prefix: str, params: dict) -> str:
    """Sections numérotées `prefix.sN.title` / `prefix.sN.body` (HTML de confiance, paramètres échappés)."""
    out = []
    n = 1
    while has("fr", f"{prefix}.s{n}.title", strict=True):
        out.append(f'<h2 id="s{n}">{t(lang, f"{prefix}.s{n}.title")}</h2>\n{t(lang, f"{prefix}.s{n}.body", **params)}')
        n += 1
    return "\n".join(out)


def _params(settings) -> dict:
    return dict(name=EDITEUR_NOM, brand=EDITEUR_MARQUE, siret=EDITEUR_SIRET, address=EDITEUR_ADRESSE,
                email=EDITEUR_COURRIEL, phone=EDITEUR_TEL, phone_intl=EDITEUR_TEL_INTL, host=SITE_HOST,
                hoster=HEBERGEUR_NOM, hoster_address=HEBERGEUR_ADRESSE, hoster_contact=HEBERGEUR_CONTACT,
                days=settings.SESSION_DAYS)


class _Mentions:
    @staticmethod
    def render(settings, lang: str, ctx) -> str:
        params = _params(settings)
        params["terms_url"] = url_for(lang, "terms")
        params["privacy_url"] = url_for(lang, "privacy")
        return f"""{_band(lang)}<section class="section section--first section--doc"><div class="wrap"><article class="doc">
  <h1>{t(lang, "site.legal.h1")}</h1>
  {_updated(lang)}
  {_sections(lang, "site.legal", params)}
</article></div></section>
"""


class _Privacy:
    @staticmethod
    def render(settings, lang: str, ctx) -> str:
        params = _params(settings)
        params["terms_url"] = url_for(lang, "terms")
        params["legal_url"] = url_for(lang, "legal")
        analytics_on = bool((settings.PLAUSIBLE_SCRIPT_URL or "").strip())
        params["audience_status"] = t(lang, "site.privacy.audience_on" if analytics_on else "site.privacy.audience_off")
        return f"""{_band(lang)}<section class="section section--first section--doc"><div class="wrap"><article class="doc">
  <h1>{t(lang, "site.privacy.h1")}</h1>
  {_updated(lang)}
  <p>{t(lang, "site.privacy.intro", **params)}</p>
  {_sections(lang, "site.privacy", params)}
</article></div></section>
"""


class _Terms:
    @staticmethod
    def render(settings, lang: str, ctx) -> str:
        doc = legal_md.load(lang) or legal_md.load("en") or legal_md.load("fr")
        if not doc:
            return f"""{_band(lang)}<section class="section section--first section--doc"><div class="wrap"><article class="doc">
  <h1>{t(lang, "site.terms.h1")}</h1>
  <div class="notice"><p>{t(lang, "site.terms.unavailable", email=EDITEUR_COURRIEL)}</p></div>
</article></div></section>
"""
        note = ""
        if lang != "fr":
            note = (f'<div class="notice notice--soft"><p><strong>{t(lang, "site.terms.prevails_title")}</strong> '
                    f'{t(lang, "site.terms.prevails_text")} <a href="{url_for("fr", "terms")}" hreflang="fr" lang="fr">'
                    f'{esc(t(lang, "site.terms.prevails_link"))}</a></p></div>')
        return f"""{_band(lang)}<section class="section section--first section--doc"><div class="wrap"><article class="doc doc--terms">
{note}
{doc["html"]}
</article></div></section>
"""


Mentions = _Mentions
Privacy = _Privacy
Terms = _Terms
