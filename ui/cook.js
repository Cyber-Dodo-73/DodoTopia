// DodoTopia : activité Cuisine (boucle de cuisine dans le jeu, configuration de la zone).
// Etats de cook.py : state idle | calibrating | cooking ; configuration en etapes (STEPS, F3), recapture des
// icones (cook_calibrate('icons')), test de detection (cook_test -> test_result), boucle avec compteurs
// dishes/fires/elapsed. Le reglage cook.max_dishes vaut 0 pour « en continu » : l'interface le presente comme
// un choix explicite « Quantité définie » / « En continu ».
function cookState(){ return (S && S.cook) ? S.cook : null; }
function cookTestOk(c){ return !!(c.test_result && !/aucune|introuvable|pas reconnue|rien|erreur|impossible|échec/i.test(c.test_result)); }
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
// résumé de la configuration : ce qui est prêt, ce qui manque
function cookConfigSummary(c){
  if(!c.calibrated){
    const miss = [];
    const refs = c.refs || {};
    if(!refs.cook) miss.push('l’icône « cuisiner »');
    if(!refs.ready) miss.push('l’icône « gants »');
    return 'Pas encore configurée' + (miss.length ? ` : il manque ${miss.join(' et ')}, et les positions à cliquer.` : ' : les positions à cliquer ne sont pas connues.');
  }
  const extra = [];
  if((c.refs || {}).spatula) extra.push('icône spatule enregistrée');
  if(c.ring_color) extra.push('couleur de l’anneau mesurée');
  return `Configurée : zone de la bulle, icônes, tuile de la dernière recette, bouton Cuisiner et coin d’herbe`
    + (extra.length ? ` · ${extra.join(' · ')}` : ' · anneau vert reconnu par sa couleur standard')
    + '. À refaire si tu changes d’écran ou de résolution.';
}
function renderCook(st){
  const c = st.cook; if(!c) return;
  const hk = st.hotkeys || {};
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
  txt('cookQtyHelp', endless
    ? 'La boucle continue jusqu’à ce que tu l’arrêtes, ou jusqu’à ce qu’un plat ne puisse plus être lancé (ingrédients épuisés).'
    : '');
  $('cookQtyHelp').hidden = !endless;
  segMark($('cookCookers'), b => Number(b.dataset.v) === nCook);
  $('cookCookers').querySelectorAll('button').forEach(b => { b.disabled = cooking || calib; });
  $('cookQty').querySelectorAll('button').forEach(b => { b.disabled = cooking || calib; });
  inp.disabled = cooking || calib;
  // a une seule cuisiniere il n'y a rien a expliquer : la contrainte ne devient utile qu'au-dela.
  txt('cookCookersHelp', nCook > 1
    ? `Les ${nCook} bulles doivent toutes se trouver dans la zone configurée : place-toi de façon à les voir toutes, et élargis la zone si besoin (Configuration).`
    : '');
  $('cookCookersHelp').hidden = nCook <= 1;

  // ---- configuration : résumé + détail
  const refs = c.refs || {};
  const items = [
    ['positions', 'Positions à cliquer (zone, tuile, bouton Cuisiner, herbe)', c.calibrated ? 'ok' : 'no'],
    ['cook', 'Icône « cuisiner »', refs.cook ? 'ok' : 'no'],
    ['ready', 'Icône « gants » (plat prêt)', refs.ready ? 'ok' : 'no'],
    ['spatula', 'Icône « spatule »', refs.spatula ? 'ok' : 'opt'],
    ['ring', 'Couleur de l’anneau vert', c.ring_color ? 'ok' : 'opt'],
  ];
  const lsig = JSON.stringify(items);
  if($('cookRefs').dataset.sig !== lsig){
    $('cookRefs').dataset.sig = lsig;
    $('cookRefs').innerHTML = items.map(([k, label, state]) => `<li class="${state}"><span class="st" aria-hidden="true">${state === 'ok' ? '✓' : state === 'no' ? '✗' : '–'}</span>${esc(label)}${state === 'opt' ? '<small>facultatif</small>' : ''}</li>`).join('');
  }
  const badge = $('cookCalibBadge');
  const bcls = 'chip chip--badge ' + (c.calibrated ? 'chip--ok' : 'chip--warn');
  if(badge.className !== bcls) badge.className = bcls;
  txt('cookCalibBadge', c.calibrated ? 'configurée' : 'à configurer');
  txt('cookConfigSum', cookConfigSummary(c));
  $('btnCookCalib').disabled = cooking || calib;
  // deux intentions, deux boutons : « Tester » lit l'écran, « Modifier » rouvre l'assistant
  txt('btnCookCalib', c.calibrated ? 'Modifier la configuration' : 'Configurer la cuisine');
  $('btnCookIcons').disabled = cooking || calib || !c.calibrated;
  $('btnCookTest').disabled = cooking || calib || !c.calibrated;
  // Le test est facultatif et son bouton est juste au-dessus : annoncer « non testée » au repos
  // n'apprend rien. On n'affiche une pastille qu'une fois qu'il y a un résultat.
  setNotice('cookTest', !c.calibrated || !c.test_result ? null
    // Succès : le détail brut du moteur (coordonnées, scores de correspondance) n'apprend rien à qui
    // cuisine ; on ne le montre qu'en mode debug. En échec, il reste la seule piste : on le garde.
    : tested ? {text: 'Détection réussie — la bulle de la cuisinière est reconnue.'
        + (st.debug ? ' ' + c.test_result : ''), kind: 'ok', icon: '🔍'}
    : {text: 'Échec de la détection — ' + c.test_result + ' Recapture les icônes de la bulle, ou refais la configuration.', kind: 'warn', icon: '🔍'});
  // rappel d'arrêt : utile pendant la boucle, encombrant au repos
  txt('cookStopHelp', `${hk.stop || 'F7'}, n'importe quelle touche ou un mouvement de souris arrêtent tout et te rendent la main.`);
  $('cookStopHelp').hidden = !cooking;

  // ---- bouton principal. Le moteur n'exige JAMAIS le test avant de cuisiner (cook.py, Cooker.start ne
  // regarde que l'état, calibrated() et SCREEN_OK) : il n'y a donc pas d'étape « Vérifier » à franchir.
  $('cookCta').hidden = cooking;
  // pendant la boucle, le panneau principal sert au suivi : les réglages et la configuration s'effacent
  $('cookSession2').hidden = cooking;
  $('cookConfig').hidden = cooking;
  const b = $('btnCook');
  let label, cls = 'btn btn--lg btn--cta';
  if(cooking){ label = 'Arrêter la cuisine'; cls = 'btn btn--lg btn--danger'; }
  else if(!c.calibrated) label = 'Configurer la cuisine';
  else label = LABELS.cook;
  if(b.className !== cls) b.className = cls;
  txt('cookLabel', label);
  txt('cookKey', cooking ? (hk.stop || 'F7') : (hk.play_pause || 'F6'));
  $('cookKey').hidden = !cooking && !c.calibrated;
  b.disabled = calib || c.screen_ok === false;
  b.title = c.screen_ok === false ? 'La lecture d’écran est indisponible sur cet ordinateur.' : '';

  const pill = $('cookPill');
  let pc = 'pill', pt = 'À configurer';
  if(cooking && c.countdown > 0){ pc = 'pill paused'; pt = `⏳ ${Math.ceil(c.countdown)} s`; }
  else if(cooking){ pc = 'pill game'; pt = '🍳 ' + cap(c.phase || 'cuisine en cours'); }
  else if(calib){ pc = 'pill paused'; pt = '🎯 Configuration'; }
  else if(c.calibrated){ pc = 'pill preview'; pt = '✓ Prêt à cuisiner'; }
  if(pill.className !== pc) pill.className = pc;
  txt('cookPill', pt);
  $('cookDisc').classList.toggle('spin', cooking);
  txt('cookHeadline', cooking ? `Plat ${c.dishes + 1} en cours` : 'Refaire la dernière recette en boucle');
  txt('cookSub', cooking ? (c.phase ? cap(c.phase) : 'Démarrage…')
    : (c.calibrated ? 'Place-toi devant la cuisinière, puis lance la boucle' : 'Configure la zone du jeu, puis lance la boucle devant la cuisinière'));
  // fin de session : objectif atteint, arrêt volontaire et erreur sont distingués
  let lastState;
  if(c.stop_reason === 'objectif') lastState = 'objectif atteint';
  else if(c.stop_reason) lastState = `arrêt : ${c.stop_reason}`;
  else lastState = c.message || (c.calibrated ? 'prêt' : 'à configurer');
  const burners = cookBurnersText(c);
  // Avant lancement, des compteurs à zéro n'apprennent rien : une seule ligne rappelle la session passée.
  if(cooking){
    html('cookStats', `<span class="stat">🍽️ <b>${c.dishes}</b>${maxDishes ? ` / ${maxDishes}` : ''} plat${c.dishes > 1 ? 's' : ''}${endless ? ' (en continu)' : ''}</span>`
      + `<span class="stat">🔥 <b>${c.fires}</b> feu${c.fires > 1 ? 'x' : ''} ajusté${c.fires > 1 ? 's' : ''}</span>`
      + (burners ? `<span class="stat" title="Une machine à états par cuisinière">🍳 ${esc(burners)}</span>` : '')
      + `<span class="stat">⏱️ <b>${fmtDur(c.elapsed)}</b></span>`);
  } else if(c.dishes > 0){
    html('cookStats', `<span class="stat">🛈 Dernière session : <b>${c.dishes}</b> plat${c.dishes > 1 ? 's' : ''}`
      + `${c.fires ? `, ${c.fires} feu${c.fires > 1 ? 'x' : ''} ajusté${c.fires > 1 ? 's' : ''}` : ''} · ${esc(lastState)}</span>`);
  } else html('cookStats', '');

  let spec = null;
  if(cooking && c.countdown > 0){
    spec = {count: Math.ceil(c.countdown), unit: 's', role: 'Cuisine', text: 'Passe sur Heartopia, devant la cuisinière, et ne touche plus à rien.',
            meta: `${hk.stop || 'F7'} annule`, actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'cook_stop'}]};
  } else if(cooking){
    spec = {live: true, count: c.dishes, unit: c.dishes > 1 ? 'plats' : 'plat', role: 'Cuisine dans Heartopia',
            text: c.phase ? cap(c.phase) : 'Cuisine en cours…',
            meta: `${fmtDur(c.elapsed)}${maxDishes ? ` · objectif ${maxDishes} plats` : ' · en continu'} · ${hk.stop || 'F7'} arrête · ne touche ni à la souris ni au clavier`,
            progress: maxDishes ? {pct: Math.min(100, c.dishes / maxDishes * 100), left: `${c.dishes} / ${maxDishes}`, right: 'plats'} : null,
            actions: [{label: LABELS.stop, kbd: hk.stop || 'F7', api: 'cook_stop'}]};
  }
  renderSession($('cookSession'), spec);

  let notice = null;
  if(!cooking){
    if(c.screen_ok === false) notice = {text: 'Lecture d’écran indisponible sur cet ordinateur : la cuisine automatique ne peut pas fonctionner ici.', kind: 'danger'};
    else if(c.message && /arrêtée|impossible|introuvable|erreur/i.test(c.message)) notice = {text: c.message, kind: 'warn'};
    else if(!c.calibrated) notice = {text: 'Pas encore configurée : place-toi devant la cuisinière dans le jeu, puis lance « Configurer la cuisine ».', kind: 'warn'};
    else if(nCook > 1) notice = {text: `Place-toi de façon à voir les ${nCook} bulles dans la zone configurée, puis appuie sur ${hk.play_pause || 'F6'} : DodoTopia sert les cuisinières à tour de rôle et clique l'anneau vert dès qu'il apparaît.`, kind: 'ok', icon: '✓'};
    else notice = {text: `Devant la cuisinière avec les ingrédients de la dernière recette, appuie sur ${hk.play_pause || 'F6'} : le dernier plat est refait en boucle.`, kind: 'ok', icon: '✓'};
  }
  setNotice('cookNotice', notice);

  if(calib){
    renderCalibOverlay({
      kind: 'cook',
      title: 'Configurer la cuisine',
      prep: `<p>Dans Heartopia, avant de commencer :</p>
        <ol class="steps">
          <li><span class="n">1</span>Place ton personnage <b>devant la cuisinière</b>, bulle visible</li>
          <li><span class="n">2</span>Aie les ingrédients de la recette à refaire</li>
          <li><span class="n">3</span>Garde la fenêtre du jeu à la même taille pendant toute la configuration</li>
        </ol>
        <p class="hint left">Les étapes « menu » se font le menu Recettes ouvert, l'étape « spatule » pendant une cuisson, l'étape « gants » quand le plat est prêt.</p>`,
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
  dialog({title: LABELS.cook, icon: '🍳', ok: 'Cuisiner',
          html: `<p>Quantité : <b>${max ? max + ' plat' + (max > 1 ? 's' : '') : 'en continu, jusqu’à l’arrêt'}</b> · cuisinières : <b>${Number(s.cookers || 1)}</b>.</p>
            <p>Dans Heartopia, place ton personnage <b>devant la cuisinière</b>, bulle « cuisiner » visible, avec les ingrédients de la <b>dernière recette cuisinée</b>.</p>
            <small>La boucle démarre 3 s après : ne touche plus à la souris ni au clavier. Toute touche l'arrête.</small>`})
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
