// DodoTopia : panneau « Salon en ligne » du lecteur (#roomBox) et bandeau de session du salon.
// Lit st.online.room (= RoomSession.status()) : cle plate {state, role, seconds_left, message} + cle room {code,
// players, song, clock, me, can_start, start_blocker...}. Toutes les actions passent par les methodes Api
// room_create / room_join / room_leave / room_ready / room_start / room_cancel / room_stop / room_set_offset.

const ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';   // meme alphabet que room.py (sans I, O, 0, 1)
const ROOMUI = {code: ''};

function roomInfo(st){ const r = st && st.online && st.online.room; return r && r.room ? r : null; }
function normRoomCode(s){ return String(s || '').toUpperCase().split('').filter(c => ROOM_ALPHABET.indexOf(c) >= 0).join('').slice(0, 6); }
// ------------------------------------------------ instrument d'un participant
// Le protocole transmet un identifiant stable (« lute »), jamais un chemin local ni une image. Les clients
// d'avant le catalogue envoient encore leurs anciens identifiants : MUSIC_LEGACY_IDS (music.js) les traduit.
// Un identifiant inconnu donne un nom de repli neutre et une pastille generique, jamais une erreur bloquante.
function instrumentEntry(st, id){
  const list = (st && st.instruments) || [];
  const raw = String(id == null ? '' : id).trim();
  if(!raw) return null;
  const key = raw.toLowerCase();
  let ins = list.find(x => x && String(x.id).toLowerCase() === key);
  if(!ins && MUSIC_LEGACY_IDS[key]) ins = list.find(x => x && x.id === MUSIC_LEGACY_IDS[key]);
  if(!ins) ins = list.find(x => ((x && x.aliases) || []).some(a => norm(a) === norm(key)));
  return ins || null;
}
function instrumentName(st, id){
  const ins = instrumentEntry(st, id);
  if(ins) return cap(ins.name);
  return String(id == null ? '' : id).trim() ? t('lobby.instrument.unknown') : '';
}
// repli de l'image : une pastille generique, sans decaler la ligne (meme taille que l'image)
function instrumentIconFallback(img){
  const s = document.createElement('span');
  s.className = img.className;
  s.setAttribute('aria-hidden', 'true');
  s.innerHTML = icon('note');
  img.replaceWith(s);
}
function instrumentIconHtml(st, id){
  const ins = instrumentEntry(st, id);
  // image locale servie depuis ui/instruments/<id>.png : rien n'est telecharge, rien n'est transmis
  const src = ins ? (ins.image || ('instruments/' + ins.id + '.png')) : '';
  if(!src) return `<span class="insico" aria-hidden="true">${icon('note')}</span>`;
  return `<img class="insico" src="${esc(src)}" alt="" width="18" height="18" onerror="instrumentIconFallback(this)">`;
}
function instrumentBadgeHtml(st, id){
  const name = instrumentName(st, id);
  if(!name) return '';
  return `${instrumentIconHtml(st, id)}${esc(name)}`;
}
function clockText(clock){
  const e = clock && clock.err_ms;
  return e == null ? t('lobby.clock.pending') : t('lobby.clock.error', {ms: Math.round(e)});
}
// avatar Discord : image si on en a une, sinon l'initiale (avatarFallback est dans online.js)
function personHtml(p, cls){
  const name = (p && (p.name || p.username || p.global_name)) || t('lobby.player');
  const ini = esc(name.slice(0, 1).toUpperCase());
  let url = (p && (p.avatar_url || p.avatar)) || '';
  if(url && !/^https?:/.test(url) && p.id != null) url = `https://cdn.discordapp.com/avatars/${encodeURIComponent(p.id)}/${encodeURIComponent(url)}.png?size=64`;
  return url ? `<img class="${cls}" src="${esc(url)}" alt="" data-ini="${ini}" onerror="avatarFallback(this)">`
             : `<span class="${cls} avatar--ini">${ini}</span>`;
}

// ------------------------------------------------ panneau hors salon : code + Rejoindre + Creer
function roomJoinHtml(st, o, logged){
  const D = roomInfo(st) ? roomInfo(st).room : null;
  const last = (D && D.last_room) || '';
  const blocked = !o || o.server_ok === false || o.client_too_old || !logged;
  const out = [];
  if(!o){
    out.push(`<div class="notice notice--info"><span class="notice__ic" aria-hidden="true">${icon('globe')}</span><div class="notice__text">${esc(t('lobby.join.unavailable'))}</div></div>`);
  } else if(o.server_ok === false){
    out.push(`<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(t('lobby.join.server_unreachable', {has_reason: o.offline_reason ? 'yes' : 'no', reason: o.offline_reason || ''}))}
      <button class="btn btn--ghost btn--sm" type="button" data-act="refresh">${esc(t('lobby.join.retry'))}</button></div></div>`);
  } else if(o.client_too_old){
    out.push(`<div class="notice notice--danger"><span class="notice__ic" aria-hidden="true">${icon('danger')}</span><div class="notice__text">${esc(t('lobby.join.too_old'))}
      <button class="btn btn--ghost btn--sm" type="button" data-act="update">${esc(t('lobby.join.see_update'))}</button></div></div>`);
  } else if(!logged){
    out.push(`<div class="notice notice--info"><span class="notice__ic" aria-hidden="true">${icon('user')}</span><div class="notice__text">${esc(t('lobby.join.need_account'))}
      <button class="btn btn--discord btn--sm" type="button" data-act="account">${icon('discord')}<span>${esc(t('lobby.join.sign_in'))}</span></button></div></div>`);
  }
  const dis = blocked ? ' disabled' : '';
  out.push(`<div class="roomjoin">
      <input class="input roomcode__in" type="text" maxlength="6" spellcheck="false" autocomplete="off"
             placeholder="${esc(t('lobby.join.code_placeholder'))}" aria-label="${esc(t('lobby.join.code_label'))}" value="${esc(ROOMUI.code || last)}"${dis}>
      <button class="btn btn--secondary btn--sm" type="button" data-act="join"${dis}>${esc(t('lobby.join.join'))}</button>
      <div class="spacer"></div>
      <button class="btn btn--cta btn--sm" type="button" data-act="create"${dis}>${icon('plus')}<span>${esc(t('lobby.join.create'))}</span></button>
    </div>`);
  const R = roomInfo(st);
  // Au repos, la ligne de code et les deux boutons se suffisent : l'explication du deroulement ne
  // s'affiche que quand elle apporte quelque chose (connexion en cours, ou erreur a lire).
  const msg = R && R.state === 'connecting' ? esc(t('lobby.join.connecting'))
    : (D && D.error) ? esc(D.error) : '';
  if(msg) out.push(`<div class="hint left">${msg}</div>`);
  return out.join('');
}

// ------------------------------------------------ panneau en salon
// En salon, la ligne « Instrument » du lecteur laisse la place au bandeau de session : on ne pouvait
// donc plus changer d'instrument sans quitter la vue. Le moteur, lui, previent deja le salon a chaque
// changement (app.py -> Room.on_instrument_change) : il ne manquait que de quoi le demander d'ici.
function myInstrumentRow(st){
  const ins = (typeof instActive === 'function' ? instActive(st) : null) || null;
  const stt = (typeof instStatus === 'function' ? instStatus(ins && ins.status) : null);
  return `<div class="roomsong roomins">
      <span class="roomsong__lbl">${esc(t('lobby.my_instrument.label'))}</span>
      ${ins ? instrumentIconHtml(st, ins.id) : icon('note')}
      <span class="t">${esc(ins ? cap(ins.name || ins.id) : t('lobby.my_instrument.none'))}</span>
      ${stt && stt.label ? `<span class="chip chip--badge ${stt.chip}">${esc(stt.label)}</span>` : ''}
      <div class="spacer"></div>
      <button class="btn btn--secondary btn--sm" type="button" data-act="inst">${esc(t('lobby.my_instrument.change'))}</button>
    </div>`;
}
function roomViewHtml(st, R, D, hk){
  const f6 = `<kbd>${esc((hk || {}).play_pause || 'F6')}</kbd>`;
  const clock = D.clock || {};
  const err = clock.err_ms;
  const warn = err != null && err > 50;
  const players = D.players || [];
  const me = D.me || {};
  const host = !!me.host;
  const song = D.song;
  const counting = D.state === 'countdown';
  const roomUrl = (st.online && st.online.room_url) || '';
  let main;
  if(counting){
    main = host ? `<button class="btn btn--danger" type="button" data-act="cancel">${icon('close')}<span>${esc(t('common.cancel'))}</span>${f6}</button>`
                : `<button class="btn btn--secondary" type="button" data-act="stop">${esc(t('lobby.room.cancel_me'))}</button>`;
  } else if(host){
    main = `<button class="btn btn--cta" type="button" data-act="start"${D.can_start ? '' : ' disabled'}>${icon('play')}<span>${esc(t('music.together.start_session'))}</span>${f6}</button>`;
  } else {
    main = `<button class="btn ${me.ready ? 'btn--secondary' : 'btn--cta'}" type="button" data-act="ready">${icon(me.ready ? 'close' : 'check')}<span>${esc(me.ready ? t('lobby.room.ready_cancel') : t('lobby.room.ready'))}</span>${f6}</button>`;
  }
  // hote bloque : la raison est ecrite sous le bouton (setAction dans roomPanel), pas repetee ici
  const hint = host ? (D.can_start || counting ? t('lobby.room.can_start') : '')
                    : (counting ? t('lobby.room.starting') : t('lobby.room.guest_hint'));
  const badge = (title, cls, name) => `<span${cls ? ` class="${cls}"` : ''} title="${esc(title)}" aria-label="${esc(title)}">${icon(name)}</span>`;
  return `<div class="roomhead">
      <button class="roomcode" type="button" data-act="code" title="${esc(t('lobby.room.copy_code'))}">${esc(D.code || '……')}</button>
      <div class="roomhead__meta">
        ${warn ? `<span class="chip chip--badge chip--warn" title="${esc(t('lobby.room.clock_title', {has_rtt: clock.rtt_ms != null ? 'yes' : 'no', rtt: clock.rtt_ms == null ? 0 : Math.round(clock.rtt_ms)}))}">${icon('clock')}${esc(clockText(clock))}</span>` : ''}
        <span class="chip chip--badge">${esc(t('lobby.room.players', {n: players.length, has_max: D.max_players ? 'yes' : 'no', max: D.max_players || 0}))}</span>
        ${D.connected === false ? `<span class="chip chip--badge chip--warn">${esc(t('lobby.room.reconnecting'))}</span>` : ''}
      </div>
      <div class="spacer"></div>
      ${roomUrl ? `<button class="btn ${players.length <= 1 ? 'btn--cta' : 'btn--secondary'} btn--sm" type="button" data-act="invite" title="${esc(roomUrl)}">${icon('link')}<span>${esc(t('lobby.room.invite_copy'))}</span></button>
      <button class="iconbtn iconbtn--sm" type="button" data-act="share" aria-haspopup="menu" title="${esc(t('share.title'))}" aria-label="${esc(t('lobby.room.share_aria'))}">${icon('share')}</button>` : ''}
      <button class="btn btn--secondary btn--sm" type="button" data-act="leave" title="${esc(t('lobby.room.leave_title'))}">${esc(t('lobby.room.leave'))}</button>
    </div>
    <details class="disclosure disclosure--inline">
      <summary>${esc(t('lobby.room.details'))}</summary>
      <div class="disclosure__body">
        <div class="line">
          <span class="label roomoff__lbl">${esc(t('lobby.room.clock_label'))}</span>
          <span class="chip chip--badge${warn ? ' chip--warn' : err != null ? ' chip--ok' : ''}" title="${esc(t('lobby.room.clock_title', {has_rtt: clock.rtt_ms != null ? 'yes' : 'no', rtt: clock.rtt_ms == null ? 0 : Math.round(clock.rtt_ms)}))}">${icon('clock')}${esc(clockText(clock))}</span>
        </div>
        <h4 class="roomoff__head">${esc(t('lobby.room.offset.summary'))}</h4>
        <div class="line">
          <span class="label roomoff__lbl">${esc(t('lobby.room.offset.label'))}</span>
          <div class="offsetctl" data-api="room_set_offset" data-path="multi.net_offset_ms" data-min="-300" data-max="300" data-step="5"
               aria-label="${esc(t('lobby.room.offset.aria'))}"></div>
        </div>
        <div class="hint left">${esc(t('lobby.room.offset.help'))}</div>
      </div>
    </details>
    <div class="roomsong">
      <span class="roomsong__lbl">${esc(t('lobby.room.song.label'))}</span>
      ${icon('note')}
      <span class="t">${esc(song ? (song.name || t('lobby.room.song.label')) : t('lobby.room.song.none'))}</span>
      <span class="m">${song && song.duration_ms ? esc(fmt(song.duration_ms / 1000)) : ''}</span>
      ${me.has_file === false && song ? `<span class="chip chip--badge chip--warn">${esc(t('lobby.room.song.receiving'))}</span>` : ''}
      <div class="spacer"></div>
      ${host ? `<button class="btn ${song ? 'btn--secondary' : 'btn--cta'} btn--sm" type="button" data-act="song">${icon('music')}<span>${esc(song ? t('lobby.room.song.change') : t('lobby.room.song.choose'))}</span></button>` : ''}
    </div>
    ${myInstrumentRow(st)}
    <ul class="roomplayers">${players.map(p => `<li class="roomplayer${p.connected === false ? ' is-off' : ''}">
        ${personHtml(p, 'avatar avatar--sm')}
        <span class="nm">${esc(p.name || t('lobby.room.player_n', {id: p.id}))}</span>
        <span class="ins" title="${esc(instrumentName(st, p.instrument) || t('lobby.room.instrument_unknown'))}">${instrumentBadgeHtml(st, p.instrument)}</span>
        <span class="bdg">${p.host ? badge(t('lobby.room.badge.host'), 'host', 'crown') : ''}${p.ready ? badge(t('lobby.room.badge.ready'), 'ok', 'check') : ''}${p.have_song === false ? badge(t('lobby.room.badge.file_pending'), 'wait', 'download') : ''}${p.connected === false ? badge(t('lobby.room.badge.disconnected'), 'off', 'offline') : ''}</span>
      </li>`).join('')}</ul>
    ${players.length <= 1 ? `<p class="hint left">${esc(t('lobby.room.alone_hint'))}</p>` : ''}
    ${typeof orchestraHtml === 'function' ? orchestraHtml(st, D) : ''}
    ${D.error ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(D.error)}</div></div>` : ''}
    <div class="gamebtn roomcta">${main}${hint ? `<span class="hint">${esc(hint)}</span>` : ''}</div>`;
}

// ------------------------------------------------ Orchestre : parties par siège (page du salon)
// D.song.tracks = [{index, name, notes, low, high, mean, drums}] (envoyé par le chef avec le morceau) ;
// D.parts = {enabled, parts: {"<id siège>": {tracks: [index], octave: int|null}}} | null.
// Le chef coche les pistes de chacun et règle l'octave ; les invités voient la répartition.
const ORCH_MIN_VERSION = [2, 1, 0];
function orchVersionOk(v){
  const n = String(v || '').split(/[.-]/).map(x => parseInt(x, 10) || 0);
  for(let i = 0; i < 3; i++){ if((n[i] || 0) !== ORCH_MIN_VERSION[i]) return (n[i] || 0) > ORCH_MIN_VERSION[i]; }
  return true;
}
function orchTrackName(tr){ return (tr.name && String(tr.name).trim()) || t('music.tracks.track_n', {n: Number(tr.index) + 1}); }
function orchSpec(D){
  // copie modifiable de la répartition en cours (toujours envoyée en entier)
  const p = D.parts || {};
  const parts = {};
  Object.entries(p.parts || {}).forEach(([k, v]) => { parts[k] = {tracks: (v.tracks || []).slice(), octave: v.octave == null ? null : v.octave}; });
  return {enabled: !!p.enabled, parts};
}
function orchestraHtml(st, D){
  const song = D.song;
  if(!song) return '';
  const tracks = (song.tracks || []).filter(tr => Number(tr.notes) > 0);
  const host = !!(D.me && D.me.host);
  const on = !!(D.parts && D.parts.enabled);
  const head = `<div class="orch__head"><h4>${icon('users')}<span>${esc(t('lobby.orch.title'))}</span></h4>
      ${host && tracks.length >= 2 ? `<label class="switch"><input type="checkbox" data-orch="toggle"${on ? ' checked' : ''}><span class="switch__track"></span><span>${esc(t('lobby.orch.enable'))}</span></label>` : ''}
      <div class="spacer"></div>
      ${host && tracks.length >= 2 ? `<button class="btn btn--secondary btn--sm" type="button" data-orch="auto">${icon('refresh')}<span>${esc(t('lobby.orch.auto'))}</span></button>` : ''}
    </div>`;
  if(tracks.length < 2){
    return `<section class="orch">${head}<p class="hint left">${esc(t('lobby.orch.single_track'))}</p></section>`;
  }
  if(!on){
    return `<section class="orch">${head}<p class="hint left">${esc(host ? t('lobby.orch.off_host') : t('lobby.orch.off_guest'))}</p></section>`;
  }
  const parts = (D.parts && D.parts.parts) || {};
  const rows = (D.players || []).map(p => {
    const part = parts[String(p.id)] || {tracks: [], octave: null};
    const old = !orchVersionOk(p.version);
    const chips = tracks.map(tr => {
      const sel = (part.tracks || []).includes(Number(tr.index));
      const label = orchTrackName(tr) + (tr.drums ? ' · ' + t('music.tracks.drums') : '');
      return host
        ? `<button type="button" class="chip orch__chip${sel ? ' active' : ''}" aria-pressed="${sel}" data-orch="track" data-seat="${p.id}" data-track="${Number(tr.index)}">${esc(label)}</button>`
        : (sel ? `<span class="chip chip--badge">${esc(label)}</span>` : '');
    }).join('');
    const oct = part.octave == null ? 'auto' : String(part.octave);
    const octCtl = host
      ? `<select class="sortsel orch__oct" data-orch="octave" data-seat="${p.id}" aria-label="${esc(t('lobby.orch.octave_aria', {name: p.name || ''}))}">
          ${[['auto', t('lobby.orch.octave_auto')], ['-1', '−1'], ['0', '0'], ['1', '+1']].map(([v, l]) => `<option value="${v}"${v === oct ? ' selected' : ''}>${esc(t('lobby.orch.octave', {value: l}))}</option>`).join('')}
        </select>`
      : (part.octave == null ? '' : `<span class="chip chip--badge">${esc(t('lobby.orch.octave', {value: (part.octave > 0 ? '+' : '') + part.octave}))}</span>`);
    const none = !(part.tracks || []).length;
    return `<li class="orch__row${p.id === (D.me || {}).id ? ' is-me' : ''}">
        <span class="orch__who">${personHtml(p, 'avatar avatar--sm')}<span class="nm">${esc(p.name || t('lobby.room.player_n', {id: p.id}))}</span>
          <span class="ins">${instrumentBadgeHtml(st, p.instrument)}</span></span>
        <span class="orch__tracks">${chips}${none && !host ? `<span class="hint">${esc(t('lobby.orch.plays_all'))}</span>` : ''}</span>
        ${octCtl}
        ${old ? `<span class="chip chip--badge chip--warn" title="${esc(t('lobby.orch.old_title'))}">${esc(t('lobby.orch.old'))}</span>` : ''}
      </li>`;
  }).join('');
  return `<section class="orch">${head}
      <p class="hint left">${esc(host ? t('lobby.orch.help_host') : t('lobby.orch.help_guest'))}</p>
      <ul class="orch__list">${rows}</ul></section>`;
}
function orchestraWire(box){
  const act = () => { const R = roomInfo(S); return R && R.room ? R.room : null; };
  box.querySelectorAll('[data-orch]').forEach(el => {
    const kind = el.dataset.orch;
    const handler = () => {
      const D = act();
      if(!D) return;
      if(kind === 'auto'){ api('room_propose_parts'); return; }
      const spec = orchSpec(D);
      if(kind === 'toggle'){
        spec.enabled = el.checked;
        if(el.checked && !Object.keys(spec.parts).length){ api('room_propose_parts'); return; }
      } else {
        const sid = String(el.dataset.seat);
        const part = spec.parts[sid] || (spec.parts[sid] = {tracks: [], octave: null});
        if(kind === 'track'){
          const i = Number(el.dataset.track);
          part.tracks = part.tracks.includes(i) ? part.tracks.filter(x => x !== i) : part.tracks.concat([i]).sort((a, b) => a - b);
        } else if(kind === 'octave'){
          part.octave = el.value === 'auto' ? null : Number(el.value);
        }
      }
      api('room_set_parts', spec);
    };
    if(el.tagName === 'SELECT' || el.type === 'checkbox') el.onchange = handler; else el.onclick = handler;
  });
}

// ------------------------------------------------ actions du panneau
function roomWire(box){
  box.querySelectorAll('[data-act]').forEach(b => {
    b.onclick = () => {
      const R = roomInfo(S), D = R ? R.room : null;
      switch(b.dataset.act){
        case 'account': accountPanel(); break;
        case 'update': openSettings(null, 'about'); break;
        case 'refresh': api('online_refresh'); break;
        case 'create': api('room_create'); break;
        case 'join': {
          const inp = box.querySelector('.roomcode__in');
          const c = normRoomCode(inp ? inp.value : '');
          if(c.length !== 6){ toast(t('lobby.join.code_length'), 'warn'); if(inp) inp.focus(); return; }
          ROOMUI.code = c;
          // vérification rapide avant de se connecter : code inconnu ou salon plein -> message clair
          api('room_exists', c).then(r => {
            if(r && r.ok && r.valid && !r.exists){ toast(t('lobby.join.not_found', {code: c}), 'warn'); return; }
            if(r && r.ok && r.exists && r.full){ toast(t('lobby.join.full', {code: c}), 'warn'); return; }
            api('room_join', c);
          });
          break;
        }
        case 'leave': ROOMUI.code = ''; api('room_leave'); break;
        case 'code': copyText(D && D.code, t('lobby.room.code_copied')); break;
        case 'invite': copyText((S.online && S.online.room_url) || '', t('lobby.room.invite_copied')); break;
        case 'share': {
          const url = (S.online && S.online.room_url) || '';
          shareMenu({anchor: b, url, text: t('share.room_text', {code: (D && D.code) || ''}), copyLabel: t('lobby.room.invite_copy')});
          break;
        }
        case 'ready': api('room_ready', !(D && D.me && D.me.ready)); break;
        case 'start': api('room_start'); break;
        case 'cancel': api('room_cancel'); break;
        case 'stop': api('stop'); break;
        case 'song': openSongPicker(b); break;
        case 'inst': openInstrumentSelector(); break;
      }
    };
  });
  const inp = box.querySelector('.roomcode__in');
  if(inp){
    inp.oninput = () => { const c = normRoomCode(inp.value); if(inp.value !== c) inp.value = c; ROOMUI.code = c; };
    inp.onkeydown = e => { e.stopPropagation(); if(e.key === 'Enter'){ const j = box.querySelector('[data-act="join"]'); if(j) j.click(); } };
  }
}

// appele par music.js (renderTogether) a chaque rendu : formulaire « creer / rejoindre » dans la carte
// Salon en ligne tant qu'on n'est dans aucun salon, page du salon (#roomBox) des qu'on y est.
function roomPanel(st){
  const box = $('roomBox'), jbox = $('roomJoinBox');
  if(!box || !jbox) return;
  const o = st.online || null;
  const R = roomInfo(st);
  const D = R ? R.room : null;
  const logged = !!(o && o.logged_in);
  const inRoom = !!(D && D.code) && R.state !== 'idle';
  const clock = (D && D.clock) || {};
  const sig = JSON.stringify([!!o, logged, o && o.server_ok, o && o.client_too_old, R && R.state, R && R.message, inRoom,
    D && D.code, D && D.state, D && D.connected, D && D.error, D && D.last_room, D && D.can_start, D && D.start_blocker,
    D && D.song && [D.song.name, D.song.duration_ms, D.song.sha256, (D.song.tracks || []).length], D && D.me, D && D.max_players,
    D && (D.players || []).map(p => [p.id, p.name, p.instrument, p.host, p.connected, p.have_song, p.ready, p.version]),
    D && D.parts, D && D.my_part,
    clock.err_ms == null ? null : Math.round(clock.err_ms), clock.rtt_ms == null ? null : Math.round(clock.rtt_ms),
    st.instrument, st.instrument_id, (st.instruments || []).length, (st.hotkeys || {}).play_pause, o && o.room_url, I18N.lang]);
  if(!changed(box, sig)) return;
  const typing = document.activeElement && document.activeElement.classList
    && document.activeElement.classList.contains('roomcode__in');
  if(inRoom){
    if(jbox.innerHTML) jbox.innerHTML = '';
    box.innerHTML = roomViewHtml(st, R, D, st.hotkeys);
    const sb = box.querySelector('[data-act="start"]');
    if(sb) setAction(sb, {disabled: !D.can_start, reason: D.start_blocker || ''});
    roomWire(box);
    orchestraWire(box);
    const oc = box.querySelector('.offsetctl');
    if(oc){
      const m = (st.settings && st.settings.multi) || {};
      offsetCtl(oc, (D.net_offset_ms != null ? D.net_offset_ms : m.net_offset_ms) || 0);
    }
  } else {
    box.innerHTML = '';
    jbox.innerHTML = roomJoinHtml(st, o, logged);
    roomWire(jbox);
    if(typing){
      const inp = jbox.querySelector('.roomcode__in');
      if(inp){ inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
    }
  }
}

// ------------------------------------------------ barre de groupe (#groupBar)
// Visible dans la bibliotheque et « Decouvrir » des qu'on est dans un salon ou que la synchro par le son est
// activee : on voit toujours avec qui on joue, quel morceau, et on agit sans changer de page.
function groupBar(st, mode, session){
  const bar = $('groupBar');
  if(!bar) return;
  const R = roomInfo(st);
  const D = R ? R.room : null;
  const inRoom = mode === 'room' && !!(D && D.code);
  const show = (inRoom || mode === 'audio') && MUSIC_VIEW !== 'together';
  const hk = st.hotkeys || {};
  const sig = JSON.stringify([show, mode, session, R && R.state, R && R.message, D && D.code, D && D.state,
    D && D.song && D.song.name, D && D.me, D && D.can_start, D && D.start_blocker, D && D.my_part,
    D && (D.players || []).map(p => [p.id, p.name, p.avatar, p.connected]),
    ((st.settings || {}).multi || {}).player_id, hk.play_pause, MUSIC_VIEW, I18N.lang]);
  if(!changed(bar, sig)) return;
  bar.hidden = !show;
  if(!show){ bar.innerHTML = ''; return; }
  const f6 = `<kbd>${esc(hk.play_pause || 'F6')}</kbd>`;
  const open = `<button class="btn btn--secondary btn--sm" type="button" data-gb="open">${esc(t('lobby.bar.open'))}${icon('chevron-right')}</button>`;
  if(!inRoom){
    const pid = ((st.settings || {}).multi || {}).player_id || 1;
    bar.innerHTML = `<span class="groupbar__what">${icon('users')}${esc(t('music.together.audio.label'))}</span>
      <span class="groupbar__part">${esc(t('lobby.bar.player_no', {n: pid}))}</span>
      <div class="spacer"></div>${open}
      <button class="btn btn--ghost btn--sm" type="button" data-gb="audio_off">${esc(t('music.together.audio_off'))}</button>`;
  } else {
    const players = D.players || [];
    const faces = players.slice(0, 5).map(p => personHtml(p, 'avatar avatar--sm')).join('')
      + (players.length > 5 ? `<span class="avatar avatar--sm avatar--ini">+${players.length - 5}</span>` : '');
    const host = !!(D.me && D.me.host);
    let act = '';
    if(!session && D.state === 'lobby'){
      const blocked = host && !D.can_start;
      const label = host ? t('music.together.start_session') : (D.me && D.me.ready ? t('lobby.room.ready_cancel') : t('lobby.room.ready'));
      act = `<button class="btn ${host || !(D.me && D.me.ready) ? 'btn--cta' : 'btn--secondary'} btn--sm" type="button" data-gb="main"${blocked ? ' disabled' : ''}
        title="${esc(blocked ? (D.start_blocker || '') : '')}">${icon(host ? 'play' : 'check')}<span>${esc(label)}</span>${f6}</button>`;
    }
    const part = D.my_part ? `<span class="groupbar__part">${icon('note')}${esc(D.my_part)}</span>` : '';
    bar.innerHTML = `<span class="groupbar__what">${icon('globe')}${esc(t('lobby.bar.room'))}</span>
      <button class="groupbar__code" type="button" data-gb="code" title="${esc(t('lobby.room.copy_code'))}">${esc(D.code)}</button>
      <span class="groupbar__faces" title="${esc(players.map(p => p.name || '').join(', '))}">${faces}</span>
      <span class="groupbar__song">${icon('music')}<b>${esc(D.song ? (D.song.name || '') : t('lobby.room.song.none'))}</b></span>
      ${part}
      ${session || D.state !== 'lobby' ? `<span class="groupbar__part">${esc(R.message || '')}</span>` : ''}
      <div class="spacer"></div>${act}${open}
      <button class="btn btn--ghost btn--sm" type="button" data-gb="leave">${esc(t('lobby.room.leave'))}</button>`;
  }
  bar.querySelectorAll('[data-gb]').forEach(b => b.onclick = () => {
    const x = b.dataset.gb;
    if(x === 'open') showMusicView('together');
    else if(x === 'leave') api('room_leave');
    else if(x === 'audio_off') setPlayMode('solo');
    else if(x === 'main') api('play_game');
    else if(x === 'code'){ const r = roomInfo(S); copyText(r && r.room && r.room.code, t('lobby.room.code_copied')); }
  });
}

// ------------------------------------------------ selecteur de morceau du salon (panneau)
// Deux onglets : la bibliotheque locale (un morceau local est televerse pour le salon) et « Decouvrir » (morceau
// partage). Choisir ferme le panneau et laisse l'utilisateur ou il etait : plus de detour par « Decouvrir ».
const PICK = {tab: 'library', q: ''};
function openSongPicker(opener){
  PICK.q = '';
  openPanel({title: t('lobby.picker.title'), wide: true, opener, html: pickerHtml(S), render: pickerHtml, wire: pickerWire});
}
function pickerOpen(){ return !!(PANEL && PANEL.render === pickerHtml && panelOpen()); }
function pickerHtml(st){
  const online = !!(st && st.online && st.online.server_ok !== false);
  const lib = PICK.tab === 'library';
  return `<div class="seg picker__tabs" role="tablist">
      <button type="button" role="tab" data-pt="library" class="${lib ? 'active' : ''}" aria-selected="${lib}">${esc(t('shell.music.library'))}</button>
      <button type="button" role="tab" data-pt="discover" class="${lib ? '' : 'active'}" aria-selected="${!lib}"${online ? '' : ' disabled'}>${esc(t('shell.music.discover'))}</button>
    </div>
    <label class="search picker__search">${icon('search')}
      <input id="pickQ" value="${esc(PICK.q)}" placeholder="${esc(lib ? t('shell.music.search_ph') : t('shell.discover.search_ph'))}" aria-label="${esc(t('shell.music.search_aria'))}"></label>
    <div class="picker__list" id="pickList">${pickerListHtml(st)}</div>
    <p class="hint left">${esc(lib ? t('lobby.picker.library_hint') : t('lobby.picker.discover_hint'))}</p>`;
}
function pickerListHtml(st){
  const D = ((roomInfo(st) || {}).room) || {};
  const curSha = D.song && D.song.sha256;
  if(PICK.tab === 'library'){
    const q = norm(PICK.q);
    const rows = (st.songs || []).filter(s => !q || norm(s.name).includes(q) || norm(s.file).includes(q))
      .sort((a, b) => (b.fav - a.fav) || I18N.compare(a.name, b.name));
    if(!rows.length) return `<p class="hint left">${esc(st.songs && st.songs.length ? t('music.library.empty.no_match') : t('lobby.picker.library_empty'))}</p>`;
    return rows.map(s => `<button type="button" class="pickrow${curSha && s.sha256 === curSha ? ' is-current' : ''}" data-sid="${esc(s.id)}">
        ${icon(s.fav ? 'star-fill' : 'music')}<span class="t">${esc(s.name)}</span><span class="m">${esc(fmt(s.duration))}</span></button>`).join('');
  }
  const lib = (st.online && st.online.library) || {};
  const items = lib.items || [];
  if(!items.length) return `<p class="hint left">${esc(lib.loading ? t('online.discover.loading') : t('online.discover.empty_prompt'))}</p>`;
  return items.map(it => `<button type="button" class="pickrow" data-oid="${esc(it.id)}">
      ${icon('globe')}<span class="t">${esc(it.title || t('online.discover.untitled'))}</span><span class="m">${esc(it.duration_s ? fmt(it.duration_s) : '')}</span></button>`).join('');
}
function pickerWire(box){
  box.querySelectorAll('[data-pt]').forEach(b => b.onclick = () => {
    PICK.tab = b.dataset.pt; PICK.q = '';
    if(PICK.tab === 'discover' && typeof onlineSearchNow === 'function'){ ONL.q = ''; onlineSearchNow(1); }
    refreshPanel();
    const q = $('pickQ'); if(q) q.focus();
  });
  const q = $('pickQ');
  if(q){
    let timer = null;
    q.oninput = () => {
      PICK.q = q.value;
      if(PICK.tab === 'library'){ html('pickList', pickerListHtml(S)); pickerWireRows(box); }
      else { clearTimeout(timer); timer = setTimeout(() => { ONL.q = PICK.q; onlineSearchNow(1); }, 300); }
    };
    q.onkeydown = e => { e.stopPropagation(); if(e.key === 'Escape') closePanel(); };
  }
  pickerWireRows(box);
}
function pickerChosen(spec){
  api('room_set_song', spec);
  closePanel();
  toast(t('online.discover.proposed_to_room'), 'ok');
}
function pickerWireRows(box){
  box.querySelectorAll('[data-sid]').forEach(b => b.onclick = () => pickerChosen(b.dataset.sid));
  box.querySelectorAll('[data-oid]').forEach(b => b.onclick = () => pickerChosen(Number(b.dataset.oid)));
}
// la liste suit l'etat (resultats en ligne, bibliotheque qui change) sans toucher au champ de saisie
view('songPicker', {sig: st => pickerOpen() ? JSON.stringify([PICK.tab, PICK.q, (st.songs || []).length,
  ((st.online || {}).library || {}).items, ((st.online || {}).library || {}).loading,
  ((((roomInfo(st) || {}).room) || {}).song || {}).sha256]) : 'closed',
  draw: st => { if(pickerOpen()){ html('pickList', pickerListHtml(st)); pickerWireRows($('panelBody')); } }});

// ------------------------------------------------ bandeau de session (#musicSession) : compte a rebours et lecture
// Rendu par music.js (renderSession) : meme composant que le Multi audio et le dessin.
function roomSessionSpec(st, R, hk){
  const D = R && R.room ? R.room : null;
  if(!D) return null;
  hk = hk || {};
  const host = !!(D.me && D.me.host);
  const code = D.code ? t('lobby.session.room_code', {code: D.code}) : t('lobby.session.room');
  const left = R.seconds_left;
  const players = D.players || [];
  const stopKey = hk.stop || 'F7';
  if(R.state === 'downloading'){
    return {countIcon: 'download', role: t('lobby.session.file_role'), text: R.message || t('lobby.session.downloading'),
            meta: code, actions: [{label: t('lobby.session.leave'), api: 'room_leave', cls: 'btn--secondary'}]};
  }
  if(R.state === 'armed' || D.state === 'countdown'){
    return {count: left != null ? (left < 10 ? left.toFixed(1) : Math.ceil(left)) : '…', unit: 's',
            role: host ? t('lobby.session.host_role') : t('lobby.session.room'),
            text: R.message || t('lobby.session.starting'),
            meta: t('lobby.session.meta', {code: D.code || '', n: players.length, clock: clockText(D.clock)}),
            actions: host ? [{label: t('lobby.session.cancel_all'), api: 'room_cancel'}]
                          : [{label: t('common.cancel'), kbd: stopKey, api: 'stop', cls: 'btn--secondary'}]};
  }
  if(R.state === 'lobby' && D.rejoin_pos != null){
    // le salon joue encore sans nous (arret par erreur) : on reprend la ou en sont les autres
    const dur = D.song && D.song.duration_ms ? D.song.duration_ms / 1000 : 0, pos = Math.min(D.rejoin_pos, dur || D.rejoin_pos);
    return {role: t('lobby.session.rejoin_role'), text: (D.song && D.song.name) || '',
            meta: `${code} · ${t('lobby.session.rejoin_meta', {key: hk.play_pause || 'F6'})}`,
            progress: {pct: dur ? pos / dur * 100 : 0, left: fmt(pos), right: fmt(dur)},
            actions: [{label: t('lobby.session.rejoin_btn'), icon: 'play', kbd: hk.play_pause || 'F6', api: 'room_rejoin', cls: 'btn--cta'}]};
  }
  if(R.state === 'playing'){
    const dur = st.duration || 0, pos = Math.min(st.position || 0, dur);
    const cur = st.songs && st.songs[st.current];
    return {live: st.state === 'playing', role: host ? t('lobby.session.in_game_host') : t('lobby.session.in_game'),
            text: (D.song && D.song.name) || (cur ? cur.name : ''),
            meta: `${code} · ${host ? t('lobby.session.stop_all_hint', {key: stopKey}) : t('lobby.session.stop_me_hint')}`,
            progress: {pct: dur ? pos / dur * 100 : 0, left: fmt(pos), right: fmt(dur)},
            actions: host ? [{label: t('lobby.session.stop_all'), kbd: stopKey, api: 'room_stop'},
                             {label: t('lobby.session.stop_me'), api: 'room_stop_local', cls: 'btn--secondary'}]
                          : [{label: t('action.stop'), kbd: stopKey, api: 'stop'}]};
  }
  return null;
}
