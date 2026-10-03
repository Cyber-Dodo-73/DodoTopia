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
// ------------------------------------------------ studio : une musique à plusieurs instruments depuis un MIDI
// creations_studio_open() -> {path, title, tracks, instruments, parts} ; chaque piste cochée reçoit un instrument
// et une octave ; creations_studio_check(spec) donne la part de notes jouées à la bonne hauteur, sans rien écrire ;
// creations_studio_listen(spec) préécoute sur l'ordinateur ; creations_studio_add(spec) écrit la musique dans le jeu.
// Seul le piano est connu d'avance : les autres instruments s'apprennent depuis une musique du jeu (crLearn).
const ST = {data: null, parts: [], title: '', timer: null, seq: 0};
function stSpec(){ return {path: ST.data.path, title: ST.title, parts: ST.parts}; }
function stTrackName(tr){ return tr.name || t('creations.studio.track', {n: tr.index + 1}); }
function stHtml(){
  const d = ST.data;
  if(!d) return '';
  const opts = cur => d.instruments.map(i => `<option value="${esc(i.id)}"${i.id === cur ? ' selected' : ''}${i.available ? '' : ' disabled'}>${esc(i.available ? i.name : t('creations.studio.to_learn', {name: i.name}))}</option>`).join('');
  const octs = cur => [-2, -1, 0, 1, 2].map(o => `<option value="${o}"${o === cur ? ' selected' : ''}>${o > 0 ? '+' + o : o}</option>`).join('');
  const rows = d.tracks.map(tr => {
    const p = ST.parts.find(x => x.track === tr.index) || {};
    return `<tr data-track="${tr.index}"${p.on ? '' : ' class="is-off"'}>
        <td><label class="switch switch--inline"><input type="checkbox" data-f="on"${p.on ? ' checked' : ''}><span class="switch__track"></span><span><b>${esc(stTrackName(tr))}</b><small>${esc(t('creations.card.notes', {n: tr.notes}))}${tr.drums ? ' · ' + esc(t('creations.studio.drums')) : ''}</small></span></label></td>
        <td><select class="select" data-f="instrument" aria-label="${esc(t('creations.studio.instrument'))}">${opts(p.instrument)}</select></td>
        <td><select class="select" data-f="octave" aria-label="${esc(t('creations.studio.octave'))}">${octs(p.octave || 0)}</select></td>
        <td class="studio__cov" data-cov="${tr.index}"></td></tr>`;
  }).join('');
  return `<div class="studio">
      <label class="field"><span class="field__label">${esc(t('creations.studio.name'))}</span>
        <input class="input" id="stTitle" type="text" maxlength="24" spellcheck="false" value="${esc(ST.title)}"></label>
      <div class="table-scroll"><table class="studio__tracks"><thead><tr><th>${esc(t('creations.studio.col_track'))}</th><th>${esc(t('creations.studio.instrument'))}</th><th>${esc(t('creations.studio.octave'))}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint left" id="stStatus" role="status"></p>
      <div class="btnrow">
        <button class="btn btn--secondary" type="button" data-act="listen">${icon('play')}<span>${esc(t('creations.studio.listen'))}</span></button>
        <button class="btn btn--cta" type="button" data-act="add">${icon('plus')}<span>${esc(t('creations.studio.add'))}</span></button>
      </div>
      <div class="hint left">${t('creations.studio.hint_html')}</div>
    </div>`;
}
function stCheck(){
  clearTimeout(ST.timer);
  ST.timer = setTimeout(() => {
    const seq = ++ST.seq;
    api('creations_studio_check', stSpec()).then(r => {
      if(seq !== ST.seq || !PANEL || PANEL.render !== stHtml) return;
      document.querySelectorAll('.studio__cov').forEach(td => { td.textContent = ''; });
      const ok = !!(r && r.ok);
      if(ok) for(const p of r.report.parts){
        const td = document.querySelector(`.studio__cov[data-cov="${p.track}"]`);
        if(td) td.textContent = t('creations.studio.coverage', {n: p.coverage});
      }
      txt('stStatus', ok ? t('creations.studio.ready', {duration: crDur(r.report.duration)}) : ((r && r.error) || t('creations.studio.none')));
      document.querySelectorAll('.studio [data-act]').forEach(b => { b.disabled = !ok; });
    });
  }, 250);
}
function stWire(box){
  const title = box.querySelector('#stTitle');
  if(title) title.oninput = () => { ST.title = title.value; };
  box.querySelectorAll('tr[data-track]').forEach(tr => {
    const p = ST.parts.find(x => x.track === Number(tr.dataset.track));
    if(!p) return;
    tr.querySelectorAll('[data-f]').forEach(el => el.onchange = () => {
      if(el.dataset.f === 'on'){ p.on = el.checked; tr.classList.toggle('is-off', !p.on); }
      else if(el.dataset.f === 'octave') p.octave = Number(el.value);
      else p.instrument = el.value;
      stCheck();
    });
  });
  const ls = box.querySelector('[data-act="listen"]');
  if(ls) ls.onclick = () => apiAction(ls, 'creations_studio_listen', stSpec());
  const ad = box.querySelector('[data-act="add"]');
  if(ad) ad.onclick = () => apiAction(ad, 'creations_studio_add', stSpec()).then(r => {
    if(r && r.ok){ closePanel(); CR.sort = 'recent'; $('crSort').value = 'recent'; loadCreations(true); }
  });
  stCheck();
}
function crStudio(btn){
  apiAction(btn, 'creations_studio_open').then(r => {
    if(!r || !r.ok) return;
    ST.data = r; ST.title = r.title || ''; ST.parts = (r.parts || []).map(p => Object.assign({}, p));
    openPanel({title: t('creations.studio.title'), wide: true, opener: btn, render: stHtml, html: stHtml(), wire: stWire});
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
