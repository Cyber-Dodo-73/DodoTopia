// DodoTopia : « Envoyer un rapport » (api/support.py). Le joueur voit la liste des fichiers avant tout envoi ;
// l'envoi rend un code court à coller sur Discord ; « Enregistrer le zip » marche sans connexion.
const DIAG = {note: '', audio: false, images: false, preview: null, result: null, busy: false};

function diagSizeText(n){
  if(n >= 1024 * 1024) return t('support.size_mb', {n: (n / 1024 / 1024).toFixed(1)});
  return t('support.size_kb', {n: Math.max(1, Math.round(n / 1024))});
}
function diagHtml(st){
  const p = DIAG.preview;
  if(DIAG.result && DIAG.result.code){
    return `<div class="diagdone">
        <p>${esc(t('support.sent'))}</p>
        <button type="button" class="roomcode diagcode" data-diag="copy" title="${esc(t('support.copy'))}">${esc(DIAG.result.code)}</button>
        <p class="hint left">${esc(t('support.sent_hint'))}</p>
        <div class="btnrow"><button type="button" class="btn btn--cta btn--sm" data-diag="copy">${icon('copy')}<span>${esc(t('support.copy'))}</span></button>
          <button type="button" class="btn btn--secondary btn--sm" data-diag="close">${esc(t('common.close'))}</button></div>
      </div>`;
  }
  const files = p ? p.files.filter(f => (f.kind !== 'audio' || DIAG.audio) && (f.kind !== 'image' || DIAG.images)) : [];
  const total = files.reduce((a, f) => a + f.size, 0);
  const online = !!(st && st.online && st.online.server_ok !== false);
  return `<p>${esc(t('support.intro'))}</p>
    <label class="field__label" for="diagNote">${esc(t('support.note_label'))}</label>
    <textarea class="input diagnote" id="diagNote" rows="4" maxlength="2000" placeholder="${esc(t('support.note_ph'))}">${esc(DIAG.note)}</textarea>
    ${p && p.images ? `<label class="check"><input type="checkbox" id="diagImages"${DIAG.images ? ' checked' : ''}> ${esc(t('support.images'))}</label>` : ''}
    ${p && p.audio ? `<label class="check"><input type="checkbox" id="diagAudio"${DIAG.audio ? ' checked' : ''}> ${esc(t('support.audio'))}</label>` : ''}
    <details class="disclosure disclosure--inline"><summary>${esc(t('support.files', {n: files.length + 1, size: diagSizeText(total)}))}</summary>
      <div class="disclosure__body"><ul class="diagfiles">
        <li>systeme.json <span class="hint">${esc(t('support.system_desc'))}</span></li>
        ${files.map(f => `<li>${esc(f.name)} <span class="hint">${esc(diagSizeText(f.size))}</span></li>`).join('')}
      </ul><p class="hint left">${esc(t('support.privacy'))}</p></div></details>
    ${DIAG.result && DIAG.result.error ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(DIAG.result.error)}</div></div>` : ''}
    <div class="btnrow">
      <button type="button" class="btn btn--cta btn--sm" data-diag="send"${DIAG.busy || !online ? ' disabled' : ''} title="${esc(online ? '' : t('support.offline'))}">${icon(DIAG.busy ? 'spinner' : 'cloud-up', DIAG.busy ? 'ic--spin' : '')}<span>${esc(t('support.send'))}</span></button>
      <button type="button" class="btn btn--secondary btn--sm" data-diag="save"${DIAG.busy ? ' disabled' : ''}>${icon('download')}<span>${esc(t('support.save'))}</span></button>
    </div>
    ${online ? '' : `<p class="hint left">${esc(t('support.offline'))}</p>`}`;
}
function diagWire(box){
  const note = box.querySelector('#diagNote');
  if(note){ note.oninput = () => { DIAG.note = note.value; }; note.onkeydown = e => e.stopPropagation(); }
  const au = box.querySelector('#diagAudio');
  if(au) au.onchange = () => { DIAG.audio = au.checked; refreshPanel(); };
  const im = box.querySelector('#diagImages');
  if(im) im.onchange = () => { DIAG.images = im.checked; refreshPanel(); };
  box.querySelectorAll('[data-diag]').forEach(b => b.onclick = () => {
    const act = b.dataset.diag;
    if(act === 'close') closePanel();
    else if(act === 'copy') copyText(DIAG.result && DIAG.result.code, t('support.copied'));
    else if(act === 'send' || act === 'save'){
      DIAG.busy = true; DIAG.result = null; refreshPanel();
      api(act === 'send' ? 'diag_send' : 'diag_save', DIAG.note, DIAG.audio, DIAG.images).then(r => {
        DIAG.busy = false;
        if(act === 'save'){
          if(r && r.ok) toast(t('support.saved', {name: r.name}), 'ok');
          DIAG.result = r && r.ok ? null : {error: (r && r.error) || t('common.action_failed')};
        } else {
          DIAG.result = r && r.ok ? {code: r.code} : {error: (r && r.error) || t('common.action_failed')};
          if(r && r.ok) DIAG.note = '';
        }
        if(panelOpen() && PANEL && PANEL.render === diagHtml) refreshPanel();
      });
    }
  });
}
function openDiagReport(opener){
  DIAG.result = null; DIAG.busy = false; DIAG.preview = null;
  openPanel({title: t('support.title'), wide: true, opener, html: diagHtml(S), render: diagHtml, wire: diagWire});
  api('diag_preview').then(r => {
    DIAG.preview = r && r.ok ? r : {files: [], audio: false};
    if(PANEL && PANEL.render === diagHtml) refreshPanel();
  });
}
