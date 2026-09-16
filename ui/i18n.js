// DodoTopia : traductions cote navigateur. Script classique charge avant core.js ; expose les globales
// `I18N` et `t`. Meme grammaire de messages que i18n.py (Python) :
//   {name}                                   interpolation (les nombres sont formates selon la langue)
//   {n, plural, =0 {…} one {…} other {…}}    pluriel ; `#` dans une branche = le nombre formate
//   {x, select, a {…} b {…} other {…}}       selection sur une valeur texte
//   {{ et }}                                 accolades litterales (`}}` seulement hors des branches)
// Les branches acceptent des messages complets (imbrication). Une accolade fermante simple ferme toujours
// la branche en cours. Clé absente : catalogue de repli (fr), sinon `[cle]` avec un console.warn par cle.
//
// Chargement : I18N.load({lang, catalogue, fallback, meta}) avec le contenu de ui/i18n/<lang>.json
// (catalogue) et de fr.json (fallback) ; `meta` = _meta du catalogue. Puis I18N.applyDom() traduit
// les elements marques data-i18n / data-i18n-html / data-i18n-attr.
(function(){
  'use strict';
  const CATEGORIES = ['zero', 'one', 'two', 'few', 'many', 'other'];
  // nom de regle → categories produites ; la regle vient de _meta.plural, sinon de la langue
  const PLURAL_RULES = {
    fr: ['one', 'other'], en: ['one', 'other'], de: ['one', 'other'], es: ['one', 'other'], 'pt-BR': ['one', 'other'],
    it: ['one', 'other'], 'zh-CN': ['other'], ja: ['other'], th: ['other'],
  };
  const PRIMARY_TAG = {fr: 'fr', en: 'en', es: 'es', de: 'de', pt: 'pt-BR', zh: 'zh-CN', ja: 'ja', th: 'th'};
  const NAME_RE = /[A-Za-z0-9_.\-]+/y;
  const SELECTOR_RE = /=\d+|[A-Za-z0-9_.\-]+/y;

  class MessageError extends Error {}

  // ------------------------------------------------------------ analyse
  function parse(message){
    const r = parseBody(String(message), 0, 0);
    if(r.i < message.length) throw new MessageError('accolade fermante en trop a la position ' + r.i);
    return r.nodes;
  }

  function parseBody(s, i, depth){
    const nodes = []; let buf = '';
    const n = s.length;
    while(i < n){
      const c = s[i];
      if(c === '{'){
        if(s[i + 1] === '{'){ buf += '{'; i += 2; continue; }
        if(buf){ nodes.push(buf); buf = ''; }
        const r = parseArg(s, i + 1, depth);
        nodes.push(r.node); i = r.i;
      } else if(c === '}'){
        if(depth > 0){ if(buf) nodes.push(buf); return {nodes, i: i + 1}; }
        buf += '}'; i += (s[i + 1] === '}') ? 2 : 1;
      } else { buf += c; i++; }
    }
    if(depth > 0) throw new MessageError('accolade fermante manquante');
    if(buf) nodes.push(buf);
    return {nodes, i};
  }

  function skipWs(s, i){ while(i < s.length && /\s/.test(s[i])) i++; return i; }
  function matchAt(re, s, i){ re.lastIndex = i; const m = re.exec(s); return m ? m[0] : null; }

  function parseArg(s, i, depth){
    i = skipWs(s, i);
    const name = matchAt(NAME_RE, s, i);
    if(!name) throw new MessageError("nom d'argument attendu a la position " + i);
    i = skipWs(s, i + name.length);
    if(s[i] === '}') return {node: {kind: 'arg', name}, i: i + 1};
    if(s[i] !== ',') throw new MessageError('« } » ou « , » attendu apres {' + name + ' (position ' + i + ')');
    i = skipWs(s, i + 1);
    const kind = matchAt(NAME_RE, s, i) || '';
    if(kind !== 'plural' && kind !== 'select') throw new MessageError("type d'argument inconnu « " + kind + ' » pour {' + name + '}');
    i = skipWs(s, i + kind.length);
    if(s[i] !== ',') throw new MessageError('« , » attendu apres {' + name + ', ' + kind);
    i++;
    const branches = {};
    for(;;){
      i = skipWs(s, i);
      if(i >= s.length) throw new MessageError('accolade fermante manquante pour {' + name + ', ' + kind);
      if(s[i] === '}') break;
      const selector = matchAt(SELECTOR_RE, s, i);
      if(!selector) throw new MessageError('selecteur attendu dans {' + name + ', ' + kind + '} (position ' + i + ')');
      i = skipWs(s, i + selector.length);
      if(s[i] !== '{') throw new MessageError('« { » attendu apres le selecteur « ' + selector + ' » de {' + name + ', ' + kind + '}');
      const r = parseBody(s, i + 1, depth + 1);
      branches[selector] = r.nodes; i = r.i;
    }
    if(!('other' in branches)) throw new MessageError('branche « other » manquante dans {' + name + ', ' + kind + '}');
    return {node: {kind, name, branches}, i: i + 1};
  }

  // ------------------------------------------------------------ rendu
  const state = {lang: 'fr', catalogue: {}, fallback: {}, meta: {}, cache: {}, warned: new Set(), fmt: {}};

  function pluralRule(lang){
    if(lang === state.lang && state.meta && PLURAL_RULES[state.meta.plural]) return state.meta.plural;
    if(PLURAL_RULES[lang]) return lang;
    const p = PRIMARY_TAG[String(lang || '').split('-')[0].toLowerCase()];
    return PLURAL_RULES[p] ? p : 'en';
  }

  function plural(lang, n){
    const rule = pluralRule(lang);
    const v = Math.abs(Number(n));
    if(Number.isNaN(v)) return 'other';
    if(PLURAL_RULES[rule].length === 1) return 'other';
    if(rule === 'fr') return (Math.trunc(v) === 0 || Math.trunc(v) === 1) ? 'one' : 'other';
    return v === 1 ? 'one' : 'other';
  }

  function numberFormat(){
    if(!state.fmt.number) state.fmt.number = new Intl.NumberFormat(state.lang, {maximumFractionDigits: 3});
    return state.fmt.number;
  }
  function fmtNumber(n){ return numberFormat().format(n); }

  function paramText(v){
    if(typeof v === 'number') return fmtNumber(v);
    if(typeof v === 'boolean') return v ? 'true' : 'false';
    return String(v);
  }

  function render(nodes, params, number){
    let out = '';
    for(const node of nodes){
      if(typeof node === 'string'){ out += (number !== null && number !== undefined) ? node.split('#').join(number) : node; continue; }
      let value = params[node.name];
      if(node.kind === 'arg'){ out += (value === undefined || value === null) ? '{' + node.name + '}' : paramText(value); continue; }
      if(node.kind === 'plural'){
        let v = (typeof value === 'number') ? value : (value === undefined || value === null || value === '' ? NaN : Number(value));
        let body = null;
        if(!Number.isNaN(v)){
          for(const sel in node.branches){ if(sel[0] === '=' && Number(sel.slice(1)) === v){ body = node.branches[sel]; break; } }
          if(!body) body = node.branches[plural(state.lang, v)];
        }
        out += render(body || node.branches.other, params, Number.isNaN(v) ? '' : fmtNumber(v));
      } else {
        const key = (value === undefined || value === null) ? '' : String(value);
        out += render(node.branches[key] || node.branches.other, params, number);
      }
    }
    return out;
  }

  function format(message, params){ return render(parse(message), params || {}, null); }

  function warnOnce(key, text){ if(state.warned.has(key)) return; state.warned.add(key); console.warn(text); }

  function t(key, params){
    let src = state.catalogue[key];
    if(typeof src !== 'string'){
      src = state.fallback[key];
      if(typeof src !== 'string'){ warnOnce(key, 'i18n : cle absente « ' + key + ' » (' + state.lang + ')'); return '[' + key + ']'; }
    }
    let nodes = state.cache[key];
    if(!nodes){
      try { nodes = parse(src); }
      catch(e){ warnOnce(key, 'i18n : message mal forme « ' + key + ' » : ' + e.message); return src; }
      state.cache[key] = nodes;
    }
    return render(nodes, params || {}, null);
  }

  // ------------------------------------------------------------ formats Intl
  function toDate(ts){
    if(ts instanceof Date) return ts;
    const n = Number(ts);
    return new Date(n < 1e12 ? n * 1000 : n); // secondes (Python) ou millisecondes (JS)
  }
  // style : 'datetime' (defaut), 'date', 'time', 'long'
  function fmtDate(ts, style){
    const opts = {datetime: {dateStyle: 'medium', timeStyle: 'short'}, date: {dateStyle: 'medium'}, time: {timeStyle: 'short'},
      long: {dateStyle: 'long', timeStyle: 'short'}}[style || 'datetime'] || {dateStyle: 'medium', timeStyle: 'short'};
    const k = 'date:' + (style || 'datetime');
    if(!state.fmt[k]) state.fmt[k] = new Intl.DateTimeFormat(state.lang, opts);
    return state.fmt[k].format(toDate(ts));
  }
  // « il y a 3 j », « hier », « dans 5 min »
  function fmtRelative(ts, now){
    if(!state.fmt.rel) state.fmt.rel = new Intl.RelativeTimeFormat(state.lang, {numeric: 'auto', style: 'short'});
    let d = (toDate(ts).getTime() - (now === undefined ? Date.now() : toDate(now).getTime())) / 1000;
    const units = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
    for(const [unit, secs] of units){ if(Math.abs(d) >= secs) return state.fmt.rel.format(Math.round(d / secs), unit); }
    return state.fmt.rel.format(Math.round(d), 'second');
  }
  function compare(a, b){
    if(!state.fmt.coll) state.fmt.coll = new Intl.Collator(state.lang, {sensitivity: 'base', numeric: true});
    return state.fmt.coll.compare(String(a ?? ''), String(b ?? ''));
  }

  // ------------------------------------------------------------ DOM
  function applyDom(root){
    root = root || document;
    for(const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
    // reserve aux messages contenant du balisage sur, jamais de donnees utilisateur
    for(const el of root.querySelectorAll('[data-i18n-html]')) el.innerHTML = t(el.dataset.i18nHtml);
    for(const el of root.querySelectorAll('[data-i18n-attr]')){
      for(const pair of el.dataset.i18nAttr.split(';')){
        const idx = pair.indexOf(':');
        if(idx < 0) continue;
        const attr = pair.slice(0, idx).trim(), key = pair.slice(idx + 1).trim();
        if(attr && key) el.setAttribute(attr, t(key));
      }
    }
  }

  function load(opts){
    opts = opts || {};
    state.lang = opts.lang || 'fr';
    state.catalogue = opts.catalogue || {};
    state.fallback = opts.fallback || {};
    state.meta = opts.meta || state.catalogue._meta || {};
    state.cache = {}; state.fmt = {}; state.warned = new Set();
    I18N.lang = state.lang; I18N.meta = state.meta;
    try { document.documentElement.lang = state.lang; } catch(e){ /* hors navigateur */ }
  }

  const I18N = {
    lang: state.lang, meta: state.meta, CATEGORIES, PLURAL_RULES, MessageError,
    load, t, has: key => typeof state.catalogue[key] === 'string' || typeof state.fallback[key] === 'string',
    parse, format, plural, fmtNumber, fmtDate, fmtRelative, compare, applyDom,
  };
  globalThis.I18N = I18N;
  globalThis.t = t;
})();
