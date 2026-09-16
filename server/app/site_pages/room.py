"""Lien d'invitation vers un salon (`/{lang}/<salon>/{CODE}`) : page `noindex` qui tente d'ouvrir DodoTopia sur
`dodotopia://room/{CODE}`, indique si le salon existe encore (`GET /api/rooms/{code}/exists`) et propose de
télécharger l'application. Jamais mise en cache (propre à chaque code)."""
from __future__ import annotations

import json
import re

from ..i18n import t
from ..rooms import ALPHABET, CODE_LEN
from ..site import NONCE, esc
from ._listing import app_buttons, plain

_CODE_RE = re.compile(rf"^[{ALPHABET}]{{{CODE_LEN}}}$")


def normalize_code(raw: str) -> str | None:
    code = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    return code if _CODE_RE.match(code) else None


def render_room(settings, lang: str, ctx, code: str) -> str:
    ctx.robots = "noindex, nofollow"
    ctx.canonical = False
    ctx.title = plain(lang, "site.room.title", code=code)
    ctx.description = plain(lang, "site.room.description", code=code)
    texts = {"open": plain(lang, "site.room.status_open"), "full": plain(lang, "site.room.status_full"),
             "gone": plain(lang, "site.room.status_gone")}
    data = json.dumps({"code": code, "texts": texts}, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    script = (f'<script nonce="{NONCE}">(function(){{var d={data};var s=document.getElementById("room-status");'
              'fetch("/api/rooms/"+d.code+"/exists",{headers:{Accept:"application/json"}})'
              '.then(function(r){return r.json()}).then(function(x){'
              's.textContent=x.exists?(x.full?d.texts.full:d.texts.open):d.texts.gone}).catch(function(){});'
              'setTimeout(function(){window.location.href="dodotopia://room/"+d.code},400)})();</script>')
    return f"""<section class="section"><div class="wrap">
  <div class="errorbox">
    <p class="eyebrow">{esc(t(lang, "site.room.eyebrow"))}</p>
    <h1>{t(lang, "site.room.h1", code=code)}</h1>
    <p class="lead">{t(lang, "site.room.text")}</p>
    <p class="roomcode mono" aria-label="{esc(plain(lang, "site.room.code_label"))}">{esc(code)}</p>
    <p class="dl-note" id="room-status" role="status" aria-live="polite"></p>
    {app_buttons(lang, f"dodotopia://room/{code}", "site.room.open_app", ctx.latest)}
  </div>
</div></section>
{script}
"""
