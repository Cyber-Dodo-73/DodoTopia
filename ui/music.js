// DodoTopia : onglet Musique (instruments, clavier, bibliotheque, lecteur, mode Solo/Multi).
function renderInstruments(st){
  const box = $('instruments');
  if(box.dataset.built !== '1'){
    box.innerHTML = '';
    st.instruments.forEach((ins, i) => {
      const el = document.createElement('button');
      el.type = 'button'; el.setAttribute('role', 'radio');
      el.className = 'inst';
      const shape = ins.id === 'piano' ? 'piano' : 'round';
      el.innerHTML = `<span class="k ${shape}">1<span>DO</span></span>${cap(ins.name)}`;
      el.onclick = () => api('set_instrument', i);
      box.appendChild(el);
    });
    box.dataset.built = '1';
  }
  segMark(box, el => [...box.children].indexOf(el) === st.instrument);
}
view('instruments', {sig: st => st.instruments.map(i => i.id).join(',') + '#' + st.instrument, draw: renderInstruments});

function renderKeyboard(st){
  const ins = st.instruments[st.instrument];
  const kb = $('keyboard');
  if(kb.dataset.sig === ins.id) return;
  kb.innerHTML = '';
  const chrom = ins.kind === 'chromatique';
  const perRow = chrom ? 12 : 5;
  let row = null;
  ins.keys.forEach((k, i) => {
    if(i % perRow === 0){ row = document.createElement('div'); row.className = 'krow'; kb.appendChild(row); }
    const el = document.createElement('div');
    const black = chrom && [1,3,6,8,10].includes(i % 12);
    el.className = 'kk ' + (ins.id === 'piano' ? 'piano' : 'round') + (black ? ' black' : '');
    el.textContent = k;
    el.title = chrom ? NOTE_NAMES[i%12] : '';
    row.appendChild(el);
  });
  kb.dataset.sig = ins.id;
}
view('keyboard', {sig: st => st.instruments[st.instrument].id, draw: renderKeyboard});

// ------------------------------------------------ bibliotheque
const LIB = {q: '', fav: false, sort: 'name'};
try{ LIB.fav = localStorage.getItem('lib.fav') === '1'; LIB.sort = localStorage.getItem('lib.sort') || 'name'; }catch(e){}
function libSave(){ try{ localStorage.setItem('lib.fav', LIB.fav ? '1' : '0'); localStorage.setItem('lib.sort', LIB.sort); }catch(e){} }
function norm(s){ return String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
function visibleSongs(st){
  let rows = st.songs.slice();
  if(LIB.fav) rows = rows.filter(s => s.fav);
  if(LIB.q){ const q = norm(LIB.q); rows = rows.filter(s => norm(s.name).includes(q) || norm(s.file).includes(q)); }
  const cmp = {
    name:   (a, b) => a.name.localeCompare(b.name, 'fr', {sensitivity:'base'}),
    added:  (a, b) => (b.added||0) - (a.added||0),
    plays:  (a, b) => (b.plays||0) - (a.plays||0) || a.name.localeCompare(b.name, 'fr'),
    recent: (a, b) => (b.last_played||0) - (a.last_played||0),
  }[LIB.sort] || ((a, b) => 0);
  rows.sort((a, b) => (b.fav - a.fav) || cmp(a, b));   // favoris toujours en tete
  return rows;
}
function ago(ts){
  if(!ts) return '';
  const d = (Date.now()/1000 - ts);
  if(d < 3600) return "à l'instant";
  if(d < 86400) return `il y a ${Math.floor(d/3600)} h`;
  if(d < 86400*30) return `il y a ${Math.floor(d/86400)} j`;
  return new Date(ts*1000).toLocaleDateString('fr-FR');
}
function startRename(el, s){
  const main = el.querySelector('.row__main');
  if(!main || el.querySelector('input.rename')) return;
  const inp = document.createElement('input');
  inp.className = 'rename'; inp.value = s.name; inp.maxLength = 120; inp.setAttribute('aria-label', 'Nouveau nom');
  main.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const finish = (save) => {
    if(done) return; done = true;
    const v = inp.value.trim();
    inp.replaceWith(main);              // la liste redevient rafraichissable
    $('list').dataset.sig = '';
    if(save && v && v !== s.name) api('rename_song', s.id, v); else if(S) render(S);
    main.focus();
  };
  inp.onkeydown = e => { e.stopPropagation(); if(e.key === 'Enter') finish(true); if(e.key === 'Escape') finish(false); };
  inp.onblur = () => finish(true);
  inp.onclick = e => e.stopPropagation(); inp.ondblclick = e => e.stopPropagation();
}

function renderSongs(st){
  const list = $('list');
  txt('count', String(st.songs.length));
  $('favFilter').classList.toggle('active', LIB.fav);
  $('favFilter').setAttribute('aria-pressed', LIB.fav ? 'true' : 'false');
  txt('favFilter', LIB.fav ? '★ Favoris' : '★');
  if($('sortSel').value !== LIB.sort) $('sortSel').value = LIB.sort;
  if(list.querySelector('input.rename')) return;          // renommage en cours : on ne touche pas la liste
  if(!st.songs.length){
    // bibliotheque vide : carte d'accueil en 3 etapes
    if(list.dataset.sig === 'welcome') return;
    list.dataset.sig = 'welcome';
    const hk = st.hotkeys || {};
    list.innerHTML = `<div class="welcome"><div class="big" style="font-size:36px">🎵</div><h3>Bienvenue dans DodoTopia</h3>
      <p>Trois étapes pour jouer une musique dans Heartopia :</p>
      <ol class="steps">
        <li><span class="n">1</span>Importe un fichier <b>&nbsp;.mid</b></li>
        <li><span class="n">2</span>Choisis l'instrument ouvert dans le jeu</li>
        <li><span class="n">3</span>Dans Heartopia, appuie sur <kbd style="margin-left:6px">${esc(hk.play_pause || 'F6')}</kbd></li>
      </ol>
      <button class="btn btn--primary" type="button" id="btnImportWelcome">＋ Importer une musique</button></div>`;
    list.querySelector('#btnImportWelcome').onclick = () => api('import_dialog');
    return;
  }
  const rows = visibleSongs(st);
  const shareOn = !!(st.online && st.online.logged_in);
  const sig = rows.map(s => s.id + s.name + (s.fav?1:0) + s.plays + (s.online_id ? 'O' : '')).join('|') + '#' + st.current + '#' + st.state + st.target + '#' + LIB.q + LIB.fav + LIB.sort + '#' + (shareOn ? 1 : 0);
  if(list.dataset.sig === sig) return;
  list.dataset.sig = sig;
  list.innerHTML = '';
  if(!rows.length){
    list.innerHTML = `<div class="empty"><div class="big">${LIB.fav && !LIB.q ? '☆' : '🔍'}</div>${LIB.fav && !LIB.q ? 'Aucun favori pour le moment.<br>Clique sur l\'étoile d\'une musique.' : 'Aucune musique ne correspond.'}</div>`;
    return;
  }
  rows.forEach((s, pos) => {
    const i = s.index;
    const el = document.createElement('div');
    const active = i === st.current;
    const playing = active && st.state === 'playing';
    el.className = 'row' + (active ? ' active' : '') + (playing ? ' playing' : '');
    const meta = [fmt(s.duration), s.plays ? `${s.plays} écoute${s.plays > 1 ? 's' : ''}` : 'jamais écoutée', LIB.sort === 'added' ? 'ajoutée ' + ago(s.added) : (LIB.sort === 'recent' && s.last_played ? ago(s.last_played) : '')].filter(Boolean).join(' · ');
    el.innerHTML = `<button class="row__main" type="button" aria-pressed="${active ? 'true' : 'false'}" title="${esc(s.name)}">
        <span class="n${pos >= 99 ? ' small' : ''}">${playing ? '♪' : pos+1}</span>
        <span class="tt"><span class="t">${esc(s.name)}</span><span class="m">${esc(meta)}</span></span>
      </button>
      <div class="row__actions">
        <button class="row__act e" type="button" title="Renommer" aria-label="Renommer">✎</button>
        <button class="row__act sh${s.online_id ? ' on' : ''}" type="button" ${shareOn ? '' : 'disabled'} title="${s.online_id ? 'Déjà partagée en ligne' : (shareOn ? 'Partager en ligne' : 'Connecte-toi dans l’onglet En ligne pour partager')}" aria-label="Partager en ligne">${s.online_id ? '☁✓' : '☁'}</button>
        <button class="row__act p" type="button" title="Écouter ici" aria-label="Écouter ici">▶</button>
        <button class="row__act x" type="button" title="Retirer" aria-label="Retirer">×</button>
        <button class="row__act star${s.fav ? ' on' : ''}" type="button" aria-pressed="${s.fav ? 'true' : 'false'}" title="${s.fav ? 'Retirer des favoris' : 'Ajouter aux favoris'}" aria-label="${s.fav ? 'Retirer des favoris' : 'Ajouter aux favoris'}">${s.fav ? '★' : '☆'}</button>
      </div>`;
    const main = el.querySelector('.row__main');
    main.onclick = () => api('select_song', i);
    main.ondblclick = e => { if(e.target.closest('.t')) startRename(el, s); else api('preview', i); };
    el.querySelector('.e').onclick = e => { e.stopPropagation(); startRename(el, s); };
    el.querySelector('.sh').onclick = e => { e.stopPropagation();
      dialog({title: s.online_id ? 'Déjà partagée' : 'Partager en ligne', icon:'☁️', ok: s.online_id ? 'Renvoyer' : 'Partager',
              html: `<b>${esc(s.name)}</b> sera envoyée au serveur DodoTopia.<br><small>Un administrateur la valide avant qu'elle apparaisse dans la bibliothèque en ligne. Ton pseudo Discord y sera associé.</small>`})
        .then(yes => { if(yes) api('online_share', s.id); }); };
    el.querySelector('.star').onclick = e => { e.stopPropagation(); api('toggle_favorite', s.id); };
    el.querySelector('.p').onclick = e => { e.stopPropagation(); api('preview', i); };
    el.querySelector('.x').onclick = e => { e.stopPropagation();
      dialog({title:'Retirer la musique', icon:'🗑️', danger:true, ok:'Retirer',
              html:`Retirer <b>${esc(s.name)}</b> de la bibliothèque ?<br><small>Le fichier d'origine n'est pas touché.</small>`})
        .then(yes => { if(yes) api('remove_song', s.id); }); };
    list.appendChild(el);
  });
}
view('songs', {draw: renderSongs});
$('search').oninput = () => { LIB.q = $('search').value; $('searchBox').classList.toggle('has', !!LIB.q); if(S) renderSongs(S); };
$('search').onkeydown = e => { e.stopPropagation(); if(e.key === 'Escape'){ $('search').value = ''; $('search').oninput(); } };
$('searchClr').onclick = () => { $('search').value = ''; $('search').oninput(); $('search').focus(); };
$('favFilter').onclick = () => { LIB.fav = !LIB.fav; libSave(); if(S) renderSongs(S); };
$('sortSel').onchange = () => { LIB.sort = $('sortSel').value; libSave(); if(S) renderSongs(S); };

function renderHotkeys(st){
  const hk = st.hotkeys;
  $('lStop').textContent = hk.stop||''; $('lNext').textContent = hk.next_song||''; $('lPrev').textContent = hk.prev_song||'';
  $('gameKey').textContent = hk.play_pause||''; $('instKey').textContent = hk.next_instrument || '';
}
view('hotkeys', {sig: st => JSON.stringify(st.hotkeys), draw: renderHotkeys});

// ------------------------------------------------ lecteur
function playMode(st){
  const m = (st.settings && st.settings.multi) || {};
  if(m.mode) return m.mode;
  return m.enabled ? 'audio' : 'solo';
}
function roomStatus(st){ return st.online && st.online.room ? st.online.room : null; }
function whenText(ts){
  if(!ts) return '';
  const d = Date.now()/1000 - ts;
  if(d < 3600) return "à l'instant";
  if(d < 86400) return `il y a ${Math.floor(d/3600)} h`;
  return new Date(ts*1000).toLocaleDateString('fr-FR');
}
function subtitle(st, cur, ins){
  let sub = `Instrument : <b>${esc(cap(ins.name))}</b>`;
  const manual = Number((st.settings || {}).transpose_semitones || 0);
  const sg = n => (n > 0 ? '+' : '') + n;
  if(st.info){
    const total = st.info.shift, auto = total - manual;
    sub += manual ? ` · transposition auto <b>${sg(auto)}</b> · manuel <b>${sg(manual)}</b>` : ` · transposition <b>${sg(total)}</b>`;
    if(st.info.snapped) sub += ` · ${st.info.snapped} notes rapprochées`;
    if(st.info.folded) sub += ` · ${st.info.folded} repliées`;
  } else if(manual){
    sub += ` · transposition auto · manuel <b>${sg(manual)}</b>`;
  }
  if(st.state !== 'stopped') sub += ` · ${fmt(Math.min(st.position || 0, st.duration || 0))} / ${fmt(st.duration || 0)}`;
  return sub;
}
// panneau Multi audio : joueur n°, avance/retard, latence, dernier calibrage
function audioPanel(st){
  const m = (st.settings && st.settings.multi) || {};
  const mu = st.multi || {};
  segMark($('playerSeg'), b => Number(b.dataset.v) === Number(m.player_id || 1));
  offsetCtl($('audioOffset'), m.offset_ms || 0);
  const c = m.calib;
  const lat = m.latency != null ? `latence mesurée ${Math.round(m.latency * 1000)} ms` : 'latence non mesurée (Réglages › Multi audio › Tester)';
  let cal;
  if(!c) cal = 'pas encore calibré ensemble';
  else if(c.role === 'leader') cal = `dernier calibrage ${whenText(c.when)} : meneur, joueurs entendus ${c.players && c.players.length ? c.players.join(', ') : 'aucun'}`;
  else if(c.rtt_ms == null) cal = `dernier calibrage ${whenText(c.when)} : pas d'écho du meneur ${c.leader}`;
  else cal = `dernier calibrage ${whenText(c.when)} : calé sur le joueur ${c.leader}, aller-retour ${c.rtt_ms} ms`;
  txt('audioInfo', `${lat} · ${cal}`);
  $('audioInfo').title = `${lat} · ${cal}`;
  $('audioInfo').hidden = !(c && m.latency != null);      // sinon la notice du bloc le dit deja
  $('btnCalib').disabled = st.state !== 'stopped' || (mu.state && mu.state !== 'idle');
}
function viewMain(st){
  const cur = st.songs[st.current];
  const ins = st.instruments[st.instrument];
  const hk = st.hotkeys || {};
  const inGame = st.state !== 'stopped' && st.target === 'game';
  const inPreview = st.state !== 'stopped' && st.target === 'preview';
  txt('title', cur ? cur.name : 'Aucune musique');
  html('sub', cur ? subtitle(st, cur, ins) : 'Importe un fichier .mid pour commencer');

  const mu = st.multi || {};
  const mode = playMode(st);
  const room = roomStatus(st);
  const syncing = mode !== 'room' && (st.state === 'sync' || (mu.state && mu.state !== 'idle' && mu.state !== 'playing'));
  const roomBusy = !!(room && ['countdown', 'armed', 'playing', 'downloading'].includes(room.state));
  const isTest = syncing && mu.state === 'test';
  const session = (syncing && !isTest) || inGame || roomBusy;

  // segmente Solo | Multi audio | Salon en ligne
  const roomBtn = $('modeChips').querySelector('[data-mode="room"]');
  roomBtn.disabled = !st.online;
  $('roomSoon').hidden = !!st.online;
  segMark($('modeChips'), c => c.dataset.mode === mode);
  $('modeChips').querySelectorAll('button').forEach(b => { if(b.dataset.mode !== 'room') b.disabled = session; });

  // pastille : etat court
  const pill = $('pill');
  let pc = 'pill', pt = 'Prêt';
  if(st.state === 'paused'){ pc = 'pill paused'; pt = '‖ En pause'; }
  else if(isTest){ pc = 'pill paused'; pt = '🔔 Test'; }
  else if(syncing){ pc = 'pill paused'; pt = mu.mode === 'calibrate' ? '🎯 Calibrage' : '👥 Écoute…'; }
  else if(roomBusy){ pc = 'pill paused'; pt = room.state === 'playing' ? '🌐 Dans le jeu' : '🌐 Salon…'; }
  else if(inGame){ pc = 'pill game'; pt = '🎮 Dans le jeu'; }
  else if(inPreview){ pc = 'pill preview'; pt = '🎧 Écoute'; }
  if(pill.className !== pc) pill.className = pc;
  txt('pill', pt);
  $('disc').classList.toggle('spin', st.state === 'playing');
  const pausing = st.state === 'playing' && inPreview;
  txt('playIcon', pausing ? '❚❚' : '▶');
  txt('playLbl', pausing ? LABELS.pause : LABELS.listen);
  $('btnPlay').setAttribute('aria-label', pausing ? LABELS.pause : LABELS.listen);
  $('btnPlay').disabled = !cur || syncing;
  $('btnStop').title = LABELS.stop;

  // appel a l'action F6 selon le mode
  const gb = $('btnGame');
  let gcls = 'btn btn--lg btn--cta', glabel;
  if(inGame && st.state === 'playing') glabel = LABELS.pause;
  else if(inGame && st.state === 'paused') glabel = LABELS.resume;
  else if(mode === 'audio') glabel = LABELS.start;
  else if(mode === 'room') glabel = LABELS.start;
  else glabel = LABELS.play;
  if(gb.className !== gcls) gb.className = gcls;
  txt('gameLabel', glabel);
  gb.disabled = !cur && mode !== 'room';
  const cd = Math.round(((st.settings || {}).multi || {}).countdown || 10);
  txt('gameHelp', mode === 'audio'
    ? `${hk.play_pause || 'F6'} lance ${cd} s d'écoute du jeu : le premier joue la note repère, les autres suivent.`
    : mode === 'room' ? `Le chef du salon lance le top départ ; chacun démarre à la même seconde.`
    : `Ouvre l'instrument dans Heartopia, puis ${hk.play_pause || 'F6'} : les touches sont envoyées au jeu.`);

  // bandeau de session (compte a rebours, ecoute, lecture dans le jeu) ou panneau du mode
  // en salon, le bouton principal est dans le panneau (Prêt / Top départ) : on n'affiche pas deux fois la même action
  const inRoom = mode === 'room' && !!(room && room.state !== 'idle' && room.room && room.room.code);
  $('modeRow').hidden = session; $('gameCta').hidden = session || inRoom; $('gameHelp').hidden = session || inRoom;
  $('modePanel').hidden = session;
  if(session){
    let spec = null;
    const left = mu.seconds_left;
    // salon en ligne : bandeau dedie (compte a rebours partage, lecture, arret pour tous) — lobby.js
    if(mode === 'room' && roomBusy && typeof roomSessionSpec === 'function') spec = roomSessionSpec(st, room, hk);
    if(spec){ /* deja rempli */ }
    else if(syncing && mu.mode === 'calibrate'){
      spec = {count: left != null ? Math.ceil(left) : '…', unit: 's', role: mu.state === 'calibrating' ? (mu.role === 'leader' ? 'Calibrage · meneur' : `Calibrage · suiveur du joueur ${mu.leader_id}`) : 'Calibrage · écoute',
              text: mu.message || 'Écoute du jeu…', meta: `${hk.stop || 'F7'} ou une touche annule`, actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'stop'}]};
    } else if(syncing){
      const role = mu.role === 'leader' ? 'Meneur' : mu.role === 'follower' ? `Suiveur du joueur ${mu.leader_id}` : 'Multi audio · écoute';
      spec = {count: left != null ? (left < 10 && mu.role ? left.toFixed(1) : Math.ceil(left)) : '…', unit: 's', role,
              text: mu.message || 'Écoute du jeu…', meta: `Reste sur Heartopia, instrument ouvert · ${hk.stop || 'F7'} ou une touche annule`,
              actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'stop'}]};
    } else if(roomBusy && room.state !== 'playing'){
      spec = {count: room.seconds_left != null ? Math.ceil(room.seconds_left) : '…', unit: 's', role: room.role === 'host' ? 'Salon · chef' : 'Salon',
              text: room.message || 'Top départ imminent…', meta: `${hk.stop || 'F7'} annule pour toi`, actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'stop'}]};
    } else {
      const dur = st.duration || 0, pos = Math.min(st.position || 0, dur);
      const role = mu.state === 'playing' ? (mu.role === 'leader' ? 'Dans le jeu · meneur' : `Dans le jeu · suiveur du joueur ${mu.leader_id}`) : roomBusy ? 'Dans le jeu · salon' : 'Dans le jeu';
      spec = {live: st.state === 'playing', count: st.state === 'paused' ? '‖' : null, role,
              text: cur ? cur.name : '', meta: st.state === 'paused' ? 'En pause' : `Une touche ou un clic gauche arrête aussi (clic droit caméra permis)`,
              progress: {pct: dur ? pos / dur * 100 : 0, left: fmt(pos), right: fmt(dur)},
              actions: [{label: st.state === 'paused' ? LABELS.resume : LABELS.pause, kbd: hk.play_pause || 'F6', api: 'play_game', cls: 'btn--secondary'},
                        {label: LABELS.stop, kbd: hk.stop || 'F7', api: 'stop'}]};
    }
    renderSession($('musicSession'), spec);
  } else {
    renderSession($('musicSession'), null);
    $('audioPanel').hidden = mode !== 'audio';
    $('roomBox').hidden = mode !== 'room';
    if(mode === 'audio') audioPanel(st);
    if(mode === 'room' && typeof roomPanel === 'function') roomPanel(st);
  }

  // notice contextuelle courte
  let notice = null;
  if(!session){
    const m = (st.settings || {}).multi || {};
    if(!cur) notice = {text: 'Importe une musique (.mid) pour commencer.', kind: 'info'};
    else if(isTest) notice = {text: mu.message || 'Test de détection en cours…', kind: 'info', icon: '🔔'};
    else if(mode === 'audio' && !m.calib) notice = {text: `Pas encore calibré : cliquez tous sur « Calibrer ensemble » en même temps, dans le jeu, instrument ouvert.`, kind: 'warn'};
    else if(mode === 'audio' && m.latency == null) notice = {text: 'Latence non mesurée : Réglages › Multi audio › Tester la détection.', kind: 'warn'};
    else if(mode === 'room' && !$('roomBox').children.length) notice = {text: 'Salon en ligne : le panneau arrive avec le client réseau.', kind: 'info', icon: '🌐'};
  }
  setNotice('musicNotice', notice);

  // erreur explicite (get_state().error) : arret anormal en danger, arret utilisateur en info pendant 12 s
  const err = st.error;
  const showErr = err && (err.kind === 'danger' || (Date.now()/1000 - (err.since || 0)) < 12) && !session;
  if(showErr){
    const cls = 'notice notice--' + (err.kind === 'danger' ? 'danger' : 'info');
    if($('musicError').className !== cls) $('musicError').className = cls;
    txt('musicErrorText', err.msg || '');
    $('musicErrorAdmin').hidden = !(st.is_admin === false && err.kind === 'danger' && err.target === 'game');
    $('musicError').hidden = false;
  } else if(!$('musicError').hidden) $('musicError').hidden = true;

  // reglages de lecture
  $('speed').disabled = !!st.speed_locked; $('spUp').disabled = !!st.speed_locked; $('spDown').disabled = !!st.speed_locked;
  const dur = st.duration || 0, pos = Math.min(st.position||0, dur);
  txt('tcur', fmt(pos)); txt('tdur', fmt(dur));
  $('fill').style.width = (dur ? (pos/dur*100) : 0) + '%';
  if(document.activeElement !== $('speed')) $('speed').value = st.speed;
  txt('speedV', 'x' + Number(st.speed).toFixed(2));
  if(document.activeElement !== $('volume')) $('volume').value = st.settings.preview_volume;
  txt('volumeV', st.settings.preview_volume + ' %');
  const tr = Number(st.settings.transpose_semitones || 0);
  txt('trV', (tr > 0 ? '+' : '') + tr);
  txt('ver', st.version ? 'v' + st.version : '');

  // barre d'etat : etat court + version
  const status = $('status');
  const scls = 'status ' + (st.state === 'playing' ? st.target : '');
  if(status.className !== scls) status.className = scls;
  let msg;
  if(TAB === 'image') msg = (st.draw && st.draw.state === 'drawing') ? 'Dessin en cours dans Heartopia' : (st.draw && st.draw.state === 'autocal') ? 'Calibrage automatique en cours' : 'Image';
  else if(TAB === 'cook') msg = (st.cook && st.cook.state === 'cooking') ? 'Cuisine en cours dans Heartopia' : 'Cuisine';
  else if(isTest) msg = 'Test de détection…';
  else if(syncing) msg = mu.mode === 'calibrate' ? 'Calibrage Multi…' : 'Multi audio : écoute du jeu…';
  else if(inGame && st.state === 'playing') msg = 'Lecture dans Heartopia';
  else if(inPreview && st.state === 'playing') msg = 'Écoute dans le logiciel (rien n\'est envoyé au jeu)';
  else if(st.state === 'paused') msg = 'En pause';
  else msg = mode === 'audio' ? 'Prêt · Multi audio' : mode === 'room' ? 'Prêt · Salon en ligne' : 'Prêt';
  txt('msg', msg);
}
view('main', {draw: viewMain});

// ------------------------------------------------ boutons
function setPlayMode(mode){
  const has = window.pywebview && window.pywebview.api.set_play_mode;
  if(has || !window.pywebview) api('set_play_mode', mode); else api('set_multi', mode === 'audio');
}
$('btnImport').onclick = () => api('import_dialog');
$('btnPlay').onclick = () => api('preview');
$('btnGame').onclick = () => api('play_game');
$('btnStop').onclick = () => api('stop');
$('btnNext').onclick = () => api('next_song');
$('btnPrev').onclick = () => api('prev_song');
$('spUp').onclick = () => api('set_speed', Math.min(4, Number($('speed').value)+0.1));
$('spDown').onclick = () => api('set_speed', Math.max(0.2, Number($('speed').value)-0.1));
$('speed').oninput = () => { $('speedV').textContent = 'x' + Number($('speed').value).toFixed(2); };
$('speed').onchange = () => api('set_speed', Number($('speed').value));
$('volume').oninput = () => { $('volumeV').textContent = $('volume').value + ' %'; };
$('volume').onchange = () => api('set_setting', 'preview_volume', Number($('volume').value));   // sans toast
function bumpTranspose(d){
  const v = Math.max(-24, Math.min(24, Number((S && S.settings && S.settings.transpose_semitones) || 0) + d));
  $('trV').textContent = (v > 0 ? '+' : '') + v;
  api('set_setting', 'transpose_semitones', v);
}
$('trUp').onclick = () => bumpTranspose(1);
$('trDown').onclick = () => bumpTranspose(-1);
$('openFolder').onclick = () => api('open_songs_folder');
$('openLog').onclick = () => api('open_draw_log');
$('openCookLog').onclick = () => api('open_cook_log');
document.querySelectorAll('#modeChips > button').forEach(c => c.onclick = () => setPlayMode(c.dataset.mode));
document.querySelectorAll('#playerSeg > button').forEach(b => b.onclick = () => { segMark($('playerSeg'), x => x === b); api('set_setting', 'multi.player_id', Number(b.dataset.v)); });
$('btnCalib').onclick = () => api('multi_calibrate');
$('btnHotkeys').onclick = () => hotkeysDialog(S);
// « Touches envoyees au jeu » : etat memorise
try{ $('keysDisc').open = localStorage.getItem('keysOpen') === '1'; }catch(e){}
$('keysDisc').ontoggle = () => { try{ localStorage.setItem('keysOpen', $('keysDisc').open ? '1' : '0'); }catch(e){} };
