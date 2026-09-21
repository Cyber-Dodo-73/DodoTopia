// DodoTopia : activite Musique (instruments, clavier, bibliotheque, lecteur, jouer a plusieurs).
// Le panneau du lecteur suit l'ordre : identite du morceau, preecoute locale, preparation et lancement
// dans le jeu, puis reglages du morceau. La vue « Decouvrir des morceaux » vit dans online.js.
// ------------------------------------------------ instrument actif
// Le choix de l'instrument vit dans instruments.js (carte #instPick, selecteur, assistant). music.js n'affiche
// plus que ce qui depend du profil actif : les touches envoyees au jeu et le diagnostic du morceau.
const MUSIC_LEGACY_IDS = {piano: 'piano', flute: 'recorder', luth: 'lute', guitare: 'lute'};
// libelles des statuts de verification : « documente par une source » n'est pas « teste dans le jeu ».
// Resolus au rendu (fonctions) : le catalogue de traduction peut changer a chaud.
const MUSIC_STATUS_TEXT = {
  unknown: () => t('music.instrument.status.unknown'),
  documented: () => t('music.instrument.status.documented'),
  custom: () => t('music.instrument.status.custom'),
  'quick-tested': () => t('music.instrument.status.quick_tested'),
  confirmed: () => t('music.instrument.status.confirmed')};
const MUSIC_FALLBACK_INST = {id: '', name: '', label_en: '', category: '', image: '', kind: '', keys: [],
  count: 0, layout_id: null, layout_label: '', status: 'unknown', ready: false, percussive: false, custom: false,
  blocked_reason: '', lowest: 60, span: 0, aliases: [], variant_count: 0};
// aucun instrument dans l'etat : un profil de repli dont les libelles sont traduits au moment du rendu
function fallbackInstrument(){
  return Object.assign({}, MUSIC_FALLBACK_INST, {name: t('music.instrument.fallback_name'),
    blocked_reason: t('music.instrument.none_available')});
}
// instrument_id fait foi ; l'index reste accepte pour les anciens etats.
function curInstrument(st){
  const list = (st && st.instruments) || [];
  let ins = null;
  if(st && st.instrument_id) ins = list.find(x => x && x.id === st.instrument_id) || null;
  if(!ins && st && typeof st.instrument === 'number') ins = list[st.instrument] || null;
  return ins || list[0] || fallbackInstrument();
}
function instrumentReady(st){
  const ins = curInstrument(st);
  return (st && st.instrument_ready !== undefined) ? !!st.instrument_ready : !!ins.ready;
}
function instrumentBlockedText(st){
  return (st && st.instrument_blocked) || curInstrument(st).blocked_reason
    || t('music.instrument.keys_not_configured');
}
function instrumentStatusText(ins){ return (MUSIC_STATUS_TEXT[ins && ins.status] || MUSIC_STATUS_TEXT.unknown)(); }
// nom affiche du profil actif (repli traduit si l'etat n'en donne pas)
function instrumentDisplayName(ins){ return cap(ins.name || t('music.instrument.fallback_name')); }
function instrumentOrThis(ins){ return cap(ins.name || t('music.compat.this_instrument')); }
// « Configurer les touches » : l'assistant appartient a instruments.js ; repli si le module manque.
function openInstrumentConfig(id){
  if(typeof openInstrumentWizard === 'function') return openInstrumentWizard(id, 'setup');
  if(typeof openKeysPanel === 'function') return openKeysPanel(id);
  if(typeof openInstrumentSelector === 'function') return openInstrumentSelector(id);
  toast(t('music.instrument.open_change_hint'), 'info');
}
// appel facultatif : renvoie null si la methode n'existe pas cote Python, sans casser l'interface.
function apiOpt(name, ...args){
  try{
    if(!window.pywebview || !window.pywebview.api || typeof window.pywebview.api[name] !== 'function') return Promise.resolve(null);
    return Promise.resolve(api(name, ...args)).catch(e => { console.error('appel facultatif ' + name + ' :', e); return null; });
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
    box.innerHTML = `<span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">
      <b>${esc(t('music.keyboard.not_ready.title', {name: instrumentDisplayName(ins), status: instrumentStatusText(ins).toLowerCase()}))}</b><br>
      ${esc(instrumentBlockedText(st))}
      <div class="notice__actions"><button class="btn btn--sm btn--cta" type="button">${esc(t('music.instrument.configure_keys'))}</button></div></div>`;
    box.querySelector('button').onclick = () => openInstrumentConfig(ins.id);
    kb.appendChild(box);
    return;
  }
  const chrom = ins.kind === 'chromatique';
  const head = document.createElement('div');
  head.className = 'hint';
  head.textContent = t('music.keyboard.summary', {n: keys.length, layout: ins.layout_label || t('music.keyboard.custom_layout'),
    labels: layout === 'azerty' ? 'AZERTY' : 'QWERTY'});
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
      const noteName = pc < 0 ? '' : (typeof noteLabel === 'function' ? noteLabel(pc) : NOTE_NAMES[pc]);
      const kp = {key: String(k).toUpperCase()};
      el.title = (noteName ? noteName + ' · ' : '')
        + (layout === 'azerty' ? t('music.keyboard.key_title.qwerty_position', kp) : t('music.keyboard.key_title.key', kp));
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
    el.className = 'diagbox';
    el.hidden = true;
    anchor.parentNode.insertBefore(el, anchor);
  }
  return el;
}
const MUSIC_OPT_ICON = {transpose: 'transpose', octave: 'arrow-down', omit: 'scissors', fold: 'undo'};
// st.song_compat = core.compat_report(...) : ce qui ne rentre pas dans le profil actif, et pourquoi.
function compatLines(c, ins){
  const who = instrumentOrThis(ins);
  const L = [];
  if(c.out_of_range) L.push(t('music.compat.out_of_range', {n: c.out_of_range, name: who, folded: c.folded || 0}));
  if(c.missing_accidental) L.push(t('music.compat.missing_accidental', {n: c.missing_accidental}));
  if(c.dropped) L.push(t('music.compat.dropped', {n: c.dropped}));
  if(c.drums) L.push(t('music.compat.drums', {n: c.drums, name: who}));
  return L;
}
// « 82 % » / « — » : la couverture mesuree, ou l'absence de mesure
function pctText(v){ return v == null ? t('music.compat.unknown_value') : t('music.percent', {p: Math.round(v)}); }
// « +3 demi-tons » (signe explicite pour les valeurs positives)
function semitonesText(n){ return t('music.compat.semitones', {n, sign: n > 0 ? '+' : ''}); }
function signed(n){ return (n > 0 ? '+' : '') + n; }
// apercu puis application : la musique n'est jamais modifiee en silence. song_compat_preview(shift) recalcule
// la couverture cote moteur ; s'il ne repond pas, on montre celle deja calculee par compat_report.
// L'option « omettre » (et son retour « replier ») ne se simule pas par une transposition : on compare la
// couverture deja mesuree par compat_report a celle du morceau tel qu'il est joue aujourd'hui.
function applyCompatFold(o, ins, c){
  const n = Math.abs(Math.round(Number(o.value || 0)));
  const omit = (o.kind || 'omit') === 'omit';
  const before = (c && c.coverage != null) ? c.coverage : null;
  // le message « Après cette adaptation » porte son propre <b> et ne recoit que des nombres : innerHTML permis
  const after = t('music.compat.after', {coverage: pctText(o.coverage), has_before: before == null ? 'no' : 'yes', before: pctText(before)});
  return dialog({title: omit ? t('music.compat.fold.omit_title') : t('music.compat.fold.fold_title'),
    icon: 'note', ok: t('music.compat.apply'),
    html: `<p>${esc(omit ? t('music.compat.fold.omit_body', {n, name: instrumentOrThis(ins)}) : t('music.compat.fold.fold_body', {n}))}</p>`
      + `<p>${after}</p>`
      + `<p><small>${esc(t('music.compat.fold.note'))}</small></p>`})
    .then(yes => { if(yes) api('song_compat_apply', omit ? 'omit' : 'fold'); });
}
// Les options de transposition / octave sont des ECARTS ajoutes a la transposition en cours (c'est ainsi
// que compat_report les mesure). song_compat_apply fait l'addition et la borne cote moteur : y ecrire la
// valeur brute avec set_setting appliquerait une transposition differente de celle annoncee.
function applyCompatOption(o, ins, c){
  const v = Math.round(Number(o.value || 0));
  const kind = o.kind || 'transpose';
  if(kind === 'omit' || kind === 'fold') return applyCompatFold(o, ins, c);
  const cur = Math.round(Number(((S || {}).settings || {}).transpose_semitones || 0));
  const fin = Math.max(-24, Math.min(24, cur + v));
  apiOpt('song_compat_preview', v).then(r => {
    const p = (r && typeof r === 'object') ? (r.preview || (typeof r.coverage === 'number' ? r : null)) : null;
    const cov = (p && typeof p.coverage === 'number') ? p.coverage : o.coverage;
    const before = (c && c.coverage != null) ? c.coverage : null;
    const det = [];
    if(p && p.out_of_range != null) det.push(t('music.compat.preview.out_of_range', {n: p.out_of_range}));
    if(p && p.missing_accidental != null) det.push(t('music.compat.preview.missing_accidental', {n: p.missing_accidental}));
    // messages a balisage <b> sans donnee utilisateur (nombres seulement) : innerHTML permis
    const after = t('music.compat.after', {coverage: pctText(cov), has_before: before == null ? 'no' : 'yes', before: pctText(before)});
    const note = t('music.compat.transpose_note', {n: v, delta: semitonesText(v), from: semitonesText(cur), to: semitonesText(fin)});
    return dialog({title: o.label || t('music.compat.adapt_title'), icon: 'note', ok: t('music.compat.apply'),
      html: `<b>${esc(o.label || semitonesText(v))}</b><br>${after}`
        + (det.length ? `<br><small>${esc(det.join(' · '))}</small>` : '')
        + `<br><small>${note}</small>`});
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
    n.innerHTML = `<span class="notice__ic" aria-hidden="true">${icon('keyboard')}</span><div class="notice__text">
      <b>${esc(t('music.diag.not_ready.title', {name: instrumentDisplayName(ins), status: instrumentStatusText(ins).toLowerCase()}))}</b><br>
      ${esc(instrumentBlockedText(st))} ${esc(t('music.diag.not_ready.body'))}
      <div class="notice__actions"><button class="btn btn--sm btn--cta" type="button">${esc(t('music.instrument.configure_keys'))}</button></div></div>`;
    n.querySelector('button').onclick = () => openInstrumentConfig(ins.id);
    box.appendChild(n);
  }
  if(lines.length){
    const n = document.createElement('div');
    n.className = 'notice notice--info';
    const cov = c.coverage == null ? ''
      : `<span class="chip chip--badge ${c.coverage >= 90 ? 'chip--ok' : 'chip--warn'}">${esc(t('music.diag.coverage_chip', {p: Math.round(c.coverage)}))}</span>`;
    const sh = c.shift ? `<span class="chip chip--badge chip--info">${esc(t('music.diag.auto_transpose_chip', {shift: signed(c.shift)}))}</span>` : '';
    const nb = (c.playable != null && c.notes) ? `<span class="chip chip--badge">${esc(t('music.diag.played_chip', {playable: c.playable, total: c.notes}))}</span>` : '';
    n.innerHTML = `<span class="notice__ic" aria-hidden="true">${icon('note')}</span><div class="notice__text">
      <b>${esc(t('music.diag.title', {name: instrumentOrThis(ins)}))}</b>
      <div class="chips diag__chips">${cov}${sh}${nb}</div>
      <ul class="diag__list">${lines.map(line => `<li>${esc(line)}</li>`).join('')}</ul>
      <div class="notice__actions compatopts"></div>
      <div class="hint left diag__hint">${esc(t('music.diag.hint'))}</div>
      </div>`;
    const acts = n.querySelector('.compatopts');
    opts.forEach(o => {
      const kind = o.kind || 'transpose';
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn--sm btn--secondary';
      const def = kind === 'octave' ? t('music.diag.option.octave')
        : kind === 'omit' ? t('music.diag.option.omit')
        : kind === 'fold' ? t('music.diag.option.fold') : t('music.diag.option.transpose');
      b.innerHTML = icon(MUSIC_OPT_ICON[kind] || 'transpose') + `<span>${esc(`${o.label || def}`
        + (o.coverage == null ? '' : ` · ${pctText(o.coverage)}`))}</span>`;
      b.title = t('music.diag.option.title');
      b.onclick = () => applyCompatOption(o, ins, c);
      acts.appendChild(b);
    });
    if(!acts.children.length){
      const s = document.createElement('span');
      s.className = 'hint left';
      s.textContent = t('music.diag.no_option');
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
    name:   (a, b) => I18N.compare(a.name, b.name),
    added:  (a, b) => (b.added||0) - (a.added||0),
    plays:  (a, b) => (b.plays||0) - (a.plays||0) || I18N.compare(a.name, b.name),
    recent: (a, b) => (b.last_played||0) - (a.last_played||0),
  }[LIB.sort] || ((a, b) => 0);
  rows.sort((a, b) => (b.fav - a.fav) || cmp(a, b));   // favoris toujours en tete
  return rows;
}
// « il y a 3 h », « hier »… jusqu'a 30 jours ; au-dela, la date courte dans la langue de l'interface
function ago(ts){
  if(!ts) return '';
  const d = (Date.now()/1000 - ts);
  if(d < 86400*30) return I18N.fmtRelative(ts);
  return I18N.fmtDate(ts, 'date');
}
function startRename(el, s){
  const main = el.querySelector('.row__main');
  if(!main || el.querySelector('input.rename')) return;
  const inp = document.createElement('input');
  inp.className = 'rename'; inp.value = s.name; inp.maxLength = 120; inp.setAttribute('aria-label', t('music.library.rename_label'));
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
  txt('count', I18N.fmtNumber(st.songs.length));
  $('favFilter').classList.toggle('active', LIB.fav);
  $('favFilter').setAttribute('aria-pressed', LIB.fav ? 'true' : 'false');
  html('favFilter', LIB.fav ? icon('star-fill') + `<span>${esc(t('music.library.favorites'))}</span>` : icon('star'));
  if($('sortSel').value !== LIB.sort) $('sortSel').value = LIB.sort;
  if(list.querySelector('input.rename')) return;          // renommage en cours : on ne touche pas la liste
  if(!st.songs.length){
    // bibliotheque vide : carte d'accueil en 3 etapes (signature = langue, pour suivre un changement a chaud)
    const wsig = 'welcome|' + I18N.lang + '|' + ((st.hotkeys || {}).play_pause || '');
    if(list.dataset.sig === wsig) return;
    list.dataset.sig = wsig;
    const hk = st.hotkeys || {};
    // intro et etape 1 : balisage <b> sans donnee utilisateur ; etape 3 : le raccourci (donnee) est echappe
    list.innerHTML = `<div class="welcome"><div class="big" aria-hidden="true">${icon('music')}</div><h3>${esc(t('music.library.welcome.title'))}</h3>
      <p>${t('music.library.welcome.intro')}</p>
      <p>${esc(t('music.library.welcome.steps_title'))}</p>
      <ol class="steps">
        <li><span class="n">1</span>${t('music.library.welcome.step1')}</li>
        <li><span class="n">2</span>${esc(t('music.library.welcome.step2'))}</li>
        <li><span class="n">3</span>${t('music.library.welcome.step3', {key: `<kbd>${esc(hk.play_pause || 'F6')}</kbd>`})}</li>
      </ol>
      <div class="btnrow btnrow--center">
        <button class="btn btn--cta" type="button" id="btnImportWelcome">${icon('plus')}<span>${esc(t('music.library.import_midi'))}</span></button>
        <button class="btn btn--secondary" type="button" id="btnDiscoverWelcome">${esc(t('music.library.discover'))}</button>
      </div></div>`;
    list.querySelector('#btnImportWelcome').onclick = () => api('import_dialog');
    list.querySelector('#btnDiscoverWelcome').onclick = () => showMusicView('discover');
    return;
  }
  const rows = visibleSongs(st);
  const shareOn = !!(st.online && st.online.logged_in);
  const sig = rows.map(s => s.id + s.name + (s.fav?1:0) + s.plays + (s.online_id ? 'O' : '')).join('|') + '#' + st.current + '#' + st.state + st.target + '#' + LIB.q + LIB.fav + LIB.sort + '#' + (shareOn ? 1 : 0) + '#' + I18N.lang;
  if(list.dataset.sig === sig) return;
  list.dataset.sig = sig;
  list.innerHTML = '';
  if(!rows.length){
    const onlyFav = LIB.fav && !LIB.q;
    list.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon(onlyFav ? 'star' : 'search')}</div>${onlyFav ? t('music.library.empty.no_favorites') : esc(t('music.library.empty.no_match'))}</div>`;
    return;
  }
  const listenLabel = t('music.library.preview_here');
  const moreLabel = t('music.library.more_actions');
  rows.forEach((s, pos) => {
    const i = s.index;
    const el = document.createElement('div');
    const active = i === st.current;
    const playing = active && st.state === 'playing';
    el.className = 'row' + (active ? ' active' : '') + (playing ? ' playing' : '');
    const meta = [fmt(s.duration), t('music.library.plays', {n: s.plays || 0}),
      LIB.sort === 'added' ? t('music.library.added_ago', {when: ago(s.added)}) : (LIB.sort === 'recent' && s.last_played ? ago(s.last_played) : '')].filter(Boolean).join(' · ');
    const favLabel = s.fav ? t('music.library.fav_remove') : t('music.library.fav_add');
    el.innerHTML = `<button class="row__main" type="button" aria-pressed="${active ? 'true' : 'false'}" title="${esc(s.name)}">
        <span class="n${pos >= 99 ? ' small' : ''}">${playing ? icon('note') : pos+1}</span>
        <span class="tt"><span class="t">${esc(s.name)}</span><span class="m">${esc(meta)}</span></span>
      </button>
      <div class="row__actions">
        <button class="row__act p" type="button" title="${esc(listenLabel)}" aria-label="${esc(listenLabel)}">${icon('play')}</button>
        <button class="row__act more" type="button" aria-haspopup="menu" title="${esc(moreLabel)}" aria-label="${esc(moreLabel)}">${icon('dots')}</button>
      </div>
      <div class="row__fav">
        <button class="row__act star${s.fav ? ' on' : ''}" type="button" aria-pressed="${s.fav ? 'true' : 'false'}" title="${esc(favLabel)}" aria-label="${esc(favLabel)}">${icon(s.fav ? 'star-fill' : 'star')}</button>
      </div>`;
    const main = el.querySelector('.row__main');
    main.onclick = () => api('select_song', i);
    main.ondblclick = e => { if(e.target.closest('.t')) startRename(el, s); else api('preview', i); };
    // Renommer, partager et retirer sont des actions nommées, pas des pictogrammes collés à la lecture.
    // Le nom du morceau (donnee utilisateur) est echappe puis passe en parametre au message.
    el.querySelector('.more').onclick = e => {
      e.stopPropagation();
      const name = `<b>${esc(s.name)}</b>`;
      menu(el.querySelector('.more'), [
        {label: t('music.library.menu.rename'), icon: 'log', fn: () => startRename(el, s)},
        {label: s.online_id ? t('music.library.menu.share_again') : t('music.library.menu.share'),
         help: shareOn ? '' : t('music.library.menu.share_help'), disabled: !shareOn, icon: 'cloud-up',
         fn: () => shareSongDialog(s)},
        {label: t('music.library.menu.remove'), help: t('music.library.menu.remove_help'), icon: 'trash',
         fn: () => dialog({title: t('music.library.remove.title'), icon: 'trash', danger: true, ok: t('music.library.remove.ok'),
                html: `${t('music.library.remove.body', {name})}<br><small>${esc(t('music.library.remove.note'))}</small>`})
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
  const tip = (id, label, key) => { const el = $(id); if(!el) return; const s = key ? t('music.player.tip_with_key', {label, key}) : label; el.title = s; el.setAttribute('aria-label', s); };
  tip('btnPrev', t('music.player.prev'), hk.prev_song);
  tip('btnNext', t('music.player.next'), hk.next_song);
  tip('btnStop', t('action.stop'), hk.stop);
}
view('hotkeys', {sig: st => JSON.stringify(st.hotkeys) + I18N.lang, draw: renderHotkeys});

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
  if(d < 86400) return I18N.fmtRelative(ts);
  return I18N.fmtDate(ts, 'date');
}
// sous-titre du lecteur : en surface, seulement l'instrument (et son etat s'il n'est pas pret). Le nom de
// l'instrument (donnee) est echappe et passe en parametre ; les autres messages ne recoivent que des nombres.
function subtitle(st, cur, ins){
  const bold = s => `<b>${esc(s)}</b>`;
  const parts = [t('music.player.sub.instrument', {name: bold(instrumentDisplayName(ins))})];
  if(!ins.ready) parts.push(bold(instrumentStatusText(ins).toLowerCase()));
  return parts.join(' · ');
}
// detail technique (transposition, notes rapprochees / repliees) : replie sous « Détails »
function subtitleDetails(st){
  const bold = s => `<b>${esc(s)}</b>`;
  const parts = [];
  const manual = Number((st.settings || {}).transpose_semitones || 0);
  if(st.info){
    const total = st.info.shift, auto = total - manual;
    if(manual) parts.push(t('music.player.sub.auto_transpose', {n: bold(signed(auto))}), t('music.player.sub.manual', {n: bold(signed(manual))}));
    else parts.push(t('music.player.sub.transpose', {n: bold(signed(total))}));
    if(st.info.snapped) parts.push(esc(t('music.player.sub.snapped', {n: st.info.snapped})));
    if(st.info.folded) parts.push(esc(t('music.player.sub.folded', {n: st.info.folded})));
  } else if(manual){
    parts.push(esc(t('music.player.sub.auto_transpose_plain')), t('music.player.sub.manual', {n: bold(signed(manual))}));
  }
  return parts.join(' · ');
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
  const ms = measured ? Math.round(m.latency * 1000) : 0;
  const lat = measured ? t('music.together.audio.latency_measured', {ms}) : t('music.together.audio.latency_never');
  let cal;
  if(!c) cal = t('music.together.audio.calib.none');
  else if(c.role === 'leader') cal = t('music.together.audio.calib.leader', {when: whenText(c.when),
    players: c.players && c.players.length ? c.players.join(', ') : t('music.together.audio.calib.nobody')});
  else if(c.rtt_ms == null) cal = t('music.together.audio.calib.failed', {when: whenText(c.when), leader: c.leader});
  else cal = t('music.together.audio.calib.follower', {when: whenText(c.when), leader: c.leader, rtt: c.rtt_ms});
  txt('audioInfo', `${lat} · ${cal}`);
  $('audioInfo').title = `${lat} · ${cal}`;
  $('audioInfo').hidden = false;
  const done = [];
  if(m.device !== undefined) done.push('device');          // la sortie par défaut convient : étape faite d'office
  if(measured) done.push('test');
  stepsMark($('audioSteps'), done, measured ? 'play' : 'test',
            {device: m.device ? String(m.device).slice(0, 18) : t('music.together.audio.default_output'), test: measured ? t('music.together.audio.ms', {ms}) : ''});
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
  txt('title', cur ? cur.name : t('music.player.no_song'));
  html('sub', cur ? subtitle(st, cur, ins) : esc(t('music.player.import_to_start')));
  const det = cur ? subtitleDetails(st) : '';
  html('subDetailsBody', det);
  if($('subDetails').hidden !== !det) $('subDetails').hidden = !det;

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
  let pc = 'pill', pt = '', pi = '';
  if(st.state === 'paused'){ pc = 'pill paused'; pi = 'pause'; pt = t('music.player.state.paused'); }
  else if(isTest){ pc = 'pill paused'; pi = 'bell'; pt = t('music.player.state.test'); }
  else if(syncing){ pc = 'pill paused'; pi = mu.mode === 'calibrate' ? 'target' : 'users'; pt = mu.mode === 'calibrate' ? t('music.player.state.calib') : t('music.player.state.listening'); }
  else if(roomBusy){ pc = 'pill paused'; pi = 'globe'; pt = room.state === 'playing' ? t('music.player.state.in_game') : t('music.player.state.room'); }
  else if(inGame){ pc = 'pill game'; pi = 'gamepad'; pt = t('music.player.state.in_game'); }
  else if(inPreview){ pc = 'pill preview'; pi = 'headphones'; pt = t('music.player.state.preview'); }
  if(pill.className !== pc) pill.className = pc;
  html('pill', pt ? icon(pi) + `<span>${esc(pt)}</span>` : '');
  pill.hidden = !pt;
  $('disc').classList.toggle('spin', st.state === 'playing');
  const pausing = st.state === 'playing' && inPreview;
  html('playIcon', icon(pausing ? 'pause' : 'play'));
  txt('playLbl', pausing ? t('music.player.pause') : t('action.listen'));
  const listenLabel = pausing ? t('music.player.listen_pause') : t('music.library.preview_here');
  $('btnPlay').setAttribute('aria-label', listenLabel);
  $('btnPlay').title = listenLabel;
  $('btnPlay').disabled = !cur || syncing;
  $('btnStop').title = t('action.stop');

  const cd = Math.round(((st.settings || {}).multi || {}).countdown || 10);
  const playKey = hk.play_pause || 'F6';

  // appel a l'action F6 selon le mode
  const gb = $('btnGame');
  let gcls = 'btn btn--lg btn--cta', glabel;
  if(inGame && st.state === 'playing') glabel = t('music.player.pause');
  else if(inGame && st.state === 'paused') glabel = t('music.player.resume');
  else if(mode === 'audio') glabel = t('music.together.start_session');
  else if(mode === 'room') glabel = t('music.together.start_session');
  else glabel = t('action.play_in_game');
  if(gb.className !== gcls) gb.className = gcls;
  // lancement bloque tant que l'instrument n'est pas pret : pas de touches inventees envoyees au jeu.
  // Action indisponible : la raison est ecrite sous le bouton (setAction), pas seulement en infobulle.
  const gDisabled = (!cur && mode !== 'room') || !ready;
  setAction(gb, {label: glabel, disabled: gDisabled,
    reason: !ready ? t('music.player.blocked_instrument', {name: instrumentOrThis(ins), status: instrumentStatusText(ins).toLowerCase()})
          : gDisabled ? t('music.player.choose_first') : ''});
  txt('gameHelp', mode === 'audio' ? t('music.player.help.audio', {key: playKey, seconds: cd})
    : mode === 'room' ? t('music.player.help.room')
    : t('music.player.help.solo', {key: playKey}));

  // bandeau de session (compte a rebours, ecoute, lecture dans le jeu) ou panneau du mode
  // en salon, le bouton principal est dans le panneau (Prêt / Top départ) : on n'affiche pas deux fois la même action
  const inRoom = mode === 'room' && !!(room && room.state !== 'idle' && room.room && room.room.code);
  $('gameCta').hidden = session || inRoom; $('gameHelp').hidden = session || inRoom;
  $('instRow').hidden = session; $('speedRow').hidden = session;
  // « Tester une note » : seulement a l'arret, avec un instrument pret
  const tb = $('btnTestNote');
  if(tb){
    const tDis = !ready || st.state !== 'stopped';
    if(tb.disabled !== tDis && !tb.classList.contains('is-loading')) tb.disabled = tDis;
  }
  // le jeu tourne en administrateur et pas DodoTopia : les touches n'arriveront pas
  const gw = st.game_window || {};
  const adminBlock = !!(gw.checked && gw.found && gw.elevated && st.is_admin === false);
  if($('gameAdminNotice').hidden !== (!adminBlock || session)) $('gameAdminNotice').hidden = !adminBlock || session;
  if($('instSum')) $('instSum').hidden = session;      // resume du profil (instruments.js)
  $('listenBlock').classList.toggle('is-dim', session);
  $('songSet').hidden = session || inRoom;
  $('gameBlock').classList.toggle('is-room', mode === 'room' && !session);
  // en salon, la préécoute se replie en une ligne : la session collective a besoin de la place
  $('listenBlock').classList.toggle('is-compact', inRoom);
  if(session){
    let spec = null;
    const left = mu.seconds_left;
    const stopKey = hk.stop || 'F7';
    // salon en ligne : bandeau dedie (compte a rebours partage, lecture, arret pour tous) — lobby.js
    if(mode === 'room' && roomBusy && typeof roomSessionSpec === 'function') spec = roomSessionSpec(st, room, hk);
    if(spec){ /* deja rempli */ }
    else if(syncing && mu.mode === 'calibrate'){
      spec = {count: left != null ? Math.ceil(left) : '…', unit: 's',
              role: mu.state === 'calibrating' ? (mu.role === 'leader' ? t('music.session.calib.leader') : t('music.session.calib.follower', {id: mu.leader_id})) : t('music.session.calib.listening'),
              text: mu.message || t('music.session.listening_game'), meta: t('music.session.cancel_keys', {key: stopKey}),
              actions: [{label: t('common.cancel'), kbd: stopKey, api: 'stop'}]};
    } else if(syncing){
      const role = mu.role === 'leader' ? t('music.session.role.leader') : mu.role === 'follower' ? t('music.session.role.follower', {id: mu.leader_id}) : t('music.session.role.audio_listen');
      spec = {count: left != null ? (left < 10 && mu.role ? left.toFixed(1) : Math.ceil(left)) : '…', unit: 's', role,
              text: mu.message || t('music.session.listening_game'), meta: t('music.session.stay_meta', {key: stopKey}),
              actions: [{label: t('common.cancel'), kbd: stopKey, api: 'stop'}]};
    } else if(roomBusy && room.state !== 'playing'){
      spec = {count: room.seconds_left != null ? Math.ceil(room.seconds_left) : '…', unit: 's', role: room.role === 'host' ? t('music.session.room.host') : t('music.session.room.label'),
              text: room.message || t('music.session.room.starting'), meta: t('music.session.room.cancel_me', {key: stopKey}),
              actions: [{label: t('common.cancel'), kbd: stopKey, api: 'stop'}]};
    } else {
      const dur = st.duration || 0, pos = Math.min(st.position || 0, dur);
      const role = mu.state === 'playing' ? (mu.role === 'leader' ? t('music.session.in_game.leader') : t('music.session.in_game.follower', {id: mu.leader_id}))
        : roomBusy ? t('music.session.in_game.room') : t('music.session.in_game.label');
      spec = {live: st.state === 'playing', countIcon: st.state === 'paused' ? 'pause' : null, role,
              text: cur ? cur.name : '', meta: st.state === 'paused' ? t('music.player.state.paused') : t('music.session.stop_hint'),
              progress: {pct: dur ? pos / dur * 100 : 0, left: fmt(pos), right: fmt(dur)},
              actions: [{label: st.state === 'paused' ? t('music.player.resume') : t('music.player.pause'), icon: st.state === 'paused' ? 'play' : 'pause', kbd: playKey, api: 'play_game', cls: 'btn--secondary'},
                        {label: t('action.stop'), icon: 'stop', kbd: stopKey, api: 'stop'}]};
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
    // sans morceau : la raison est deja ecrite sous « Jouer dans Heartopia » (setAction)
    if(!cur) notice = null;
    else if(isTest) notice = {text: mu.message || t('music.notice.test_running'), kind: 'info', icon: 'bell'};
    else if(mode === 'audio' && m.latency == null) notice = {text: t('music.notice.latency_never'), kind: 'warn'};
    else if(mode === 'audio' && !m.calib) notice = {text: t('music.notice.not_calibrated'), kind: 'warn'};
    else if(mode === 'room' && !$('roomBox').children.length) notice = {text: t('music.notice.room_pending'), kind: 'info', icon: 'globe'};
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
  txt('volumeV', t('music.percent', {p: Number(st.settings.preview_volume)}));
  const tr = Number(st.settings.transpose_semitones || 0);
  txt('trV', signed(tr));
  txt('ver', st.version ? 'v' + st.version : '');

  // barre d'etat : etat court + version
  const status = $('status');
  const scls = 'status ' + (st.state === 'playing' ? st.target : '');
  if(status.className !== scls) status.className = scls;
  let msg;
  if(TAB === 'image') msg = (st.draw && st.draw.state === 'drawing') ? t('music.status_bar.drawing') : (st.draw && st.draw.state === 'autocal') ? t('music.status_bar.autocal') : t('music.status_bar.draw');
  else if(TAB === 'cook') msg = (st.cook && st.cook.state === 'cooking') ? t('music.status_bar.cooking') : t('music.status_bar.cook');
  else if(isTest) msg = t('music.status_bar.test');
  else if(syncing) msg = mu.mode === 'calibrate' ? t('music.status_bar.calib') : t('music.status_bar.audio_listening');
  else if(inGame && st.state === 'playing') msg = t('music.status_bar.in_game');
  else if(inPreview && st.state === 'playing') msg = t('music.status_bar.preview');
  else if(st.state === 'paused') msg = t('music.player.state.paused');
  // au repos, la barre d'état ne répète pas « Prêt » : elle dit le mode seulement s'il n'est pas solo
  else msg = mode === 'audio' ? t('music.together.audio.label') : mode === 'room' ? t('music.together.room.label') : '';
  txt('msg', msg);
}
view('main', {draw: viewMain});

// ------------------------------------------------ destination « Jouer ensemble »
// Le mode de jeu (cfg.multi.mode) ne change QUE par un choix explicite ici : ni la navigation, ni
// l'ouverture d'un autre écran ne doivent faire quitter un salon.
// Le detail derriere « Comment ca marche ? » : le deroulement, pas la redite du sous-titre de la carte.
function modeHelp(mode){
  if(mode === 'audio') return t('music.together.help.audio');
  if(mode === 'room') return t('music.together.help.room');
  return t('music.together.help.solo');
}
function renderTogether(st, mode, session, room){
  const box = $('togetherMethods');
  if(!box) return;
  const roomBtn = $('methodRoom');
  roomBtn.disabled = !st.online;
  roomBtn.title = st.online ? '' : t('music.together.room_unavailable');
  segMark(box, b => b.dataset.mode === mode);
  box.querySelectorAll('button').forEach(b => { if(b.dataset.mode !== 'room') b.disabled = session; });
  // le detail vit sous « Comment ca marche ? » : tant qu'aucune methode n'est choisie, les deux
  // cartes se decrivent elles-memes et il n'y a rien de plus a dire.
  txt('togetherHelp', modeHelp(mode));
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
    const what = mode === 'room' ? (code ? t('music.together.recall.room_code', {code}) : t('music.together.room.label')) : t('music.together.audio.label');
    recall.innerHTML = icon(mode === 'room' ? 'globe' : 'users')
      + `<span>${esc(what)}</span>`
      + `<span class="moderecall__go">${esc(t('music.together.recall.open'))}${icon('chevron-right')}</span>`;
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
$('volume').oninput = () => { $('volumeV').textContent = t('music.percent', {p: Number($('volume').value)}); };
$('volume').onchange = () => api('set_setting', 'preview_volume', Number($('volume').value));   // sans toast
function bumpTranspose(d){
  const v = Math.max(-24, Math.min(24, Number((S && S.settings && S.settings.transpose_semitones) || 0) + d));
  $('trV').textContent = signed(v);
  api('set_setting', 'transpose_semitones', v);
}
$('trUp').onclick = () => bumpTranspose(1);
$('trDown').onclick = () => bumpTranspose(-1);
$('openLog').onclick = () => api('open_draw_log');
$('openCookLog').onclick = () => api('open_cook_log');
document.querySelectorAll('#playerSeg > button').forEach(b => b.onclick = () => { segMark($('playerSeg'), x => x === b); api('set_setting', 'multi.player_id', Number(b.dataset.v)); });
$('btnCalib').onclick = () => api('multi_calibrate');
// « Réglages du morceau » : état mémorisé
try{ $('songSet').open = localStorage.getItem('songSetOpen') === '1'; }catch(e){}
$('songSet').ontoggle = () => { try{ localStorage.setItem('songSetOpen', $('songSet').open ? '1' : '0'); }catch(e){} if(S) render(S); };
$('btnTestNote').onclick = () => { if(typeof testNote === 'function') testNote($('btnTestNote')); };
$('gameAdminHow').onclick = () => { if(typeof gameAdminHelp === 'function') gameAdminHelp(); };

// ------------------------------------------------ pistes MIDI du morceau (« Réglages du morceau »)
// song_tracks(id) -> {ok, tracks:[{index, name, notes, channels, drums}], off:[index…]} ; set_song_tracks(id, off)
const TRK = {id: null, data: null, error: '', seq: 0};
function tracksLoad(id){
  const seq = ++TRK.seq;
  TRK.id = id; TRK.data = null; TRK.error = '';
  tracksDraw();
  api('song_tracks', id).then(r => {
    if(seq !== TRK.seq) return;
    if(r && r.ok){ TRK.data = {tracks: r.tracks || [], off: (r.off || []).map(Number)}; }
    else TRK.error = (r && r.error) || t('common.action_failed');
    tracksDraw();
  });
}
function tracksDraw(){
  const box = $('tracksList'); if(!box) return;
  if(TRK.error){ box.innerHTML = `<p class="hint left">${esc(t('music.tracks.error', {error: TRK.error}))}</p>`; return; }
  if(!TRK.data){ box.innerHTML = `<p class="hint left"><span class="spinner" aria-hidden="true"></span> ${esc(t('music.tracks.loading'))}</p>`; return; }
  const list = TRK.data.tracks.filter(tr => Number(tr.notes) > 0);
  if(!list.length){ box.innerHTML = `<p class="hint left">${esc(t('music.tracks.none'))}</p>`; return; }
  box.innerHTML = list.map(tr => {
    const on = !TRK.data.off.includes(Number(tr.index));
    const name = (tr.name && String(tr.name).trim()) || t('music.tracks.track_n', {n: Number(tr.index) + 1});
    return `<label class="track${on ? '' : ' is-off'}"><input type="checkbox" data-i="${Number(tr.index)}"${on ? ' checked' : ''}>
      <span class="track__nm">${esc(name)}</span>
      ${tr.drums ? `<span class="chip chip--badge chip--info">${esc(t('music.tracks.drums'))}</span>` : ''}
      <span class="track__n">${esc(t('music.tracks.notes', {n: Number(tr.notes)}))}</span></label>`;
  }).join('');
  box.querySelectorAll('input[data-i]').forEach(cb => cb.onchange = () => {
    const boxes = [...box.querySelectorAll('input[data-i]')];
    if(!boxes.some(x => x.checked)){ cb.checked = true; toast(t('music.tracks.keep_one'), 'warn'); return; }
    const shown = boxes.map(x => Number(x.dataset.i));
    // les pistes sans note deja ignorees restent ignorees
    const off = TRK.data.off.filter(i => !shown.includes(i)).concat(boxes.filter(x => !x.checked).map(x => Number(x.dataset.i)));
    TRK.data.off = off;
    cb.closest('.track').classList.toggle('is-off', !cb.checked);
    api('set_song_tracks', TRK.id, off);
  });
}
view('tracks', {sig: st => {
  const cur = st.songs && st.songs[st.current];
  return ($('songSet').open && !$('songSet').hidden ? 'o' : 'c') + '|' + (cur ? cur.id : '') + '|' + I18N.lang;
}, draw: st => {
  const cur = st.songs && st.songs[st.current];
  $('tracksBlock').hidden = !cur;
  if(!cur || !$('songSet').open || $('songSet').hidden) return;
  if(TRK.id !== cur.id || (!TRK.data && !TRK.error)) tracksLoad(cur.id);
  else tracksDraw();
}});
try{ $('audioAdv').open = localStorage.getItem('audioAdvOpen') === '1'; }catch(e){}
$('audioAdv').ontoggle = () => { try{ localStorage.setItem('audioAdvOpen', $('audioAdv').open ? '1' : '0'); }catch(e){} };
