// DodoTopia : panneau « Salon en ligne » du lecteur (#roomBox) et bandeau de session du salon.
// Lit st.online.room (= RoomSession.status()) : cle plate {state, role, seconds_left, message} + cle room {code,
// players, song, clock, me, can_start, start_blocker...}. Toutes les actions passent par les methodes Api
// room_create / room_join / room_leave / room_ready / room_start / room_cancel / room_stop / room_set_offset.

const ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';   // meme alphabet que room.py (sans I, O, 0, 1)
const ROOMUI = {code: ''};

function roomInfo(st){ const r = st && st.online && st.online.room; return r && r.room ? r : null; }
function normRoomCode(s){ return String(s || '').toUpperCase().split('').filter(c => ROOM_ALPHABET.indexOf(c) >= 0).join('').slice(0, 6); }
function instrumentName(st, id){
  const i = ((st && st.instruments) || []).find(x => x.id === id);
  return i ? cap(i.name) : (id ? cap(String(id)) : '');
}
function clockText(clock){
  const e = clock && clock.err_ms;
  return e == null ? 'horloge…' : '±' + Math.round(e) + ' ms';
}
// avatar Discord : image si on en a une, sinon l'initiale (avatarFallback est dans online.js)
function personHtml(p, cls){
  const name = (p && (p.name || p.username || p.global_name)) || 'Joueur';
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
    out.push(`<div class="notice notice--info"><span class="notice__ic">🌐</span><div class="notice__text">Le client réseau n'est pas disponible dans cette version.</div></div>`);
  } else if(o.server_ok === false){
    out.push(`<div class="notice notice--warn"><span class="notice__ic">⚠️</span><div class="notice__text">Serveur injoignable${o.offline_reason ? ' : ' + esc(o.offline_reason) : ''}.
      <button class="btn btn--ghost btn--sm" type="button" data-act="refresh">Réessayer</button></div></div>`);
  } else if(o.client_too_old){
    out.push(`<div class="notice notice--danger"><span class="notice__ic">⚠️</span><div class="notice__text">Mets à jour DodoTopia pour utiliser les salons.
      <button class="btn btn--ghost btn--sm" type="button" data-act="tab">Onglet En ligne</button></div></div>`);
  } else if(!logged){
    out.push(`<div class="notice notice--info"><span class="notice__ic">🌐</span><div class="notice__text">Connecte-toi dans l'onglet En ligne pour créer ou rejoindre un salon.
      <button class="btn btn--ghost btn--sm" type="button" data-act="tab">Se connecter</button></div></div>`);
  }
  const dis = blocked ? ' disabled' : '';
  out.push(`<div class="roomjoin">
      <input class="input roomcode__in" type="text" maxlength="6" spellcheck="false" autocomplete="off"
             placeholder="CODE" aria-label="Code du salon (6 caractères)" value="${esc(ROOMUI.code || last)}"${dis}>
      <button class="btn btn--secondary btn--sm" type="button" data-act="join"${dis}>Rejoindre</button>
      <div class="spacer"></div>
      <button class="btn btn--cta btn--sm" type="button" data-act="create"${dis}>＋ Créer un salon</button>
    </div>`);
  const R = roomInfo(st);
  const msg = R && R.state === 'connecting' ? 'Connexion au salon…'
    : (D && D.error) ? esc(D.error)
    : 'Code de 6 caractères. Le chef choisit la musique, chacun se met « Prêt », le chef lance le top départ.';
  out.push(`<div class="hint left">${msg}</div>`);
  return out.join('');
}

// ------------------------------------------------ panneau en salon
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
  let main;
  if(counting){
    main = host ? `<button class="btn btn--danger" type="button" data-act="cancel">${esc(LABELS.cancel)} ${f6}</button>`
                : `<button class="btn btn--secondary" type="button" data-act="stop">${esc(LABELS.cancel)} pour moi</button>`;
  } else if(host){
    main = `<button class="btn btn--cta" type="button" data-act="start"${D.can_start ? '' : ' disabled'}
             title="${esc(D.start_blocker || LABELS.start)}">🚀 ${esc(LABELS.start)} ${f6}</button>`;
  } else {
    main = `<button class="btn ${me.ready ? 'btn--secondary' : 'btn--cta'}" type="button" data-act="ready">${me.ready ? '✓ Prêt — annuler' : 'Je suis prêt'} ${f6}</button>`;
  }
  const hint = host ? (D.start_blocker || 'Tout le monde est prêt : lance le top départ.')
                    : (counting ? 'Top départ en cours…' : 'Le chef lance le top départ ; reste sur Heartopia, instrument ouvert.');
  return `<div class="roomhead">
      <button class="roomcode" type="button" data-act="code" title="Copier le code du salon">${esc(D.code || '……')}</button>
      <div class="roomhead__meta">
        <span class="chip chip--badge${warn ? ' chip--warn' : err != null ? ' chip--ok' : ''}" title="Précision de l'horloge partagée${clock.rtt_ms != null ? ' · aller-retour ' + Math.round(clock.rtt_ms) + ' ms' : ''}">🕑 ${esc(clockText(clock))}</span>
        <span class="chip chip--badge">${players.length} joueur${players.length > 1 ? 's' : ''}${D.max_players ? ' / ' + D.max_players : ''}</span>
        ${D.connected === false ? '<span class="chip chip--badge chip--warn">reconnexion…</span>' : ''}
      </div>
      <div class="spacer"></div>
      <button class="btn btn--secondary btn--sm" type="button" data-act="leave">Quitter</button>
    </div>
    <div class="line">
      <span class="label roomoff__lbl">Avance / retard</span>
      <div class="offsetctl" data-api="room_set_offset" data-path="multi.net_offset_ms" data-min="-300" data-max="300" data-step="5"
           aria-label="Avance ou retard du salon en millisecondes"></div>
    </div>
    <div class="roomsong">
      <span class="ic">♪</span>
      <span class="t">${song ? esc(song.name || 'Morceau du salon') : 'Aucun morceau choisi'}</span>
      <span class="m">${song && song.duration_ms ? esc(fmt(song.duration_ms / 1000)) : ''}</span>
      ${me.has_file === false && song ? '<span class="chip chip--badge chip--warn">réception…</span>' : ''}
      <div class="spacer"></div>
      ${host ? '<button class="btn btn--secondary btn--sm" type="button" data-act="song">Choisir un morceau</button>' : ''}
    </div>
    <ul class="roomplayers">${players.map(p => `<li class="roomplayer${p.connected === false ? ' is-off' : ''}">
        ${personHtml(p, 'avatar avatar--sm')}
        <span class="nm">${esc(p.name || ('Joueur ' + p.id))}</span>
        <span class="ins">${esc(instrumentName(st, p.instrument))}</span>
        <span class="bdg">${p.host ? '<span title="Chef du salon">👑</span>' : ''}${p.ready ? '<span class="ok" title="Prêt">✓</span>' : ''}${p.have_song === false ? '<span class="wait" title="Fichier pas encore reçu">⬇</span>' : ''}${p.connected === false ? '<span class="off" title="Déconnecté">●</span>' : ''}</span>
      </li>`).join('')}</ul>
    ${D.error ? `<div class="notice notice--warn"><span class="notice__ic">⚠️</span><div class="notice__text">${esc(D.error)}</div></div>` : ''}
    <div class="gamebtn">${main}</div>
    <div class="hint">${esc(hint)}</div>`;
}

// ------------------------------------------------ actions du panneau
function roomWire(box){
  box.querySelectorAll('[data-act]').forEach(b => {
    b.onclick = () => {
      const R = roomInfo(S), D = R ? R.room : null;
      switch(b.dataset.act){
        case 'tab': showTab('online'); break;
        case 'refresh': api('online_refresh'); break;
        case 'create': api('room_create'); break;
        case 'join': {
          const inp = box.querySelector('.roomcode__in');
          const c = normRoomCode(inp ? inp.value : '');
          if(c.length !== 6){ toast('Le code d\'un salon fait 6 caractères', 'warn'); if(inp) inp.focus(); return; }
          ROOMUI.code = c; api('room_join', c); break;
        }
        case 'leave': ROOMUI.code = ''; api('room_leave'); break;
        case 'code': copyText(D && D.code, 'Code du salon copié'); break;
        case 'ready': api('room_ready', !(D && D.me && D.me.ready)); break;
        case 'start': api('room_start'); break;
        case 'cancel': api('room_cancel'); break;
        case 'stop': api('stop'); break;
        case 'song': showTab('online'); break;
      }
    };
  });
  const inp = box.querySelector('.roomcode__in');
  if(inp){
    inp.oninput = () => { const c = normRoomCode(inp.value); if(inp.value !== c) inp.value = c; ROOMUI.code = c; };
    inp.onkeydown = e => { e.stopPropagation(); if(e.key === 'Enter'){ const j = box.querySelector('[data-act="join"]'); if(j) j.click(); } };
  }
}

// appele par music.js quand le mode « Salon » est choisi et qu'aucune session n'occupe le bloc
function roomPanel(st){
  const box = $('roomBox');
  if(!box) return;
  const o = st.online || null;
  const R = roomInfo(st);
  const D = R ? R.room : null;
  const logged = !!(o && o.logged_in);
  const inRoom = !!(D && D.code) && R.state !== 'idle';
  const clock = (D && D.clock) || {};
  const sig = JSON.stringify([!!o, logged, o && o.server_ok, o && o.client_too_old, R && R.state, R && R.message, inRoom,
    D && D.code, D && D.state, D && D.connected, D && D.error, D && D.last_room, D && D.can_start, D && D.start_blocker,
    D && D.song && [D.song.name, D.song.duration_ms], D && D.me, D && D.max_players,
    D && (D.players || []).map(p => [p.id, p.name, p.instrument, p.host, p.connected, p.have_song, p.ready]),
    clock.err_ms == null ? null : Math.round(clock.err_ms), clock.rtt_ms == null ? null : Math.round(clock.rtt_ms),
    st.instrument, (st.hotkeys || {}).play_pause]);
  if(changed(box, sig)){
    const wasTyping = document.activeElement && document.activeElement.classList
      && document.activeElement.classList.contains('roomcode__in');
    box.innerHTML = inRoom ? roomViewHtml(st, R, D, st.hotkeys) : roomJoinHtml(st, o, logged);
    roomWire(box);
    if(wasTyping){
      const inp = box.querySelector('.roomcode__in');
      if(inp){ inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
    }
  }
  const oc = box.querySelector('.offsetctl');
  if(oc){
    const m = (st.settings && st.settings.multi) || {};
    offsetCtl(oc, (D && D.net_offset_ms != null ? D.net_offset_ms : m.net_offset_ms) || 0);
  }
}

// ------------------------------------------------ bandeau de session (#musicSession) : compte a rebours et lecture
// Rendu par music.js (renderSession) : meme composant que le Multi audio et le dessin.
function roomSessionSpec(st, R, hk){
  const D = R && R.room ? R.room : null;
  if(!D) return null;
  hk = hk || {};
  const host = !!(D.me && D.me.host);
  const code = D.code ? 'Salon ' + D.code : 'Salon';
  const left = R.seconds_left;
  const players = D.players || [];
  if(R.state === 'downloading'){
    return {count: '⬇', role: 'Salon · fichier', text: R.message || 'Téléchargement du morceau du salon…',
            meta: code, actions: [{label: 'Quitter', api: 'room_leave', cls: 'btn--secondary'}]};
  }
  if(R.state === 'armed' || D.state === 'countdown'){
    return {count: left != null ? (left < 10 ? left.toFixed(1) : Math.ceil(left)) : '…', unit: 's',
            role: host ? 'Salon · chef' : 'Salon',
            text: R.message || 'Top départ : reste sur Heartopia, instrument ouvert.',
            meta: `${D.code || ''} · ${players.length} joueurs · ${clockText(D.clock)}`,
            actions: host ? [{label: 'Annuler pour tous', api: 'room_cancel'}]
                          : [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'stop', cls: 'btn--secondary'}]};
  }
  if(R.state === 'playing'){
    const dur = st.duration || 0, pos = Math.min(st.position || 0, dur);
    const cur = st.songs && st.songs[st.current];
    return {live: st.state === 'playing', role: host ? 'Dans le jeu · salon · chef' : 'Dans le jeu · salon',
            text: (D.song && D.song.name) || (cur ? cur.name : ''),
            meta: `${code} · ${host ? (hk.stop || 'F7') + ' arrête tout le monde' : "une touche ou un clic gauche t'arrête"}`,
            progress: {pct: dur ? pos / dur * 100 : 0, left: fmt(pos), right: fmt(dur)},
            actions: host ? [{label: 'Arrêter pour tous', kbd: hk.stop || 'F7', api: 'room_stop'},
                             {label: 'Arrêter pour moi', api: 'room_stop_local', cls: 'btn--secondary'}]
                          : [{label: LABELS.stop, kbd: hk.stop || 'F7', api: 'stop'}]};
  }
  return null;
}
