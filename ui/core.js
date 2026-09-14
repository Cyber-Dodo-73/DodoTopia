// DodoTopia : noyau de l'interface (helpers, appels API, registre de vues, dialogues, toasts, onglets, boucle).
const $ = id => document.getElementById(id);
let S = null;
const NOTE_NAMES = ['DO','DO#','RÉ','RÉ#','MI','FA','FA#','SOL','SOL#','LA','LA#','SI'];
// vocabulaire unique de l'interface (le meme mot partout : boutons, bandeaux, raccourcis)
const LABELS = {
  listen: 'Écouter ici', play: 'Jouer dans Heartopia', stop: 'Arrêter', start: 'Top départ', cancel: 'Annuler',
  pause: 'Pause', resume: 'Reprendre', draw: 'Dessiner dans Heartopia', cook: 'Cuisiner en boucle',
};
const HOTKEY_LABELS = {play_pause: 'Jouer dans Heartopia / pause', stop: 'Arrêter', next_song: 'Musique suivante', prev_song: 'Musique précédente',
  speed_down: 'Ralentir', speed_up: 'Accélérer', next_instrument: 'Instrument suivant', draw_point: 'Repère (calibrage)'};

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
    el.querySelectorAll('.session__actions button').forEach(b => b.onclick = () => { const a = spec.actions[Number(b.dataset.i)]; if(a && a.api) api(a.api, ...(a.args || [])); if(a && a.fn) a.fn(); });
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
function closeMenu(){ if(MENU){ MENU.remove(); MENU = null; } }
function menu(anchor, items){
  closeMenu();
  const m = document.createElement('div'); m.className = 'menu'; m.setAttribute('role', 'menu');
  m.innerHTML = items.map((it, i) => `<button type="button" role="menuitem" data-i="${i}" ${it.disabled ? 'disabled' : ''}>${esc(it.label)}${it.help ? `<span class="menu__help">${esc(it.help)}</span>` : ''}</button>`).join('');
  m.querySelectorAll('button').forEach(b => b.onclick = () => { const it = items[Number(b.dataset.i)]; closeMenu(); if(it.fn) it.fn(); });
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight;
  let left = Math.min(r.left, window.innerWidth - mw - 8), top = r.bottom + 6;
  if(top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
  m.style.left = left + 'px'; m.style.top = top + 'px';
  MENU = m;
  setTimeout(() => { const f = m.querySelector('button:not([disabled])'); if(f) f.focus(); }, 20);
}
document.addEventListener('mousedown', e => { if(MENU && !MENU.contains(e.target)) closeMenu(); });
document.addEventListener('keydown', e => { if(MENU && e.key === 'Escape'){ closeMenu(); } });
// dialogue des raccourcis (bouton « ? Raccourcis »)
function hotkeysDialog(st){
  const hk = (st && st.hotkeys) || {};
  const rows = Object.keys(HOTKEY_LABELS).map(k => `<kbd class="kbd">${esc(hk[k] || '–')}</kbd><span>${esc(HOTKEY_LABELS[k])}</span>`).join('');
  dialog({title: 'Raccourcis clavier', icon: '⌨️', ok: 'Fermer', cancel: null,
    html: `<div class="hklist">${rows}</div><small>Actifs même quand Heartopia a le focus. Modifiables dans Réglages › Raccourcis.</small>`});
}
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
  $('dlgOverlay').classList.add('open');
  setTimeout(() => $('dlgOk').focus(), 30);
  return new Promise(res => { dlgResolve = res; });
}
function dlgClose(v){ $('dlgOverlay').classList.remove('open'); if(dlgResolve){ dlgResolve(v); dlgResolve = null; } }
$('dlgOk').onclick = () => dlgClose(true);
$('dlgCancel').onclick = () => dlgClose(false);
$('dlgOverlay').onclick = e => { if(e.target === $('dlgOverlay')) dlgClose(false); };
document.addEventListener('keydown', e => {
  if(!$('dlgOverlay').classList.contains('open')) return;
  if(e.key === 'Escape') dlgClose(false);
  if(e.key === 'Enter') dlgClose(true);
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

// ------------------------------------------------ onglets
let TAB = 'music';
function showTab(name){
  if(name === 'online' && !$('pageOnline')) name = 'music';    // onglet En ligne : branche a l'etape 5
  TAB = name;
  closeMenu();
  segMark($('tabs'), t => t.dataset.tab === name);
  $('pageMusic').classList.toggle('active', name === 'music');
  $('pageImage').classList.toggle('active', name === 'image');
  $('pageCook').classList.toggle('active', name === 'cook');
  if($('pageOnline')) $('pageOnline').classList.toggle('active', name === 'online');
  $('openFolder').style.display = name === 'music' ? '' : 'none';
  $('openLog').style.display = name === 'image' ? '' : 'none';
  $('openCookLog').style.display = name === 'cook' ? '' : 'none';
  try{ localStorage.setItem('tab', name); }catch(e){}
  api('set_tab', name);
  if(name === 'image'){ renderPixels(); }
  if(S) render(S);
}
document.querySelectorAll('.tab').forEach(t => t.onclick = () => showTab(t.dataset.tab));

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
  // dernier onglet ouvert
  try{ const t0 = localStorage.getItem('tab'); if(t0 === 'image' || t0 === 'cook' || (t0 === 'online' && $('pageOnline'))) showTab(t0); }catch(e){}
  window.addEventListener('pywebviewready', onReady);
  if(window.pywebview) onReady();
}
