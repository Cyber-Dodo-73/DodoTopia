// DodoTopia : activité « Mes créations » (ce qu'Heartopia garde sur cet ordinateur : photos de l'album,
// peintures, musiques enregistrées). Rien dans get_state() : la liste vient de creations_list() quand l'onglet
// s'ouvre, les vignettes de creations_thumb(id) pour les cartes visibles (IntersectionObserver), le détail de
// creations_view(id).
// Sections : Photos · Peintures · Musiques, et « Cache du jeu » seulement si le réglage creations.show_cache
// (Réglages › Apparence) est activé : images et musiques des autres joueurs, cadres, pochettes, annonces
// (décision du propriétaire, 2026-10-03 : par défaut on ne voit que ce que le joueur a fait lui-même).
// Actions : Remplacer… (original sauvegardé), Remettre l'original, Exporter (image ou MIDI), Ajouter une photo /
// une musique (rien n'est remplacé), Supprimer cet ajout, Ouvrir le dossier du jeu.
// Textes : t('creations.*') au rendu. Clés résolues par nom (déclarées pour i18n_check) : t('creations.sec.photo')
// t('creations.sec.painting') t('creations.sec.music') t('creations.sec.cache') t('creations.cat.all')
// t('creations.cat.photo') t('creations.cat.draw') t('creations.cat.frame') t('creations.cat.cover')
// t('creations.cat.book') t('creations.cat.home') t('creations.cat.paint') t('creations.cat.dress')
// t('creations.cat.announcement') t('creations.cat.music') t('creations.cat.other') t('creations.add.photo')
// t('creations.add.music') t('creations.intro.photo') t('creations.intro.painting') t('creations.intro.music')
// t('creations.intro.cache') t('creations.add_photo.title') t('creations.add_photo.body_html') t('creations.add_music.title')
// t('creations.studio.none')
// t('creations.add_music.body_html') t('creations.card.details') t('creations.card.export') t('creations.card.export_midi') t('creations.card.export_short') t('creations.card.listen')
const CR = {items: [], cats: {}, sections: {}, folder: '', found: null, available: true, my_id: null, error: '', show_cache: false,
  sec: 'photo', cat: 'all', sort: 'recent', loading: false, loaded: false, at: 0, seq: 0, thumbs: new Map(), pending: new Set()};
const CR_SECS = ['photo', 'painting', 'music', 'cache'];
const CR_CATS = ['photo', 'draw', 'frame', 'cover', 'book', 'home', 'paint', 'dress', 'music', 'announcement', 'other'];
const CR_SEC_ICON = {photo: 'image', painting: 'brush', music: 'music', cache: 'folder'};
const CR_STALE_MS = 60000;
let CR_OBS = null;

function crCatLabel(c){ const key = 'creations.cat.' + (c === 'all' || CR_CATS.includes(c) ? c : 'other'); return t(key); }
function crSecText(group, sec){ const key = 'creations.' + group + '.' + sec; return t(key); }
// une peinture ne se remplace pas : son fichier local n'est qu'un aperçu, le vrai dessin est sur les serveurs du jeu
function crCanReplace(it){ return it.section !== 'painting'; }
function crIsMusic(it){ return it.cat === 'music'; }
function crDur(s){ s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
function crBump(){ CR.seq++; if(S) render(S); else renderCreations(); }
// ouverture de l'onglet : première lecture, ou relecture si la liste date (le jeu a pu ajouter des créations)
function openCreations(){
  if(!CR.loaded || (!CR.loading && Date.now() - CR.at > CR_STALE_MS)) loadCreations(false);
}
// Au démarrage, l'onglet est restauré (localStorage) AVANT que le pont pywebview existe : un appel partirait
// dans le vide et afficherait une erreur. On attend alors le premier état (renderCreations relance).
function crBridgeReady(){ return !!(window.pywebview || window.MOCK_API); }
function loadCreations(refresh){
  if(CR.loading || !crBridgeReady()) return;
  CR.loading = true; crBump();
  api('creations_list', !!refresh).then(r => {
    CR.loading = false; CR.loaded = true; CR.at = Date.now();
    if(!r){ CR.error = t('creations.error_bridge'); CR.items = []; CR.cats = {}; CR.sections = {}; crBump(); return; }
    CR.available = r.available !== false; CR.found = !!r.found; CR.folder = r.folder || ''; CR.my_id = r.my_id || null;
    CR.show_cache = !!r.show_cache;
    CR.error = r.ok ? '' : (r.error === 'no_crypto' ? '' : (r.error || ''));
    CR.items = Array.isArray(r.items) ? r.items : []; CR.cats = r.cats || {}; CR.sections = r.sections || {};
    if(CR.sec === 'cache' && !CR.show_cache) CR.sec = 'photo';
    // vignettes d'images réécrites entre deux lectures : on garde celles dont rien n'a bougé
    const keep = new Map();
    for(const it of CR.items){ const th = CR.thumbs.get(it.id); if(th && th.modified === it.modified) keep.set(it.id, th); }
    CR.thumbs = keep;
    crBump();
  });
}
// réglage « afficher aussi le cache du jeu » changé dans les Réglages (settings.js) : la liste est relue
function crSettingChanged(){ if(CR.loaded) loadCreations(true); }
function crFiltered(){
  let list = CR.items.filter(it => it.section === CR.sec);
  if(CR.sec === 'cache' && CR.cat !== 'all') list = list.filter(it => it.cat === CR.cat);
  const big = it => crIsMusic(it) ? (it.duration || 0) : it.w * it.h;
  const by = {recent: (a, b) => (b.created || 0) - (a.created || 0), oldest: (a, b) => (a.created || 0) - (b.created || 0),
    size: (a, b) => big(b) - big(a) || (b.created || 0) - (a.created || 0)}[CR.sort] || ((a, b) => 0);
  return list.slice().sort(by);
}
function crTitle(it){ return crIsMusic(it) ? (it.name || crCatLabel('music')) : `${crCatLabel(it.cat)} · ${it.w}×${it.h}`; }
function crMeta(it){
  const parts = [];
  if(it.created) parts.push(I18N.fmtDate(it.created, 'date'));
  if(crIsMusic(it)){ parts.push(crDur(it.duration)); parts.push(t('creations.card.notes', {n: it.notes || 0})); }
  if(it.section === 'cache'){ if(it.mine === true) parts.push(t('creations.card.mine')); else if(it.mine === false) parts.push(t('creations.card.other')); }
  if(!crIsMusic(it)) parts.push(t('creations.card.variants', {n: (it.variants || []).length}));
  return parts.join(' · ');
}
function crCardHtml(it){
  const title = crTitle(it), th = CR.thumbs.get(it.id), music = crIsMusic(it);
  const img = music ? `<span class="gcard__noimg crcard__disc" aria-hidden="true">${icon('disc')}<b>${esc(crDur(it.duration))}</b></span>`
    : th && th.data ? `<img src="${esc(th.data)}" alt="" width="${esc(th.w)}" height="${esc(th.h)}">`
    : `<span class="gcard__noimg" aria-hidden="true">${icon(th && th.error ? 'warn' : 'image')}</span>`;
  return `<article class="gcard crcard${music ? ' is-music' : ''}${it.indexed ? ' is-draw' : ''}" data-id="${esc(it.id)}">
      <button class="gcard__img" type="button" data-act="view" data-id="${esc(it.id)}"${music ? ' data-noimg' : ''} title="${esc(t('creations.card.view'))}" aria-label="${esc(t('creations.card.view_aria', {title}))}">${img}</button>
      <div class="gcard__body"><div class="gcard__t" title="${esc(title)}">${esc(title)}</div><div class="gcard__m" title="${esc(crMeta(it))}">${esc(crMeta(it))}</div></div>
      <div class="gcard__acts">
        ${it.added ? `<span class="chip chip--badge chip--ok">${esc(t('creations.card.added'))}</span>` : ''}
        ${it.backup ? `<span class="chip chip--badge chip--warn">${esc(t('creations.card.replaced'))}</span>` : ''}
        <div class="spacer"></div>
        <button class="iconbtn iconbtn--sm" type="button" data-act="more" data-id="${esc(it.id)}" aria-haspopup="menu" title="${esc(t('creations.card.more'))}" aria-label="${esc(t('creations.card.more'))}">${icon('dots')}</button>
        ${crCanReplace(it) ? `<button class="btn btn--cta btn--sm" type="button" data-act="replace" data-id="${esc(it.id)}">${icon('import')}<span>${esc(t('creations.card.replace'))}</span></button>`
          : `<button class="btn btn--cta btn--sm" type="button" data-act="export" data-id="${esc(it.id)}">${icon('download')}<span>${esc(t('creations.card.export_short'))}</span></button>`}
      </div>
    </article>`;
}
// vignettes : demandées quand la carte entre dans la zone visible de la grille, gardées en mémoire ensuite
function crObserver(){
  if(CR_OBS) return CR_OBS;
  if(!('IntersectionObserver' in window)) return null;
  CR_OBS = new IntersectionObserver(entries => {
    for(const e of entries){
      if(!e.isIntersecting) continue;
      CR_OBS.unobserve(e.target);
      crLoadThumb(e.target.dataset.id, e.target);
    }
  }, {root: $('crGrid'), rootMargin: '200px 0px'});
  return CR_OBS;
}
function crLoadThumb(id, btn){
  if(CR.thumbs.has(id) || CR.pending.has(id)) return;
  CR.pending.add(id);
  api('creations_thumb', id).then(r => {
    CR.pending.delete(id);
    const it = CR.items.find(x => x.id === id);
    if(r && r.ok) CR.thumbs.set(id, {data: r.data, w: r.w, h: r.h, modified: it ? it.modified : 0});
    else CR.thumbs.set(id, {error: (r && r.error) || 'failed', modified: it ? it.modified : 0});
    // la carte est peut-être encore à l'écran : on la met à jour sans redessiner toute la grille
    const cur = $('crGrid').querySelector(`.gcard__img[data-id="${CSS.escape(id)}"]`);
    if(cur){
      const th = CR.thumbs.get(id);
      cur.innerHTML = th.data ? `<img src="${esc(th.data)}" alt="" width="${esc(th.w)}" height="${esc(th.h)}">`
        : `<span class="gcard__noimg" aria-hidden="true">${icon('warn')}</span>`;
    }
  });
}
function crChips(box, chips, cur, pick){
  const sig = JSON.stringify([chips, cur, I18N.lang]);
  if(box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.innerHTML = chips.map(([v, label, n, ic]) => `<button class="chip${v === cur ? ' active' : ''}" type="button" data-v="${esc(v)}" aria-pressed="${v === cur}">${ic ? icon(ic) : ''}${esc(label)} <span class="count">${esc(I18N.fmtNumber(n))}</span></button>`).join('');
  box.querySelectorAll('[data-v]').forEach(b => b.onclick = () => pick(b.dataset.v));
}
function renderCreations(){
  if(TAB !== 'creations') return;
  if(!CR.loaded && !CR.loading && crBridgeReady()){ loadCreations(false); return; }   // onglet restauré au démarrage
  const grid = $('crGrid');
  const list = crFiltered();
  txt('crCount', I18N.fmtNumber(list.length));
  // sections : Photos · Peintures · Musiques (+ Cache du jeu si le réglage le demande)
  const secs = CR_SECS.filter(s => s !== 'cache' || CR.show_cache);
  crChips($('crSecs'), secs.map(s => [s, crSecText('sec', s), CR.sections[s] || 0, CR_SEC_ICON[s]]), CR.sec,
    v => { CR.sec = v; try{ localStorage.setItem('creations.sec', v); }catch(e){} $('crGrid').scrollTop = 0; crBump(); });
  $('crSecs').hidden = !CR.found;
  // cache : sous-filtre par type d'image
  const inCache = CR.sec === 'cache';
  if(inCache) crChips($('crCats'), [['all', crCatLabel('all'), CR.sections.cache || 0]].concat(CR_CATS.filter(c => CR.cats[c]).map(c => [c, crCatLabel(c), CR.cats[c]])), CR.cat,
    v => { CR.cat = v; try{ localStorage.setItem('creations.cat', v); }catch(e){} crBump(); });
  $('crCats').hidden = !inCache || !(CR.sections.cache > 0);
  txt('crIntro', crSecText('intro', CR.sec));
  if($('crSort').value !== CR.sort) $('crSort').value = CR.sort;
  $('crFolder').disabled = !CR.found;
  // « Ajouter » : une photo ou une musique (une peinture est un objet de l'inventaire, créé par le jeu)
  const canAdd = CR.found && (CR.sec === 'photo' || CR.sec === 'music');
  $('crAdd').hidden = !canAdd;
  if(canAdd) txt('crAddLabel', crSecText('add', CR.sec));

  let notice = null, choose = false;
  if(!CR.available) notice = t('creations.no_crypto');
  else if(CR.error) notice = t('creations.error', {error: CR.error});
  else if(CR.loaded && !CR.found){ notice = t('creations.not_found'); choose = true; }
  txt('crNoticeText', notice || '');
  $('crNotice').hidden = !notice;
  $('crNoticeActions').hidden = !choose;

  if(CR.loading && !CR.items.length){
    grid.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon('spinner', 'ic--spin')}</div>${esc(t('creations.loading'))}</div>`;
  } else if(!CR.found && CR.loaded){
    grid.innerHTML = '';
  } else if(!list.length){
    grid.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon(CR_SEC_ICON[CR.sec] || 'image')}</div>${esc(t('creations.empty'))}</div>`;
  } else {
    grid.innerHTML = list.map(crCardHtml).join('');
    const obs = crObserver();
    grid.querySelectorAll('.gcard__img[data-id]:not([data-noimg])').forEach(b => {
      if(CR.thumbs.has(b.dataset.id)) return;
      if(obs) obs.observe(b); else crLoadThumb(b.dataset.id, b);
    });
  }
  grid.querySelectorAll('[data-act]').forEach(b => b.onclick = () => {
    const it = CR.items.find(x => x.id === b.dataset.id);
    if(!it) return;
    switch(b.dataset.act){
      case 'view': crView(it); break;
      case 'replace': crReplace(it, b); break;
      case 'export': api('creations_export', it.id); break;
      case 'more': crMore(b, it); break;
    }
  });
}
function crSizes(it){ return (it.variants || []).map(v => `${v.w}×${v.h}`).join(', '); }
// cadrage mémorisé pour une image d'un autre format : « Remplir » (recadrée au centre) ou « Ajuster » (bandes)
// (clés résolues selon le choix, déclarées pour i18n_check : t('creations.replace.fit_cover_hint') t('creations.replace.fit_contain_hint'))
let CR_FIT = 'cover';
try{ if(localStorage.getItem('creations.fit') === 'contain') CR_FIT = 'contain'; }catch(e){}
function crFitHtml(){
  return `<div class="line line--stack crfit"><span class="label label--wide" id="crFitLabel">${esc(t('creations.replace.fit_label'))}</span>
      <div class="seg" id="crFitSeg" role="radiogroup" aria-labelledby="crFitLabel">
        <button type="button" role="radio" data-v="cover">${esc(t('shell.draw.fit_cover'))}</button>
        <button type="button" role="radio" data-v="contain">${esc(t('shell.draw.fit_contain'))}</button>
      </div><span class="hint left" id="crFitHint"></span></div>`;
}
function crFitWire(){
  const seg = $('crFitSeg');
  const show = () => { segMark(seg, b => b.dataset.v === CR_FIT); txt('crFitHint', t(CR_FIT === 'contain' ? 'creations.replace.fit_contain_hint' : 'creations.replace.fit_cover_hint')); };
  seg.querySelectorAll('button').forEach(b => b.onclick = () => { CR_FIT = b.dataset.v; try{ localStorage.setItem('creations.fit', CR_FIT); }catch(e){} show(); });
  show();
}
function crReplace(it, btn){
  if(crIsMusic(it)){
    dialog({title: t('creations.replace_music.title'), icon: 'music', ok: t('creations.add.ok'), cancel: t('common.cancel'),
            html: t('creations.replace_music.body_html')})
      .then(yes => { if(yes) return apiAction(btn, 'creations_replace_dialog', it.id).then(r => crApplyResult(it, r)); });
    return;
  }
  const p = dialog({title: t('creations.replace.title'), icon: 'image', ok: t('creations.replace.ok'), cancel: t('common.cancel'),
          html: t('creations.replace.body_html', {sizes: esc(crSizes(it))}) + crFitHtml()});
  crFitWire();
  p.then(yes => { if(yes) return apiAction(btn, 'creations_replace_dialog', it.id, CR_FIT).then(r => crApplyResult(it, r)); });
}
// ajout : une photo dans l'album, ou une musique (MIDI converti) ; rien d'existant n'est remplacé
function crAdd(btn){
  const sec = CR.sec;
  if(sec === 'music'){ crStudio(btn); return; }      // une musique passe par le studio (pistes, instruments)
  if(sec !== 'photo') return;
  const photo = sec === 'photo';
  const p = dialog({title: t(photo ? 'creations.add_photo.title' : 'creations.add_music.title'), icon: photo ? 'image' : 'music',
          ok: t('creations.add.ok'), cancel: t('common.cancel'),
          html: t(photo ? 'creations.add_photo.body_html' : 'creations.add_music.body_html') + (photo ? crFitHtml() : '')});
  if(photo) crFitWire();
  p.then(yes => { if(yes) return apiAction(btn, 'creations_add_dialog', sec, CR_FIT).then(r => { if(r && r.ok){ CR.sort = 'recent'; $('crSort').value = 'recent'; loadCreations(true); } }); });
}
function crApplyResult(it, r){
  if(!r || !r.ok) return;
  if(r.item){ const i = CR.items.findIndex(x => x.id === it.id); if(i >= 0) CR.items[i] = r.item; }
  CR.thumbs.delete(it.id);
  crBump();
}
function crRestore(it){
  dialog({title: t('creations.restore.title'), icon: 'undo', ok: t('creations.restore.ok'), cancel: t('common.cancel'),
          html: `<p>${esc(t('creations.restore.body'))}</p>`})
    .then(yes => { if(yes) api('creations_restore', it.id).then(r => crApplyResult(it, r)); });
}
function crDelete(it){
  dialog({title: t('creations.delete.title'), icon: 'trash', danger: true, ok: t('creations.delete.ok'), cancel: t('common.cancel'),
          html: `<p>${esc(t('creations.delete.body'))}</p>`})
    .then(yes => { if(yes) api('creations_delete', it.id).then(r => { if(r && r.ok) loadCreations(true); }); });
}
// écoute sur l'ordinateur : la musique du jeu passe dans la bibliothèque et la préécoute démarre (onglet Musique)
function crListen(it){
  return api('creations_listen', it.id).then(r => { if(r && r.ok && typeof showTab === 'function') showTab('music'); return r; });
}
function crExportLabel(it){ return t(crIsMusic(it) ? 'creations.card.export_midi' : 'creations.card.export'); }
function crMore(anchor, it){
  const items = [
    {label: t(crIsMusic(it) ? 'creations.card.details' : 'creations.card.view'), icon: 'search', fn: () => crView(it)},
    {label: crExportLabel(it), icon: 'download', fn: () => api('creations_export', it.id)},
    {label: t('creations.card.restore'), icon: 'undo', disabled: !it.backup, help: it.backup ? '' : t('creations.card.no_backup'), fn: () => crRestore(it)},
  ];
  if(crIsMusic(it)) items.unshift({label: t('creations.card.listen'), icon: 'play', fn: () => crListen(it)});
  if(crIsMusic(it)) items.push({label: t('creations.learn.menu'), icon: 'music', fn: () => crLearn(it)});
  if(it.added) items.push({label: t('creations.card.delete'), icon: 'trash', fn: () => crDelete(it)});
  items.push({label: t('creations.open_folder'), icon: 'folder', fn: () => api('creations_open_folder')});
  menu(anchor, items);
}
// détail : panneau générique (image en grand déchiffrée, ou fiche de la musique), informations et actions
function crView(it){
  const music = crIsMusic(it);
  const files = (it.variants || []).map(v => `${v.folder}/${v.name}`);
  const body = (top, m) => `<div class="crview">
      ${music ? '' : `<div class="crview__img${it.indexed ? ' is-draw' : ''}">${top}</div>`}
      <dl class="crview__meta">
        ${music ? `<dt>${esc(t('creations.view.title_label'))}</dt><dd>${esc(it.name || '')}</dd>
        <dt>${esc(t('creations.view.duration'))}</dt><dd>${esc(crDur(it.duration))}</dd>
        <dt>${esc(t('creations.view.notes'))}</dt><dd>${esc(I18N.fmtNumber(m ? m.notes : (it.notes || 0)))}</dd>
        ${m ? `<dt>${esc(t('creations.view.players'))}</dt><dd>${esc(I18N.fmtNumber(m.players))}</dd>
        <dt>${esc(t('creations.view.instruments'))}</dt><dd>${esc(I18N.fmtNumber((m.instruments || []).length))}</dd>` : ''}`
        : `<dt>${esc(t('creations.view.type'))}</dt><dd>${esc(crCatLabel(it.cat))}${it.kind ? ` <small>(${esc(it.kind)})</small>` : ''}</dd>
        <dt>${esc(t('creations.view.size'))}</dt><dd>${esc(crSizes(it))}</dd>`}
        ${it.created ? `<dt>${esc(t('creations.view.created'))}</dt><dd>${esc(I18N.fmtDate(it.created, 'long'))}</dd>` : ''}
        ${it.player && it.section === 'cache' ? `<dt>${esc(t('creations.view.player'))}</dt><dd>${esc(it.player)}${it.mine === true ? ` · ${esc(t('creations.card.mine'))}` : ''}</dd>` : ''}
        <dt>${esc(t('creations.view.files', {n: files.length}))}</dt><dd class="crview__files">${files.map(f => `<code>${esc(f)}</code>`).join('<br>')}</dd>
      </dl>
      <div class="btnrow">
        ${crCanReplace(it) ? `<button class="btn btn--cta btn--sm" type="button" data-act="replace">${icon('import')}<span>${esc(t('creations.card.replace'))}</span></button>` : ''}
        ${music ? `<button class="btn btn--secondary btn--sm" type="button" data-act="listen">${icon('play')}<span>${esc(t('creations.card.listen'))}</span></button>` : ''}
        <button class="btn btn--secondary btn--sm" type="button" data-act="export">${icon('download')}<span>${esc(crExportLabel(it))}</span></button>
        ${it.backup ? `<button class="btn btn--secondary btn--sm" type="button" data-act="restore">${icon('undo')}<span>${esc(t('creations.card.restore'))}</span></button>` : ''}
        ${it.added ? `<button class="btn btn--secondary btn--sm" type="button" data-act="delete">${icon('trash')}<span>${esc(t('creations.card.delete'))}</span></button>` : ''}
      </div></div>`;
  const wire = box => {
    const rp = box.querySelector('[data-act="replace"]'); if(rp) rp.onclick = () => { closePanel(); crReplace(it, rp); };
    const ex = box.querySelector('[data-act="export"]'); if(ex) ex.onclick = () => api('creations_export', it.id);
    const rs = box.querySelector('[data-act="restore"]'); if(rs) rs.onclick = () => { closePanel(); crRestore(it); };
    const ls = box.querySelector('[data-act="listen"]'); if(ls) ls.onclick = () => { closePanel(); crListen(it); };
    const dl = box.querySelector('[data-act="delete"]'); if(dl) dl.onclick = () => { closePanel(); crDelete(it); };
  };
  const loading = `<div class="empty"><div class="big" aria-hidden="true">${icon('spinner', 'ic--spin')}</div>${esc(t('creations.loading_image'))}</div>`;
  openPanel({title: crTitle(it), wide: !music, opener: document.activeElement, html: body(loading, null), wire});
  api('creations_view', it.id).then(r => {
    if(!panelOpen() || !PANEL || PANEL.title !== crTitle(it)) return;
    const img = r && r.ok && r.data ? `<img src="${esc(r.data)}" alt="" width="${esc(r.w)}" height="${esc(r.h)}" class="crview__pic${it.indexed ? ' is-pixel' : ''}">`
      : `<div class="empty"><div class="big" aria-hidden="true">${icon('warn')}</div>${esc(t('creations.view.failed'))}</div>`;
    $('panelBody').innerHTML = body(img, r && r.ok ? r.music : null);
    wire($('panelBody'));
  });
}
$('crRefresh').onclick = () => loadCreations(true);
$('crFolder').onclick = () => api('creations_open_folder');
$('crChoose').onclick = () => api('creations_choose_folder').then(r => { if(r && r.ok) loadCreations(true); });
$('crAdd').onclick = () => crAdd($('crAdd'));
$('crSort').onchange = () => { CR.sort = $('crSort').value; try{ localStorage.setItem('creations.sort', CR.sort); }catch(e){} crBump(); };
try{
  const k0 = localStorage.getItem('creations.sec'); if(CR_SECS.includes(k0)) CR.sec = k0;
  const c0 = localStorage.getItem('creations.cat'); if(c0 && (c0 === 'all' || CR_CATS.includes(c0))) CR.cat = c0;
  const s0 = localStorage.getItem('creations.sort'); if(['recent', 'oldest', 'size'].includes(s0)) CR.sort = s0;
}catch(e){}
// ------------------------------------------------ studio : éditeur d'une musique à plusieurs instruments
// creations_studio_open() -> {path, title, duration, tracks:[{index, name, notes, low, high, roll:[[début, durée,
// note]]}], instruments, parts}. Chaque piste est une ligne sur la ligne de temps ; elle se coupe en passages (ciseaux)
// et chaque passage a son instrument et son octave. creations_studio_check(spec) -> {report, notes:[[début, durée,
// note, k]]} : ce que le jeu jouera (k = rang dans report.parts). L'éditeur le fait entendre lui-même (Web Audio,
// son de synthèse) : lecture, pause, reprise où l'on clique sur la règle. creations_studio_add(spec) écrit la musique
// dans le jeu.
const ST = {data: null, parts: [], title: '', timer: null, seq: 0, n: 0, sel: null, tool: 'select', pps: 0, scroll: 0,
  report: null, ok: false, error: '',
  au: {ctx: null, out: null, bus: null, notes: [], kinds: [], pos: 0, base: 0, idx: 0, playing: false, timer: null}};
const ST_HEAD_W = 190, ST_MIN = 0.5, ST_MAX_W = 16000, ST_LANE_H = 52;
const ST_FAMILY = {recorder: 'wind', xiao: 'wind', ocarina: 'wind', conch: 'wind', saxophone: 'reed', bagpipe: 'reed', concertina: 'reed',
  violin: 'bow', cello: 'bow', 'wooden-bass': 'bow'};
function stSpec(){ return {path: ST.data.path, title: ST.title, parts: ST.parts}; }
function stDur(){ return (ST.data && ST.data.duration) || 1; }
function stEnd(p){ return p.to == null ? stDur() : p.to; }
function stTrackName(tr){ return tr.name || t('creations.studio.track', {n: tr.index + 1}); }
function stPartsOf(index){ return ST.parts.filter(p => p.track === index).sort((a, b) => a.from - b.from); }
function stInst(id){ return ST.data.instruments.find(i => i.id === id); }
function stHue(id){ return (Math.max(0, ST.data.instruments.findIndex(i => i.id === id)) * 47 + 28) % 360; }
function stEditorOpen(){ return !!(PANEL && PANEL.render === stHtml); }

function stInspHtml(){
  const d = ST.data, p = ST.parts.find(x => x.id === ST.sel);
  if(!p) return `<p class="hint left">${esc(t('creations.studio.cut_hint'))}</p>`;
  const tr = d.tracks.find(x => x.index === p.track), first = stPartsOf(p.track)[0] === p;
  const opts = d.instruments.map(i => `<option value="${esc(i.id)}"${i.id === p.instrument ? ' selected' : ''}${i.available ? '' : ' disabled'}>${esc(i.available ? i.name : t('creations.studio.to_learn', {name: i.name}))}</option>`).join('');
  const octs = [-2, -1, 0, 1, 2].map(o => `<option value="${o}"${o === (p.octave || 0) ? ' selected' : ''}>${o > 0 ? '+' + o : o}</option>`).join('');
  return `<div class="studio__sel"><b>${esc(stTrackName(tr))}</b><span>${esc(crDur(p.from))} → ${esc(crDur(stEnd(p)))}</span><span class="studio__cov" id="stSelCov"></span></div>
      <label class="field"><span class="field__label">${esc(t('creations.studio.instrument'))}</span><select class="select" data-f="instrument">${opts}</select></label>
      <label class="field"><span class="field__label">${esc(t('creations.studio.octave'))}</span><select class="select" data-f="octave">${octs}</select></label>
      <label class="switch switch--inline"><input type="checkbox" data-f="clip_on"${p.on ? ' checked' : ''}><span class="switch__track"></span><span>${esc(t('creations.studio.clip_on'))}</span></label>
      <button class="btn btn--secondary btn--sm" type="button" data-act="whole">${esc(t('creations.studio.whole_track'))}</button>
      ${first ? '' : `<button class="btn btn--secondary btn--sm" type="button" data-act="merge">${esc(t('creations.studio.merge'))}</button>`}`;
}
function stHtml(){
  const d = ST.data;
  if(!d) return '';
  const cut = ST.tool === 'cut';
  const rows = d.tracks.map(tr => {
    const parts = stPartsOf(tr.index), on = parts.some(p => p.on);
    const clips = parts.map((p, i) => `<div class="studio__clip${p.on ? '' : ' is-off'}${p.id === ST.sel ? ' is-sel' : ''}" data-clip="${esc(p.id)}" role="button" tabindex="0">
          <span class="studio__tag">${esc((stInst(p.instrument) || {name: p.instrument}).name)}${p.octave ? ' ' + (p.octave > 0 ? '+' : '') + p.octave : ''}</span>${i ? `<i class="studio__grip" data-grip="${esc(p.id)}"></i>` : ''}</div>`).join('');
    return `<div class="studio__row" data-track="${tr.index}">
        <div class="studio__th"><label class="switch switch--inline"><input type="checkbox" data-f="on"${on ? ' checked' : ''}><span class="switch__track"></span><span><b>${esc(stTrackName(tr))}</b><small>${esc(t('creations.card.notes', {n: tr.notes}))}${tr.drums ? ' · ' + esc(t('creations.studio.drums')) : ''}</small></span></label></div>
        <div class="studio__lane"><canvas height="${ST_LANE_H}"></canvas>${clips}</div></div>`;
  }).join('');
  return `<div class="studio">
      <div class="studio__top">
        <label class="field studio__name"><span class="field__label">${esc(t('creations.studio.name'))}</span>
          <input class="input" id="stTitle" type="text" maxlength="24" spellcheck="false" value="${esc(ST.title)}"></label>
        <div class="studio__transport">
          <button class="btn btn--cta" type="button" id="stPlay"></button>
          <button class="iconbtn iconbtn--sm" type="button" id="stRewind" title="${esc(t('creations.studio.rewind'))}" aria-label="${esc(t('creations.studio.rewind'))}">${icon('prev')}</button>
          <output class="studio__clock" id="stClock"></output>
        </div>
        <div class="studio__tools">
          <button class="iconbtn iconbtn--sm${cut ? ' is-on' : ''}" type="button" id="stCutTool" aria-pressed="${cut}" title="${esc(t('creations.studio.scissors'))}" aria-label="${esc(t('creations.studio.scissors'))}">${icon('scissors')}</button>
          <button class="iconbtn iconbtn--sm" type="button" id="stZoomOut" title="${esc(t('creations.studio.zoom_out'))}" aria-label="${esc(t('creations.studio.zoom_out'))}">${icon('minus')}</button>
          <button class="iconbtn iconbtn--sm" type="button" id="stZoomIn" title="${esc(t('creations.studio.zoom_in'))}" aria-label="${esc(t('creations.studio.zoom_in'))}">${icon('plus')}</button>
        </div>
      </div>
      <div class="studio__ed${cut ? ' is-cut' : ''}" id="stEd">
        <div class="studio__row studio__row--ruler"><div class="studio__th"></div><div class="studio__ruler" id="stRuler"></div></div>
        ${rows}
        <div class="studio__playhead" id="stHead"></div>
      </div>
      <div class="studio__insp" id="stInsp">${stInspHtml()}</div>
      <div class="studio__foot">
        <p class="hint left" id="stStatus" role="status"></p>
        <button class="btn btn--cta" type="button" data-act="add">${icon('plus')}<span>${esc(t('creations.studio.add'))}</span></button>
      </div>
      <div class="hint left">${t('creations.studio.hint_html')}</div>
    </div>`;
}

// ---- lecture : petit synthétiseur, les notes sont programmées un tiers de seconde à l'avance
function stNow(){ const a = ST.au; return a.playing ? Math.min(stDur(), Math.max(0, a.ctx.currentTime - a.base)) : a.pos; }
function stVoice(a, when, dur, midi, fam){
  const c = a.ctx, o = c.createOscillator(), g = c.createGain(), f = 440 * Math.pow(2, (midi - 69) / 12);
  let end;
  o.frequency.value = f;
  g.gain.setValueAtTime(0.0001, when);
  if(fam === 'pluck'){
    o.type = 'triangle';
    end = when + Math.min(1.8, Math.max(0.35, dur + 0.5));
    g.gain.exponentialRampToValueAtTime(0.22, when + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, end);
  }else{
    const peak = fam === 'wind' ? 0.15 : 0.07, att = fam === 'bow' ? 0.06 : 0.03;
    o.type = fam === 'wind' ? 'sine' : fam === 'bow' ? 'sawtooth' : 'square';
    end = when + Math.max(0.12, dur) + 0.09;
    g.gain.linearRampToValueAtTime(peak, when + att);
    g.gain.setValueAtTime(peak, Math.max(when + att, end - 0.09));
    g.gain.linearRampToValueAtTime(0.0001, end);
  }
  o.connect(g);
  if(fam === 'bow' || fam === 'reed'){
    const lp = c.createBiquadFilter();
    lp.type = 'lowpass'; lp.frequency.value = Math.min(6000, f * 4);
    g.connect(lp); lp.connect(a.bus);
  }else g.connect(a.bus);
  o.start(when); o.stop(end + 0.02);
}
function stIndexAt(at){ const n = ST.au.notes; let i = 0; while(i < n.length && n[i][0] < at - 0.001) i++; return i; }
function stPump(){
  const a = ST.au;
  if(!a.playing) return;
  if(!stEditorOpen()){ stPause(); return; }
  const now = a.ctx.currentTime - a.base;
  while(a.idx < a.notes.length && a.notes[a.idx][0] < now + 0.3){
    const n = a.notes[a.idx++];
    if(n[0] >= now - 0.05) stVoice(a, a.base + n[0], n[1], n[2], a.kinds[n[3]] || 'pluck');
  }
  if(now >= stDur() + 0.4){ stPause(); a.pos = 0; stHeadPaint(false); }
}
function stPlay(){
  const a = ST.au, AC = window.AudioContext || window.webkitAudioContext;
  if(a.playing || !a.notes.length || !AC) return;
  if(!a.ctx){ a.ctx = new AC(); a.out = a.ctx.createDynamicsCompressor(); a.out.connect(a.ctx.destination); }
  if(a.ctx.state === 'suspended') a.ctx.resume();
  a.bus = a.ctx.createGain(); a.bus.gain.value = 0.7; a.bus.connect(a.out);
  if(a.pos >= stDur() - 0.05) a.pos = 0;
  a.base = a.ctx.currentTime + 0.08 - a.pos;
  a.idx = stIndexAt(a.pos);
  a.playing = true;
  a.timer = setInterval(stPump, 50);
  stPump(); stTransport();
  requestAnimationFrame(stTick);
}
function stPause(){
  const a = ST.au;
  if(!a.playing) return;
  a.pos = stNow();
  a.playing = false;
  clearInterval(a.timer);
  const bus = a.bus;
  bus.gain.setTargetAtTime(0, a.ctx.currentTime, 0.015);
  setTimeout(() => bus.disconnect(), 250);
  stTransport();
}
function stSeek(at){
  const a = ST.au, was = a.playing;
  if(was) stPause();
  a.pos = Math.max(0, Math.min(stDur(), at));
  if(was) stPlay();
  stHeadPaint(false);
}
function stTick(){
  if(!ST.au.playing || !stEditorOpen()) return;
  stHeadPaint(true);
  requestAnimationFrame(stTick);
}
function stHeadPaint(follow){
  const head = $('stHead'), ed = $('stEd');
  if(!head || !ed) return;
  const now = stNow(), x = ST_HEAD_W + now * ST.pps;
  head.style.left = x + 'px';
  txt('stClock', crDur(now) + ' / ' + crDur(stDur()));
  if(follow && (x > ed.scrollLeft + ed.clientWidth - 30 || x < ed.scrollLeft + ST_HEAD_W)) ed.scrollLeft = x - ST_HEAD_W - 30;
}
function stTransport(){
  const b = $('stPlay'), on = ST.au.playing;
  if(!b) return;
  b.innerHTML = icon(on ? 'pause' : 'play') + `<span>${esc(on ? t('creations.studio.pause') : t('creations.studio.play'))}</span>`;
  b.disabled = !ST.au.notes.length;
}

// ---- contrôle : part de notes à la bonne hauteur par passage, et les notes à faire entendre
function stReport(){
  const r = ST.report;
  document.querySelectorAll('.studio__clip').forEach(el => { el.title = ''; });
  if(ST.ok) for(const p of r.parts){
    const el = document.querySelector(`.studio__clip[data-clip="${CSS.escape(String(p.id))}"]`);
    if(el) el.title = t('creations.studio.coverage', {n: p.coverage});
    if(p.id === ST.sel) txt('stSelCov', t('creations.studio.coverage', {n: p.coverage}));
  }
  txt('stStatus', ST.ok ? t('creations.studio.ready', {duration: crDur(r.duration)}) : (ST.error || t('creations.studio.none')));
  document.querySelectorAll('.studio [data-act="add"]').forEach(b => { b.disabled = !ST.ok; });
  stTransport();
}
function stCheck(){
  clearTimeout(ST.timer);
  ST.timer = setTimeout(() => {
    const seq = ++ST.seq;
    api('creations_studio_check', stSpec()).then(r => {
      if(seq !== ST.seq || !stEditorOpen()) return;
      const a = ST.au;
      ST.ok = !!(r && r.ok);
      ST.report = ST.ok ? r.report : null;
      ST.error = ST.ok ? '' : ((r && r.error) || '');
      a.notes = ST.ok ? (r.notes || []) : [];
      a.kinds = ST.ok ? r.report.parts.map(p => ST_FAMILY[p.instrument] || 'pluck') : [];
      if(a.playing){ if(a.notes.length) a.idx = stIndexAt(stNow() + 0.3); else stPause(); }
      stReport();
    });
  }, 200);
}

// ---- passages
// coupe le passage de la piste qui contient l'instant `at` (une demi-seconde au moins de chaque côté)
function stCut(index, at){
  at = Math.round(at * 100) / 100;
  const p = stPartsOf(index).find(x => at > x.from && at < stEnd(x));
  if(!p) return null;
  const end = stEnd(p);
  if(at - p.from < ST_MIN || end - at < ST_MIN) return null;
  const q = Object.assign({}, p, {id: 'p' + index + '_' + (++ST.n), from: at, to: end});
  ST.parts.push(q);
  p.to = at;
  return q;
}
function stMerge(id){
  const p = ST.parts.find(x => x.id === id);
  if(!p) return;
  const list = stPartsOf(p.track), prev = list[list.indexOf(p) - 1];
  if(!prev) return;
  prev.to = p.to;
  ST.parts.splice(ST.parts.indexOf(p), 1);
  ST.sel = prev.id;
}
function stEdited(){ refreshPanel(); stCheck(); }

// ---- mise en place : largeurs, graduations, notes et passages suivent l'échelle ST.pps (pixels par seconde)
function stDraw(canvas, tr, W){
  const g = canvas.getContext('2d'), parts = stPartsOf(tr.index);
  const lo = tr.low == null ? 48 : tr.low, span = Math.max(12, (tr.high == null ? 84 : tr.high) - lo);
  canvas.width = W;
  g.clearRect(0, 0, W, ST_LANE_H);
  let k = 0;
  for(const n of tr.roll || []){
    while(k < parts.length - 1 && n[0] >= stEnd(parts[k])) k++;
    const p = parts[k];
    g.fillStyle = p && p.on ? `hsl(${stHue(p.instrument)} 62% 52%)` : 'rgba(128,128,128,.45)';
    g.fillRect(n[0] * ST.pps, 5 + (1 - (n[2] - lo) / span) * (ST_LANE_H - 13), Math.max(2, n[1] * ST.pps - 1), 3);
  }
}
function stPlace(el, p){
  const hue = stHue(p.instrument);
  el.style.left = (p.from * ST.pps) + 'px';
  el.style.width = Math.max(4, (stEnd(p) - p.from) * ST.pps) + 'px';
  el.style.borderColor = `hsl(${hue} 55% 42%)`;
  el.style.background = `hsla(${hue}, 62%, 52%, .14)`;
  const tag = el.querySelector('.studio__tag');
  if(tag) tag.style.background = `hsl(${hue} 50% 32%)`;
}
function stLayout(){
  const ed = $('stEd'), ruler = $('stRuler'), total = stDur();
  if(!ed || !ruler) return;
  if(!ed.clientWidth) return;                       // panneau pas encore affiché : rien à mesurer
  const fit = Math.max(0.5, (ed.clientWidth - ST_HEAD_W - 6) / total);
  ST.pps = Math.max(fit, Math.min(ST.pps || fit, 160, Math.max(fit, ST_MAX_W / total)));
  const W = Math.round(total * ST.pps);
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find(s => s * ST.pps >= 64) || 600;
  let ticks = '';
  for(let s = 0; s < total; s += step) ticks += `<span data-at="${s}">${esc(crDur(s))}</span>`;
  ruler.innerHTML = ticks;
  ruler.style.width = W + 'px';
  ruler.querySelectorAll('span').forEach(sp => { sp.style.left = (Number(sp.dataset.at) * ST.pps) + 'px'; });
  ed.querySelectorAll('.studio__row[data-track]').forEach(row => {
    const tr = ST.data.tracks.find(x => x.index === Number(row.dataset.track)), lane = row.querySelector('.studio__lane');
    lane.style.width = W + 'px';
    stDraw(lane.querySelector('canvas'), tr, W);
    lane.querySelectorAll('.studio__clip').forEach(el => { const p = ST.parts.find(x => x.id === el.dataset.clip); if(p) stPlace(el, p); });
  });
  $('stHead').style.height = ed.scrollHeight + 'px';
  stHeadPaint(false);
}
function stZoom(k){
  const ed = $('stEd'), at = stNow();
  ST.pps *= k;
  stLayout();
  ed.scrollLeft = Math.max(0, at * ST.pps - (ed.clientWidth - ST_HEAD_W) / 2);
}
function stWire(box){
  const ed = $('stEd'), ruler = $('stRuler');
  const laneTime = (lane, e) => (e.clientX - lane.getBoundingClientRect().left) / ST.pps;
  const title = box.querySelector('#stTitle');
  if(title) title.oninput = () => { ST.title = title.value; };
  stLayout();
  ed.scrollLeft = ST.scroll;
  ed.onscroll = () => { ST.scroll = ed.scrollLeft; };
  // règle : un clic ou un glissé place la tête de lecture, lecture en cours ou non
  ruler.onpointerdown = e => {
    ruler.setPointerCapture(e.pointerId);
    stSeek(laneTime(ruler, e));
    ruler.onpointermove = ev => stSeek(laneTime(ruler, ev));
    ruler.onpointerup = ruler.onpointercancel = () => { ruler.onpointermove = null; };
  };
  box.querySelectorAll('.studio__row[data-track]').forEach(row => {
    const index = Number(row.dataset.track), lane = row.querySelector('.studio__lane');
    const sw = row.querySelector('[data-f="on"]');
    if(sw) sw.onchange = () => { stPartsOf(index).forEach(p => { p.on = sw.checked; }); stEdited(); };
    lane.querySelectorAll('.studio__clip').forEach(el => {
      const pick = e => {
        if(ST.tool === 'cut' && e.clientX != null){
          const q = stCut(index, laneTime(lane, e));
          if(q){ ST.sel = q.id; stEdited(); }
          return;
        }
        ST.sel = el.dataset.clip;
        refreshPanel();
      };
      el.onclick = pick;
      el.onkeydown = e => { if(e.key === 'Enter'){ e.preventDefault(); ST.sel = el.dataset.clip; refreshPanel(); } };
    });
    // limite entre deux passages : se tire à la souris
    lane.querySelectorAll('.studio__grip').forEach(grip => {
      grip.onclick = e => e.stopPropagation();
      grip.onpointerdown = e => {
        const p = ST.parts.find(x => x.id === grip.dataset.grip), list = stPartsOf(index), prev = list[list.indexOf(p) - 1];
        if(!p || !prev) return;
        e.stopPropagation(); e.preventDefault();
        grip.setPointerCapture(e.pointerId);
        grip.onpointermove = ev => {
          const at = Math.round(Math.max(prev.from + ST_MIN, Math.min(stEnd(p) - ST_MIN, laneTime(lane, ev))) * 100) / 100;
          prev.to = p.from = at;
          stPlace(grip.parentElement, p);
          const pe = lane.querySelector(`.studio__clip[data-clip="${CSS.escape(prev.id)}"]`);
          if(pe) stPlace(pe, prev);
        };
        grip.onpointerup = grip.onpointercancel = () => { grip.onpointermove = null; stEdited(); };
      };
    });
  });
  const insp = $('stInsp'), sel = ST.parts.find(x => x.id === ST.sel);
  if(insp && sel){
    insp.querySelectorAll('select[data-f]').forEach(el => el.onchange = () => {
      if(el.dataset.f === 'octave') sel.octave = Number(el.value); else sel.instrument = el.value;
      stEdited();
    });
    const on = insp.querySelector('[data-f="clip_on"]');
    if(on) on.onchange = () => { sel.on = on.checked; stEdited(); };
    const whole = insp.querySelector('[data-act="whole"]');
    if(whole) whole.onclick = () => { stPartsOf(sel.track).forEach(p => { p.instrument = sel.instrument; p.octave = sel.octave; }); stEdited(); };
    const merge = insp.querySelector('[data-act="merge"]');
    if(merge) merge.onclick = () => { stMerge(sel.id); stEdited(); };
  }
  $('stPlay').onclick = () => { if(ST.au.playing) stPause(); else stPlay(); };
  $('stRewind').onclick = () => stSeek(0);
  $('stCutTool').onclick = () => { ST.tool = ST.tool === 'cut' ? 'select' : 'cut'; refreshPanel(); };
  $('stZoomIn').onclick = () => stZoom(1.6);
  $('stZoomOut').onclick = () => stZoom(1 / 1.6);
  // Espace : lecture ou pause, sauf dans un champ ou sur un bouton
  box.onkeydown = e => {
    if(e.code !== 'Space' || e.target.closest('input, select, button, textarea')) return;
    e.preventDefault();
    if(ST.au.playing) stPause(); else stPlay();
  };
  const ad = box.querySelector('[data-act="add"]');
  if(ad) ad.onclick = () => apiAction(ad, 'creations_studio_add', stSpec()).then(r => {
    if(r && r.ok){ closePanel(); CR.sort = 'recent'; $('crSort').value = 'recent'; loadCreations(true); }
  });
  stReport();
}
function crStudio(btn){
  apiAction(btn, 'creations_studio_open').then(r => {
    if(!r || !r.ok) return;
    stPause();
    Object.assign(ST, {data: r, title: r.title || '', n: 0, sel: null, tool: 'select', pps: 0, scroll: 0, report: null, ok: false, error: ''});
    Object.assign(ST.au, {notes: [], kinds: [], pos: 0, idx: 0});
    ST.parts = (r.parts || []).map(p => Object.assign({}, p, {from: p.from || 0, to: p.to == null ? r.duration : p.to}));
    openPanel({title: t('creations.studio.title'), full: true, opener: btn, render: stHtml, html: stHtml(), wire: stWire, closed: stPause});
    refreshPanel();                                      // le panneau est maintenant affiché : l'échelle se mesure
    stCheck();
  });
}
// apprendre un instrument : une musique du jeu où toutes ses touches ont été jouées, de la plus grave à la plus aiguë
function crLearn(it){
  api('creations_studio_instruments').then(r => {
    const list = (r && r.instruments) || [];
    if(!list.length) return;
    const html = `<p>${esc(t('creations.learn.body'))}</p>
      <label class="field"><span class="field__label">${esc(t('creations.studio.instrument'))}</span>
        <select class="select" id="crLearnSel">${list.filter(i => i.id !== 'piano').map(i => `<option value="${esc(i.id)}">${esc(i.name)} · ${esc(t('creations.card.notes', {n: i.notes}))}${i.learned ? ' · ' + esc(t('creations.learn.learned')) : ''}</option>`).join('')}</select></label>`;
    const p = dialog({title: t('creations.learn.title'), icon: 'music', ok: t('creations.learn.ok'), cancel: t('common.cancel'), html});
    const sel = $('crLearnSel');
    p.then(yes => { if(yes && sel) api('creations_learn', it.id, sel.value); });
  });
}
// redessinée quand l'onglet, la langue ou les données changent (CR.seq) ; jamais à chaque tick d'état
view('creations', {sig: st => TAB + '|' + I18N.lang + '|' + CR.seq, draw: renderCreations});
