// DodoTopia : Réglages v2 — panneau à sections, sauvegarde automatique champ par champ (set_setting),
// « Avancé » replié, keycaps pour les raccourcis, « Rétablir » par section.
// Chaque champ est déclaré UNE fois dans FIELDS ; bornes, unités, défaut et valeur viennent de get_settings_schema().
// Les champs en contexte ne sont plus ici : transposition et volume (lecteur), joueur n° et avance/retard (panneau
// Multi audio du lecteur), contours / fond / blanc (bloc « Méthode » de la page Image).

const SETTINGS_SECTIONS = [
  {id: 'general', label: 'Général', ic: '🏠'},
  {id: 'lecture', label: 'Lecture', ic: '🎮', reset: 'lecture'},
  {id: 'hotkeys', label: 'Raccourcis', ic: '⌨️', reset: 'hotkeys'},
  {id: 'multi', label: 'Multi audio', ic: '👥', reset: 'multi'},
  {id: 'draw', label: 'Dessin', ic: '🎨', reset: 'draw'},
  {id: 'cook', label: 'Cuisine', ic: '🍳', reset: 'cook'},
  {id: 'online', label: 'En ligne', ic: '🌐', reset: 'online'},
  {id: 'about', label: 'À propos', ic: 'ℹ️'},
];

// {path, section, control: switch|slider|number|seg|select|text, label, help, advanced, wide, options}
const FIELDS = [
  // ---- Lecture
  {path: 'stop_on_input', section: 'lecture', control: 'switch', label: 'Reprendre la main', help: 'Une touche ou un clic pendant la lecture dans le jeu l’arrête aussitôt.'},
  {path: 'start_delay', section: 'lecture', control: 'slider', label: 'Délai avant lecture', help: 'Le temps de revenir dans le jeu après F6.'},
  {path: 'hold_mode', section: 'lecture', control: 'seg', advanced: true, label: 'Mode d’appui', options: [['note', 'Suivre la musique'], ['tap', 'Tap bref']], help: 'Suivre la musique : appuis longs sur les notes tenues. Tap : la même durée pour toutes.'},
  {path: 'hold_time', section: 'lecture', control: 'number', advanced: true, label: 'Durée d’appui', help: 'Durée minimale d’une touche enfoncée.'},
  {path: 'input_mode', section: 'lecture', control: 'seg', advanced: true, label: 'Envoi des touches', options: [['scancode', 'Position (recommandé)'], ['vk', 'Lettre affichée']], help: 'Passe en « Lettre affichée » seulement si les notes jouées sont fausses.'},
  // ---- Raccourcis : générés depuis hotkey_labels (control keycap)
  // ---- Multi audio
  {path: 'multi.device', section: 'multi', control: 'select', wide: true, label: 'Sortie audio écoutée', help: 'Celle où le jeu joue le son ; la liste est relue à chaque ouverture.', options: () => [['', 'Sortie par défaut (recommandé)'], ...(SET.sch.multi_devices || []).map(n => [n, n])]},
  {path: 'multi.countdown', section: 'multi', control: 'slider', label: 'Compte à rebours', help: 'Durée d’écoute du jeu avant de devenir meneur.'},
  {path: 'multi.lead', section: 'multi', control: 'number', advanced: true, label: 'Délai après la note repère', help: 'Temps entre le motif repère et le départ de la musique.'},
  // ---- Dessin (contours / fond / blanc : bloc « Méthode » de la page Image)
  {path: 'draw.verify', section: 'draw', control: 'switch', label: 'Vérifier et corriger', help: 'Relit l’écran après chaque couleur et repeint les cases manquantes.'},
  {path: 'draw.mouse_glide', section: 'draw', control: 'switch', label: 'Souris naturelle', help: 'Le curseur glisse jusqu’à chaque cible au lieu de sauter.'},
  {path: 'draw.glide_speed', section: 'draw', control: 'number', advanced: true, label: 'Durée des glissements', help: '1 = environ 0,1 s pour 100 px ; 2 = deux fois plus lent.'},
  {path: 'draw.dense', section: 'draw', control: 'switch', advanced: true, label: 'Mode précis', help: 'Un point de souris par case dès le départ : plus lent, si les traits restent en pointillés.'},
  {path: 'draw.refine', section: 'draw', control: 'switch', advanced: true, label: 'Deux repères', help: 'Peint deux cases repères et mesure la taille exacte des cases à l’écran.'},
  {path: 'draw.step_delay', section: 'draw', control: 'number', advanced: true, label: 'Délai entre deux points', help: 'Augmente-le si le jeu coupe les angles des traits.'},
  {path: 'draw.click_delay', section: 'draw', control: 'number', advanced: true, label: 'Délai après un clic', help: 'Changement de couleur, case isolée.'},
  // ---- Cuisine (aides tirées des commentaires de DEFAULT_COOK)
  {path: 'cook.max_dishes', section: 'cook', control: 'number', label: 'Nombre de plats', help: '0 = sans fin, jusqu’à l’arrêt ou la fin des ingrédients.'},
  {path: 'cook.cook_timeout', section: 'cook', control: 'number', label: 'Durée maximale d’une cuisson', help: 'Au-delà, la boucle s’arrête (plat pas prêt).'},
  {path: 'cook.match', section: 'cook', control: 'number', advanced: true, label: 'Seuil de reconnaissance', help: 'Score minimal pour reconnaître une icône : baisse-le si la bulle n’est pas vue, monte-le si autre chose est prise pour elle.'},
  {path: 'cook.green_px', section: 'cook', control: 'number', advanced: true, label: 'Pixels verts de l’anneau', help: 'Minimum de pixels verts pour reconnaître l’anneau de la spatule.'},
  {path: 'cook.click_delay', section: 'cook', control: 'number', advanced: true, label: 'Délai après un clic', help: 'Temps laissé au jeu après chaque clic.'},
  // ---- En ligne
  {path: 'online.server_url', section: 'online', control: 'text', wide: true, label: 'Adresse du serveur', help: 'Serveur DodoTopia : mises à jour, bibliothèque, salons.'},
  {path: 'online.check_updates', section: 'online', control: 'switch', label: 'Vérifier les mises à jour', help: 'Au lancement, propose la nouvelle version quand il y en a une.'},
];

const INSTALL_KIND = {setup: 'Installée (installeur)', portable: 'Portable', targz: 'Archive Linux', source: 'Depuis les sources'};
const SET = {sch: null, section: 'general', timers: {}, lastSent: {}, listening: null, savedTimer: null};

// ------------------------------------------------ helpers
function fieldSpec(path){ return SET.sch && SET.sch.fields ? SET.sch.fields[path] : null; }
function fieldId(path){ return 'sf_' + path.replace(/[^a-z0-9]/gi, '_'); }
function decimalsOf(step){ const s = String(step || 1); const i = s.indexOf('.'); return i < 0 ? 0 : s.length - i - 1; }
function fmtVal(v, spec){
  if(v == null || v === '') return '–';
  const n = Number(v);
  const s = isNaN(n) ? String(v) : n.toFixed(decimalsOf(spec && spec.step)).replace('.', ',');
  return spec && spec.unit ? `${s} ${spec.unit}` : s;
}
function settingsOpen(){ return $('overlay').classList.contains('open'); }
function flashSaved(ok){
  const el = $('settingsSaved');
  el.textContent = ok ? 'Enregistré ✓' : 'Non enregistré';
  el.classList.toggle('err', !ok);
  el.classList.add('show');
  clearTimeout(SET.savedTimer);
  SET.savedTimer = setTimeout(() => el.classList.remove('show'), ok ? 1400 : 2600);
}
function fieldBox(path){
  const pane = $('settingsPane');
  const box = pane.querySelector(`.sfield[data-path="${CSS.escape(path)}"]`);
  if(box) return box;
  const g = pane.querySelector(`[data-gpath="${CSS.escape(path)}"]`);
  return g ? g.closest('.sfield') : null;
}
function setFieldError(path, msg){
  const box = fieldBox(path); if(!box) return;
  const err = box.querySelector('.field__error'); if(!err) return;
  err.textContent = msg || ''; err.hidden = !msg;
  box.classList.toggle('has-error', !!msg);
}

// ------------------------------------------------ sauvegarde automatique
function saveSetting(path, value){
  clearTimeout(SET.timers[path]); delete SET.timers[path];
  const key = JSON.stringify(value);
  if(SET.lastSent[path] === key) return Promise.resolve(null);
  SET.lastSent[path] = key;
  return api('set_setting', path, value).then(r => {
    const spec = fieldSpec(path);
    if(r == null){ if(spec) spec.value = value; flashSaved(true); return r; }   // aperçu sans backend
    if(r.ok){
      if(spec) spec.value = r.value;
      setFieldError(path, ''); refreshField(path, r.value); flashSaved(true);
    } else {
      delete SET.lastSent[path];
      if(spec && r.value !== undefined && r.value !== null) spec.value = r.value;
      setFieldError(path, r.error || 'valeur refusée'); refreshField(path, r.value); flashSaved(false);
    }
    return r;
  });
}
function saveLater(path, value){
  clearTimeout(SET.timers[path]);
  SET.timers[path] = setTimeout(() => saveSetting(path, value), 300);
}
function flushPending(){
  for(const path of Object.keys(SET.timers)){
    clearTimeout(SET.timers[path]); delete SET.timers[path];
    const box = fieldBox(path); const el = box && (box.querySelector(`[data-gpath="${CSS.escape(path)}"]`) || box.querySelector('input,select'));
    if(el && el.value !== '' && !(el.validity && el.validity.badInput)) saveSetting(path, el.type === 'checkbox' ? el.checked : el.value);
  }
}
// remet la valeur (normalisée ou restaurée) dans le contrôle, sans toucher à un champ en cours de saisie
function refreshField(path, value){
  if(value === undefined || value === null) return;
  const box = fieldBox(path); if(!box) return;
  const spec = fieldSpec(path);
  const g = box.querySelector(`[data-gpath="${CSS.escape(path)}"]`);
  if(g){ if(document.activeElement !== g) g.value = value; return; }
  const kc = box.querySelector('.keycap'); if(kc){ kc.textContent = value || '–'; return; }
  const seg = box.querySelector('.seg'); if(seg){ segMark(seg, b => String(b.dataset.v) === String(value)); return; }
  const cb = box.querySelector('input[type=checkbox]'); if(cb){ cb.checked = !!value; return; }
  const rg = box.querySelector('input[type=range]');
  if(rg){ if(document.activeElement !== rg) rg.value = value; const v = box.querySelector('.stepper__v'); if(v) v.textContent = fmtVal(value, spec); return; }
  const inp = box.querySelector('input,select'); if(inp && document.activeElement !== inp) inp.value = value;
}

// ------------------------------------------------ rendu d'un champ
function renderField(f){
  const spec = fieldSpec(f.path); if(!spec) return '';
  const id = fieldId(f.path);
  const unit = spec.unit ? `<span class="field__unit">${esc(spec.unit)}</span>` : '';
  const val = spec.value == null ? '' : spec.value;
  let ctl = '';
  if(f.control === 'switch'){
    ctl = `<label class="switch"><input type="checkbox" id="${id}" ${val ? 'checked' : ''} aria-labelledby="${id}_l"><span class="switch__track"></span></label>`;
  } else if(f.control === 'slider'){
    ctl = `<input type="range" id="${id}" min="${spec.min}" max="${spec.max}" step="${spec.step}" value="${esc(val)}" aria-labelledby="${id}_l"><span class="stepper__v">${fmtVal(val, spec)}</span>`;
  } else if(f.control === 'number'){
    ctl = `<input type="number" id="${id}" min="${spec.min}" max="${spec.max}" step="${spec.step}" value="${esc(val)}" aria-labelledby="${id}_l">${unit}`;
  } else if(f.control === 'seg'){
    const opts = (typeof f.options === 'function' ? f.options() : f.options) || (spec.choices || []).map(c => [c, c]);
    ctl = `<div class="seg" id="${id}" role="radiogroup" aria-labelledby="${id}_l">` + opts.map(([v, l]) => {
      const on = String(v) === String(val);
      return `<button type="button" role="radio" data-v="${esc(v)}" aria-checked="${on}" class="${on ? 'active' : ''}" tabindex="${on ? 0 : -1}">${esc(l)}</button>`;
    }).join('') + '</div>';
  } else if(f.control === 'select'){
    let opts = (typeof f.options === 'function' ? f.options() : f.options) || [];
    if(val && !opts.some(([v]) => v === val)) opts = [...opts, [val, val + ' (absente)']];
    ctl = `<select id="${id}" class="select" aria-labelledby="${id}_l">` + opts.map(([v, l]) => `<option value="${esc(v)}" ${v === val ? 'selected' : ''}>${esc(l)}</option>`).join('') + '</select>';
  } else if(f.control === 'text'){
    ctl = `<input type="text" id="${id}" class="input" value="${esc(val)}" spellcheck="false" aria-labelledby="${id}_l">`;
  }
  return `<div class="field sfield${f.wide ? ' sfield--wide' : ''}" data-path="${esc(f.path)}" data-control="${f.control}">
    <span class="field__label" id="${id}_l">${esc(f.label)}</span>
    ${f.help ? `<span class="field__help">${esc(f.help)}</span>` : ''}
    <span class="field__error" hidden></span>
    <div class="field__control">${ctl}</div>
  </div>`;
}
function renderFieldList(list){ return list.map(renderField).join(''); }
function renderAdvanced(list, extraHtml){
  const body = renderFieldList(list) + (extraHtml || '');
  if(!body.trim()) return '';
  return `<details class="disclosure" ${SET.advOpen ? 'open' : ''} id="settingsAdv"><summary>Avancé</summary><div class="disclosure__body">${body}</div></details>`;
}
function bindFields(root){
  root.querySelectorAll('.sfield[data-path]').forEach(box => {
    const path = box.dataset.path, ctl = box.dataset.control;
    if(ctl === 'switch'){
      const cb = box.querySelector('input[type=checkbox]');
      cb.onchange = () => saveSetting(path, cb.checked);
    } else if(ctl === 'slider'){
      const rg = box.querySelector('input[type=range]'), v = box.querySelector('.stepper__v');
      rg.oninput = () => { v.textContent = fmtVal(rg.value, fieldSpec(path)); saveLater(path, Number(rg.value)); };
      rg.onchange = () => saveSetting(path, Number(rg.value));
    } else if(ctl === 'number'){
      const inp = box.querySelector('input[type=number]');
      const ok = () => inp.value !== '' && !(inp.validity && inp.validity.badInput);
      inp.oninput = () => { if(ok()) saveLater(path, Number(inp.value)); };
      inp.onchange = () => { if(ok()) saveSetting(path, Number(inp.value)); else refreshField(path, (fieldSpec(path) || {}).value); };
      inp.onkeydown = e => { if(e.key === 'Enter') inp.blur(); };
    } else if(ctl === 'seg'){
      const seg = box.querySelector('.seg');
      seg.querySelectorAll('button').forEach(b => b.onclick = () => {
        segMark(seg, x => x === b);
        const spec = fieldSpec(path);
        saveSetting(path, spec && (spec.type === 'int' || spec.type === 'num') ? Number(b.dataset.v) : b.dataset.v);
      });
    } else if(ctl === 'select'){
      const sel = box.querySelector('select');
      sel.onchange = () => saveSetting(path, sel.value);
    } else if(ctl === 'text'){
      const inp = box.querySelector('input[type=text]');
      inp.oninput = () => saveLater(path, inp.value);
      inp.onchange = () => saveSetting(path, inp.value);
      inp.onkeydown = e => { if(e.key === 'Enter') inp.blur(); };
    }
  });
}

// ------------------------------------------------ raccourcis (keycaps)
function renderHotkeyFields(){
  const labels = SET.sch.hotkey_labels || {};
  return Object.keys(labels).map(name => {
    const path = 'hotkeys.' + name, spec = fieldSpec(path); if(!spec) return '';
    return `<div class="field sfield" data-path="${esc(path)}" data-control="keycap">
      <span class="field__label">${esc(labels[name])}</span>
      <span class="field__error" hidden></span>
      <div class="field__control">
        <button type="button" class="keycap" data-hk="${esc(path)}" title="Cliquer puis appuyer sur la nouvelle touche" aria-label="${esc(labels[name])} : ${esc(spec.value || 'aucune')}">${esc(spec.value || '–')}</button>
        <button type="button" class="keycap__clear" data-hkreset="${esc(path)}" title="Remettre ${esc(spec.default)}" aria-label="Remettre ${esc(spec.default)}">×</button>
      </div>
    </div>`;
  }).join('');
}
function hotkeyListen(btn, path){
  hotkeyCancel();
  SET.listening = {btn, path, prev: btn.textContent};
  btn.classList.add('is-listening'); btn.textContent = 'Appuie sur une touche…';
}
function hotkeyCancel(){
  const l = SET.listening; if(!l) return;
  l.btn.classList.remove('is-listening'); l.btn.textContent = l.prev; SET.listening = null;
}
function comboFromEvent(e){
  let key = e.key;
  if(['Control', 'Alt', 'Shift', 'Meta', 'AltGraph'].includes(key)) return null;
  if(key === ' ') key = 'space';
  if(key.length === 1) key = key.toLowerCase();
  const mods = [];
  if(e.ctrlKey) mods.push('ctrl'); if(e.altKey) mods.push('alt'); if(e.shiftKey) mods.push('shift');
  return [...mods, key].join('+');
}
function bindHotkeys(root){
  root.querySelectorAll('.keycap[data-hk]').forEach(b => b.onclick = () => (SET.listening && SET.listening.btn === b) ? hotkeyCancel() : hotkeyListen(b, b.dataset.hk));
  root.querySelectorAll('.keycap__clear[data-hkreset]').forEach(b => b.onclick = () => {
    const path = b.dataset.hkreset, spec = fieldSpec(path);
    if(spec) saveSetting(path, spec.default);
  });
}
// une seule écoute clavier pour le panneau : capture de raccourci, sinon Échap ferme
document.addEventListener('keydown', e => {
  if(!settingsOpen()) return;
  if(SET.listening){
    e.preventDefault(); e.stopPropagation();
    if(e.key === 'Escape'){ hotkeyCancel(); return; }
    const combo = comboFromEvent(e); if(!combo) return;
    const {btn, path} = SET.listening;
    SET.listening = null; btn.classList.remove('is-listening'); btn.textContent = combo;
    saveSetting(path, combo);
    return;
  }
  if(e.key === 'Escape' && !$('dlgOverlay').classList.contains('open')){ e.preventDefault(); closeSettings(); }
}, true);

// ------------------------------------------------ grilles (section « grids » du schéma : tableau des 5 formats)
function gridBadge(f, c, r){
  const validated = !!(S && S.draw && S.draw.validated && S.draw.validated[f]);
  if(validated) return '<span class="chip chip--badge chip--ok">validé</span>';
  if(c.value === c.default && r.value === r.default) return '<span class="chip chip--badge">par défaut</span>';
  return '<span class="chip chip--badge chip--info">saisi</span>';
}
function renderGrids(){
  const fmts = (typeof FORMATS !== 'undefined' ? FORMATS : ['16:9', '4:3', '1:1', '3:4', '9:16']);
  const rows = fmts.map(f => {
    const c = fieldSpec(`draw.formats.${f}.cols`), r = fieldSpec(`draw.formats.${f}.rows`); if(!c || !r) return '';
    return `<tr data-fmt="${f}"><td class="fmt">${f}</td>
      <td class="cells"><input type="number" data-gpath="draw.formats.${f}.cols" min="${c.min}" max="${c.max}" step="1" value="${esc(c.value)}" aria-label="Colonnes ${f}"> × <input type="number" data-gpath="draw.formats.${f}.rows" min="${r.min}" max="${r.max}" step="1" value="${esc(r.value)}" aria-label="Lignes ${f}"></td>
      <td>${gridBadge(f, c, r)}</td>
      <td class="act"><button type="button" class="btn btn--ghost btn--round" data-greset="${f}" title="Remettre ${c.default} × ${r.default}" aria-label="Remettre ${c.default} × ${r.default}">↺</button></td></tr>`;
  }).join('');
  if(!rows) return '';
  return `<div class="field sfield sfield--wide" data-grids="1">
    <span class="field__label">Cases par format</span>
    <span class="field__help">Largeur × hauteur à la finesse maximale ; détecté au calibrage si la grille du jeu est visible, sinon corrige ici.</span>
    <span class="field__error" hidden></span>
    <div class="field__control"><table class="gridtab"><thead><tr><th>Format</th><th>Cases</th><th>État</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="field__control" style="justify-content:flex-end"><button type="button" class="btn btn--ghost btn--sm" id="btnGridsReset">↺ Rétablir toutes les grilles</button></div>
  </div>`;
}
function bindGrids(root){
  root.querySelectorAll('input[data-gpath]').forEach(inp => {
    const path = inp.dataset.gpath;
    const ok = () => inp.value !== '' && !(inp.validity && inp.validity.badInput);
    inp.oninput = () => { if(ok()) saveLater(path, Number(inp.value)); };
    inp.onchange = () => { if(ok()) saveSetting(path, Number(inp.value)).then(refreshGridBadges); else refreshField(path, (fieldSpec(path) || {}).value); };
    inp.onkeydown = e => { if(e.key === 'Enter') inp.blur(); };
  });
  root.querySelectorAll('[data-greset]').forEach(b => b.onclick = () => {
    const f = b.dataset.greset, c = fieldSpec(`draw.formats.${f}.cols`), r = fieldSpec(`draw.formats.${f}.rows`);
    delete SET.lastSent[`draw.formats.${f}.cols`]; delete SET.lastSent[`draw.formats.${f}.rows`];
    saveSetting(`draw.formats.${f}.cols`, c.default).then(() => saveSetting(`draw.formats.${f}.rows`, r.default)).then(refreshGridBadges);
  });
  const all = root.querySelector('#btnGridsReset');
  if(all) all.onclick = () => resetSection('grids', 'les grilles des 5 formats');
}
function refreshGridBadges(){
  $('settingsPane').querySelectorAll('tr[data-fmt]').forEach(tr => {
    const f = tr.dataset.fmt, c = fieldSpec(`draw.formats.${f}.cols`), r = fieldSpec(`draw.formats.${f}.rows`);
    if(c && r) tr.children[2].innerHTML = gridBadge(f, c, r);
  });
}

// ------------------------------------------------ blocs spécifiques
function renderFolders(){
  const sch = SET.sch;
  return `<div class="field sfield sfield--wide">
      <span class="field__label">Dossier des musiques</span>
      <span class="field__help">Les fichiers .mid importés sont copiés ici.</span>
      <div class="field__control"><input type="text" class="input" readonly value="${esc(sch.songs_folder || '')}" aria-label="Dossier des musiques"><button type="button" class="btn btn--secondary btn--sm" id="sOpenSongs">Ouvrir le dossier</button></div>
    </div>
    <div class="field sfield sfield--wide">
      <span class="field__label">Dossier de données</span>
      <span class="field__help">Réglages, bibliothèque et journaux.</span>
      <div class="field__control"><input type="text" class="input" readonly value="${esc(sch.data_dir || '')}" aria-label="Dossier de données"><button type="button" class="btn btn--secondary btn--sm" id="sOpenData">Ouvrir</button></div>
    </div>`;
}
function multiDiagText(st){
  const mu = (st && st.settings && st.settings.multi) || {};
  const lat = mu.latency != null ? `${Math.round(mu.latency * 1000)} ms` : 'non mesurée';
  const fr = mu.beacon_freqs ? ` · fréquences ${mu.beacon_freqs.map(f => Math.round(f)).join(' / ')} Hz` : '';
  return `Latence mesurée : <b>${lat}</b>${fr}`;
}
function multiResultText(st){
  const m = (st && st.multi) || {};
  if(m.state === 'test') return m.message || 'Test en cours…';
  if(m.test) return (m.test.ok ? '✅ ' : '⚠️ ') + (m.test.message || '');
  return '';
}
function renderMultiDiag(){
  return `<div class="notice notice--info" id="multiDiag"><span class="notice__ic">🔔</span><div class="notice__text">
    <b>Diagnostic</b>
    <div id="multiDiagInfo">${multiDiagText(S)}</div>
    <div id="multiTestResult">${esc(multiResultText(S))}</div>
    <div class="notice__actions">
      <button type="button" class="btn btn--secondary btn--sm" id="btnMultiTest">Tester la détection</button>
      <button type="button" class="btn btn--secondary btn--sm" id="btnMultiListen">Écouter 30 s</button>
    </div>
    <span class="field__help">La fenêtre se réduit pendant le test : passe sur Heartopia, instrument ouvert. L’écoute dit quels motifs elle reconnaît.</span>
  </div></div>`;
}
function bindMultiDiag(root){
  const t = root.querySelector('#btnMultiTest'), l = root.querySelector('#btnMultiListen');
  if(t) t.onclick = () => { $('multiTestResult').textContent = 'Test lancé : passe sur Heartopia (3 s), instrument ouvert…'; api('multi_test'); };
  if(l) l.onclick = () => { $('multiTestResult').textContent = 'Écoute de 30 s lancée…'; api('multi_listen_test', 30); };
}
view('settingsMulti', {draw: st => {
  if(!settingsOpen() || SET.section !== 'multi') return;
  html('multiDiagInfo', multiDiagText(st));
  const r = multiResultText(st); if(r) txt('multiTestResult', r);
  const busy = st.multi && st.multi.state !== 'idle';
  ['btnMultiTest', 'btnMultiListen'].forEach(id => { const b = $(id); if(b) b.disabled = !!busy; });
}});
function renderAbout(){
  const sch = SET.sch, logs = sch.logs || {};
  const logBtn = (name, label) => `<button type="button" class="btn btn--secondary btn--sm" data-log="${name}" ${logs[name] === false ? 'disabled title="Pas encore de journal"' : ''}>${label}</button>`;
  return `<dl class="about">
      <dt>Version</dt><dd><b>DodoTopia ${esc(sch.version || '')}</b><span class="chip chip--badge">${esc(INSTALL_KIND[sch.install_kind] || sch.install_kind || '')}</span></dd>
      <dt>Mises à jour</dt><dd><button type="button" class="btn btn--secondary btn--sm" id="btnUpdateCheck" ${sch.online_ready ? '' : 'disabled'}>Vérifier les mises à jour</button>${sch.online_ready ? '' : '<span class="chip chip--badge chip--warn">bientôt</span>'}</dd>
      <dt>Journaux</dt><dd>${logBtn('multi', 'Multi')}${logBtn('dessin', 'Dessin')}${logBtn('cuisine', 'Cuisine')}</dd>
      <dt>Données</dt><dd><span class="path">${esc(sch.data_dir || '')}</span><button type="button" class="btn btn--ghost btn--sm" id="sOpenData2">Ouvrir</button></dd>
    </dl>
    <p class="settings__intro">Boîte à outils pour Heartopia : musique, dessin et cuisine dans le jeu. Les réglages sont enregistrés dès qu’ils changent.</p>`;
}

// ------------------------------------------------ sections
const SECTION_INTRO = {
  hotkeys: 'Raccourcis globaux, actifs même quand le jeu a le focus. « Jouer / pause » joue, dessine ou cuisine selon l’onglet ouvert ; « Arrêter » arrête tout.',
  multi: 'À plusieurs sans réseau : F6 lance un compte à rebours, le premier joue une note repère dans le jeu, les autres la détectent et partent ensemble. Numéro de joueur et avance/retard : panneau Multi audio du lecteur.',
  draw: 'Comment DodoTopia peint dans le jeu (contours, fond et blanc : bloc « Méthode » de la page Image). Les grilles calibrées ne sont pas touchées par « Rétablir ».',
  cook: 'Boucle de cuisine : nombre de plats et seuils de reconnaissance des bulles.',
  online: 'Le serveur DodoTopia n’est pas encore branché : ces réglages seront utilisés par la mise à jour, la bibliothèque et les salons.',
};
function sectionFields(id, advanced){ return FIELDS.filter(f => f.section === id && !!f.advanced === !!advanced); }
function renderSection(id){
  const pane = $('settingsPane'); const top = pane.scrollTop;
  const sec = SETTINGS_SECTIONS.find(s => s.id === id) || SETTINGS_SECTIONS[0];
  SET.section = sec.id;
  hotkeyCancel();
  try{ localStorage.setItem('settingsSection', sec.id); }catch(e){}
  $('settingsNav').querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.section === sec.id));
  let body = `<h3>${esc(sec.label)}</h3>` + (SECTION_INTRO[sec.id] ? `<p class="settings__intro">${esc(SECTION_INTRO[sec.id])}</p>` : '');
  if(sec.id === 'general') body += renderFolders();
  else if(sec.id === 'hotkeys') body += renderHotkeyFields();
  else if(sec.id === 'about') body += renderAbout();
  else {
    body += renderFieldList(sectionFields(sec.id, false));
    if(sec.id === 'multi') body += renderMultiDiag();
    body += renderAdvanced(sectionFields(sec.id, true), sec.id === 'draw' ? renderGrids() : '');
  }
  if(sec.reset) body += `<div class="settings__actions"><button type="button" class="btn btn--ghost btn--sm" id="btnSectionReset">↺ Rétablir les valeurs par défaut</button></div>`;
  pane.innerHTML = body;
  bindFields(pane); bindHotkeys(pane); bindGrids(pane); bindMultiDiag(pane);
  const adv = pane.querySelector('#settingsAdv'); if(adv) adv.ontoggle = () => { SET.advOpen = adv.open; };
  const so = pane.querySelector('#sOpenSongs'); if(so) so.onclick = () => api('open_songs_folder');
  pane.querySelectorAll('#sOpenData,#sOpenData2').forEach(b => b.onclick = () => api('open_data_folder'));
  pane.querySelectorAll('[data-log]').forEach(b => b.onclick = () => api('open_log', b.dataset.log));
  const rs = pane.querySelector('#btnSectionReset'); if(rs) rs.onclick = () => resetSection(sec.reset, sec.label);
  pane.scrollTop = top;
}
function resetSection(section, label){
  const grids = section === 'grids';
  dialog({title: 'Rétablir les valeurs par défaut', icon: '↺', ok: 'Rétablir',
    html: `Remettre ${grids ? '' : 'les réglages de '}<b>${esc(label)}</b> à leurs valeurs d’origine ?` +
      (section === 'draw' ? '<br><small>Les grilles calibrées ne sont pas touchées.</small>' : '') +
      (grids ? '<br><small>Les grilles validées par le calibrage seront à refaire.</small>' : '')
  }).then(ok => {
    if(!ok) return;
    api('reset_settings', section).then(r => {
      if(r && r.ok === false){ toast(r.error || 'Impossible de rétablir', 'warn'); return; }
      SET.lastSent = {};
      reloadSchema().then(() => { renderSection(SET.section); flashSaved(true); });
    });
  });
}
function reloadSchema(){
  return api('get_settings_schema').then(sch => { if(sch && sch.fields) SET.sch = sch; });
}
function buildNav(){
  const nav = $('settingsNav');
  nav.innerHTML = SETTINGS_SECTIONS.map(s => `<button type="button" data-section="${s.id}" class="${s.id === SET.section ? 'active' : ''}"><span class="ic">${s.ic}</span>${esc(s.label)}</button>`).join('');
  nav.querySelectorAll('button').forEach(b => b.onclick = () => renderSection(b.dataset.section));
}

// ------------------------------------------------ ouverture / fermeture
function openSettings(schema){
  const go = sch => {
    if(!sch || !sch.fields) return;
    SET.sch = sch; SET.lastSent = {};
    try{ const s0 = localStorage.getItem('settingsSection'); if(s0 && SETTINGS_SECTIONS.some(s => s.id === s0)) SET.section = s0; }catch(e){}
    buildNav(); renderSection(SET.section);
    $('overlay').classList.add('open');
    setTimeout(() => { const b = $('settingsNav').querySelector('button.active'); if(b) b.focus(); }, 30);
  };
  if(schema) go(schema); else api('get_settings_schema').then(go);
}
function closeSettings(){
  hotkeyCancel(); flushPending();
  $('overlay').classList.remove('open');
  $('btnSettings').focus();
}
$('btnSettings').onclick = () => openSettings();
$('btnSettingsClose').onclick = closeSettings;
$('overlay').onclick = e => { if(e.target === $('overlay')) closeSettings(); };
