// DodoTopia : activite Musique (instruments, clavier, bibliotheque, lecteur, jouer a plusieurs).
// Le panneau du lecteur suit l'ordre : identite du morceau, preecoute locale, preparation et lancement
// dans le jeu, puis reglages du morceau. La vue « Decouvrir des morceaux » vit dans online.js.
// ------------------------------------------------ instrument actif
// Le choix de l'instrument vit dans instruments.js (carte #instPick, selecteur, assistant). music.js n'affiche
// plus que ce qui depend du profil actif : les touches envoyees au jeu et le diagnostic du morceau.
const MUSIC_LEGACY_IDS = {piano: 'piano', flute: 'recorder', luth: 'lute', guitare: 'lute'};
// libelles des statuts de verification : « documente par une source » n'est pas « teste dans le jeu ».
const MUSIC_STATUS_TEXT = {
  unknown: 'Touches à configurer',
  documented: 'Profil documenté · à vérifier',
  custom: 'Touches personnalisées · à vérifier',
  'quick-tested': 'Test rapide réussi · vérification partielle',
  confirmed: 'Confirmé sur cet ordinateur'};
const MUSIC_FALLBACK_INST = {id: '', name: 'Instrument', label_en: '', category: '', image: '', kind: '', keys: [],
  count: 0, layout_id: null, layout_label: '', status: 'unknown', ready: false, percussive: false, custom: false,
  blocked_reason: 'Aucun instrument disponible : ouvre « Changer » pour en choisir un.',
  lowest: 60, span: 0, aliases: [], variant_count: 0};
// instrument_id fait foi ; l'index reste accepte pour les anciens etats.
function curInstrument(st){
  const list = (st && st.instruments) || [];
  let ins = null;
  if(st && st.instrument_id) ins = list.find(x => x && x.id === st.instrument_id) || null;
  if(!ins && st && typeof st.instrument === 'number') ins = list[st.instrument] || null;
  return ins || list[0] || MUSIC_FALLBACK_INST;
}
function instrumentReady(st){
  const ins = curInstrument(st);
  return (st && st.instrument_ready !== undefined) ? !!st.instrument_ready : !!ins.ready;
}
function instrumentBlockedText(st){
  return (st && st.instrument_blocked) || curInstrument(st).blocked_reason
    || 'Les touches de cet instrument ne sont pas configurées.';
}
function instrumentStatusText(ins){ return MUSIC_STATUS_TEXT[ins && ins.status] || MUSIC_STATUS_TEXT.unknown; }
// « Configurer les touches » : l'assistant appartient a instruments.js ; repli si le module manque.
function openInstrumentConfig(id){
  if(typeof openInstrumentWizard === 'function') return openInstrumentWizard(id, 'setup');
  if(typeof openKeysPanel === 'function') return openKeysPanel(id);
  if(typeof openInstrumentSelector === 'function') return openInstrumentSelector(id);
  toast('Ouvre « Changer » pour configurer les touches de cet instrument.', 'info');
}
// appel facultatif : renvoie null si la methode n'existe pas cote Python, sans casser l'interface.
function apiOpt(name, ...args){
  try{
    if(!window.pywebview || !window.pywebview.api || typeof window.pywebview.api[name] !== 'function') return Promise.resolve(null);
    return Promise.resolve(api(name, ...args)).catch(() => null);
  }catch(e){ return Promise.resolve(null); }
}
// la carte #instPick est dessinee par instruments.js ; s'il enregistre deja sa vue, on ne la redessine pas.
function drawInstPick(st){
  if(typeof renderInstPick !== 'function') return;
  if(typeof VIEWS !== 'undefined' && VIEWS.some(v => v.name === 'instPick')) return;
  try{ renderInstPick(st); }catch(e){ console.error('vue instPick :', e); }
}
view('instPickFallback', {sig: st => [(st.instrument_id || ''), st.instrument, curInstrument(st).status,
  curInstrument(st).ready ? 1 : 0, (st.instruments || []).length, (st.instrument_favorites || []).join(',')].join('|'),
  draw: drawInstPick});

// ------------------------------------------------ touches envoyees au jeu (#keyboard)
// Les positions internes ("a", ";", "2"...) sont nommees d'apres le clavier QWERTY US : c'est la POSITION
// physique qui part au jeu. Seul le libelle affiche depend de la disposition du clavier de l'utilisateur.
const MUSIC_AZERTY = {
  '1': '&', '2': 'é', '3': '"', '4': "'", '5': '(', '6': '-', '7': 'è', '8': '_', '9': 'ç', '0': 'à', '-': ')', '=': '=',
  'q': 'a', 'w': 'z', 'e': 'e', 'r': 'r', 't': 't', 'y': 'y', 'u': 'u', 'i': 'i', 'o': 'o', 'p': 'p', '[': '^', ']': '$',
  'a': 'q', 's': 's', 'd': 'd', 'f': 'f', 'g': 'g', 'h': 'h', 'j': 'j', 'k': 'k', 'l': 'l', ';': 'm', "'": 'ù',
  'z': 'w', 'x': 'x', 'c': 'c', 'v': 'v', 'b': 'b', 'n': 'n', 'm': ',', ',': ';', '.': ':', '/': '!'};
function kbKeyLabel(key, layout){
  const k = String(key == null ? '' : key);
  if(layout !== 'azerty') return k.toUpperCase();
  const l = MUSIC_AZERTY[k.toLowerCase()];
  return (l === undefined ? k : l).toUpperCase();
}
// decoupage en rangees des dispositions du catalogue (affichage seulement : les touches viennent de l'etat)
const MUSIC_LAYOUT_ROWS = {'diatonic-15-2row': [7, 8], 'diatonic-15-3row': [5, 5, 5],
                           'piano-diatonic-22': [7, 7, 8], 'piano-chromatic-37': [12, 12, 13]};
function kbRows(ins){
  const n = (ins.keys || []).length;
  const rows = MUSIC_LAYOUT_ROWS[ins.layout_id];
  if(!ins.custom && rows && rows.reduce((a, b) => a + b, 0) === n) return rows.slice();
  const per = ins.kind === 'chromatique' ? 12 : 5;      // bindings personnalises : decoupage regulier
  const out = [];
  for(let i = 0; i < n; i += per) out.push(Math.min(per, n - i));
  return out;
}
function renderKeyboard(st){
  const ins = curInstrument(st);
  const kb = $('keyboard');
  if(!kb) return;
  const layout = st.keyboard_layout === 'azerty' ? 'azerty' : 'qwerty';
  const keys = ins.keys || [];
  const sig = [ins.id, ins.status, ins.ready ? 1 : 0, ins.custom ? 1 : 0, ins.layout_id, ins.lowest, layout, keys.join(' ')].join('|');
  if(!changed(kb, sig)) return;
  kb.innerHTML = '';
  if(!ins.ready || !keys.length){
    // aucun clavier invente : on dit pourquoi, et on mene a la configuration
    const box = document.createElement('div');
    box.className = 'notice notice--warn';
    box.style.width = '100%';
    box.innerHTML = `<span class="notice__ic" aria-hidden="true">⚠️</span><div class="notice__text">
      <b>${esc(cap(ins.name || 'Instrument'))} : ${esc(instrumentStatusText(ins).toLowerCase())}</b><br>
      ${esc(instrumentBlockedText(st))}
      <div class="notice__actions"><button class="btn btn--sm btn--cta" type="button">Configurer les touches</button></div></div>`;
    box.querySelector('button').onclick = () => openInstrumentConfig(ins.id);
    kb.appendChild(box);
    return;
  }
  const chrom = ins.kind === 'chromatique';
  const head = document.createElement('div');
  head.className = 'hint';
  head.textContent = `${keys.length} touches · ${ins.layout_label || 'disposition personnalisée'}`
    + ` · libellés ${layout === 'azerty' ? 'AZERTY' : 'QWERTY'}`;
  kb.appendChild(head);
  let i = 0;
  for(const n of kbRows(ins)){
    const row = document.createElement('div');
    row.className = 'krow';
    for(let j = 0; j < n && i < keys.length; j++, i++){
      const k = keys[i];
      const midi = chrom ? Number(ins.lowest || 0) + i : null;
      const pc = midi == null ? -1 : ((midi % 12) + 12) % 12;
      const el = document.createElement('div');
      el.className = 'kk ' + (chrom ? 'piano' : 'round') + ([1, 3, 6, 8, 10].includes(pc) ? ' black' : '');
      el.textContent = kbKeyLabel(k, layout);
      el.title = (pc >= 0 ? NOTE_NAMES[pc] + ' · ' : '')
        + (layout === 'azerty' ? `position QWERTY « ${String(k).toUpperCase()} »` : `touche « ${String(k).toUpperCase()} »`);
      row.appendChild(el);
    }
    kb.appendChild(row);
  }
}
view('keyboard', {draw: renderKeyboard});

// ------------------------------------------------ diagnostic : instrument pas pret, compatibilite du morceau
// index.html appartient au selecteur : la zone est creee a la volee, juste avant la notice du lecteur.
function diagBox(){
  let el = $('playerDiag');
  if(!el){
    const anchor = $('musicNotice');
    if(!anchor || !anchor.parentNode) return null;
    el = document.createElement('div');
    el.id = 'playerDiag';
    el.style.cssText = 'display:flex;flex-direction:column;gap:8px';
    el.hidden = true;
    anchor.parentNode.insertBefore(el, anchor);
  }
  return el;
}
const MUSIC_OPT_ICON = {transpose: '⇅', octave: '↧', omit: '✂', fold: '↺'};
// st.song_compat = core.compat_report(...) : ce qui ne rentre pas dans le profil actif, et pourquoi.
function compatLines(c, ins){
  const who = cap(ins.name || 'cet instrument');
  const L = [];
  if(c.out_of_range) L.push(`${c.out_of_range} notes hors du registre de ${who}`
    + (c.folded ? ` (${c.folded} rejouées une octave plus loin)` : ''));
  if(c.missing_accidental) L.push(`${c.missing_accidental} notes tombent sur une altération absente : l'instrument n'a pas ce dièse ou ce bémol`);
  if(c.dropped) L.push(`${c.dropped} notes ne seront pas jouées du tout`);
  if(c.drums) L.push(`${c.drums} notes de percussion (piste de batterie) sont ignorées : ${who} ne joue pas les frappes`);
  return L;
}
// apercu puis application : la musique n'est jamais modifiee en silence. song_compat_preview(shift) recalcule
// la couverture cote moteur ; s'il ne repond pas, on montre celle deja calculee par compat_report.
// L'option « omettre » (et son retour « replier ») ne se simule pas par une transposition : on compare la
// couverture deja mesuree par compat_report a celle du morceau tel qu'il est joue aujourd'hui.
function applyCompatFold(o, ins, c){
  const n = Math.abs(Math.round(Number(o.value || 0)));
  const omit = (o.kind || 'omit') === 'omit';
  const before = (c && c.coverage != null) ? Math.round(c.coverage) : null;
  const cov = (o.coverage == null) ? null : Math.round(o.coverage);
  return dialog({title: omit ? 'Omettre les notes hors registre ?' : 'Replier les notes hors registre ?',
    icon: '🎼', ok: 'Appliquer',
    html: (omit
        ? `<p>Aujourd'hui, ${n} note${n > 1 ? 's' : ''} hors du registre de ${esc(cap(ins.name || 'cet instrument'))}
             ${n > 1 ? 'sont rejouées' : 'est rejouée'} une octave plus loin. Les omettre à la place :
             elles ne seront plus jouées du tout.</p>`
        : `<p>Aujourd'hui, ${n} note${n > 1 ? 's' : ''} hors registre ${n > 1 ? 'sont omises' : 'est omise'}.
             Les replier : elles seront rejouées une octave plus loin, à une hauteur différente de l'originale.</p>`)
      + `<p>Après cette adaptation : <b>${cov == null ? '—' : cov + ' %'}</b> des notes à la hauteur exacte`
      + `${before == null ? '' : ` (au lieu de ${before} %)`}.</p>`
      + `<p><small>Ce réglage se change dans les deux sens et le fichier MIDI n'est jamais modifié.</small></p>`})
    .then(yes => { if(yes) api('song_compat_apply', omit ? 'omit' : 'fold'); });
}
// Les options de transposition / octave sont des ECARTS ajoutes a la transposition en cours (c'est ainsi
// que compat_report les mesure). song_compat_apply fait l'addition et la borne cote moteur : y ecrire la
// valeur brute avec set_setting appliquerait une transposition differente de celle annoncee.
function applyCompatOption(o, ins, c){
  const v = Math.round(Number(o.value || 0));
  const kind = o.kind || 'transpose';
  if(kind === 'omit' || kind === 'fold') return applyCompatFold(o, ins, c);
  const demi = n => `${n > 0 ? '+' : ''}${n} demi-ton${Math.abs(n) > 1 ? 's' : ''}`;
  const cur = Math.round(Number(((S || {}).settings || {}).transpose_semitones || 0));
  const fin = Math.max(-24, Math.min(24, cur + v));
  apiOpt('song_compat_preview', v).then(r => {
    const p = (r && typeof r === 'object') ? (r.preview || (typeof r.coverage === 'number' ? r : null)) : null;
    const cov = (p && typeof p.coverage === 'number') ? p.coverage : o.coverage;
    const before = (c && c.coverage != null) ? Math.round(c.coverage) : null;
    const det = [];
    if(p && p.out_of_range != null) det.push(`${p.out_of_range} notes hors registre`);
    if(p && p.missing_accidental != null) det.push(`${p.missing_accidental} notes sur une altération absente`);
    return dialog({title: o.label || 'Adapter le morceau', icon: '🎼', ok: 'Appliquer',
      html: `<b>${esc(o.label || demi(v))}</b><br>Après cette adaptation : <b>${cov == null ? '—' : Math.round(cov) + ' %'}</b>`
        + ` des notes à la hauteur exacte${before == null ? '' : ` (au lieu de ${before} %)`}.`
        + (det.length ? `<br><small>${esc(det.join(' · '))}</small>` : '')
        + `<br><small>${esc(demi(v))} s'ajoutent à la transposition manuelle des « Réglages du morceau » :`
        + ` elle passera de ${esc(demi(cur))} à <b>${esc(demi(fin))}</b>.`
        + ` Tu peux la remettre à zéro quand tu veux : le fichier MIDI n'est jamais modifié.</small>`});
  }).then(yes => { if(yes) api('song_compat_apply', kind, v); });
}
function renderDiag(st){
  const box = diagBox();
  if(!box) return;
  const ins = curInstrument(st);
  const ready = instrumentReady(st);
  const c = st.song_compat || null;
  const lines = c ? compatLines(c, ins) : [];
  const opts = (c && c.options) || [];
  // pendant une session (lecture dans le jeu, synchronisation, salon) le bandeau de session prend la place :
  // meme condition que viewMain, pour ne pas afficher deux choses au meme endroit.
  const mode = playMode(st);
  const mu = st.multi || {};
  const room = roomStatus(st);
  const syncing = mode !== 'room' && (st.state === 'sync' || !!(mu.state && mu.state !== 'idle' && mu.state !== 'playing'));
  const roomBusy = !!(room && ['countdown', 'armed', 'playing', 'downloading'].includes(room.state));
  const busy = syncing || roomBusy || (st.state !== 'stopped' && st.target === 'game');
  // Le detail « 172 notes hors du registre, 68 sur une alteration absente… » n'a d'interet qu'au
  // debogage : il ne s'affiche qu'avec --debug. L'avertissement d'instrument non pret, lui, reste
  // toujours visible : sans ses touches, le morceau ne partira pas.
  const show = !busy && (!ready || (lines.length > 0 && !!st.debug));
  const sig = JSON.stringify([ready, ins.id, ins.status, ins.name, show, !!st.debug, lines, opts,
                              c && c.coverage, c && c.shift, c && c.notes, c && c.playable]);
  if(!changed(box, sig)) return;
  box.hidden = !show;
  box.innerHTML = '';
  if(!show) return;
  if(!ready){
    const n = document.createElement('div');
    n.className = 'notice notice--warn';
    n.innerHTML = `<span class="notice__ic" aria-hidden="true">🎹</span><div class="notice__text">
      <b>${esc(cap(ins.name || 'Instrument'))} n'est pas prêt : ${esc(instrumentStatusText(ins).toLowerCase())}</b><br>
      ${esc(instrumentBlockedText(st))} Tant que ses touches ne sont pas connues, DodoTopia ne lance pas le morceau :
      il ne reprend jamais les touches du piano à la place.
      <div class="notice__actions"><button class="btn btn--sm btn--cta" type="button">Configurer les touches</button></div></div>`;
    n.querySelector('button').onclick = () => openInstrumentConfig(ins.id);
    box.appendChild(n);
  }
  if(lines.length){
    const n = document.createElement('div');
    n.className = 'notice notice--info';
    const cov = c.coverage == null ? ''
      : `<span class="chip chip--badge ${c.coverage >= 90 ? 'chip--ok' : 'chip--warn'}">${Math.round(c.coverage)} % à la hauteur exacte</span>`;
    const sh = c.shift ? `<span class="chip chip--badge chip--info">transposition automatique ${c.shift > 0 ? '+' : ''}${c.shift}</span>` : '';
    const nb = (c.playable != null && c.notes) ? `<span class="chip chip--badge">${c.playable} notes jouées sur ${c.notes}</span>` : '';
    n.innerHTML = `<span class="notice__ic" aria-hidden="true">🎼</span><div class="notice__text">
      <b>Ce morceau ne rentre pas entièrement dans ${esc(cap(ins.name || 'cet instrument'))}</b>
      <div class="chips" style="margin:5px 0">${cov}${sh}${nb}</div>
      <ul style="margin:4px 0 0;padding-left:18px">${lines.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
      <div class="notice__actions compatopts"></div>
      <div class="hint left" style="margin-top:4px">Rien n'est changé sans toi : choisis une option pour en voir l'effet avant de l'appliquer.</div>
      </div>`;
    const acts = n.querySelector('.compatopts');
    opts.forEach(o => {
      const kind = o.kind || 'transpose';
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn--sm btn--secondary';
      const def = kind === 'octave' ? "Déplacer d'une octave"
        : kind === 'omit' ? 'Omettre les notes hors registre'
        : kind === 'fold' ? 'Replier les notes hors registre' : 'Transposer';
      b.textContent = `${MUSIC_OPT_ICON[kind] || '⇅'} ${o.label || def}`
        + (o.coverage == null ? '' : ` · ${Math.round(o.coverage)} %`);
      b.title = "Voir l'effet avant d'appliquer";
      b.onclick = () => applyCompatOption(o, ins, c);
      acts.appendChild(b);
    });
    if(!acts.children.length){
      const s = document.createElement('span');
      s.className = 'hint left';
      s.textContent = 'Aucune adaptation automatique ne ferait mieux : choisis un autre instrument, ou un autre morceau.';
      acts.appendChild(s);
    }
    box.appendChild(n);
  }
}
view('diag', {draw: renderDiag});

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
    list.innerHTML = `<div class="welcome"><div class="big" style="font-size:36px" aria-hidden="true">🎵</div><h3>Bienvenue dans DodoTopia</h3>
      <p>Trois activités, à choisir en haut de la fenêtre : <b>Musique</b>, <b>Dessin</b> et <b>Cuisine</b>.
         DodoTopia prépare ton travail ici, puis le réalise dans Heartopia à ta place.</p>
      <p>Pour la musique, trois étapes :</p>
      <ol class="steps">
        <li><span class="n">1</span>Importe un fichier <b>&nbsp;.mid</b>, ou va dans « Découvrir des morceaux »</li>
        <li><span class="n">2</span>Choisis l'instrument ouvert dans le jeu</li>
        <li><span class="n">3</span>Dans Heartopia, appuie sur <kbd style="margin-left:6px">${esc(hk.play_pause || 'F6')}</kbd></li>
      </ol>
      <div class="btnrow btnrow--center">
        <button class="btn btn--cta" type="button" id="btnImportWelcome">＋ Importer un fichier MIDI</button>
        <button class="btn btn--secondary" type="button" id="btnDiscoverWelcome">Découvrir des morceaux</button>
      </div></div>`;
    list.querySelector('#btnImportWelcome').onclick = () => api('import_dialog');
    list.querySelector('#btnDiscoverWelcome').onclick = () => showMusicView('discover');
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
        <button class="row__act p" type="button" title="Préécouter sur cet ordinateur" aria-label="Préécouter sur cet ordinateur">▶</button>
        <button class="row__act more" type="button" aria-haspopup="menu" title="Plus d'actions" aria-label="Plus d'actions">⋯</button>
      </div>
      <div class="row__fav">
        <button class="row__act star${s.fav ? ' on' : ''}" type="button" aria-pressed="${s.fav ? 'true' : 'false'}" title="${s.fav ? 'Retirer des favoris' : 'Ajouter aux favoris'}" aria-label="${s.fav ? 'Retirer des favoris' : 'Ajouter aux favoris'}">${s.fav ? '★' : '☆'}</button>
      </div>`;
    const main = el.querySelector('.row__main');
    main.onclick = () => api('select_song', i);
    main.ondblclick = e => { if(e.target.closest('.t')) startRename(el, s); else api('preview', i); };
    // Renommer, partager et retirer sont des actions nommées, pas des pictogrammes collés à la lecture.
    el.querySelector('.more').onclick = e => {
      e.stopPropagation();
      menu(el.querySelector('.more'), [
        {label: 'Renommer', fn: () => startRename(el, s)},
        {label: s.online_id ? 'Partager à nouveau' : 'Partager en ligne',
         help: shareOn ? '' : 'connexion nécessaire', disabled: !shareOn,
         fn: () => dialog({title: s.online_id ? 'Déjà partagée' : 'Partager en ligne', icon: '☁️', ok: s.online_id ? 'Renvoyer' : 'Partager',
                html: `<b>${esc(s.name)}</b> sera envoyée au serveur DodoTopia.<br><small>Un administrateur la valide avant qu'elle apparaisse dans le catalogue partagé. Ton pseudo Discord y sera associé.</small>`})
              .then(yes => { if(yes) api('online_share', s.id); })},
        {label: 'Retirer de la bibliothèque', help: 'le fichier d’origine n’est pas touché',
         fn: () => dialog({title: 'Retirer la musique', icon: '🗑️', danger: true, ok: 'Retirer',
                html: `Retirer <b>${esc(s.name)}</b> de la bibliothèque ?<br><small>Le fichier d'origine n'est pas touché.</small>`})
              .then(yes => { if(yes) api('remove_song', s.id); })},
      ]);
    };
    el.querySelector('.star').onclick = e => { e.stopPropagation(); api('toggle_favorite', s.id); };
    el.querySelector('.p').onclick = e => { e.stopPropagation(); api('preview', i); };
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
  // Les raccourcis sont des aides secondaires : ils vivent en infobulle sur les boutons ronds du transport
  // et en <kbd> lisible a cote des actions principales, plus en inscriptions de 9 px sous les icones.
  const hk = st.hotkeys;
  $('gameKey').textContent = hk.play_pause || '';
  if($('instKey')) $('instKey').textContent = hk.next_instrument || '';
  const tip = (id, label, key) => { const el = $(id); if(!el) return; const t = label + (key ? ' (' + key + ')' : ''); el.title = t; el.setAttribute('aria-label', t); };
  tip('btnPrev', 'Musique précédente', hk.prev_song);
  tip('btnNext', 'Musique suivante', hk.next_song);
  tip('btnStop', 'Arrêter', hk.stop);
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
  let sub = `Instrument : <b>${esc(cap(ins.name || 'Instrument'))}</b>`;
  if(!ins.ready) sub += ` · <b>${esc(instrumentStatusText(ins).toLowerCase())}</b>`;
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
// panneau « Synchronisation par le son » : parcours source audio -> test -> jouer ensemble
function audioPanel(st){
  const m = (st.settings && st.settings.multi) || {};
  const mu = st.multi || {};
  segMark($('playerSeg'), b => Number(b.dataset.v) === Number(m.player_id || 1));
  offsetCtl($('audioOffset'), m.offset_ms || 0);
  const c = m.calib;
  // « pas de mesure » et « test échoué » sont deux états différents : latency == null = jamais mesurée.
  const measured = m.latency != null;
  const lat = measured ? `latence mesurée ${Math.round(m.latency * 1000)} ms` : 'latence jamais mesurée';
  let cal;
  if(!c) cal = 'pas encore calé avec les autres joueurs';
  else if(c.role === 'leader') cal = `dernier calage ${whenText(c.when)} : tu menais, joueurs entendus ${c.players && c.players.length ? c.players.join(', ') : 'aucun'}`;
  else if(c.rtt_ms == null) cal = `dernier calage ${whenText(c.when)} : pas d'écho du meneur ${c.leader} (échec)`;
  else cal = `dernier calage ${whenText(c.when)} : calé sur le joueur ${c.leader}, aller-retour ${c.rtt_ms} ms`;
  txt('audioInfo', `${lat} · ${cal}`);
  $('audioInfo').title = `${lat} · ${cal}`;
  $('audioInfo').hidden = false;
  const done = [];
  if(m.device !== undefined) done.push('device');          // la sortie par défaut convient : étape faite d'office
  if(measured) done.push('test');
  stepsMark($('audioSteps'), done, measured ? 'play' : 'test',
            {device: m.device ? String(m.device).slice(0, 18) : 'sortie par défaut', test: measured ? `${Math.round(m.latency * 1000)} ms` : ''});
  const busy = st.state !== 'stopped' || (mu.state && mu.state !== 'idle');
  $('btnCalib').disabled = busy;
  $('btnAudioSetup').disabled = false;
}
function viewMain(st){
  const cur = st.songs[st.current];
  const ins = curInstrument(st);
  const ready = instrumentReady(st);
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

  // destination « Jouer ensemble » : méthode, explication, panneaux, retour au solo
  renderTogether(st, mode, session, room);

  // pastille : etat court
  // Le logiciel ne détecte RIEN du jeu : ni la fenêtre, ni l'instrument ouvert. Une pastille « Prêt »
  // laisserait croire à une vérification qui n'existe pas. Au repos, on n'affiche donc pas d'état.
  const pill = $('pill');
  let pc = 'pill', pt = '';
  if(st.state === 'paused'){ pc = 'pill paused'; pt = '‖ En pause'; }
  else if(isTest){ pc = 'pill paused'; pt = '🔔 Test'; }
  else if(syncing){ pc = 'pill paused'; pt = mu.mode === 'calibrate' ? '🎯 Calage' : '👥 Écoute du jeu…'; }
  else if(roomBusy){ pc = 'pill paused'; pt = room.state === 'playing' ? '🌐 Dans le jeu' : '🌐 Salon…'; }
  else if(inGame){ pc = 'pill game'; pt = '🎮 Dans le jeu'; }
  else if(inPreview){ pc = 'pill preview'; pt = '🎧 Préécoute'; }
  if(pill.className !== pc) pill.className = pc;
  txt('pill', pt);
  pill.hidden = !pt;
  $('disc').classList.toggle('spin', st.state === 'playing');
  const pausing = st.state === 'playing' && inPreview;
  txt('playIcon', pausing ? '❚❚' : '▶');
  txt('playLbl', pausing ? LABELS.pause : 'Préécouter');
  const listenLabel = pausing ? 'Mettre la préécoute en pause' : 'Préécouter sur cet ordinateur';
  $('btnPlay').setAttribute('aria-label', listenLabel);
  $('btnPlay').title = listenLabel;
  $('btnPlay').disabled = !cur || syncing;
  $('btnStop').title = LABELS.stop;

  const cd = Math.round(((st.settings || {}).multi || {}).countdown || 10);

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
  // lancement bloque tant que l'instrument n'est pas pret : pas de touches inventees envoyees au jeu
  gb.disabled = (!cur && mode !== 'room') || !ready;
  // action indisponible : dire pourquoi, sur place
  gb.title = !ready ? `${cap(ins.name || 'Cet instrument')} : ${instrumentStatusText(ins).toLowerCase()}. Configure ses touches avant de jouer.`
           : gb.disabled ? 'Choisis d’abord une musique dans ta bibliothèque.' : '';
  txt('gameHelp', mode === 'audio'
    ? `Ouvre ton instrument dans Heartopia, puis utilise ${hk.play_pause || 'F6'} : ${cd} s d'écoute du jeu commencent, le premier joue la note repère et les autres suivent.`
    : mode === 'room' ? `Ouvre ton instrument dans Heartopia : le chef du salon lance la session, chacun démarre à la même seconde.`
    : `Ouvre ton instrument dans Heartopia, puis utilise ${hk.play_pause || 'F6'} : les touches sont envoyées au jeu.`);

  // bandeau de session (compte a rebours, ecoute, lecture dans le jeu) ou panneau du mode
  // en salon, le bouton principal est dans le panneau (Prêt / Top départ) : on n'affiche pas deux fois la même action
  const inRoom = mode === 'room' && !!(room && room.state !== 'idle' && room.room && room.room.code);
  $('gameCta').hidden = session || inRoom; $('gameHelp').hidden = session || inRoom;
  $('instRow').hidden = session; $('speedRow').hidden = session;
  if($('instSum')) $('instSum').hidden = session;      // resume du profil (instruments.js)
  $('listenBlock').classList.toggle('is-dim', session);
  $('songSet').hidden = session || inRoom;
  $('gameBlock').classList.toggle('is-room', mode === 'room' && !session);
  // en salon, la préécoute se replie en une ligne : la session collective a besoin de la place
  $('listenBlock').classList.toggle('is-compact', inRoom);
  if(session){
    let spec = null;
    const left = mu.seconds_left;
    // salon en ligne : bandeau dedie (compte a rebours partage, lecture, arret pour tous) — lobby.js
    if(mode === 'room' && roomBusy && typeof roomSessionSpec === 'function') spec = roomSessionSpec(st, room, hk);
    if(spec){ /* deja rempli */ }
    else if(syncing && mu.mode === 'calibrate'){
      spec = {count: left != null ? Math.ceil(left) : '…', unit: 's', role: mu.state === 'calibrating' ? (mu.role === 'leader' ? 'Calage · meneur' : `Calage · suiveur du joueur ${mu.leader_id}`) : 'Calage · écoute',
              text: mu.message || 'Écoute du jeu…', meta: `${hk.stop || 'F7'} ou une touche annule`, actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'stop'}]};
    } else if(syncing){
      const role = mu.role === 'leader' ? 'Meneur' : mu.role === 'follower' ? `Suiveur du joueur ${mu.leader_id}` : 'Synchronisation par le son · écoute';
      spec = {count: left != null ? (left < 10 && mu.role ? left.toFixed(1) : Math.ceil(left)) : '…', unit: 's', role,
              text: mu.message || 'Écoute du jeu…', meta: `Reste sur Heartopia, instrument ouvert · ${hk.stop || 'F7'} ou une touche annule`,
              actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'stop'}]};
    } else if(roomBusy && room.state !== 'playing'){
      spec = {count: room.seconds_left != null ? Math.ceil(room.seconds_left) : '…', unit: 's', role: room.role === 'host' ? 'Salon · chef' : 'Salon',
              text: room.message || 'Départ imminent…', meta: `${hk.stop || 'F7'} annule pour toi`, actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'stop'}]};
    } else {
      const dur = st.duration || 0, pos = Math.min(st.position || 0, dur);
      const role = mu.state === 'playing' ? (mu.role === 'leader' ? 'Dans le jeu · meneur' : `Dans le jeu · suiveur du joueur ${mu.leader_id}`) : roomBusy ? 'Dans le jeu · salon' : 'Dans le jeu';
      spec = {live: st.state === 'playing', count: st.state === 'paused' ? '‖' : null, role,
              text: cur ? cur.name : '', meta: st.state === 'paused' ? 'En pause' : `Une touche ou un clic gauche arrête aussi (clic droit caméra permis)`,
              progress: {pct: dur ? pos / dur * 100 : 0, left: fmt(pos), right: fmt(dur)},
              actions: [{label: st.state === 'paused' ? LABELS.resume : LABELS.pause, kbd: hk.play_pause || 'F6', api: 'play_game', cls: 'btn--secondary'},
                        {label: LABELS.stop, kbd: hk.stop || 'F7', api: 'stop'}]};
    }
    // le même bandeau sert dans le lecteur et dans « Jouer ensemble » : l'arrêt reste trouvable des deux côtés
    renderSession($('musicSession'), spec);
    renderSession($('togetherSession'), spec);
  } else {
    renderSession($('musicSession'), null);
    renderSession($('togetherSession'), null);
  }

  // notice contextuelle courte
  let notice = null;
  if(!session){
    const m = (st.settings || {}).multi || {};
    if(!cur) notice = {text: 'Choisis une musique dans ta bibliothèque, ou importe un fichier MIDI, pour pouvoir jouer.', kind: 'info'};
    else if(isTest) notice = {text: mu.message || 'Test de détection en cours…', kind: 'info', icon: '🔔'};
    else if(mode === 'audio' && m.latency == null) notice = {text: 'La détection du son n’a jamais été mesurée sur cet ordinateur. Fais le test une fois avant de jouer à plusieurs : bouton « Source audio et test… ».', kind: 'warn'};
    else if(mode === 'audio' && !m.calib) notice = {text: 'Pas encore calé avec les autres : lancez tous « Calibrer ensemble » en même temps, dans le jeu, instrument ouvert.', kind: 'warn'};
    else if(mode === 'room' && !$('roomBox').children.length) notice = {text: 'Salon en ligne : le panneau arrive avec le client réseau.', kind: 'info', icon: '🌐'};
    if(notice && MUSIC_VIEW !== 'library') notice = null;       // ces conseils appartiennent au lecteur
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
  if(TAB === 'image') msg = (st.draw && st.draw.state === 'drawing') ? 'Dessin en cours dans Heartopia' : (st.draw && st.draw.state === 'autocal') ? 'Mesure automatique en cours' : 'Dessin';
  else if(TAB === 'cook') msg = (st.cook && st.cook.state === 'cooking') ? 'Cuisine en cours dans Heartopia' : 'Cuisine';
  else if(isTest) msg = 'Test de détection…';
  else if(syncing) msg = mu.mode === 'calibrate' ? 'Calage entre joueurs…' : 'Synchronisation par le son : écoute du jeu…';
  else if(inGame && st.state === 'playing') msg = 'Lecture dans Heartopia';
  else if(inPreview && st.state === 'playing') msg = 'Préécoute sur cet ordinateur (rien n\'est envoyé au jeu)';
  else if(st.state === 'paused') msg = 'En pause';
  // au repos, la barre d'état ne répète pas « Prêt » : elle dit le mode seulement s'il n'est pas solo
  else msg = mode === 'audio' ? 'Synchronisation par le son' : mode === 'room' ? 'Salon en ligne' : '';
  txt('msg', msg);
}
view('main', {draw: viewMain});

// ------------------------------------------------ destination « Jouer ensemble »
// Le mode de jeu (cfg.multi.mode) ne change QUE par un choix explicite ici : ni la navigation, ni
// l'ouverture d'un autre écran ne doivent faire quitter un salon.
const MODE_HELP = {
  solo: 'Choisis une méthode pour jouer le même morceau que d’autres joueurs, au même instant.',
  audio: 'Sans réseau. Tout le monde lance l’écoute, le premier joue une note repère dans le jeu, les autres la détectent et partent avec lui. Reste sur Heartopia, instrument ouvert.',
  // derriere « Comment ca marche ? » : le deroulement, pas la redite du sous-titre de la carte.
  room: 'Le chef crée un salon et partage le code à six caractères. Chacun le saisit, ouvre son instrument dans Heartopia et se met « Prêt ». Le chef choisit le morceau et lance la session : tout le monde part au même instant.',
};
function renderTogether(st, mode, session, room){
  const box = $('togetherMethods');
  if(!box) return;
  const roomBtn = $('methodRoom');
  roomBtn.disabled = !st.online;
  roomBtn.title = st.online ? '' : 'Les salons en ligne demandent le client réseau : cette version ne les propose pas encore.';
  segMark(box, b => b.dataset.mode === mode);
  box.querySelectorAll('button').forEach(b => { if(b.dataset.mode !== 'room') b.disabled = session; });
  // le detail vit sous « Comment ca marche ? » : tant qu'aucune methode n'est choisie, les deux
  // cartes se decrivent elles-memes et il n'y a rien de plus a dire.
  txt('togetherHelp', MODE_HELP[mode] || MODE_HELP.solo);
  $('togetherHow').hidden = mode === 'solo';
  $('togetherSolo').hidden = mode === 'solo' || session;
  $('audioPanel').hidden = mode !== 'audio' || session;
  $('roomBox').hidden = mode !== 'room' || session;
  $('togetherPanel').hidden = mode === 'solo' || session;
  if(mode === 'audio' && !session) audioPanel(st);
  if(mode === 'room' && !session && typeof roomPanel === 'function') roomPanel(st);

  // rappel dans le lecteur : une session à plusieurs est armée, on dit laquelle et on y mène
  const recall = $('modeRecall');
  const code = room && room.room && room.room.code;
  if(mode === 'solo' || session){ recall.hidden = true; }
  else {
    recall.hidden = false;
    recall.innerHTML = `<span class="moderecall__ic" aria-hidden="true">${mode === 'room' ? '🌐' : '👥'}</span>`
      + `<span>${mode === 'room' ? (code ? 'Salon ' + esc(code) : 'Salon en ligne') : 'Synchronisation par le son'}</span>`
      + `<span class="moderecall__go">Ouvrir « Jouer ensemble »</span>`;
  }
}
document.querySelectorAll('#togetherMethods > button').forEach(b => b.onclick = () => setPlayMode(b.dataset.mode));
$('togetherSolo').onclick = () => setPlayMode('solo');
$('modeRecall').onclick = () => showMusicView('together');

// ------------------------------------------------ boutons
function setPlayMode(mode){
  const has = window.pywebview && window.pywebview.api.set_play_mode;
  if(has || !window.pywebview) api('set_play_mode', mode); else api('set_multi', mode === 'audio');
}
$('btnImport').onclick = () => api('import_dialog');
$('btnAudioSetup').onclick = () => openSettings(null, 'audio');
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
document.querySelectorAll('#playerSeg > button').forEach(b => b.onclick = () => { segMark($('playerSeg'), x => x === b); api('set_setting', 'multi.player_id', Number(b.dataset.v)); });
$('btnCalib').onclick = () => api('multi_calibrate');
// « Réglages du morceau » : état mémorisé
try{ $('songSet').open = localStorage.getItem('songSetOpen') === '1'; }catch(e){}
$('songSet').ontoggle = () => { try{ localStorage.setItem('songSetOpen', $('songSet').open ? '1' : '0'); }catch(e){} };
try{ $('audioAdv').open = localStorage.getItem('audioAdvOpen') === '1'; }catch(e){}
$('audioAdv').ontoggle = () => { try{ localStorage.setItem('audioAdvOpen', $('audioAdv').open ? '1' : '0'); }catch(e){} };
