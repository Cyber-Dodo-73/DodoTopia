// DodoTopia : onglet Cuisine (boucle de cuisine dans le jeu, calibrage).
// Etats de cook.py : state idle | calibrating | cooking ; calibrage en etapes (STEPS, F3), recapture des icones
// (cook_calibrate('icons')), test de detection (cook_test -> test_result), boucle avec compteurs dishes/fires/elapsed.
// ------------------------------------------------ page Cuisine
function cookState(){ return (S && S.cook) ? S.cook : null; }
function cookTestOk(c){ return !!(c.test_result && !/aucune|introuvable|pas reconnue|rien|erreur|impossible/i.test(c.test_result)); }
// « 2 cuisinières suivies · 1 en cuisson, 1 prête » : resume sobre de l'etat de chaque cuisinière (status.burners)
const COOK_BURNER_LABELS = {cook: ['au repos', 'au repos'], cooking: ['en cuisson', 'en cuisson'],
  spatula: ['feu à régler', 'feux à régler'], ready: ['prête', 'prêtes'], none: ['non vue', 'non vues']};
function cookBurnersText(c){
  const n = (c.settings && c.settings.cookers) || c.cookers || 1;
  if(n < 2) return '';
  const list = c.burners || [];
  if(!list.length) return `${n} cuisinières · aucune bulle repérée pour l'instant`;
  const order = ['spatula', 'ready', 'cooking', 'cook', 'none'], by = {};
  list.forEach(b => { by[b.state] = (by[b.state] || 0) + 1; });
  const parts = order.filter(k => by[k]).map(k => `${by[k]} ${COOK_BURNER_LABELS[k][by[k] > 1 ? 1 : 0]}`);
  return `${list.length} cuisinière${list.length > 1 ? 's' : ''} suivie${list.length > 1 ? 's' : ''}`
    + (parts.length ? ' · ' + parts.join(', ') : '');
}
function renderCook(st){
  const c = st.cook; if(!c) return;
  const hk = st.hotkeys || {};
  const cooking = c.state === 'cooking', calib = c.state === 'calibrating';
  const s = c.settings || {};
  const tested = cookTestOk(c);
  const next = !c.calibrated ? 'calib' : !tested ? 'test' : 'cook';

  // colonne de gauche : etat du calibrage
  const refs = c.refs || {};
  const items = [
    ['positions', 'Positions (zone, tuile, bouton, herbe)', c.calibrated ? 'ok' : 'no'],
    ['cook', 'Icône « cuisiner »', refs.cook ? 'ok' : 'no'],
    ['ready', 'Icône « gants »', refs.ready ? 'ok' : 'no'],
    ['spatula', 'Icône « spatule »', refs.spatula ? 'ok' : 'opt'],
    ['ring', 'Couleur de l’anneau vert', c.ring_color ? 'ok' : 'opt'],
  ];
  const lsig = JSON.stringify(items);
  if($('cookRefs').dataset.sig !== lsig){
    $('cookRefs').dataset.sig = lsig;
    $('cookRefs').innerHTML = items.map(([k, label, state]) => `<li class="${state}"><span class="st">${state === 'ok' ? '✓' : state === 'no' ? '✗' : '–'}</span>${esc(label)}${state === 'opt' ? '<small>facultatif</small>' : ''}</li>`).join('');
  }
  const badge = $('cookCalibBadge');
  const bcls = 'chip chip--badge ' + (c.calibrated ? 'chip--ok' : 'chip--warn');
  if(badge.className !== bcls) badge.className = bcls;
  txt('cookCalibBadge', c.calibrated ? 'calibré' : 'non calibré');
  $('btnCookCalib').disabled = cooking || calib;
  $('btnCookIcons').disabled = cooking || calib || !c.calibrated;
  $('btnCookTest').disabled = cooking || calib || !c.calibrated;
  txt('cookStopKey', hk.stop || 'F7');
  setNotice('cookTest', c.test_result ? {text: c.test_result, kind: tested ? 'ok' : 'warn', icon: '🔍'} : null);
  // segmenté « Cuisinières : 1 2 3 4 » (réglage cook.cookers, aussi dans Réglages › Cuisine)
  const nCook = Number(s.cookers || c.cookers || 1);
  segMark($('cookCookers'), b => Number(b.dataset.v) === nCook);
  $('cookCookers').querySelectorAll('button').forEach(b => { b.disabled = cooking || calib; });

  // colonne de droite : stepper, bouton principal, compteurs, bandeau
  const done = [];
  if(c.calibrated) done.push('calib');
  if(tested) done.push('test');
  stepsMark($('cookSteps'), done, cooking ? 'cook' : next);
  // pendant la cuisine, le bandeau de session porte seul l'action Arreter (comme l'onglet Musique)
  $('cookSteps').hidden = cooking;
  $('cookCta').hidden = cooking;
  const b = $('btnCook');
  let label, cls = 'btn btn--lg btn--cta';
  if(cooking){ label = 'Arrêter la cuisine'; cls = 'btn btn--lg btn--danger'; }
  else if(next === 'calib') label = 'Calibrer la cuisine';
  else if(next === 'test') label = 'Tester la détection';
  else label = LABELS.cook;
  if(b.className !== cls) b.className = cls;
  txt('cookLabel', label);
  txt('cookKey', cooking ? (hk.stop || 'F7') : (hk.play_pause || 'F6'));
  $('cookKey').hidden = !cooking && next !== 'cook';
  b.disabled = calib;

  const pill = $('cookPill');
  let pc = 'pill', pt = 'Non calibré';
  if(cooking && c.countdown > 0){ pc = 'pill paused'; pt = `⏳ ${Math.ceil(c.countdown)} s`; }
  else if(cooking){ pc = 'pill game'; pt = '🍳 ' + (c.phase || 'Cuisine en cours'); }
  else if(calib){ pc = 'pill paused'; pt = '🎯 Calibrage'; }
  else if(c.calibrated){ pc = 'pill preview'; pt = '✓ Calibré'; }
  if(pill.className !== pc) pill.className = pc;
  txt('cookPill', pt);
  $('cookDisc').classList.toggle('spin', cooking);
  txt('cookTitle', cooking ? `Plat ${c.dishes + 1} en cours` : 'Cuisine automatique');
  txt('cookSub', cooking ? (c.phase ? cap(c.phase) : 'Démarrage…') : (c.calibrated ? 'Place-toi devant la cuisinière, puis lance la boucle' : 'Calibre, puis lance la boucle devant la cuisinière'));
  const lastState = c.stop_reason ? `arrêt : ${c.stop_reason}` : (c.message || (c.calibrated ? 'prêt' : 'à calibrer'));
  const burners = cookBurnersText(c);
  html('cookStats', `<span class="stat">🍽️ <b>${c.dishes}</b>${s.max_dishes ? ` / ${s.max_dishes}` : ''} plat${c.dishes > 1 ? 's' : ''}</span>`
    + `<span class="stat">🔥 <b>${c.fires}</b> feu${c.fires > 1 ? 'x' : ''} ajusté${c.fires > 1 ? 's' : ''}</span>`
    + (burners ? `<span class="stat" title="Une machine à états par cuisinière">🍳 ${esc(burners)}</span>` : '')
    + (cooking ? `<span class="stat">⏱️ <b>${fmtDur(c.elapsed)}</b></span>` : `<span class="stat" title="Dernier état">🛈 ${esc(lastState)}</span>`));

  let spec = null;
  if(cooking && c.countdown > 0){
    spec = {count: Math.ceil(c.countdown), unit: 's', role: 'Cuisine', text: 'Passe sur Heartopia, devant la cuisinière, et ne touche plus à rien.',
            meta: `${hk.stop || 'F7'} annule`, actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'cook_stop'}]};
  } else if(cooking){
    spec = {live: true, count: c.dishes, unit: c.dishes > 1 ? 'plats' : 'plat', role: 'Cuisine dans Heartopia',
            text: c.phase ? cap(c.phase) : 'Cuisine en cours…',
            meta: `${fmtDur(c.elapsed)}${s.max_dishes ? ` · ${c.dishes} / ${s.max_dishes} plats` : ''} · ${hk.stop || 'F7'} arrête · ne touche ni à la souris ni au clavier`,
            actions: [{label: LABELS.stop, kbd: hk.stop || 'F7', api: 'cook_stop'}]};
  }
  renderSession($('cookSession'), spec);

  let notice = null;
  if(!cooking){
    if(c.message && /arrêtée|impossible|introuvable|erreur/i.test(c.message)) notice = {text: c.message, kind: 'warn'};
    else if(c.screen_ok === false) notice = {text: 'Capture d’écran indisponible : la cuisine automatique ne peut pas fonctionner ici.', kind: 'danger'};
    else if(!c.calibrated) notice = {text: 'Pas encore calibré : place-toi devant la cuisinière dans le jeu, puis clique sur Calibrer.', kind: 'warn'};
    else if(!tested) notice = {text: 'Devant la cuisinière (bulle « cuisiner » visible), teste la détection une fois pour vérifier le calibrage.', kind: 'info'};
    else if(nCook > 1) notice = {text: `Place-toi de façon à voir les ${nCook} bulles dans la zone calibrée, puis appuie sur ${hk.play_pause || 'F6'} : DodoTopia sert les cuisinières à tour de rôle et clique l'anneau vert dès qu'il apparaît.`, kind: 'ok', icon: '✓'};
    else notice = {text: `Devant la cuisinière avec les ingrédients de la dernière recette, appuie sur ${hk.play_pause || 'F6'} : le dernier plat est refait en boucle.`, kind: 'ok', icon: '✓'};
  }
  setNotice('cookNotice', notice);

  if(calib){
    renderCalibOverlay({
      title: 'Calibrer la cuisine 🍳',
      intro: `Dans Heartopia, place-toi devant la cuisinière. Pour chaque étape, place la souris sur la cible <b>dans le jeu</b> et appuie sur <kbd>${esc(hk.draw_point || 'F3')}</kbd>. Les étapes « menu » se font le menu Recettes ouvert, l'étape « spatule » pendant une cuisson, l'étape « gants » quand le plat est prêt.`,
      steps: c.steps || [], step: c.step, hk,
      skippable: s => !!s.optional,
      cancel: 'cook_calibrate_cancel', skip: 'cook_calibrate_skip'});
  }
}
$('btnCook').onclick = () => {
  const c = cookState();
  if(c && c.state === 'cooking'){ api('cook_stop'); return; }
  if(c && !c.calibrated){ api('cook_calibrate', 'all'); return; }
  if(c && !cookTestOk(c)){ api('cook_test'); return; }
  dialog({title: LABELS.cook, icon: '🍳', ok: 'Cuisiner',
          html: `Dans Heartopia, place ton personnage <b>devant la cuisinière</b>, bulle « cuisiner » visible, avec les ingrédients de la <b>dernière recette cuisinée</b>.<br><small>La boucle démarre 3 s après : ne touche plus à la souris ni au clavier. Toute touche l'arrête.</small>`})
    .then(yes => { if(yes) api('cook_start'); });
};
document.querySelectorAll('#cookCookers > button').forEach(b => b.onclick = () => {
  segMark($('cookCookers'), x => x === b);
  api('set_setting', 'cook.cookers', Number(b.dataset.v));
});
$('btnCookCalib').onclick = () => api('cook_calibrate', 'all');
$('btnCookIcons').onclick = () => api('cook_calibrate', 'icons');
$('btnCookTest').onclick = () => api('cook_test');
$('btnCookLog').onclick = () => api(window.pywebview && !window.pywebview.api.open_log ? 'open_cook_log' : 'open_log', 'cuisine');
view('cook', {draw: renderCook});   // enregistree apres la vue « draw » : l'assistant de calibrage partage est ferme par draw, rouvert ici
