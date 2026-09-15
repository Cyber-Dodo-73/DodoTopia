// DodoTopia : noyau de l'interface (helpers, appels API, registre de vues, dialogues, toasts, navigation,
// modales, aide, indicateur de tache en cours, boucle d'etat).
const $ = id => document.getElementById(id);
let S = null;
const NOTE_NAMES = ['DO','DO#','RÉ','RÉ#','MI','FA','FA#','SOL','SOL#','LA','LA#','SI'];
// vocabulaire unique de l'interface (le meme mot partout : boutons, bandeaux, raccourcis)
const LABELS = {
  listen: 'Préécouter', play: 'Jouer dans Heartopia', stop: 'Arrêter', start: 'Lancer la session', cancel: 'Annuler',
  pause: 'Pause', resume: 'Reprendre', draw: 'Dessiner dans Heartopia', cook: 'Cuisiner en boucle',
};
const HOTKEY_LABELS = {play_pause: 'Lancer / mettre en pause (selon l’activité ouverte)', stop: 'Tout arrêter', next_song: 'Musique suivante', prev_song: 'Musique précédente',
  speed_down: 'Ralentir', speed_up: 'Accélérer', next_instrument: 'Instrument suivant', draw_point: 'Enregistrer une position (configuration)'};

function fmt(s){ s = Math.max(0, Math.floor(s||0)); return Math.floor(s/60)+':'+String(s%60).padStart(2,'0'); }
function cap(s){ return s.charAt(0).toUpperCase()+s.slice(1); }
function esc(t){ return String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
// n'ecrit dans le DOM que si la valeur change (evite de reecrire a chaque tick)
function txt(id, s){ const el = $(id); if(el && el.textContent !== s) el.textContent = s; }
function html(id, s){ const el = $(id); if(el && el.dataset.html !== s){ el.dataset.html = s; el.innerHTML = s; } }
// signature memorisee sur un element : true si elle a change (et la met a jour)
function changed(el, sig){ if(el.dataset.sig === sig) return false; el.dataset.sig = sig; return true; }

function api(name, ...args){
  if(!window.pywebview){ return Promise.resolve(null); }
  // la reponse est soit un etat complet (get_state...), soit un objet {ok, ..., state} (set_setting, reset_settings)
  return window.pywebview.api[name](...args).then(r => {
    if(r && r.state && typeof r.state === 'object' && r.state.songs) render(r.state);
    else if(r && r.songs) render(r);
    return r;
  });
}

// ------------------------------------------------ registre de vues : chaque module enregistre ses vues,
// render(st) ne redessine une vue que si sa signature change (sig null = a chaque etat)
const VIEWS = [];
function view(name, {sig = null, draw}){ VIEWS.push({name, sig, draw, last: undefined}); }
function render(st){
  S = st;
  if($('btnSettings').disabled) $('btnSettings').disabled = false;   // reglages accessibles des le premier etat
  for(const v of VIEWS){
    let key = null;
    if(v.sig){ key = v.sig(st); if(key === v.last) continue; }
    try{ v.draw(st); v.last = key; }
    catch(e){ console.error('vue ' + v.name + ' :', e); }
  }
}

// ------------------------------------------------ groupes segmentes (.seg, role=radiogroup) et onglets : etat + fleches clavier
function segMark(box, isOn){
  const items = [...box.querySelectorAll(':scope > button')];
  let any = false;
  items.forEach(el => {
    const on = !!isOn(el);
    el.classList.toggle('active', on);
    el.setAttribute(el.getAttribute('role') === 'tab' ? 'aria-selected' : 'aria-checked', on ? 'true' : 'false');
    el.tabIndex = on ? 0 : -1;
    any = any || on;
  });
  if(!any && items.length) items[0].tabIndex = 0;
}
document.addEventListener('keydown', e => {
  const b = e.target.closest && e.target.closest('.seg > button, .tabs > .tab');
  if(!b || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(e.key)) return;
  const items = [...b.parentElement.querySelectorAll(':scope > button:not([disabled]):not([hidden])')];
  let i = items.indexOf(b);
  if(e.key === 'Home') i = 0;
  else if(e.key === 'End') i = items.length - 1;
  else i = (i + (e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length;
  e.preventDefault(); items[i].focus(); items[i].click();
});

// ------------------------------------------------ composants communs
// bandeau de session (.card--session) : compte a rebours / lecture / dessin / cuisine. spec = null : masque.
// spec : {count (nombre ou texte), unit, role, text, meta, live, progress {pct, left, right}, actions [{label, kbd, api, args, cls}]}
function renderSession(el, spec){
  if(!el) return;
  if(!spec){ if(!el.hidden){ el.hidden = true; el.dataset.sig = ''; el.innerHTML = ''; } return; }
  const sig = JSON.stringify([spec.count, spec.unit, spec.role, spec.text, spec.meta, spec.live, spec.progress, (spec.actions || []).map(a => a.label + a.kbd + a.api)]);
  if(el.dataset.sig === sig) return;
  const rebuild = !el.dataset.sig || el.dataset.acts !== JSON.stringify((spec.actions || []).map(a => a.label + a.api));
  el.dataset.sig = sig;
  el.hidden = false;
  el.className = 'card--session' + (spec.live ? ' is-live' : '');
  if(rebuild){
    el.dataset.acts = JSON.stringify((spec.actions || []).map(a => a.label + a.api));
    el.innerHTML = `<div class="countdown" hidden></div>
      <div class="session__body"><div class="session__role"></div><div class="session__text"></div><div class="session__meta"></div>
        <div class="progress" hidden><span class="pl"></span><div class="bar"><div class="fill"></div></div><span class="pr"></span></div></div>
      <div class="session__actions">${(spec.actions || []).map((a, i) => `<button type="button" class="btn btn--sm ${a.cls || 'btn--danger'}" data-i="${i}"></button>`).join('')}</div>`;
    el.querySelectorAll('.session__actions button').forEach(b => b.onclick = () => { const a = el._spec.actions[Number(b.dataset.i)]; if(a && a.api) api(a.api, ...(a.args || [])); if(a && a.fn) a.fn(); });
  }
  el._spec = spec;
  el.querySelectorAll('.session__actions button').forEach(b => { const a = spec.actions[Number(b.dataset.i)]; b.innerHTML = esc(a.label) + (a.kbd ? ` <kbd>${esc(a.kbd)}</kbd>` : ''); });
  const cd = el.querySelector('.countdown');
  cd.hidden = spec.count == null;
  if(spec.count != null) cd.innerHTML = esc(String(spec.count)) + (spec.unit ? `<small>${esc(spec.unit)}</small>` : '');
  const role = el.querySelector('.session__role'); role.textContent = spec.role || ''; role.hidden = !spec.role;
  el.querySelector('.session__text').textContent = spec.text || '';
  const meta = el.querySelector('.session__meta'); meta.textContent = spec.meta || ''; meta.hidden = !spec.meta;
  const pr = el.querySelector('.progress');
  pr.hidden = !spec.progress;
  if(spec.progress){
    pr.querySelector('.fill').style.width = Math.max(0, Math.min(100, spec.progress.pct || 0)).toFixed(1) + '%';
    pr.querySelector('.pl').textContent = spec.progress.left || ''; pr.querySelector('.pr').textContent = spec.progress.right || '';
  }
}
// avance / retard (ms) : curseur + valeur + bouton 0 ; ecrit le reglage data-path par set_setting (partage Multi audio / Salon)
function offsetCtl(el, value){
  if(!el) return;
  if(!el.dataset.built){
    const min = el.dataset.min || -500, max = el.dataset.max || 500, step = el.dataset.step || 5;
    el.innerHTML = `<input type="range" min="${min}" max="${max}" step="${step}" value="0" aria-label="Avance ou retard en millisecondes"><span class="stepper__v">0 ms</span><button type="button" class="stepper__btn" title="Remettre à 0" aria-label="Remettre à 0">0</button>`;
    const rg = el.querySelector('input'), v = el.querySelector('.stepper__v'), z = el.querySelector('button');
    const show = n => { n = Number(n); v.textContent = (n > 0 ? '+' : '') + n + ' ms'; v.title = n < 0 ? 'joue plus tôt' : n > 0 ? 'joue plus tard' : 'sans décalage'; };
    // data-api : appel dedie (salon -> room_set_offset, qui ecrit aussi le reglage) ; sinon set_setting
    const send = n => { if(el.dataset.api) api(el.dataset.api, n); else api('set_setting', el.dataset.path, n); };
    rg.oninput = () => show(rg.value);
    rg.onchange = () => send(Number(rg.value));
    z.onclick = () => { rg.value = 0; show(0); send(0); };
    el._show = show; el.dataset.built = '1';
  }
  const rg = el.querySelector('input');
  if(document.activeElement !== rg && String(rg.value) !== String(value || 0)){ rg.value = value || 0; el._show(value || 0); }
}
// copie dans le presse-papier : navigator.clipboard, repli textarea + execCommand (file:// sans permission)
function copyFallback(s){
  const ta = document.createElement('textarea');
  ta.value = s; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.top = '-1000px'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, ta.value.length);
  let ok = false;
  try{ ok = document.execCommand('copy'); }catch(e){ ok = false; }
  ta.remove();
  return ok;
}
function copyText(s, msg){
  s = String(s == null ? '' : s);
  const done = ok => { if(ok) toast(msg || 'Copié', 'ok'); else toast('Copie impossible : sélectionne le texte à la main', 'warn'); };
  try{
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(s).then(() => done(true), () => done(copyFallback(s)));
      return;
    }
  }catch(e){}
  done(copyFallback(s));
}
// stepper horizontal (.steps--h) : done = liste des cles faites, now = cle en cours
function stepsMark(ol, done, now, marks){
  [...ol.querySelectorAll('li')].forEach((li, i) => {
    const k = li.dataset.step, isDone = done.includes(k), isNow = k === now;
    const cls = 'steps__i' + (isDone ? ' done' : '') + (isNow ? ' now' : '');
    if(li.className !== cls) li.className = cls;
    const n = li.querySelector('.n'); const t = isDone ? '✓' : String(i + 1); if(n.textContent !== t) n.textContent = t;
    let ok = li.querySelector('.ok'); const m = marks && marks[k];
    if(m){ if(!ok){ ok = document.createElement('span'); ok.className = 'ok'; li.appendChild(ok); } if(ok.textContent !== m) ok.textContent = m; }
    else if(ok) ok.remove();
  });
}
// menu contextuel sous un bouton : items [{label, help, fn, disabled}]
let MENU = null;
function closeMenu(restoreFocus = false){ if(MENU){ const anchor = MENU._anchor; MENU.remove(); MENU = null; if(anchor){ anchor.setAttribute('aria-expanded', 'false'); if(restoreFocus && anchor.isConnected) anchor.focus(); } } }
function menu(anchor, items){
  closeMenu();
  const m = document.createElement('div'); m.className = 'menu'; m.setAttribute('role', 'menu');
  m._anchor = anchor;
  anchor.setAttribute('aria-haspopup', 'menu');
  anchor.setAttribute('aria-expanded', 'true');
  m.innerHTML = items.map((it, i) => `<button type="button" role="menuitem" data-i="${i}" ${it.disabled ? 'disabled' : ''}>${esc(it.label)}${it.help ? `<span class="menu__help">${esc(it.help)}</span>` : ''}</button>`).join('');
  m.querySelectorAll('button').forEach(b => b.onclick = () => { const it = items[Number(b.dataset.i)]; closeMenu(true); if(it.fn) it.fn(); });
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight;
  let left = Math.max(8, Math.min(r.left, window.innerWidth - mw - 8)), top = r.bottom + 6;
  if(top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
  m.style.left = left + 'px'; m.style.top = top + 'px';
  MENU = m;
  setTimeout(() => { const f = m.querySelector('button:not([disabled])'); if(f) f.focus(); }, 20);
}
document.addEventListener('mousedown', e => { if(MENU && !MENU.contains(e.target)) closeMenu(); });
document.addEventListener('keydown', e => {
  if(!MENU) return;
  if(e.key === 'Escape'){ e.preventDefault(); closeMenu(true); return; }
  if(e.key === 'Tab'){ closeMenu(true); return; }
  if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key)) return;
  const items = [...MENU.querySelectorAll('button:not([disabled])')];
  if(!items.length) return;
  e.preventDefault();
  const current = items.indexOf(document.activeElement);
  const i = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1
    : (current + (e.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length;
  items[i].focus();
});
window.addEventListener('resize', () => closeMenu());
// ------------------------------------------------ aide : raccourcis, vocabulaire, dépannage
const GLOSSARY = [
  ['Fichier MIDI (.mid)', 'Une partition : la liste des notes et de leur durée, sans son enregistré. DodoTopia la rejoue sur les touches de l’instrument du jeu.'],
  ['Préécouter', 'Écouter le morceau dans DodoTopia, sur les haut-parleurs de l’ordinateur. Rien n’est envoyé à Heartopia.'],
  ['Transposition', 'Décaler toutes les notes vers le grave ou l’aigu, en demi-tons, pour qu’elles rentrent dans l’étendue de l’instrument.'],
  ['Synchronisation par le son', 'Jouer à plusieurs sans réseau : le premier joue une note repère dans le jeu, DodoTopia l’entend sur la sortie audio et chacun démarre en même temps.'],
  ['Salon en ligne', 'Jouer à plusieurs par le serveur DodoTopia : un code à 6 caractères, un chef, un morceau commun et un départ donné par le serveur.'],
  ['Avance / retard', 'Un décalage volontaire, en millisecondes, appliqué à ton départ : négatif pour jouer plus tôt, positif pour jouer plus tard.'],
  ['Configurer la zone du jeu (calibrage)', 'Montrer une fois à DodoTopia où se trouvent, à l’écran, la toile de dessin, la palette et les outils du jeu. Sans cela il ne sait pas où cliquer.'],
  ['Tramage', 'Alterner deux couleurs voisines case par case pour imiter une teinte absente de la palette.'],
  ['Contours + pot de peinture', 'Tracer le bord d’une zone au crayon puis la remplir d’un seul clic au pot, au lieu de peindre chaque case.'],
];
// Six rubriques orientées tâches. Le glossaire n'est plus la porte d'entrée : il est en annexe de
// « Commencer ». Les raccourcis sont produits depuis la configuration réelle, jamais écrits en dur.
const HELP_TOPICS = [
  {id: 'start', label: 'Commencer'},
  {id: 'music', label: 'Musique'},
  {id: 'draw', label: 'Dessin'},
  {id: 'cook', label: 'Cuisine'},
  {id: 'keys', label: 'Raccourcis'},
  {id: 'fix', label: 'Dépannage'},
];
let HELP_TOPIC = 'start';
function helpKey(st, name, fallback){ return ((st && st.hotkeys) || {})[name] || fallback; }
function helpTask(titre, etapes, note){
  return `<section class="helptask"><h4>${esc(titre)}</h4><ol>${etapes.map(e => `<li>${e}</li>`).join('')}</ol>`
    + (note ? `<p class="hint left">${note}</p>` : '') + `</section>`;
}
function helpBody(st, topic){
  const f6 = esc(helpKey(st, 'play_pause', 'F6')), f7 = esc(helpKey(st, 'stop', 'F7'));
  const f3 = esc(helpKey(st, 'draw_point', 'F3')), f12 = esc(helpKey(st, 'next_instrument', 'F12'));
  if(topic === 'music'){
    return helpTask('Importer un morceau', [
        'Musique › Ma bibliothèque › <b>Importer</b>, ou glisse un fichier <code>.mid</code> dans la fenêtre.',
        'Les fichiers sont copiés dans ton dossier de musiques ; l’original n’est pas touché.'],
        'Tu peux aussi prendre un morceau partagé : Musique › <b>Découvrir</b> › <b>Ajouter à ma bibliothèque</b>.')
      + helpTask('Choisir mon instrument', [
        'Dans Heartopia, ouvre l’instrument que tu veux jouer.',
        `Dans DodoTopia, bloc « Jouer dans Heartopia » › <b>Changer</b> (ou <kbd class="kbd">${f12}</kbd>), et prends le même type.`,
        'Choisir ici n’équipe rien dans le jeu : c’est DodoTopia qui s’adapte à ton instrument.'],
        'Si les notes sonnent faux, c’est presque toujours que l’instrument choisi n’est pas celui ouvert dans le jeu.')
      + helpTask('Jouer dans le jeu', [
        'Sélectionne un morceau, garde Heartopia au premier plan, instrument ouvert.',
        `Bouton <b>Jouer dans Heartopia</b> ou <kbd class="kbd">${f6}</kbd>.`,
        `Pour reprendre la main : <kbd class="kbd">${f7}</kbd>, n’importe quelle touche ou un clic gauche.`],
        '« Préécouter » joue le morceau sur les haut-parleurs de l’ordinateur : rien n’est envoyé au jeu.')
      + helpTask('Jouer à plusieurs', [
        'Musique › <b>Jouer ensemble</b>, puis choisis une méthode.',
        '<b>Par le son</b> : sans réseau, le premier joue une note repère que les autres détectent.',
        '<b>Salon en ligne</b> : un code à six caractères, un chef qui lance la session.'],
        'Le calage dépend de ta machine et de ta connexion : les départs sont ajustés au mieux, pas parfaits.');
  }
  if(topic === 'draw'){
    return helpTask('Préparer une image', [
        'Dessin › <b>Importer une image</b> (.png, .jpg, .gif, .bmp, .webp).',
        'L’aperçu montre le rendu case par case sur les couleurs de la palette du jeu.',
        'Règle le format, le cadrage et les couleurs dans le panneau de droite.'],
        'Les cases transparentes apparaissent en damier. Si « Remplir le fond au pot » est coché, elles prendront la couleur de fond dans le jeu.')
      + helpTask('Configurer la toile', [
        'Dans Heartopia, ouvre une toile au format retenu, finesse des détails au maximum, grille activée.',
        'Bouton <b>Configurer la zone du jeu</b> : l’assistant demande une position à la fois.',
        `Place la souris sur la cible <b>dans le jeu</b> et appuie sur <kbd class="kbd">${f3}</kbd>.`],
        'La configuration est conservée. Elle est à refaire si tu changes de résolution ou de taille de fenêtre.')
      + helpTask('Lancer le dessin', [
        'Ouvre une toile vide au bon format, outil crayon sélectionné, sans zoom.',
        `Bouton <b>Dessiner dans Heartopia</b> ou <kbd class="kbd">${f6}</kbd>, puis ne touche plus à la souris.`],
        'Un dessin interrompu ne peut pas être repris là où il s’est arrêté.');
  }
  if(topic === 'cook'){
    return helpTask('Configurer la cuisine', [
        'Dans le jeu, place-toi devant la cuisinière, bulle visible.',
        'Cuisine › <b>Configurer la cuisine</b>, puis suis les étapes une par une.',
        `Chaque position se capture avec <kbd class="kbd">${f3}</kbd>.`],
        '<b>Tester la détection</b> est facultatif : il lit l’écran et dit quelle bulle est reconnue. Tu peux lancer la boucle sans l’avoir fait.')
      + helpTask('Lancer la boucle', [
        'Cuisine une fois toi-même la recette voulue : DodoTopia refait la dernière recette du jeu.',
        'Choisis <b>Quantité définie</b> ou <b>En continu</b>, et le nombre de cuisinières.',
        `Place-toi devant la cuisinière, puis <kbd class="kbd">${f6}</kbd>.`],
        `Pendant la boucle, <kbd class="kbd">${f7}</kbd>, n’importe quelle touche ou un mouvement de souris arrêtent tout.`);
  }
  if(topic === 'keys'){
    const rows = Object.keys(HOTKEY_LABELS).map(k =>
      `<div class="hkrow"><kbd class="kbd">${esc(helpKey(st, k, '–'))}</kbd><span>${esc(HOTKEY_LABELS[k])}</span></div>`).join('');
    return `<section class="helptask"><h4>Raccourcis globaux</h4>
        <p class="hint left">Actifs même quand Heartopia est au premier plan. Modifiables dans Réglages › Raccourcis.</p>
        <div class="hklist">${rows}</div></section>`;
  }
  if(topic === 'fix'){
    return `<dl class="gloss">
        <dt>Le jeu ne reçoit pas les touches</dt><dd>Heartopia doit être la fenêtre active. Si rien ne passe, relance DodoTopia en administrateur.</dd>
        <dt>Les notes sont fausses</dt><dd>Vérifie que l’instrument choisi est celui ouvert dans le jeu. Sinon, essaie Réglages › Musique et audio › Avancé › Envoi des touches.</dd>
        <dt>Le dessin est décalé ou tordu</dt><dd>Refais « Configurer la zone du jeu » pour ce format : le calibrage dépend de la résolution et de la position de la fenêtre.</dd>
        <dt>La bulle de la cuisinière n’est pas reconnue</dt><dd>Lance « Tester la détection » devant la cuisinière, puis recapture les icônes de la bulle.</dd>
        <dt>Tout arrêter tout de suite</dt><dd><kbd class="kbd">${f7}</kbd>, n’importe quelle touche ou un clic gauche arrêtent l’automatisation en cours.</dd>
      </dl>
      <div class="btnrow"><button type="button" class="btn btn--secondary btn--sm" data-act="logs">Ouvrir les journaux</button></div>`;
  }
  // Commencer
  return `<p>DodoTopia prépare ton travail ici, puis le réalise dans Heartopia à ta place : il appuie sur les
      touches et clique pour toi. Le jeu doit être ouvert au moment du lancement.</p>
    ${helpTask('Les trois activités', [
      '<b>Musique</b> : jouer un fichier MIDI sur un instrument du jeu.',
      '<b>Dessin</b> : reproduire une image sur la toile, case par case.',
      '<b>Cuisine</b> : refaire la dernière recette en boucle.'],
      'La musique fonctionne dès l’installation. Le dessin et la cuisine demandent une configuration, une seule fois.')}
    <section class="helptask"><h4>Les mots de DodoTopia</h4><dl class="gloss">${
      GLOSSARY.map(([t, d]) => `<dt>${esc(t)}</dt><dd>${esc(d)}</dd>`).join('')}</dl></section>`;
}
function helpPanel(st, topic){
  HELP_TOPIC = topic && HELP_TOPICS.some(t => t.id === topic) ? topic : 'start';
  const render = s2 => `<nav class="helpnav" aria-label="Rubriques d’aide">${
      HELP_TOPICS.map(t => `<button type="button" class="${t.id === HELP_TOPIC ? 'active' : ''}" data-topic="${t.id}"${t.id === HELP_TOPIC ? ' aria-current="true"' : ''}>${esc(t.label)}</button>`).join('')
    }</nav><div class="helpbody" id="helpBody">${helpBody(s2, HELP_TOPIC)}</div>`;
  const wire = box => {
    box.querySelectorAll('[data-topic]').forEach(b => b.onclick = () => {
      HELP_TOPIC = b.dataset.topic;
      box.querySelectorAll('[data-topic]').forEach(x => {
        const on = x.dataset.topic === HELP_TOPIC;
        x.classList.toggle('active', on);
        if(on) x.setAttribute('aria-current', 'true'); else x.removeAttribute('aria-current');
      });
      const body = box.querySelector('#helpBody');
      if(body){ body.innerHTML = helpBody(S, HELP_TOPIC); wireLogs(box); }
      $('panelBody').scrollTop = 0;          // chaque rubrique s'ouvre en haut
    });
    wireLogs(box);
  };
  const wireLogs = box => {
    const b = box.querySelector('[data-act="logs"]');
    if(b) b.onclick = () => { closePanel(); openSettings(null, 'about'); };
  };
  openPanel({title: 'Aide', wide: true, opener: $('btnHelp'), html: render(st), wire});
}
function hotkeysDialog(st){ helpPanel(st, 'keys'); }
// notice (.notice) : {text, kind} ou null pour masquer ; l'id du texte = id + 'Text'
function setNotice(id, spec){
  const el = $(id); if(!el) return;
  if(!spec || !spec.text){ if(!el.hidden) el.hidden = true; return; }
  const cls = 'notice notice--' + (spec.kind || 'info');
  if(el.className !== cls) el.className = cls;
  const ic = el.querySelector('.notice__ic'); const icon = spec.icon || ({info: '💡', ok: '✓', warn: '⚠️', danger: '⚠️'}[spec.kind || 'info']);
  if(ic && ic.textContent !== icon) ic.textContent = icon;
  txt(id + 'Text', spec.text);
  if(el.hidden) el.hidden = false;
}

// ------------------------------------------------ boite de dialogue (remplace confirm/alert)
let dlgResolve = null;
function dialog({title, html, ok = 'OK', cancel = 'Annuler', danger = false, icon = '♪'}){
  $('dlgTitle').textContent = title; $('dlgBody').innerHTML = html; $('dlgIcon').textContent = icon;
  $('dlgOk').textContent = ok; $('dlgOk').className = 'dlg-btn ok' + (danger ? ' danger' : '');
  $('dlgCancel').textContent = cancel; $('dlgCancel').hidden = cancel === null;
  openModal($('dlgOverlay'));
  setTimeout(() => { if($('dlgOverlay').classList.contains('open')) (danger && cancel !== null ? $('dlgCancel') : $('dlgOk')).focus(); }, 30);
  return new Promise(res => { dlgResolve = res; });
}
function dlgClose(v){ closeModal($('dlgOverlay')); if(dlgResolve){ dlgResolve(v); dlgResolve = null; } }
$('dlgOk').onclick = () => dlgClose(true);
$('dlgCancel').onclick = () => dlgClose(false);
$('dlgOverlay').onclick = e => { if(e.target === $('dlgOverlay')) dlgClose(false); };
document.addEventListener('keydown', e => {
  if(!$('dlgOverlay').classList.contains('open')) return;
  if(e.key === 'Escape'){ e.preventDefault(); dlgClose(false); }
  // Entrée active le bouton réellement sélectionné via le comportement natif du navigateur.
});

// ------------------------------------------------ toasts : pile de 3, auto-fermeture 3,5 s, variante persistante
// (sticky : reste jusqu'a dismiss_toast(id) cote Python ou clic sur l'action, avec progression facultative)
const TOAST_MS = 3500, TOAST_MAX = 3;
const TOAST = {timers: new Map(), seen: new Set(), seq: 0};
const TOAST_ICON = {ok: '✓', warn: '!', danger: '✕', info: 'i'};
function toastEl(id){ return [...document.querySelectorAll('.toast')].find(el => el.dataset.id === String(id)); }
function showToast(t){
  const stack = $('toastStack');
  const id = String(t.id);
  let el = toastEl(id);
  const sig = [t.msg, t.kind, t.sticky ? 1 : 0, t.progress, t.action && t.action.label].join('|');
  if(el && el.dataset.sig === sig){ return; }
  const fresh = !el;
  if(fresh){
    el = document.createElement('div');
    el.dataset.id = id; el.dataset.src = t.src || 'py';
    el.setAttribute('role', t.kind === 'warn' || t.kind === 'danger' ? 'alert' : 'status');
    el.innerHTML = '<span class="toast__ic"></span><span class="toast__msg"></span>'
      + '<button class="btn btn--sm btn--cta toast__action" type="button" hidden></button>'
      + '<button class="toast__close" type="button" aria-label="Fermer">×</button>'
      + '<div class="progress" hidden><div class="fill"></div></div>';
    el.querySelector('.toast__close').onclick = () => dismissToast(id, true);
    el.querySelector('.toast__action').onclick = () => {
      const a = el._action;
      if(a && a.method) api(a.method, ...(a.args || []));
      dismissToast(id, true);
    };
    stack.appendChild(el);
    // pile de 3 : les plus anciens non persistants s'effacent
    const all = [...stack.querySelectorAll('.toast')];
    if(all.length > TOAST_MAX) all.filter(e => !e.classList.contains('toast--sticky')).slice(0, all.length - TOAST_MAX).forEach(e => dismissToast(e.dataset.id));
  }
  el.dataset.sig = sig;
  el.className = 'toast' + (fresh ? '' : ' show') + (t.kind ? ' toast--' + t.kind : '') + (t.sticky ? ' toast--sticky' : '');
  el.querySelector('.toast__ic').textContent = TOAST_ICON[t.kind] || TOAST_ICON.info;
  el.querySelector('.toast__msg').textContent = t.msg;
  const act = el.querySelector('.toast__action');
  el._action = t.action || null;
  act.hidden = !t.action; if(t.action) act.textContent = t.action.label || 'OK';
  const pr = el.querySelector('.progress');
  pr.hidden = t.progress == null;
  if(t.progress != null) pr.querySelector('.fill').style.width = Math.max(0, Math.min(100, Number(t.progress))) + '%';
  if(fresh) requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(TOAST.timers.get(id));
  if(!t.sticky) TOAST.timers.set(id, setTimeout(() => dismissToast(id), TOAST_MS));
}
function dismissToast(id, tellPython){
  id = String(id);
  const el = toastEl(id); if(!el) return;
  clearTimeout(TOAST.timers.get(id)); TOAST.timers.delete(id);
  el.classList.remove('show'); setTimeout(() => el.remove(), 260);
  if(tellPython && el.dataset.src === 'py' && el.classList.contains('toast--sticky')) api('dismiss_toast', Number(id));
}
// toast local (sans passer par Python)
function toast(msg, kind, opts){ TOAST.seq++; showToast(Object.assign({id: 'l' + TOAST.seq, src: 'local', msg, kind: kind || 'info'}, opts || {})); }
function viewToasts(st){
  const list = st.toasts || [];
  for(const t of list){
    if(t.sticky){ showToast(t); TOAST.seen.add(t.id); }             // persistant : mis a jour a chaque etat (progression)
    else if(!TOAST.seen.has(t.id)){ TOAST.seen.add(t.id); showToast(t); }
  }
  // persistant retire cote Python (action faite ailleurs) : on le ferme aussi ici
  document.querySelectorAll('.toast--sticky').forEach(el => {
    if(el.dataset.src === 'py' && !list.some(t => String(t.id) === el.dataset.id)) dismissToast(el.dataset.id);
  });
  if(TOAST.seen.size > 300) TOAST.seen = new Set(list.map(t => t.id));
}
view('toasts', {draw: viewToasts});

// ------------------------------------------------ navigation : 3 activites + vues locales de la Musique
let TAB = 'music';
let MUSIC_VIEW = 'library';     // library | discover | together
function showTab(name){
  if(name === 'online'){ showTab('music'); showMusicView('discover'); return; }   // ancien onglet « En ligne »
  if(!['music', 'image', 'cook'].includes(name)) name = 'music';
  TAB = name;
  closeMenu();
  segMark($('tabs'), t => t.dataset.tab === name);
  $('pageMusic').classList.toggle('active', name === 'music');
  $('pageImage').classList.toggle('active', name === 'image');
  $('pageCook').classList.toggle('active', name === 'cook');
  $('openFolder').style.display = name === 'music' ? '' : 'none';
  $('openLog').style.display = name === 'image' ? '' : 'none';
  $('openCookLog').style.display = name === 'cook' ? '' : 'none';
  try{ localStorage.setItem('tab', name); }catch(e){}
  api('set_tab', name);
  if(name === 'image'){ renderPixels(); }
  if(S) render(S);
}
document.querySelectorAll('.tab').forEach(t => t.onclick = () => showTab(t.dataset.tab));

// Trois destinations musicales : chacune occupe tout l'espace de la page. Naviguer ne change JAMAIS le
// mode de jeu (cfg.multi.mode) : sortir de « Jouer ensemble » ne doit pas quitter un salon en cours.
const MUSIC_VIEWS = ['library', 'discover', 'together'];
function showMusicView(name){
  MUSIC_VIEW = MUSIC_VIEWS.includes(name) ? name : 'library';
  segMark($('musicNav'), b => b.dataset.view === MUSIC_VIEW);
  MUSIC_VIEWS.forEach(v => {
    const el = $('view' + v.charAt(0).toUpperCase() + v.slice(1));
    if(el) el.classList.toggle('active', v === MUSIC_VIEW);
  });
  try{ localStorage.setItem('musicView', MUSIC_VIEW); }catch(e){}
  if(S) render(S);
}
document.querySelectorAll('#musicNav > button').forEach(b => b.onclick = () => showMusicView(b.dataset.view));

// ------------------------------------------------ modales : focus piege, Echap, retour au declencheur
const MODALS = [];
function trapFocus(box, e){
  const items = [...box.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])')]
    .filter(el => el.offsetParent !== null || el === document.activeElement);
  if(!items.length) return;
  const first = items[0], last = items[items.length - 1];
  // le focus peut etre RESTE dans la page derriere la modale (retour a l'element declencheur, ouverture
  // sans focus explicite) : dans ce cas la tabulation partait dans les commandes du lecteur. On le ramene.
  if(!box.contains(document.activeElement)){ e.preventDefault(); (e.shiftKey ? last : first).focus(); return; }
  if(e.shiftKey && document.activeElement === first){ e.preventDefault(); last.focus(); }
  else if(!e.shiftKey && document.activeElement === last){ e.preventDefault(); first.focus(); }
}
function openModal(overlay, opener, onClose){
  const existing = MODALS.find(m => m.overlay === overlay);
  if(existing) return existing;
  const entry = {overlay, opener: opener || document.activeElement, onClose};
  MODALS.push(entry);
  overlay.classList.add('open');
  return entry;
}
function closeModal(overlay){
  const i = MODALS.findIndex(m => m.overlay === overlay);
  if(i < 0){ overlay.classList.remove('open'); return; }
  const m = MODALS.splice(i, 1)[0];
  overlay.classList.remove('open');
  if(m.onClose) m.onClose();
  if(m.opener && document.contains(m.opener) && m.opener.offsetParent !== null) m.opener.focus();
}
document.addEventListener('keydown', e => {
  if(e.key !== 'Tab' || !MODALS.length) return;
  const top = MODALS[MODALS.length - 1];
  if(top.overlay.classList.contains('open')) trapFocus(top.overlay, e);
});

// panneau generique (compte, aide, administration) : un seul gabarit de modale
let PANEL = null;
function openPanel(spec){
  PANEL = spec;
  $('panelTitle').textContent = spec.title || '';
  $('panelBody').innerHTML = spec.html || '';
  $('panelOverlay').querySelector('.modal').className = 'modal panel' + (spec.wide ? ' panel--wide' : '');
  if(spec.wire) spec.wire($('panelBody'));
  $('panelBody').scrollTop = 0;
  openModal($('panelOverlay'), spec.opener);
  setTimeout(() => { $('panelBody').scrollTop = 0; $('panelBody').focus(); }, 30);
}
function closePanel(){ PANEL = null; closeModal($('panelOverlay')); }
function panelOpen(){ return $('panelOverlay').classList.contains('open'); }
// repeint le panneau ouvert quand l'etat change (compte, administration)
function refreshPanel(){ if(PANEL && PANEL.render) { $('panelBody').innerHTML = PANEL.render(S); if(PANEL.wire) PANEL.wire($('panelBody')); } }
$('panelClose').onclick = () => closePanel();
$('panelOverlay').onclick = e => { if(e.target === $('panelOverlay')) closePanel(); };
document.addEventListener('keydown', e => { if(e.key === 'Escape' && panelOpen() && !$('dlgOverlay').classList.contains('open')){ e.preventDefault(); closePanel(); } });

// ------------------------------------------------ indicateur global : une tache tourne dans une autre activite
const RUN_TABS = {music: 'Musique', image: 'Dessin', cook: 'Cuisine'};
function runningTask(st){
  if(st.draw && (st.draw.state === 'drawing' || st.draw.state === 'autocal'))
    return {tab: 'image', label: st.draw.state === 'autocal' ? 'Calibrage auto' : 'Dessin en cours', stop: 'draw_stop'};
  if(st.cook && st.cook.state === 'cooking') return {tab: 'cook', label: 'Cuisine en cours', stop: 'cook_stop'};
  const room = st.online && st.online.room;
  if(st.state !== 'stopped' && st.target === 'game') return {tab: 'music', label: 'Lecture dans le jeu', stop: 'stop'};
  if(st.multi && st.multi.state && !['idle', 'playing'].includes(st.multi.state)) return {tab: 'music', label: 'Synchronisation…', stop: 'stop'};
  if(room && ['countdown', 'armed', 'playing'].includes(room.state)) return {tab: 'music', label: 'Salon en ligne', stop: 'stop'};
  return null;
}
// La barre d'état porte l'arrêt : une tâche lancée doit pouvoir être coupée depuis n'importe quel écran.
view('statusStop', {sig: st => { const r = runningTask(st); return r ? r.label + r.stop : ''; }, draw: st => {
  const r = runningTask(st), btn = $('statusStop');
  if(!btn) return;
  btn.hidden = !r;
  if(r){ btn.textContent = 'Arrêter'; btn.onclick = () => api(r.stop); btn.title = r.label; }
}});
view('runPill', {sig: st => { const r = runningTask(st); return (r ? r.tab + r.label : '') + '|' + TAB; }, draw: st => {
  const r = runningTask(st), pill = $('runPill');
  if(!r || r.tab === TAB){ pill.hidden = true; return; }
  pill.hidden = false;
  pill.innerHTML = `<span class="runpill__dot" aria-hidden="true"></span><span>${esc(RUN_TABS[r.tab])} · ${esc(r.label)}</span><span class="runpill__go">Voir</span>`;
  pill.title = `Aller à l'activité ${RUN_TABS[r.tab]}`;
  pill.onclick = () => showTab(r.tab);
}});

// ------------------------------------------------ glisser-deposer (chemin recupere cote Python)
document.addEventListener('dragover', e => { e.preventDefault(); document.body.classList.add('dragging'); });
document.addEventListener('dragleave', e => { if(!e.relatedTarget) document.body.classList.remove('dragging'); });
document.addEventListener('drop', e => {
  e.preventDefault(); document.body.classList.remove('dragging');
  if(window.pywebview) return;  // Python recupere les chemins
  const f = [...(e.dataTransfer.files || [])].find(f => IMAGE_EXT.test(f.name));
  if(f) readLocalImage(f);
});

// ------------------------------------------------ boucle d'etat
function tick(){ api('get_state').finally(() => setTimeout(tick, S && (S.state==='playing' || S.state==='sync' || (S.multi && S.multi.state !== 'idle') || (S.cook && S.cook.state !== 'idle')) ? 200 : 500)); }
function loadLogo(){
  window.pywebview.api.get_logo().then(d => { if(d){ $('logo').src = d; $('logo').style.display = ''; } });
}
function onReady(){ loadLogo(); api('set_tab', TAB); tick(); }
function boot(){
  // dernier contexte : activité et vue de la Musique (aucune automatisation n'est relancée)
  try{ const v0 = localStorage.getItem('musicView'); if(v0 && v0 !== 'library') showMusicView(v0); }catch(e){}
  try{ const t0 = localStorage.getItem('tab'); if(t0 === 'image' || t0 === 'cook') showTab(t0); }catch(e){}
  $('btnHelp').onclick = () => helpPanel(S);
  window.addEventListener('pywebviewready', onReady);
  if(window.pywebview) onReady();
}
