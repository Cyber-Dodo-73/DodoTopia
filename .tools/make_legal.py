"""Convertit legal/CGU-<lang>.md en legal/CGU-<lang>.rtf pour la page de licence d'Inno Setup.

Inno Setup n'accepte que .txt ou .rtf pour `LicenseFile` ; le RTF garde les titres, le gras et les
listes. Aucune dépendance externe : un Markdown volontairement limité est reconnu (voir legal/README.md).

    py .tools/make_legal.py            # convertit tous les legal/CGU-*.md et vérifie les RTF produits
    py .tools/make_legal.py fr en      # seulement ces langues

Encodage : le fichier RTF est écrit en ASCII pur. Les caractères présents dans cp1252 sont émis
`\\'xx` (Word, WordPad et le composant RichEdit d'Inno Setup les lisent tous), les autres en `\\uN?`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGAL = ROOT / "legal"

# --- Encodage RTF ---------------------------------------------------------------------------------

def rtf_escape(text: str) -> str:
    """Texte brut -> séquence RTF ASCII (accolades, antislash, accents, caractères hors cp1252)."""
    out = []
    for ch in text:
        code = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\t":
            out.append("\\tab ")
        elif ch == "\u00a0":
            out.append("\\~")          # espace insécable (avant « : », « ; », « ? »...)
        elif 0x20 <= code < 0x7F:
            out.append(ch)
        elif code < 0x20:
            continue
        else:
            try:
                b = ch.encode("cp1252")
                out.append("\\'%02x" % b[0])
            except UnicodeEncodeError:
                if code > 0xFFFF:      # hors plan de base : paire de substituts
                    hi, lo = divmod(code - 0x10000, 0x400)
                    for unit in (0xD800 + hi, 0xDC00 + lo):
                        out.append("\\u%d?" % (unit - 0x10000 if unit > 0x7FFF else unit))
                else:
                    out.append("\\u%d?" % (code - 0x10000 if code > 0x7FFF else code))
    return "".join(out)


# --- Mise en forme en ligne -----------------------------------------------------------------------

_INLINE = re.compile(
    r"\[(?P<ltxt>[^\]]+)\]\((?P<lurl>[^)\s]+)\)"     # [texte](url)
    r"|\*\*(?P<bold>.+?)\*\*"                        # **gras**
    r"|(?<![\w*])\*(?P<ital>[^*\n]+?)\*(?![\w*])"    # *italique*
    r"|(?<!\w)_(?P<ital2>[^_\n]+?)_(?!\w)"           # _italique_
    r"|`(?P<code>[^`]+)`"                            # `code`
)


def inline(text: str) -> str:
    """Markdown en ligne -> RTF. Les liens deviennent « texte (url) » : le RTF de l'installeur n'est pas cliquable."""
    pos, out = 0, []
    for m in _INLINE.finditer(text):
        out.append(rtf_escape(text[pos:m.start()]))
        if m.group("ltxt") is not None:
            txt, url = m.group("ltxt"), m.group("lurl")
            if txt.strip() == url.strip():
                out.append(rtf_escape(url))
            else:
                out.append(inline(txt) + " (" + rtf_escape(url) + ")")
        elif m.group("bold") is not None:
            out.append("{\\b " + inline(m.group("bold")) + "}")
        elif m.group("ital") is not None:
            out.append("{\\i " + inline(m.group("ital")) + "}")
        elif m.group("ital2") is not None:
            out.append("{\\i " + inline(m.group("ital2")) + "}")
        else:
            out.append("{\\f1 " + rtf_escape(m.group("code")) + "}")
        pos = m.end()
    out.append(rtf_escape(text[pos:]))
    return "".join(out)


# --- Blocs -----------------------------------------------------------------------------------------

HEADER = (
    "{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1036\\deflangfe1036"
    "{\\fonttbl{\\f0\\fswiss\\fcharset0 Arial;}{\\f1\\fmodern\\fcharset0 Consolas;}}"
    "{\\colortbl;\\red0\\green0\\blue0;}"
    "\\viewkind4\\uc1\\pard\\f0\\fs20\r\n"
)

# Style par niveau de titre : (taille en demi-points, espace avant, espace après)
HEADING = {1: (34, 0, 200), 2: (26, 300, 120), 3: (22, 220, 80)}

_H = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")
_UL = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def paragraph(text: str, *, sb: int = 0, sa: int = 120) -> str:
    return f"\\pard\\sb{sb}\\sa{sa}\\ql {inline(text)}\\par\r\n"


def heading(level: int, text: str) -> str:
    size, sb, sa = HEADING[level]
    return f"\\pard\\sb{sb}\\sa{sa}\\keepn{{\\b\\fs{size} {inline(text)}}}\\par\r\n"


def bullet(text: str) -> str:
    return f"\\pard\\fi-283\\li566\\sa60 \\bullet\\tab {inline(text)}\\par\r\n"


def numbered(n: str, text: str) -> str:
    return f"\\pard\\fi-360\\li720\\sa60 {rtf_escape(n)}.\\tab {inline(text)}\\par\r\n"


def md_to_rtf(md: str) -> str:
    md = _COMMENT.sub("", md)
    out = [HEADER]
    buf: list[str] = []          # lignes du paragraphe en cours
    item: list[str] | None = None  # ["ul"|"ol", numéro, lignes...]

    def flush_par():
        if buf:
            out.append(paragraph(" ".join(s.strip() for s in buf)))
            buf.clear()

    def flush_item():
        nonlocal item
        if item:
            kind, num, *lines = item
            text = " ".join(s.strip() for s in lines)
            out.append(bullet(text) if kind == "ul" else numbered(num, text))
            item = None

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_par(); flush_item()
            continue
        if line.lstrip().startswith("```"):
            continue                      # les blocs de code ne sont pas attendus dans les CGU
        m = _H.match(line)
        if m:
            flush_par(); flush_item()
            out.append(heading(len(m.group(1)), m.group(2)))
            continue
        if _HR.match(line):
            flush_par(); flush_item()
            out.append("\\pard\\sa120\\brdrb\\brdrs\\brdrw10\\brsp20 \\par\r\n")
            continue
        m = _UL.match(line)
        if m and not _HR.match(line):
            flush_par(); flush_item()
            item = ["ul", "", m.group(1)]
            continue
        m = _OL.match(line)
        if m:
            flush_par(); flush_item()
            item = ["ol", m.group(1), m.group(2)]
            continue
        # Ligne de continuation : appartient à l'élément de liste en cours s'il est indenté, sinon au paragraphe.
        if item is not None and raw[:1] in (" ", "\t"):
            item.append(line)
        else:
            flush_item()
            buf.append(line)
    flush_par(); flush_item()
    out.append("}\r\n")
    return "".join(out)


# --- Vérification ----------------------------------------------------------------------------------

def check_rtf(path: Path, source_md: str) -> list[str]:
    """Contrôles minimaux : en-tête, fermeture, accolades équilibrées, ASCII pur, accents encodés."""
    problems = []
    data = path.read_bytes()
    if not data.startswith(b"{\\rtf1"):
        problems.append("ne commence pas par {\\rtf1")
    if not data.rstrip().endswith(b"}"):
        problems.append("ne se termine pas par }")
    if any(b > 0x7E for b in data):
        problems.append("contient des octets non ASCII (accents non echappes)")
    depth = 0
    prev = ""
    for ch in data.decode("ascii", "replace"):
        if ch in "{}" and prev != "\\":
            depth += 1 if ch == "{" else -1
            if depth < 0:
                problems.append("accolade fermante en trop"); break
        prev = "" if prev == "\\" else ch
    if depth != 0:
        problems.append(f"accolades desequilibrees (profondeur finale {depth})")
    # Chaque caractère accentué du Markdown doit apparaître encodé dans le RTF.
    body = _COMMENT.sub("", source_md)
    for ch in sorted({c for c in body if ord(c) > 0x7F}):
        try:
            token = ("\\'%02x" % ch.encode("cp1252")[0]).encode()
        except UnicodeEncodeError:
            code = ord(ch)
            token = ("\\u%d?" % (code - 0x10000 if code > 0x7FFF else code)).encode()
        if ch != "\u00a0" and token not in data:
            problems.append(f"caractere {ch!r} (U+{ord(ch):04X}) absent du RTF sous la forme {token.decode()}")
    return problems


def main(argv: list[str]) -> int:
    langs = argv or sorted(p.stem.split("-", 1)[1] for p in LEGAL.glob("CGU-*.md"))
    if not langs:
        print(f"aucun legal/CGU-<lang>.md trouve dans {LEGAL}", file=sys.stderr)
        return 1
    rc = 0
    for lang in langs:
        src = LEGAL / f"CGU-{lang}.md"
        dst = LEGAL / f"CGU-{lang}.rtf"
        if not src.is_file():
            print(f"[{lang}] introuvable : {src}", file=sys.stderr)
            rc = 1
            continue
        md = src.read_text(encoding="utf-8")
        dst.write_bytes(md_to_rtf(md).encode("ascii"))
        # copie pour le site (le contexte Docker du serveur est server/ : il ne voit pas legal/ a la racine)
        server_copy = ROOT / "server" / "app" / "legal" / src.name
        server_copy.parent.mkdir(parents=True, exist_ok=True)
        if not server_copy.is_file() or server_copy.read_text(encoding="utf-8") != md:
            server_copy.write_text(md, encoding="utf-8", newline="\n")
            print(f"[{lang}] copie mise a jour : {server_copy.relative_to(ROOT)}")
        problems = check_rtf(dst, md)
        if problems:
            rc = 1
            print(f"[{lang}] {dst.name} : ECHEC")
            for p in problems:
                print(f"    - {p}")
        else:
            print(f"[{lang}] {dst.relative_to(ROOT)} : {dst.stat().st_size} octets, controles OK")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
