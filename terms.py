# -*- coding: utf-8 -*-
"""Conditions generales d'utilisation (CGU) : version en vigueur, lecture des textes livres dans legal/,
rendu HTML sur pour l'interface, et etat d'acceptation dans la configuration.

Personne ne peut utiliser DodoTopia sans avoir accepte les CGU : l'installeur les presente (LicenseFile), puis
l'application les redemande au premier lancement et a chaque changement de TERMS_VERSION (version portable
comprise). Les methodes de l'Api qui agissent (jouer, dessiner, cuisiner, en ligne) refusent tant que
`required(cfg)` est vrai : la garde n'est pas seulement dans l'interface."""
import html
import os
import re
import time

# A faire correspondre a la ligne « Version : » de legal/CGU-fr.md (verifie par tests_client/test_terms.py).
TERMS_VERSION = "2026-10"
LANGS = ("fr", "en", "es", "de", "pt-BR", "zh-CN", "ja", "th", "id", "fil")
SUMMARY_TITLES = {"fr": "L'essentiel en 6 points", "en": "The essentials in 6 points"}

_cache = {}


def legal_dir(res_dir):
    return os.path.join(res_dir, "legal")


def path_for(res_dir, lang):
    lang = lang if lang in LANGS else "fr"
    return os.path.join(legal_dir(res_dir), f"CGU-{lang}.md")


# ---------------------------------------------------------------- etat d'acceptation
def required(cfg):
    """Vrai tant que la version en vigueur n'a pas ete acceptee."""
    return str(cfg.get("terms_accepted_version") or "") != TERMS_VERSION


def accept(cfg, version, lang="fr"):
    """Enregistre l'acceptation. Refuse une version qui n'est pas celle en vigueur (ecran perime)."""
    if str(version) != TERMS_VERSION:
        return False
    cfg["terms_accepted_version"] = TERMS_VERSION
    cfg["terms_accepted_at"] = time.time()
    cfg["terms_accepted_lang"] = lang if lang in LANGS else "fr"
    return True


def state(cfg):
    return {"required": required(cfg), "version": TERMS_VERSION,
            "accepted_version": cfg.get("terms_accepted_version") or None,
            "accepted_at": cfg.get("terms_accepted_at") or None}


# ---------------------------------------------------------------- rendu
_INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\*)(.+?)(?<!\*)\*(?![*\w])")
_CODE = re.compile(r"`([^`]+)`")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _inline(text):
    """Balisage en ligne sur du texte deja echappe : gras, italique, code, liens (https seulement)."""
    text = html.escape(text, quote=False)
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = _INLINE_LINK.sub(r'<a href="\2" rel="noopener">\1</a>', text)
    return text


def markdown_to_html(md):
    """Convertisseur minimal et sur : titres, paragraphes, listes a puces et numerotees. Tout le texte est
    echappe avant d'ajouter le balisage (aucune donnee utilisateur ici, mais la regle vaut partout)."""
    md = _COMMENT.sub("", md)
    out = []
    para = []
    list_kind = None

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_kind
        if list_kind:
            out.append("</ul>" if list_kind == "ul" else "</ol>")
            list_kind = None

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            close_list()
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_para()
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            flush_para()
            if list_kind != "ul":
                close_list()
                out.append("<ul>")
                list_kind = "ul"
            out.append("<li>" + _inline(m.group(1)) + "</li>")
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            flush_para()
            if list_kind != "ol":
                close_list()
                out.append("<ol>")
                list_kind = "ol"
            out.append("<li>" + _inline(m.group(1)) + "</li>")
            continue
        if list_kind and line.startswith("  "):
            out[-1] = out[-1][:-5] + " " + _inline(line.strip()) + "</li>"
            continue
        close_list()
        para.append(line.strip())
    flush_para()
    close_list()
    return "\n".join(out)


def _summary(md, lang):
    """Les 6 points du resume : les elements numerotes sous le titre « L'essentiel en 6 points ». Langue sans
    titre dans SUMMARY_TITLES : la premiere section `##` qui contient une liste numerotee (meme place dans
    toutes les traductions)."""
    title = SUMMARY_TITLES.get(lang)
    sections = []
    for line in md.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip().lower(), []))
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m and sections:
            sections[-1][1].append(re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1)).strip())
    if title:
        for heading, items in sections:
            if heading.startswith(title.lower()[:12]):
                return items
    return next((items for _, items in sections if items), [])


def _version_in(md):
    m = re.search(r"^Version\s*:\s*(\S+)", md, re.M)
    return m.group(1) if m else ""


def load(res_dir, lang="fr"):
    """{version, lang, summary, markdown, html}. Cache par (chemin, mtime). Repli sur l'anglais puis sur le
    francais si la langue demandee n'est pas livree."""
    lang = lang if lang in LANGS else "fr"
    path = path_for(res_dir, lang)
    for fallback in ("en", "fr"):
        if os.path.isfile(path):
            break
        path, lang = path_for(res_dir, fallback), fallback
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    key = (path, mtime)
    if key in _cache:
        return dict(_cache[key])
    with open(path, "r", encoding="utf-8") as f:
        md = f.read()
    doc = {"version": _version_in(md) or TERMS_VERSION, "lang": lang, "summary": _summary(md, lang),
           "markdown": _COMMENT.sub("", md).strip(), "html": markdown_to_html(md)}
    _cache[key] = doc
    return dict(doc)
