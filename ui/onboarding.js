// DodoTopia : premiere experience (decouverte en 3 etapes), etat de la fenetre du jeu (puce d'en-tete),
// « Tester une note » et confirmation des liens dodotopia://.
// Donnees : get_state().game_window {found, foreground, elevated, checked, process}, is_admin, terms, deeplink.
// Textes : cles onb.*, game.*, deeplink.* (ui/i18n/src/<lang>/onboarding.json).

// ------------------------------------------------ etat du jeu
// kind : unchecked (rien a dire) | ok (fenetre trouvee) | off (jeu non lance) | admin (jeu eleve, DodoTopia non)
function gameInfo(st){
  const g = (st && st.game_window) || {};
  if(!g.checked || g.found === null || g.found === undefined) return {kind: 'unchecked', process: g.process || ''};
  if(g.found && g.elevated && st.is_admin === false) return {kind: 'admin', process: g.process || ''};
  return {kind: g.found ? 'ok' : 'off', process: g.process || '', foreground: !!g.foreground};
}
function gameStatusText(kind){
  if(kind === 'ok') return {chip: t('game.chip.ok'), title: t('onb.game.found'), help: t('onb.game.found_help'), notice: 'ok', icon: 'check'};
  if(kind === 'off') return {chip: t('game.chip.off'), title: t('onb.game.missing'), help: t('onb.game.missing_help'), notice: 'info', icon: 'gamepad'};
  if(kind === 'admin') return {chip: t('game.chip.admin'), title: t('onb.game.elevated'), help: t('game.admin.body'), notice: 'warn', icon: 'shield'};
  return {chip: '', title: t('onb.game.unchecked'), help: t('onb.game.unchecked_help'), notice: 'info', icon: 'info'};
}
// « Comment faire » : relancer DodoTopia en administrateur
function gameAdminHelp(){
  return dialog({title: t('game.admin.title'), icon: 'shield', cancel: null, ok: t('common.ok'),
    html: `<p>${esc(t('game.admin.body'))}</p><p><small>${esc(t('game.admin.why'))}</small></p>`});
}
function gameStatusDialog(st){
  const g = gameInfo(st);
  if(g.kind === 'admin') return gameAdminHelp();
  const s = gameStatusText(g.kind);
  return dialog({title: s.title, icon: g.kind === 'ok' ? 'check' : 'gamepad', cancel: null, ok: t('common.ok'),
    html: `<p>${esc(s.help)}</p>` + (g.process ? `<p><small>${esc(t('onb.game.process', {name: g.process}))}</small></p>` : '')});
}
view('gameStatus', {sig: st => JSON.stringify([gameInfo(st), I18N.lang]), draw: st => {
  const chip = $('gameChip'); if(!chip) return;
  const g = gameInfo(st);
  if(g.kind === 'unchecked'){ chip.hidden = true; return; }
  const s = gameStatusText(g.kind);
  chip.hidden = false;
  chip.className = 'gamechip gamechip--' + g.kind;
  chip.innerHTML = `<span class="gamechip__dot" aria-hidden="true"></span>${icon(s.icon)}<span>${esc(s.chip)}</span>`;
  chip.title = s.title;
  chip.setAttribute('aria-label', s.chip + ' : ' + s.title);
  chip.onclick = () => gameStatusDialog(S);
}});

// ------------------------------------------------ « Tester une note » (test_key -> {ok, reason})
// done(res) : res = {ok, reason} | null ; sans done, le resultat part en toast
function testNote(btn, done){
  const sd = Number(((S || {}).settings || {}).start_delay);
  const delay = isNaN(sd) ? 1 : sd;
  toast(t('game.test.go_back', {delay}), 'info');
  return apiAction(btn, 'test_key').then(r => {
    const res = r && typeof r === 'object' ? {ok: !!r.ok, reason: r.reason || ''} : null;
    if(done) done(res);
    else if(res) toast(res.reason || t(res.ok ? 'game.test.ok' : 'common.action_failed'), res.ok ? 'ok' : 'warn');
    return res;
  });
}

// ------------------------------------------------ premiere experience
const ONB_KEY = 'dodotopia.onboarded';
const ONB_STEPS = ['welcome', 'game', 'song'];
const ONB = {step: 0, shown: false, test: null};
function onbDone(){ try{ return localStorage.getItem(ONB_KEY) === '1'; }catch(e){ return false; } }
function onbMark(){ try{ localStorage.setItem(ONB_KEY, '1'); }catch(e){} }
function onbOpen(){ const o = $('onbOverlay'); return !!(o && o.classList.contains('open')); }
function onbEnsure(){
  if($('onbOverlay')) return $('onbOverlay');
  const o = document.createElement('div');
  o.className = 'overlay'; o.id = 'onbOverlay';
  o.innerHTML = `<div class="modal onb" role="dialog" aria-modal="true" aria-labelledby="onbTitle">
      <ol class="steps steps--h onb__steps" id="onbSteps">${ONB_STEPS.map((k, i) => `<li data-step="${k}"><span class="n">${i + 1}</span><span class="onb__stepnm"></span></li>`).join('')}</ol>
      <p class="calib__count" id="onbCount"></p>
      <h2 id="onbTitle" tabindex="-1"></h2>
      <div class="onb__body" id="onbBody"></div>
      <div class="actions">
        <button class="btn btn--ghost" type="button" id="onbSkip"></button>
        <div class="spacer"></div>
        <button class="btn btn--secondary" type="button" id="onbBack">${icon('arrow-left')}<span></span></button>
        <button class="btn btn--cta" type="button" id="onbNext"><span></span>${icon('arrow-right')}</button>
      </div>
    </div>`;
  // avant les autres modales dans le DOM : le selecteur d'instrument et les dialogues s'ouvrent PAR-DESSUS
  const anchor = $('overlay');
  if(anchor && anchor.parentNode) anchor.insertAdjacentElement('afterend', o); else document.body.appendChild(o);
  $('onbSkip').onclick = () => closeOnboarding();
  $('onbBack').onclick = () => { if(ONB.step > 0){ ONB.step--; onbDraw(S, true); } };
  $('onbNext').onclick = () => {
    if(ONB.step >= ONB_STEPS.length - 1){ closeOnboarding(); return; }
    ONB.step++; onbDraw(S, true);
  };
  return o;
}
function openOnboarding(step){
  onbEnsure();
  ONB.step = Math.max(0, Math.min(ONB_STEPS.length - 1, Number(step) || 0));
  ONB.test = null;
  ONB.shown = true;
  openModal($('onbOverlay'), document.activeElement, null, () => closeOnboarding());
  onbDraw(S, true);
}
function closeOnboarding(){
  onbMark();
  if(onbOpen()) closeModal($('onbOverlay'));
}
function onbLangOptions(){
  const cur = I18N.lang;
  const list = LANGS_AVAILABLE.length ? LANGS_AVAILABLE : [{tag: cur, name: cur, beta: false}];
  return list.map(a => `<option value="${esc(a.tag)}"${a.tag === cur ? ' selected' : ''}>${esc(a.beta ? t('settings.general.lang.opt_beta', {name: a.name}) : a.name)}</option>`).join('');
}
function onbBody(st, key){
  if(key === 'welcome'){
    const theme = getTheme();
    const opts = [['auto', t('settings.general.theme.auto'), 'monitor'], ['light', t('settings.general.theme.light'), 'sun'], ['dark', t('settings.general.theme.dark'), 'moon']];
    return `<p class="onb__intro">${esc(t('onb.welcome.intro'))}</p>
      <div class="onb__fields">
        <div class="field sfield"><label class="field__label" for="onbLang">${esc(t('onb.welcome.lang'))}</label>
          <span class="field__help">${esc(t('onb.welcome.lang_help'))}</span>
          <div class="field__control"><select class="select" id="onbLang">${onbLangOptions()}</select></div></div>
        <div class="field sfield"><span class="field__label" id="onbThemeL">${esc(t('onb.welcome.theme'))}</span>
          <div class="field__control"><div class="seg" id="onbTheme" role="radiogroup" aria-labelledby="onbThemeL">${opts.map(([v, l, ic]) =>
            `<button type="button" role="radio" data-v="${v}" aria-checked="${v === theme}" class="${v === theme ? 'active' : ''}" tabindex="${v === theme ? 0 : -1}">${icon(ic)}<span>${esc(l)}</span></button>`).join('')}</div></div></div>
      </div>`;
  }
  if(key === 'game'){
    const g = gameInfo(st || {});
    const s = gameStatusText(g.kind);
    return `<p class="onb__intro">${esc(t('onb.game.intro'))}</p>
      <div class="notice notice--${s.notice} onb__game" role="status"><span class="notice__ic" aria-hidden="true">${icon(s.icon)}</span>
        <div class="notice__text"><b>${esc(s.title)}</b><br>${esc(s.help)}
          ${g.process ? `<div class="onb__proc">${esc(t('onb.game.process', {name: g.process}))}</div>` : ''}
          ${g.kind === 'admin' ? `<div class="notice__actions"><button class="btn btn--secondary btn--sm" type="button" data-act="adminhow">${esc(t('game.notice.how'))}</button></div>` : ''}
        </div></div>
      <p class="hint left">${esc(t('onb.game.tip'))}</p>`;
  }
  // premier morceau
  const ins = typeof curInstrument === 'function' ? curInstrument(st || {}) : null;
  const ready = ins && typeof instrumentReady === 'function' ? instrumentReady(st || {}) : false;
  const sd = Number(((st || {}).settings || {}).start_delay);
  const r = ONB.test;
  const testWhy = !ready ? t('api.test_key.no_keys') : (st || {}).state !== 'stopped' ? t('api.test_key.stop_first') : '';
  return `<p class="onb__intro">${esc(t('onb.song.intro'))}</p>
    <div class="onb__cards">
      <section class="onb__card"><span class="onb__num">1</span><div class="onb__cardtxt"><b>${esc(t('onb.song.add'))}</b>
        <div class="btnrow"><button class="btn btn--cta btn--sm" type="button" data-act="import">${icon('plus')}<span>${esc(t('onb.song.import'))}</span></button>
        <button class="btn btn--secondary btn--sm" type="button" data-act="discover">${icon('globe')}<span>${esc(t('onb.song.discover'))}</span></button></div></div></section>
      <section class="onb__card"><span class="onb__num">2</span><div class="onb__cardtxt"><b>${esc(t('onb.song.instrument_title'))}</b>
        <span class="hint left">${esc(ins ? t('onb.song.instrument_current', {name: instrumentDisplayName(ins)}) : '')}</span>
        <div class="btnrow"><button class="btn btn--secondary btn--sm" type="button" data-act="inst">${icon('music')}<span>${esc(t('onb.song.instrument'))}</span></button></div></div></section>
      <section class="onb__card"><span class="onb__num">3</span><div class="onb__cardtxt"><b>${esc(t('onb.song.test_title'))}</b>
        <span class="hint left">${esc(t('onb.song.test_hint', {delay: isNaN(sd) ? 1 : sd}))}</span>
        <div class="btnrow"><button class="btn btn--secondary btn--sm" type="button" data-act="test"${testWhy ? ' disabled' : ''}>${icon('note')}<span>${esc(t('game.test.btn'))}</span></button></div>
        ${testWhy ? `<p class="btn__why onb__why">${icon('info')}<span>${esc(testWhy)}</span></p>` : ''}
        ${r ? `<div class="notice notice--${r.ok ? 'ok' : 'warn'}" role="status"><span class="notice__ic" aria-hidden="true">${icon(r.ok ? 'check' : 'warn')}</span><div class="notice__text">${esc(r.reason || (r.ok ? t('game.test.ok') : t('common.action_failed')))}</div></div>` : ''}
      </div></section>
    </div>`;
}
function onbWire(box){
  const lang = box.querySelector('#onbLang');
  if(lang) lang.onchange = () => {
    const v = lang.value;
    api('set_setting', 'general.lang', v).then(r => { if(r == null && window.MOCK_I18N) applyLanguage(v); });
  };
  const seg = box.querySelector('#onbTheme');
  if(seg) seg.querySelectorAll('button').forEach(b => b.onclick = () => { segMark(seg, x => x === b); setTheme(b.dataset.v); });
  const on = (act, fn) => { const b = box.querySelector(`[data-act="${act}"]`); if(b) b.onclick = () => fn(b); };
  on('adminhow', () => gameAdminHelp());
  on('import', b => apiAction(b, 'import_dialog'));
  on('discover', () => { closeOnboarding(); showTab('music'); showMusicView('discover'); });
  on('inst', () => { if(typeof openInstrumentSelector === 'function') openInstrumentSelector(); });
  on('test', b => testNote(b, res => { ONB.test = res || {ok: false, reason: t('common.action_failed')}; if(onbOpen()) onbDraw(S, true); }));
}
function onbDraw(st, force){
  if(!onbOpen()) return;
  const key = ONB_STEPS[ONB.step];
  // pas de redessin pendant un appel en cours ou une saisie (liste des langues ouverte)
  const busy = $('onbBody').querySelector('.is-loading');
  if(busy && !force) return;
  const names = [t('onb.step.welcome'), t('onb.step.game'), t('onb.step.song')];
  $('onbSteps').querySelectorAll('.onb__stepnm').forEach((el, i) => { el.textContent = names[i]; });
  $('onbSteps').setAttribute('aria-label', t('onb.progress_aria'));
  stepsMark($('onbSteps'), ONB_STEPS.slice(0, ONB.step), key);
  txt('onbCount', t('onb.count', {n: ONB.step + 1, total: ONB_STEPS.length}));
  txt('onbTitle', key === 'welcome' ? t('onb.welcome.title') : key === 'game' ? t('onb.game.title') : t('onb.song.title'));
  const body = $('onbBody');
  body.innerHTML = onbBody(st || {}, key);
  onbWire(body);
  $('onbSkip').textContent = t('onb.skip');
  $('onbBack').hidden = ONB.step === 0;
  $('onbBack').querySelector('span').textContent = t('common.back');
  const last = ONB.step >= ONB_STEPS.length - 1;
  $('onbNext').querySelector('span').textContent = last ? t('onb.finish') : t('onb.next');
  $('onbNext').querySelector('.ic').style.display = last ? 'none' : '';
  $('onbSkip').hidden = last;
  if(force) setTimeout(() => { if(onbOpen()) $('onbTitle').focus(); }, 30);
}
// Affichage automatique au premier lancement, une fois les conditions acceptees. Le stockage local est
// persistant (app.py : private_mode=False, storage_path). Garde-fou si ce stockage est vide alors que
// l'application a deja servi (dossier efface, profil WebView2 reinitialise) : on ne l'impose pas a quelqu'un
// qui a deja des morceaux.
function onbShouldAuto(st){
  if(ONB.shown || !st || (st.terms && st.terms.required) || st.deeplink) return false;
  if(!window.pywebview) return /[?&]onboarding(?:=[a-z]+)?(?:&|$)/.test(location.search);   // apercu : &onboarding[=game|song]
  if(onbDone()) return false;
  return !(st.songs || []).length;
}
view('onboarding', {sig: st => {
  const open = onbOpen();
  const key = ONB_STEPS[ONB.step];
  return JSON.stringify([open, ONB.step, !!(st.terms && st.terms.required), !!st.deeplink, I18N.lang,
    open && key === 'game' ? gameInfo(st) : null,
    open && key === 'song' ? [st.instrument_id, st.instrument_ready, st.state] : null]);
}, draw: st => {
  if(onbShouldAuto(st)){
    const m = /[?&]onboarding=([a-z]+)/.exec(window.pywebview ? '' : location.search);
    openOnboarding(m ? Math.max(0, ONB_STEPS.indexOf(m[1])) : 0);
    return;
  }
  if(onbOpen()) onbDraw(st, false);
}});

// ------------------------------------------------ liens dodotopia:// a confirmer (get_state().deeplink)
const DL = {id: null, handled: null};
function deeplinkTitle(action){
  if(action === 'song') return t('deeplink.title.song');
  if(action === 'room') return t('deeplink.title.room');
  if(action === 'drawing') return t('deeplink.title.drawing');
  return t('deeplink.title.import');
}
function deeplinkEnsure(){
  if($('dlOverlay')) return $('dlOverlay');
  const o = document.createElement('div');
  o.className = 'dlg-overlay'; o.id = 'dlOverlay';
  o.innerHTML = `<div class="dlg" role="alertdialog" aria-modal="true" aria-labelledby="dlTitle" aria-describedby="dlBody">
      <div class="dlg-head">${icon('link', 'dlg-head__ic')}<h2 id="dlTitle"></h2></div>
      <div class="dlg-body" id="dlBody"></div>
      <div class="dlg-actions">
        <button class="dlg-btn cancel" type="button" id="dlDismiss"></button>
        <button class="dlg-btn ok" type="button" id="dlConfirm"></button>
      </div></div>`;
  document.body.appendChild(o);
  $('dlDismiss').onclick = () => deeplinkAnswer(false);
  $('dlConfirm').onclick = () => deeplinkAnswer(true);
  return o;
}
function deeplinkClose(){ const o = $('dlOverlay'); if(o && o.classList.contains('open')) closeModal(o); }
function deeplinkAnswer(yes){
  const id = DL.id;
  if(id == null) return;
  DL.handled = id;
  const btn = yes ? $('dlConfirm') : $('dlDismiss');
  apiAction(btn, yes ? 'deeplink_confirm' : 'deeplink_dismiss', id).then(() => deeplinkClose());
}
view('deeplink', {sig: st => JSON.stringify([st.deeplink || null, !!(st.terms && st.terms.required), I18N.lang]), draw: st => {
  const d = st.deeplink;
  if(!d || (st.terms && st.terms.required) || d.id === DL.handled){ deeplinkClose(); return; }
  const o = deeplinkEnsure();
  DL.id = d.id;
  $('dlTitle').textContent = deeplinkTitle(d.action);
  $('dlBody').innerHTML = `<p class="dl__label">${esc(d.label || '')}</p><p><small>${esc(t('deeplink.intro'))}</small></p>`;
  $('dlDismiss').textContent = t('deeplink.dismiss');
  $('dlConfirm').textContent = t('deeplink.confirm');
  if(!o.classList.contains('open')){
    openModal(o, document.activeElement, null, () => deeplinkAnswer(false));
    setTimeout(() => { if(o.classList.contains('open')) $('dlConfirm').focus(); }, 30);
  }
}});
