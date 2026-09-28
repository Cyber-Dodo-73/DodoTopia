// DodoTopia : noyau de l'interface (helpers, appels API, registre de vues, dialogues, toasts, navigation,
// modales, aide, indicateur de tache en cours, boucle d'etat, chargement de la langue).
// Textes : tout passe par la fonction t() de ui/i18n.js ; les catalogues sont assembles depuis ui/i18n/src/<lang>/.
const $ = id => document.getElementById(id);
let S = null;
// noms des notes : solfege (DO RÉ MI…) ou lettres (C D E…) selon _meta.notes de la langue chargee (applyI18nData)
const NOTE_NAMES_SOLFEGE = ['DO','DO#','RÉ','RÉ#','MI','FA','FA#','SOL','SOL#','LA','LA#','SI'];
const NOTE_NAMES_LETTERS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
let NOTE_NAMES = NOTE_NAMES_SOLFEGE;
// langues proposees par le backend (get_i18n().available) : [{tag, name, beta}]
let LANGS_AVAILABLE = [];
// vocabulaire unique de l'interface (le meme mot partout : boutons, bandeaux, raccourcis) ; accesseurs pour
// suivre la langue courante sans que les autres modules aient a se re-executer
const LABELS = {
  get listen(){ return t('action.listen'); }, get play(){ return t('action.play_in_game'); }, get stop(){ return t('action.stop'); },
  get start(){ return t('action.start_session'); }, get cancel(){ return t('common.cancel'); }, get pause(){ return t('action.pause'); },
  get resume(){ return t('action.resume'); }, get draw(){ return t('action.draw_in_game'); }, get cook(){ return t('action.cook_loop'); },
};
// libelles des raccourcis globaux : source unique = catalogue (settings.hotkeys.<nom>.label)
const HOTKEY_LABELS = {
  get play_pause(){ return t('settings.hotkeys.play_pause.label'); }, get stop(){ return t('settings.hotkeys.stop.label'); },
  get next_song(){ return t('settings.hotkeys.next_song.label'); }, get prev_song(){ return t('settings.hotkeys.prev_song.label'); },
  get speed_down(){ return t('settings.hotkeys.speed_down.label'); }, get speed_up(){ return t('settings.hotkeys.speed_up.label'); },
  get next_instrument(){ return t('settings.hotkeys.next_instrument.label'); }, get draw_point(){ return t('settings.hotkeys.draw_point.label'); },
};

function fmt(s){ s = Math.max(0, Math.floor(s||0)); return Math.floor(s/60)+':'+String(s%60).padStart(2,'0'); }
function cap(s){ return s.charAt(0).toUpperCase()+s.slice(1); }
function esc(t){ return String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
// n'ecrit dans le DOM que si la valeur change (evite de reecrire a chaque tick)
function txt(id, s){ const el = $(id); if(el && el.textContent !== s) el.textContent = s; }
function html(id, s){ const el = $(id); if(el && el.dataset.html !== s){ el.dataset.html = s; el.innerHTML = s; } }
// signature memorisee sur un element : true si elle a change (et la met a jour)
function changed(el, sig){ if(el.dataset.sig === sig) return false; el.dataset.sig = sig; return true; }
// icone du sprite SVG d'index.html (#i-<nom>) : jamais d'emoji comme pictogramme (rendu variable, impossible a teinter)
function icon(name, cls = ''){ return `<svg class="ic${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="#i-${name}"/></svg>`; }
// libelle sans pictogramme de tete (« ＋ Importer », « ↺ Réinitialiser », « ✓ Prêt ») ni coche finale : l'icone est
// dessinee a part. Protege les catalogues pas encore mis a jour (les sources fr/en n'en portent plus).
const LEAD_GLYPH = /^\s*(?:<span class="ok"[^>]*>[^<]*<\/span>|[\p{Extended_Pictographic}\u2190-\u21FF\u2300-\u23FF\u25A0-\u27BF\u27F0-\u27FF\u2B00-\u2BFF\uFF0B+?]\uFE0F?)\s*/u;
function plain(s){ return String(s == null ? '' : s).replace(LEAD_GLYPH, '').replace(/\s*\u2713\s*$/u, ''); }

// appels silencieux en cas d'echec : la boucle d'etat et le catalogue ne doivent pas empiler des toasts
const API_QUIET = new Set(['get_state', 'get_i18n', 'get_logo', 'dismiss_toast']);
function api(name, ...args){
  if(!window.pywebview){
    // apercu : reponses simulees facultatives (mock.js, window.MOCK_API[nom](...args))
    const m = window.MOCK_API && window.MOCK_API[name];
    return Promise.resolve(m ? m(...args) : null);
  }
  // la reponse est soit un etat complet (get_state...), soit un objet {ok, ..., state} (set_setting, reset_settings)
  return Promise.resolve().then(() => window.pywebview.api[name](...args)).then(r => {
    if(r && r.state && typeof r.state === 'object' && r.state.songs) render(r.state);
    else if(r && r.songs) render(r);
    return r;
  }).catch(e => {
    console.error('api ' + name + ' :', e);
    // la console est invisible dans l'application installee : l'erreur part aussi dans dodotopia.log.
    // Jamais pour ui_log lui-meme (pas de boucle), et un echec du relais est ignore.
    if(name !== 'ui_log'){
      try{
        const p = window.pywebview.api.ui_log('error', name + ': ' + ((e && (e.stack || e.message)) || e));
        if(p && typeof p.catch === 'function') p.catch(() => {});
      }catch(_){}
    }
    if(!API_QUIET.has(name)) toast(t('common.action_failed'), 'danger', {id: 'apifail'});
    return null;
  });
}
// bouton qui declenche un appel : anneau de chargement pendant l'appel, pas de double clic
function apiAction(btn, name, ...args){
  if(btn && btn.classList.contains('is-loading')) return Promise.resolve(null);
  if(btn){ btn.classList.add('is-loading'); btn.setAttribute('aria-busy', 'true'); }
  return api(name, ...args).finally(() => { if(btn){ btn.classList.remove('is-loading'); btn.removeAttribute('aria-busy'); } });
}
// appel a l'action principal (CTA) : libelle, raccourci, etat et RAISON lisible sous le bouton quand il est desactive.
// o : {label, kbd, disabled, reason, loading} ; une cle absente laisse la valeur actuelle.
function setAction(btn, o){
  if(!btn) return;
  o = o || {};
  if(o.label !== undefined){
    const l = btn.querySelector('span:not(.btn__why)');
    if(l){ if(l.textContent !== o.label) l.textContent = o.label; }
  }
  if(o.kbd !== undefined){
    const k = btn.querySelector('kbd');
    if(k){ if(k.textContent !== (o.kbd || '')) k.textContent = o.kbd || ''; k.hidden = !o.kbd; }
  }
  if(o.disabled !== undefined && btn.disabled !== !!o.disabled) btn.disabled = !!o.disabled;
  if(o.loading !== undefined){ btn.classList.toggle('is-loading', !!o.loading); if(o.loading) btn.setAttribute('aria-busy', 'true'); else btn.removeAttribute('aria-busy'); }
  const reason = btn.disabled && o.reason ? String(o.reason) : '';
  let why = btn._why;
  if(!why && reason){
    why = document.createElement('p');
    why.className = 'btn__why';
    why.id = (btn.id || ('b' + Math.random().toString(36).slice(2))) + 'Why';
    btn.insertAdjacentElement('afterend', why);
    btn._why = why;
  }
  if(why){
    const h = reason ? icon('info') + `<span>${esc(reason)}</span>` : '';
    if(why.dataset.html !== h){ why.dataset.html = h; why.innerHTML = h; }
    why.hidden = !reason;
    if(reason) btn.setAttribute('aria-describedby', why.id); else btn.removeAttribute('aria-describedby');
  }
  if(btn.title !== reason) btn.title = reason;
}

// ------------------------------------------------ langue : chargement du catalogue et application au DOM
// d = reponse de get_i18n : {lang, available, catalogue, fallback, meta}
function applyI18nData(d){
  if(!d || !d.catalogue) return;
  I18N.load({lang: d.lang, catalogue: d.catalogue, fallback: d.fallback, meta: d.meta});
  LANGS_AVAILABLE = Array.isArray(d.available) ? d.available : [];
  document.documentElement.lang = I18N.lang;
  NOTE_NAMES = (I18N.meta && I18N.meta.notes === 'letters') ? NOTE_NAMES_LETTERS : NOTE_NAMES_SOLFEGE;
  I18N.applyDom(document);
  document.querySelectorAll('[data-plain]').forEach(el => { const s = plain(el.textContent); if(el.textContent !== s) el.textContent = s; });
  document.title = t('shell.app_title');
}
// charge la langue courante (backend, ou source mock : window.MOCK_I18N(lang) -> Promise)
function loadI18n(lang){
  if(window.MOCK_I18N) return window.MOCK_I18N(lang).then(applyI18nData);
  return api('get_i18n').then(applyI18nData).catch(e => console.error('i18n :', e));
}
// appelee par Python apres un changement de general.lang : recharge le catalogue, retraduit le DOM statique
// et force chaque vue a se redessiner avec le dernier etat connu
function applyLanguage(lang){
  return loadI18n(lang).then(() => {
    // caches de rendu des composants (renderSession, html(), curseur avance/retard) : a reconstruire
    document.querySelectorAll('[data-sig],[data-html]').forEach(el => { delete el.dataset.sig; delete el.dataset.html; });
    document.querySelectorAll('.offsetctl[data-built]').forEach(el => { delete el.dataset.built; el.innerHTML = ''; });
    for(const v of VIEWS) v.last = undefined;
    if(S) render(S);
    if(typeof settingsOpen === 'function' && settingsOpen()){ buildNav(); renderSection(SET.section); }
    if(PANEL && PANEL.reopen) PANEL.reopen(); else refreshPanel();
    if(typeof termsOpen === 'function' && termsOpen()) termsLabels();
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
  el.querySelectorAll('.session__actions button').forEach(b => { const a = spec.actions[Number(b.dataset.i)]; b.innerHTML = (a.icon ? icon(a.icon) : '') + `<span>${esc(a.label)}</span>` + (a.kbd ? `<kbd>${esc(a.kbd)}</kbd>` : ''); });
  const cd = el.querySelector('.countdown');
  // count : nombre ou texte court ; countIcon : pictogramme a la place du nombre (telechargement, pause)
  cd.hidden = spec.count == null && !spec.countIcon;
  if(spec.countIcon) cd.innerHTML = icon(spec.countIcon, 'ic--xl');
  else if(spec.count != null) cd.innerHTML = esc(String(spec.count)) + (spec.unit ? `<small>${esc(spec.unit)}</small>` : '');
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
    el.innerHTML = `<input type="range" min="${min}" max="${max}" step="${step}" value="0" aria-label="${esc(t('shell.offset.aria'))}"><span class="stepper__v"></span><button type="button" class="stepper__btn" title="${esc(t('shell.offset.reset'))}" aria-label="${esc(t('shell.offset.reset'))}">0</button>`;
    const rg = el.querySelector('input'), v = el.querySelector('.stepper__v'), z = el.querySelector('button');
    const show = n => { n = Number(n); v.textContent = t('shell.offset.ms', {n, sign: n > 0 ? 'plus' : 'other'}); v.title = t('shell.offset.meaning', {dir: n < 0 ? 'early' : n > 0 ? 'late' : 'none'}); };
    // data-api : appel dedie (salon -> room_set_offset, qui ecrit aussi le reglage) ; sinon set_setting
    const send = n => { if(el.dataset.api) api(el.dataset.api, n); else api('set_setting', el.dataset.path, n); };
    rg.oninput = () => show(rg.value);
    rg.onchange = () => send(Number(rg.value));
    z.onclick = () => { rg.value = 0; show(0); send(0); };
    el._show = show; el.dataset.built = '1';
    show(0);
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
  const done = ok => { if(ok) toast(msg || t('common.copied'), 'ok'); else toast(t('common.copy_failed'), 'warn'); };
  try{
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(s).then(() => done(true), () => done(copyFallback(s)));
      return;
    }
  }catch(e){}
  done(copyFallback(s));
}
// menu Partager : {anchor, url, text, copyLabel}. X et Bluesky s'ouvrent par open_external (liste blanche cote
// Python) ; « Copier pour Discord » copie le texte et le lien, l'apercu vient des balises OG de la page publique.
function shareMenu(o){
  o = o || {};
  const url = String(o.url || ''), text = String(o.text || o.title || '');
  const anchor = o.anchor || document.activeElement || document.body;
  if(!url){ toast(t('share.no_link'), 'warn'); return; }
  const enc = encodeURIComponent;
  menu(anchor, [
    {label: o.copyLabel || t('share.copy_link'), icon: 'link', fn: () => copyText(url, t('share.link_copied'))},
    {label: t('share.x'), icon: 'share', fn: () => api('open_external', `https://x.com/intent/post?text=${enc(text)}&url=${enc(url)}`)},
    {label: t('share.bluesky'), icon: 'share', fn: () => api('open_external', `https://bsky.app/intent/compose?text=${enc(text ? text + ' ' + url : url)}`)},
    {label: t('share.discord'), help: t('share.discord_help'), icon: 'copy', fn: () => copyText(text ? text + '\n' + url : url, t('share.discord_copied'))},
  ]);
}
// stepper horizontal (.steps--h) : done = liste des cles faites, now = cle en cours
function stepsMark(ol, done, now, marks){
  [...ol.querySelectorAll('li')].forEach((li, i) => {
    const k = li.dataset.step, isDone = done.includes(k), isNow = k === now;
    const cls = 'steps__i' + (isDone ? ' done' : '') + (isNow ? ' now' : '');
    if(li.className !== cls) li.className = cls;
    const n = li.querySelector('.n'); const t = isDone ? 'done' : String(i + 1);
    if(n.dataset.v !== t){ n.dataset.v = t; n.innerHTML = isDone ? icon('check') : t; }
    let ok = li.querySelector('.ok'); const m = marks && marks[k];
    if(m){ if(!ok){ ok = document.createElement('span'); ok.className = 'ok'; li.appendChild(ok); } if(ok.textContent !== m) ok.textContent = m; }
    else if(ok) ok.remove();
  });
}
// menu contextuel sous un bouton : items [{label, help, fn, disabled, icon}]
let MENU = null;
function closeMenu(restoreFocus = false){ if(MENU){ const anchor = MENU._anchor; MENU.remove(); MENU = null; if(anchor){ anchor.setAttribute('aria-expanded', 'false'); if(restoreFocus && anchor.isConnected) anchor.focus(); } } }
function menu(anchor, items){
  closeMenu();
  const m = document.createElement('div'); m.className = 'menu'; m.setAttribute('role', 'menu');
  m._anchor = anchor;
  anchor.setAttribute('aria-haspopup', 'menu');
  anchor.setAttribute('aria-expanded', 'true');
  m.innerHTML = items.map((it, i) => `<button type="button" role="menuitem" data-i="${i}" ${it.disabled ? 'disabled' : ''}>${it.icon ? icon(it.icon) : ''}<span class="menu__label">${esc(it.label)}</span>${it.help ? `<span class="menu__help">${esc(it.help)}</span>` : ''}</button>`).join('');
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
// (apercu mock : window.MOCK_KEEP_MENU garde le menu ouvert quand la capture d'ecran redimensionne la fenetre)
window.addEventListener('resize', () => { if(!window.MOCK_KEEP_MENU) closeMenu(); });
// ------------------------------------------------ aide : raccourcis, vocabulaire, dépannage
// glossaire : [terme, definition] dans la langue courante
function glossary(){
  return [
    [t('help.gloss.midi.term'), t('help.gloss.midi.def')],
    [t('help.gloss.listen.term'), t('help.gloss.listen.def')],
    [t('help.gloss.transpose.term'), t('help.gloss.transpose.def')],
    [t('help.gloss.audio_sync.term'), t('help.gloss.audio_sync.def')],
    [t('help.gloss.room.term'), t('help.gloss.room.def')],
    [t('help.gloss.offset.term'), t('help.gloss.offset.def')],
    [t('help.gloss.calib.term'), t('help.gloss.calib.def')],
    [t('help.gloss.dither.term'), t('help.gloss.dither.def')],
    [t('help.gloss.outline.term'), t('help.gloss.outline.def')],
  ];
}
// Six rubriques orientées tâches. Le glossaire n'est plus la porte d'entrée : il est en annexe de
// « Commencer ». Les raccourcis sont produits depuis la configuration réelle, jamais écrits en dur.
const HELP_TOPICS = [
  {id: 'start', label: () => t('help.topic.start')},
  {id: 'music', label: () => t('help.topic.music')},
  {id: 'draw', label: () => t('help.topic.draw')},
  {id: 'cook', label: () => t('help.topic.cook')},
  {id: 'keys', label: () => t('help.topic.keys')},
  {id: 'fix', label: () => t('help.topic.fix')},
];
let HELP_TOPIC = 'start';
function helpKey(st, name, fallback){ return ((st && st.hotkeys) || {})[name] || fallback; }
function helpTask(titre, etapes, note){
  return `<section class="helptask"><h4>${esc(titre)}</h4><ol>${etapes.map(e => `<li>${e}</li>`).join('')}</ol>`
    + (note ? `<p class="hint left">${note}</p>` : '') + `</section>`;
}
// Les messages help.* contiennent du balisage sur (<b>, <kbd>, <code>) et sont inseres en innerHTML :
// jamais de donnee utilisateur dedans, les raccourcis sont echappes avant d'etre passes en parametre.
function helpBody(st, topic){
  const f6 = esc(helpKey(st, 'play_pause', 'F6')), f7 = esc(helpKey(st, 'stop', 'F7'));
  const f3 = esc(helpKey(st, 'draw_point', 'F3')), f12 = esc(helpKey(st, 'next_instrument', 'F12'));
  const k = {f6, f7, f3, f12};
  if(topic === 'music'){
    return helpTask(t('help.music.import.title'), [t('help.music.import.s1'), t('help.music.import.s2')], t('help.music.import.note'))
      + helpTask(t('help.music.instrument.title'), [t('help.music.instrument.s1'), t('help.music.instrument.s2', k), t('help.music.instrument.s3')], t('help.music.instrument.note'))
      + helpTask(t('help.music.play.title'), [t('help.music.play.s1'), t('help.music.play.s2', k), t('help.music.play.s3', k)], t('help.music.play.note'))
      + helpTask(t('help.music.together.title'), [t('help.music.together.s1'), t('help.music.together.s2'), t('help.music.together.s3')], t('help.music.together.note'));
  }
  if(topic === 'draw'){
    return helpTask(t('help.draw.prepare.title'), [t('help.draw.prepare.s1'), t('help.draw.prepare.s2'), t('help.draw.prepare.s3')], t('help.draw.prepare.note'))
      + helpTask(t('help.draw.setup.title'), [t('help.draw.setup.s1'), t('help.draw.setup.s2'), t('help.draw.setup.s3', k)], t('help.draw.setup.note'))
      + helpTask(t('help.draw.run.title'), [t('help.draw.run.s1'), t('help.draw.run.s2', k)], t('help.draw.run.note'));
  }
  if(topic === 'cook'){
    return helpTask(t('help.cook.setup.title'), [t('help.cook.setup.s1'), t('help.cook.setup.s2'), t('help.cook.setup.s3', k)], t('help.cook.setup.note'))
      + helpTask(t('help.cook.run.title'), [t('help.cook.run.s1'), t('help.cook.run.s2'), t('help.cook.run.s3', k)], t('help.cook.run.note', k));
  }
  if(topic === 'keys'){
    const rows = Object.keys(HOTKEY_LABELS).map(k =>
      `<div class="hkrow"><kbd class="kbd">${esc(helpKey(st, k, '–'))}</kbd><span>${esc(HOTKEY_LABELS[k])}</span></div>`).join('');
    return `<section class="helptask"><h4>${esc(t('help.keys.title'))}</h4>
        <p class="hint left">${esc(t('help.keys.intro'))}</p>
        <div class="hklist">${rows}</div></section>`;
  }
  if(topic === 'fix'){
    return `<dl class="gloss">
        <dt>${esc(t('help.fix.keys.q'))}</dt><dd>${esc(t('help.fix.keys.a'))}</dd>
        <dt>${esc(t('help.fix.notes.q'))}</dt><dd>${esc(t('help.fix.notes.a'))}</dd>
        <dt>${esc(t('help.fix.draw.q'))}</dt><dd>${esc(t('help.fix.draw.a'))}</dd>
        <dt>${esc(t('help.fix.cook.q'))}</dt><dd>${esc(t('help.fix.cook.a'))}</dd>
        <dt>${esc(t('help.fix.stop.q'))}</dt><dd>${t('help.fix.stop.a', k)}</dd>
      </dl>
      <div class="btnrow"><button type="button" class="btn btn--secondary btn--sm" data-act="logs">${esc(t('help.fix.open_logs'))}</button>
        <button type="button" class="btn btn--cta btn--sm" data-act="report">${esc(t('support.report_btn'))}</button></div>
      <p class="hint left">${esc(t('support.help_hint'))}</p>`;
  }
  // Commencer
  return `<p>${t('help.start.intro')}</p>
    <div class="btnrow"><button type="button" class="btn btn--secondary btn--sm" data-act="onboarding">${icon('rocket')}<span>${esc(t('onb.replay'))}</span></button></div>
    ${helpTask(t('help.start.activities.title'), [t('help.start.activities.music'), t('help.start.activities.draw'), t('help.start.activities.cook')], t('help.start.activities.note'))}
    <section class="helptask"><h4>${esc(t('help.start.glossary'))}</h4><dl class="gloss">${
      glossary().map(([term, d]) => `<dt>${esc(term)}</dt><dd>${esc(d)}</dd>`).join('')}</dl></section>`;
}
function helpPanel(st, topic){
  HELP_TOPIC = topic && HELP_TOPICS.some(t => t.id === topic) ? topic : 'start';
  const render = s2 => `<nav class="helpnav" aria-label="${esc(t('help.nav_aria'))}">${
      HELP_TOPICS.map(t => `<button type="button" class="${t.id === HELP_TOPIC ? 'active' : ''}" data-topic="${t.id}"${t.id === HELP_TOPIC ? ' aria-current="true"' : ''}>${esc(t.label())}</button>`).join('')
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
    const rp = box.querySelector('[data-act="report"]');
    if(rp) rp.onclick = () => { closePanel(); if(typeof openDiagReport === 'function') openDiagReport($('btnHelp')); };
    const o = box.querySelector('[data-act="onboarding"]');
    if(o) o.onclick = () => { closePanel(); if(typeof openOnboarding === 'function') openOnboarding(); };
  };
  // reopen : apres un changement de langue, le panneau se reconstruit sur la meme rubrique
  openPanel({title: t('help.title'), wide: true, opener: $('btnHelp'), html: render(st), wire, reopen: () => helpPanel(S, HELP_TOPIC)});
}
function hotkeysDialog(st){ helpPanel(st, 'keys'); }
// notice (.notice) : {text, kind, icon (nom d'icone du sprite)} ou null pour masquer ; l'id du texte = id + 'Text'
const NOTICE_ICON = {info: 'info', ok: 'check', warn: 'warn', danger: 'danger'};
function setNotice(id, spec){
  const el = $(id); if(!el) return;
  if(!spec || !spec.text){ if(!el.hidden) el.hidden = true; return; }
  const cls = 'notice notice--' + (spec.kind || 'info');
  if(el.className !== cls) el.className = cls;
  const ic = el.querySelector('.notice__ic'); const name = spec.icon || NOTICE_ICON[spec.kind || 'info'] || 'info';
  if(ic && ic.dataset.icon !== name){ ic.dataset.icon = name; ic.innerHTML = icon(name); }
  txt(id + 'Text', spec.text);
  if(el.hidden) el.hidden = false;
}

// ------------------------------------------------ boite de dialogue (remplace confirm/alert)
// ok / cancel absents : libelles OK / Annuler dans la langue courante ; cancel === null : pas de bouton Annuler
// icon : nom d'icone du sprite (note, trash, warn...)
let dlgResolve = null;
// wide : formulaire (partage, import) ; le bouton OK est reactive a chaque ouverture (un formulaire peut le bloquer)
function dialog({title, html, ok, cancel, danger = false, icon = 'note', wide = false}){
  $('dlgTitle').textContent = title; $('dlgBody').innerHTML = html;
  $('dlgIcon').querySelector('use').setAttribute('href', '#i-' + icon);
  $('dlgOverlay').querySelector('.dlg').classList.toggle('dlg--danger', !!danger);
  $('dlgOverlay').querySelector('.dlg').classList.toggle('dlg--wide', !!wide);
  $('dlgOk').disabled = false;
  $('dlgOk').textContent = ok == null ? t('common.ok') : ok; $('dlgOk').className = 'dlg-btn ok' + (danger ? ' danger' : '');
  $('dlgCancel').textContent = cancel == null ? t('common.cancel') : cancel; $('dlgCancel').hidden = cancel === null;
  openModal($('dlgOverlay'), null, null, () => dlgClose(false));
  setTimeout(() => { if($('dlgOverlay').classList.contains('open')) (danger && cancel !== null ? $('dlgCancel') : $('dlgOk')).focus(); }, 30);
  return new Promise(res => { dlgResolve = res; });
}
function dlgClose(v){ closeModal($('dlgOverlay')); if(dlgResolve){ dlgResolve(v); dlgResolve = null; } }
$('dlgOk').onclick = () => dlgClose(true);
$('dlgCancel').onclick = () => dlgClose(false);
$('dlgOverlay').onclick = e => { if(e.target === $('dlgOverlay')) dlgClose(false); };
// Échap : gestionnaire unique des modales (pile MODALS, plus bas). Entrée active le bouton sélectionné (natif).

// ------------------------------------------------ toasts : pile de 3, duree selon le type, variante persistante
// ok / info 3,5 s ; warn 8 s ; danger reste affiche jusqu'au clic sur Fermer.
// (sticky : reste jusqu'a dismiss_toast(id) cote Python ou clic sur l'action, avec progression facultative)
// Un toast venu de Python peut porter {key, params} a la place de msg : il est traduit ici.
const TOAST_MS = {ok: 3500, info: 3500, warn: 8000, danger: 0}, TOAST_MAX = 3;
const TOAST = {timers: new Map(), seen: new Set(), seq: 0};
const TOAST_ICON = {ok: 'check', warn: 'warn', danger: 'danger', info: 'info'};
function toastEl(id){ return [...document.querySelectorAll('.toast')].find(el => el.dataset.id === String(id)); }
function toastMsg(t0){ return t0.key ? t(t0.key, t0.params || {}) : (t0.msg || ''); }
function showToast(t0){
  const stack = $('toastStack');
  const id = String(t0.id);
  let el = toastEl(id);
  const msg = toastMsg(t0);
  const actionLabel = t0.action ? (t0.action.key ? t(t0.action.key, t0.action.params || {}) : (t0.action.label || t('common.ok'))) : '';
  const sig = [msg, t0.kind, t0.sticky ? 1 : 0, t0.progress, actionLabel].join('|');
  if(el && el.dataset.sig === sig){ return; }
  const fresh = !el;
  if(fresh){
    el = document.createElement('div');
    el.dataset.id = id; el.dataset.src = t0.src || 'py';
    el.setAttribute('role', t0.kind === 'warn' || t0.kind === 'danger' ? 'alert' : 'status');
    el.innerHTML = '<span class="toast__ic"></span><span class="toast__msg"></span>'
      + '<button class="btn btn--sm btn--cta toast__action" type="button" hidden></button>'
      + `<button class="toast__close" type="button" aria-label="${esc(t('common.close'))}">${icon('close')}</button>`
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
    if(all.length > TOAST_MAX) all.filter(e => !e.classList.contains('toast--sticky') && !e.classList.contains('toast--danger')).slice(0, all.length - TOAST_MAX).forEach(e => dismissToast(e.dataset.id));
  }
  el.dataset.sig = sig;
  el.className = 'toast' + (fresh ? '' : ' show') + (t0.kind ? ' toast--' + t0.kind : '') + (t0.sticky ? ' toast--sticky' : '');
  const tic = el.querySelector('.toast__ic'), tname = TOAST_ICON[t0.kind] || TOAST_ICON.info;
  if(tic.dataset.icon !== tname){ tic.dataset.icon = tname; tic.innerHTML = icon(tname); }
  el.querySelector('.toast__msg').textContent = msg;
  const act = el.querySelector('.toast__action');
  el._action = t0.action || null;
  act.hidden = !t0.action; if(t0.action) act.textContent = actionLabel;
  const pr = el.querySelector('.progress');
  pr.hidden = t0.progress == null;
  if(t0.progress != null) pr.querySelector('.fill').style.width = Math.max(0, Math.min(100, Number(t0.progress))) + '%';
  if(fresh) requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(TOAST.timers.get(id));
  const ms = TOAST_MS[t0.kind] !== undefined ? TOAST_MS[t0.kind] : TOAST_MS.info;
  if(!t0.sticky && ms > 0) TOAST.timers.set(id, setTimeout(() => dismissToast(id), ms));
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
  for(const t0 of list){
    if(t0.sticky){ showToast(t0); TOAST.seen.add(t0.id); }             // persistant : mis a jour a chaque etat (progression)
    else if(!TOAST.seen.has(t0.id)){ TOAST.seen.add(t0.id); showToast(t0); }
  }
  // persistant retire cote Python (action faite ailleurs) : on le ferme aussi ici
  document.querySelectorAll('.toast--sticky').forEach(el => {
    if(el.dataset.src === 'py' && !list.some(t0 => String(t0.id) === el.dataset.id)) dismissToast(el.dataset.id);
  });
  if(TOAST.seen.size > 300) TOAST.seen = new Set(list.map(t0 => t0.id));
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
// onEscape : fermeture propre sur Échap (annuler, ignorer…) ; absent = Échap sans effet sur cette modale
function openModal(overlay, opener, onClose, onEscape){
  const existing = MODALS.find(m => m.overlay === overlay);
  if(existing){ if(onEscape) existing.onEscape = onEscape; return existing; }
  const entry = {overlay, opener: opener || document.activeElement, onClose, onEscape};
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
// Échap : un seul gestionnaire pour toutes les modales, qui ne ferme que celle du dessus de la pile.
// Les cas particuliers s'arretent avant lui : menu contextuel (preventDefault), capture d'un raccourci ou d'une
// touche d'instrument et champs de recherche (stopPropagation), conditions d'utilisation (phase de capture).
document.addEventListener('keydown', e => {
  if(e.key !== 'Escape' || e.defaultPrevented || !MODALS.length) return;
  const top = MODALS[MODALS.length - 1];
  if(!top.overlay.classList.contains('open')) return;
  e.preventDefault();
  if(top.onEscape) top.onEscape();
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
  openModal($('panelOverlay'), spec.opener, null, closePanel);
  setTimeout(() => { $('panelBody').scrollTop = 0; $('panelBody').focus(); }, 30);
}
function closePanel(){ PANEL = null; closeModal($('panelOverlay')); }
function panelOpen(){ return $('panelOverlay').classList.contains('open'); }
// repeint le panneau ouvert quand l'etat change (compte, administration)
function refreshPanel(){ if(PANEL && PANEL.render) { $('panelBody').innerHTML = PANEL.render(S); if(PANEL.wire) PANEL.wire($('panelBody')); } }
$('panelClose').onclick = () => closePanel();
$('panelOverlay').onclick = e => { if(e.target === $('panelOverlay')) closePanel(); };

// ------------------------------------------------ indicateur global : une tache tourne dans une autre activite
function runTabLabel(tab){ return tab === 'image' ? t('shell.tab.image') : tab === 'cook' ? t('shell.tab.cook') : t('shell.tab.music'); }
function runningTask(st){
  if(st.draw && (st.draw.state === 'drawing' || st.draw.state === 'autocal'))
    return {tab: 'image', label: st.draw.state === 'autocal' ? t('shell.run.autocal') : t('shell.run.drawing'), stop: 'draw_stop'};
  if(st.cook && st.cook.state === 'cooking') return {tab: 'cook', label: t('shell.run.cooking'), stop: 'cook_stop'};
  const room = st.online && st.online.room;
  if(st.state !== 'stopped' && st.target === 'game') return {tab: 'music', label: t('shell.run.playing'), stop: 'stop'};
  if(st.multi && st.multi.state && !['idle', 'playing'].includes(st.multi.state)) return {tab: 'music', label: t('shell.run.syncing'), stop: 'stop'};
  if(room && ['countdown', 'armed', 'playing'].includes(room.state)) return {tab: 'music', label: t('shell.run.room'), stop: 'stop'};
  return null;
}
// La barre d'état porte l'arrêt : une tâche lancée doit pouvoir être coupée depuis n'importe quel écran.
view('statusStop', {sig: st => { const r = runningTask(st); return r ? r.label + r.stop : ''; }, draw: st => {
  const r = runningTask(st), btn = $('statusStop');
  if(!btn) return;
  btn.hidden = !r;
  if(r){ btn.innerHTML = icon('stop') + `<span>${esc(t('action.stop'))}</span>`; btn.onclick = () => api(r.stop); btn.title = r.label; }
}});
view('runPill', {sig: st => { const r = runningTask(st); return (r ? r.tab + r.label : '') + '|' + TAB; }, draw: st => {
  const r = runningTask(st), pill = $('runPill');
  if(!r || r.tab === TAB){ pill.hidden = true; return; }
  pill.hidden = false;
  pill.innerHTML = `<span class="runpill__dot" aria-hidden="true"></span><span>${esc(t('shell.run.pill', {tab: runTabLabel(r.tab), task: r.label}))}</span><span class="runpill__go">${esc(t('shell.run.go'))}${icon('chevron-right')}</span>`;
  pill.title = t('shell.run.goto', {tab: runTabLabel(r.tab)});
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
// la langue est chargee AVANT le premier etat : le premier rendu est deja dans la bonne langue
function onReady(){ loadLogo(); api('set_tab', TAB); loadI18n().finally(tick); }
function boot(){
  // dernier contexte : activité et vue de la Musique (aucune automatisation n'est relancée)
  try{ const v0 = localStorage.getItem('musicView'); if(v0 && v0 !== 'library') showMusicView(v0); }catch(e){}
  try{ const t0 = localStorage.getItem('tab'); if(t0 === 'image' || t0 === 'cook') showTab(t0); }catch(e){}
  $('btnHelp').onclick = () => helpPanel(S);
  window.addEventListener('pywebviewready', onReady);
  if(window.pywebview) onReady();
}
