// DodoTopia : activite Dessin (import, pixellisation sur la palette du jeu, dessin dans le jeu,
// configuration de la zone du jeu). L'assistant de configuration (renderCalibOverlay) est partage
// avec la Cuisine : une etape active dominante, un schema qui designe la cible, un recapitulatif replie.
// ------------------------------------------------ activite Dessin : import
// job : grille déjà convertie {format, w, h, cells} reprise de la galerie (pas d'image source) ; source : {id} du dessin
const IMG = {name: null, img: null, w: 0, h: 0, job: null, source: null};
function hasPic(){ return !!(IMG.img || IMG.job); }
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
  if(IMG.job) return FORMATS.includes(IMG.job.format) ? IMG.job.format : '16:9';
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
    IMG.name = payload.name || t('image.import.default_name'); IMG.img = img; IMG.w = img.naturalWidth; IMG.h = img.naturalHeight;
    IMG.job = null; IMG.source = null; DSHARE.upSeq = null;
    showTab('image');
    renderPixels();
  };
  img.onerror = () => toast(t('image.import.read_error'), 'warn');
  img.src = payload.data;
}
window.loadImageData = loadImageData;

function pickImage(){
  if(window.pywebview){ window.pywebview.api.import_image_dialog().then(r => { if(r) loadImageData(r); }); }
  else { $('fileImg').click(); }
}
$('btnImportImg').onclick = pickImage;
$('btnImportImgBig').onclick = pickImage;
$('fileImg').onchange = e => { const f = e.target.files[0]; if(f) readLocalImage(f); e.target.value = ''; };
function readLocalImage(file){
  const rd = new FileReader();
  rd.onload = () => loadImageData({name: file.name.replace(/\.[^.]+$/, ''), data: rd.result});
  rd.readAsDataURL(file);
}

// ------------------------------------------------ pixellisation sur la palette du jeu
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

// grille reprise de la galerie : les cases sont déjà des indices de la palette du jeu
function gridPixels(){
  const job = IMG.job, palette = gamePalette();
  const cells = new Int16Array(job.w * job.h).fill(-1);
  const counts = palette.map(() => 0);
  for(let i = 0; i < cells.length; i++){
    const k = Number(job.cells[i]);
    if(k >= 0 && k < palette.length){ cells[i] = k; counts[k]++; }
  }
  return {w: job.w, h: job.h, cells, palette, counts, format: currentFormat()};
}
function computePixels(){
  if(IMG.job) return gridPixels();
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
  // état vide : une seule zone d'import domine la page, les réglages restent masqués
  $('drawEmpty').hidden = hasPic();
  $('drawWork').hidden = !hasPic();
  $('drawOpts').hidden = !hasPic();
  $('drawOpts').classList.toggle('is-grid', !!IMG.job);
  $('drawMain').classList.toggle('is-empty', !hasPic());
  $('pageImage').classList.toggle('is-empty', !hasPic() && !GAL.open);
  $('drawShare').hidden = !hasPic();
  txt('drawHeadTitle', hasPic() ? t('image.import.head_title') : t('image.import.head_title_empty'));
  if(!hasPic()){
    wrap.classList.remove('has'); PIX = null;
    $('imgTitle').textContent = t('image.import.none_title');
    $('imgSub').textContent = t('image.import.none_sub');
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
  const sd = (S && S.settings && S.settings.draw) || {};
  const fills = sd.fill_background !== false;     // défaut du moteur : le fond est rempli au pot
  // Un nom qui ressemble à un identifiant technique ne fait pas un titre : on garde le fichier en détail.
  const human = /[aeiouyàâéèêëîïôöùûü]/i.test(IMG.name) && !/^[A-Z0-9][A-Z0-9 _-]{5,}$/.test(IMG.name);
  $('imgTitle').textContent = human ? IMG.name : t('image.import.my_drawing');
  $('imgTitle').title = IMG.name;
  // les messages *_html ne portent que du balisage sur et des nombres ; le nom du fichier passe par esc()
  $('imgSub').innerHTML = IMG.job
    ? esc(t('image.gallery.grid_sub', {format, w, h}))
    : `${human ? '' : esc(IMG.name) + ' · '}` + t('image.import.sub_html', {format, w, h, sw: IMG.w, sh: IMG.h});
  // grille de la galerie : ni cadrage ni couleurs à régler ; une grille d'une autre taille que la zone configurée
  // est dite tout de suite (le dessin serait décalé)
  const gn = $('gridNote');
  if(gn){
    gn.hidden = !IMG.job;
    if(IMG.job){
      const [gw, gh] = gridFor(format);
      txt('gridNote', gw === w && gh === h ? t('image.gallery.grid_note', {format}) : t('image.gallery.grid_mismatch', {format, w, h, gw, gh}));
    }
  }
  // « à peindre » ne vaut pas largeur × hauteur : les cases transparentes, et le blanc si « Ne pas peindre
  // le blanc » est coché, sont écartées par le moteur.
  const skipW = !!sd.skip_white;
  const whiteIdx = skipW ? palette.reduce((bi, c, i) => (c[0] + c[1] + c[2] > palette[bi][0] + palette[bi][1] + palette[bi][2] ? i : bi), 0) : -1;
  const whiteCells = whiteIdx >= 0 ? counts[whiteIdx] : 0;
  const colored = painted - whiteCells;
  $('imgStats').innerHTML = [
    `<span class="stat" title="${esc(t('image.import.stat_grid_title'))}">${icon('grid')}${plain(t('image.import.stat_grid_html', {w, h}))}</span>`,
    `<span class="stat" title="${esc(t('image.import.stat_colored_title'))}">${icon('brush')}${plain(t('image.import.stat_colored_html', {n: colored}))}</span>`,
    empty ? `<span class="stat" title="${esc(fills ? t('image.import.stat_empty_title_fill') : t('image.import.stat_empty_title_keep'))}">${icon('square')}${plain(t('image.import.stat_empty_html', {n: empty}))}</span>` : '',
    whiteCells ? `<span class="stat" title="${esc(t('image.import.stat_white_title'))}">${icon('square')}${plain(t('image.import.stat_white_html', {n: whiteCells}))}</span>` : '',
    `<span class="stat">${icon('palette')}${plain(t('image.import.stat_colors_html', {n: used}))}</span>`,
  ].filter(Boolean).join('');
  // le damier dit la vérité sur l'image, pas forcément sur le rendu en jeu
  const alpha = $('alphaNote');
  if(alpha){
    alpha.hidden = !empty;
    if(empty) txt('alphaNote', fills ? t('image.import.alpha_fill', {n: empty}) : t('image.import.alpha_keep', {n: empty}));
  }
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
    api('set_draw_job', {format: PIX.format, w: PIX.w, h: PIX.h, cells: Array.from(PIX.cells), name: IMG.name || ''});
  }, 250);
}

let pixTimer;
function schedulePixels(){ clearTimeout(pixTimer); pixTimer = setTimeout(renderPixels, 60); }
// valeurs affichees a cote des curseurs (resolues a chaque rendu : la langue peut changer)
const IOPT_FMT = {
  colors: v => v >= 126 ? t('image.settings.colors_all') : I18N.fmtNumber(v),
  bright: v => (v > 0 ? '+' : '') + I18N.fmtNumber(v),
  contrast: v => (v > 0 ? '+' : '') + I18N.fmtNumber(v),
  sat: v => t('image.settings.percent', {n: v}),
};
function bindOpt(id, key){
  const el = $(id), v = $(id + 'V');
  el.oninput = () => { IOPT[key] = Number(el.value); v.textContent = IOPT_FMT[key](IOPT[key]); schedulePixels(); };
}
bindOpt('optColors', 'colors');
bindOpt('optBright', 'bright'); bindOpt('optContrast', 'contrast');
bindOpt('optSat', 'sat');
function syncOptValues(){
  [['optColors', 'colors'], ['optBright', 'bright'], ['optContrast', 'contrast'], ['optSat', 'sat']].forEach(([id, k]) => {
    if($(id)){ $(id).value = IOPT[k]; txt(id + 'V', String(IOPT_FMT[k](IOPT[k]))); }
  });
}
$('optDither').onchange = () => { IOPT.dither = $('optDither').checked; schedulePixels(); };
$('optGrid').onchange = () => { IOPT.grid = $('optGrid').checked; schedulePixels(); };
function syncFormatChips(){
  const cur = currentFormat();
  segMark($('formats'), c => c.dataset.f === IOPT.format);
  document.querySelectorAll('#formats > button').forEach(c => {
    const f = c.dataset.f;
    // « Auto » montre le format réellement retenu : pas de sélection contradictoire
    // Une seule sélection : la puce ne porte QUE le format. L'état du calibrage est dit à part, sous le
    // groupe, pour ne pas mélanger « ce que je choisis » et « ce qui est déjà configuré ».
    if(f === 'auto'){ c.textContent = t('image.settings.format_auto'); c.title = t('image.settings.format_auto_help'); }
    else {
      const [gw, gh] = gridFor(f);
      c.textContent = f;
      c.title = t('image.settings.cells', {w: gw, h: gh});
    }
  });
  segMark($('fits'), c => c.dataset.fit === IOPT.fit);
  const [gw, gh] = gridFor(cur);
  txt('fmtHelp', hasPic()
    ? t('image.settings.format_help', {format: cur, w: gw, h: gh})
    : t('image.settings.format_help_empty'));
  // disponibilité du calibrage : une phrase séparée, jamais une coche dans la puce du format
  const cal = $('fmtCalib');
  if(cal){
    const d = drawState(); const val = !!(d && d.validated && d.validated[cur]);
    const ok = isCalibrated(cur);
    cal.className = 'hint left fmtcalib ' + (ok ? 'is-ok' : 'is-todo');
    txt('fmtCalib', !ok ? t('image.settings.calib_todo', {format: cur})
      : val ? t('image.settings.calib_ok_measured', {format: cur})
      : t('image.settings.calib_ok', {format: cur}));
  }
  txt('fitHelp', IOPT.fit === 'contain' ? t('image.settings.fit_contain') : t('image.settings.fit_cover'));
  syncOptValues();
}
document.querySelectorAll('#formats > button').forEach(c => c.onclick = () => { IOPT.format = c.dataset.f; schedulePixels(); });
document.querySelectorAll('#fits > button').forEach(c => c.onclick = () => { IOPT.fit = c.dataset.fit; schedulePixels(); });
window.addEventListener('resize', () => { if(TAB === 'image') schedulePixels(); });

// remise à zéro par groupe de réglages (aperçu seulement : rien n'est écrit côté Python)
const IOPT_DEFAULTS = {format: 'auto', fit: 'contain', colors: 126, dither: false, bright: 0, contrast: 0, sat: 100, grid: true};
const RESET_GROUPS = {frame: ['format', 'fit'], colors: ['colors', 'bright', 'contrast', 'sat', 'dither']};
document.querySelectorAll('#drawOpts [data-reset]').forEach(b => b.onclick = () => {
  (RESET_GROUPS[b.dataset.reset] || []).forEach(k => { IOPT[k] = IOPT_DEFAULTS[k]; });
  syncOptValues();
  $('optDither').checked = IOPT.dither;
  schedulePixels();
  toast(b.dataset.reset === 'frame' ? t('image.settings.reset_frame') : t('image.settings.reset_colors'), 'ok');
});

// ------------------------------------------------ page Dessin : dessin dans le jeu + configuration de la zone
let drawSig = '';
// prochaine etape pour le format courant : image | calib | draw
function drawNext(fmt){
  if(!hasPic()) return 'image';
  const d = drawState();
  if(!isCalibrated(fmt) || !shadesOk()) return 'calib';
  return 'draw';
}
function renderDraw(st){
  const d = st.draw; if(!d) return;
  const hk = st.hotkeys || {};
  const fmt = currentFormat();
  const drawing = d.state === 'drawing', calib = d.state === 'calibrating', auto = d.state === 'autocal';
  const busy = drawing || auto;
  const next = drawNext(fmt);
  const ready = isCalibrated(fmt) && shadesOk();
  const validated = !!(d.validated && d.validated[fmt]);

  // progression (1) Préparer l'image (2) Configurer la zone du jeu (3) Dessiner
  const done = [];
  if(hasPic()) done.push('image');
  if(ready) done.push('calib');
  stepsMark($('drawSteps'), done, busy ? (auto ? 'calib' : 'draw') : next,
            {image: hasPic() ? `${PIX ? PIX.w + '×' + PIX.h : ''}` : '',
             calib: ready ? fmt : ''});

  // un seul bouton principal = prochaine étape ; un calibrage valide n'est jamais refait tout seul
  const b = $('btnDraw');
  const stopKey = hk.stop || 'F7', playKey = hk.play_pause || 'F6';
  let label, cls = 'btn btn--lg btn--cta';
  if(busy){ label = auto ? t('image.run.stop_measure') : t('image.run.stop_draw'); cls = 'btn btn--lg btn--danger'; }
  else if(!hasPic()) label = LABELS.draw;
  else if(next === 'calib') label = t('image.run.configure_format', {format: fmt});
  else label = LABELS.draw;
  if(b.className !== cls) b.className = cls;
  b.querySelector('use').setAttribute('href', busy ? '#i-stop' : next === 'calib' ? '#i-target' : '#i-brush');
  txt('drawLabel', label);
  txt('drawKey', busy ? stopKey : playKey);
  $('drawKey').hidden = !busy && next !== 'draw';
  // action indisponible : la raison est ecrite sous le bouton (setAction)
  setAction(b, {disabled: calib || (!busy && !hasPic()),
    reason: calib ? t('image.run.why_calib') : (!busy && !hasPic()) ? t('image.import.first') : ''});
  // tant que rien n'est configuré, le bouton principal EST l'entrée vers la configuration : pas de doublon
  $('btnDrawConfig').hidden = !ready;
  $('btnDrawConfig').disabled = busy || calib;
  txt('btnDrawConfig', t('image.run.config_btn'));
  $('btnDrawLog').hidden = busy || calib;
  // Le parcours en trois étapes n'a d'intérêt qu'au premier usage. Une fois la zone configurée, il laisse
  // la place à une synthèse d'état : on ne réaffiche pas un assistant à chaque dessin.
  $('drawSteps').hidden = busy || ready;
  const rs = $('drawReady');
  if(rs){
    rs.hidden = busy || !ready;
    // message sur (balisage fixe, format issu de la liste FORMATS, nombres) : innerHTML sans donnee utilisateur
    if(!rs.hidden) html('drawReady', icon('check') + `<span>${plain(t('image.run.ready_html', {format: esc(fmt), measured: validated ? 'yes' : 'no', w: PIX ? PIX.w : '', h: PIX ? PIX.h : ''}))}</span>`);
  }
  // pendant le dessin, le bandeau de session porte seul l'action Arreter (comme la Musique et la Cuisine)
  $('drawCta').hidden = busy;

  const pill = $('imgPill');
  let pc = 'pill', pt = t('image.run.pill_todo'), pi = 'target';
  if(drawing){ pc = 'pill game'; pi = 'brush'; pt = t('image.run.pill_drawing'); }
  else if(calib){ pc = 'pill paused'; pi = 'target'; pt = t('image.run.pill_config'); }
  else if(auto){ pc = 'pill game'; pi = 'ruler'; pt = t('image.run.pill_measure'); }
  else if(!hasPic()){ pc = 'pill'; pi = 'image'; pt = t('image.run.pill_none'); }
  else if(!ready){ pc = 'pill'; pi = 'target'; pt = t('image.run.pill_todo'); }
  else { pc = 'pill preview'; pi = 'check'; pt = t('image.run.pill_ready'); }
  if(pill.className !== pc) pill.className = pc;
  html('imgPill', icon(pi) + `<span>${esc(plain(pt))}</span>`);
  $('imgDisc').classList.toggle('spin', drawing);

  // bandeau de session : compte a rebours puis progression
  let spec = null;
  if(busy && d.countdown > 0){
    spec = {count: Math.ceil(d.countdown), unit: t('image.run.unit_seconds'), role: auto ? t('image.run.role_measure') : t('image.run.role_draw'),
            text: auto ? t('image.run.countdown_measure', {format: d.format}) : t('image.run.countdown_draw'),
            meta: t('image.run.meta_cancel', {key: stopKey}), actions: [{label: LABELS.cancel, kbd: stopKey, api: 'draw_stop'}]};
  } else if(drawing){
    const pct = d.total ? d.done / d.total * 100 : 0;
    spec = {live: true, role: t('image.run.role_drawing'), text: d.progress_msg || t('image.run.drawing_text'),
            meta: t('image.run.drawing_meta', {done: d.done, total: d.total, time: d.eta != null ? t('image.run.eta', {dur: fmtDur(d.eta)}) : fmtDur(d.elapsed), key: stopKey}),
            progress: {pct, left: t('image.settings.percent', {n: Math.round(pct)}), right: d.eta != null ? t('image.run.eta_short', {dur: fmtDur(d.eta)}) : fmtDur(d.elapsed)},
            actions: [{label: LABELS.stop, icon: 'stop', kbd: stopKey, api: 'draw_stop'}]};
  } else if(auto){
    spec = {live: true, role: t('image.run.role_measure'), text: d.progress_msg || t('image.run.measure_text'), meta: t('image.run.measure_meta', {key: stopKey}),
            actions: [{label: LABELS.stop, icon: 'stop', kbd: stopKey, api: 'draw_stop'}]};
  } else if(!calib && d.resume && d.resume.total){
    // dessin interrompu (arret, souris, erreur, application fermee) : on le reprend la ou il en etait
    const r = d.resume, pct = r.done / r.total * 100;
    spec = {role: t('image.run.resume_role'),
            text: r.name ? t('image.run.resume_text_named', {name: r.name, format: r.format}) : t('image.run.resume_text', {format: r.format}),
            meta: t('image.run.resume_meta', {done: r.done, total: r.total}),
            progress: {pct, left: t('image.settings.percent', {n: Math.round(pct)}), right: ''},
            actions: [{label: t('image.run.resume_btn'), icon: 'play', api: 'draw_resume', cls: 'btn--cta'},
                      {label: t('image.run.resume_forget'), api: 'draw_forget_resume', cls: 'btn--ghost'}]};
  }
  renderSession($('drawSession'), spec);

  // notice courte : elle dit toujours ce qui manque et comment l'obtenir
  let notice = null;
  if(!busy){
    if(d.screen_ok === false) notice = {text: t('image.run.no_screen'), kind: 'danger'};
    else if(d.message && /impossible|arrêté|erreur|unable|cannot|stopped|error|fail/i.test(d.message)) notice = {text: d.message, kind: 'warn'};
    else if(!hasPic()) notice = {text: t('image.run.notice_import'), kind: 'info'};
    else if(!isCalibrated(fmt)) notice = {text: t('image.run.notice_calib', {format: fmt}), kind: 'warn'};
    else if(!shadesOk()) notice = {text: t('image.run.notice_shades', {format: fmt}), kind: 'warn'};
    else if(!validated) notice = {text: t('image.run.notice_measure'), kind: 'info'};
    else notice = {text: t('image.run.notice_ready', {format: fmt, key: playKey}), kind: 'ok', icon: 'check'};
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
  if(!outlineOn) ostat = t('image.settings.outline_off');
  else if(!PIX) ostat = t('image.settings.outline_intro');
  else if(!os) ostat = t('image.settings.outline_computing');
  else if(os.available) ostat = t('image.settings.outline_stats', {pencil: os.pencil_cells, zones: os.fill_zones, fill: os.fill_cells, total: os.total_cells});
  else ostat = t('image.settings.outline_unavailable');
  txt('outlineStat', ostat);

  // assistant de configuration
  if(calib){
    renderCalibOverlay({
      kind: 'draw',
      title: t('image.calib.title_draw', {format: d.format}),
      prep: t('image.calib.prep_draw_html', {format: esc(d.format)}),
      steps: d.steps || [], step: d.step, hk, message: d.message,
      skippable: s => s.key === 'pencil' || s.key === 'bucket' || s.key === 'undo',
      cancel: 'draw_calibrate_cancel', skip: 'draw_calibrate_skip', back: 'draw_calibrate_back', goto: 'draw_calibrate_goto'});
  } else if(!(st.cook && st.cook.state === 'calibrating')){
    closeCalibOverlay();
  }
  // palette ou grilles changees (fin de calibrage) : on recalcule l'apercu
  const sig = JSON.stringify([d.palette, d.formats, d.shades_ok]);
  if(sig !== drawSig){ drawSig = sig; if(hasPic()) schedulePixels(); else syncFormatChips(); }
}
view('draw', {draw: renderDraw});

// ------------------------------------------------ assistant de configuration (dessin et cuisine)
// Une seule étape active, montrée en grand avec un schéma qui désigne la cible. Le récapitulatif complet
// reste disponible, replié. Les schémas sont des dessins de DodoTopia, pas des captures du jeu : ils
// montrent où chercher, l'écran réel peut différer.
const CAL_ART = {
  // --- dessin : vue de l'outil de dessin (toile rayée, outils à gauche, palette en bas)
  draw: {
    view: (hi) => `<svg viewBox="0 0 300 190" role="img" aria-label="${esc(t('image.calib.art_draw_view'))}">
      <rect x="2" y="2" width="296" height="186" rx="14" fill="#fbf5ea" stroke="#e4d4ba" stroke-width="2"/>
      <rect x="72" y="30" width="180" height="108" rx="6" fill="#fff" stroke="#c7b9ad" stroke-width="2"/>
      <g stroke="#e9ded0" stroke-width="1">${Array.from({length: 17}, (_, i) => `<path d="M${76 + i * 11} 30V138"/>`).join('')}${Array.from({length: 9}, (_, i) => `<path d="M72 ${34 + i * 12}H252"/>`).join('')}</g>
      <circle cx="86" cy="16" r="9" fill="#f6f1e6" stroke="#c7b9ad" stroke-width="2"/><path d="M82 16h7m-3-3-4 3 4 3" stroke="#9c8a7f" stroke-width="2" fill="none" stroke-linecap="round"/>
      <g fill="#f6f1e6" stroke="#c7b9ad" stroke-width="2">
        <rect x="40" y="38" width="24" height="24" rx="8"/><rect x="40" y="70" width="24" height="24" rx="8"/><rect x="40" y="102" width="24" height="24" rx="8"/></g>
      <path d="M47 57l10-10 3 3-10 10z" fill="#b56f3f"/>
      <path d="M46 84c3-6 9-8 13-4s2 10-4 12z" fill="#46cbc4"/>
      <circle cx="52" cy="114" r="7" fill="#e8a531"/><circle cx="50" cy="112" r="1.6" fill="#fff"/>
      <g>${[0, 1].map(r => Array.from({length: 8}, (_, c) => `<rect x="${90 + c * 20}" y="${150 + r * 16}" width="15" height="12" rx="4" fill="${['#c94f5a', '#e8a531', '#edca16', '#a8bc16', '#05a25d', '#058781', '#05729c', '#534da1'][c]}" opacity="${r ? .55 : 1}"/>`).join('')).join('')}</g>
      ${hi}</svg>`,
    shades: (hi) => `<svg viewBox="0 0 300 190" role="img" aria-label="${esc(t('image.calib.art_draw_shades'))}">
      <rect x="2" y="2" width="296" height="186" rx="14" fill="#fbf5ea" stroke="#e4d4ba" stroke-width="2"/>
      <rect x="54" y="28" width="192" height="134" rx="14" fill="#fff" stroke="#c7b9ad" stroke-width="2"/>
      <text x="150" y="20" text-anchor="middle" font-size="11" fill="#9c8a7f">${esc(t('image.calib.art_shades_caption'))}</text>
      <path d="M70 52l-7 7 7 7" stroke="#b56f3f" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M230 52l7 7-7 7" stroke="#b56f3f" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      <g>${Array.from({length: 5}, (_, i) => `<circle cx="${102 + i * 24}" cy="59" r="9" fill="${['#c94f5a', '#e8a531', '#05a25d', '#058781', '#534da1'][i]}"/>`).join('')}</g>
      <rect x="141" y="48" width="22" height="22" rx="11" fill="none" stroke="#fff" stroke-width="3"/>
      <rect x="141" y="48" width="22" height="22" rx="11" fill="none" stroke="#9c8a7f" stroke-width="1"/>
      <g>${Array.from({length: 10}, (_, i) => `<rect x="${112 + (i % 2) * 40}" y="${84 + Math.floor(i / 2) * 15}" width="34" height="12" rx="4" fill="#058781" opacity="${1 - Math.floor(i / 2) * .15}"/>`).join('')}</g>
      ${hi}</svg>`},
  // --- cuisine : vue du monde (cuisinière + bulle) et vue du menu Recettes
  cook: {
    world: (hi) => `<svg viewBox="0 0 300 190" role="img" aria-label="${esc(t('image.calib.art_cook_world'))}">
      <rect x="2" y="2" width="296" height="186" rx="14" fill="#eef2da" stroke="#d7e0b8" stroke-width="2"/>
      <path d="M2 140h296v46a14 14 0 0 1-14 14H16a14 14 0 0 1-14-14z" fill="#cfdca6"/>
      <rect x="108" y="96" width="84" height="48" rx="10" fill="#c98644"/>
      <rect x="118" y="106" width="64" height="26" rx="6" fill="#fbe7bd"/>
      <circle cx="150" cy="58" r="26" fill="#fff" stroke="#c7b9ad" stroke-width="2"/>
      <path d="M140 80l10 12 10-12z" fill="#fff" stroke="#c7b9ad" stroke-width="2"/>
      <path d="M140 52h20m-16 6h12" stroke="#6b5a52" stroke-width="3" stroke-linecap="round"/>
      <circle cx="150" cy="58" r="32" fill="none" stroke="#9fb356" stroke-width="4" stroke-dasharray="5 5"/>
      <circle cx="232" cy="160" r="8" fill="#9fb356"/><circle cx="252" cy="168" r="6" fill="#9fb356"/>
      ${hi}</svg>`,
    menu: (hi) => `<svg viewBox="0 0 300 190" role="img" aria-label="${esc(t('image.calib.art_cook_menu'))}">
      <rect x="2" y="2" width="296" height="186" rx="14" fill="#fbf5ea" stroke="#e4d4ba" stroke-width="2"/>
      <rect x="22" y="16" width="256" height="158" rx="16" fill="#fff" stroke="#c7b9ad" stroke-width="2"/>
      <text x="42" y="40" font-size="12" fill="#9c8a7f">${esc(t('image.calib.art_menu_recent'))}</text>
      <g>${Array.from({length: 4}, (_, i) => `<rect x="${42 + i * 44}" y="${50}" width="36" height="36" rx="8" fill="#fbe7bd" stroke="#e4d4ba" stroke-width="2"/>`).join('')}</g>
      <g>${Array.from({length: 4}, (_, i) => `<rect x="${42 + i * 44}" y="${98}" width="36" height="36" rx="8" fill="#f6f1e6" stroke="#e4d4ba" stroke-width="2"/>`).join('')}</g>
      <rect x="196" y="132" width="66" height="26" rx="13" fill="#e8a531"/>
      <text x="229" y="149" text-anchor="middle" font-size="11" fill="#4a3527" font-weight="700">${esc(t('image.calib.art_menu_cook'))}</text>
      ${hi}</svg>`}};
// cible : anneau + flèche, posés sur le schéma
function calMark(x, y, r){
  r = r || 16;
  return `<g class="calmark"><circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="#c94f5a" stroke-width="3"/>
    <circle cx="${x}" cy="${y}" r="2.5" fill="#c94f5a"/></g>`;
}
function calRect(x, y, w, h){
  return `<g class="calmark"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6" fill="none" stroke="#c94f5a" stroke-width="3" stroke-dasharray="7 5"/></g>`;
}
// step -> schéma. Une clé inconnue ne dessine rien plutôt qu'un schéma faux.
const CAL_STEP_ART = {
  draw: {
    tl: () => CAL_ART.draw.view(calMark(72, 30, 13)),
    br: () => CAL_ART.draw.view(calMark(252, 138, 13)),
    pal0: () => CAL_ART.draw.view(calMark(97, 156, 13)),
    pal1: () => CAL_ART.draw.view(calMark(237, 172, 13)),
    palbtn: () => CAL_ART.draw.view(calMark(52, 114, 16)),
    pencil: () => CAL_ART.draw.view(calMark(52, 50, 16)),
    bucket: () => CAL_ART.draw.view(calMark(52, 82, 16)),
    undo: () => CAL_ART.draw.view(calMark(86, 16, 13)),
    strip: () => CAL_ART.draw.shades(calMark(150, 59, 16)),
    prev: () => CAL_ART.draw.shades(calMark(66, 59, 14)),
    next: () => CAL_ART.draw.shades(calMark(234, 59, 14)),
    sub0: () => CAL_ART.draw.shades(calMark(129, 90, 14)),
    sub1: () => CAL_ART.draw.shades(calMark(169, 150, 14))},
  cook: {
    search_tl: () => CAL_ART.cook.world(calRect(86, 14, 128, 92) + calMark(86, 14, 11)),
    search_br: () => CAL_ART.cook.world(calRect(86, 14, 128, 92) + calMark(214, 106, 11)),
    cook: () => CAL_ART.cook.world(calMark(150, 58, 20)),
    spatula: () => CAL_ART.cook.world(calMark(150, 58, 20)),
    ready: () => CAL_ART.cook.world(calMark(150, 58, 20)),
    neutral: () => CAL_ART.cook.world(calMark(240, 163, 16)),
    tile: () => CAL_ART.cook.menu(calMark(60, 68, 21)),
    cook_btn: () => CAL_ART.cook.menu(calMark(229, 145, 20))}};

let CALIB = {cancel: 'draw_calibrate_cancel', skip: 'draw_calibrate_skip', back: 'draw_calibrate_back', goto: 'draw_calibrate_goto'};
function closeCalibOverlay(){ if($('calibOverlay').classList.contains('open')) closeModal($('calibOverlay')); }
function renderCalibOverlay(spec){
  const fresh = !$('calibOverlay').classList.contains('open');
  CALIB = spec;
  const steps = spec.steps || [];
  const n = steps.length, i = Math.min(spec.step, n - 1);
  const cur = steps[i];
  const hk = spec.hk || {};
  txt('calibTitle', spec.title.replace(/<[^>]+>/g, ''));
  txt('calibCount', t('image.calib.step_count', {i: i + 1, n}));
  $('calibFill').style.width = (n ? (i / n * 100) : 0).toFixed(1) + '%';
  $('calibBar').setAttribute('aria-valuenow', String(i + 1));
  $('calibBar').setAttribute('aria-valuemin', '1');
  $('calibBar').setAttribute('aria-valuemax', String(n));
  html('calibPrepBody', spec.prep || '');
  if(fresh) $('calibPrep').open = spec.step === 0;
  // étape active : titre, consigne et schéma de la cible
  if(cur){
    txt('calibStepTitle', cur.title);
    txt('calibStepHelp', cur.help);
    const art = (CAL_STEP_ART[spec.kind] || {})[cur.key];
    const svg = art ? art() : '';
    html('calibArt', svg ? svg + `<span class="calib__artnote">${esc(t('image.calib.art_note'))}</span>` : '');
    $('calibArt').hidden = !svg;
  }
  txt('calibKey', hk.draw_point || 'F3');
  txt('calibState', t('image.calib.waiting'));
  setNotice('calibMsg', spec.message ? {text: spec.message, kind: 'warn'} : null);
  // récapitulatif complet, replié : chaque étape faite est cliquable pour y revenir
  const sig = JSON.stringify([steps.map(s => s.title), i, I18N.lang]);
  if(changed($('calibSteps'), sig)){
    $('calibSteps').innerHTML = steps.map((s, k) => {
      const cls = k < i ? 'done' : k === i ? 'now' : '';
      const mark = k < i ? icon('check') : k + 1;
      return k < i
        ? `<li class="${cls}"><button type="button" class="stepback" data-goto="${k}" title="${esc(t('image.calib.back_to_step'))}"><span class="n">${mark}</span>${esc(s.title)}</button></li>`
        : `<li class="${cls}"><span class="n">${mark}</span>${esc(s.title)}</li>`;
    }).join('');
    $('calibSteps').querySelectorAll('[data-goto]').forEach(b => b.onclick = () => api(CALIB.goto, Number(b.dataset.goto)));
  }
  txt('calibAllSum', t('image.calib.all_steps', {n}));
  $('calibSkip').hidden = !(cur && spec.skippable(cur));
  $('calibBack').disabled = i <= 0;
  if(fresh){ openModal($('calibOverlay')); setTimeout(() => $('calibStepTitle').focus && $('calibStepTitle').focus(), 30); }
}
// duree lisible (« 3 min 05 s », « 42 s ») ; partagee avec la Cuisine
function fmtDur(s){
  s = Math.max(0, Math.round(s || 0));
  return s >= 60 ? t('image.run.dur_min', {m: Math.floor(s / 60), s: String(s % 60).padStart(2, '0')}) : t('image.run.dur_sec', {s});
}

// ------------------------------------------------ actions
function drawCalibrate(){ api('draw_calibrate', currentFormat()); }
function drawAutoCalibrate(){
  if(!isCalibrated(currentFormat())){ drawCalibrate(); return; }
  dialog({title: t('image.run.measure_title'), icon: 'ruler', ok: t('image.run.measure_ok'), cancel: t('common.cancel'),
          html: t('image.run.measure_html', {format: currentFormat()})})
    .then(yes => { if(yes) api('draw_auto_calibrate', currentFormat()); });
}
function drawStart(){
  const fmt = currentFormat();
  const [gw, gh] = gridFor(fmt);
  const painted = PIX ? PIX.counts.reduce((a, b) => a + b, 0) : 0;
  // le nom du fichier est une donnee utilisateur : echappe avant d'entrer dans le message HTML
  dialog({title: LABELS.draw, icon: 'brush', ok: t('image.run.start_ok'), cancel: t('common.cancel'),
          html: t('image.run.start_html', {name: esc(IMG.name || t('image.import.default_name')), format: fmt, w: gw, h: gh, painted})})
    .then(yes => { if(yes) api('draw_start'); });
}
$('btnDraw').onclick = () => {
  const d = drawState();
  if(d && (d.state === 'drawing' || d.state === 'autocal')){ api('draw_stop'); return; }
  if(!hasPic()){ toast(t('image.import.first'), 'warn'); return; }
  const next = drawNext(currentFormat());
  if(next === 'calib') drawCalibrate();
  else drawStart();
};
// « Configuration » est une tâche de préparation ; « Journal » est un outil de diagnostic. Deux boutons.
$('btnDrawConfig').onclick = () => {
  const fmt = currentFormat(), cal = isCalibrated(fmt), d = drawState();
  const val = !!(d && d.validated && d.validated[fmt]);
  if(!cal){ drawCalibrate(); return; }
  menu($('btnDrawConfig'), [
    {label: t('image.run.menu_redo', {format: fmt}), help: t('image.run.menu_redo_help'), icon: 'target', fn: drawCalibrate},
    {label: t('image.run.measure_title'), icon: 'ruler', help: val ? t('image.run.menu_measure_done') : t('image.run.menu_measure_advice'), fn: drawAutoCalibrate},
  ]);
};
$('btnDrawLog').onclick = () => api('open_draw_log');
$('calibCancel').onclick = $('calibCancel2').onclick = () => api(CALIB.cancel);
$('calibSkip').onclick = () => api(CALIB.skip);
$('calibBack').onclick = () => api(CALIB.back);
// bloc Methode : interrupteurs -> set_setting (sans toast)
['mOutline', 'mFill', 'mSkipWhite'].forEach(id => { const cb = $(id); cb.onchange = () => api('set_setting', cb.dataset.path, cb.checked); });

// ------------------------------------------------ export et publication du dessin converti
// Export : l'aperçu est redessiné sans grille à l'échelle ×8 (réduite si le fichier dépasserait 5 Mo), avec un petit
// badge DodoTopia facultatif, puis enregistré par Python dans DATA_DIR/exports/. Publication : même rendu sans badge,
// 1024 px et 512 Ko au plus (limites du serveur), avec la grille de cases pour « Reproduire ce dessin ».
const DSHARE = {upSeq: null};
const EXPORT_MAX = 5 * 1024 * 1024, GALLERY_PNG_MAX = 512 * 1024, GALLERY_PX_MAX = 1024;
function dataUrlBytes(u){ const i = u.indexOf(','); return Math.floor((u.length - i - 1) * 3 / 4); }
function renderDrawingPng(scale, badge){
  if(!PIX) return '';
  const {w, h, cells, palette} = PIX;
  const cv = document.createElement('canvas'); cv.width = w * scale; cv.height = h * scale;
  const ctx = cv.getContext('2d');
  for(let y = 0; y < h; y++) for(let x = 0; x < w; x++){
    const k = cells[y * w + x]; if(k < 0) continue;
    ctx.fillStyle = hex(palette[k]); ctx.fillRect(x * scale, y * scale, scale, scale);
  }
  if(badge){
    // pastille crème en bas à droite : logo (s'il est chargé) + « DodoTopia », proportionnelle à l'image
    const fs = Math.max(11, Math.round(Math.min(cv.width, cv.height) / 34));
    ctx.font = `700 ${fs}px Nunito, "Segoe UI", sans-serif`;
    const logo = $('logo'), hasLogo = !!(logo && logo.complete && logo.naturalWidth && logo.style.display !== 'none');
    const label = 'DodoTopia', tw = ctx.measureText(label).width, pad = Math.round(fs * .55), lg = hasLogo ? Math.round(fs * 1.35) : 0;
    const bw = Math.round(tw + pad * 2 + (lg ? lg + pad * .6 : 0)), bh = Math.round(fs * 1.9), m = Math.round(fs * .6);
    const bx = cv.width - bw - m, by = cv.height - bh - m, r = bh / 2;
    ctx.fillStyle = 'rgba(251,245,234,.92)'; ctx.strokeStyle = 'rgba(181,111,63,.55)'; ctx.lineWidth = Math.max(1, fs / 10);
    ctx.beginPath(); ctx.moveTo(bx + r, by); ctx.arcTo(bx + bw, by, bx + bw, by + bh, r); ctx.arcTo(bx + bw, by + bh, bx, by + bh, r);
    ctx.arcTo(bx, by + bh, bx, by, r); ctx.arcTo(bx, by, bx + bw, by, r); ctx.closePath(); ctx.fill(); ctx.stroke();
    if(lg){ try{ ctx.drawImage(logo, bx + pad, by + (bh - lg) / 2, lg, lg); }catch(e){} }
    ctx.fillStyle = '#7d4826'; ctx.textBaseline = 'middle';
    ctx.fillText(label, bx + pad + (lg ? lg + pad * .6 : 0), by + bh / 2 + 1);
  }
  try{ return cv.toDataURL('image/png'); }catch(e){ return ''; }
}
function drawingFileName(){ return (IMG.name || t('image.import.default_name')).replace(/[\\/:*?"<>|]+/g, ' ').trim().slice(0, 80) || 'dessin'; }
function exportDrawing(){
  if(!PIX){ toast(t('image.import.first'), 'warn'); return; }
  let badge = true;
  try{ badge = localStorage.getItem('draw.exportBadge') !== '0'; }catch(e){}
  dialog({title: t('image.export.title'), icon: 'download', ok: t('image.export.ok'),
          html: `<p>${esc(t('image.export.body', {w: PIX.w * 8, h: PIX.h * 8}))}</p>
            <label class="checkline"><input type="checkbox" class="export__badge"${badge ? ' checked' : ''}><span>${esc(t('image.export.badge'))}</span></label>`})
    .then(yes => {
      const cb = $('dlgBody').querySelector('.export__badge');
      if(!yes) return;
      badge = !!(cb && cb.checked);
      try{ localStorage.setItem('draw.exportBadge', badge ? '1' : '0'); }catch(e){}
      let url = '';
      for(const sc of [8, 6, 4, 2, 1]){ url = renderDrawingPng(sc, badge); if(url && dataUrlBytes(url) <= EXPORT_MAX) break; }
      if(!url || dataUrlBytes(url) > EXPORT_MAX){ toast(t('image.export.too_big'), 'warn'); return; }
      apiAction($('btnExportImg'), 'save_drawing_png', url, drawingFileName());
    });
}
function publishDrawing(){
  if(!PIX){ toast(t('image.import.first'), 'warn'); return; }
  const o = S && S.online;
  if(!o || !o.logged_in){ toast(t('image.publish.need_account'), 'info'); if(typeof accountPanel === 'function' && o) accountPanel(); return; }
  dialog({title: t('image.publish.title'), icon: 'cloud-up', ok: t('image.publish.ok'), wide: true,
          html: `<p>${esc(t('image.publish.body'))}</p>
            <label class="field"><span class="field__label">${esc(t('image.publish.name'))}</span>
              <input class="input dlg-input publish__title" type="text" maxlength="60" value="${esc((IMG.name || '').slice(0, 60))}"></label>
            <p class="hint left">${esc(t('image.publish.moderation'))}</p>`})
    .then(yes => {
      const inp = $('dlgBody').querySelector('.publish__title');
      if(!yes) return;
      let url = '';
      const maxSc = Math.max(1, Math.floor(GALLERY_PX_MAX / Math.max(PIX.w, PIX.h)));
      for(const sc of [8, 6, 4, 3, 2, 1].filter(v => v <= maxSc)){ url = renderDrawingPng(sc, false); if(url && dataUrlBytes(url) <= GALLERY_PNG_MAX) break; }
      if(!url || dataUrlBytes(url) > GALLERY_PNG_MAX){ toast(t('image.publish.too_big'), 'warn'); return; }
      const job = {format: PIX.format, w: PIX.w, h: PIX.h, cells: Array.from(PIX.cells)};
      apiAction($('btnPublishImg'), 'gallery_share', url, inp ? inp.value.trim() : '', job).then(r => {
        if(r && r.ok) DSHARE.upSeq = (((r.state || S || {}).online || {}).gallery_upload || {}).seq || null;
      });
    });
}
$('btnExportImg').onclick = exportDrawing;
$('btnPublishImg').onclick = publishDrawing;
// état du dépôt lancé ici : envoi, en attente de modération (+ partage du lien si déjà publié), erreur
view('drawShare', {sig: st => { const u = st.online && st.online.gallery_upload; return JSON.stringify([u, DSHARE.upSeq, I18N.lang]); }, draw: st => {
  const u = st.online && st.online.gallery_upload, box = $('drawShareStatus');
  if(!box) return;
  const mine = u && DSHARE.upSeq != null && u.seq === DSHARE.upSeq;
  $('btnPublishImg').classList.toggle('is-loading', !!(mine && u.state === 'uploading'));
  if(!mine || u.state === 'idle' || u.state === 'uploading'){ box.innerHTML = ''; return; }
  if(u.state === 'error'){ box.innerHTML = `<span class="chip chip--badge chip--warn" title="${esc(u.error || '')}">${icon('warn')}${esc(t('image.publish.failed'))}</span>`; return; }
  const it = u.item || {};
  const approved = it.status === 'approved';
  box.innerHTML = `<span class="chip chip--badge ${approved ? 'chip--ok' : 'chip--info'}">${icon(approved ? 'check' : 'hourglass')}${esc(approved ? t('image.publish.published') : t('image.publish.pending'))}</span>`
    + (approved && it.page_url ? `<button class="iconbtn iconbtn--sm" type="button" data-act="share" aria-haspopup="menu" title="${esc(t('share.title'))}" aria-label="${esc(t('share.title'))}">${icon('share')}</button>` : '');
  const b = box.querySelector('[data-act="share"]');
  if(b) b.onclick = () => shareMenu({anchor: b, url: it.page_url, text: t('share.drawing_text', {title: it.title || ''})});
}});

// ------------------------------------------------ galerie des dessins partagés
const GAL = {open: false, sort: 'recent', searched: false, takenSeq: null};
try{ GAL.sort = localStorage.getItem('gallery.sort') === 'popular' ? 'popular' : 'recent'; }catch(e){}
function showDrawView(name){
  GAL.open = name === 'gallery';
  $('drawGallery').hidden = !GAL.open;
  $('pageImage').classList.toggle('is-gallery', GAL.open);
  $('pageImage').classList.toggle('is-empty', !hasPic() && !GAL.open);
  if(GAL.open){
    const o = S && S.online, g = o && o.gallery;
    if(o && o.server_ok !== false && (!g || !g.at) && !(g && g.loading)){ GAL.searched = true; api('gallery_list', 1, GAL.sort); }
    setTimeout(() => { const f = $('galleryBack'); if(f) f.focus(); }, 30);
  }
  if(S) render(S);
}
function galleryCardHtml(it, o){
  const title = it.title || t('image.gallery.untitled');
  const by = it.uploader_name ? t('image.gallery.by', {name: it.uploader_name}) : '';
  const meta = [by, `${it.w}×${it.h}`].filter(Boolean).join(' · ');
  const thumb = it.thumb_url ? `<img src="${esc(it.thumb_url)}" alt="" loading="lazy" width="${esc(it.thumb_w || 200)}" height="${esc(it.thumb_h || 200)}">`
    : `<span class="gcard__noimg" aria-hidden="true">${icon('image')}</span>`;
  const canOpen = it.has_cells !== false;
  return `<article class="gcard">
      <button class="gcard__img" type="button" data-act="open" data-id="${esc(it.id)}"${canOpen ? '' : ' disabled'} title="${esc(canOpen ? t('image.gallery.reproduce') : t('image.gallery.no_cells'))}" aria-label="${esc(t('image.gallery.reproduce_aria', {title}))}">${thumb}</button>
      <div class="gcard__body"><div class="gcard__t" title="${esc(title)}">${esc(title)}</div><div class="gcard__m">${esc(meta)}</div></div>
      <div class="gcard__acts">
        ${likeButtonHtml(it, 'like')}
        <div class="spacer"></div>
        ${it.page_url ? `<button class="iconbtn iconbtn--sm" type="button" data-act="share" data-id="${esc(it.id)}" aria-haspopup="menu" title="${esc(t('share.title'))}" aria-label="${esc(t('share.title'))}">${icon('share')}</button>` : ''}
        <button class="iconbtn iconbtn--sm" type="button" data-act="more" data-id="${esc(it.id)}" aria-haspopup="menu" title="${esc(t('image.gallery.more'))}" aria-label="${esc(t('image.gallery.more'))}">${icon('dots')}</button>
        <button class="btn btn--cta btn--sm" type="button" data-act="open" data-id="${esc(it.id)}"${canOpen ? '' : ' disabled'}>${icon('brush')}<span>${esc(t('image.gallery.reproduce'))}</span></button>
      </div>
    </article>`;
}
function renderGallery(st){
  if(!GAL.open) return;
  const o = st.online || null;
  const g = (o && o.gallery) || {items: [], page: 1, pages: 0, total: 0, loading: false, error: '', at: 0};
  const grid = $('galleryGrid');
  const items = g.items || [];
  if($('gallerySort').value !== (g.sort || GAL.sort)) $('gallerySort').value = g.sort || GAL.sort;
  txt('galleryCount', I18N.fmtNumber(g.total || items.length || 0));
  if(o && o.server_ok && !g.at && !g.loading && !GAL.searched){ GAL.searched = true; api('gallery_list', 1, GAL.sort); }
  if(!o || o.server_ok === false){
    grid.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon('offline')}</div>${esc(t('image.gallery.offline'))}</div>`;
  } else if(g.error){
    grid.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon('warn')}</div>${esc(g.error)}
      <div class="btnrow btnrow--center"><button class="btn btn--secondary btn--sm" type="button" data-act="retry">${esc(t('online.discover.retry'))}</button></div></div>`;
  } else if(!items.length){
    grid.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon(g.loading ? 'spinner' : 'image', g.loading ? 'ic--spin' : '')}</div>${esc(g.loading ? t('online.discover.loading') : t('image.gallery.empty'))}</div>`;
  } else {
    grid.innerHTML = items.map(it => galleryCardHtml(it, o)).join('');
  }
  grid.querySelectorAll('[data-act]').forEach(b => b.onclick = () => {
    const id = b.dataset.id, it = items.find(x => String(x.id) === String(id));
    switch(b.dataset.act){
      case 'retry': api('gallery_list', g.page || 1, GAL.sort); break;
      case 'open': apiAction(b, 'gallery_open', id); break;
      case 'like': toggleLike(o, 'gallery_like', id, items); break;
      case 'share': if(it) shareMenu({anchor: b, url: it.page_url, text: t('share.drawing_text', {title: it.title || ''})}); break;
      case 'more': galleryMore(b, it, o); break;
    }
  });
  $('galleryPager').hidden = (g.pages || 0) < 2;
  txt('galleryPage', t('online.discover.page', {page: g.page || 1, pages: g.pages || 1}));
  $('galleryPrev').disabled = (g.page || 1) <= 1;
  $('galleryNext').disabled = (g.page || 1) >= (g.pages || 1);
}
function galleryMore(anchor, it, o){
  if(!it) return;
  const logged = !!(o && o.logged_in);
  const items = [{label: t('image.gallery.report'), icon: 'flag', disabled: !logged || it.mine, help: logged ? '' : t('image.gallery.need_account_short'),
    fn: () => dialog({title: t('image.gallery.report_title'), icon: 'flag', ok: t('image.gallery.report_ok'), danger: true,
      html: `<p>${esc(t('image.gallery.report_body', {title: it.title || t('image.gallery.untitled')}))}</p>
        <label class="field"><span class="field__label">${esc(t('image.gallery.report_reason'))}</span>
          <input class="input dlg-input" type="text" maxlength="500"></label>`})
      .then(yes => { const inp = $('dlgBody').querySelector('.dlg-input'); const r = inp ? inp.value.trim() : '';
        if(yes && r) api('gallery_report', it.id, r); else if(yes) toast(t('online.gallery.error.bad_reason'), 'warn'); })}];
  if(it.mine) items.push({label: t('image.gallery.delete'), icon: 'trash',
    fn: () => dialog({title: t('image.gallery.delete_title'), icon: 'trash', ok: t('image.gallery.delete_ok'), danger: true,
      html: `<p>${esc(t('image.gallery.delete_body', {title: it.title || t('image.gallery.untitled')}))}</p>`})
      .then(yes => { if(yes) api('gallery_delete', it.id); })});
  menu(anchor, items);
}
view('gallery', {sig: st => {
  const o = st.online || null;
  return JSON.stringify([GAL.open, o && o.server_ok, o && o.logged_in, o && o.gallery, I18N.lang]);
}, draw: renderGallery});
// grille récupérée (bouton « Reproduire » ou lien dodotopia://drawing/<id>) : reprise une fois, ouverte dans Dessin
view('drawingOpen', {sig: st => { const d = st.online && st.online.drawing_open; return d ? d.state + '|' + d.seq : ''; }, draw: st => {
  const d = st.online && st.online.drawing_open;
  if(!d || d.state !== 'ready' || GAL.takenSeq === d.seq) return;
  GAL.takenSeq = d.seq;
  api('gallery_take', d.seq).then(r => { if(r && r.ok && r.job) loadGridJob(r); });
}});
function loadGridJob(r){
  const job = r.job || {};
  if(!job.w || !job.h || !Array.isArray(job.cells)) return;
  IMG.img = null; IMG.job = {format: job.format, w: job.w, h: job.h, cells: job.cells};
  IMG.name = r.title || t('image.gallery.untitled'); IMG.w = job.w; IMG.h = job.h; IMG.source = {id: r.id};
  DSHARE.upSeq = null;
  showTab('image');
  showDrawView('draw');
  renderPixels();
  toast(t('image.gallery.loaded', {title: IMG.name}), 'ok');
}
window.loadGridJob = loadGridJob;
$('btnGallery').onclick = () => showDrawView('gallery');
$('btnGalleryBig').onclick = () => showDrawView('gallery');
$('galleryBack').onclick = () => showDrawView('draw');
$('gallerySort').onchange = () => {
  GAL.sort = $('gallerySort').value === 'popular' ? 'popular' : 'recent';
  try{ localStorage.setItem('gallery.sort', GAL.sort); }catch(e){}
  api('gallery_list', 1, GAL.sort);
};
$('galleryRefresh').onclick = () => { const g = S && S.online && S.online.gallery; api('gallery_list', (g && g.page) || 1, GAL.sort); };
$('galleryPrev').onclick = () => { const g = S && S.online && S.online.gallery; api('gallery_list', Math.max(1, ((g && g.page) || 1) - 1), GAL.sort); };
$('galleryNext').onclick = () => { const g = S && S.online && S.online.gallery; api('gallery_list', ((g && g.page) || 1) + 1, GAL.sort); };
