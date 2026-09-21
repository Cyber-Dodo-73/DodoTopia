// DodoTopia : conditions d'utilisation obligatoires (#termsOverlay).
// Une modale bloquante, au-dessus de tout, tant que get_state().terms.required est vrai : le reste de
// l'interface est rendu inerte, Échap ne ferme rien, la tabulation reste dans la modale. L'acceptation
// n'est possible qu'une fois le texte défilé jusqu'en bas ET la case cochée. Refuser ferme l'application.
//
// Contrat backend consommé :
//   get_state().terms = {required, version, accepted_version, accepted_at}
//   api('get_terms', lang) -> {version, lang, summary: [6 chaînes], markdown, html}  (html : rendu sûr, sans donnée utilisateur)
//   api('accept_terms', version) -> état complet ; api('quit') ferme l'application
// Aperçu sans backend : window.MOCK_TERMS (fonction lang -> données, ou null pour simuler un échec).

const TERMS = {
  lang: null,        // langue du texte affiché ('fr' | 'en') ; null = pas encore choisie (termsDefaultLang à l'ouverture)
  data: null,        // dernière réponse de get_terms
  version: '',       // version demandée par l'état (get_state().terms.version)
  scrolled: false,   // le texte a été défilé jusqu'en bas (ou tient dans la zone)
  loading: false,
  inerted: [],       // éléments rendus inertes par la modale (pour ne retirer que ce qu'on a posé)
  ro: null,          // ResizeObserver de la zone défilante
};
// Libellés fixes de la modale : catalogue de l'interface (clés terms.*, langue de l'interface). Le TEXTE des
// conditions, lui, est en français ou en anglais au choix (TERMS.lang) : bouton « Read in English » / « Lire en français ».
// langue du texte proposée par défaut : celle de l'interface si elle est fr ou en, sinon l'anglais
function termsDefaultLang(){ const l = (window.I18N && I18N.lang) || 'fr'; return l === 'fr' || l === 'en' ? l : 'en'; }
function termsOpen(){ return $('termsOverlay').classList.contains('open'); }

// ------------------------------------------------ données : backend, ou source mock quand il n'y a pas de pywebview
function fetchTerms(lang){
  if(window.MOCK_TERMS !== undefined){
    const src = window.MOCK_TERMS;
    const d = typeof src === 'function' ? src(lang) : src;
    return new Promise(res => setTimeout(() => res(d && d.html !== undefined ? d : null), 120));
  }
  return api('get_terms', lang).then(r => (r && r.html !== undefined) ? r : null).catch(e => { console.error('CGU (get_terms) :', e); return null; });
}

// ------------------------------------------------ libellés fixes de la modale (langue de l'interface ; rappelée par applyLanguage)
function termsLabels(){
  const v = (TERMS.data && TERMS.data.version) || TERMS.version || '';
  txt('termsTitle', t('terms.title'));
  txt('termsSub', t('terms.sub', {v}));
  txt('termsGistTitle', t('terms.gist'));
  $('termsDoc').setAttribute('aria-label', t('terms.full'));
  txt('termsLang', TERMS.lang === 'en' ? t('terms.lang_fr') : t('terms.lang_en'));
  txt('termsCheckLbl', t('terms.check'));
  txt('termsAccept', t('terms.accept'));
  txt('termsRefuse', t('terms.refuse'));
  txt('termsLoadingTxt', t('terms.loading'));
  txt('termsErrorTxt', t('terms.error'));
  txt('termsRetry', t('common.retry'));
  txt('termsConfirmTxt', t('terms.confirm'));
  txt('termsQuit', t('terms.yes'));
  txt('termsStay', t('terms.no'));
  // le document (résumé + texte intégral) porte la langue du texte ; le reste de la modale suit l'interface
  $('termsDoc').setAttribute('lang', TERMS.lang || 'fr');
  if(!$('termsMain').hidden) termsCheckScroll();
}

// ------------------------------------------------ chargement du texte
function loadTerms(lang){
  TERMS.lang = lang === 'en' ? 'en' : 'fr';
  TERMS.loading = true; TERMS.scrolled = false;
  termsLabels();
  $('termsLoading').hidden = false; $('termsError').hidden = true; $('termsMain').hidden = true;
  $('termsConfirm').hidden = true;
  termsGate();
  const want = TERMS.lang;
  fetchTerms(want).then(d => {
    if(!termsOpen() || want !== TERMS.lang) return;     // fermée entre-temps, ou autre langue demandée
    TERMS.loading = false;
    TERMS.data = d;
    $('termsLoading').hidden = true;
    if(!d){ $('termsError').hidden = false; termsLabels(); termsGate(); setTimeout(() => $('termsRetry').focus(), 30); return; }
    termsLabels();
    $('termsGist').innerHTML = (d.summary || []).map(s => `<li>${esc(s)}</li>`).join('');
    const doc = $('termsDoc');
    $('termsText').innerHTML = d.html || '';   // HTML produit côté Python depuis legal/CGU-<lang>.md : jamais de donnée utilisateur
    doc.scrollTop = 0;
    $('termsMain').hidden = false;
    // un texte plus court que la zone compte comme lu : on vérifie une fois posé, puis à chaque redimensionnement
    requestAnimationFrame(() => termsCheckScroll());
    if(!TERMS.ro && window.ResizeObserver){ TERMS.ro = new ResizeObserver(() => termsCheckScroll()); TERMS.ro.observe(doc); }
  });
}

// ------------------------------------------------ défilement : lu jusqu'en bas ?
function termsCheckScroll(){
  const doc = $('termsDoc');
  if($('termsMain').hidden) return;
  const max = doc.scrollHeight - doc.clientHeight;
  const pct = max <= 0 ? 100 : Math.min(100, Math.round(doc.scrollTop / max * 100));
  if(max <= 8 || doc.scrollTop >= max - 8) TERMS.scrolled = true;
  html('termsPos', TERMS.scrolled ? icon('check') + `<span>${esc(plain(t('terms.pos_done')))}</span>` : esc(t('terms.pos', {p: pct})));
  $('termsPos').classList.toggle('is-done', TERMS.scrolled);
  termsGate();
}

// ------------------------------------------------ bouton Accepter : actif si lu ET coché ; raison visible sinon
function termsGate(){
  const ok = !TERMS.loading && !!TERMS.data && TERMS.scrolled && $('termsAgree').checked;
  const btn = $('termsAccept');
  if(btn.disabled !== !ok) btn.disabled = !ok;
  const why = $('termsWhy');
  const reason = (TERMS.loading || !TERMS.data) ? '' : !TERMS.scrolled ? t('terms.why_scroll') : !$('termsAgree').checked ? t('terms.why_check') : t('terms.ready');
  const whyHtml = reason ? icon(ok ? 'check' : 'arrow-right') + `<span>${esc(reason)}</span>` : '';
  if(why.dataset.html !== whyHtml){ why.dataset.html = whyHtml; why.innerHTML = whyHtml; }
  why.classList.toggle('is-ok', ok);
  why.hidden = !reason;
}

// ------------------------------------------------ ouverture / fermeture : au-dessus de tout, reste de la page inerte
function termsInert(on){
  if(on){
    TERMS.inerted = [];
    for(const el of document.body.children){
      if(el.id === 'termsOverlay' || el.tagName === 'SCRIPT' || el.hasAttribute('inert')) continue;
      el.setAttribute('inert', ''); TERMS.inerted.push(el);
    }
  }else{
    TERMS.inerted.forEach(el => el.removeAttribute('inert'));
    TERMS.inerted = [];
  }
}
function openTerms(version){
  TERMS.version = version || '';
  if(termsOpen()) return;
  $('termsAgree').checked = false;
  $('termsOverlay').classList.add('open');
  termsInert(true);
  loadTerms(TERMS.lang || termsDefaultLang());
  setTimeout(() => { if(termsOpen()) $('termsTitle').focus(); }, 30);
}
function closeTerms(){
  if(!termsOpen()) return;
  $('termsOverlay').classList.remove('open');
  termsInert(false);
  if(TERMS.ro){ TERMS.ro.disconnect(); TERMS.ro = null; }
  TERMS.data = null; TERMS.scrolled = false;
  // rend la main à l'application : premier élément utile de l'en-tête
  const first = document.querySelector('#tabs .tab.active') || $('btnHelp');
  if(first) setTimeout(() => first.focus(), 30);
}

// ------------------------------------------------ actions
function termsAccept(){
  const btn = $('termsAccept');
  if(btn.disabled || btn.classList.contains('is-loading')) return;
  const v = (TERMS.data && TERMS.data.version) || TERMS.version;
  btn.classList.add('is-loading');
  api('accept_terms', v).then(r => {
    btn.classList.remove('is-loading');
    // hors pywebview (aperçu mock), api() renvoie null : on simule l'état accepté
    if(r == null && window.MOCK_TERMS !== undefined && S && S.terms){
      S.terms = Object.assign({}, S.terms, {required: false, accepted_version: v, accepted_at: Date.now() / 1000});
      render(S);
      return;
    }
    if(r == null) toast(t('terms.accept_failed'), 'warn');
  }).catch(() => { btn.classList.remove('is-loading'); toast(t('terms.accept_failed'), 'warn'); });
}
function termsRefuse(){
  $('termsConfirm').hidden = false;
  $('termsRefuse').setAttribute('aria-expanded', 'true');
  setTimeout(() => $('termsStay').focus(), 20);
}
function termsStay(){
  $('termsConfirm').hidden = true;
  $('termsRefuse').setAttribute('aria-expanded', 'false');
  $('termsRefuse').focus();
}
function termsQuit(){
  const b = $('termsQuit'); b.classList.add('is-loading');
  api('quit').finally(() => setTimeout(() => b.classList.remove('is-loading'), 1500));
}

// ------------------------------------------------ vue : suit get_state().terms
view('terms', {sig: st => JSON.stringify(st.terms || null), draw: st => {
  const t = st.terms;
  if(t && t.required){
    if(termsOpen() && TERMS.version && t.version && t.version !== TERMS.version){ TERMS.version = t.version; loadTerms(TERMS.lang); }
    else openTerms(t.version);
  }else closeTerms();
}});

// ------------------------------------------------ branchements
$('termsDoc').addEventListener('scroll', termsCheckScroll, {passive: true});
$('termsAgree').onchange = termsGate;
$('termsAccept').onclick = termsAccept;
$('termsRefuse').onclick = termsRefuse;
$('termsStay').onclick = termsStay;
$('termsQuit').onclick = termsQuit;
$('termsRetry').onclick = () => loadTerms(TERMS.lang);
$('termsLang').onclick = () => loadTerms(TERMS.lang === 'fr' ? 'en' : 'fr');
// Échap inopérant, tabulation piégée : en phase de capture, avant les gestionnaires des autres modales
document.addEventListener('keydown', e => {
  if(!termsOpen()) return;
  if(e.key === 'Escape'){ e.preventDefault(); e.stopPropagation(); if(!$('termsConfirm').hidden) termsStay(); return; }
  if(e.key !== 'Tab') return;
  e.stopPropagation();
  trapFocus($('termsOverlay'), e);
}, true);
