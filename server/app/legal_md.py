# -*- coding: utf-8 -*-
"""Conditions d'utilisation publiées sur le site : rendu HTML du Markdown de `app/legal/CGU-<lang>.md`.

Le fichier est une copie de `legal/CGU-<lang>.md` à la racine du dépôt (source unique des CGU, aussi livrée
dans l'application et présentée par l'installeur) ; `.tools/make_legal.py` fait la copie et un test vérifie
que les deux sont identiques. Même convertisseur minimal et sûr que `terms.py` côté client : tout le texte
est échappé avant l'ajout du balisage, seuls les liens https sont transformés."""
from __future__ import annotations

import html
import re
from pathlib import Path

LEGAL_DIR = Path(__file__).resolve().parent / "legal"

_INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\*)(.+?)(?<!\*)\*(?![*\w])")
_CODE = re.compile(r"`([^`]+)`")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = _INLINE_LINK.sub(r'<a href="\2" rel="noopener">\1</a>', text)
    return text


def markdown_to_html(md: str) -> str:
    md = _COMMENT.sub("", md)
    out: list[str] = []
    para: list[str] = []
    list_kind: str | None = None

    def flush_para() -> None:
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list() -> None:
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


def load(lang: str = "fr") -> dict | None:
    """{version, html} ou None si le fichier n'est pas livré avec le serveur."""
    path = LEGAL_DIR / f"CGU-{lang}.md"
    if not path.is_file():
        return None
    md = path.read_text(encoding="utf-8")
    m = re.search(r"^Version\s*:\s*(\S+)", md, re.M)
    return {"version": m.group(1) if m else "", "html": markdown_to_html(md), "markdown": md}
