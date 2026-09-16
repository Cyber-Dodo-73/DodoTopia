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
// Tous les libelles passent par t() AU MOMENT DU RENDU (le catalogue change a chaud) : ici, seules des cles.
const INST_CATS = ['strings', 'winds', 'keys', 'percussion'];
// cles par famille (declarees pour i18n_check) : t('inst.picker.cat_strings') t('inst.picker.cat_winds')
// t('inst.picker.cat_keys') t('inst.picker.cat_percussion')
const INST_CAT_KEY = {strings: 'inst.picker.cat_strings', winds: 'inst.picker.cat_winds', keys: 'inst.picker.cat_keys', percussion: 'inst.picker.cat_percussion'};
function instCatLabel(cat){ return INST_CAT_KEY[cat] ? t(INST_CAT_KEY[cat]) : ''; }
// statut de verification : cle du libelle + teinte de pastille. Jamais « teste dans Heartopia ».
// cles par statut (declarees pour i18n_check) : t('inst.status.unknown') t('inst.status.documented')
// t('inst.status.custom') t('inst.status.quick_tested') t('inst.status.confirmed')
const INST_STATUS = {
  unknown:        {key: 'inst.status.unknown',      chip: 'chip--warn'},
  documented:     {key: 'inst.status.documented',   chip: 'chip--info'},
  custom:         {key: 'inst.status.custom',       chip: 'chip--info'},
  'quick-tested': {key: 'inst.status.quick_tested', chip: 'chip--warn'},
  confirmed:      {key: 'inst.status.confirmed',    chip: 'chip--ok'},
};
function instStatus(s){ const e = INST_STATUS[s] || INST_STATUS.unknown; return {label: t(e.key), chip: e.chip}; }
// nom affiche d'un instrument : `name` (francais) ou `label_en` hors francais (le catalogue moteur porte les deux)
function instName(inst){
  if(!inst) return '';
  const en = I18N.lang !== 'fr' && inst.label_en;
  return cap(String(en || inst.name || inst.id || ''));
}
// libelle / description d'une disposition du catalogue : labelEn hors francais quand il existe, sinon labelFr
function instLayText(l, field){
  if(!l) return '';
  const fr = l[field + 'Fr'] != null ? l[field + 'Fr'] : l[field];
  const en = l[field + 'En'];
  return String((I18N.lang !== 'fr' && en) ? en : (fr || ''));
}

// noms de notes, convention d'affichage du dossier : Do4 / C4 = MIDI 60. Le nom depend de la langue :
// NOTE_NAMES (core.js) donne la forme locale (« DO#, RÉ… » ou « C#, D… »), ramenee a la casse du dossier.
const INST_EN = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
function instNoteBase(pc){
  const names = (typeof NOTE_NAMES === 'function') ? NOTE_NAMES() : NOTE_NAMES;
  const raw = String((names && names[pc]) || INST_EN[pc]);
  return cap(raw.toLowerCase()).replace('#', '♯');
}
function noteFr(m){ m = Number(m); return instNoteBase(((m % 12) + 12) % 12) + (Math.floor(m / 12) - 1); }
function noteEn(m){ m = Number(m); return INST_EN[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1); }
function noteOctave(m){ return Math.floor(Number(m) / 12) - 1; }
// une note peut arriver en entier MIDI (contrat) ou deja detaillee {midi, solfege} : les deux se lisent.
// `solfege` vient du moteur en francais : hors francais, on recalcule le nom local a partir du MIDI.
function instNoteText(n){
  if(n != null && typeof n === 'object') return (I18N.lang === 'fr' && n.solfege) || noteFr(n.midi);
  return noteFr(n);
}
function instSolfege(n){ return (I18N.lang === 'fr' && n.solfege) || noteFr(n.midi); }
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
  img.title = instCatLabel(cat) ? t('inst.picker.image_unavailable_cat', {cat: instCatLabel(cat)}) : t('inst.picker.image_unavailable');
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
  return (l && instLayText(l, 'label')) || id || '';
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
  if(!ins.ready) return ins.blocked_reason || t('inst.status.blocked');
  const out = [];
  const n = ins.count != null ? ins.count : (ins.keys || []).length;
  if(n) out.push(t('inst.picker.notes_n', {n}));
  if(ins.lowest != null && ins.span != null && n) out.push(t('inst.picker.range', {low: noteFr(ins.lowest), high: noteFr(ins.lowest + ins.span)}));
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
  txt('instPickName', (ins && ins.name) ? instName(ins) : t('inst.picker.none'));
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
  if(keys) keys.textContent = (ins && ins.ready) ? t('inst.picker.keys') : t('inst.picker.setup');
  // meme condition que music.js : pendant une session, la ligne instrument laisse la place au bandeau
  const sum = $('instSum');
  if(sum) sum.hidden = !!($('instRow') && $('instRow').hidden);
}
view('instPick', {
  sig: st => {
    const i = instActive(st) || {};
    return [i.id, i.status, i.ready, i.count, i.layout_id, i.lowest, i.span, st.keyboard_layout, I18N.lang,
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
  const tabs = [['all', t('inst.picker.filter_all')]];
  if(instFavs(st).length) tabs.push(['fav', t('inst.picker.filter_fav')]);            // pas de filtre vide
  INST_CATS.forEach(id => { if(list.some(i => i.category === id)) tabs.push([id, instCatLabel(id)]); });
  if(!tabs.some(tab => tab[0] === INST.filter)) INST.filter = 'all';
  const sig = tabs.map(tab => tab[0] + ':' + tab[1]).join(',') + '#' + INST.filter;
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
  const name = instName(i);
  return `<div class="instcell">
    <button type="button" class="instcard${isActive ? ' is-active' : ''}${isSel ? ' is-sel' : ''}" data-id="${esc(i.id)}"
        aria-current="${isSel ? 'true' : 'false'}" tabindex="${isSel ? '0' : '-1'}">
      <span class="instcard__check" aria-hidden="true">${icon('check')}</span>
      ${instImageHtml(i.id, 'instcard__img', i.category)}
      <span class="instcard__name">${esc(name)}</span>
      <span class="sr-only">${esc(t('inst.picker.card_sr', {cat: instCatLabel(i.category), active: isActive ? 'yes' : 'no', status: stt.label}))}</span>
    </button>
    <button type="button" class="instfav${fav ? ' on' : ''}" data-fav="${esc(i.id)}" aria-pressed="${fav ? 'true' : 'false'}"
      title="${esc(fav ? t('inst.picker.fav_remove') : t('inst.picker.fav_add'))}"
      aria-label="${esc(fav ? t('inst.picker.fav_remove_aria', {name}) : t('inst.picker.fav_add_aria', {name}))}">${icon(fav ? 'star-fill' : 'star')}</button>
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
  const sig = rows.map(i => [i.id, i.status, i.ready].join('~')).join(',') + '#' + INST.sel + '#' + activeId + '#' + instFavs(st).join(',') + '#' + I18N.lang;
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
  txt('instSelCount', rows.length ? t('inst.picker.count', {n: rows.length, total: (st.instruments || []).length}) : '');
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
  if(!i){ box.innerHTML = `<p class="hint left">${esc(t('inst.picker.choose'))}</p>`; return; }
  const d = instDetailCached(id);
  const stt = instStatus(i.status);
  const activeId = (instActive(st) || {}).id;
  const fav = instFavs(st).includes(id);
  const layouts = (d && d.layouts) || [];
  const lay = layouts.find(l => l.layoutId === i.layout_id) || null;
  const missing = (d && d.missing_notes) || [];
  const srcs = (d && d.source_urls) || i.source_urls || [];
  const name = instName(i);
  // sous-titre : l'autre nom (anglais en francais, francais ailleurs) quand il differe, puis la famille
  const other = I18N.lang === 'fr' ? (i.label_en || '') : (i.name && cap(i.name) !== name ? cap(i.name) : '');

  const notesTxt = i.ready
    ? t('inst.picker.notes_range', {n: i.count != null ? i.count : (i.keys || []).length, low: noteFr(i.lowest), high: noteFr(i.lowest + (i.span || 0))})
    : (i.blocked_reason || t('inst.picker.no_keys'));
  // « 15 notes · Do4 -> Do6 · 3 rangees » : ce qu'on a besoin de savoir avant de choisir, en une ligne.
  const layLabel = lay ? (instLayText(lay, 'label') || lay.layoutId) : (i.layout_label || instLayoutLabel(i.layout_id) || '');
  const factsTxt = i.ready
    ? [notesTxt, String(layLabel).replace(/^\d+\s+notes?,?\s*/, '')].filter(Boolean).join(' · ')
    : notesTxt;
  const missTxt = missing.length
    ? `<p class="instdet__warnline">${esc(t('inst.picker.missing_alt', {list: missing.slice(0, 8).map(instNoteText).join(', '), more: missing.length > 8 ? 'yes' : 'no'}))}</p>`
    : '';
  const percTxt = i.percussive ? `<p class="instdet__warnline">${esc(t('inst.picker.percussion_warn'))}</p>` : '';

  const main = i.ready
    ? `<button class="btn btn--cta" type="button" data-act="use"${id === activeId ? ' disabled' : ''}>${esc(id === activeId ? t('inst.picker.active') : t('inst.picker.use'))}</button>`
    : `<button class="btn btn--cta" type="button" data-act="setup">${esc(t('inst.picker.setup'))}</button>`;

  box.innerHTML = `
    <div class="instdet__top">
      ${instImageHtml(id, 'instdet__img', i.category)}
      <div class="instdet__id">
        <h3>${esc(name)}</h3>
        <p class="instdet__en">${esc(other)}${other && i.category ? ' · ' : ''}${esc(instCatLabel(i.category))}</p>
        <span class="chip chip--badge ${stt.chip}">${esc(stt.label)}</span>
      </div>
      <button type="button" class="instfav${fav ? ' on' : ''}" data-act="fav" aria-pressed="${fav ? 'true' : 'false'}"
        title="${esc(fav ? t('inst.picker.fav_remove') : t('inst.picker.fav_add'))}">${icon(fav ? 'star-fill' : 'star')}</button>
    </div>
    <p class="instdet__facts1">${esc(factsTxt)}</p>
    ${percTxt}
    <div class="instdet__acts">
      ${main}
      <button class="btn btn--secondary btn--sm" type="button" data-act="keys">${esc(t('inst.picker.keys'))}</button>
      ${i.ready ? `<button class="btn btn--ghost btn--sm" type="button" data-act="setup">${esc(t('inst.picker.reconfigure'))}</button>` : ''}
    </div>
    ${layouts.length > 1 ? `<details class="disclosure"><summary>${esc(t('inst.picker.layouts_summary', {n: layouts.length}))}</summary>
      <div class="disclosure__body"><p class="hint left">${esc(t('inst.picker.layouts_hint'))}</p>
      <div class="instlays">${layouts.map(l => `<button type="button" class="instlay${l.layoutId === i.layout_id ? ' active' : ''}" data-lay="${esc(l.layoutId)}">
        <b>${esc(instLayText(l, 'label') || l.layoutId)}</b><span>${esc(instLayText(l, 'description'))}</span>
        <span class="instlay__n">${l.noteCount != null ? esc(t('inst.picker.notes_n', {n: l.noteCount})) : ''}</span></button>`).join('')}</div></div></details>` : ''}
    <details class="disclosure"><summary>${esc(t('inst.picker.tech_summary'))}</summary>
      <div class="disclosure__body">
        ${missTxt}
        ${i.ready ? `<div class="btnrow"><button class="btn btn--ghost btn--sm" type="button" data-act="full"
          title="${esc(t('inst.picker.full_title'))}">${esc(t('inst.picker.full'))}</button></div>` : ''}
        <dl class="instdet__facts instdet__facts--tech">
          <dt>${esc(t('inst.picker.dt_id'))}</dt><dd>${esc(id)}</dd>
          <dt>${esc(t('inst.picker.dt_layout'))}</dt><dd>${esc(i.layout_id || '—')}</dd>
          <dt>${esc(t('inst.picker.dt_variants'))}</dt><dd>${esc(t('inst.picker.variants_note', {n: i.variant_count != null ? String(i.variant_count) : '—'}))}</dd>
          <dt>${esc(t('inst.picker.dt_provenance'))}</dt><dd>${esc(instProvenance(i))}</dd>
        </dl>
        ${srcs.length ? `<p class="hint left">${esc(t('inst.picker.sources'))}</p><ul class="instsrc">${srcs.map(u => `<li><code>${esc(u)}</code></li>`).join('')}</ul>
          <button class="btn btn--ghost btn--sm" type="button" data-act="copysrc">${esc(t('inst.picker.copy_sources'))}</button>` : ''}
        <p class="hint left">${esc(t('inst.picker.hint_community'))}</p>
        <p class="hint left">${esc(t('inst.picker.hint_json'))}</p>
        <div class="btnrow">
          <button class="btn btn--ghost btn--sm" type="button" data-act="export">${esc(t('inst.picker.export'))}</button>
          <button class="btn btn--ghost btn--sm" type="button" data-act="import">${esc(t('inst.picker.import'))}</button>
        </div>
      </div>
    </details>`;

  const on = (sel, fn) => box.querySelectorAll(sel).forEach(b => b.onclick = fn);
  on('[data-act="use"]', () => instUse(id));
  on('[data-act="setup"]', () => { closeModal($('instOverlay')); openInstrumentWizard(id, 'setup'); });
  on('[data-act="full"]', () => { closeModal($('instOverlay')); openInstrumentWizard(id, 'full'); });
  on('[data-act="keys"]', () => { closeModal($('instOverlay')); openKeysPanel(id); });
  on('[data-act="fav"]', () => api('toggle_instrument_favorite', id).then(() => instSelDraw()));
  on('[data-act="copysrc"]', () => copyText(srcs.join('\n'), t('inst.picker.sources_copied')));
  on('[data-act="export"]', () => instExportProfile(id));
  on('[data-act="import"]', () => instImportProfile(id));
  box.querySelectorAll('[data-lay]').forEach(b => b.onclick = () => instSetLayout(id, b.dataset.lay));

  if(!d) instDetail(id).then(r => { if(r && INST.sel === id) instDetailDraw(); });
}
function instProvenance(i){
  if(i.status === 'confirmed') return t('inst.status.provenance_confirmed');
  if(i.status === 'quick-tested') return t('inst.status.provenance_quick_tested');
  if(i.status === 'custom') return t('inst.status.provenance_custom');
  if(i.status === 'documented') return t('inst.status.provenance_documented');
  return t('inst.status.provenance_unknown');
}
// Export / import d'un profil : les deux methodes existent cote Python (schema valide, rien n'est
// execute). Sans point d'entree ici, la documentation promettrait une fonction inatteignable.
function instExportProfile(id){
  apiOpt('export_instrument_profile', id).then(r => {
    if(r && r.ok === false){ toast(r.error || t('inst.picker.export_failed'), 'warn'); return; }
    if(r && r.path) return;                                  // enregistre par la boite de dialogue systeme
    if(r && r.text) copyText(r.text, t('inst.picker.profile_copied'));
  });
}
function instImportProfile(id){
  const i = instFromState(id) || {};
  if(instPlaying()){ toast(t('inst.picker.stop_before_import'), 'warn'); return; }
  // le nom d'instrument entre dans un message HTML : echappe avant
  dialog({title: t('inst.picker.import_title'), icon: 'keyboard',
    html: t('inst.picker.import_html', {name: esc(instName(i) || id)}),
    ok: t('inst.picker.import_ok'), cancel: t('common.cancel')}).then(okv => {
      if(!okv) return;
      api('import_instrument_profile', null, id).then(() => { instForget(); instSelDraw(); });
    });
}
function instUse(id){
  const i = instFromState(id);
  if(i && !i.ready){ openInstrumentWizard(id, 'setup'); return; }
  // le choix est fait : la fenetre se ferme, comme n'importe quel selecteur. Rester ouvert obligeait
  // a cliquer une deuxieme fois sur « Fermer » pour revenir a ce qu'on etait en train de faire.
  api('set_instrument', id).then(() => { closeInstrumentSelector(); toast(t('inst.picker.chosen', {name: instName(i) || id}), 'ok'); });
}
function instSetLayout(id, layoutId){
  const i = instFromState(id);
  if(i && i.custom){
    dialog({title: t('inst.picker.replace_title'), icon: 'keyboard',
      html: t('inst.picker.replace_html', {layout: esc(instLayoutLabel(layoutId))}),
      ok: t('inst.picker.replace_ok'), cancel: t('common.cancel'), danger: true}).then(okv => {
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
  openModal($('instOverlay'), $('instPick'), null, closeInstrumentSelector);
  instSelDraw();
  instCatalogue().then(() => instSelDraw());
  if(INST.sel) instDetail(INST.sel).then(() => instSelDraw());
  setTimeout(() => { if(f) f.focus(); }, 30);
}
function closeInstrumentSelector(){ closeModal($('instOverlay')); }
// le selecteur ouvert suit l'etat (changement d'instrument, favoris, fin d'assistant)
view('instSel', {
  sig: st => $('instOverlay').classList.contains('open')
    ? (st.instruments || []).map(i => [i.id, i.status, i.ready].join('~')).join(',') + '#' + st.instrument_id + '#' + instFavs(st).join(',') + '#' + I18N.lang
    : 'closed',
  draw: () => instSelDraw(),
});

// ------------------------------------------------ panneau « Voir les touches »
// cles par affectation (declarees pour i18n_check) : t('inst.keys.assign_layout') t('inst.keys.assign_custom') t('inst.keys.assign_none')
const INST_ASSIGN = {
  layout: ['inst.keys.assign_layout', 'chip--info'],
  custom: ['inst.keys.assign_custom', 'chip--warn'],
  none: ['inst.keys.assign_none', 'chip--warn'],
};
function instKeyRowsHtml(d, kbl){
  const rows = (d && d.rows) || [];
  if(!rows.length) return '';
  return `<div class="keyboard keyboard--wide">${rows.map(r => `<div class="krow">${r.map(n =>
    `<span class="kk ${d.id === 'piano' ? 'piano' : 'round'}${[1, 3, 6, 8, 10].includes(Number(n.midi) % 12) ? ' black' : ''}"
      title="${esc(t('inst.keys.note_key_title', {note: instSolfege(n), key: instKeyLabel(n.key, kbl)}))}">${esc(instKeyLabel(n.key, kbl))}</span>`).join('')}</div>`).join('')}</div>`;
}
// Les messages *_html ne contiennent que du balisage sur (gras) et des valeurs controlees (AZERTY/QWERTY, mode) :
// ils sont injectes tels quels ; tout ce qui vient du moteur ou du profil passe par esc().
function instKeysHtml(st, d, i){
  const kbl = instKbLayout(st);
  const mode = instInputMode(st);
  const notes = (d && d.notes) || [];
  const custom = !!(i && i.custom);
  const pref = st.keyboard_layout_pref || 'auto';
  const KBL = kbl.toUpperCase().replace(/[^A-Z]/g, '');
  const head = `<div class="instkeys__head">
      ${instImageHtml(i.id, 'instkeys__img', i.category)}
      <div><h3 class="instkeys__name">${esc(instName(i))}</h3>
        <span class="chip chip--badge ${instStatus(i.status).chip}">${esc(instStatus(i.status).label)}</span></div>
      <div class="spacer"></div>
      <div class="seg" id="kblSeg" role="radiogroup" aria-label="${esc(t('inst.keys.kbl_aria'))}">
        <button type="button" role="radio" data-kbl="auto">${esc(t('inst.keys.kbl_auto'))}</button>
        <button type="button" role="radio" data-kbl="azerty">AZERTY</button>
        <button type="button" role="radio" data-kbl="qwerty">QWERTY</button>
      </div>
    </div>
    <p class="hint left">${t('inst.keys.display_hint_html', {kbl: KBL, detected: pref === 'auto' ? 'yes' : 'no'})}</p>`;
  if(!notes.length){
    return head + `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span>
      <div class="notice__text">${esc(i.blocked_reason || t('inst.keys.no_keys'))}
      </div></div>
      <div class="btnrow"><button class="btn btn--cta" type="button" data-act="setup">${esc(t('inst.picker.setup'))}</button></div>`;
  }
  const rows = notes.map(n => {
    const key = n.key || '';
    const lab = n.label || instKeyLabel(key, kbl);
    const state = !key ? 'none' : (custom ? 'custom' : 'layout');
    const [sk, sc] = INST_ASSIGN[state];
    return `<tr>
      <td class="instkeys__note">${esc(instSolfege(n))}</td>
      <td class="instkeys__en">${esc(n.note || noteEn(n.midi))}</td>
      <td class="instkeys__oct">${esc(t('inst.keys.octave', {n: noteOctave(n.midi)}))}</td>
      <td><span class="keycap keycap--static">${esc(lab)}</span>${(n.shift != null ? n.shift : instKeyShift(key, kbl)) ? ` <span class="chip chip--badge chip--warn">${esc(t('inst.keys.shift'))}</span>` : ''}</td>
      <td><span class="chip chip--badge ${sc}">${esc(t(sk))}</span></td>
    </tr>`;
  }).join('');
  const shiftWarn = (mode === 'vk' && kbl === 'azerty' && notes.some(n => (n.shift != null ? n.shift : instKeyShift(n.key, kbl))))
    ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(t('inst.keys.shift_warn'))}</div></div>`
    : '';
  return head + shiftWarn + instKeyRowsHtml(d, kbl) + `
    <div class="tablewrap"><table class="instkeys">
      <thead><tr><th scope="col">${esc(t('inst.keys.th_note'))}</th><th scope="col">${esc(t('inst.keys.th_intl'))}</th><th scope="col">${esc(t('inst.keys.th_register'))}</th>
        <th scope="col">${esc(t('inst.keys.th_key', {kbl: KBL}))}</th><th scope="col">${esc(t('inst.keys.th_assign'))}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="btnrow">
      <button class="btn btn--secondary btn--sm" type="button" data-act="setup">${esc(t('inst.keys.edit'))}</button>
      <button class="btn btn--ghost btn--sm" type="button" data-act="full">${esc(t('inst.picker.full'))}</button>
      <button class="btn btn--ghost btn--sm" type="button" data-act="copy">${esc(t('inst.keys.copy'))}</button>
    </div>
    <p class="hint left">${t('inst.keys.full_hint_html')}</p>
    <details class="disclosure"><summary>${esc(t('inst.keys.adv_summary'))}</summary>
      <div class="disclosure__body">
        <p class="hint left">${t('inst.keys.adv_convention_html')}</p>
        <div class="tablewrap"><table class="instkeys instkeys--tech">
          <thead><tr><th scope="col">${esc(t('inst.keys.th_midi'))}</th><th scope="col">${esc(t('inst.keys.th_note'))}</th><th scope="col">${esc(t('inst.keys.th_position'))}</th><th scope="col">${esc(t('inst.keys.th_legend', {kbl: KBL}))}</th></tr></thead>
          <tbody>${notes.map(n => `<tr><td>${esc(String(n.midi))}</td><td>${esc(n.note || noteEn(n.midi))}</td>
            <td><code>${esc(n.key || '—')}</code></td><td>${esc(n.label || instKeyLabel(n.key, kbl))}</td></tr>`).join('')}</tbody>
        </table></div>
        <p class="hint left">${t('inst.keys.send_mode_html', {mode: mode === 'vk' ? 'vk' : 'scancode'})}</p>
      </div>
    </details>`;
}
function openKeysPanel(id){
  const st = S || {};
  id = id || (instActive(st) || {}).id;
  const i = instFromState(id, st);
  if(!i){ toast(t('inst.picker.not_found'), 'warn'); return; }
  const show = d0 => {
    const d = d0 || instFallbackDetail(i) || {id: id, notes: [], rows: []};
    openPanel({
      title: t('inst.keys.panel_title'), wide: true, opener: $('btnKeys'),
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
          `${instSolfege(n)}\t${n.note || noteEn(n.midi)}\t${n.midi}\t${n.key || ''}`).join('\n'), t('inst.keys.copied'));
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
// titres d'etape et frappes : des cles, resolues par t() a chaque rendu (wizDraw / wizStepHtml)
// (declarees pour i18n_check) : t('inst.wizard.title_open') t('inst.wizard.title_layout') t('inst.wizard.title_bind')
// t('inst.wizard.title_test') t('inst.wizard.title_save') t('inst.wizard.title_default')
const WIZ_TITLE_KEYS = {open: 'inst.wizard.title_open', layout: 'inst.wizard.title_layout',
  bind: 'inst.wizard.title_bind', test: 'inst.wizard.title_test', save: 'inst.wizard.title_save'};
function wizTitle(step){ return t(WIZ_TITLE_KEYS[step] || 'inst.wizard.title_default'); }
// frappes proposees pour une percussion : on demande CE QUI A SONNE, pas un Do/Re arbitraire
// (declarees pour i18n_check) : t('inst.wizard.strike_low') t('inst.wizard.strike_open') t('inst.wizard.strike_slap') t('inst.wizard.strike_none')
const WIZ_STRIKE_KEYS = [['low', 'inst.wizard.strike_low'], ['open', 'inst.wizard.strike_open'],
  ['slap', 'inst.wizard.strike_slap'], ['none', 'inst.wizard.strike_none']];
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
      message: t('inst.wizard.conflict_dup', {notes: dup.map(noteFr).join(', ')})});
    if(!instKeyInjectable(k)) out.push({midi, key: k, severity: 'error',
      message: t('inst.wizard.conflict_uninjectable')});
    Object.keys(hk).forEach(h => {
      const parts = String(hk[h] || '').toLowerCase().split('+').map(s => s.trim()).filter(Boolean);
      if(!parts.includes(k)) return;
      const hard = (h === 'stop' || h === 'play_pause');
      out.push({midi, key: k, severity: hard ? 'error' : 'warn',
        message: hard ? t('inst.wizard.conflict_hotkey_hard', {label: HOTKEY_LABELS[h] || h, key: hk[h]})
                      : t('inst.wizard.conflict_hotkey_soft', {label: HOTKEY_LABELS[h] || h, key: hk[h]})});
    });
    if(mode === 'vk' && instKeyShift(k, kbl)) out.push({midi, key: k, severity: 'warn',
      message: t('inst.wizard.conflict_shift')});
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
    WIZ.msg = t('inst.wizard.key_rejected');
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
  const KBL = kbl.toUpperCase().replace(/[^A-Z]/g, '');
  // Les messages *_html ne portent que du balisage sur ; les noms d'instrument (moteur) sont echappes avant.
  if(WIZ.step === 'open'){
    return `<div class="wiz__lead">${instImageHtml(WIZ.id, 'wiz__img', i.category)}
      <div><h3>${esc(instName(i) || WIZ.id || '')}</h3>
      <p>${t('inst.wizard.open_lead_html', {name: esc(instName(i))})}</p></div></div>
      <div class="notice notice--info"><span class="notice__ic" aria-hidden="true">${icon('info')}</span><div class="notice__text">${esc(t('inst.wizard.open_notice'))}</div></div>
      ${i.percussive ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(t('inst.wizard.open_percussion'))}</div></div>` : ''}
      <p class="hint left">${esc(t('inst.wizard.open_hint'))}</p>`;
  }
  if(WIZ.step === 'layout'){
    const list = wizLayoutList();
    const documented = !!((WIZ.detail && WIZ.detail.layouts) || []).length;
    return `<p>${t('inst.wizard.layout_intro_html')}</p>
      ${documented ? '' : `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(t('inst.wizard.layout_undocumented'))}</div></div>`}
      <div class="wizlays">${list.map(l => `<button type="button" class="wizlay${l.layoutId === WIZ.layoutId ? ' active' : ''}"
          data-lay="${esc(l.layoutId)}" aria-pressed="${l.layoutId === WIZ.layoutId ? 'true' : 'false'}">
          <b>${esc(instLayText(l, 'label') || l.layoutId)}${l.layoutId === WIZ.layoutId ? icon('check') : ''}</b>
          <span class="wizlay__d">${esc(instLayText(l, 'description'))}</span>
          <span class="wizlay__n">${l.noteCount != null ? esc(t('inst.picker.notes_n', {n: l.noteCount})) : ''}</span>
          <span class="wizlay__k">${(l.notes || []).slice(0, 24).map(n => `<i>${esc(instKeyLabel(n.key, kbl))}</i>`).join('')}${(l.notes || []).length > 24 ? '…' : ''}</span>
        </button>`).join('')}</div>
      <p class="hint left">${esc(t('inst.wizard.layout_hint'))}</p>`;
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
            aria-label="${esc(t('inst.wizard.key_for_aria', {note: noteFr(m), key: k ? instKeyLabel(k, kbl) : t('inst.wizard.key_none')}))}">${WIZ.capture === m ? '…' : esc(instKeyLabel(k, kbl))}</button>
          ${k ? `<button type="button" class="instrowx" data-clr="${m}" aria-label="${esc(t('inst.wizard.clear_aria', {note: noteFr(m)}))}" title="${esc(t('inst.wizard.clear'))}">${icon('close')}</button>` : ''}</td>
        <td class="wizconf">${cs.map(c => `<span class="chip chip--badge ${c.severity === 'error' ? 'chip--warn' : 'chip--info'}">${icon(c.severity === 'error' ? 'warn' : 'info')}${esc(c.message)}</span>`).join('')}</td>
      </tr>`;
    }).join('');
    return `<p>${t('inst.wizard.bind_intro_html')}</p>
      <p class="hint left">${esc(t('inst.wizard.bind_hint'))}</p>
      <div class="wizbar">
        <span class="chip chip--badge ${wizBound() === WIZ.order.length ? 'chip--ok' : 'chip--warn'}">${esc(t('inst.wizard.bind_count', {bound: wizBound(), total: WIZ.order.length}))}</span>
        <div class="spacer"></div>
        <button class="btn btn--ghost btn--sm" type="button" data-act="reset">${esc(t('inst.wizard.reset'))}</button>
      </div>
      <div class="tablewrap tablewrap--tall"><table class="instkeys">
        <thead><tr><th scope="col">${esc(t('inst.keys.th_note'))}</th><th scope="col">${esc(t('inst.keys.th_intl'))}</th>
          <th scope="col">${esc(t('inst.keys.th_key', {kbl: KBL}))}</th><th scope="col">${esc(t('inst.wizard.th_conflicts'))}</th></tr></thead>
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
    // liste des touches envoyees : fragments <b> composes avec esc(), puis inseres dans le message
    const sentList = sample.map(m => `<b>${esc(instKeyLabel(WIZ.bindings[m], kbl))}</b> (${esc(noteFr(m))})`).join(' · ') || '—';
    const expected = ((test && test.solfege && I18N.lang === 'fr') ? test.solfege : sample.map(noteFr)).join(', ') || '—';
    return `<p>${t('inst.wizard.test_intro_html', {key: esc(stopKey)})}</p>
      <div class="notice notice--info"><span class="notice__ic" aria-hidden="true">${icon('info')}</span><div class="notice__text">${esc(t('inst.wizard.test_notice', {name: instName(wizInst())}))}</div></div>
      ${full ? `<div class="notice notice--info"><span class="notice__ic" aria-hidden="true">${icon('check')}</span><div class="notice__text">${t('inst.wizard.full_progress_html', {done, bound})}</div></div>` : ''}
      <div class="wizbar">
        <span class="hint left">${t('inst.wizard.sent_keys_html', {list: sentList})}</span>
        <div class="spacer"></div>
        ${running ? `<button class="btn btn--secondary btn--sm" type="button" data-act="teststop">${esc(t('inst.wizard.test_stop'))}</button>` : ''}
        <button class="btn btn--cta btn--sm" type="button" data-act="test" ${running || !sample.length ? 'disabled' : ''}>
          ${esc(running ? t('inst.wizard.test_running') : (done ? t('inst.wizard.test_next') : t('inst.wizard.test_start')))}</button>
      </div>
      ${running && left != null ? `<p class="hint left">${esc(t('inst.wizard.switching', {n: Math.max(0, Math.ceil(left))}))}</p>` : ''}
      ${running && tstate === 'playing' ? `<p class="hint left">${esc(t('inst.wizard.sending'))}</p>` : ''}
      ${failed ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(t('inst.wizard.test_failed', {message: test.message || t('inst.wizard.test_failed_default')}))}</div></div>` : ''}
      ${tstate === 'answer'
        ? (wizPercussive()
          ? `<fieldset class="wizask"><legend>${esc(t('inst.wizard.heard'))}</legend>
              <p class="hint left">${esc(t('inst.wizard.heard_percussion_hint'))}</p>
              ${WIZ_STRIKE_KEYS.map(([v, key]) => `<button type="button" class="btn btn--secondary btn--sm" data-strike="${esc(v)}">${esc(t(key))}</button>`).join(' ')}
            </fieldset>`
          : `<fieldset class="wizask"><legend>${esc(t('inst.wizard.heard'))}</legend>
              <p class="hint left">${esc(t('inst.wizard.expected', {notes: expected}))}</p>
              <button type="button" class="btn btn--secondary btn--sm" data-ans="1">${esc(t('inst.wizard.ans_yes'))}</button>
              <button type="button" class="btn btn--secondary btn--sm" data-ans="0">${esc(t('inst.wizard.ans_no'))}</button>
            </fieldset>`)
        : `<p class="hint left">${esc(t('inst.wizard.heard_hint'))}</p>`}
      ${answered ? `<div class="notice notice--${answered.ok ? 'ok' : 'warn'}"><span class="notice__ic" aria-hidden="true">${icon(answered.ok ? 'check' : 'warn')}</span>
        <div class="notice__text">${esc(answered.ok
          ? (full
            ? t('inst.wizard.group_ok', {done, bound, all: (bound && done >= bound) ? 'yes' : 'no'})
            : t('inst.wizard.quick_ok', {n: WIZ.order.length}))
          : t('inst.wizard.answer_no'))}</div></div>` : ''}
      <p class="hint left">${esc(t('inst.wizard.skip_hint'))}</p>`;
  }
  // save
  const conf = wizConflicts();
  const hard = wizBlocking(conf);
  // statut annonce = celui que Python ECRIRA (next_status) : on n'annonce jamais plus que ce qui sera fait
  const wzs = (S && S.instrument_wizard) || null;
  const status = hard.length ? null
    : ((wzs && wzs.next_status) || (WIZ.tested && WIZ.tested.ok ? 'quick-tested' : 'custom'));
  return `<p>${t('inst.wizard.save_profile_html', {name: esc(instName(i) || WIZ.id || '')})}</p>
    <dl class="instdet__facts">
      <dt>${esc(t('inst.wizard.save_layout'))}</dt><dd>${esc(instLayoutLabel(WIZ.layoutId) || t('inst.wizard.save_manual'))}</dd>
      <dt>${esc(t('inst.wizard.save_notes'))}</dt><dd>${esc(t('inst.wizard.save_notes_val', {n: wizBound(), total: WIZ.order.length}))}</dd>
      <dt>${esc(t('inst.wizard.save_kbl'))}</dt><dd>${esc(instKbLayout(S).toUpperCase())}</dd>
      <dt>${esc(t('inst.wizard.save_status'))}</dt><dd>${esc(hard.length ? t('inst.wizard.save_conflicts') : instStatus(status).label)}</dd>
    </dl>
    ${hard.length ? `<div class="notice notice--danger"><span class="notice__ic" aria-hidden="true">${icon('danger')}</span><div class="notice__text">${esc(t('inst.wizard.save_conflicts_notice', {n: hard.length, notes: hard.map(c => noteFr(c.midi)).join(', ')}))}</div></div>` : ''}
    <p class="hint left">${esc(t('inst.wizard.save_hint'))}</p>`;
}
function wizDraw(){
  if(!$('wizOverlay').classList.contains('open')) return;
  const idx = WIZ_STEPS.indexOf(WIZ.step);
  txt('wizTitle', wizTitle(WIZ.step));
  txt('wizCount', t('inst.wizard.count', {i: idx + 1, n: WIZ_STEPS.length, name: instName(wizInst())}));
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
    next.textContent = t('inst.wizard.btn_save');
    next.disabled = wizBlocking(wizConflicts()).length > 0 || !wizBound();
  } else if(WIZ.step === 'test'){
    next.textContent = WIZ.tested ? t('inst.wizard.btn_continue') : t('inst.wizard.btn_skip_test');
    next.disabled = false;
  } else {
    next.textContent = t('inst.wizard.btn_continue');
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
  if(S && S.state !== 'stopped'){ WIZ.msg = t('inst.wizard.stop_before_test'); WIZ.msgKind = 'warn'; wizDraw(); return; }
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
  if(hard.length){ WIZ.msg = t('inst.wizard.fix_conflicts'); WIZ.msgKind = 'danger'; wizDraw(); return; }
  const id = WIZ.id, label = instName(wizInst()) || id || '';
  api('instrument_wizard_save').then(r => {
    instForget();
    if(WIZ.id !== id) return;                 // un autre assistant a ete ouvert entre-temps
    // Python renvoie {ok, error, state} : sans ce verdict, un refus (lecture en cours, conflit calcule
    // cote moteur) fermait la modale en annoncant « Profil enregistré » et le travail etait perdu.
    if(r && typeof r === 'object' && r.ok === false){
      WIZ.msg = r.error || t('inst.wizard.save_failed');
      WIZ.msgKind = 'danger';
      const wz = (S && S.instrument_wizard) || null;
      if(wz && wz.step) WIZ.step = WIZ_STEPS[Math.max(0, Math.min(WIZ_STEPS.length - 1, Number(wz.step) - 1))];
      wizDraw();
      return;
    }
    wizCaptureEnd();
    closeModal($('wizOverlay'));
    toast(t('inst.wizard.saved', {name: label}), 'ok');
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
  dialog({title: t('inst.wizard.cancel_title'), icon: 'keyboard',
    html: t('inst.wizard.cancel_html'),
    ok: t('inst.wizard.cancel_ok'), cancel: t('inst.wizard.cancel_continue'), danger: true}).then(v => { if(v) done(); });
}
function openInstrumentWizard(id, mode){
  const st = S || {};
  id = id || (instActive(st) || {}).id;
  const i = instFromState(id, st);
  if(!i){ toast(t('inst.picker.not_found'), 'warn'); return; }
  // Python refuse d'ouvrir l'assistant pendant une lecture (preecoute comprise : elle laisse #instRow
  // visible). On ne presente pas une modale qui n'enregistrerait rien.
  if(instPlaying(st)){ toast(t('inst.wizard.stop_before_setup'), 'warn'); return; }
  WIZ.id = id; WIZ.mode = mode === 'full' ? 'full' : 'setup'; WIZ.step = 'open';
  WIZ.bindings = {}; WIZ.order = []; WIZ.layoutId = null; WIZ.capture = null;
  WIZ.msg = ''; WIZ.tested = null; WIZ.testing = false; WIZ.dirty = false; WIZ.detail = null;
  openModal($('wizOverlay'), $('instPick'), () => { wizCaptureEnd(); }, () => wizCancel());
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
  sig: st => $('wizOverlay').classList.contains('open') ? JSON.stringify((st.instrument_wizard || {}).test || null) + '#' + WIZ.step + '#' + I18N.lang : 'closed',
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
  // Échap : gestionnaire unique des modales (core.js) ; les fermetures sont passées à openModal
})();
