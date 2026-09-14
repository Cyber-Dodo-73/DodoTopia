// DodoTopia : onglet Image (import, pixellisation sur la palette du jeu, dessin dans le jeu, calibrage).
// ------------------------------------------------ page Image : import
const IMG = {name: null, img: null, w: 0, h: 0};
let PIX = null;   // resultat : {w, h, cells: Int16Array (index palette du jeu ou -1 = vide), palette, counts, format}
const IOPT = {format: 'auto', fit: 'contain', colors: 126, dither: false, bright: 0, contrast: 0, sat: 100, grid: true};
const FORMATS = ['16:9', '4:3', '1:1', '3:4', '9:16'];
const DEFAULT_GRIDS = {'16:9': [140, 84], '4:3': [150, 114], '1:1': [150, 150], '3:4': [114, 150], '9:16': [84, 150]};
// Nuances du jeu : chaque pastille de la palette ouvre 10 nuances (6 pour le noir). [pastille, [nuances]]
const SHADE_FAMILIES = [
  [0, [[5,22,22],[65,69,69],[128,130,130],[190,191,191],[254,255,255],[249,246,236]]],
  [4, [[207,53,77],[238,111,114],[166,38,61],[245,172,166],[201,132,131],[163,93,94],[105,49,59],[231,213,213],[192,172,171],[117,94,94]]],
  [5, [[233,94,43],[249,131,88],[171,66,38],[254,186,159],[217,147,124],[175,108,88],[117,59,49],[233,213,208],[193,172,166],[117,94,89]]],
  [6, [[244,158,22],[254,174,59],[177,111,22],[254,206,146],[218,167,109],[179,129,75],[121,81,38],[245,228,206],[205,188,169],[128,111,94]]],
  [7, [[237,202,22],[249,216,56],[179,148,22],[250,231,145],[211,190,111],[171,149,75],[117,99,38],[238,231,199],[198,191,162],[120,114,89]]],
  [8, [[168,188,22],[182,201,49],[117,134,22],[216,223,147],[173,183,109],[133,145,75],[83,94,43],[230,233,199],[188,194,163],[110,116,93]]],
  [9, [[5,162,93],[65,185,123],[5,116,71],[156,218,173],[118,178,139],[79,137,105],[36,86,64],[195,224,204],[157,183,166],[83,105,93]]],
  [10, [[5,135,129],[5,171,160],[5,105,102],[126,205,194],[85,164,156],[43,126,120],[5,75,75],[190,224,218],[152,183,178],[78,107,102]]],
  [11, [[5,114,156],[5,153,186],[5,88,120],[121,187,202],[81,147,165],[36,109,127],[5,73,91],[198,221,226],[158,181,186],[79,103,111]]],
  [12, [[5,94,166],[43,131,193],[5,71,130],[131,168,201],[93,128,161],[54,91,127],[25,59,86],[193,205,213],[155,166,176],[76,89,103]]],
  [13, [[83,77,161],[117,119,189],[62,56,126],[162,160,199],[120,122,161],[85,86,126],[51,53,85],[201,202,213],[162,163,176],[86,88,105]]],
  [14, [[129,61,139],[161,103,169],[96,43,108],[184,155,185],[144,115,149],[108,77,115],[67,46,75],[207,201,209],[171,161,172],[96,86,101]]],
  [15, [[173,53,111],[207,107,143],[134,38,88],[217,161,180],[180,122,140],[139,83,103],[96,53,75],[228,213,218],[188,173,177],[114,94,102]]],
];
const DEFAULT_PALETTE = SHADE_FAMILIES.flatMap(([, cs]) => cs);
// pastille de la palette principale equivalente a chaque nuance (-1 : aucune) : blanc, gris et creme sont des nuances du noir
const DEFAULT_MAIN = SHADE_FAMILIES.flatMap(([f, cs]) => cs.map((c, j) => f === 0 ? ({0: 0, 4: 1, 2: 2, 5: 3}[j] ?? -1) : (j === 1 ? f : -1)));
const IMAGE_EXT = /\.(png|jpe?g|gif|bmp|webp)$/i;

function drawState(){ return (S && S.draw) ? S.draw : null; }
function gamePalette(){ const d = drawState(); return (d && d.palette && d.palette.length === DEFAULT_PALETTE.length) ? d.palette : DEFAULT_PALETTE; }
function shadesOk(){ const d = drawState(); return !d || !!d.shades_ok; }
// l'apercu utilise toujours les 126 nuances ; le dessin exige que les nuances soient calibrees (shadesOk)

function gridFor(fmt){ const d = drawState(); const f = d && d.formats && d.formats[fmt]; return f ? [f.cols, f.rows] : DEFAULT_GRIDS[fmt]; }
function isCalibrated(fmt){ const d = drawState(); return !!(d && d.formats && d.formats[fmt] && d.formats[fmt].calibrated); }
function ratioOf(fmt){ const [a, b] = fmt.split(':').map(Number); return a / b; }
function currentFormat(){
  if(IOPT.format !== 'auto') return IOPT.format;
  if(!IMG.img) return '16:9';
  const r = IMG.w / IMG.h;
  return FORMATS.reduce((best, f) => Math.abs(Math.log(ratioOf(f) / r)) < Math.abs(Math.log(ratioOf(best) / r)) ? f : best, '16:9');
}

function loadImageData(payload){
  /* appele par Python (dialogue ou glisser-deposer) ou par le fallback navigateur */
  if(!payload || !payload.data) return;
  const img = new Image();
  img.onload = () => {
    IMG.name = payload.name || 'image'; IMG.img = img; IMG.w = img.naturalWidth; IMG.h = img.naturalHeight;
    $('thumbImg').src = payload.data; $('thumb').classList.add('has');
    $('thumbDim').textContent = IMG.w + ' × ' + IMG.h + ' px';
    showTab('image');
    renderPixels();
  };
  img.onerror = () => toast("Impossible de lire cette image", 'warn');
  img.src = payload.data;
}
window.loadImageData = loadImageData;

$('btnImportImg').onclick = () => {
  if(window.pywebview){ window.pywebview.api.import_image_dialog().then(r => { if(r) loadImageData(r); }); }
  else { $('fileImg').click(); }
};
$('fileImg').onchange = e => { const f = e.target.files[0]; if(f) readLocalImage(f); e.target.value = ''; };
function readLocalImage(file){
  const rd = new FileReader();
  rd.onload = () => loadImageData({name: file.name.replace(/\.[^.]+$/, ''), data: rd.result});
  rd.readAsDataURL(file);
}

// ------------------------------------------------ page Image : pixellisation sur la palette du jeu
// comparaison des couleurs dans l'espace CIELAB (perceptuel) : une distance RGB envoie toutes les teintes
// ternes (peau, bois, murs beiges) sur le gris.
function rgb2lab(c){
  const f = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const r = f(c[0]), g = f(c[1]), b = f(c[2]);
  const x = (r*0.4124 + g*0.3576 + b*0.1805) / 0.95047, y = r*0.2126 + g*0.7152 + b*0.0722, z = (r*0.0193 + g*0.1192 + b*0.9505) / 1.08883;
  const h = t => t > 0.008856 ? Math.cbrt(t) : 7.787*t + 16/116;
  const fx = h(x), fy = h(y), fz = h(z);
  return [116*fy - 16, 500*(fx - fy), 200*(fy - fz)];
}
function toLab(p){ const l = rgb2lab(p); const s = IOPT.sat / 100; l[1] *= s; l[2] *= s; return l; }
function nearest(lab, plab, allowed){
  let bi = -1, bd = Infinity;
  for(let i = 0; i < plab.length; i++){
    if(allowed && !allowed[i]) continue;
    const q = plab[i], dl = lab[0]-q[0], da = lab[1]-q[1], db = lab[2]-q[2];
    const d = dl*dl + da*da + db*db; if(d < bd){ bd = d; bi = i; }
  }
  return bi;
}
function hex(c){ return '#' + c.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join(''); }

function computePixels(){
  if(!IMG.img) return null;
  const fmt = currentFormat();
  const [W, H] = gridFor(fmt);
  // cadrage de l'image dans la grille (cases carrees)
  const ir = IMG.w / IMG.h, gr = W / H;
  let dw, dh;
  if(IOPT.fit === 'contain'){ if(ir > gr){ dw = W; dh = W / ir; } else { dh = H; dw = H * ir; } }
  else { if(ir > gr){ dh = H; dw = H * ir; } else { dw = W; dh = W / ir; } }
  const dx = (W - dw) / 2, dy = (H - dh) / 2;
  // reduction progressive pour un bon moyennage
  let src = IMG.img, sw = IMG.w, sh = IMG.h;
  while(sw > dw * 2 && sh > dh * 2){
    const c = document.createElement('canvas'); c.width = Math.ceil(sw / 2); c.height = Math.ceil(sh / 2);
    const cc = c.getContext('2d'); cc.imageSmoothingEnabled = true; cc.imageSmoothingQuality = 'high';
    cc.drawImage(src, 0, 0, c.width, c.height); src = c; sw = c.width; sh = c.height;
  }
  const off = document.createElement('canvas'); off.width = W; off.height = H;
  const ctx = off.getContext('2d', {willReadFrequently: true});
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(src, dx, dy, dw, dh);
  const d = ctx.getImageData(0, 0, W, H).data;
  const k = (259 * (IOPT.contrast + 255)) / (255 * (259 - IOPT.contrast));
  const buf = new Float32Array(W * H * 3), alive = new Uint8Array(W * H);
  for(let i = 0; i < W * H; i++){
    if(d[i*4+3] < 128) continue;
    alive[i] = 1;
    for(let c = 0; c < 3; c++){
      let v = d[i*4+c]; v = k * (v - 128) + 128 + IOPT.bright;
      buf[i*3+c] = Math.max(0, Math.min(255, v));
    }
  }
  const palette = gamePalette();
  const plab = palette.map(rgb2lab);
  const cells = new Int16Array(W * H).fill(-1);
  const counts = palette.map(() => 0);
  // nuances non calibrees : seules les 16 pastilles principales sont utilisables
  let allowed = null;
  // 1re passe : couleurs les plus utiles, pour limiter le nombre de couleurs
  const avail = allowed ? allowed.filter(Boolean).length : palette.length;
  if(IOPT.colors < avail){
    const pre = palette.map(() => 0);
    for(let i = 0; i < W * H; i++){ if(alive[i]) pre[nearest(toLab([buf[i*3], buf[i*3+1], buf[i*3+2]]), plab, allowed)]++; }
    const keep = pre.map((n, i) => i).filter(i => pre[i] > 0).sort((a, b) => pre[b] - pre[a]).slice(0, IOPT.colors);
    allowed = palette.map(() => false); keep.forEach(i => allowed[i] = true);
  }
  // 2e passe : attribution (avec tramage si demande)
  const work = IOPT.dither ? Float32Array.from(buf) : buf;
  for(let y = 0; y < H; y++) for(let x = 0; x < W; x++){
    const i = y * W + x;
    if(!alive[i]) continue;
    const p = [work[i*3], work[i*3+1], work[i*3+2]];
    const ki = nearest(toLab(p), plab, allowed);
    cells[i] = ki; counts[ki]++;
    if(IOPT.dither){
      const q = palette[ki];
      const err = [p[0]-q[0], p[1]-q[1], p[2]-q[2]];
      const spread = (ddx, ddy, f) => {
        const nx = x + ddx, ny = y + ddy;
        if(nx < 0 || nx >= W || ny >= H) return;
        const j = ny * W + nx; if(!alive[j]) return;
        for(let c = 0; c < 3; c++) work[j*3+c] = Math.max(0, Math.min(255, work[j*3+c] + err[c] * f));
      };
      spread(1, 0, 7/16); spread(-1, 1, 3/16); spread(0, 1, 5/16); spread(1, 1, 1/16);
    }
  }
  return {w: W, h: H, cells, palette, counts, format: fmt};
}

function renderPixels(){
  const wrap = $('canvasWrap');
  syncFormatChips();
  if(!IMG.img){
    wrap.classList.remove('has'); PIX = null;
    $('imgTitle').textContent = 'Aucune image';
    $('imgSub').textContent = 'Importe une image pour voir le rendu en jeu';
    $('imgStats').innerHTML = ''; $('swatches').innerHTML = '<span class="none">—</span>';
    if(S) renderDraw(S);
    return;
  }
  PIX = computePixels();
  const {w, h, cells, palette, counts, format} = PIX;
  const cw = Math.max(40, wrap.clientWidth - 24), ch = Math.max(40, wrap.clientHeight - 24);
  const cell = Math.max(1, Math.floor(Math.min(cw / w, ch / h)));
  const cv = $('pixCanvas'); cv.width = w * cell; cv.height = h * cell;
  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);
  for(let y = 0; y < h; y++) for(let x = 0; x < w; x++){
    const k = cells[y * w + x]; if(k < 0) continue;
    ctx.fillStyle = hex(palette[k]); ctx.fillRect(x * cell, y * cell, cell, cell);
  }
  if(IOPT.grid && cell >= 4){
    ctx.strokeStyle = 'rgba(60,40,30,.18)'; ctx.lineWidth = 1;
    ctx.beginPath();
    for(let x = 0; x <= w; x++){ ctx.moveTo(x * cell + .5, 0); ctx.lineTo(x * cell + .5, cv.height); }
    for(let y = 0; y <= h; y++){ ctx.moveTo(0, y * cell + .5); ctx.lineTo(cv.width, y * cell + .5); }
    ctx.stroke();
  }
  wrap.classList.add('has');
  const painted = counts.reduce((a, b) => a + b, 0), empty = w * h - painted;
  const used = counts.filter(n => n > 0).length;
  $('imgTitle').textContent = IMG.name;
  $('imgSub').innerHTML = `Source <b>${IMG.w} × ${IMG.h}</b> px · format <b>${format}</b> · <b>${w} × ${h}</b> cases`;
  $('imgStats').innerHTML = [
    `<span class="stat">📐 <b>${w} × ${h}</b> cases</span>`,
    `<span class="stat">🖌️ <b>${painted}</b> à peindre</span>`,
    empty ? `<span class="stat">⬜ <b>${empty}</b> vides</span>` : '',
    `<span class="stat">🎨 <b>${used}</b> couleur${used > 1 ? 's' : ''}</span>`,
  ].join('');
  const order = palette.map((c, i) => i).filter(i => counts[i] > 0).sort((a, b) => counts[b] - counts[a]);
  $('swatches').innerHTML = order.map(i => `<span class="sw" title="${hex(palette[i])}"><i style="background:${hex(palette[i])}"></i>${counts[i]}</span>`).join('') || '<span class="none">—</span>';
  if(S) renderDraw(S);
  pushJob();
}

let jobTimer;
function pushJob(){
  clearTimeout(jobTimer);
  jobTimer = setTimeout(() => {
    if(!PIX) return;
    api('set_draw_job', {format: PIX.format, w: PIX.w, h: PIX.h, cells: Array.from(PIX.cells)});
  }, 250);
}

let pixTimer;
function schedulePixels(){ clearTimeout(pixTimer); pixTimer = setTimeout(renderPixels, 60); }
function bindOpt(id, key, fmtv){
  const el = $(id), v = $(id + 'V');
  el.oninput = () => { IOPT[key] = Number(el.value); v.textContent = fmtv ? fmtv(IOPT[key]) : el.value; schedulePixels(); };
}
bindOpt('optColors', 'colors', v => v >= 126 ? 'toutes' : v);
bindOpt('optBright', 'bright', v => (v > 0 ? '+' : '') + v); bindOpt('optContrast', 'contrast', v => (v > 0 ? '+' : '') + v);
bindOpt('optSat', 'sat', v => v + ' %');
$('optDither').onchange = () => { IOPT.dither = $('optDither').checked; schedulePixels(); };
$('optGrid').onchange = () => { IOPT.grid = $('optGrid').checked; schedulePixels(); };
function syncFormatChips(){
  const cur = currentFormat();
  segMark($('formats'), c => c.dataset.f === IOPT.format);
  document.querySelectorAll('#formats > button').forEach(c => {
    const f = c.dataset.f;
    if(f === 'auto'){ c.textContent = IMG.img ? `Auto (${cur})` : 'Auto'; }
    else {
      const [gw, gh] = gridFor(f); const d = drawState(); const val = !!(d && d.validated && d.validated[f]);
      c.innerHTML = `${f}${val ? '<span class="ok">✓✓</span>' : isCalibrated(f) ? '<span class="ok">✓</span>' : ''}`;
      c.title = `${gw} × ${gh} cases` + (val ? ' · calibrage auto validé' : isCalibrated(f) ? ' · calibré à la main (lance le calibrage auto)' : ' · pas encore calibré');
    }
  });
  segMark($('fits'), c => c.dataset.fit === IOPT.fit);
}
document.querySelectorAll('#formats > button').forEach(c => c.onclick = () => { IOPT.format = c.dataset.f; schedulePixels(); });
document.querySelectorAll('#fits > button').forEach(c => c.onclick = () => { IOPT.fit = c.dataset.fit; schedulePixels(); });
window.addEventListener('resize', () => { if(TAB === 'image') schedulePixels(); });

// ------------------------------------------------ page Image : dessin dans le jeu + calibrage
let drawSig = '';
// prochaine etape du dessin pour le format courant : calib | valid | draw
function drawNext(fmt){
  const d = drawState();
  if(!isCalibrated(fmt) || !shadesOk()) return 'calib';
  if(!(d && d.validated && d.validated[fmt])) return 'valid';
  return 'draw';
}
function renderDraw(st){
  const d = st.draw; if(!d) return;
  const hk = st.hotkeys || {};
  const fmt = currentFormat();
  const drawing = d.state === 'drawing', calib = d.state === 'calibrating', auto = d.state === 'autocal';
  const busy = drawing || auto;
  const next = drawNext(fmt);
  const validated = !!(d.validated && d.validated[fmt]);

  // stepper (1) Calibrer (2) Valider (3) Dessiner
  const done = [];
  if(isCalibrated(fmt) && shadesOk()) done.push('calib');
  if(validated) done.push('valid');
  stepsMark($('drawSteps'), done, busy ? (auto ? 'valid' : 'draw') : next, {calib: done.includes('calib') ? fmt : '', valid: validated ? '✓✓' : ''});

  // un seul bouton principal = prochaine etape
  const b = $('btnDraw');
  let label, cls = 'btn btn--lg btn--cta';
  if(busy){ label = auto ? 'Arrêter le calibrage auto' : 'Arrêter le dessin'; cls = 'btn btn--lg btn--danger'; }
  else if(!IMG.img) label = LABELS.draw;
  else if(next === 'calib') label = `Calibrer ${fmt}`;
  else if(next === 'valid') label = 'Valider (calibrage auto)';
  else label = LABELS.draw;
  if(b.className !== cls) b.className = cls;
  txt('drawLabel', label);
  txt('drawKey', busy ? (hk.stop || 'F7') : (hk.play_pause || 'F6'));
  $('drawKey').hidden = !busy && next !== 'draw';
  b.disabled = calib || (!busy && !IMG.img);
  $('btnDrawMore').disabled = busy || calib;
  $('drawSteps').hidden = busy;

  const pill = $('imgPill');
  let pc = 'pill', pt = 'Prêt';
  if(drawing){ pc = 'pill game'; pt = '🎨 Dessin en cours'; }
  else if(calib){ pc = 'pill paused'; pt = '🎯 Calibrage'; }
  else if(auto){ pc = 'pill game'; pt = '🧪 Calibrage auto'; }
  else if(PIX){ pc = 'pill preview'; pt = '🧩 Aperçu'; }
  if(pill.className !== pc) pill.className = pc;
  txt('imgPill', pt);
  $('imgDisc').classList.toggle('spin', drawing);

  // bandeau de session : compte a rebours puis progression
  let spec = null;
  if(busy && d.countdown > 0){
    spec = {count: Math.ceil(d.countdown), unit: 's', role: auto ? 'Calibrage auto' : 'Dessin',
            text: auto ? `Passe sur Heartopia avec un dessin VIDE au format ${d.format}, crayon sélectionné, zoom au minimum.` : 'Passe sur Heartopia, crayon sélectionné, et ne touche plus à rien.',
            meta: `${hk.stop || 'F7'} annule`, actions: [{label: LABELS.cancel, kbd: hk.stop || 'F7', api: 'draw_stop'}]};
  } else if(drawing){
    const pct = d.total ? d.done / d.total * 100 : 0;
    spec = {live: true, role: 'Dessin dans Heartopia', text: d.progress_msg || 'Dessin en cours…',
            meta: `${d.done} / ${d.total} · ${d.eta != null ? 'reste ~' + fmtDur(d.eta) : fmtDur(d.elapsed)} · ${hk.stop || 'F7'} arrête · ne touche pas à la souris`,
            progress: {pct, left: `${Math.round(pct)} %`, right: d.eta != null ? `~${fmtDur(d.eta)}` : fmtDur(d.elapsed)},
            actions: [{label: LABELS.stop, kbd: hk.stop || 'F7', api: 'draw_stop'}]};
  } else if(auto){
    spec = {live: true, role: 'Calibrage automatique', text: d.progress_msg || 'Mesure en cours…', meta: `${hk.stop || 'F7'} ou une touche arrête`,
            actions: [{label: LABELS.stop, kbd: hk.stop || 'F7', api: 'draw_stop'}]};
  }
  renderSession($('drawSession'), spec);

  // notice courte
  let notice = null;
  if(!busy){
    if(d.message && /impossible|arrêté|erreur/i.test(d.message)) notice = {text: d.message, kind: 'warn'};
    else if(!IMG.img) notice = {text: 'Importe une image : DodoTopia la transforme en dessin case par case.', kind: 'info'};
    else if(!isCalibrated(fmt)) notice = {text: `Format ${fmt} pas encore calibré : indique où sont le canevas et la palette dans le jeu.`, kind: 'warn'};
    else if(!shadesOk()) notice = {text: 'Les nuances de la palette ne sont pas calibrées : refais les 6 étapes « nuances » (Autres… › Recalibrer).', kind: 'warn'};
    else if(!validated) notice = {text: `Calibré à la main. Lance le calibrage auto une fois (dessin vide dans le jeu) pour mesurer et valider.`, kind: 'info'};
    else notice = {text: `Ouvre un dessin vide dans Heartopia (format ${fmt}, finesse au maximum, crayon), puis ${hk.play_pause || 'F6'}.`, kind: 'ok', icon: '✓'};
  }
  setNotice('drawNotice', notice);

  // bloc Methode (colonne de gauche) : contours + pot, fond, blanc — valeurs de settings.draw
  const sd = (st.settings && st.settings.draw) || d.settings || {};
  [['mOutline', 'outline'], ['mFill', 'fill_background'], ['mSkipWhite', 'skip_white']].forEach(([id, k]) => {
    const cb = $(id); if(cb && document.activeElement !== cb && cb.checked !== !!sd[k]) cb.checked = !!sd[k];
  });
  const os = st.draw_stats;
  const outlineOn = sd.outline !== false;
  let ostat = '';
  if(!outlineOn) ostat = 'Tout au crayon, case par case.';
  else if(!PIX) ostat = 'Trace les contours de chaque zone puis la remplit d’un clic.';
  else if(!os) ostat = 'Calcul des zones…';
  else if(os.available) ostat = `✏️ ${os.pencil_cells} cases au crayon + 🪣 ${os.fill_zones} zone${os.fill_zones > 1 ? 's' : ''} au pot (${os.fill_cells} cases) au lieu de ${os.total_cells} au crayon.`;
  else ostat = 'Indisponible : calibre le crayon et le pot de peinture.';
  txt('outlineStat', ostat);

  // assistant de calibrage
  if(calib){
    renderCalibOverlay({
      title: `Calibrer le dessin <span class="fmt">${esc(d.format)}</span>`,
      intro: `Dans Heartopia, ouvre un dessin au format <b>${esc(d.format)}</b>, mets la <b>finesse des détails au maximum</b> et <b>active la grille</b> (bouton grille en haut du canevas). Puis, pour chaque étape, place la souris sur la cible <b>dans le jeu</b> et appuie sur <kbd>${esc(hk.draw_point || 'F3')}</kbd>.`,
      steps: d.steps || [], step: d.step, hk,
      skippable: s => s.key === 'pencil' || s.key === 'bucket' || s.key === 'undo',
      cancel: 'draw_calibrate_cancel', skip: 'draw_calibrate_skip'});
  } else if(!(st.cook && st.cook.state === 'calibrating')){
    $('calibOverlay').classList.remove('open');
  }
  // palette ou grilles changees (fin de calibrage) : on recalcule l'apercu
  const sig = JSON.stringify([d.palette, d.formats, d.shades_ok]);
  if(sig !== drawSig){ drawSig = sig; if(IMG.img) schedulePixels(); else syncFormatChips(); }
}
view('draw', {draw: renderDraw});
let CALIB = {cancel: 'draw_calibrate_cancel', skip: 'draw_calibrate_skip'};
function renderCalibOverlay(spec){
  CALIB = spec;
  $('calibTitle').innerHTML = spec.title;
  $('calibIntro').innerHTML = spec.intro;
  const steps = spec.steps || [];
  $('calibSteps').innerHTML = steps.map((s, i) => `<li class="${i < spec.step ? 'done' : i === spec.step ? 'now' : ''}"><span class="n">${i < spec.step ? '✓' : i + 1}</span>${esc(s.title)}</li>`).join('');
  const cur = steps[spec.step];
  const hk = spec.hk || {};
  if(cur) $('calibNow').innerHTML = `<b>Étape ${spec.step + 1} / ${steps.length}</b> · ${esc(cur.help)}<br>Puis appuie sur <kbd>${esc(hk.draw_point || 'F3')}</kbd> (ou sur ${esc(hk.play_pause || 'F6')}).`;
  $('calibSkip').hidden = !(cur && spec.skippable(cur));
  $('calibOverlay').classList.add('open');
  const now = $('calibSteps').querySelector('li.now'); if(now && now.scrollIntoView) now.scrollIntoView({block: 'nearest'});
}
function fmtDur(s){ s = Math.max(0, Math.round(s || 0)); return s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s` : `${s} s`; }

// ------------------------------------------------ actions
function drawCalibrate(){ api('draw_calibrate', currentFormat()); }
function drawAutoCalibrate(){
  if(!isCalibrated(currentFormat())){ drawCalibrate(); return; }
  dialog({title: 'Calibrage automatique', icon: '🧪', ok: 'Lancer',
          html: `Dans Heartopia, ouvre un dessin <b>vide</b> au format <b>${currentFormat()}</b>, finesse au maximum, crayon sélectionné, zoom au minimum.<br><small>DodoTopia va remplir le fond, peindre des pastilles et des repères, mesurer l'écran, tester le rythme des traits, puis valider. Le canevas de test sera annulé si le bouton Annuler est calibré, sinon ouvre un nouveau dessin ensuite.</small>`})
    .then(yes => { if(yes) api('draw_auto_calibrate', currentFormat()); });
}
function drawStart(){
  dialog({title: LABELS.draw, icon: '🎨', ok: 'Dessiner',
          html: `Dans Heartopia, ouvre un dessin au format <b>${currentFormat()}</b>, finesse des détails <b>au maximum</b>, outil crayon sélectionné, sans zoom.<br><small>Le dessin démarre 3 s après : ne touche plus à la souris ni au clavier. Toute touche l'arrête.</small>`})
    .then(yes => { if(yes) api('draw_start'); });
}
$('btnDraw').onclick = () => {
  const d = drawState();
  if(d && (d.state === 'drawing' || d.state === 'autocal')){ api('draw_stop'); return; }
  if(!IMG.img){ toast("Importe d'abord une image", 'warn'); return; }
  const next = drawNext(currentFormat());
  if(next === 'calib') drawCalibrate();
  else if(next === 'valid') drawAutoCalibrate();
  else drawStart();
};
$('btnDrawMore').onclick = () => {
  const fmt = currentFormat(), cal = isCalibrated(fmt), d = drawState();
  menu($('btnDrawMore'), [
    {label: cal ? `Recalibrer ${fmt} à la main` : `Calibrer ${fmt} à la main`, help: 'canevas, palette, nuances', fn: drawCalibrate},
    {label: 'Calibrage auto (mesure et valide)', help: 'dessin vide dans le jeu', fn: drawAutoCalibrate, disabled: !cal},
    {label: 'Dessiner sans valider', help: (d && d.validated && d.validated[fmt]) ? '' : 'déconseillé', fn: drawStart, disabled: !cal || !IMG.img},
    {label: 'Journal du dessin', fn: () => api('open_draw_log')},
  ]);
};
$('calibCancel').onclick = $('calibCancel2').onclick = () => api(CALIB.cancel);
$('calibSkip').onclick = () => api(CALIB.skip);
// bloc Methode : interrupteurs -> set_setting (sans toast)
['mOutline', 'mFill', 'mSkipWhite'].forEach(id => { const cb = $(id); cb.onchange = () => api('set_setting', cb.dataset.path, cb.checked); });
