// DodoTopia : catalogue d'instruments cote interface.
//   - controle compact du lecteur (#instRow / #instSum) : image, nom, statut, resume, « Voir les touches » ;
//   - selecteur (#instOverlay) : une carte par TYPE, recherche, filtres, favoris, fiche de detail ;
//   - panneau « Voir les touches » : table lisible + section avancee (MIDI, position QWERTY, envoi des touches) ;
//   - assistant (#wizOverlay) : 5 etapes, capture d'une touche par position physique, conflits, test court.
// Regles : une seule carte par type, aucun skin / aucune couleur / aucune variante esthetique.
// Choisir ici n'equipe pas l'instrument dans Heartopia : c'est dit dans le selecteur et avant le premier test.
// Fonctions exposees a music.js / lobby.js : renderInstPick, openInstrumentSelector, openKeysPanel,
// instImageHtml, instCatalogue.

// ------------------------------------------------ vocabulaire et tables
const INST_CATS = [['strings', 'Cordes'], ['winds', 'Vents'], ['keys', 'Claviers'], ['percussion', 'Percussions']];
const INST_CAT_LABEL = {strings: 'Cordes', winds: 'Vents', keys: 'Claviers', percussion: 'Percussions'};
// statut de verification : libelle affiche + teinte de pastille. Jamais « teste dans Heartopia ».
const INST_STATUS = {
  unknown:        {label: 'Touches à configurer',                 chip: 'chip--warn'},
  documented:     {label: 'Profil documenté · à vérifier',        chip: 'chip--info'},
  custom:         {label: 'Touches personnalisées · à vérifier',  chip: 'chip--info'},
  'quick-tested': {label: 'Test rapide réussi · vérification partielle', chip: 'chip--warn'},
  confirmed:      {label: 'Confirmé sur cet ordinateur',          chip: 'chip--ok'},
};
function instStatus(s){ return INST_STATUS[s] || INST_STATUS.unknown; }

// noms de notes, convention d'affichage du dossier : Do4 / C4 = MIDI 60
const INST_FR = ['Do', 'Do♯', 'Ré', 'Ré♯', 'Mi', 'Fa', 'Fa♯', 'Sol', 'Sol♯', 'La', 'La♯', 'Si'];
const INST_EN = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
function noteFr(m){ m = Number(m); return INST_FR[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1); }
function noteEn(m){ m = Number(m); return INST_EN[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1); }
function noteOctave(m){ return Math.floor(Number(m) / 12) - 1; }
// une note peut arriver en entier MIDI (contrat) ou deja detaillee {midi, solfege} : les deux se lisent
function instNoteText(n){
  if(n != null && typeof n === 'object') return n.solfege || noteFr(n.midi);
  return noteFr(n);
}
// l'assistant et les ecritures de profil sont refuses pendant une lecture : on le dit AVANT d'ouvrir
function instPlaying(st){ const s = st || S || {}; return s.state != null && s.state !== 'stopped'; }

// Positions physiques injectables (nommees d'apres le clavier QWERTY US : c'est la semantique des
// scancodes cote Python). e.code decrit la POSITION de la touche appuyee, quelle que soit la disposition.
const INST_CODE_KEY = (() => {
  const m = {};
  'abcdefghijklmnopqrstuvwxyz'.split('').forEach(c => { m['Key' + c.toUpperCase()] = c; });
  for(let i = 0; i <= 9; i++) m['Digit' + i] = String(i);
  m.Minus = '-'; m.Equal = '='; m.BracketLeft = '['; m.BracketRight = ']';
  m.Semicolon = ';'; m.Quote = "'"; m.Comma = ','; m.Period = '.'; m.Slash = '/';
  return m;
})();
const INST_KEYS_OK = new Set(Object.keys(INST_CODE_KEY).map(c => INST_CODE_KEY[c]));
function instKeyInjectable(k){ return INST_KEYS_OK.has(String(k || '').toLowerCase()); }

// Position US -> legende imprimee sur un clavier francais. Le LIBELLE change, jamais la position envoyee.
const INST_AZERTY = {
  '1': '&', '2': 'é', '3': '"', '4': "'", '5': '(', '6': '-', '7': 'è', '8': '_', '9': 'ç', '0': 'à', '-': ')', '=': '=',
  q: 'A', w: 'Z', e: 'E', r: 'R', t: 'T', y: 'Y', u: 'U', i: 'I', o: 'O', p: 'P', '[': '^', ']': '$',
  a: 'Q', s: 'S', d: 'D', f: 'F', g: 'G', h: 'H', j: 'J', k: 'K', l: 'L', ';': 'M', "'": 'ù',
  z: 'W', x: 'X', c: 'C', v: 'V', b: 'B', n: 'N', m: ',', ',': ';', '.': ':', '/': '!',
};
function instKeyLabel(key, kbl){
  if(key == null || key === '') return '—';
  const k = String(key).toLowerCase();
  const lab = (kbl === 'azerty' && INST_AZERTY[k] != null) ? INST_AZERTY[k] : k;
  return lab.toUpperCase();
}
// AZERTY : la rangee des chiffres demande Maj. Pertinent seulement en envoi « Lettre affichée » (vk).
function instKeyShift(key, kbl){ return kbl === 'azerty' && /^[0-9]$/.test(String(key || '')); }
function instInputMode(st){ return (((st || S || {}).settings) || {}).input_mode || 'scancode'; }
function instKbLayout(st){ return ((st || S || {}).keyboard_layout) || 'qwerty'; }

function instNorm(s){ return String(s == null ? '' : s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }

// ------------------------------------------------ images : locales, hors ligne, repli de famille
// Pastille generique par famille (disque creme + note) : elle ne represente aucun instrument precis et
// garde exactement la taille de l'image, donc la grille ne bouge pas.
const INST_FB_INK = {strings: '%23c98644', winds: '%232fa8a1', keys: '%23c98a1f', percussion: '%237f9240'};
function instFallbackSrc(cat){
  const ink = INST_FB_INK[cat] || '%23b56f3f';
  return 'data:image/svg+xml;utf8,' + "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
    + "<circle cx='24' cy='24' r='22' fill='%23fbf5ea' stroke='%23e4d4ba' stroke-width='2'/>"
    + "<text x='24' y='33' font-size='24' font-family='sans-serif' text-anchor='middle' fill='" + ink + "'>&#9834;</text></svg>";
}
function instCatOf(id, cat){
  if(cat) return cat;
  const it = instFromState(id);
  if(it && it.category) return it.category;
  const c = INST.cat && INST.cat.by_id && INST.cat.by_id[id];
  return (c && c.category) || '';
}
// appele par l'attribut onerror des images d'instrument (une seule fois par image)
function instImgFail(img){
  if(!img || img.dataset.fb === '1') return;
  img.dataset.fb = '1';
  img.classList.add('is-fb');
  const cat = img.dataset.cat || '';
  img.src = instFallbackSrc(cat);
  img.title = 'Image indisponible' + (INST_CAT_LABEL[cat] ? ' · ' + INST_CAT_LABEL[cat] : '');
}
// <img> d'un type d'instrument, servie en relatif depuis la page (donc hors ligne)
function instImageHtml(id, cls, cat){
  const c = instCatOf(id, cat);
  return `<img class="instimg ${esc(cls || '')}" data-cat="${esc(c)}" alt="" loading="lazy"`
    + ` src="instruments/${encodeURIComponent(String(id || ''))}.png" onerror="instImgFail(this)">`;
}

// ------------------------------------------------ etat local : catalogue en cache, filtres du selecteur
const INST = {
  cat: null, catPromise: null,     // get_instrument_catalogue() : appele une seule fois
  detail: new Map(),               // id -> {key, val} : fiche complete (notes, rangees, dispositions)
  q: '', filter: 'all', sel: null, // recherche, filtre, type affiche dans la fiche
};
function instCatalogue(){
  if(INST.cat) return Promise.resolve(INST.cat);
  if(INST.catPromise) return INST.catPromise;
  INST.catPromise = api('get_instrument_catalogue').then(r => {
    INST.cat = (r && (r.layouts || r.categories)) ? r : null;
    if(!INST.cat) INST.catPromise = null;                      // backend absent (mock) : on reessaiera
    return INST.cat;
  }).catch(() => { INST.catPromise = null; return null; });
  return INST.catPromise;
}
// dispositions du catalogue : dict {id: layout} ou liste, les deux sont acceptes
function instLayouts(){
  const l = (INST.cat && INST.cat.layouts) || null;
  if(!l) return {};
  if(Array.isArray(l)){ const m = {}; l.forEach(x => { if(x && x.layoutId) m[x.layoutId] = x; }); return m; }
  return l;
}
function instLayoutLabel(id){
  const l = instLayouts()[id];
  return (l && (l.labelFr || l.label)) || id || '';
}
function instFromState(id, st){
  st = st || S;
  if(!st || !st.instruments) return null;
  return st.instruments.find(i => i.id === id) || null;
}
function instActive(st){
  if(!st || !st.instruments || !st.instruments.length) return null;
  return st.instruments.find(i => i.id === st.instrument_id) || st.instruments[st.instrument] || st.instruments[0];
}
function instFavs(st){ return ((st || S || {}).instrument_favorites) || []; }
// fiche complete ; le cache est invalide des que le profil ou le clavier change
function instDetail(id, force){
  const it = instFromState(id) || {};
  const key = [id, it.status, it.layout_id, it.count, instKbLayout()].join('|');
  const c = INST.detail.get(id);
  if(!force && c && c.key === key) return Promise.resolve(c.val);
  return api('get_instrument_detail', id).then(r => {
    const val = (r && r.id) ? r : null;
    if(val) INST.detail.set(id, {key, val});
    return val;
  }).catch(() => null);
}
function instDetailCached(id){ const c = INST.detail.get(id); return c ? c.val : null; }
function instForget(){ INST.detail.clear(); }
// Repli quand la fiche complete n'est pas disponible (backend absent, apercu mock) : on redresse ce qu'on
// peut a partir de la disposition du catalogue. Jamais de touches inventees : sans disposition, on n'affiche rien.
function instFallbackDetail(i){
  if(!i) return null;
  const lay = instLayouts()[i.layout_id];
  const notes = (lay && lay.notes) || [];
  if(!notes.length) return null;
  const counts = (lay.rows && lay.rows.length) ? lay.rows : [notes.length];
  const rows = [];
  let at = 0;
  counts.forEach(n => { rows.push(notes.slice(at, at + n)); at += n; });
  if(at < notes.length) rows.push(notes.slice(at));
  return {id: i.id, notes: notes.slice(), rows: rows, missing_notes: [], layouts: [], source_urls: i.source_urls || []};
}

// ------------------------------------------------ resume d'un profil
// « 15 notes · Do4 → Do6 · 15 notes, 2 rangees »
function instSummary(ins){
  if(!ins) return '';
  if(!ins.ready) return ins.blocked_reason || 'Touches à configurer avant de pouvoir jouer.';
  const out = [];
  const n = ins.count != null ? ins.count : (ins.keys || []).length;
  if(n) out.push(n + (n > 1 ? ' notes' : ' note'));
  if(ins.lowest != null && ins.span != null && n) out.push(noteFr(ins.lowest) + ' → ' + noteFr(ins.lowest + ins.span));
  // le libellé de disposition commence par « 15 notes, … » : on ne répète pas le compte déjà écrit
  let lab = ins.layout_label || instLayoutLabel(ins.layout_id);
  if(lab && n) lab = lab.replace(new RegExp('^' + n + ' notes?,?\\s*'), '');
  if(lab) out.push(lab);
  else if(ins.kind) out.push(ins.kind);
  return out.join(' · ');
}

// ------------------------------------------------ controle compact du lecteur (#instRow / #instSum)
function renderInstPick(st){
  const ins = instActive(st);
  const img = $('instPickImg');
  if(img){
    const id = (ins && ins.id) || '';
    if(img.dataset.id !== id){
      img.dataset.id = id; img.dataset.fb = ''; img.dataset.cat = (ins && ins.category) || '';
      img.classList.remove('is-fb'); img.title = '';
      img.onerror = () => instImgFail(img);
      if(id) img.src = 'instruments/' + encodeURIComponent(id) + '.png';
      else instImgFail(img);
    }
  }
  txt('instPickName', (ins && ins.name) ? cap(ins.name) : 'Aucun instrument');
  const stt = instStatus(ins && ins.status);
  const badge = $('instPickStatus');
  if(badge){
    const cls = 'instpick__status chip chip--badge ' + stt.chip;
    if(badge.className !== cls) badge.className = cls;
    if(badge.textContent !== stt.label) badge.textContent = stt.label;
  }
  const pick = $('instPick');
  if(pick) pick.classList.toggle('is-blocked', !!(ins && !ins.ready));
  txt('instSumTxt', instSummary(ins));
  const keys = $('btnKeys');
  if(keys) keys.textContent = (ins && ins.ready) ? 'Voir les touches' : 'Configurer les touches';
  // meme condition que music.js : pendant une session, la ligne instrument laisse la place au bandeau
  const sum = $('instSum');
  if(sum) sum.hidden = !!($('instRow') && $('instRow').hidden);
}
view('instPick', {
  sig: st => {
    const i = instActive(st) || {};
    return [i.id, i.status, i.ready, i.count, i.layout_id, i.lowest, i.span, st.keyboard_layout,
            instFavs(st).join(','), $('instRow') && $('instRow').hidden ? 1 : 0].join('|');
  },
  draw: renderInstPick,
});

// ------------------------------------------------ selecteur : « Choisir mon instrument »
function instVisible(st){
  const list = (st.instruments || []).slice();
  const favs = instFavs(st);
  const q = instNorm(INST.q);
  return list.filter(i => {
    if(INST.filter === 'fav' && !favs.includes(i.id)) return false;
    if(INST.filter !== 'all' && INST.filter !== 'fav' && i.category !== INST.filter) return false;
    if(!q) return true;
    const hay = [i.name, i.label_en, i.id].concat(i.aliases || []).map(instNorm);
    return hay.some(h => h.includes(q));
  });
}
function instDrawFilters(st){
  const box = $('instFilters');
  if(!box) return;
  const list = st.instruments || [];
  const tabs = [['all', 'Tous']];
  if(instFavs(st).length) tabs.push(['fav', 'Favoris']);            // pas de filtre vide
  INST_CATS.forEach(([id, lab]) => { if(list.some(i => i.category === id)) tabs.push([id, lab]); });
  if(!tabs.some(t => t[0] === INST.filter)) INST.filter = 'all';
  const sig = tabs.map(t => t[0]).join(',') + '#' + INST.filter;
  if(box.dataset.sig !== sig){
    box.dataset.sig = sig;
    box.innerHTML = tabs.map(([id, lab]) =>
      `<button type="button" class="chip" data-f="${esc(id)}" aria-pressed="false">${esc(lab)}</button>`).join('');
    box.querySelectorAll('button').forEach(b => b.onclick = () => { INST.filter = b.dataset.f; instSelDraw(); });
  }
  box.querySelectorAll('button').forEach(b => {
    const on = b.dataset.f === INST.filter;
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
}
function instCardHtml(st, i, activeId){
  const stt = instStatus(i.status);
  const fav = instFavs(st).includes(i.id);
  const isActive = i.id === activeId;
  const isSel = i.id === INST.sel;
  return `<div class="instcell">
    <button type="button" class="instcard${isActive ? ' is-active' : ''}${isSel ? ' is-sel' : ''}" data-id="${esc(i.id)}"
        aria-current="${isSel ? 'true' : 'false'}" tabindex="${isSel ? '0' : '-1'}">
      <span class="instcard__check" aria-hidden="true">✓</span>
      ${instImageHtml(i.id, 'instcard__img', i.category)}
      <span class="instcard__name">${esc(cap(i.name || i.id))}</span>
      <span class="sr-only">${esc(INST_CAT_LABEL[i.category] || '')}. ${isActive ? 'Instrument actif. ' : ''}${esc(stt.label)}</span>
    </button>
    <button type="button" class="instfav${fav ? ' on' : ''}" data-fav="${esc(i.id)}" aria-pressed="${fav ? 'true' : 'false'}"
      title="${fav ? 'Retirer des favoris' : 'Ajouter aux favoris'}"
      aria-label="${fav ? 'Retirer' : 'Ajouter'} ${esc(cap(i.name || i.id))} ${fav ? 'des' : 'aux'} favoris">${fav ? '★' : '☆'}</button>
  </div>`;
}
function instSelDraw(){
  const st = S;
  if(!st || !$('instOverlay').classList.contains('open')) return;
  instDrawFilters(st);
  const rows = instVisible(st);
  const activeId = (instActive(st) || {}).id;
  if(!INST.sel || !rows.some(i => i.id === INST.sel)) INST.sel = rows.length ? (rows.some(i => i.id === activeId) ? activeId : rows[0].id) : null;
  const grid = $('instGrid');
  const sig = rows.map(i => [i.id, i.status, i.ready].join('~')).join(',') + '#' + INST.sel + '#' + activeId + '#' + instFavs(st).join(',');
  if(grid.dataset.sig !== sig){
    // le focus vit dans la grille : on le rend a la carte selectionnee apres reconstruction
    const hadFocus = !!(document.activeElement && document.activeElement.closest && document.activeElement.closest('.instcell'));
    grid.dataset.sig = sig;
    grid.innerHTML = rows.map(i => instCardHtml(st, i, activeId)).join('');
    if(hadFocus) setTimeout(() => {
      const c = grid.querySelector('.instcard[tabindex="0"]');
      if(c && !grid.contains(document.activeElement)) c.focus();
    }, 0);
    grid.querySelectorAll('.instcard').forEach(b => {
      b.onclick = () => { INST.sel = b.dataset.id; instSelDraw(); const d = $('instDetail'); if(d) d.scrollTop = 0; };
      b.ondblclick = () => instUse(b.dataset.id);
    });
    grid.querySelectorAll('.instfav').forEach(b => b.onclick = e => {
      e.stopPropagation();
      api('toggle_instrument_favorite', b.dataset.fav).then(() => instSelDraw());
    });
  }
  $('instGridEmpty').hidden = rows.length > 0;
  txt('instSelCount', rows.length
    ? `${rows.length} instrument${rows.length > 1 ? 's' : ''} sur ${(st.instruments || []).length} · une carte par type`
    : '');
  instDetailDraw();
}
// navigation clavier dans la grille (tabindex glissant : une seule carte tabulable)
function instGridKeys(e){
  const card = e.target.closest && e.target.closest('.instcard');
  if(!card) return;
  const items = [...$('instGrid').querySelectorAll('.instcard')];
  if(!items.length) return;
  let i = items.indexOf(card);
  // nombre de colonnes : les cartes de la premiere ligne partagent le meme offsetTop
  const top = items[0].offsetTop;
  let cols = items.findIndex(el => el.offsetTop > top);
  if(cols <= 0) cols = items.length;
  if(e.key === 'ArrowRight') i = Math.min(items.length - 1, i + 1);
  else if(e.key === 'ArrowLeft') i = Math.max(0, i - 1);
  else if(e.key === 'ArrowDown') i = Math.min(items.length - 1, i + cols);
  else if(e.key === 'ArrowUp') i = Math.max(0, i - cols);
  else if(e.key === 'Home') i = 0;
  else if(e.key === 'End') i = items.length - 1;
  else return;
  e.preventDefault();
  INST.sel = items[i].dataset.id;
  instSelDraw();
  const again = [...$('instGrid').querySelectorAll('.instcard')].find(el => el.dataset.id === INST.sel);
  if(again) again.focus();
}

// fiche de detail : image, nom, mode musical, notes disponibles, action principale, niveau secondaire
function instDetailDraw(){
  const box = $('instDetail');
  if(!box) return;
  const st = S, id = INST.sel;
  const i = instFromState(id, st);
  if(!i){ box.innerHTML = '<p class="hint left">Choisis un instrument dans la liste.</p>'; return; }
  const d = instDetailCached(id);
  const stt = instStatus(i.status);
  const activeId = (instActive(st) || {}).id;
  const fav = instFavs(st).includes(id);
  const layouts = (d && d.layouts) || [];
  const lay = layouts.find(l => l.layoutId === i.layout_id) || null;
  const missing = (d && d.missing_notes) || [];
  const srcs = (d && d.source_urls) || i.source_urls || [];

  const notesTxt = i.ready
    ? `${i.count != null ? i.count : (i.keys || []).length} notes · ${noteFr(i.lowest)} → ${noteFr(i.lowest + (i.span || 0))}`
    : (i.blocked_reason || 'Aucune touche n’est encore associée à cet instrument.');
  // « 15 notes · Do4 -> Do6 · 3 rangees » : ce qu'on a besoin de savoir avant de choisir, en une ligne.
  const layLabel = lay ? (lay.labelFr || lay.layoutId) : (i.layout_label || instLayoutLabel(i.layout_id) || '');
  const factsTxt = i.ready
    ? [notesTxt, String(layLabel).replace(/^\d+\s+notes?,?\s*/, '')].filter(Boolean).join(' · ')
    : notesTxt;
  const missTxt = missing.length
    ? `<p class="instdet__warnline">Altérations absentes de cette disposition : ${esc(missing.slice(0, 8).map(instNoteText).join(', '))}${missing.length > 8 ? '…' : ''} — les morceaux qui les utilisent seront signalés avant la lecture.</p>`
    : '';
  const percTxt = i.percussive
    ? `<p class="instdet__warnline">Percussion : la correspondance issue des sources ne dit pas quelle frappe produit quelle hauteur. Un test adapté est demandé avant de pouvoir jouer.</p>`
    : '';

  const main = i.ready
    ? `<button class="btn btn--cta" type="button" data-act="use"${id === activeId ? ' disabled' : ''}>${id === activeId ? 'Instrument actif' : 'Utiliser cet instrument'}</button>`
    : `<button class="btn btn--cta" type="button" data-act="setup">Configurer les touches</button>`;

  box.innerHTML = `
    <div class="instdet__top">
      ${instImageHtml(id, 'instdet__img', i.category)}
      <div class="instdet__id">
        <h3>${esc(cap(i.name || id))}</h3>
        <p class="instdet__en">${esc(i.label_en || '')}${i.label_en && i.category ? ' · ' : ''}${esc(INST_CAT_LABEL[i.category] || '')}</p>
        <span class="chip chip--badge ${stt.chip}">${esc(stt.label)}</span>
      </div>
      <button type="button" class="instfav${fav ? ' on' : ''}" data-act="fav" aria-pressed="${fav ? 'true' : 'false'}"
        title="${fav ? 'Retirer des favoris' : 'Ajouter aux favoris'}">${fav ? '★' : '☆'}</button>
    </div>
    <p class="instdet__facts1">${esc(factsTxt)}</p>
    ${percTxt}
    <div class="instdet__acts">
      ${main}
      <button class="btn btn--secondary btn--sm" type="button" data-act="keys">Voir les touches</button>
      ${i.ready ? '<button class="btn btn--ghost btn--sm" type="button" data-act="setup">Reconfigurer…</button>' : ''}
    </div>
    ${layouts.length > 1 ? `<details class="disclosure"><summary>Dispositions possibles pour ce type (${layouts.length})</summary>
      <div class="disclosure__body"><p class="hint left">Choisis dans le jeu la même disposition qu'ici. Elles n'ont pas les mêmes touches.</p>
      <div class="instlays">${layouts.map(l => `<button type="button" class="instlay${l.layoutId === i.layout_id ? ' active' : ''}" data-lay="${esc(l.layoutId)}">
        <b>${esc(l.labelFr || l.layoutId)}</b><span>${esc(l.descriptionFr || '')}</span>
        <span class="instlay__n">${l.noteCount != null ? l.noteCount + ' notes' : ''}</span></button>`).join('')}</div></div></details>` : ''}
    <details class="disclosure"><summary>Détails techniques et sources</summary>
      <div class="disclosure__body">
        ${missTxt}
        ${i.ready ? `<div class="btnrow"><button class="btn btn--ghost btn--sm" type="button" data-act="full"
          title="Vérifier toutes les associations, par groupes de trois, pour obtenir « Confirmé sur cet ordinateur »">Validation intégrale…</button></div>` : ''}
        <dl class="instdet__facts instdet__facts--tech">
          <dt>Identifiant</dt><dd>${esc(id)}</dd>
          <dt>Disposition</dt><dd>${esc(i.layout_id || '—')}</dd>
          <dt>Variantes d'apparence regroupées</dt><dd>${i.variant_count != null ? esc(String(i.variant_count)) : '—'} (une seule carte : même son, mêmes touches)</dd>
          <dt>Provenance du profil</dt><dd>${esc(instProvenance(i))}</dd>
        </dl>
        ${srcs.length ? `<p class="hint left">Sources consultées :</p><ul class="instsrc">${srcs.map(u => `<li><code>${esc(u)}</code></li>`).join('')}</ul>
          <button class="btn btn--ghost btn--sm" type="button" data-act="copysrc">Copier les sources</button>` : ''}
        <p class="hint left">Les tables de touches viennent de projets communautaires. Elles n'ont pas été testées dans
          Heartopia depuis cet ordinateur : le statut le dit pour chaque instrument.</p>
        <p class="hint left">Profil au format JSON : seules les données sont lues, aucun contenu importé n'est exécuté.
          Un profil vérifié ailleurs redevient « à vérifier » ici.</p>
        <div class="btnrow">
          <button class="btn btn--ghost btn--sm" type="button" data-act="export">Exporter ce profil…</button>
          <button class="btn btn--ghost btn--sm" type="button" data-act="import">Importer un profil…</button>
        </div>
      </div>
    </details>`;

  const on = (sel, fn) => box.querySelectorAll(sel).forEach(b => b.onclick = fn);
  on('[data-act="use"]', () => instUse(id));
  on('[data-act="setup"]', () => { closeModal($('instOverlay')); openInstrumentWizard(id, 'setup'); });
  on('[data-act="full"]', () => { closeModal($('instOverlay')); openInstrumentWizard(id, 'full'); });
  on('[data-act="keys"]', () => { closeModal($('instOverlay')); openKeysPanel(id); });
  on('[data-act="fav"]', () => api('toggle_instrument_favorite', id).then(() => instSelDraw()));
  on('[data-act="copysrc"]', () => copyText(srcs.join('\n'), 'Sources copiées'));
  on('[data-act="export"]', () => instExportProfile(id));
  on('[data-act="import"]', () => instImportProfile(id));
  box.querySelectorAll('[data-lay]').forEach(b => b.onclick = () => instSetLayout(id, b.dataset.lay));

  if(!d) instDetail(id).then(r => { if(r && INST.sel === id) instDetailDraw(); });
}
function instProvenance(i){
  if(i.status === 'confirmed') return 'Confirmé sur cet ordinateur';
  if(i.status === 'quick-tested') return 'Test rapide réussi sur cet ordinateur (échantillon, pas une validation intégrale)';
  if(i.status === 'custom') return 'Touches saisies sur cet ordinateur, non vérifiées dans le jeu';
  if(i.status === 'documented') return 'Documenté par une source communautaire, non vérifié dans le jeu';
  return 'Inconnu : aucune source ne documente les touches de cet instrument';
}
// Export / import d'un profil : les deux methodes existent cote Python (schema valide, rien n'est
// execute). Sans point d'entree ici, la documentation promettrait une fonction inatteignable.
function instExportProfile(id){
  apiOpt('export_instrument_profile', id).then(r => {
    if(r && r.ok === false){ toast(r.error || 'Export impossible', 'warn'); return; }
    if(r && r.path) return;                                  // enregistre par la boite de dialogue systeme
    if(r && r.text) copyText(r.text, 'Profil copié dans le presse-papiers');
  });
}
function instImportProfile(id){
  const i = instFromState(id) || {};
  if(instPlaying()){ toast('Arrête la lecture avant d’importer un profil.', 'warn'); return; }
  dialog({title: 'Importer un profil ?', icon: '⌨',
    html: `<p>Choisis un fichier <code>.json</code> exporté par DodoTopia. Les touches de
           « ${esc(cap(i.name || id))} » seront remplacées.</p>
           <p>Un profil vérifié sur un autre ordinateur redevient « à vérifier » ici : une validation faite
           ailleurs ne prouve rien sur cette installation.</p>`,
    ok: 'Choisir un fichier'}).then(okv => {
      if(!okv) return;
      api('import_instrument_profile', null, id).then(() => { instForget(); instSelDraw(); });
    });
}
function instUse(id){
  const i = instFromState(id);
  if(i && !i.ready){ openInstrumentWizard(id, 'setup'); return; }
  // le choix est fait : la fenetre se ferme, comme n'importe quel selecteur. Rester ouvert obligeait
  // a cliquer une deuxieme fois sur « Fermer » pour revenir a ce qu'on etait en train de faire.
  api('set_instrument', id).then(() => { closeInstrumentSelector(); toast(`Instrument : ${cap((i && i.name) || id)}`, 'ok'); });
}
function instSetLayout(id, layoutId){
  const i = instFromState(id);
  if(i && i.custom){
    dialog({title: 'Remplacer tes touches ?', icon: '⌨',
      html: `<p>Cet instrument utilise des touches que tu as saisies toi-même. Changer de disposition les remplace
             par la table documentée de « ${esc(instLayoutLabel(layoutId))} ».</p><p>Ta personnalisation sera perdue.</p>`,
      ok: 'Remplacer', danger: true}).then(okv => {
        if(!okv) return;
        api('set_instrument_layout', id, layoutId, true).then(() => { instForget(); instSelDraw(); });
      });
    return;
  }
  api('set_instrument_layout', id, layoutId).then(() => { instForget(); instSelDraw(); });
}
function openInstrumentSelector(){
  const st = S || {};
  INST.q = ''; INST.filter = 'all';
  INST.sel = (instActive(st) || {}).id || null;
  const f = $('instSearch');
  if(f){ f.value = ''; $('instSearchBox').classList.remove('has'); }
  openModal($('instOverlay'), $('instPick'));
  instSelDraw();
  instCatalogue().then(() => instSelDraw());
  if(INST.sel) instDetail(INST.sel).then(() => instSelDraw());
  setTimeout(() => { if(f) f.focus(); }, 30);
}
function closeInstrumentSelector(){ closeModal($('instOverlay')); }
// le selecteur ouvert suit l'etat (changement d'instrument, favoris, fin d'assistant)
view('instSel', {
  sig: st => $('instOverlay').classList.contains('open')
    ? (st.instruments || []).map(i => [i.id, i.status, i.ready].join('~')).join(',') + '#' + st.instrument_id + '#' + instFavs(st).join(',')
    : 'closed',
  draw: () => instSelDraw(),
});

// ------------------------------------------------ panneau « Voir les touches »
const INST_ASSIGN = {
  layout: ['Disposition', 'chip--info'],
  custom: ['Personnalisée', 'chip--warn'],
  none: ['Non affectée', 'chip--warn'],
};
function instKeyRowsHtml(d, kbl){
  const rows = (d && d.rows) || [];
  if(!rows.length) return '';
  return `<div class="keyboard keyboard--wide">${rows.map(r => `<div class="krow">${r.map(n =>
    `<span class="kk ${d.id === 'piano' ? 'piano' : 'round'}${[1, 3, 6, 8, 10].includes(Number(n.midi) % 12) ? ' black' : ''}"
      title="${esc((n.solfege || noteFr(n.midi)) + ' · ' + instKeyLabel(n.key, kbl))}">${esc(instKeyLabel(n.key, kbl))}</span>`).join('')}</div>`).join('')}</div>`;
}
function instKeysHtml(st, d, i){
  const kbl = instKbLayout(st);
  const mode = instInputMode(st);
  const notes = (d && d.notes) || [];
  const custom = !!(i && i.custom);
  const pref = st.keyboard_layout_pref || 'auto';
  const head = `<div class="instkeys__head">
      ${instImageHtml(i.id, 'instkeys__img', i.category)}
      <div><h3 class="instkeys__name">${esc(cap(i.name || i.id))}</h3>
        <span class="chip chip--badge ${instStatus(i.status).chip}">${esc(instStatus(i.status).label)}</span></div>
      <div class="spacer"></div>
      <div class="seg" id="kblSeg" role="radiogroup" aria-label="Disposition de mon clavier">
        <button type="button" role="radio" data-kbl="auto">Auto</button>
        <button type="button" role="radio" data-kbl="azerty">AZERTY</button>
        <button type="button" role="radio" data-kbl="qwerty">QWERTY</button>
      </div>
    </div>
    <p class="hint left">Disposition utilisée pour l'affichage : <b>${esc(kbl.toUpperCase())}</b>${pref === 'auto' ? ' (détectée)' : ''}.
      DodoTopia envoie une <b>position</b> de touche au jeu : changer cette valeur change la légende affichée, pas ce qui est envoyé.</p>`;
  if(!notes.length){
    return head + `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">⚠️</span>
      <div class="notice__text">${esc(i.blocked_reason || 'Aucune touche n’est associée à cet instrument : ses touches ne sont documentées nulle part.')}
      </div></div>
      <div class="btnrow"><button class="btn btn--cta" type="button" data-act="setup">Configurer les touches</button></div>`;
  }
  const rows = notes.map(n => {
    const key = n.key || '';
    const lab = n.label || instKeyLabel(key, kbl);
    const state = !key ? 'none' : (custom ? 'custom' : 'layout');
    const [sl, sc] = INST_ASSIGN[state];
    return `<tr>
      <td class="instkeys__note">${esc(n.solfege || noteFr(n.midi))}</td>
      <td class="instkeys__en">${esc(n.note || noteEn(n.midi))}</td>
      <td class="instkeys__oct">Octave ${noteOctave(n.midi)}</td>
      <td><span class="keycap keycap--static">${esc(lab)}</span>${(n.shift != null ? n.shift : instKeyShift(key, kbl)) ? ' <span class="chip chip--badge chip--warn">Maj</span>' : ''}</td>
      <td><span class="chip chip--badge ${sc}">${esc(sl)}</span></td>
    </tr>`;
  }).join('');
  const shiftWarn = (mode === 'vk' && kbl === 'azerty' && notes.some(n => (n.shift != null ? n.shift : instKeyShift(n.key, kbl))))
    ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">⚠️</span><div class="notice__text">
        « Envoi des touches » est réglé sur « Lettre affichée » et ton clavier est en AZERTY : les chiffres demandent Maj
        et risquent de ne pas passer. Repasse sur « Position » dans Réglages › Musique et audio › Avancé.</div></div>`
    : '';
  return head + shiftWarn + instKeyRowsHtml(d, kbl) + `
    <div class="tablewrap"><table class="instkeys">
      <thead><tr><th scope="col">Note</th><th scope="col">Nom international</th><th scope="col">Registre</th>
        <th scope="col">Touche (${esc(kbl.toUpperCase())})</th><th scope="col">Affectation</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="btnrow">
      <button class="btn btn--secondary btn--sm" type="button" data-act="setup">Modifier les touches…</button>
      <button class="btn btn--ghost btn--sm" type="button" data-act="full">Validation intégrale…</button>
      <button class="btn btn--ghost btn--sm" type="button" data-act="copy">Copier la table</button>
    </div>
    <p class="hint left">La validation intégrale repasse <b>toutes</b> les associations dans le jeu, par groupes de trois.
      C'est la seule procédure qui donne « Confirmé sur cet ordinateur » : un test rapide ne suffit pas.</p>
    <details class="disclosure"><summary>Avancé : MIDI, position de référence et envoi des touches</summary>
      <div class="disclosure__body">
        <p class="hint left">Convention d'affichage : <b>Do4 = MIDI 60</b>. La colonne « position » est le nom de la
          touche sur un clavier <b>QWERTY US</b> : c'est ce nom que DodoTopia envoie au jeu, quelle que soit ta disposition.</p>
        <div class="tablewrap"><table class="instkeys instkeys--tech">
          <thead><tr><th scope="col">MIDI</th><th scope="col">Note</th><th scope="col">Position QWERTY</th><th scope="col">Légende ${esc(kbl.toUpperCase())}</th></tr></thead>
          <tbody>${notes.map(n => `<tr><td>${esc(String(n.midi))}</td><td>${esc(n.note || noteEn(n.midi))}</td>
            <td><code>${esc(n.key || '—')}</code></td><td>${esc(n.label || instKeyLabel(n.key, kbl))}</td></tr>`).join('')}</tbody>
        </table></div>
        <p class="hint left">Envoi des touches : <b>${mode === 'vk' ? 'Lettre affichée (vk)' : 'Position (scancode)'}</b>.
          En « Position », la disposition du clavier ne change rien à ce que reçoit le jeu. En « Lettre affichée », un
          clavier AZERTY modifie les chiffres et la ponctuation : c'est le seul cas où la colonne « Maj » compte.</p>
      </div>
    </details>`;
}
function openKeysPanel(id){
  const st = S || {};
  id = id || (instActive(st) || {}).id;
  const i = instFromState(id, st);
  if(!i){ toast('Instrument introuvable', 'warn'); return; }
  const show = d0 => {
    const d = d0 || instFallbackDetail(i) || {id: id, notes: [], rows: []};
    openPanel({
      title: 'Touches envoyées au jeu', wide: true, opener: $('btnKeys'),
      html: instKeysHtml(S || st, d, i),
      wire: box => {
        const seg = box.querySelector('#kblSeg');
        if(seg){
          const pref = (S || st).keyboard_layout_pref || 'auto';
          segMark(seg, b => b.dataset.kbl === pref);
          seg.querySelectorAll('button').forEach(b => b.onclick = () => {
            api('set_keyboard_layout', b.dataset.kbl).then(() => { instForget(); closePanel(); openKeysPanel(id); });
          });
        }
        const s = box.querySelector('[data-act="setup"]');
        if(s) s.onclick = () => { closePanel(); openInstrumentWizard(id, 'setup'); };
        const fu = box.querySelector('[data-act="full"]');
        if(fu) fu.onclick = () => { closePanel(); openInstrumentWizard(id, 'full'); };
        const c = box.querySelector('[data-act="copy"]');
        if(c) c.onclick = () => copyText(((d && d.notes) || []).map(n =>
          `${n.solfege || noteFr(n.midi)}\t${n.note || noteEn(n.midi)}\t${n.midi}\t${n.key || ''}`).join('\n'), 'Table copiée');
      },
    });
  };
  const cached = instDetailCached(id);
  if(cached) show(cached);
  instDetail(id).then(d => {
    if(!cached){ show(d); return; }                        // premier affichage : on attend la fiche
    if(d && d !== cached && panelOpen()) show(d);           // fiche rafraichie (profil ou clavier change)
  });
}

// ------------------------------------------------ assistant de configuration (5 etapes)
const WIZ_STEPS = ['open', 'layout', 'bind', 'test', 'save'];
const WIZ_TITLES = {open: 'Ouvre l’instrument dans Heartopia', layout: 'Quelle disposition vois-tu ?',
  bind: 'Associe les notes aux touches', test: 'Teste quelques touches', save: 'Enregistre ce profil'};
// frappes proposees pour une percussion : on demande CE QUI A SONNE, pas un Do/Re arbitraire
const WIZ_STRIKES = [['low', 'Frappe grave (basse)'], ['open', 'Frappe ouverte (médium)'],
  ['slap', 'Frappe claquée (aigu)'], ['none', 'Aucun son']];
const WIZ = {
  id: null, mode: 'setup', step: 'open', layoutId: null, bindings: {}, order: [],
  capture: null, msg: '', msgKind: 'warn', detail: null, tested: null, testing: false, dirty: false,
};
function wizInst(){ return instFromState(WIZ.id) || {}; }
function wizPercussive(){ return !!wizInst().percussive; }
function wizLayoutList(){
  const d = WIZ.detail;
  const all = instLayouts();
  const sup = (d && d.layouts) || [];
  if(sup.length) return sup;
  return Object.keys(all).map(k => all[k]);        // type inconnu : aucune source, on montre les 4 candidates
}
function wizLayoutNotes(layoutId){
  const l = (wizLayoutList().find(x => x.layoutId === layoutId)) || instLayouts()[layoutId];
  return (l && l.notes) || [];
}
// Table de travail {midi: touche} a partir d'une disposition candidate.
// Deux regles, les memes que instrument_wizard_layout() cote Python (c'est lui qui enregistre) :
//  - une disposition DOCUMENTEE pour ce type propose ses touches comme point de depart ;
//  - un type sans mapping documente ne pose que les notes A RELEVER, aucune touche : il n'herite
//    jamais du profil d'un autre instrument.
// L'appel a instrument_wizard_layout garde les deux tables identiques : sans lui, l'assistant afficherait
// une disposition et en enregistrerait une autre.
function wizLoadLayout(layoutId){
  WIZ.layoutId = layoutId;
  const documented = ((WIZ.detail && WIZ.detail.layouts) || []).some(l => l.layoutId === layoutId);
  const notes = wizLayoutNotes(layoutId);
  WIZ.order = notes.map(n => Number(n.midi));
  WIZ.bindings = {};
  notes.forEach(n => { WIZ.bindings[n.midi] = documented ? (n.key || '') : ''; });
  WIZ.tested = null; WIZ.dirty = true;
  api('instrument_wizard_layout', layoutId, true);
}
function wizConflicts(){
  const st = S || {};
  const kbl = instKbLayout(st), mode = instInputMode(st);
  const hk = st.hotkeys || {};
  const out = [];
  const byKey = {};
  Object.keys(WIZ.bindings).forEach(m => {
    const k = String(WIZ.bindings[m] || '').toLowerCase();
    if(!k) return;
    (byKey[k] = byKey[k] || []).push(Number(m));
  });
  Object.keys(WIZ.bindings).forEach(mk => {
    const midi = Number(mk), k = String(WIZ.bindings[mk] || '').toLowerCase();
    if(!k) return;
    const dup = (byKey[k] || []).filter(x => x !== midi);
    if(dup.length) out.push({midi, key: k, severity: 'error',
      message: 'Déjà utilisée par ' + dup.map(noteFr).join(', ') + ' : deux notes ne peuvent pas partager une touche.'});
    if(!instKeyInjectable(k)) out.push({midi, key: k, severity: 'error',
      message: 'Cette touche ne peut pas être envoyée au jeu.'});
    Object.keys(hk).forEach(h => {
      const parts = String(hk[h] || '').toLowerCase().split('+').map(s => s.trim()).filter(Boolean);
      if(!parts.includes(k)) return;
      const hard = (h === 'stop' || h === 'play_pause');
      out.push({midi, key: k, severity: hard ? 'error' : 'warn',
        message: hard
          ? `Occupée par le raccourci « ${HOTKEY_LABELS[h] || h} » (${hk[h]}). Choisis une autre touche : un raccourci d'arrêt n'est jamais supprimé pour un mapping.`
          : `Aussi utilisée par le raccourci « ${HOTKEY_LABELS[h] || h} » (${hk[h]}).`});
    });
    if(mode === 'vk' && instKeyShift(k, kbl)) out.push({midi, key: k, severity: 'warn',
      message: 'En AZERTY avec l’envoi « Lettre affichée », ce chiffre demande Maj : le jeu peut ne rien recevoir.'});
  });
  return out;
}
function wizBlocking(list){ return list.filter(c => c.severity === 'error'); }
function wizBound(){ return Object.keys(WIZ.bindings).filter(m => WIZ.bindings[m]).length; }

// --- capture d'une touche : e.code (POSITION physique), raccourcis globaux debranches pendant la saisie
function wizKeyDown(e){
  if(WIZ.capture == null) return;
  e.preventDefault(); e.stopPropagation();
  if(e.key === 'Escape'){ wizCaptureEnd(); wizDraw(); return; }
  if(e.key === 'Backspace' || e.key === 'Delete'){
    const m = WIZ.capture;
    WIZ.bindings[m] = ''; WIZ.dirty = true; WIZ.tested = null;
    api('instrument_wizard_clear', Number(m));
    wizCaptureEnd(); wizDraw(); return;
  }
  const k = INST_CODE_KEY[e.code];
  if(!k){
    WIZ.msg = 'Cette touche ne peut pas être envoyée au jeu : utilise une lettre, un chiffre ou une ponctuation du clavier principal.';
    WIZ.msgKind = 'warn';
    wizDraw();
    return;
  }
  const m = WIZ.capture;
  WIZ.bindings[m] = k; WIZ.dirty = true; WIZ.tested = null; WIZ.msg = '';
  api('instrument_wizard_bind', Number(m), k);
  wizCaptureEnd();
  wizDraw();
  // enchainer : la note suivante encore vide passe en ecoute
  const next = WIZ.order.find(x => x > Number(m) && !WIZ.bindings[x]);
  if(next != null) setTimeout(() => wizCaptureBegin(next), 60);
}
function wizCaptureBegin(midi){
  if(WIZ.capture != null) wizCaptureEnd();
  WIZ.capture = midi; WIZ.msg = '';
  document.addEventListener('keydown', wizKeyDown, true);
  api('instrument_wizard_capture_begin');
  wizDraw();
  const el = $('wizBody').querySelector(`[data-cap="${midi}"]`);
  if(el) el.focus();
}
function wizCaptureEnd(){
  if(WIZ.capture == null) return;
  WIZ.capture = null;
  document.removeEventListener('keydown', wizKeyDown, true);
  api('instrument_wizard_capture_end');
}

// --- rendu des 5 etapes
function wizStepHtml(){
  const i = wizInst();
  const st = S || {};
  const kbl = instKbLayout(st);
  if(WIZ.step === 'open'){
    return `<div class="wiz__lead">${instImageHtml(WIZ.id, 'wiz__img', i.category)}
      <div><h3>${esc(cap(i.name || WIZ.id || ''))}</h3>
      <p>Ouvre <b>${esc(cap(i.name || ''))}</b> dans Heartopia et place-toi devant son clavier de jeu.</p></div></div>
      <div class="notice notice--info"><span class="notice__ic" aria-hidden="true">💡</span><div class="notice__text">
        Choisir un instrument ici n'équipe rien dans Heartopia : DodoTopia envoie seulement des touches à la fenêtre du jeu.
        Avant le test de l'étape 4, l'instrument doit déjà être ouvert dans le jeu.</div></div>
      ${i.percussive ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">⚠️</span><div class="notice__text">
        Cet instrument est une percussion. Les sources donnent une correspondance MIDI, mais rien ne prouve quelle frappe
        elle produit : le test de l'étape 4 te demandera quelle frappe tu as entendue.</div></div>` : ''}
      <p class="hint left">Tu peux revenir en arrière ou annuler à tout moment : le profil enregistré n'est remplacé
        qu'à la dernière étape.</p>`;
  }
  if(WIZ.step === 'layout'){
    const list = wizLayoutList();
    const documented = !!((WIZ.detail && WIZ.detail.layouts) || []).length;
    return `<p>Regarde le clavier de l'instrument <b>dans le jeu</b> et choisis la disposition qui lui ressemble.
        Deux dispositions de 15 notes n'utilisent pas les mêmes touches : compare les rangées.</p>
      ${documented ? '' : `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">⚠️</span><div class="notice__text">
        Aucune source ne documente les touches de cet instrument. Les dispositions ci-dessous sont des candidates :
        à toi de relever ce que tu vois, puis de corriger touche par touche à l'étape suivante.</div></div>`}
      <div class="wizlays">${list.map(l => `<button type="button" class="wizlay${l.layoutId === WIZ.layoutId ? ' active' : ''}"
          data-lay="${esc(l.layoutId)}" aria-pressed="${l.layoutId === WIZ.layoutId ? 'true' : 'false'}">
          <b>${esc(l.labelFr || l.layoutId)}${l.layoutId === WIZ.layoutId ? ' <span aria-hidden="true">✓</span>' : ''}</b>
          <span class="wizlay__d">${esc(l.descriptionFr || '')}</span>
          <span class="wizlay__n">${l.noteCount != null ? l.noteCount + ' notes' : ''}</span>
          <span class="wizlay__k">${(l.notes || []).slice(0, 24).map(n => `<i>${esc(instKeyLabel(n.key, kbl))}</i>`).join('')}${(l.notes || []).length > 24 ? '…' : ''}</span>
        </button>`).join('')}</div>
      <p class="hint left">Choisis dans Heartopia la même disposition qu'ici. L'emplacement exact de ce réglage dans le
        jeu n'est pas confirmé : DodoTopia ne te donnera pas un chemin de menus inventé.</p>`;
  }
  if(WIZ.step === 'bind'){
    const conf = wizConflicts();
    const byMidi = {};
    conf.forEach(c => { (byMidi[c.midi] = byMidi[c.midi] || []).push(c); });
    const rows = WIZ.order.map(m => {
      const k = WIZ.bindings[m] || '';
      const cs = byMidi[m] || [];
      const bad = cs.some(c => c.severity === 'error');
      return `<tr class="${bad ? 'is-bad' : ''}">
        <td class="instkeys__note">${esc(noteFr(m))}</td>
        <td class="instkeys__en">${esc(noteEn(m))}</td>
        <td><button type="button" class="keycap${WIZ.capture === m ? ' is-listening' : ''}" data-cap="${m}"
            aria-label="Touche pour ${esc(noteFr(m))}${k ? ' : ' + esc(instKeyLabel(k, kbl)) : ' : aucune'}">${WIZ.capture === m ? '…' : esc(instKeyLabel(k, kbl))}</button>
          ${k ? `<button type="button" class="instrowx" data-clr="${m}" aria-label="Effacer la touche de ${esc(noteFr(m))}" title="Effacer">×</button>` : ''}</td>
        <td class="wizconf">${cs.map(c => `<span class="chip chip--badge ${c.severity === 'error' ? 'chip--warn' : 'chip--info'}">${c.severity === 'error' ? '⚠️' : 'ℹ'} ${esc(c.message)}</span>`).join('')}</td>
      </tr>`;
    }).join('');
    return `<p>Clique sur une touche du tableau puis <b>appuie sur la touche</b> que tu utilises dans le jeu pour cette note.
        C'est la <b>position</b> de la touche qui est retenue, pas la lettre imprimée dessus.</p>
      <p class="hint left">Échap annule la saisie en cours, Retour arrière efface l'association.
        Rien n'est envoyé au jeu et les raccourcis globaux sont débranchés pendant la capture.</p>
      <div class="wizbar">
        <span class="chip chip--badge ${wizBound() === WIZ.order.length ? 'chip--ok' : 'chip--warn'}">${wizBound()} / ${WIZ.order.length} notes associées</span>
        <div class="spacer"></div>
        <button class="btn btn--ghost btn--sm" type="button" data-act="reset">Repartir de la disposition</button>
      </div>
      <div class="tablewrap tablewrap--tall"><table class="instkeys">
        <thead><tr><th scope="col">Note</th><th scope="col">Nom international</th>
          <th scope="col">Touche (${esc(kbl.toUpperCase())})</th><th scope="col">Conflits</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
  }
  if(WIZ.step === 'test'){
    const wz = (S && S.instrument_wizard) || null;
    const test = (wz && wz.test) || null;
    const tstate = (test && test.state) || '';
    const sample = wizTestSample();
    // seuls « countdown » et « playing » sont des etats ACTIFS : un test annule ou en erreur doit laisser
    // le bouton relancable, sinon l'etape reste figee sur « Test en cours… » sans aucun moyen de repartir.
    const running = ['countdown', 'playing'].includes(tstate) || WIZ.testing;
    // cle du contrat cote Python : test.remaining (seconds_left accepte par tolerance)
    const left = test ? (test.remaining != null ? test.remaining : test.seconds_left) : null;
    const answered = WIZ.tested;
    const full = WIZ.mode === 'full';
    const bound = WIZ.order.filter(m => WIZ.bindings[m]).length;
    const done = ((wz && wz.verified) || []).length;
    const stopKey = (S && S.hotkeys && S.hotkeys.stop) || 'F7';
    const failed = ['cancelled', 'error'].includes(tstate);
    return `<p>Le test envoie <b>au plus 3 touches</b> à Heartopia. DodoTopia réduit sa fenêtre, compte à rebours,
        puis envoie. Le bouton <b>Arrêter le test</b> ci-dessous et le raccourci d'arrêt (${esc(stopKey)}) coupent
        l'envoi immédiatement.</p>
      <div class="notice notice--info"><span class="notice__ic" aria-hidden="true">💡</span><div class="notice__text">
        Heartopia doit être au premier plan avec ${esc(cap(wizInst().name || ''))} ouvert. Choisir l'instrument dans
        DodoTopia ne l'équipe pas dans le jeu.</div></div>
      ${full ? `<div class="notice notice--info"><span class="notice__ic" aria-hidden="true">✓</span><div class="notice__text">
        <b>Validation intégrale</b> : ${done} association${done > 1 ? 's' : ''} vérifiée${done > 1 ? 's' : ''} sur ${bound}.
        Chaque passage reprend là où tu t'es arrêté, par groupes de trois touches. Le statut
        « Confirmé sur cet ordinateur » n'est écrit qu'une fois <b>toutes</b> les associations vérifiées.</div></div>` : ''}
      <div class="wizbar">
        <span class="hint left">Touches envoyées : ${sample.map(m => `<b>${esc(instKeyLabel(WIZ.bindings[m], kbl))}</b> (${esc(noteFr(m))})`).join(' · ') || '—'}</span>
        <div class="spacer"></div>
        ${running ? '<button class="btn btn--secondary btn--sm" type="button" data-act="teststop">Arrêter le test</button>' : ''}
        <button class="btn btn--cta btn--sm" type="button" data-act="test" ${running || !sample.length ? 'disabled' : ''}>
          ${running ? 'Test en cours…' : (done ? 'Tester le groupe suivant' : 'Lancer le test')}</button>
      </div>
      ${running && left != null ? `<p class="hint left">Bascule vers Heartopia : ${esc(String(Math.max(0, Math.ceil(left))))} s…</p>` : ''}
      ${running && tstate === 'playing' ? '<p class="hint left">Envoi des touches en cours…</p>' : ''}
      ${failed ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">⚠️</span><div class="notice__text">
        ${esc(test.message || 'Le test ne s’est pas déroulé jusqu’au bout.')} Aucune conclusion n'en est tirée :
        relance-le quand tu veux.</div></div>` : ''}
      ${tstate === 'answer'
        ? (wizPercussive()
          ? `<fieldset class="wizask"><legend>Qu'as-tu entendu ?</legend>
              <p class="hint left">Sur une percussion, la question n'est pas « était-ce un Do ? » mais quelle frappe a sonné.</p>
              ${WIZ_STRIKES.map(([v, lab]) => `<button type="button" class="btn btn--secondary btn--sm" data-strike="${esc(v)}">${esc(lab)}</button>`).join(' ')}
            </fieldset>`
          : `<fieldset class="wizask"><legend>Qu'as-tu entendu ?</legend>
              <p class="hint left">Attendu : ${esc(((test && test.solfege) || sample.map(noteFr)).join(', ') || '—')}.</p>
              <button type="button" class="btn btn--secondary btn--sm" data-ans="1">Ces notes exactement</button>
              <button type="button" class="btn btn--secondary btn--sm" data-ans="0">Non : autre chose, ou rien</button>
            </fieldset>`)
        : `<p class="hint left">La question « qu'as-tu entendu ? » n'apparaît qu'une fois les touches réellement
            envoyées : DodoTopia ne te demande jamais de valider un test qui n'a pas eu lieu.</p>`}
      ${answered ? `<div class="notice notice--${answered.ok ? 'ok' : 'warn'}"><span class="notice__ic" aria-hidden="true">${answered.ok ? '✓' : '⚠️'}</span>
        <div class="notice__text">${answered.ok
          ? (full
            ? `Groupe vérifié : ${done} association${done > 1 ? 's' : ''} sur ${bound}.`
              + (bound && done >= bound
                ? ' Toutes les associations sont vérifiées : le profil sera enregistré « Confirmé sur cet ordinateur ».'
                : ' Continue avec le groupe suivant.')
            : 'Test rapide réussi · vérification partielle. Trois touches ne prouvent pas les ' + WIZ.order.length + ' associations : la validation intégrale reste à faire.')
          : 'Réponse enregistrée : le profil restera « touches personnalisées · à vérifier ». Reviens à l’étape précédente pour corriger.'}</div></div>` : ''}
      <p class="hint left">Tu peux aussi passer cette étape : le profil sera enregistré comme « à vérifier ».</p>`;
  }
  // save
  const conf = wizConflicts();
  const hard = wizBlocking(conf);
  // statut annonce = celui que Python ECRIRA (next_status) : on n'annonce jamais plus que ce qui sera fait
  const wzs = (S && S.instrument_wizard) || null;
  const status = hard.length ? null
    : ((wzs && wzs.next_status) || (WIZ.tested && WIZ.tested.ok ? 'quick-tested' : 'custom'));
  return `<p>Profil de <b>${esc(cap(i.name || WIZ.id || ''))}</b> :</p>
    <dl class="instdet__facts">
      <dt>Disposition</dt><dd>${esc(instLayoutLabel(WIZ.layoutId) || 'saisie manuelle')}</dd>
      <dt>Notes associées</dt><dd>${wizBound()} sur ${WIZ.order.length}</dd>
      <dt>Clavier utilisé pour l'affichage</dt><dd>${esc(instKbLayout(S).toUpperCase())}</dd>
      <dt>Statut enregistré</dt><dd>${hard.length ? '— (conflits à corriger)' : esc(instStatus(status).label)}</dd>
    </dl>
    ${hard.length ? `<div class="notice notice--danger"><span class="notice__ic" aria-hidden="true">⚠️</span><div class="notice__text">
        ${hard.length} conflit${hard.length > 1 ? 's' : ''} à corriger avant d'enregistrer : ${esc(hard.map(c => noteFr(c.midi)).join(', '))}.
        Reviens à l'étape « Touches ». Aucun raccourci d'arrêt ne sera supprimé pour accepter ce mapping.</div></div>` : ''}
    <p class="hint left">Ce statut décrit ce qui a réellement été fait sur cet ordinateur. Il ne dit jamais que le profil
      a été validé dans Heartopia tant que toutes les touches n'ont pas été vérifiées une par une.</p>`;
}
function wizDraw(){
  if(!$('wizOverlay').classList.contains('open')) return;
  const idx = WIZ_STEPS.indexOf(WIZ.step);
  txt('wizTitle', WIZ_TITLES[WIZ.step] || 'Configurer les touches');
  txt('wizCount', `Étape ${idx + 1} sur ${WIZ_STEPS.length} · ${cap(wizInst().name || '')}`);
  $('wizFill').style.width = Math.round((idx / (WIZ_STEPS.length - 1)) * 100) + '%';
  stepsMark($('wizSteps'), WIZ_STEPS.slice(0, idx), WIZ.step, {});
  const body = $('wizBody');
  body.innerHTML = wizStepHtml();
  setNotice('wizMsg', WIZ.msg ? {text: WIZ.msg, kind: WIZ.msgKind || 'warn'} : null);

  body.querySelectorAll('[data-lay]').forEach(b => b.onclick = () => { wizLoadLayout(b.dataset.lay); wizDraw(); });
  body.querySelectorAll('[data-cap]').forEach(b => b.onclick = () => wizCaptureBegin(Number(b.dataset.cap)));
  body.querySelectorAll('[data-clr]').forEach(b => b.onclick = () => {
    const m = Number(b.dataset.clr);
    WIZ.bindings[m] = ''; WIZ.dirty = true; WIZ.tested = null;
    api('instrument_wizard_clear', m);
    wizDraw();
  });
  const rst = body.querySelector('[data-act="reset"]');
  if(rst) rst.onclick = () => { if(WIZ.layoutId) wizLoadLayout(WIZ.layoutId); wizDraw(); };
  const tb = body.querySelector('[data-act="test"]');
  if(tb) tb.onclick = () => wizRunTest();
  const ts = body.querySelector('[data-act="teststop"]');
  if(ts) ts.onclick = () => wizStopTest();
  body.querySelectorAll('[data-ans]').forEach(b => b.onclick = () => wizAnswer(b.dataset.ans === '1', null));
  body.querySelectorAll('[data-strike]').forEach(b => b.onclick = () => wizAnswer(b.dataset.strike !== 'none', b.dataset.strike));

  $('wizBack').disabled = idx === 0;
  const next = $('wizNext');
  if(WIZ.step === 'save'){
    next.textContent = 'Enregistrer ce profil';
    next.disabled = wizBlocking(wizConflicts()).length > 0 || !wizBound();
  } else if(WIZ.step === 'test'){
    next.textContent = WIZ.tested ? 'Continuer' : 'Passer le test';
    next.disabled = false;
  } else {
    next.textContent = 'Continuer';
    next.disabled = (WIZ.step === 'layout' && !WIZ.layoutId) || (WIZ.step === 'bind' && !wizBound());
  }
  // saisie en cours : la touche ecoutee reprend le focus apres la reconstruction du corps
  if(WIZ.capture != null){
    const el = body.querySelector(`[data-cap="${WIZ.capture}"]`);
    if(el && document.activeElement !== el) el.focus();
  }
}
// Echantillon envoye au jeu. En validation integrale, on avance dans les associations NON ENCORE
// verifiees : sans cela les passages successifs retesteraient toujours les trois memes notes et le statut
// « Confirmé sur cet ordinateur » resterait inatteignable. En assistant court, on garde un echantillon
// reparti grave / milieu / aigu, plus parlant que trois voisines (meme regle que le repli cote Python).
function wizTestSample(){
  const bound = WIZ.order.filter(m => WIZ.bindings[m]);
  if(!bound.length) return [];
  if(WIZ.mode === 'full'){
    const wz = (S && S.instrument_wizard) || null;
    const seen = {};
    ((wz && wz.verified) || []).forEach(m => { seen[Number(m)] = true; });
    const rest = bound.filter(m => !seen[Number(m)]);
    return (rest.length ? rest : bound).slice(0, 3);
  }
  const idx = [0, Math.floor(bound.length / 2), bound.length - 1]
    .filter((v, k, a) => a.indexOf(v) === k).sort((a, b) => a - b);
  return idx.map(k => bound[k]);
}
function wizStopTest(){
  WIZ.testing = false;
  api('instrument_wizard_test_stop').then(() => wizDraw());
}
function wizRunTest(){
  const sample = wizTestSample();
  if(!sample.length) return;
  if(S && S.state !== 'stopped'){ WIZ.msg = 'Arrête la lecture avant de tester les touches.'; WIZ.msgKind = 'warn'; wizDraw(); return; }
  WIZ.testing = true; WIZ.msg = ''; wizDraw();
  api('instrument_wizard_test', sample).finally(() => { WIZ.testing = false; wizDraw(); });
}
function wizAnswer(ok, strike){
  WIZ.tested = {ok: !!ok, strike: strike || null};
  api('instrument_wizard_answer', !!ok, strike || null);
  wizDraw();
}
function wizGoto(step){
  wizCaptureEnd();
  WIZ.step = step; WIZ.msg = '';
  api('instrument_wizard_goto', step);
  wizDraw();
}
function wizNext(){
  const idx = WIZ_STEPS.indexOf(WIZ.step);
  if(WIZ.step === 'save'){ wizSave(); return; }
  if(WIZ.step === 'layout' && !WIZ.order.length && WIZ.layoutId) wizLoadLayout(WIZ.layoutId);
  wizGoto(WIZ_STEPS[Math.min(WIZ_STEPS.length - 1, idx + 1)]);
}
function wizBack(){
  const idx = WIZ_STEPS.indexOf(WIZ.step);
  if(idx <= 0) return;
  wizCaptureEnd();
  WIZ.step = WIZ_STEPS[idx - 1]; WIZ.msg = '';
  api('instrument_wizard_back');
  wizDraw();
}
function wizSave(){
  const hard = wizBlocking(wizConflicts());
  if(hard.length){ WIZ.msg = 'Corrige les conflits avant d’enregistrer.'; WIZ.msgKind = 'danger'; wizDraw(); return; }
  const id = WIZ.id, label = cap(wizInst().name || id || '');
  api('instrument_wizard_save').then(r => {
    instForget();
    if(WIZ.id !== id) return;                 // un autre assistant a ete ouvert entre-temps
    // Python renvoie {ok, error, state} : sans ce verdict, un refus (lecture en cours, conflit calcule
    // cote moteur) fermait la modale en annoncant « Profil enregistré » et le travail etait perdu.
    if(r && typeof r === 'object' && r.ok === false){
      WIZ.msg = r.error || "Le profil n'a pas été enregistré.";
      WIZ.msgKind = 'danger';
      const wz = (S && S.instrument_wizard) || null;
      if(wz && wz.step) WIZ.step = WIZ_STEPS[Math.max(0, Math.min(WIZ_STEPS.length - 1, Number(wz.step) - 1))];
      wizDraw();
      return;
    }
    wizCaptureEnd();
    closeModal($('wizOverlay'));
    toast('Profil enregistré pour ' + label, 'ok');
    WIZ.id = null; WIZ.dirty = false;
  });
}
function wizCancel(){
  const done = () => {
    wizCaptureEnd();
    api('instrument_wizard_cancel');
    closeModal($('wizOverlay'));
    WIZ.id = null; WIZ.dirty = false;
  };
  if(!WIZ.dirty){ done(); return; }
  dialog({title: 'Abandonner la configuration ?', icon: '⌨',
    html: '<p>Les touches saisies dans l’assistant seront perdues. Le profil déjà enregistré pour cet instrument reste inchangé.</p>',
    ok: 'Abandonner', cancel: 'Continuer', danger: true}).then(v => { if(v) done(); });
}
function openInstrumentWizard(id, mode){
  const st = S || {};
  id = id || (instActive(st) || {}).id;
  const i = instFromState(id, st);
  if(!i){ toast('Instrument introuvable', 'warn'); return; }
  // Python refuse d'ouvrir l'assistant pendant une lecture (preecoute comprise : elle laisse #instRow
  // visible). On ne presente pas une modale qui n'enregistrerait rien.
  if(instPlaying(st)){ toast('Arrête la lecture avant de configurer les touches.', 'warn'); return; }
  WIZ.id = id; WIZ.mode = mode === 'full' ? 'full' : 'setup'; WIZ.step = 'open';
  WIZ.bindings = {}; WIZ.order = []; WIZ.layoutId = null; WIZ.capture = null;
  WIZ.msg = ''; WIZ.tested = null; WIZ.testing = false; WIZ.dirty = false; WIZ.detail = null;
  openModal($('wizOverlay'), $('instPick'), () => { wizCaptureEnd(); });
  wizDraw();
  // le focus doit ENTRER dans la modale : sinon la tabulation repart dans les commandes du lecteur derriere
  setTimeout(() => { const b = $('wizBody'); if(b && $('wizOverlay').classList.contains('open')) b.focus(); }, 30);
  api('instrument_wizard_start', id, WIZ.mode).then(r => {
    // refus cote Python : l'etat revient sans assistant. Le toast est deja affiche, on referme.
    if(r && r.songs && r.instrument_wizard == null){
      wizCaptureEnd();
      closeModal($('wizOverlay'));
      WIZ.id = null; WIZ.dirty = false;
      return null;
    }
    return instCatalogue().then(() => instDetail(id, true));
  }).then(d0 => {
    if(WIZ.id !== id) return;
    const d = d0 || instFallbackDetail(i);
    WIZ.detail = d;
    const prof = (d && d.profile) || {};
    const notes = (d && d.notes) || [];
    WIZ.layoutId = prof.layoutId || i.layout_id || (d && d.layouts && d.layouts[0] && d.layouts[0].layoutId) || null;
    if(notes.length){
      WIZ.order = notes.map(n => Number(n.midi));
      WIZ.bindings = {};
      notes.forEach(n => { WIZ.bindings[n.midi] = n.key || ''; });
    } else if(WIZ.layoutId){
      wizLoadLayout(WIZ.layoutId);
    }
    WIZ.dirty = false;
    wizDraw();
  });
}
// compte a rebours / etat du test cote Python : on repeint l'etape 4
view('instWiz', {
  sig: st => $('wizOverlay').classList.contains('open') ? JSON.stringify((st.instrument_wizard || {}).test || null) + '#' + WIZ.step : 'closed',
  draw: () => wizDraw(),
});

// ------------------------------------------------ cablage
(function instWire(){
  const pick = $('instPick');
  if(pick) pick.onclick = () => openInstrumentSelector();
  const keys = $('btnKeys');
  if(keys) keys.onclick = () => {
    const ins = instActive(S || {});
    if(ins && !ins.ready) openInstrumentWizard(ins.id, 'setup');
    else openKeysPanel(ins && ins.id);
  };
  const close = () => closeInstrumentSelector();
  if($('instSelClose')) $('instSelClose').onclick = close;
  if($('instSelCancel')) $('instSelCancel').onclick = close;
  $('instOverlay').onclick = e => { if(e.target === $('instOverlay')) close(); };
  const f = $('instSearch');
  if(f){
    f.oninput = () => { INST.q = f.value; $('instSearchBox').classList.toggle('has', !!f.value); instSelDraw(); };
    f.onkeydown = e => {
      if(e.key === 'Escape' && f.value){ e.stopPropagation(); f.value = ''; INST.q = ''; $('instSearchBox').classList.remove('has'); instSelDraw(); }
      if(e.key === 'ArrowDown' || e.key === 'Enter'){
        e.preventDefault();
        const c = $('instGrid').querySelector('.instcard[tabindex="0"]') || $('instGrid').querySelector('.instcard');
        if(c) c.focus();
      }
    };
  }
  if($('instSearchClr')) $('instSearchClr').onclick = () => { f.value = ''; INST.q = ''; $('instSearchBox').classList.remove('has'); instSelDraw(); f.focus(); };
  $('instGrid').addEventListener('keydown', instGridKeys);
  if($('wizClose')) $('wizClose').onclick = () => wizCancel();
  if($('wizCancel')) $('wizCancel').onclick = () => wizCancel();
  if($('wizBack')) $('wizBack').onclick = () => wizBack();
  if($('wizNext')) $('wizNext').onclick = () => wizNext();
  $('wizOverlay').onclick = e => { if(e.target === $('wizOverlay')) wizCancel(); };
  document.addEventListener('keydown', e => {
    if(e.key !== 'Escape' || $('dlgOverlay').classList.contains('open')) return;
    if($('wizOverlay').classList.contains('open')){ e.preventDefault(); wizCancel(); return; }
    if($('instOverlay').classList.contains('open')){ e.preventDefault(); close(); }
  });
})();
