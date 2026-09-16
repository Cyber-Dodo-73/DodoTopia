// DodoTopia : activité Cuisine (boucle de cuisine dans le jeu, configuration de la zone).
// Etats de cook.py : state idle | calibrating | cooking ; configuration en etapes (STEPS, F3), recapture des
// icones (cook_calibrate('icons')), test de detection (cook_test -> test_result), boucle avec compteurs
// dishes/fires/elapsed. Le reglage cook.max_dishes vaut 0 pour « en continu » : l'interface le presente comme
// un choix explicite « Quantité définie » / « En continu ».
// Textes : t('cook.*') au moment du rendu (le catalogue change a chaud) ; les textes venus du moteur
// (phase, message, test_result, stop_reason, titres des etapes) sont affiches tels quels.
function cookState(){ return (S && S.cook) ? S.cook : null; }
function cookTestOk(c){ return !!(c.test_result && !/aucune|introuvable|pas reconnue|rien|erreur|impossible|échec|not found|not recognised|not recognized|nothing|error|fail|unable|cannot/i.test(c.test_result)); }
// « 2 cuisinières suivies · 1 en cuisson, 1 prête » : resume sobre de l'etat de chaque cuisinière (status.burners)
// cles resolues par etat (declarees pour i18n_check) : t('cook.session.burner_cook') t('cook.session.burner_cooking')
// t('cook.session.burner_spatula') t('cook.session.burner_ready') t('cook.session.burner_none')
const COOK_BURNER_KEYS = {cook: 'cook.session.burner_cook', cooking: 'cook.session.burner_cooking',
  spatula: 'cook.session.burner_spatula', ready: 'cook.session.burner_ready', none: 'cook.session.burner_none'};
function cookBurnersText(c){
  const n = (c.settings && c.settings.cookers) || c.cookers || 1;
  if(n < 2) return '';
  const list = c.burners || [];
  if(!list.length) return t('cook.session.burners_none', {n});
  const order = ['spatula', 'ready', 'cooking', 'cook', 'none'], by = {};
  list.forEach(b => { by[b.state] = (by[b.state] || 0) + 1; });
  const parts = order.filter(k => by[k]).map(k => t(COOK_BURNER_KEYS[k], {n: by[k]}));
  const tracked = t('cook.session.burners_tracked', {n: list.length});
  return parts.length ? t('cook.session.burners_summary', {tracked, parts: parts.join(', ')}) : tracked;
}
// résumé de la configuration : ce qui est prêt, ce qui manque
function cookConfigSummary(c){
  const refs = c.refs || {};
  if(!c.calibrated){
    const missCook = !refs.cook, missReady = !refs.ready;
    if(!missCook && !missReady) return t('cook.config.summary_todo');
    return t('cook.config.summary_todo_missing', {missing: missCook && missReady ? 'both' : missCook ? 'cook' : 'ready'});
  }
  const spatula = !!refs.spatula, ring = !!c.ring_color;
  return t('cook.config.summary_ok', {spatula: spatula ? 'yes' : 'no', ring: ring ? 'yes' : 'no', extra: (spatula || ring) ? 'some' : 'none'});
}
function renderCook(st){
  const c = st.cook; if(!c) return;
  const hk = st.hotkeys || {};
  const stopKey = hk.stop || 'F7', playKey = hk.play_pause || 'F6';
  const cooking = c.state === 'cooking', calib = c.state === 'calibrating';
  const s = c.settings || {};
  const tested = cookTestOk(c);
  const nCook = Number(s.cookers || c.cookers || 1);
  const maxDishes = Number(s.max_dishes || 0);
  const endless = maxDishes === 0;

  // ---- réglages de la session : quantité (explicite) et cuisinières
  segMark($('cookQty'), b => b.dataset.v === (endless ? 'endless' : 'limited'));
  $('cookQtyNum').hidden = endless;
  const inp = $('cookDishes');
  if(document.activeElement !== inp && !endless && String(inp.value) !== String(maxDishes)) inp.value = maxDishes;
  txt('cookQtyHelp', endless ? t('cook.session.qty_endless_help') : '');
  $('cookQtyHelp').hidden = !endless;
  segMark($('cookCookers'), b => Number(b.dataset.v) === nCook);
  $('cookCookers').querySelectorAll('button').forEach(b => { b.disabled = cooking || calib; });
  $('cookQty').querySelectorAll('button').forEach(b => { b.disabled = cooking || calib; });
  inp.disabled = cooking || calib;
  // a une seule cuisiniere il n'y a rien a expliquer : la contrainte ne devient utile qu'au-dela.
  txt('cookCookersHelp', nCook > 1 ? t('cook.session.cookers_help', {n: nCook}) : '');
  $('cookCookersHelp').hidden = nCook <= 1;

  // ---- configuration : résumé + détail
  const refs = c.refs || {};
  const items = [
    ['positions', t('cook.config.item_positions'), c.calibrated ? 'ok' : 'no'],
    ['cook', t('cook.config.item_cook'), refs.cook ? 'ok' : 'no'],
    ['ready', t('cook.config.item_ready'), refs.ready ? 'ok' : 'no'],
    ['spatula', t('cook.config.item_spatula'), refs.spatula ? 'ok' : 'opt'],
    ['ring', t('cook.config.item_ring'), c.ring_color ? 'ok' : 'opt'],
  ];
  const lsig = JSON.stringify(items) + I18N.lang;
  if($('cookRefs').dataset.sig !== lsig){
    $('cookRefs').dataset.sig = lsig;
    $('cookRefs').innerHTML = items.map(([k, label, state]) => `<li class="${state}"><span class="st" aria-hidden="true">${icon(state === 'ok' ? 'check' : state === 'no' ? 'close' : 'minus')}</span>${esc(label)}${state === 'opt' ? `<small>${esc(t('cook.config.optional'))}</small>` : ''}</li>`).join('');
  }
  const badge = $('cookCalibBadge');
  const bcls = 'chip chip--badge ' + (c.calibrated ? 'chip--ok' : 'chip--warn');
  if(badge.className !== bcls) badge.className = bcls;
  txt('cookCalibBadge', c.calibrated ? t('cook.config.badge_ok') : t('cook.config.badge_todo'));
  txt('cookConfigSum', cookConfigSummary(c));
  $('btnCookCalib').disabled = cooking || calib;
  // deux intentions, deux boutons : « Tester » lit l'écran, « Modifier » rouvre l'assistant
  txt('btnCookCalib', c.calibrated ? t('cook.config.modify') : t('cook.config.configure'));
  $('btnCookIcons').disabled = cooking || calib || !c.calibrated;
  $('btnCookTest').disabled = cooking || calib || !c.calibrated;
  // Le test est facultatif et son bouton est juste au-dessus : annoncer « non testée » au repos
  // n'apprend rien. On n'affiche une pastille qu'une fois qu'il y a un résultat.
  setNotice('cookTest', !c.calibrated || !c.test_result ? null
    // Succès : le détail brut du moteur (coordonnées, scores de correspondance) n'apprend rien à qui
    // cuisine ; on ne le montre qu'en mode debug. En échec, il reste la seule piste : on le garde.
    : tested ? {text: t('cook.config.test_ok') + (st.debug ? ' ' + c.test_result : ''), kind: 'ok', icon: 'search'}
    : {text: t('cook.config.test_fail', {detail: c.test_result}), kind: 'warn', icon: 'search'});
  // rappel d'arrêt : utile pendant la boucle, encombrant au repos
  txt('cookStopHelp', t('cook.session.stop_help', {key: stopKey}));
  $('cookStopHelp').hidden = !cooking;

  // ---- bouton principal. Le moteur n'exige JAMAIS le test avant de cuisiner (cook.py, Cooker.start ne
  // regarde que l'état, calibrated() et SCREEN_OK) : il n'y a donc pas d'étape « Vérifier » à franchir.
  $('cookCta').hidden = cooking;
  // pendant la boucle, le panneau principal sert au suivi : les réglages et la configuration s'effacent
  $('cookSession2').hidden = cooking;
  $('cookConfig').hidden = cooking;
  const b = $('btnCook');
  let label, cls = 'btn btn--lg btn--cta';
  if(cooking){ label = t('cook.run.stop'); cls = 'btn btn--lg btn--danger'; }
  else if(!c.calibrated) label = t('cook.config.configure');
  else label = LABELS.cook;
  if(b.className !== cls) b.className = cls;
  b.querySelector('use').setAttribute('href', cooking ? '#i-stop' : c.calibrated ? '#i-pot' : '#i-target');
  txt('cookLabel', label);
  txt('cookKey', cooking ? stopKey : playKey);
  $('cookKey').hidden = !cooking && !c.calibrated;
  // action indisponible : la raison est ecrite sous le bouton (setAction)
  setAction(b, {disabled: calib || c.screen_ok === false,
    reason: c.screen_ok === false ? t('cook.run.no_screen_title') : calib ? t('cook.run.why_calib') : ''});

  const pill = $('cookPill');
  let pc = 'pill', pt = t('cook.run.pill_todo'), pi = 'target';
  if(cooking && c.countdown > 0){ pc = 'pill paused'; pi = 'hourglass'; pt = t('cook.run.pill_countdown', {n: Math.ceil(c.countdown)}); }
  else if(cooking){ pc = 'pill game'; pi = 'pot'; pt = t('cook.run.pill_cooking', {phase: cap(plain(c.phase || t('cook.run.phase_default')))}); }
  else if(calib){ pc = 'pill paused'; pi = 'target'; pt = t('cook.run.pill_config'); }
  else if(c.calibrated){ pc = 'pill preview'; pi = 'check'; pt = t('cook.run.pill_ready'); }
  if(pill.className !== pc) pill.className = pc;
  html('cookPill', icon(pi) + `<span>${esc(plain(pt))}</span>`);
  $('cookDisc').classList.toggle('spin', cooking);
  txt('cookHeadline', cooking ? t('cook.run.headline_cooking', {n: c.dishes + 1}) : t('cook.run.headline_idle'));
  txt('cookSub', cooking ? (c.phase ? cap(c.phase) : t('cook.run.sub_starting'))
    : (c.calibrated ? t('cook.run.sub_ready') : t('cook.run.sub_todo')));
  // fin de session : objectif atteint, arrêt volontaire et erreur sont distingués
  let lastState;
  if(c.stop_reason === 'objectif') lastState = t('cook.run.last_goal');
  else if(c.stop_reason) lastState = t('cook.run.last_stop', {reason: c.stop_reason});
  else lastState = c.message || (c.calibrated ? t('cook.run.last_ready') : t('cook.run.last_todo'));
  const burners = cookBurnersText(c);
  // Avant lancement, des compteurs à zéro n'apprennent rien : une seule ligne rappelle la session passée.
  // Les messages *_html ne contiennent que du balisage sur et des nombres ; les textes du moteur passent par esc().
  if(cooking){
    html('cookStats', `<span class="stat">${icon('plate')}${plain(maxDishes ? t('cook.run.stat_dishes_of_html', {n: c.dishes, max: maxDishes}) : t('cook.run.stat_dishes_html', {n: c.dishes}))}</span>`
      + `<span class="stat">${icon('fire')}${plain(t('cook.run.stat_fires_html', {n: c.fires}))}</span>`
      + (burners ? `<span class="stat" title="${esc(t('cook.run.stat_burners_title'))}">${icon('pot')}${esc(burners)}</span>` : '')
      + `<span class="stat">${icon('timer')}<b>${esc(fmtDur(c.elapsed))}</b></span>`);
  } else if(c.dishes > 0){
    html('cookStats', `<span class="stat">${icon('info')}${plain(t('cook.run.stat_last_html', {dishes: c.dishes, fires: c.fires || 0, state: esc(lastState)}))}</span>`);
  } else html('cookStats', '');

  let spec = null;
  if(cooking && c.countdown > 0){
    spec = {count: Math.ceil(c.countdown), unit: t('image.run.unit_seconds'), role: t('cook.run.role_cook'), text: t('cook.run.countdown_text'),
            meta: t('cook.run.meta_cancel', {key: stopKey}), actions: [{label: LABELS.cancel, kbd: stopKey, api: 'cook_stop'}]};
  } else if(cooking){
    spec = {live: true, count: c.dishes, unit: t('cook.run.unit_dishes', {n: c.dishes}), role: t('cook.run.role_cooking'),
            text: c.phase ? cap(c.phase) : t('cook.run.cooking_text'),
            meta: t('cook.run.cooking_meta', {time: fmtDur(c.elapsed), max: maxDishes, key: stopKey}),
            progress: maxDishes ? {pct: Math.min(100, c.dishes / maxDishes * 100), left: t('cook.run.progress_left', {done: c.dishes, max: maxDishes}), right: t('cook.run.progress_right')} : null,
            actions: [{label: LABELS.stop, icon: 'stop', kbd: stopKey, api: 'cook_stop'}]};
  }
  renderSession($('cookSession'), spec);

  let notice = null;
  if(!cooking){
    if(c.screen_ok === false) notice = {text: t('cook.run.no_screen'), kind: 'danger'};
    else if(c.message && /arrêtée|impossible|introuvable|erreur|stopped|unable|cannot|not found|error|fail/i.test(c.message)) notice = {text: c.message, kind: 'warn'};
    else if(!c.calibrated) notice = {text: t('cook.run.notice_todo'), kind: 'warn'};
    else if(nCook > 1) notice = {text: t('cook.run.notice_multi', {n: nCook, key: playKey}), kind: 'ok', icon: 'check'};
    else notice = {text: t('cook.run.notice_ready', {key: playKey}), kind: 'ok', icon: 'check'};
  }
  setNotice('cookNotice', notice);

  if(calib){
    renderCalibOverlay({
      kind: 'cook',
      title: t('cook.config.configure'),
      prep: t('cook.config.calib_prep_html'),
      steps: c.steps || [], step: c.step, hk, message: c.message,
      skippable: s => !!s.optional,
      cancel: 'cook_calibrate_cancel', skip: 'cook_calibrate_skip', back: 'cook_calibrate_back', goto: 'cook_calibrate_goto'});
  }
}
$('btnCook').onclick = () => {
  const c = cookState();
  if(c && c.state === 'cooking'){ api('cook_stop'); return; }
  if(c && !c.calibrated){ api('cook_calibrate', 'all'); return; }
  const s = (c && c.settings) || {};
  const max = Number(s.max_dishes || 0);
  dialog({title: LABELS.cook, icon: 'pot', ok: t('cook.run.start_ok'), cancel: t('common.cancel'),
          html: t('cook.run.start_html', {qty: max ? t('cook.session.qty_limited', {n: max}) : t('cook.session.qty_endless'), cookers: Number(s.cookers || 1)})})
    .then(yes => { if(yes) api('cook_start'); });
};
document.querySelectorAll('#cookCookers > button').forEach(b => b.onclick = () => {
  segMark($('cookCookers'), x => x === b);
  api('set_setting', 'cook.cookers', Number(b.dataset.v));
});
// quantité : choix explicite ; « En continu » écrit 0, la représentation interne ne change pas
document.querySelectorAll('#cookQty > button').forEach(b => b.onclick = () => {
  segMark($('cookQty'), x => x === b);
  if(b.dataset.v === 'endless'){ $('cookQtyNum').hidden = true; api('set_setting', 'cook.max_dishes', 0); }
  else {
    $('cookQtyNum').hidden = false;
    const v = Math.max(1, Math.min(999, Number($('cookDishes').value) || 10));
    $('cookDishes').value = v;
    api('set_setting', 'cook.max_dishes', v);
  }
});
$('cookDishes').onchange = () => {
  const v = Math.max(1, Math.min(999, Number($('cookDishes').value) || 1));
  $('cookDishes').value = v;
  api('set_setting', 'cook.max_dishes', v);
};
$('cookDishes').onkeydown = e => { e.stopPropagation(); if(e.key === 'Enter') $('cookDishes').blur(); };
$('btnCookCalib').onclick = () => api('cook_calibrate', 'all');
$('btnCookIcons').onclick = () => api('cook_calibrate', 'icons');
$('btnCookTest').onclick = () => api('cook_test');
$('btnCookLog').onclick = () => api(window.pywebview && !window.pywebview.api.open_log ? 'open_cook_log' : 'open_log', 'cuisine');
view('cook', {draw: renderCook});   // enregistree apres la vue « draw » : l'assistant partage est ferme par draw, rouvert ici
