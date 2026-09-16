"""Images de partage générées à la volée : `/og/song/{id}.png` (1200×630) pour la fiche publique d'un morceau.

Rendu Pillow une fois, puis cache disque `DATA_DIR/og_cache/song-<id>-<empreinte>.png` : l'empreinte change avec le
titre, l'artiste ou la date de mise à jour, l'ancienne image est alors supprimée. Seuls les morceaux approuvés ont
une image. Polices : Fredoka/Nunito du site si Pillow sait les lire, sinon une police système, sinon la police
intégrée de Pillow.
"""
from __future__ import annotations

import hashlib
import threading
import time
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from . import db
from .auth import api_error, settings_of
from .config import Settings
from .ratelimit import limit

router = APIRouter()

W, H = 1200, 630
STATIC = Path(__file__).resolve().parent.parent / "static"
CREAM = (244, 234, 216)
CREAM_LIGHT = (255, 248, 234)
BROWN = (79, 64, 57)
INK2 = (108, 92, 82)
TEAL = (24, 123, 117)
TEAL_SOFT = (223, 246, 244)
AMBER = (232, 165, 49)
OG_CACHE_DAYS = 30
RENDER_VERSION = "1"
_RENDER_LOCK = threading.Lock()

_BOLD = (STATIC / "fonts" / "fredoka-latin.woff2", Path("C:/Windows/Fonts/segoeuib.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
         Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"))
_REGULAR = (STATIC / "fonts" / "nunito-latin.woff2", Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"))


@lru_cache(maxsize=16)
def _font(bold: bool, size: int):
    from PIL import ImageFont
    for path in (_BOLD if bold else _REGULAR):
        if not path.is_file():
            continue
        try:
            font = ImageFont.truetype(str(path), size)
        except OSError:
            continue
        if path.suffix == ".woff2":
            try:
                font.set_variation_by_axes([600 if bold else 650])
            except Exception:  # noqa - police non variable
                pass
        return font
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = word
        while draw.textlength(line, font=font) > width and len(line) > 1:   # mot plus long que la ligne
            cut = len(line)
            while cut > 1 and draw.textlength(line[:cut], font=font) > width:
                cut -= 1
            lines.append(line[:cut])
            line = line[cut:]
        if len(lines) >= max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _duration(seconds) -> str:
    s = int(round(float(seconds or 0)))
    return f"{s // 60}:{s % 60:02d}"


def render_song_card(title: str, artist: str | None, note_count: int, duration_s: float, host: str) -> bytes:
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)
    for y in range(H):                                  # léger dégradé vertical
        t = y / H
        draw.line([(0, y), (W, y)], fill=tuple(round(CREAM_LIGHT[i] * (1 - t) + CREAM[i] * t) for i in range(3)))
    try:
        logo = Image.open(STATIC / "logo.png").convert("RGBA")
        img.paste(logo.resize((64, 64), Image.LANCZOS), (64, 58), logo.resize((64, 64), Image.LANCZOS))
        big = logo.resize((300, 300), Image.LANCZOS)
        img.paste(big, (850, 165), big)
    except OSError:
        pass
    draw.text((144, 70), "DodoTopia", font=_font(True, 38), fill=BROWN)
    title_font = _font(True, 64)
    lines = _wrap(draw, title, title_font, 720, 3)
    if len(lines) > 2:
        title_font = _font(True, 52)
        lines = _wrap(draw, title, title_font, 720, 3)
    y = 190
    for line in lines:
        draw.text((64, y), line, font=title_font, fill=BROWN)
        y += int(getattr(title_font, "size", 60) * 1.2)
    y += 10
    draw.rounded_rectangle((64, y, 154, y + 8), 4, fill=AMBER)
    y += 30
    text_font = _font(False, 32)
    if artist:
        for line in _wrap(draw, artist, text_font, 720, 1):
            draw.text((64, y), line, font=text_font, fill=INK2)
            y += 48
    draw.text((64, y), f"{note_count} notes · {_duration(duration_s)}", font=text_font, fill=INK2)
    pill = _font(True, 26)
    tw = draw.textlength(host, font=pill)
    draw.rounded_rectangle((64, H - 88, 64 + tw + 44, H - 40), 24, fill=TEAL_SOFT)
    draw.text((86, H - 83), host, font=pill, fill=TEAL)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def song_card_path(settings: Settings, row: db.Row) -> Path:
    key = "|".join(str(row.get(k) or "") for k in ("title", "artist", "note_count", "duration_s", "updated_at"))
    digest = hashlib.sha256(f"{RENDER_VERSION}|{settings.public_url}|{key}".encode("utf-8")).hexdigest()[:16]
    return settings.og_cache_dir / f"song-{int(row['id'])}-{digest}.png"


def song_card(settings: Settings, row: db.Row) -> Path:
    path = song_card_path(settings, row)
    if path.is_file():
        return path
    from urllib.parse import urlsplit
    host = urlsplit(settings.public_url).hostname or "dodotopia.cyber-dodo.fr"
    with _RENDER_LOCK:                                   # un rendu à la fois : pas de pic CPU sur une rafale
        if path.is_file():
            return path
        data = render_song_card(row["title"], row.get("artist"), int(row["note_count"] or 0),
                                float(row["duration_s"] or 0), host)
        path.parent.mkdir(parents=True, exist_ok=True)
        for old in path.parent.glob(f"song-{int(row['id'])}-*.png"):
            old.unlink(missing_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path


def purge_cache(settings: Settings) -> None:
    cutoff = time.time() - OG_CACHE_DAYS * 86400
    for p in settings.og_cache_dir.glob("*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


@router.get("/og/song/{song_id}.png", include_in_schema=False, dependencies=[Depends(limit("og", 60, 60))])
def song_og(song_id: int, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = conn.execute("SELECT id, title, artist, note_count, duration_s, updated_at, created_at, status "
                       "FROM songs WHERE id=?", (song_id,)).fetchone()
    if row is None or row["status"] != "approved":
        raise api_error(404, "not_found", "Morceau introuvable.")
    path = song_card(settings, row)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
