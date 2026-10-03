// DodoTopia : « Découvrir des morceaux » (catalogue partagé), compte Discord, espace d'administration et
// mise à jour. Tout vient de get_state().online (online.OnlineService.status()) ; aucune requête réseau n'est
// faite depuis le JS : les actions passent par les méthodes Api online_* / update_* et l'état revient au tick
// suivant.
//   — le catalogue vit dans la page Musique (vue « Découvrir ») : trouver, récupérer, jouer ;
//   — le compte est dans un panneau ouvert depuis l'avatar de l'en-tête ;
//   — la modération est dans un panneau réservé aux administrateurs (les droits restent vérifiés côté serveur) ;
//   — la mise à jour est dans Réglages › À propos et mises à jour (+ toast contextuel quand une action est utile).

const ONL = {q: '', sort: 'recent', tag: '', page: 1, timer: null, searched: false, loginUrl: '', pendingAt: 0, reportsAt: 0,
  // id du morceau que l'utilisateur vient d'ajouter : des qu'il est la, on l'emmene dessus.
  awaited: null,
  // cle du travail d'import par lien en cours : a la fin, le morceau est ouvert dans la bibliotheque
  importAwait: null};
try{ ONL.sort = localStorage.getItem('online.sort') || 'recent'; }catch(e){}

// tags de la liste blanche du serveur (online.SONG_TAGS) : libelles resolus au rendu
const SONG_TAG_LABELS = {
  piano: () => t('online.tag.piano'), flute: () => t('online.tag.flute'), lute: () => t('online.tag.lute'),
  violin: () => t('online.tag.violin'), harp: () => t('online.tag.harp'), percussion: () => t('online.tag.percussion'),
  pop: () => t('online.tag.pop'), rock: () => t('online.tag.rock'), classique: () => t('online.tag.classique'),
  'jeu-video': () => t('online.tag.jeu-video'), anime: () => t('online.tag.anime'), film: () => t('online.tag.film'),
  folk: () => t('online.tag.folk'), noel: () => t('online.tag.noel'), calme: () => t('online.tag.calme'),
  rapide: () => t('online.tag.rapide'), facile: () => t('online.tag.facile'), difficile: () => t('online.tag.difficile')};
const SONG_TAGS = Object.keys(SONG_TAG_LABELS);
const MAX_SONG_TAGS = 8;
function tagLabel(tag){ return SONG_TAG_LABELS[tag] ? SONG_TAG_LABELS[tag]() : String(tag || ''); }
const LICENSE_TEXT = {
  own: () => [t('online.license.own'), t('online.license.own_help')],
  public_domain: () => [t('online.license.public_domain'), t('online.license.public_domain_help')],
  cc: () => [t('online.license.cc'), t('online.license.cc_help')],
  unknown: () => [t('online.license.unknown'), t('online.license.unknown_help')]};
if(ONL.sort && !['recent', 'trending', 'likes', 'popular', 'title'].includes(ONL.sort)) ONL.sort = 'recent';

// libelles resolus au rendu (fonctions) : le catalogue de traduction peut changer a chaud
const UPDATE_KIND = {setup: () => t('online.update.kind.setup'), portable: () => t('online.update.kind.portable'),
  targz: () => t('online.update.kind.targz'), source: () => t('online.update.kind.source')};
const UPDATE_STATE = {idle: () => '', checking: () => t('online.update.state.checking'), available: () => t('online.update.state.available'),
  downloading: () => t('online.update.state.downloading'), ready: () => t('online.update.state.ready'),
  installing: () => t('online.update.state.installing'), error: () => t('online.update.state.error'), uptodate: () => t('online.update.state.uptodate')};
function updateKindText(kind){ return UPDATE_KIND[kind] ? UPDATE_KIND[kind]() : (kind || ''); }
function updateStateText(state){ return UPDATE_STATE[state] ? UPDATE_STATE[state]() : ''; }

function onlineOf(st){ return (st && st.online) || null; }
function userLabel(u){ return (u && (u.name || u.username || u.global_name)) || t('online.account.player'); }
// repli de l'avatar Discord (image absente ou hors ligne) : l'initiale du pseudo
function avatarFallback(img){
  const s = document.createElement('span');
  s.className = img.className + ' avatar--ini';
  s.textContent = img.dataset.ini || '?';
  img.replaceWith(s);
}
// « il y a 3 h », « hier »… jusqu'a 30 jours ; au-dela, la date courte dans la langue de l'interface
function agoText(v){
  if(!v) return '';
  const ms = typeof v === 'number' ? v * 1000 : Date.parse(String(v).replace(' ', 'T'));
  if(!ms || isNaN(ms)) return '';
  const d = (Date.now() - ms) / 1000;
  if(d < 86400 * 30) return I18N.fmtRelative(ms);
  return I18N.fmtDate(ms, 'date');
}
function itemAuthor(it){
  const who = (it.author && it.author.name) || it.uploader_name || '';
  return who ? t('online.discover.shared_by', {name: who}) : (it.artist || '');
}
// chef d'un salon en attente : la bibliothèque propose « Pour le salon »
function roomHostLobby(o){
  const R = o && o.room;
  const D = R && R.room;
  return !!(D && D.code && R.state !== 'idle' && D.state === 'lobby' && D.me && D.me.host);
}
function discoverOpen(){ return TAB === 'music' && MUSIC_VIEW === 'discover'; }

// ------------------------------------------------ panneau « Mon compte » (avatar de l'en-tête)
function accountHtml(st){
  const o = onlineOf(st);
  if(!o) return `<p class="hint left">${esc(t('online.account.unavailable'))}</p>`;
  const lg = o.login || {};
  const server = o.server_ok === true ? `<span class="chip chip--badge chip--ok">${esc(t('online.account.server_online'))}</span>`
    : o.server_ok === false ? `<span class="chip chip--badge chip--warn">${esc(t('online.account.server_unreachable'))}</span>`
    : `<span class="chip chip--badge">${esc(t('online.account.server_pending'))}</span>`;
  // L'adresse du serveur et sa version ne servent à aucune décision de l'utilisateur courant : elles
  // descendent dans un repli de diagnostic.
  const foot = `<details class="disclosure disclosure--inline"><summary>${esc(t('online.account.details'))}</summary>
      <div class="disclosure__body"><p class="hint left">${server}</p>
      ${o.server_url ? `<p class="hint left"><code class="path">${esc(o.server_url)}</code></p>` : ''}
      ${o.server_version ? `<p class="hint left">${esc(t('online.account.server_version', {version: o.server_version}))}</p>` : ''}</div></details>`;
  if(o.logged_in && o.user){
    const u = o.user;
    return `<div class="account-card">
        ${personHtml(u, 'avatar avatar--lg')}
        <div class="account-card__id">
          <div class="nm">${esc(userLabel(u))}</div>
          <div class="m">${esc(t('online.account.connected_discord'))}</div>
        </div>
        ${o.is_admin ? `<span class="chip chip--badge chip--info">${esc(t('online.account.admin_badge'))}</span>` : ''}
      </div>
      <p class="hint left">${esc(t('online.account.purpose'))}</p>
      <div class="btnrow">
        ${o.is_admin ? `<button class="btn btn--secondary btn--sm" type="button" data-act="admin">${esc(t('online.moderation.title'))}</button>` : ''}
        <button class="btn btn--secondary btn--sm" type="button" data-act="logout">${esc(t('online.account.logout'))}</button>
        <button class="btn btn--ghost btn--sm btn--danger-text" type="button" data-act="delete">${esc(t('online.account.delete'))}</button>
      </div>${foot}`;
  }
  if(lg.state === 'waiting'){
    const url = lg.url || ONL.loginUrl || '';
    const code = lg.user_code || '';
    // sans code : le navigateur revient tout seul vers DodoTopia après l'autorisation (rien à recopier)
    if(lg.mode === 'loopback' && !code){
      return `<div class="account-wait">
        <div class="account-wait__top"><span class="spinner" aria-hidden="true"></span>
          <span><b>${esc(t('online.account.waiting'))}</b> ${esc(t('online.account.waiting_browser'))}</span></div>
        <div class="btnrow">
          <button class="btn btn--discord btn--sm" type="button" data-act="openbrowser">${icon('discord')}<span>${esc(t('online.account.open_browser'))}</span></button>
          <button class="btn btn--ghost btn--sm" type="button" data-act="logincancel">${esc(t('common.cancel'))}</button>
        </div>
        <button class="btn btn--ghost btn--sm" type="button" data-act="usecode">${esc(t('online.account.use_code'))}</button>
      </div>${foot}`;
    }
    const left = lg.expires_in != null ? Math.max(0, Math.ceil(lg.expires_in / 60)) : null;
    // Le code est la protection anti-hameçonnage : la page web le demande avant d'envoyer vers Discord, donc
    // un lien reçu de quelqu'un d'autre ne peut pas connecter ce compte sur SON ticket.
    return `<div class="account-wait">
        <div class="account-wait__top"><span class="spinner" aria-hidden="true"></span>
          <span><b>${esc(t('online.account.waiting'))}</b> ${esc(code ? t('online.account.waiting_code') : t('online.account.waiting_link'))}</span></div>
        ${code ? `<div class="login-code" role="group" aria-label="${esc(t('online.account.code_group'))}">
          <span class="login-code__label">${esc(t('online.account.code_label'))}</span>
          <output class="login-code__value" aria-live="polite">${esc(code)}</output>
          <button class="btn btn--secondary btn--sm" type="button" data-act="copycode" title="${esc(t('online.account.copy_code'))}">${esc(t('online.account.copy'))}</button>
        </div>` : ''}
        <div class="btnrow">
          <button class="btn btn--cta btn--sm" type="button" data-act="openbrowser">${icon('globe')}<span>${esc(t('online.account.open_browser'))}</span></button>
        </div>
        <div class="field">
          <div class="field__control">
            <input class="input login-url" type="text" readonly value="${esc(url)}" aria-label="${esc(t('online.account.link_label'))}">
            <button class="btn btn--secondary btn--sm" type="button" data-act="copy">${esc(t('online.account.copy'))}</button>
          </div>
          <div class="field__help">${esc(t('online.account.link_help', {has_expiry: left != null ? 'yes' : 'no', min: left == null ? 0 : left}))}</div>
        </div>
        <button class="btn btn--ghost btn--sm" type="button" data-act="logincancel">${esc(t('common.cancel'))}</button>
      </div>${foot}`;
  }
  const blocked = o.server_ok === false ? t('online.account.blocked_server')
    : o.client_too_old ? t('online.account.blocked_old', {version: o.min_client || '?'}) : '';
  // texte d'accueil : balisage <b> sans donnee utilisateur, injecte tel quel
  return `${blocked ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(blocked)}</div></div>` : ''}
    ${lg.state === 'error' && lg.error ? `<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(lg.error)}</div></div>` : ''}
    <h3 class="account-why__t">${esc(t('online.account.benefits_title'))}</h3>
    <ul class="account-why">
      <li>${icon('share')}<span>${esc(t('online.account.benefit.share'))}</span></li>
      <li>${icon('users')}<span>${esc(t('online.account.benefit.rooms'))}</span></li>
      <li>${icon('heart')}<span>${esc(t('online.account.benefit.like'))}</span></li>
      <li>${icon('link')}<span>${esc(t('online.account.benefit.import'))}</span></li>
    </ul>
    <div class="btnrow"><button class="btn btn--discord" type="button" data-act="login"${blocked ? ' disabled' : ''}>${icon('discord')}<span>${esc(t('online.account.login'))}</span></button></div>
    <p class="hint left">${icon('shield')} ${esc(t('online.account.privacy'))}</p>
    <p class="hint left">${t('online.account.no_account')}</p>
    ${foot}`;
}
function accountWire(box){
  box.querySelectorAll('[data-act]').forEach(b => {
    b.onclick = () => {
      switch(b.dataset.act){
        case 'login':
          api('online_login').then(r => { if(r && r.url){ ONL.loginUrl = r.url; refreshPanel(); } });
          break;
        case 'logincancel': ONL.loginUrl = ''; api('online_login_cancel'); break;
        // pendant l'attente, online_login rouvre le navigateur sur le même ticket (même code)
        case 'openbrowser': api('online_login'); break;
        // autre appareil (téléphone) : on repart sur un ticket avec un code à recopier et un lien à copier
        case 'usecode': api('online_login', true).then(r => { if(r && r.url){ ONL.loginUrl = r.url; refreshPanel(); } }); break;
        case 'copy': {
          const inp = box.querySelector('.login-url');
          if(inp){ inp.select(); copyText(inp.value, t('online.account.link_copied')); }
          break;
        }
        case 'copycode': {
          const out = box.querySelector('.login-code__value');
          if(out) copyText(out.textContent.trim(), t('online.account.code_copied'));
          break;
        }
        case 'admin': adminPanel(); break;
        case 'logout':
          dialog({title: t('online.account.logout'), icon: 'user', ok: t('online.account.logout'), danger: true,
                  html: esc(t('online.account.logout_body'))})
            .then(yes => { if(yes) api('online_logout'); });
          break;
        case 'delete':
          dialog({title: t('online.account.delete_title'), icon: 'trash', ok: t('online.account.delete_confirm'), danger: true,
                  html: esc(t('online.account.delete_body'))})
            .then(yes => { if(yes) api('online_delete_account'); });
          break;
      }
    };
  });
}
function accountPanel(){
  openPanel({title: t('online.account.title'), opener: $('accountPill'),
             html: accountHtml(S), render: accountHtml, wire: accountWire});
}

// ------------------------------------------------ carte Mise à jour (Réglages › À propos et mises à jour)
function updateHtml(o){
  const u = (o && o.update) || {};
  const s = u.state || 'idle';
  const out = [];
  out.push(`<div class="update-row"><span class="m">${esc(t('online.update.installed'))}</span><b>${esc(u.current || '')}</b>
    ${u.kind ? `<span class="chip chip--badge">${esc(updateKindText(u.kind))}</span>` : ''}</div>`);
  if(u.latest && u.latest !== u.current){
    out.push(`<div class="update-row"><span class="m">${esc(t('online.update.available'))}</span><b>${esc(u.latest)}</b>
      ${u.mandatory ? `<span class="chip chip--badge chip--warn">${esc(t('online.update.mandatory'))}</span>` : ''}</div>`);
  }
  if(s === 'uptodate') out.push(`<div class="update-row"><span class="chip chip--badge chip--ok">${icon('check')}${esc(t('online.update.state.uptodate'))}</span></div>`);
  if(u.notes && ['available', 'downloading', 'ready'].indexOf(s) >= 0){
    out.push(`<div class="update-notes">${esc(u.notes)}</div>`);
  }
  if(s === 'downloading'){
    const pct = Math.max(0, Math.min(100, (u.progress || 0) * 100));
    out.push(`<div class="progress"><span>${esc(t('online.update.megabytes', {n: Number((u.done_mb || 0).toFixed(1))}))}</span>
      <div class="bar"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div>
      <span>${esc(t('online.update.megabytes', {n: Number((u.size_mb || 0).toFixed(1))}))}</span></div>`);
  }
  if(u.error) out.push(`<div class="notice notice--warn"><span class="notice__ic" aria-hidden="true">${icon('warn')}</span><div class="notice__text">${esc(u.error)}</div></div>`);
  let btns;
  if(s === 'checking' || s === 'installing'){
    btns = `<button class="btn btn--secondary btn--sm" type="button" disabled>${esc(updateStateText(s))}</button>`;
  } else if(s === 'available'){
    btns = `<button class="btn btn--cta btn--sm" type="button" data-act="udl">${icon('download')}<span>${esc(t('online.update.download'))}</span></button>
            <button class="btn btn--ghost btn--sm" type="button" data-act="udismiss">${esc(t('online.update.later'))}</button>`;
  } else if(s === 'downloading'){
    btns = `<button class="btn btn--secondary btn--sm" type="button" disabled>${esc(t('online.update.state.downloading'))}</button>`;
  } else if(s === 'ready'){
    btns = u.kind === 'setup'
      ? `<button class="btn btn--cta btn--sm" type="button" data-act="uinstall">${esc(t('online.update.install_restart'))}</button>`
      : `<button class="btn btn--cta btn--sm" type="button" data-act="ufolder">${icon('folder')}<span>${esc(t('online.update.open_folder'))}</span></button>`;
    btns += `<button class="btn btn--ghost btn--sm" type="button" data-act="udismiss">${esc(t('online.update.later'))}</button>`;
  } else {
    btns = `<button class="btn btn--secondary btn--sm" type="button" data-act="ucheck"${o && o.server_ok === false ? ` disabled title="${esc(t('online.update.server_unreachable'))}"` : ''}>${esc(t('online.update.check'))}</button>`;
  }
  out.push(`<div class="btnrow">${btns}</div>`);
  if(u.kind === 'source' && s === 'ready') out.push(`<p class="hint left">${esc(t('online.update.source_hint'))}</p>`);
  return out.join('');
}
function wireUpdate(box){
  box.querySelectorAll('[data-act]').forEach(b => {
    const m = {ucheck: 'update_check', udl: 'update_download', uinstall: 'update_install',
               udismiss: 'update_dismiss', ufolder: 'update_open_folder'}[b.dataset.act];
    if(m) b.onclick = () => api(m);
  });
}

// ------------------------------------------------ « Découvrir des morceaux »
function songIndexById(st, sid){
  const s = (st.songs || []).find(x => x.id === sid);
  return s ? s.index : -1;
}
function openLocal(sid){
  const i = songIndexById(S, sid);
  showMusicView('library');
  if(i >= 0) api('select_song', i);
  else toast(t('online.discover.not_in_library'), 'warn');
}
// Quatre colonnes fixes : morceau, partagé par, durée, action. La zone d'action a une largeur constante,
// donc passer de « Ajouter » à « Ajouté · Ouvrir » ne décale plus les titres des lignes voisines.
function libRowHtml(it, jobs, canRoom){
  const job = jobs[String(it.id)] || null;
  const busy = job && ['meta', 'downloading', 'importing'].indexOf(job.state) >= 0;
  const local = it.local || (job && job.state === 'done' && job.song_id) || null;
  const by = itemAuthor(it) || '—';
  const dur = it.duration_s ? fmt(it.duration_s) : '—';
  const when = agoText(it.created_at);
  const title = it.title || t('online.discover.untitled');
  let act;
  if(busy){
    const pct = Math.max(2, Math.min(100, (job.progress || 0) * 100));
    act = `<div class="dlprog" title="${esc(job.state === 'importing' ? t('online.discover.importing') : t('online.discover.downloading'))}">
      <div class="bar"><div class="fill" style="width:${pct.toFixed(0)}%"></div></div><span>${esc(t('online.discover.adding', {pct: Math.round(pct)}))}</span></div>`;
  } else if(job && job.state === 'error'){
    act = `<span class="chip chip--badge chip--warn" title="${esc(job.error || '')}">${esc(t('online.discover.failed'))}</span>
           <button class="btn btn--secondary btn--sm" type="button" data-act="dl" data-id="${esc(it.id)}">${icon('refresh')}<span>${esc(t('online.discover.retry'))}</span></button>`;
  } else if(local){
    act = `<button class="btn btn--secondary btn--sm" type="button" data-act="open" data-sid="${esc(local)}"
             title="${esc(t('online.discover.already_in_library'))}">${icon('check')}<span>${esc(t('online.discover.open'))}</span></button>`;
  } else if(it.local){
    act = `<span class="chip chip--badge chip--ok">${esc(t('online.discover.added'))}</span>`;
  } else {
    act = `<button class="btn btn--secondary btn--sm" type="button" data-act="dl" data-id="${esc(it.id)}"
             title="${esc(t('online.discover.add_title'))}">${icon('plus')}<span>${esc(t('online.discover.add'))}</span></button>`;
  }
  const tags = (Array.isArray(it.tags) ? it.tags : []).filter(x => SONG_TAG_LABELS[x]);
  const tagsHtml = tags.length ? `<span class="tags">${tags.map(x => `<span class="tag">${esc(tagLabel(x))}</span>`).join('')}</span>` : '';
  return `<div class="row row--online">
      <span class="tt"><span class="t" title="${esc(title)}">${esc(title)}</span>${when || tagsHtml ? `<span class="m">${esc(when)}${tagsHtml}</span>` : ''}</span>
      <span class="c-by" title="${esc(by)}">${esc(by)}</span>
      <span class="c-dur">${esc(dur)}</span>
      <div class="row__actions">
        ${likeButtonHtml(it, 'like')}
        ${it.page_url ? `<button class="iconbtn iconbtn--sm" type="button" data-act="share" data-id="${esc(it.id)}" title="${esc(t('share.title'))}" aria-label="${esc(t('share.song_aria', {title}))}" aria-haspopup="menu">${icon('share')}</button>` : ''}
        ${act}
        ${canRoom ? `<button class="btn btn--cta btn--sm" type="button" data-act="room" data-id="${esc(it.id)}" title="${esc(t('online.discover.for_room_title'))}">${esc(t('online.discover.for_room'))}</button>` : ''}
      </div>
    </div>`;
}
// bouton « J'aime » (morceau ou dessin) : cœur plein quand aimé, compteur toujours visible
function likeButtonHtml(it, act){
  const on = !!it.liked_by_me, n = Math.max(0, Number(it.likes) || 0);
  const label = on ? t('online.like.remove') : t('online.like.add');
  return `<button class="likebtn${on ? ' on' : ''}" type="button" data-act="${act}" data-id="${esc(it.id)}" aria-pressed="${on ? 'true' : 'false'}"
      title="${esc(label)}" aria-label="${esc(t('online.like.aria', {label, n}))}">${icon(on ? 'heart-fill' : 'heart')}<span>${esc(I18N.fmtNumber(n))}</span></button>`;
}
// clic sur un cœur : connexion requise (message), sinon bascule côté serveur ; l'état revient au tick
function toggleLike(o, method, id, items){
  if(!o || !o.logged_in){ toast(t('online.like.need_account'), 'info'); return; }
  const it = (items || []).find(x => String(x.id) === String(id));
  return api(method, id, !(it && it.liked_by_me));
}
// barre de tags de « Découvrir » : un seul filtre actif à la fois (le serveur filtre sur un tag)
function renderTagBar(lib){
  const bar = $('onlineTags');
  if(!bar) return;
  const cur = (lib && lib.tag) || '';
  const sig = cur + '|' + I18N.lang;
  if(!changed(bar, sig)) return;
  bar.innerHTML = [['', t('online.discover.all_tags')], ...SONG_TAGS.map(x => [x, tagLabel(x)])]
    .map(([v, l]) => `<button class="chip chip--sm${v === cur ? ' active' : ''}" type="button" data-tag="${esc(v)}" aria-pressed="${v === cur ? 'true' : 'false'}">${esc(l)}</button>`).join('');
  bar.querySelectorAll('[data-tag]').forEach(b => b.onclick = () => {
    ONL.tag = b.dataset.tag === ONL.tag ? '' : b.dataset.tag;
    ONL.searched = true; onlineSearchNow(1);
  });
}
function viewOnlineLib(st){
  const o = onlineOf(st);
  const list = $('onlineList');
  if(!list) return;
  // état du serveur, dans la vue qui en dépend
  const badge = $('onlineServer');
  let bt = t('online.discover.server.pending'), bc = 'chip chip--badge';
  if(!o){ bt = t('online.discover.server.down'); }
  else if(o.server_ok === true){ bt = t('online.discover.server.online'); bc += ' chip--ok'; }
  else if(o.server_ok === false){ bt = t('online.discover.server.offline'); bc += ' chip--warn'; }
  if(badge.className !== bc) badge.className = bc;
  txt('onlineServer', bt);
  setNotice('onlineOffline', o && o.server_ok === false
    ? {kind: 'warn', text: t('online.discover.offline_notice', {has_reason: o.offline_reason ? 'yes' : 'no', reason: o.offline_reason || ''})}
    : null);
  setNotice('onlineOld', o && o.client_too_old
    ? {kind: 'danger', text: t('online.discover.too_old', {version: o.min_client || '?'})}
    : null);
  const nt = $('onlineOfflineText');
  if(o && o.server_ok === false && nt && !nt.querySelector('button')){
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn--secondary btn--sm'; b.textContent = t('online.discover.retry');
    b.onclick = () => api('online_refresh');
    nt.appendChild(document.createTextNode(' ')); nt.appendChild(b);
  }

  const lib = (o && o.library) || {q: '', page: 1, pages: 0, total: 0, items: [], loading: false, error: '', at: 0};
  const jobs = (o && o.jobs && o.jobs.downloads) || {};
  const items = lib.items || [];
  ONL.page = lib.page || 1;
  if(document.activeElement !== $('onlineSearch') && $('onlineSearch').value !== (lib.q || '')){
    $('onlineSearch').value = lib.q || '';
    $('onlineSearchBox').classList.toggle('has', !!lib.q);
  }
  if($('onlineSort').value !== (lib.sort || ONL.sort)) $('onlineSort').value = lib.sort || ONL.sort;
  if(lib.at) ONL.tag = lib.tag || '';
  renderTagBar({tag: ONL.tag});
  $('onlineTags').hidden = !o || o.server_ok === false;
  txt('onlineCount', String(lib.total || items.length || 0));
  // première ouverture de la vue : on charge la page 1
  if(discoverOpen() && o && o.server_ok && !lib.at && !lib.loading && !ONL.searched){
    ONL.searched = true;
    api('online_search', ONL.q, 1, ONL.sort);
  }
  const canRoom = roomHostLobby(o);
  // L'ajout termine emmene au lecteur avec le morceau choisi : c'est la seule page ou l'on peut
  // regler son instrument et lancer. Sans cela il fallait revenir a la main par « Ma bibliotheque ».
  if(ONL.awaited){
    const j = jobs[String(ONL.awaited)];
    if(j && j.state === 'done' && j.song_id){ const sid = j.song_id; ONL.awaited = null; openLocal(sid); }
    else if(j && j.state === 'error') ONL.awaited = null;
  }
  if(!o || o.server_ok === false){
    // message a balisage <br> sans donnee utilisateur, injecte tel quel
    list.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon('offline')}</div>${t('online.discover.unavailable')}</div>`;
  } else if(lib.error){
    list.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon('warn')}</div>${esc(lib.error)}
      <div class="btnrow btnrow--center"><button class="btn btn--secondary btn--sm" type="button" data-act="retry">${esc(t('online.discover.retry'))}</button></div></div>`;
    const r = list.querySelector('[data-act="retry"]'); if(r) r.onclick = () => onlineSearchNow(ONL.page);
  } else if(!items.length && lib.loading){
    list.innerHTML = `<div class="empty"><div class="big" aria-hidden="true">${icon('spinner', 'ic--spin')}</div>${esc(t('online.discover.loading'))}</div>`;
  } else if(!items.length){
    list.innerHTML = lib.at
      ? `<div class="empty"><div class="big" aria-hidden="true">${icon('search')}</div>${esc(lib.tag && !lib.q ? t('online.discover.no_match_tag', {tag: tagLabel(lib.tag)}) : t('online.discover.no_match', {has_query: lib.q ? 'yes' : 'no', query: lib.q || ''}))}</div>`
      : `<div class="empty"><div class="big" aria-hidden="true">${icon('music')}</div>${esc(t('online.discover.empty_prompt'))}</div>`;
  } else {
    list.innerHTML = items.map(it => libRowHtml(it, jobs, canRoom)).join('');
    list.querySelectorAll('[data-act]').forEach(b => {
      b.onclick = () => {
        if(b.dataset.act === 'dl'){ ONL.awaited = b.dataset.id; api('online_download', b.dataset.id); }
        else if(b.dataset.act === 'open') openLocal(b.dataset.sid);
        else if(b.dataset.act === 'room'){
          // proposé au salon : retour direct à la page du salon (le téléchargement s'y affiche)
          api('room_set_song', Number(b.dataset.id)); toast(t('online.discover.proposed_to_room'), 'ok'); showMusicView('together');
        }
        else if(b.dataset.act === 'like') toggleLike(o, 'online_like_song', b.dataset.id, items);
        else if(b.dataset.act === 'share'){
          const it = items.find(x => String(x.id) === b.dataset.id);
          if(it) shareMenu({anchor: b, url: it.page_url, text: t('share.song_text', {title: it.title || t('online.discover.untitled')})});
        }
      };
    });
  }
  const pages = lib.pages || 0;
  $('onlinePager').hidden = pages < 2;
  txt('onlinePage', t('online.discover.page', {page: lib.page || 1, pages: pages || 1}));
  $('onlinePrev').disabled = (lib.page || 1) <= 1;
  $('onlineNext').disabled = (lib.page || 1) >= pages;
  const hint = $('onlineShareHint');
  if(o && o.server_ok !== false && !o.logged_in){
    txt('onlineShareHint', t('online.discover.share_hint.anonymous'));
    hint.hidden = false;
  } else if(o && o.logged_in){
    txt('onlineShareHint', t('online.discover.share_hint.logged'));
    hint.hidden = false;
  } else hint.hidden = true;
}
view('onlineLib', {sig: st => {
  const o = onlineOf(st);
  if(!o) return 'none|' + TAB + MUSIC_VIEW + I18N.lang;
  return JSON.stringify([o.server_ok, o.offline_reason, o.client_too_old, o.min_client, o.logged_in,
                         o.library, o.jobs && o.jobs.downloads, roomHostLobby(o), TAB, MUSIC_VIEW,
                         (st.songs || []).length, I18N.lang]);
}, draw: viewOnlineLib});

// ------------------------------------------------ espace d'administration (panneau réservé)
// Les droits sont vérifiés côté serveur : ce panneau ne fait que présenter les listes renvoyées.
function pendingRowHtml(it){
  const meta = [itemAuthor(it), it.duration_s ? fmt(it.duration_s) : '', agoText(it.created_at)].filter(Boolean).join(' · ');
  return `<div class="row row--online">
      <span class="n" aria-hidden="true">${icon('hourglass')}</span>
      <span class="tt"><span class="t">${esc(it.title || t('online.discover.untitled'))}</span><span class="m">${esc(meta)}</span></span>
      <div class="row__actions">
        <button class="btn btn--cta btn--sm" type="button" data-act="ok" data-id="${esc(it.id)}">${icon('check')}<span>${esc(t('online.moderation.publish'))}</span></button>
        <button class="btn btn--secondary btn--sm" type="button" data-act="no" data-id="${esc(it.id)}">${icon('close')}<span>${esc(t('online.moderation.reject'))}</span></button>
      </div>
    </div>`;
}
// Les listes d'administration se chargent seules dès qu'on est admin, puis se rafraîchissent au plus
// toutes les 30 s.
function loadAdminLists(o, force){
  const now = Date.now();
  const pend = o.pending || {}, reps = o.reports || {};
  if(force){ ONL.pendingAt = 0; ONL.reportsAt = 0; }
  if(!pend.loading && now - ONL.pendingAt > 30000){ ONL.pendingAt = now; api('online_pending', 1); }
  if(!reps.loading && now - ONL.reportsAt > 30000){ ONL.reportsAt = now; api('online_reports'); }
}
function adminHtml(st){
  const o = onlineOf(st);
  if(!o || !o.is_admin) return `<p class="hint left">${esc(t('online.moderation.restricted'))}</p>`;
  const pend = o.pending || {items: [], loading: false};
  const reps = o.reports || {items: [], loading: false, error: ''};
  const items = pend.items || [], ritems = reps.items || [];
  const pl = pend.loading && !items.length ? `<div class="empty">${esc(t('online.discover.loading'))}</div>`
    : pend.error ? `<div class="empty">${esc(pend.error)}</div>`
    : !items.length ? `<div class="empty">${esc(t('online.moderation.nothing_pending'))}</div>`
    : items.map(pendingRowHtml).join('');
  const rl = reps.loading && !ritems.length ? `<div class="empty">${esc(t('online.discover.loading'))}</div>`
    : reps.error ? `<div class="empty">${esc(reps.error)}</div>`
    : !ritems.length ? `<div class="empty">${esc(t('online.moderation.no_reports'))}</div>`
    : ritems.map(r => `<div class="row row--online">
        <span class="n" aria-hidden="true">${icon('flag')}</span>
        <span class="tt"><span class="t">${esc(r.song_title || ('#' + r.song_id))}</span>
          <span class="m">${esc([r.reason || '', r.reporter_name ? t('online.moderation.reported_by', {name: r.reporter_name}) : '', agoText(r.created_at)].filter(Boolean).join(' · '))}</span></span>
        <span class="row__actions">
          <button class="btn btn--secondary btn--sm" type="button" data-rep="keep" data-id="${esc(String(r.id))}">${esc(t('online.moderation.keep'))}</button>
          <button class="btn btn--danger btn--sm" type="button" data-rep="drop" data-id="${esc(String(r.id))}" data-title="${esc(r.song_title || '')}">${esc(t('online.moderation.remove_song'))}</button>
        </span>
      </div>`).join('');
  return `<p class="hint left">${esc(t('online.moderation.intro'))}</p>
    <section class="helpsec"><h3>${esc(t('online.moderation.pending_title', {n: pend.total != null ? pend.total : items.length}))}</h3><div class="list list--panel">${pl}</div></section>
    <section class="helpsec"><h3>${esc(t('online.moderation.reports_title', {n: ritems.length}))}</h3><div class="list list--panel">${rl}</div></section>
    <div class="btnrow"><button class="btn btn--secondary btn--sm" type="button" data-act="areload">${icon('refresh')}<span>${esc(t('online.moderation.refresh'))}</span></button></div>`;
}
function adminWire(box){
  box.querySelectorAll('[data-act="areload"]').forEach(b => b.onclick = () => {
    const o = onlineOf(S); if(o) loadAdminLists(o, true);
  });
  box.querySelectorAll('[data-act="ok"],[data-act="no"]').forEach(b => {
    const id = b.dataset.id;
    b.onclick = () => {
      if(b.dataset.act === 'ok') return api('online_moderate', id, 'approve', '');
      dialog({title: t('online.moderation.reject_title'), icon: 'close', ok: t('online.moderation.reject'), danger: true,
              html: `<label class="field"><span class="field__label">${esc(t('online.moderation.reject_reason_label'))}</span>
                <input class="input dlg-input" type="text" maxlength="120" placeholder="${esc(t('online.moderation.reject_placeholder'))}"></label>`})
        .then(yes => {
          const inp = $('dlgBody').querySelector('.dlg-input');
          if(yes) api('online_moderate', id, 'reject', inp ? inp.value.trim() : '');
        });
    };
  });
  box.querySelectorAll('[data-rep]').forEach(b => {
    const id = b.dataset.id;
    b.onclick = () => {
      if(b.dataset.rep === 'keep') return api('online_resolve_report', id, 'dismiss');
      dialog({title: t('online.moderation.remove_title'), icon: 'trash', ok: t('online.moderation.remove_ok'), danger: true,
              html: `<p>${esc(t('online.moderation.remove_body', {title: b.dataset.title || t('online.moderation.this_song')}))}</p>`})
        .then(yes => { if(yes) api('online_resolve_report', id, 'remove_song'); });
    };
  });
}
function adminPanel(){
  const o = onlineOf(S);
  if(o) loadAdminLists(o, true);
  openPanel({title: t('online.moderation.title'), wide: true, opener: $('accountPill'),
             html: adminHtml(S), render: adminHtml, wire: adminWire});
}
// les listes d'administration se chargent en fond dès qu'on est admin (compteur du panneau à jour)
view('onlineAdmin', {sig: st => {
  const o = onlineOf(st);
  return JSON.stringify(o ? [o.is_admin, o.pending, o.reports] : null);
}, draw: st => {
  const o = onlineOf(st);
  if(o && o.is_admin) loadAdminLists(o);
  if(PANEL && PANEL.render === adminHtml) refreshPanel();
}});

// ------------------------------------------------ pastille de compte (en-tête) et point de mise à jour
function viewAccountPill(st){
  const o = onlineOf(st);
  const pill = $('accountPill'), dot = $('settingsDot');
  if(!pill) return;
  if(!o){ pill.hidden = true; if(dot) dot.hidden = true; return; }
  pill.hidden = false;
  if(o.logged_in && o.user){
    pill.innerHTML = personHtml(o.user, 'avatar avatar--sm') + `<span>${esc(userLabel(o.user))}</span>`;
    pill.title = t('online.account.title');
    pill.setAttribute('aria-label', t('online.account.pill_label', {name: userLabel(o.user)}));
  } else {
    pill.innerHTML = `${icon('discord')}<span>${esc(t('online.account.sign_in'))}</span>`;
    pill.title = t('online.account.login');
    pill.setAttribute('aria-label', t('online.account.pill_label_anonymous'));
  }
  pill.classList.toggle('account--join', !(o.logged_in && o.user));
  const u = o.update || {};
  if(dot) dot.hidden = !(u.state === 'available' || u.state === 'ready');
  if(PANEL && PANEL.render === accountHtml) refreshPanel();
}
view('accountPill', {sig: st => {
  const o = onlineOf(st);
  return JSON.stringify(o ? [o.logged_in, o.user, o.is_admin, o.login, o.server_ok, (o.update || {}).state, ONL.loginUrl, I18N.lang] : null);
}, draw: viewAccountPill});

// ------------------------------------------------ invitation à se connecter avec Discord (tous les onglets)
// Affichée tant qu'on n'est pas connecté et que le serveur répond ; « Plus tard » la masque deux semaines
// (localStorage), la connexion la retire. Jamais pendant une attente de connexion ni si le client est trop vieux.
const DINVITE_KEY = 'discord.invite.until', DINVITE_SNOOZE_MS = 14 * 86400 * 1000;
function discordInviteWanted(o){
  if(!o || o.logged_in || o.server_ok !== true || o.client_too_old || (o.login || {}).state === 'waiting') return false;
  let until = 0;
  try{ until = Number(localStorage.getItem(DINVITE_KEY)) || 0; }catch(e){}
  return Date.now() >= until;
}
function discordLogin(){
  accountPanel();
  api('online_login').then(r => { if(r && r.url){ ONL.loginUrl = r.url; refreshPanel(); } });
}
function viewDiscordInvite(st){
  const box = $('discordInvite');
  if(!box) return;
  // pas pendant la découverte du premier lancement : elle a sa propre étape Discord
  const show = discordInviteWanted(onlineOf(st)) && !(typeof onbOpen === 'function' && onbOpen());
  box.hidden = !show;
  if(!show){ box.innerHTML = ''; return; }
  box.innerHTML = `<span class="dinvite__ic" aria-hidden="true">${icon('discord')}</span>
    <div class="dinvite__txt"><b>${esc(t('online.invite.title'))}</b><span>${esc(t('online.invite.text'))}</span></div>
    <button class="btn btn--discord btn--sm" type="button" data-act="join">${icon('discord')}<span>${esc(t('online.account.login'))}</span></button>
    <button class="btn btn--ghost btn--sm" type="button" data-act="later">${esc(t('online.invite.later'))}</button>`;
  box.querySelector('[data-act="join"]').onclick = discordLogin;
  box.querySelector('[data-act="later"]').onclick = () => {
    try{ localStorage.setItem(DINVITE_KEY, String(Date.now() + DINVITE_SNOOZE_MS)); }catch(e){}
    box.hidden = true; box.innerHTML = '';
  };
}
view('discordInvite', {sig: st => {
  const o = onlineOf(st);
  return JSON.stringify(o ? [o.logged_in, o.server_ok, o.client_too_old, (o.login || {}).state, I18N.lang,
    typeof onbOpen === 'function' && onbOpen()] : null);
}, draw: viewDiscordInvite});

// ------------------------------------------------ recherche, tri, pagination
function onlineSearchNow(page){
  ONL.page = page || 1;
  api('online_search', ONL.q, ONL.page, ONL.sort, ONL.tag, '');
}

// ------------------------------------------------ import par lien (bouton « Lien » de la bibliothèque)
// Le serveur va chercher le fichier (Online Sequencer, BitMidi, lien direct .mid) ; le client le vérifie comme tout
// téléchargement. À la fin, le morceau est ouvert dans la bibliothèque (voir la vue importWatch).
function importUrlDialog(prefill, error){
  const o = onlineOf(S);
  const logged = !!(o && o.logged_in);
  const html = `<p>${esc(t('online.import.intro'))}</p>
    ${logged ? '' : `<div class="notice notice--info"><span class="notice__ic" aria-hidden="true">${icon('user')}</span><div class="notice__text">${esc(t('online.import.need_account'))}</div></div>`}
    <label class="field"><span class="field__label">${esc(t('online.import.label'))}</span>
      <input class="input dlg-input importurl__in" type="url" inputmode="url" spellcheck="false" autocomplete="off" maxlength="2000"
             placeholder="https://onlinesequencer.net/1234567" value="${esc(prefill || '')}"${error ? ' aria-invalid="true"' : ''}></label>
    ${error ? `<p class="field__error" role="alert">${esc(error)}</p>` : ''}
    <ul class="importurl__ex">
      <li><b>Online Sequencer</b> · <code>https://onlinesequencer.net/1234567</code></li>
      <li><b>BitMidi</b> · <code>https://bitmidi.com/…-mid</code></li>
      <li><b>${esc(t('online.import.direct'))}</b> · <code>https://…/morceau.mid</code></li>
    </ul>
    <p class="hint left">${esc(t('online.import.rights'))}</p>`;
  const done = dialog({title: t('online.import.title'), icon: 'link', ok: t('online.import.ok'), wide: true, html});
  const inp = $('dlgBody').querySelector('.importurl__in');
  if(inp){
    $('dlgOk').disabled = !logged || !inp.value.trim();
    inp.oninput = () => { $('dlgOk').disabled = !logged || !inp.value.trim(); };
    inp.onkeydown = e => { e.stopPropagation(); if(e.key === 'Enter' && !$('dlgOk').disabled) $('dlgOk').click(); if(e.key === 'Escape') dlgClose(false); };
    setTimeout(() => { inp.focus(); inp.select(); }, 40);
  }
  return done.then(yes => {
    const url = inp ? inp.value.trim() : '';
    if(!yes || !url) return null;
    return api('online_import_url', url).then(r => {
      if(r && r.ok){ ONL.importAwait = r.key; toast(t('online.import.started'), 'info'); return r; }
      if(r && r.error) return importUrlDialog(url, r.error);
      return r;
    });
  });
}
// fin d'un import par lien lancé ici : le morceau est sélectionné dans « Ma bibliothèque »
view('importWatch', {sig: st => {
  const o = onlineOf(st);
  const j = ONL.importAwait && o && o.jobs && o.jobs.imports ? o.jobs.imports[ONL.importAwait] : null;
  return j ? j.state + '|' + (j.song_id || '') + '|' + (st.songs || []).length : '';
}, draw: st => {
  const o = onlineOf(st);
  const j = ONL.importAwait && o && o.jobs && o.jobs.imports ? o.jobs.imports[ONL.importAwait] : null;
  if(!j) return;
  if(j.state === 'error'){ ONL.importAwait = null; return; }
  if(j.state === 'done' && j.song_id && songIndexById(st, j.song_id) >= 0){
    ONL.importAwait = null;
    showTab('music'); openLocal(j.song_id);
  }
}});
if($('btnImportUrl')) $('btnImportUrl').onclick = () => importUrlDialog('');

// ------------------------------------------------ partage d'un morceau : métadonnées et engagement
// Formulaire du menu « Partager » de la bibliothèque : tags (8 au plus), instrument, source, licence et case
// obligatoire « J'ai le droit de partager ce fichier ». Le serveur revalide tout.
function shareSongDialog(s){
  const st = S || {};
  const again = !!s.online_id;
  const insts = (st.instruments || []).slice().sort((a, b) => I18N.compare(instrumentDisplayName(a), instrumentDisplayName(b)));
  const curInst = st.instrument_id || '';
  const lic = 'unknown';
  const html = `<p>${t('music.library.share.body', {name: `<b>${esc(s.name)}</b>`})}</p>
    <fieldset class="sharefs"><legend class="field__label">${esc(t('online.sharef.tags'))}</legend>
      <div class="chips sharetags">${SONG_TAGS.map(x => `<label class="chip chip--sm chip--check"><input type="checkbox" value="${esc(x)}"><span>${esc(tagLabel(x))}</span></label>`).join('')}</div>
      <p class="field__help sharetags__n" aria-live="polite"></p></fieldset>
    <label class="field"><span class="field__label">${esc(t('online.sharef.instrument'))}</span>
      <select class="select share__inst"><option value="">${esc(t('online.sharef.instrument_none'))}</option>
        ${insts.map(i => `<option value="${esc(i.id)}"${i.id === curInst ? ' selected' : ''}>${esc(instrumentDisplayName(i))}</option>`).join('')}</select></label>
    <div class="sharerow">
      <label class="field"><span class="field__label">${esc(t('online.sharef.source_url'))}</span>
        <input class="input share__src" type="url" maxlength="500" spellcheck="false" placeholder="https://…" value="${esc(s.source_url || '')}"></label>
      <label class="field"><span class="field__label">${esc(t('online.sharef.source_name'))}</span>
        <input class="input share__srcname" type="text" maxlength="60" placeholder="${esc(t('online.sharef.source_name_ph'))}" value="${esc(s.source_name || '')}"></label>
    </div>
    <p class="field__error share__srcerr" hidden>${esc(t('online.share.error.bad_source_url'))}</p>
    <label class="field"><span class="field__label">${esc(t('online.sharef.license'))}</span>
      <select class="select share__lic">${Object.keys(LICENSE_TEXT).map(k => `<option value="${k}"${k === lic ? ' selected' : ''}>${esc(LICENSE_TEXT[k]()[0])}</option>`).join('')}</select>
      <span class="field__help share__lichelp"></span></label>
    <label class="checkline"><input type="checkbox" class="share__rights"><span>${esc(t('online.sharef.rights'))}</span></label>
    <p class="hint left">${esc(t('music.library.share.note'))}</p>`;
  const done = dialog({title: again ? t('music.library.share.title_again') : t('music.library.share.title'), icon: 'cloud-up',
                       ok: again ? t('music.library.share.ok_again') : t('music.library.share.ok'), wide: true, html});
  const box = $('dlgBody');
  const q = sel => box.querySelector(sel);
  const boxes = [...box.querySelectorAll('.sharetags input')];
  const srcOk = () => { const v = q('.share__src').value.trim(); return !v || /^https:\/\/[^\s/@]+\.[^\s/@]+(\/\S*)?$/i.test(v); };
  const sync = () => {
    const n = boxes.filter(b => b.checked).length;
    boxes.forEach(b => { b.disabled = !b.checked && n >= MAX_SONG_TAGS; b.parentElement.classList.toggle('active', b.checked); });
    q('.sharetags__n').textContent = t('online.sharef.tags_count', {n, max: MAX_SONG_TAGS});
    q('.share__lichelp').textContent = LICENSE_TEXT[q('.share__lic').value]()[1];
    const okSrc = srcOk();
    q('.share__srcerr').hidden = okSrc;
    $('dlgOk').disabled = !q('.share__rights').checked || !okSrc;
  };
  boxes.forEach(b => b.onchange = sync);
  ['.share__lic', '.share__rights'].forEach(k => q(k).onchange = sync);
  q('.share__src').oninput = sync;
  box.querySelectorAll('input[type=url],input[type=text]').forEach(i => i.onkeydown = e => e.stopPropagation());
  sync();
  return done.then(yes => {
    if(!yes || !q('.share__rights').checked) return null;
    const meta = {tags: boxes.filter(b => b.checked).map(b => b.value), instrument: q('.share__inst').value,
      source_url: q('.share__src').value.trim(), source_name: q('.share__srcname').value.trim(),
      license: q('.share__lic').value, rights: true};
    return api('online_share', s.id, meta);
  });
}
if($('onlineSearch')){
  $('onlineSearch').oninput = () => {
    const v = $('onlineSearch').value;
    $('onlineSearchBox').classList.toggle('has', !!v);
    clearTimeout(ONL.timer);
    ONL.timer = setTimeout(() => { ONL.q = v.trim(); ONL.searched = true; onlineSearchNow(1); }, 400);   // débounce 400 ms
  };
  $('onlineSearch').onkeydown = e => {
    e.stopPropagation();
    if(e.key === 'Escape'){ $('onlineSearch').value = ''; $('onlineSearch').oninput(); }
    if(e.key === 'Enter'){ clearTimeout(ONL.timer); ONL.q = $('onlineSearch').value.trim(); ONL.searched = true; onlineSearchNow(1); }
  };
  $('onlineSearchClr').onclick = () => { $('onlineSearch').value = ''; $('onlineSearch').oninput(); $('onlineSearch').focus(); };
  $('onlineSort').onchange = () => {
    ONL.sort = $('onlineSort').value;
    try{ localStorage.setItem('online.sort', ONL.sort); }catch(e){}
    ONL.searched = true; onlineSearchNow(1);
  };
  $('onlinePrev').onclick = () => onlineSearchNow(Math.max(1, ONL.page - 1));
  $('onlineNext').onclick = () => onlineSearchNow(ONL.page + 1);
  $('btnOnlineRefresh').onclick = () => {
    api('online_refresh');                       // santé du serveur + /api/me
    ONL.searched = true; onlineSearchNow(ONL.page);
  };
  $('onlineSort').value = ONL.sort;
}
if($('accountPill')) $('accountPill').onclick = () => accountPanel();
