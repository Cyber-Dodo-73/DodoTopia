// DodoTopia : onglet « En ligne » (compte Discord, bibliothèque MIDI en ligne, modération admin, mise à jour).
// Tout vient de get_state().online (online.OnlineService.status()) ; aucune requête réseau n'est faite depuis le JS :
// les actions passent par les méthodes Api online_* / update_* et l'état revient au tick suivant.

const ONL = {q: '', sort: 'recent', page: 1, timer: null, searched: false, loginUrl: '', pendingAt: 0, reportsAt: 0};
try{ ONL.sort = localStorage.getItem('online.sort') || 'recent'; }catch(e){}

const UPDATE_KIND = {setup: 'installée', portable: 'portable', targz: 'archive Linux', source: 'sources'};
const UPDATE_STATE = {idle: '', checking: 'Vérification…', available: 'Mise à jour disponible', downloading: 'Téléchargement…',
  ready: 'Prête à installer', installing: 'Installation…', error: 'Échec', uptodate: 'À jour'};

function onlineOf(st){ return (st && st.online) || null; }
function userLabel(u){ return (u && (u.name || u.username || u.global_name)) || 'Joueur'; }
// repli de l'avatar Discord (image absente ou hors ligne) : l'initiale du pseudo
function avatarFallback(img){
  const s = document.createElement('span');
  s.className = img.className + ' avatar--ini';
  s.textContent = img.dataset.ini || '?';
  img.replaceWith(s);
}
function agoText(v){
  if(!v) return '';
  const t = typeof v === 'number' ? v * 1000 : Date.parse(String(v).replace(' ', 'T'));
  if(!t || isNaN(t)) return '';
  const d = (Date.now() - t) / 1000;
  if(d < 3600) return "à l'instant";
  if(d < 86400) return `il y a ${Math.floor(d / 3600)} h`;
  if(d < 86400 * 30) return `il y a ${Math.floor(d / 86400)} j`;
  return new Date(t).toLocaleDateString('fr-FR');
}
function itemAuthor(it){
  return (it.author && it.author.name) || it.uploader_name || it.artist || '';
}
// chef d'un salon en attente : la bibliothèque propose « Pour le salon »
function roomHostLobby(o){
  const R = o && o.room;
  const D = R && R.room;
  return !!(D && D.code && R.state !== 'idle' && D.state === 'lobby' && D.me && D.me.host);
}

// ------------------------------------------------ carte Compte
function accountHtml(st, o){
  if(!o) return `<div class="hint left">Le client réseau n'est pas disponible dans cette version.</div>`;
  const lg = o.login || {};
  if(o.logged_in && o.user){
    const u = o.user;
    return `<div class="account-card">
      ${personHtml(u, 'avatar avatar--lg')}
      <div class="account-card__id">
        <div class="nm">${esc(userLabel(u))}</div>
        <div class="m">Connecté avec Discord</div>
      </div>
      ${o.is_admin ? '<span class="chip chip--badge chip--info" title="Tu peux valider les morceaux déposés">admin</span>' : ''}
      <button class="btn btn--secondary btn--sm" type="button" data-act="logout">Se déconnecter</button>
    </div>`;
  }
  if(lg.state === 'waiting'){
    const url = lg.url || ONL.loginUrl || '';
    const left = lg.expires_in != null ? Math.max(0, Math.ceil(lg.expires_in / 60)) : null;
    return `<div class="account-wait">
      <div class="account-wait__top"><span class="spinner" aria-hidden="true"></span>
        <span><b>En attente…</b> ouvre le lien dans ton navigateur et autorise DodoTopia.</span></div>
      <div class="field">
        <div class="field__control">
          <input class="input login-url" type="text" readonly value="${esc(url)}" aria-label="Lien de connexion Discord">
          <button class="btn btn--secondary btn--sm" type="button" data-act="copy">Copier</button>
        </div>
        <div class="field__help">Le lien marche aussi depuis un téléphone${left != null ? ` · il expire dans ${left} min` : ''}.</div>
      </div>
      <button class="btn btn--ghost btn--sm" type="button" data-act="logincancel">${esc(LABELS.cancel)}</button>
    </div>`;
  }
  const dis = (o.server_ok === false || o.client_too_old) ? ' disabled' : '';
  return `${lg.state === 'error' && lg.error ? `<div class="notice notice--warn"><span class="notice__ic">⚠️</span><div class="notice__text">${esc(lg.error)}</div></div>` : ''}
    <div class="account-out">
      <button class="btn btn--cta" type="button" data-act="login"${dis}>Se connecter avec Discord</button>
      <div class="hint left">Un compte sert à partager tes musiques et à jouer en salon. DodoTopia ne lit que ton pseudo et ton avatar.</div>
    </div>`;
}

function viewOnlineAccount(st){
  const o = onlineOf(st);
  const box = $('onlineAccount');
  if(!box) return;
  // etat du serveur
  const badge = $('onlineServer');
  let bt = 'serveur…', bc = 'chip chip--badge';
  if(!o){ bt = 'hors service'; }
  else if(o.server_ok === true){ bt = 'serveur en ligne'; bc += ' chip--ok'; }
  else if(o.server_ok === false){ bt = 'hors ligne'; bc += ' chip--warn'; }
  if(badge.className !== bc) badge.className = bc;
  txt('onlineServer', bt);
  txt('onlineServerUrl', o && o.server_url ? `Serveur : ${o.server_url}${o.server_version ? ' · v' + o.server_version : ''}` : '');
  setNotice('onlineOffline', o && o.server_ok === false
    ? {kind: 'warn', text: `Serveur injoignable${o.offline_reason ? ' : ' + o.offline_reason : ''}. La bibliothèque et les salons sont indisponibles.`}
    : null);
  setNotice('onlineOld', o && o.client_too_old
    ? {kind: 'danger', text: `Mets à jour DodoTopia pour utiliser les salons (version minimale ${o.min_client || '?'}).`}
    : null);
  // bouton Réessayer dans la notice hors ligne (ajouté une fois)
  const nt = $('onlineOfflineText');
  if(o && o.server_ok === false && nt && !nt.querySelector('button')){
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn--secondary btn--sm'; b.textContent = 'Réessayer';
    b.onclick = () => api('online_refresh');
    nt.appendChild(document.createTextNode(' ')); nt.appendChild(b);
  }
  box.innerHTML = accountHtml(st, o);
  box.querySelectorAll('[data-act]').forEach(b => {
    b.onclick = () => {
      switch(b.dataset.act){
        case 'login':
          api('online_login').then(r => { if(r && r.url){ ONL.loginUrl = r.url; if(S) render(S); } });
          break;
        case 'logincancel': ONL.loginUrl = ''; api('online_login_cancel'); break;
        case 'copy': {
          const inp = box.querySelector('.login-url');
          if(inp){ inp.select(); copyText(inp.value, 'Lien copié'); }
          break;
        }
        case 'logout':
          dialog({title: 'Se déconnecter', icon: '🌐', ok: 'Se déconnecter', danger: true,
                  html: 'Tu quitteras aussi le salon en cours. Tes musiques locales ne changent pas.'})
            .then(yes => { if(yes) api('online_logout'); });
          break;
      }
    };
  });
}
view('onlineAccount', {sig: st => {
  const o = onlineOf(st);
  return JSON.stringify(o ? [o.server_ok, o.offline_reason, o.server_url, o.server_version, o.client_too_old, o.min_client,
    o.logged_in, o.user, o.is_admin, o.login, ONL.loginUrl] : null);
}, draw: viewOnlineAccount});

// ------------------------------------------------ carte Mise à jour
function updateHtml(o){
  const u = (o && o.update) || {};
  const s = u.state || 'idle';
  const out = [];
  out.push(`<div class="update-row"><span class="m">Version installée</span><b>${esc(u.current || '')}</b>
    ${u.kind ? `<span class="chip chip--badge">${esc(UPDATE_KIND[u.kind] || u.kind)}</span>` : ''}</div>`);
  if(u.latest && u.latest !== u.current){
    out.push(`<div class="update-row"><span class="m">Disponible</span><b>${esc(u.latest)}</b>
      ${u.mandatory ? '<span class="chip chip--badge chip--warn">obligatoire</span>' : ''}</div>`);
  }
  if(s === 'uptodate') out.push(`<div class="update-row"><span class="chip chip--badge chip--ok">✓ À jour</span></div>`);
  if(u.notes && ['available', 'downloading', 'ready'].indexOf(s) >= 0){
    out.push(`<div class="update-notes">${esc(u.notes)}</div>`);
  }
  if(s === 'downloading'){
    const pct = Math.max(0, Math.min(100, (u.progress || 0) * 100));
    out.push(`<div class="progress"><span>${(u.done_mb || 0).toFixed(1)} Mo</span>
      <div class="bar"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div>
      <span>${(u.size_mb || 0).toFixed(1)} Mo</span></div>`);
  }
  if(u.error) out.push(`<div class="notice notice--warn"><span class="notice__ic">⚠️</span><div class="notice__text">${esc(u.error)}</div></div>`);
  let btns;
  if(s === 'checking' || s === 'installing'){
    btns = `<button class="btn btn--secondary btn--sm" type="button" disabled>${esc(UPDATE_STATE[s])}</button>`;
  } else if(s === 'available'){
    btns = `<button class="btn btn--cta btn--sm" type="button" data-act="udl">⬇ Télécharger</button>
            <button class="btn btn--ghost btn--sm" type="button" data-act="udismiss">Plus tard</button>`;
  } else if(s === 'downloading'){
    btns = `<button class="btn btn--secondary btn--sm" type="button" disabled>Téléchargement…</button>`;
  } else if(s === 'ready'){
    btns = u.kind === 'setup'
      ? `<button class="btn btn--cta btn--sm" type="button" data-act="uinstall">Installer et redémarrer</button>`
      : `<button class="btn btn--cta btn--sm" type="button" data-act="ufolder">📁 Ouvrir le dossier</button>`;
    btns += `<button class="btn btn--ghost btn--sm" type="button" data-act="udismiss">Plus tard</button>`;
  } else {
    btns = `<button class="btn btn--secondary btn--sm" type="button" data-act="ucheck"${o && o.server_ok === false ? ' disabled' : ''}>Vérifier les mises à jour</button>`;
  }
  out.push(`<div class="btnrow">${btns}</div>`);
  if(u.kind === 'source' && s === 'ready') out.push(`<div class="hint left">Version lancée depuis les sources : remplace les fichiers à la main.</div>`);
  return out.join('');
}
function viewOnlineUpdate(st){
  const o = onlineOf(st);
  const box = $('onlineUpdate');
  if(!box) return;
  box.innerHTML = updateHtml(o);
  box.querySelectorAll('[data-act]').forEach(b => {
    const m = {ucheck: 'update_check', udl: 'update_download', uinstall: 'update_install',
               udismiss: 'update_dismiss', ufolder: 'update_open_folder'}[b.dataset.act];
    if(m) b.onclick = () => api(m);
  });
}
view('onlineUpdate', {sig: st => JSON.stringify((onlineOf(st) || {}).update || null) + '|' + ((onlineOf(st) || {}).server_ok),
  draw: viewOnlineUpdate});

// ------------------------------------------------ bibliothèque en ligne
function libRowHtml(it, jobs, canRoom){
  const job = jobs[String(it.id)] || null;
  const busy = job && ['meta', 'downloading', 'importing'].indexOf(job.state) >= 0;
  const local = it.local || (job && job.state === 'done');
  const meta = [itemAuthor(it), it.duration_s ? fmt(it.duration_s) : '',
    `${it.downloads || 0} téléchargement${(it.downloads || 0) > 1 ? 's' : ''}`, agoText(it.created_at)].filter(Boolean).join(' · ');
  let act;
  if(busy){
    const pct = Math.max(2, Math.min(100, (job.progress || 0) * 100));
    act = `<div class="dlprog" title="${esc(job.state === 'importing' ? 'Import…' : 'Téléchargement…')}">
      <div class="bar"><div class="fill" style="width:${pct.toFixed(0)}%"></div></div><span>${pct.toFixed(0)} %</span></div>`;
  } else if(job && job.state === 'error'){
    act = `<button class="btn btn--secondary btn--sm" type="button" data-act="dl" data-id="${esc(it.id)}" title="${esc(job.error || '')}">↻ Réessayer</button>`;
  } else if(local){
    act = `<span class="chip chip--badge chip--ok" title="Déjà dans ta bibliothèque">✓ Déjà présente</span>`;
  } else {
    act = `<button class="btn btn--secondary btn--sm" type="button" data-act="dl" data-id="${esc(it.id)}">⬇ Télécharger</button>`;
  }
  return `<div class="row row--online">
      <span class="n">♪</span>
      <span class="tt"><span class="t">${esc(it.title || 'Sans titre')}</span><span class="m">${esc(meta)}</span></span>
      <div class="row__actions">
        ${canRoom ? `<button class="btn btn--cta btn--sm" type="button" data-act="room" data-id="${esc(it.id)}" title="Choisir ce morceau pour ton salon">🌐 Salon</button>` : ''}
        ${act}
      </div>
    </div>`;
}
function viewOnlineLib(st){
  const o = onlineOf(st);
  const list = $('onlineList');
  if(!list) return;
  const lib = (o && o.library) || {q: '', page: 1, pages: 0, total: 0, items: [], loading: false, error: '', at: 0};
  const jobs = (o && o.jobs && o.jobs.downloads) || {};
  const items = lib.items || [];
  ONL.page = lib.page || 1;
  if(document.activeElement !== $('onlineSearch') && $('onlineSearch').value !== (lib.q || '')){
    $('onlineSearch').value = lib.q || '';
    $('onlineSearchBox').classList.toggle('has', !!lib.q);
  }
  if($('onlineSort').value !== (lib.sort || ONL.sort)) $('onlineSort').value = lib.sort || ONL.sort;
  txt('onlineCount', String(lib.total || items.length || 0));
  // premiere ouverture de l'onglet : on charge la page 1
  if(TAB === 'online' && o && o.server_ok && !lib.at && !lib.loading && !ONL.searched){
    ONL.searched = true;
    api('online_search', ONL.q, 1, ONL.sort);
  }
  const canRoom = roomHostLobby(o);
  if(!o || o.server_ok === false){
    list.innerHTML = `<div class="empty"><div class="big">🌐</div>Hors ligne.<br>La bibliothèque en ligne demande un serveur joignable.</div>`;
  } else if(lib.error){
    list.innerHTML = `<div class="empty"><div class="big">⚠️</div>${esc(lib.error)}</div>`;
  } else if(!items.length && lib.loading){
    list.innerHTML = `<div class="empty"><div class="big">⏳</div>Chargement…</div>`;
  } else if(!items.length){
    list.innerHTML = lib.at
      ? `<div class="empty"><div class="big">🔍</div>Aucun morceau ne correspond${lib.q ? ' à « ' + esc(lib.q) + ' »' : ''}.</div>`
      : `<div class="empty"><div class="big">🎶</div>Cherche un morceau, ou clique sur Actualiser.</div>`;
  } else {
    list.innerHTML = items.map(it => libRowHtml(it, jobs, canRoom)).join('');
    list.querySelectorAll('[data-act]').forEach(b => {
      const id = b.dataset.id;
      b.onclick = () => {
        if(b.dataset.act === 'dl') api('online_download', id);
        else if(b.dataset.act === 'room'){ api('room_set_song', id); toast('Morceau proposé au salon', 'ok'); }
      };
    });
  }
  const pages = lib.pages || 0;
  $('onlinePager').hidden = pages < 2;
  txt('onlinePage', `page ${lib.page || 1} / ${pages || 1}`);
  $('onlinePrev').disabled = (lib.page || 1) <= 1;
  $('onlineNext').disabled = (lib.page || 1) >= pages;
  const hint = $('onlineShareHint');
  if(o && o.server_ok !== false && !o.logged_in){
    txt('onlineShareHint', 'Connecte-toi pour partager tes musiques : bouton ☁ sur chaque ligne de « Mes musiques ».');
    hint.hidden = false;
  } else if(o && o.logged_in){
    txt('onlineShareHint', 'Partage une musique locale : onglet Musique, bouton ☁ sur la ligne du morceau.');
    hint.hidden = false;
  } else hint.hidden = true;
}
view('onlineLib', {sig: st => {
  const o = onlineOf(st);
  if(!o) return 'none';
  return JSON.stringify([o.server_ok, o.logged_in, o.library, o.jobs && o.jobs.downloads, roomHostLobby(o), TAB]);
}, draw: viewOnlineLib});

// ------------------------------------------------ modération (admin)
function pendingRowHtml(it){
  const meta = [itemAuthor(it), it.duration_s ? fmt(it.duration_s) : '', agoText(it.created_at)].filter(Boolean).join(' · ');
  return `<div class="row row--online">
      <span class="n">⏳</span>
      <span class="tt"><span class="t">${esc(it.title || 'Sans titre')}</span><span class="m">${esc(meta)}</span></span>
      <div class="row__actions">
        <button class="btn btn--cta btn--sm" type="button" data-act="ok" data-id="${esc(it.id)}">✓ Valider</button>
        <button class="btn btn--secondary btn--sm" type="button" data-act="no" data-id="${esc(it.id)}">✕ Refuser</button>
      </div>
    </div>`;
}
// Les listes d'administration se chargent seules dès qu'on est admin, puis se rafraîchissent au plus
// toutes les 30 s. Avant, elles n'étaient demandées qu'à l'ouverture du volet, une seule fois : si cette
// unique tentative échouait ou n'avait pas lieu, le compteur restait à 0 jusqu'au redémarrage.
function loadAdminLists(o, force){
  const now = Date.now();
  const pend = o.pending || {}, reps = o.reports || {};
  if(force){ ONL.pendingAt = 0; ONL.reportsAt = 0; }
  if(!pend.loading && now - ONL.pendingAt > 30000){ ONL.pendingAt = now; api('online_pending', 1); }
  if(!reps.loading && now - ONL.reportsAt > 30000){ ONL.reportsAt = now; api('online_reports'); }
}
function viewOnlineAdmin(st){
  const o = onlineOf(st);
  const box = $('onlineAdminBox');
  if(!box) return;
  const admin = !!(o && o.is_admin);
  box.hidden = !admin;
  if(!admin) return;
  loadAdminLists(o);
  const pend = o.pending || {items: [], loading: false, page: 1, pages: 0, total: 0};
  const reps = o.reports || {items: [], loading: false, error: ''};
  const items = pend.items || [];
  txt('onlinePendingSum', `À valider (${pend.total != null ? pend.total : items.length})`);
  const pl = $('onlinePendingList');
  if(pend.loading && !items.length) pl.innerHTML = `<div class="empty">Chargement…</div>`;
  else if(pend.error) pl.innerHTML = `<div class="empty">${esc(pend.error)}</div>`;
  else if(!items.length) pl.innerHTML = `<div class="empty">Rien à valider.</div>`;
  else {
    pl.innerHTML = items.map(pendingRowHtml).join('');
    pl.querySelectorAll('[data-act]').forEach(b => {
      const id = b.dataset.id;
      b.onclick = () => {
        if(b.dataset.act === 'ok') return api('online_moderate', id, 'approve', '');
        dialog({title: 'Refuser ce morceau', icon: '✕', ok: 'Refuser', danger: true,
                html: `<label class="field"><span class="field__label">Raison (vue par la personne qui l'a déposé)</span>
                  <input class="input dlg-input" type="text" maxlength="120" placeholder="Fichier incomplet, doublon…"></label>`})
          .then(yes => {
            const inp = $('dlgBody').querySelector('.dlg-input');
            if(yes) api('online_moderate', id, 'reject', inp ? inp.value.trim() : '');
          });
      };
    });
  }
  const rl = $('onlineReportsList');
  const ritems = reps.items || [];
  txt('onlineReportsSum', `Signalements (${ritems.length})`);
  if(reps.loading && !ritems.length) rl.innerHTML = `<div class="empty">Chargement…</div>`;
  else if(reps.error) rl.innerHTML = `<div class="empty">${esc(reps.error)}</div>`;
  else if(!ritems.length) rl.innerHTML = `<div class="empty">Aucun signalement ouvert.</div>`;
  else {
    rl.innerHTML = ritems.map(r => `<div class="row row--online">
      <span class="n">⚑</span>
      <span class="tt"><span class="t">${esc(r.song_title || ('#' + r.song_id))}</span>
        <span class="m">${esc([r.reason || '', r.reporter_name ? 'signalé par ' + r.reporter_name : '', agoText(r.created_at)].filter(Boolean).join(' · '))}</span></span>
      <span class="row__actions">
        <button class="btn btn--secondary btn--sm" type="button" data-rep="keep" data-id="${esc(String(r.id))}">Sans suite</button>
        <button class="btn btn--danger btn--sm" type="button" data-rep="drop" data-id="${esc(String(r.id))}" data-title="${esc(r.song_title || '')}">Retirer le morceau</button>
      </span>
    </div>`).join('');
    rl.querySelectorAll('[data-rep]').forEach(b => {
      const id = b.dataset.id;
      b.onclick = () => {
        if(b.dataset.rep === 'keep') return api('online_resolve_report', id, 'dismiss');
        dialog({title: 'Retirer ce morceau ?', icon: '🗑️', ok: 'Retirer', danger: true,
                html: `<p>${esc(b.dataset.title || 'Ce morceau')} sera retiré de la bibliothèque en ligne. Les personnes qui l'ont déjà téléchargé le gardent.</p>`})
          .then(yes => { if(yes) api('online_resolve_report', id, 'remove_song'); });
      };
    });
  }
}
view('onlineAdmin', {sig: st => {
  const o = onlineOf(st);
  return JSON.stringify(o ? [o.is_admin, o.pending, o.reports] : null);
}, draw: viewOnlineAdmin});

// ------------------------------------------------ pastille de compte (en-tête) et point de mise à jour
function viewAccountPill(st){
  const o = onlineOf(st);
  const pill = $('accountPill'), dot = $('settingsDot');
  if(!pill) return;
  if(!o){ pill.hidden = true; if(dot) dot.hidden = true; return; }
  pill.hidden = false;
  if(o.logged_in && o.user){
    pill.innerHTML = personHtml(o.user, 'avatar avatar--sm') + `<span>${esc(userLabel(o.user))}</span>`;
    pill.title = 'Compte Discord · onglet En ligne';
  } else {
    pill.innerHTML = `<span class="avatar avatar--sm avatar--ini">🌐</span><span>Se connecter</span>`;
    pill.title = 'Se connecter avec Discord';
  }
  const u = o.update || {};
  if(dot) dot.hidden = !(u.state === 'available' || u.state === 'ready');
}
view('accountPill', {sig: st => {
  const o = onlineOf(st);
  return JSON.stringify(o ? [o.logged_in, o.user, (o.update || {}).state] : null);
}, draw: viewAccountPill});

// ------------------------------------------------ recherche, tri, pagination
function onlineSearchNow(page){
  ONL.page = page || 1;
  api('online_search', ONL.q, ONL.page, ONL.sort);
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
    const o = onlineOf(S); if(o && o.is_admin) loadAdminLists(o, true);   // file de modération et signalements
  };
  $('onlineSort').value = ONL.sort;
  // ouvrir un volet force un rafraîchissement immédiat (le chargement automatique a lieu de toute façon)
  $('onlinePendingDisc').ontoggle = () => { if($('onlinePendingDisc').open){ ONL.pendingAt = Date.now(); api('online_pending', 1); } };
  $('onlineReportsDisc').ontoggle = () => { if($('onlineReportsDisc').open){ ONL.reportsAt = Date.now(); api('online_reports'); } };
}
if($('accountPill')) $('accountPill').onclick = () => showTab('online');
