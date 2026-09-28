// DodoTopia : Réglages v2 — panneau à sections, sauvegarde automatique champ par champ (set_setting),
// « Avancé » replié, keycaps pour les raccourcis, réinitialisation à portée explicite.
// Chaque champ est déclaré UNE fois dans FIELDS() ; bornes, unités, défaut et valeur viennent de get_settings_schema().
// Les réglages qui appartiennent à une tâche restent près d'elle et ne sont pas ici : transposition et volume
// (lecteur), joueur n° et avance/retard (panneau de synchronisation), format, cadrage, couleurs et méthode
// (activité Dessin), quantité de plats et nombre de cuisinières (activité Cuisine).
// Libellés : clés settings.<chemin>.label | .help | .opt.<valeur> du catalogue (t()), lus au moment du rendu.

// resets : [[portée envoyée à reset_settings, clé du libellé « la lecture dans le jeu »…]] ; ic : nom d'icône du sprite
const SETTINGS_SECTIONS = [
  {id: 'audio', label: () => t('settings.section.audio'), ic: 'music',
   resets: [['lecture', () => t('settings.reset.lecture')], ['multi', () => t('settings.reset.multi')]]},
  {id: 'hotkeys', label: () => t('settings.section.hotkeys'), ic: 'keyboard', resets: [['hotkeys', () => t('settings.reset.hotkeys')]]},
  {id: 'draw', label: () => t('settings.section.draw'), ic: 'brush', resets: [['draw', () => t('settings.reset.draw')]]},
  {id: 'cook', label: () => t('settings.section.cook'), ic: 'pot', resets: [['cook', () => t('settings.reset.cook')]]},
  {id: 'online', label: () => t('settings.section.online'), ic: 'globe', resets: [['online', () => t('settings.reset.online')]]},
  {id: 'general', label: () => t('settings.section.general'), ic: 'palette'},
  {id: 'storage', label: () => t('settings.section.storage'), ic: 'folder'},
  {id: 'about', label: () => t('settings.section.about'), ic: 'info'},
];

// {path, section, control: switch|slider|number|seg|select|text, label, help, advanced, wide, options}
// Fonction : les libellés sont traduits à chaque rendu (changement de langue sans recharger la page).
function FIELDS(){ return [
  // ---- Apparence : langue de l'interface (liste = get_i18n().available)
  {path: 'general.lang', section: 'general', control: 'select', wide: true, label: t('settings.general.lang.label'), help: t('settings.general.lang.help'),
   options: () => [['auto', t('settings.general.lang.auto')], ...LANGS_AVAILABLE.map(a => [a.tag, a.beta ? t('settings.general.lang.opt_beta', {name: a.name}) : a.name])]},
  // ---- Apparence : overlay au-dessus de Heartopia (api/overlay.py)
  {path: 'overlay.enabled', section: 'general', control: 'switch', label: t('settings.overlay.enabled.label'), help: t('settings.overlay.enabled.help')},
  {path: 'overlay.corner', section: 'general', control: 'select', label: t('settings.overlay.corner.label'), help: t('settings.overlay.corner.help'),
   options: () => [['top-right', t('settings.overlay.corner.opt.top-right')], ['top-left', t('settings.overlay.corner.opt.top-left')],
                   ['top-center', t('settings.overlay.corner.opt.top-center')], ['bottom-left', t('settings.overlay.corner.opt.bottom-left')],
                   ['bottom-right', t('settings.overlay.corner.opt.bottom-right')]]},
  // ---- Musique et audio : lecture dans le jeu (groupe « lecture »)
  {path: 'stop_on_input', section: 'audio', group: 'lecture', control: 'switch', label: t('settings.stop_on_input.label'), help: t('settings.stop_on_input.help')},
  {path: 'start_delay', section: 'audio', group: 'lecture', control: 'slider', label: t('settings.start_delay.label'), help: t('settings.start_delay.help')},
  {path: 'multi.room_minimize', section: 'audio', group: 'lecture', control: 'switch', label: t('settings.multi.room_minimize.label'), help: t('settings.multi.room_minimize.help')},
  {path: 'arrange', section: 'audio', group: 'lecture', control: 'seg', label: t('settings.arrange.label'), options: [['auto', t('settings.arrange.opt.auto')], ['on', t('settings.arrange.opt.on')], ['off', t('settings.arrange.opt.off')]], help: t('settings.arrange.help')},
  {path: 'hold_mode', section: 'audio', group: 'lecture', control: 'seg', advanced: true, label: t('settings.hold_mode.label'), options: [['note', t('settings.hold_mode.opt.note')], ['tap', t('settings.hold_mode.opt.tap')]], help: t('settings.hold_mode.help')},
  {path: 'hold_time', section: 'audio', group: 'lecture', control: 'number', advanced: true, label: t('settings.hold_time.label'), help: t('settings.hold_time.help')},
  {path: 'input_mode', section: 'audio', group: 'lecture', control: 'seg', advanced: true, label: t('settings.input_mode.label'), options: [['scancode', t('settings.input_mode.opt.scancode')], ['vk', t('settings.input_mode.opt.vk')]], help: t('settings.input_mode.help')},
  {path: 'min_press', section: 'audio', group: 'lecture', control: 'number', advanced: true, label: t('settings.min_press.label'), help: t('settings.min_press.help')},
  {path: 'min_gap', section: 'audio', group: 'lecture', control: 'number', advanced: true, label: t('settings.min_gap.label'), help: t('settings.min_gap.help')},
  {path: 'sustain', section: 'audio', group: 'lecture', control: 'switch', advanced: true, label: t('settings.sustain.label'), help: t('settings.sustain.help')},
  {path: 'game_process', section: 'audio', group: 'lecture', control: 'text', advanced: true, label: t('settings.game_process.label'), help: t('settings.game_process.help')},
  // ---- Musique et audio : synchronisation par le son (groupe « multi »)
  {path: 'multi.device', section: 'audio', group: 'multi', control: 'select', wide: true, label: t('settings.multi.device.label'), help: t('settings.multi.device.help'), options: () => [['', t('settings.multi.device.opt.default')], ...(SET.sch.multi_devices || []).map(n => [n, n])]},
  {path: 'multi.countdown', section: 'audio', group: 'multi', control: 'slider', label: t('settings.multi.countdown.label'), help: t('settings.multi.countdown.help')},
  {path: 'multi.lead', section: 'audio', group: 'multi', control: 'number', advanced: true, label: t('settings.multi.lead.label'), help: t('settings.multi.lead.help')},
  // ---- Raccourcis : générés depuis HOTKEY_LABELS (control keycap)
  // ---- Dessin (contours / fond / blanc : « Options avancées » de la page Dessin)
  {path: 'draw.verify', section: 'draw', control: 'switch', label: t('settings.draw.verify.label'), help: t('settings.draw.verify.help')},
  {path: 'draw.mouse_glide', section: 'draw', control: 'switch', label: t('settings.draw.mouse_glide.label'), help: t('settings.draw.mouse_glide.help')},
  {path: 'draw.glide_speed', section: 'draw', control: 'number', advanced: true, label: t('settings.draw.glide_speed.label'), help: t('settings.draw.glide_speed.help')},
  {path: 'draw.dense', section: 'draw', control: 'switch', advanced: true, label: t('settings.draw.dense.label'), help: t('settings.draw.dense.help')},
  {path: 'draw.refine', section: 'draw', control: 'switch', advanced: true, label: t('settings.draw.refine.label'), help: t('settings.draw.refine.help')},
  {path: 'draw.step_delay', section: 'draw', control: 'number', advanced: true, label: t('settings.draw.step_delay.label'), help: t('settings.draw.step_delay.help')},
  {path: 'draw.click_delay', section: 'draw', control: 'number', advanced: true, label: t('settings.draw.click_delay.label'), help: t('settings.draw.click_delay.help')},
  // ---- Cuisine (aides tirées des commentaires de DEFAULT_COOK)
  {path: 'cook.cook_timeout', section: 'cook', control: 'number', label: t('settings.cook.cook_timeout.label'), help: t('settings.cook.cook_timeout.help')},
  {path: 'cook.match', section: 'cook', control: 'number', advanced: true, label: t('settings.cook.match.label'), help: t('settings.cook.match.help')},
  {path: 'cook.green_px', section: 'cook', control: 'number', advanced: true, label: t('settings.cook.green_px.label'), help: t('settings.cook.green_px.help')},
  {path: 'cook.click_delay', section: 'cook', control: 'number', advanced: true, label: t('settings.cook.click_delay.label'), help: t('settings.cook.click_delay.help')},
  // ---- En ligne
  {path: 'online.server_url', section: 'online', control: 'text', wide: true, label: t('settings.online.server_url.label'), help: t('settings.online.server_url.help')},
  {path: 'online.check_updates', section: 'online', control: 'switch', label: t('settings.online.check_updates.label'), help: t('settings.online.check_updates.help')},
  {path: 'online.auto_update', section: 'online', control: 'switch', label: t('settings.online.auto_update.label'), help: t('settings.online.auto_update.help')},
  // ---- En ligne : intégrations (Discord, OBS)
  {path: 'online.rich_presence', section: 'online', control: 'switch', label: t('settings.online.rich_presence.label'), help: t('settings.online.rich_presence.help')},
  {path: 'online.now_playing_file', section: 'online', control: 'switch', label: t('settings.online.now_playing_file.label'), help: t('settings.online.now_playing_file.help')},
]; }

const SET = {sch: null, section: SETTINGS_SECTIONS[0].id, timers: {}, lastSent: {}, listening: null, savedTimer: null, q: '', proto: null};

// ------------------------------------------------ helpers
function fieldSpec(path){ return SET.sch && SET.sch.fields ? SET.sch.fields[path] : null; }
function fieldId(path){ return 'sf_' + path.replace(/[^a-z0-9]/gi, '_'); }
function decimalsOf(step){ const s = String(step || 1); const i = s.indexOf('.'); return i < 0 ? 0 : s.length - i - 1; }
const NUM_FMT = {};
function fmtVal(v, spec){
  if(v == null || v === '') return '–';
  const n = Number(v);
  let s;
  if(isNaN(n)) s = String(v);
  else {
    const d = decimalsOf(spec && spec.step), k = I18N.lang + ':' + d;
    if(!NUM_FMT[k]) NUM_FMT[k] = new Intl.NumberFormat(I18N.lang, {minimumFractionDigits: d, maximumFractionDigits: d});
    s = NUM_FMT[k].format(n);
  }
  return spec && spec.unit ? `${s} ${spec.unit}` : s;
}
function settingsOpen(){ return $('overlay').classList.contains('open'); }
function flashSaved(ok){
  const el = $('settingsSaved');
  el.innerHTML = icon(ok ? 'check' : 'warn') + `<span>${esc(plain(ok ? t('settings.saved') : t('settings.not_saved')))}</span>`;
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
    if(r == null){   // aperçu sans backend
      if(spec) spec.value = value; flashSaved(true);
      // la langue change quand même en aperçu (mock.js fournit MOCK_I18N) ; en vrai, Python appelle applyLanguage()
      if(path === 'general.lang' && window.MOCK_I18N) applyLanguage(value);
      return r;
    }
    if(r.ok){
      if(spec) spec.value = r.value;
      setFieldError(path, ''); refreshField(path, r.value); flashSaved(true);
    } else {
      delete SET.lastSent[path];
      if(spec && r.value !== undefined && r.value !== null) spec.value = r.value;
      // r.error : texte de Python, ou {key, params} à traduire ici
      const err = r.error && r.error.key ? t(r.error.key, r.error.params || {}) : (r.error || t('settings.value_refused'));
      setFieldError(path, err); refreshField(path, r.value); flashSaved(false);
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
    if(val && !opts.some(([v]) => v === val)) opts = [...opts, [val, t('settings.select.missing', {name: val})]];
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
function renderAdvanced(list, extraHtml, suffix){
  const body = renderFieldList(list) + (extraHtml || '');
  if(!body.trim()) return '';
  return `<details class="disclosure" ${SET.advOpen ? 'open' : ''} id="settingsAdv${suffix ? '_' + suffix : ''}"><summary>${esc(t('settings.advanced'))}</summary><div class="disclosure__body">${body}</div></details>`;
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

// ------------------------------------------------ raccourcis (keycaps) : libellés du catalogue (HOTKEY_LABELS, core.js)
function renderHotkeyFields(names){
  return (names || Object.keys(HOTKEY_LABELS)).map(name => {
    const path = 'hotkeys.' + name, spec = fieldSpec(path); if(!spec) return '';
    const label = HOTKEY_LABELS[name];
    return `<div class="field sfield" data-path="${esc(path)}" data-control="keycap">
      <span class="field__label">${esc(label)}</span>
      <span class="field__error" hidden></span>
      <div class="field__control">
        <button type="button" class="keycap" data-hk="${esc(path)}" title="${esc(t('settings.hotkeys.keycap_title'))}" aria-label="${esc(t('settings.hotkeys.keycap_aria', {label, key: spec.value || t('settings.hotkeys.none')}))}">${esc(spec.value || '–')}</button>
        <button type="button" class="keycap__clear" data-hkreset="${esc(path)}" title="${esc(t('settings.hotkeys.reset_to', {key: spec.default}))}" aria-label="${esc(t('settings.hotkeys.reset_to', {key: spec.default}))}">${icon('undo')}</button>
      </div>
    </div>`;
  }).join('');
}
function hotkeyListen(btn, path){
  hotkeyCancel();
  SET.listening = {btn, path, prev: btn.textContent};
  btn.classList.add('is-listening'); btn.textContent = t('settings.hotkeys.press_key');
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
// capture d'un raccourci (phase de capture, avant tout le reste) ; Échap hors capture : gestionnaire unique (core.js)
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
}, true);

// ------------------------------------------------ grilles (section « grids » du schéma : tableau des 5 formats)
function gridBadge(f, c, r){
  const validated = !!(S && S.draw && S.draw.validated && S.draw.validated[f]);
  if(validated) return `<span class="chip chip--badge chip--ok">${esc(t('settings.grids.badge_validated'))}</span>`;
  if(c.value === c.default && r.value === r.default) return `<span class="chip chip--badge">${esc(t('settings.grids.badge_default'))}</span>`;
  return `<span class="chip chip--badge chip--info">${esc(t('settings.grids.badge_custom'))}</span>`;
}
function renderGrids(){
  const fmts = (typeof FORMATS !== 'undefined' ? FORMATS : ['16:9', '4:3', '1:1', '3:4', '9:16']);
  const rows = fmts.map(f => {
    const c = fieldSpec(`draw.formats.${f}.cols`), r = fieldSpec(`draw.formats.${f}.rows`); if(!c || !r) return '';
    const reset = t('settings.grids.reset_to', {cols: c.default, rows: r.default});
    return `<tr data-fmt="${f}"><td class="fmt">${f}</td>
      <td class="cells"><input type="number" data-gpath="draw.formats.${f}.cols" min="${c.min}" max="${c.max}" step="1" value="${esc(c.value)}" aria-label="${esc(t('settings.grids.cols_aria', {format: f}))}"> × <input type="number" data-gpath="draw.formats.${f}.rows" min="${r.min}" max="${r.max}" step="1" value="${esc(r.value)}" aria-label="${esc(t('settings.grids.rows_aria', {format: f}))}"></td>
      <td>${gridBadge(f, c, r)}</td>
      <td class="act"><button type="button" class="btn btn--ghost btn--round" data-greset="${f}" title="${esc(reset)}" aria-label="${esc(reset)}">${icon('undo')}</button></td></tr>`;
  }).join('');
  if(!rows) return '';
  return `<div class="field sfield sfield--wide" data-grids="1">
    <span class="field__label">${esc(t('settings.grids.label'))}</span>
    <span class="field__help">${esc(t('settings.grids.help'))}</span>
    <span class="field__error" hidden></span>
    <div class="field__control"><table class="gridtab"><thead><tr><th>${esc(t('settings.grids.col_format'))}</th><th>${esc(t('settings.grids.col_cells'))}</th><th>${esc(t('settings.grids.col_state'))}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="field__control field__control--end"><button type="button" class="btn btn--ghost btn--sm" id="btnGridsReset">${icon('undo')}<span>${esc(plain(t('settings.grids.reset_all')))}</span></button></div>
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
  if(all) all.onclick = () => resetSection('grids', t('settings.reset.grids'));
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
  // Ces deux chemins sont imposés par l'installation : ils ne sont modifiables nulle part dans le moteur.
  // Ils sont donc présentés comme des valeurs, pas comme des champs de saisie.
  const row = (label, help, value, openId, copyId) => `<div class="field sfield sfield--wide">
      <span class="field__label">${esc(label)}</span>
      <span class="field__help">${esc(help)}</span>
      <div class="field__control pathrow">
        <code class="path path--wide" title="${esc(value)}">${esc(value)}</code>
        <button type="button" class="btn btn--secondary btn--sm" id="${copyId}">${esc(t('common.copy'))}</button>
        <button type="button" class="btn btn--secondary btn--sm" id="${openId}">${esc(t('settings.storage.open_folder'))}</button>
      </div>
    </div>`;
  return row(t('settings.storage.songs.label'), t('settings.storage.songs.help'), sch.songs_folder || '', 'sOpenSongs', 'sCopySongs')
    + row(t('settings.storage.data.label'), t('settings.storage.data.help'), sch.data_dir || '', 'sOpenData', 'sCopyData');
}
// langue en bêta : rappel que certains textes restent en français
function renderLangNotice(){
  const cur = LANGS_AVAILABLE.find(a => a.tag === I18N.lang);
  if(!cur || !cur.beta) return '';
  return `<div class="notice notice--info"><span class="notice__ic" aria-hidden="true">${icon('info')}</span><div class="notice__text">${esc(t('lang.beta_hint', {lang: cur.name}))}</div></div>`;
}
function multiDiagText(st){
  const mu = (st && st.settings && st.settings.multi) || {};
  const lat = mu.latency != null ? t('settings.multi.diag.latency_ms', {ms: Math.round(mu.latency * 1000)}) : t('settings.multi.diag.not_measured');
  const freqs = mu.beacon_freqs ? mu.beacon_freqs.map(f => Math.round(f)).join(' / ') : 'none';
  return t('settings.multi.diag.text', {lat: esc(lat), freqs});
}
// résultat du test de détection : icône d'état + message du moteur (échappé)
function multiResultText(st){
  const m = (st && st.multi) || {};
  if(m.state === 'test') return esc(m.message || t('settings.multi.diag.testing'));
  if(m.test) return `<span class="multitest multitest--${m.test.ok ? 'ok' : 'warn'}">${icon(m.test.ok ? 'check' : 'warn')}${esc(m.test.message || '')}</span>`;
  return '';
}
function renderMultiDiag(){
  return `<div class="notice notice--info" id="multiDiag"><span class="notice__ic" aria-hidden="true">${icon('bell')}</span><div class="notice__text">
    <b>${esc(t('settings.multi.diag.title'))}</b>
    <div id="multiDiagInfo">${multiDiagText(S)}</div>
    <div id="multiTestResult">${multiResultText(S)}</div>
    <div class="notice__actions">
      <button type="button" class="btn btn--secondary btn--sm" id="btnMultiTest">${esc(t('settings.multi.diag.test_btn'))}</button>
      <button type="button" class="btn btn--secondary btn--sm" id="btnMultiListen">${esc(t('settings.multi.diag.listen_btn'))}</button>
    </div>
    <span class="field__help">${esc(t('settings.multi.diag.help'))}</span>
  </div></div>`;
}
function bindMultiDiag(root){
  const tb = root.querySelector('#btnMultiTest'), l = root.querySelector('#btnMultiListen');
  const note = s => { const el = $('multiTestResult'); delete el.dataset.html; el.textContent = s; };
  if(tb) tb.onclick = () => { note(t('settings.multi.diag.test_started')); api('multi_test'); };
  if(l) l.onclick = () => { note(t('settings.multi.diag.listen_started')); api('multi_listen_test', 30); };
}
view('settingsMulti', {draw: st => {
  if(!settingsOpen()) return;
  if(SET.section === 'audio' && $('multiDiagInfo')){
    html('multiDiagInfo', multiDiagText(st));
    const r = multiResultText(st); if(r) html('multiTestResult', r);
    const busy = st.multi && st.multi.state !== 'idle';
    ['btnMultiTest', 'btnMultiListen'].forEach(id => { const b = $(id); if(b) b.disabled = !!busy; });
  }
  // la carte « Mise à jour » vit dans « À propos et mises à jour » : elle suit la progression en direct
  if(SET.section === 'about'){
    const box = $('settingsPane').querySelector('.update-box');
    const o = st.online || null;
    if(box && o){ const h = updateHtml(o); if(box.dataset.h !== h){ box.dataset.h = h; box.innerHTML = h; wireUpdate(box); } }
  }
}});
function renderAbout(){
  const sch = SET.sch, logs = sch.logs || {};
  const logBtn = (name, label) => `<button type="button" class="btn btn--secondary btn--sm" data-log="${name}" ${logs[name] === false ? `disabled title="${esc(t('settings.about.no_log'))}"` : ''}>${esc(label)}</button>`;
  const o = (S && S.online) || null;
  const upd = o ? `<section class="settings__group"><h4 class="settings__grouphead">${esc(t('settings.about.update'))}</h4>
      <div class="update-box">${updateHtml(o)}</div></section>`
    : `<section class="settings__group"><h4 class="settings__grouphead">${esc(t('settings.about.update'))}</h4>
      <p class="hint left">${esc(t('settings.about.no_network'))}</p></section>`;
  const kind = t('settings.about.install_kind', {kind: sch.install_kind || 'other', raw: sch.install_kind || ''});
  return upd + `<dl class="about">
      <dt>${esc(t('settings.about.version'))}</dt><dd><b>${esc(t('settings.about.version_value', {version: sch.version || ''}))}</b><span class="chip chip--badge">${esc(kind)}</span></dd>
      <dt>${esc(t('settings.about.logs'))}</dt><dd>${logBtn('multi', t('settings.about.log_multi'))}${logBtn('dessin', t('shell.tab.image'))}${logBtn('cuisine', t('shell.tab.cook'))}</dd>
      <dt>${esc(t('support.title'))}</dt><dd><button type="button" class="btn btn--secondary btn--sm" id="sReport">${esc(t('support.report_btn'))}</button><span class="hint">${esc(t('support.about_hint'))}</span></dd>
      <dt>${esc(t('settings.about.data'))}</dt><dd><span class="path">${esc(sch.data_dir || '')}</span><button type="button" class="btn btn--ghost btn--sm" id="sOpenData2">${esc(t('common.open'))}</button></dd>
      <dt>${esc(t('settings.about.site'))}</dt><dd><button type="button" class="btn btn--ghost btn--sm" data-site="site">dodotopia.cyber-dodo.fr</button></dd>
      <dt>${esc(t('settings.about.legal'))}</dt><dd><button type="button" class="btn btn--ghost btn--sm" data-site="mentions">${esc(t('settings.about.legal_notice'))}</button><button type="button" class="btn btn--ghost btn--sm" data-site="confidentialite">${esc(t('settings.about.privacy'))}</button><button type="button" class="btn btn--ghost btn--sm" data-site="conditions">${esc(t('settings.about.terms'))}</button></dd>
    </dl>
    <p class="settings__intro">${esc(t('settings.about.intro'))}</p>
    <p class="settings__legal">${t('settings.about.legal_1', {year: String(new Date().getFullYear())})}</p>
    <p class="settings__legal">${esc(t('settings.about.legal_2'))}</p>`;
}

// ------------------------------------------------ Apparence : thème (préférence locale, theme.js : aucun appel api)
function renderThemeField(){
  const cur = getTheme();
  const opts = [['auto', t('settings.general.theme.auto'), 'monitor'], ['light', t('settings.general.theme.light'), 'sun'], ['dark', t('settings.general.theme.dark'), 'moon']];
  return `<div class="field sfield" data-control="theme">
    <span class="field__label" id="sf_theme_l">${esc(t('settings.general.theme.label'))}</span>
    <span class="field__help">${esc(t('settings.general.theme.help'))}</span>
    <div class="field__control"><div class="seg" id="sf_theme" role="radiogroup" aria-labelledby="sf_theme_l">${opts.map(([v, l, ic]) => {
      const on = v === cur;
      return `<button type="button" role="radio" data-v="${v}" aria-checked="${on}" class="${on ? 'active' : ''}" tabindex="${on ? 0 : -1}">${icon(ic)}<span>${esc(l)}</span></button>`;
    }).join('')}</div></div>
  </div>`;
}
function bindTheme(root){
  const seg = root.querySelector('#sf_theme'); if(!seg) return;
  seg.querySelectorAll('button').forEach(b => b.onclick = () => { segMark(seg, x => x === b); setTheme(b.dataset.v); flashSaved(true); });
}

// ------------------------------------------------ Compte et connexion : liens dodotopia:// (protocol_status / register_protocol)
function protocolStateHtml(){
  const p = SET.proto;
  if(!p) return `<span class="chip chip--badge">${esc(t('settings.protocol.checking'))}</span>`;
  if(p.registered && p.current) return `<span class="chip chip--badge chip--ok">${icon('check')}${esc(t('settings.protocol.state.current'))}</span>`;
  if(p.registered) return `<span class="chip chip--badge chip--warn">${icon('warn')}${esc(t('settings.protocol.state.other'))}</span>`;
  return `<span class="chip chip--badge">${esc(t('settings.protocol.state.none'))}</span>`;
}
function protocolBtnLabel(){ return (SET.proto && SET.proto.registered && SET.proto.current) ? t('settings.protocol.register_again') : t('settings.protocol.register'); }
function renderProtocol(){
  return `<div class="field sfield sfield--wide" data-protocol="1">
    <span class="field__label">${esc(t('settings.protocol.title'))}</span>
    <span class="field__help">${esc(t('settings.protocol.help'))}</span>
    <div class="field__control protorow"><span id="protoState">${protocolStateHtml()}</span>
      <button type="button" class="btn btn--secondary btn--sm" id="btnProtoRegister">${icon('link')}<span>${esc(protocolBtnLabel())}</span></button></div>
  </div>`;
}
function refreshProtocol(){
  return api('protocol_status').then(r => {
    SET.proto = r && typeof r === 'object' ? r : {registered: false, command: '', current: false};
    const el = $('protoState'); if(el) el.innerHTML = protocolStateHtml();
    const b = $('btnProtoRegister'); const l = b && b.querySelector('span');
    if(l) l.textContent = protocolBtnLabel();
  });
}
function bindProtocol(root){
  const b = root.querySelector('#btnProtoRegister'); if(!b) return;
  b.onclick = () => apiAction(b, 'register_protocol').then(r => {
    if(r && r.ok === false) toast(r.error || t('common.action_failed'), 'warn');
    refreshProtocol();
  });
  if(!SET.proto) refreshProtocol();
}

// ------------------------------------------------ recherche : filtre les champs de TOUTES les sections (libellé, aide)
function settingsNorm(s){ return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
function renderSearch(q){
  const pane = $('settingsPane');
  const nq = settingsNorm(q.trim());
  const hit = (...xs) => xs.some(x => settingsNorm(x).includes(nq));
  $('settingsNav').querySelectorAll('button').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-current', 'false'); });
  hotkeyCancel();
  let n = 0;
  const groups = SETTINGS_SECTIONS.map(sec => {
    let body = '';
    const fields = FIELDS().filter(f => f.section === sec.id && fieldSpec(f.path) && hit(f.label, f.help));
    n += fields.length; body += renderFieldList(fields);
    if(sec.id === 'hotkeys'){
      const names = Object.keys(HOTKEY_LABELS).filter(k => fieldSpec('hotkeys.' + k) && hit(HOTKEY_LABELS[k]));
      n += names.length; body += renderHotkeyFields(names);
    }
    if(sec.id === 'general' && hit(t('settings.general.theme.label'), t('settings.general.theme.help'))){ n++; body = renderThemeField() + body; }
    if(sec.id === 'online' && hit(t('settings.protocol.title'), t('settings.protocol.help'))){ n++; body += renderProtocol(); }
    if(sec.id === 'draw' && hit(t('settings.grids.label'), t('settings.grids.help'))){ const g = renderGrids(); if(g){ n++; body += g; } }
    if(sec.id === 'storage' && hit(t('settings.storage.songs.label'), t('settings.storage.songs.help'), t('settings.storage.data.label'), t('settings.storage.data.help'))){ n++; body += renderFolders(); }
    return body ? `<section class="settings__group"><h4 class="settings__grouphead settings__grouphead--ic">${icon(sec.ic)}<span>${esc(sec.label())}</span></h4>${body}</section>` : '';
  }).join('');
  pane.innerHTML = `<h3>${esc(t('settings.search.title'))}</h3>`
    + (n ? `<p class="settings__intro">${esc(t('settings.search.results', {n}))}</p>` + groups
         : `<p class="settings__intro">${esc(t('settings.search.empty', {q: q.trim()}))}</p>`);
  bindPane(pane);
  pane.scrollTop = 0;
}
function settingsSearchSet(v){
  SET.q = v || '';
  const inp = $('settingsSearch');
  if(inp && inp.value !== SET.q) inp.value = SET.q;
  if($('settingsSearchBox')) $('settingsSearchBox').classList.toggle('has', !!SET.q);
}
(function settingsSearchWire(){
  const inp = $('settingsSearch'); if(!inp) return;
  inp.oninput = () => { settingsSearchSet(inp.value); if(SET.q.trim()) renderSearch(SET.q); else renderSection(SET.section); };
  // Échap vide d'abord la recherche ; un second Échap ferme les réglages (gestionnaire unique, core.js)
  inp.onkeydown = e => { if(e.key === 'Escape' && inp.value){ e.stopPropagation(); e.preventDefault(); settingsSearchSet(''); renderSection(SET.section); } };
  $('settingsSearchClr').onclick = () => { settingsSearchSet(''); renderSection(SET.section); inp.focus(); };
})();

// ------------------------------------------------ sections
function sectionIntro(id){
  return id === 'hotkeys' ? t('settings.intro.hotkeys') : id === 'draw' ? t('settings.intro.draw') : id === 'cook' ? t('settings.intro.cook')
    : id === 'online' ? t('settings.intro.online') : id === 'general' ? t('settings.intro.general') : '';
}
function groupTitle(group){
  if(group === 'lecture') return [t('settings.group.lecture.title'), t('settings.group.lecture.intro')];
  if(group === 'multi') return [t('settings.group.multi.title'), t('settings.group.multi.intro')];
  return [group, ''];
}
function sectionFields(id, advanced, group){
  return FIELDS().filter(f => f.section === id && !!f.advanced === !!advanced && (group === undefined || f.group === group));
}
function renderGroup(sec, group){
  const [title, intro] = groupTitle(group);
  let body = `<h4 class="settings__grouphead">${esc(title)}</h4>`
    + (intro ? `<p class="settings__intro">${esc(intro)}</p>` : '')
    + renderFieldList(sectionFields(sec.id, false, group));
  if(group === 'multi') body += renderMultiDiag();
  body += renderAdvanced(sectionFields(sec.id, true, group), '', group);
  return `<section class="settings__group">${body}</section>`;
}
function renderSection(id){
  if(SET.q && SET.q.trim()){ renderSearch(SET.q); return; }
  const pane = $('settingsPane'); const top = pane.scrollTop;
  const sec = SETTINGS_SECTIONS.find(s => s.id === id) || SETTINGS_SECTIONS[0];
  SET.section = sec.id;
  hotkeyCancel();
  $('settingsNav').querySelectorAll('button').forEach(b => {
    const on = b.dataset.section === sec.id;
    b.classList.toggle('active', on);
    b.setAttribute('aria-current', on ? 'true' : 'false');
  });
  const intro = sectionIntro(sec.id);
  let body = `<h3>${esc(sec.label())}</h3>` + (intro ? `<p class="settings__intro">${esc(intro)}</p>` : '');
  if(sec.id === 'storage') body += renderFolders();
  else if(sec.id === 'hotkeys') body += renderHotkeyFields();
  else if(sec.id === 'about') body += renderAbout();
  else if(sec.id === 'audio') body += renderGroup(sec, 'lecture') + renderGroup(sec, 'multi');
  else if(sec.id === 'general') body += renderThemeField() + renderFieldList(sectionFields(sec.id, false)) + renderLangNotice();
  else if(sec.id === 'online') body += renderFieldList(sectionFields(sec.id, false)) + renderProtocol();
  else {
    body += renderFieldList(sectionFields(sec.id, false));
    body += renderAdvanced(sectionFields(sec.id, true), sec.id === 'draw' ? renderGrids() : '');
  }
  // portée explicite de chaque réinitialisation
  if(sec.resets && sec.resets.length){
    body += `<div class="settings__actions">` + sec.resets.map(([s, lab]) =>
      `<button type="button" class="btn btn--ghost btn--sm" data-reset-sec="${esc(s)}" data-reset-label="${esc(lab())}">${icon('undo')}<span>${esc(plain(t('settings.reset.btn', {scope: lab()})))}</span></button>`).join('') + `</div>`;
  }
  pane.innerHTML = body;
  bindPane(pane);
  if(sec.id === 'about') wireUpdate(pane);
  pane.scrollTop = top;
}
// branchements communs d'un contenu du panneau (section ou résultats de recherche)
function bindPane(pane){
  bindFields(pane); bindHotkeys(pane); bindGrids(pane); bindMultiDiag(pane); bindTheme(pane); bindProtocol(pane);
  pane.querySelectorAll('.disclosure[id^="settingsAdv"]').forEach(adv => { adv.ontoggle = () => { SET.advOpen = adv.open; }; });
  const so = pane.querySelector('#sOpenSongs'); if(so) so.onclick = () => api('open_songs_folder');
  const cs = pane.querySelector('#sCopySongs'); if(cs) cs.onclick = () => copyText((SET.sch || {}).songs_folder || '', t('settings.storage.path_copied'));
  const cd = pane.querySelector('#sCopyData'); if(cd) cd.onclick = () => copyText((SET.sch || {}).data_dir || '', t('settings.storage.path_copied'));
  pane.querySelectorAll('#sOpenData,#sOpenData2').forEach(b => b.onclick = () => api('open_data_folder'));
  const rep = pane.querySelector('#sReport');
  if(rep) rep.onclick = () => { closeSettings(); openDiagReport($('btnSettings')); };
  pane.querySelectorAll('[data-log]').forEach(b => b.onclick = () => api('open_log', b.dataset.log));
  pane.querySelectorAll('[data-site]').forEach(b => b.onclick = () => api('open_site', b.dataset.site));
  pane.querySelectorAll('[data-reset-sec]').forEach(b => b.onclick = () => resetSection(b.dataset.resetSec, b.dataset.resetLabel));
}
function resetScope(section){
  return section === 'lecture' ? t('settings.reset_scope.lecture') : section === 'multi' ? t('settings.reset_scope.multi')
    : section === 'hotkeys' ? t('settings.reset_scope.hotkeys') : section === 'draw' ? t('settings.reset_scope.draw')
    : section === 'cook' ? t('settings.reset_scope.cook') : section === 'online' ? t('settings.reset_scope.online')
    : section === 'grids' ? t('settings.reset_scope.grids') : '';
}
function resetSection(section, label){
  dialog({title: t('settings.reset.title'), icon: 'undo', ok: t('settings.reset.title'),
    html: `<p>${t('settings.reset.confirm', {scope: esc(label)})}</p><small>${esc(resetScope(section))}</small>`
  }).then(ok => {
    if(!ok) return;
    api('reset_settings', section).then(r => {
      if(r && r.ok === false){ toast(r.error && r.error.key ? t(r.error.key, r.error.params || {}) : (r.error || t('settings.reset.failed')), 'warn'); return; }
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
  nav.innerHTML = SETTINGS_SECTIONS.map(s => `<button type="button" data-section="${s.id}" class="${s.id === SET.section ? 'active' : ''}">${icon(s.ic)}<span>${esc(s.label())}</span></button>`).join('');
  nav.querySelectorAll('button').forEach(b => b.onclick = () => { settingsSearchSet(''); renderSection(b.dataset.section); });
}

// ------------------------------------------------ ouverture / fermeture
function openSettings(schema, section){
  const go = sch => {
    if(!sch || !sch.fields) return;
    SET.sch = sch; SET.lastSent = {};
    // ouverture sur la section demandée, sinon toujours sur « Musique et audio »
    SET.section = section && SETTINGS_SECTIONS.some(s => s.id === section) ? section : SETTINGS_SECTIONS[0].id;
    SET.proto = null;
    settingsSearchSet('');
    buildNav(); renderSection(SET.section);
    if(!settingsOpen()) openModal($('overlay'), $('btnSettings'), () => { hotkeyCancel(); flushPending(); }, closeSettings);
    setTimeout(() => { const b = $('settingsNav').querySelector('button.active'); if(b) b.focus(); }, 30);
  };
  if(schema) go(schema); else api('get_settings_schema').then(go);
}
function closeSettings(){
  if(!settingsOpen()) return;
  closeModal($('overlay'));
}
$('btnSettings').onclick = () => openSettings();
$('btnSettingsClose').onclick = closeSettings;
$('overlay').onclick = e => { if(e.target === $('overlay')) closeSettings(); };
