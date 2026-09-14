// DodoTopia : apercu sans backend (tests) : index.html?mock[&image][&calib|&drawing|&autocal][&cook|&ccalib][&dialog][&toast][&tab=cook]
//   [&settings[=section]][&empty (bibliotheque vide)][&multi (compte a rebours Multi audio)][&audio (mode Multi audio au repos)]
//   [&game (lecture dans le jeu)][&error (arret anormal, non admin)]
//   En ligne / Salon : [&online (connecte + bibliotheque)][&online=out (deconnecte)][&online=off (serveur injoignable)]
//   [&online=wait (connexion Discord en attente)][&admin (file de moderation)][&lobby (salon en attente, 3 joueurs)]
//   [&lobby=count (compte a rebours du salon)][&update (mise a jour disponible : carte + toast persistant)]
if(location.search.includes('mock')){
  const q = location.search;
  const has = k => new RegExp('[?&]' + k + '(?:&|$)').test(q);
  const keysP = [",","l",".",";","/","o","0","p","-","[","=","]","z","s","x","d","c","v","g","b","h","n","j","m","q","2","w","3","e","r","5","t","6","y","7","u","i"];
  const keysF = ["y","u","i","o","p","h","j","k","l",";","n","m",",",".","/"];
  const arg = k => { const m = new RegExp('[?&]' + k + '(?:=([a-z0-9]*))?(?:&|$)').exec(q); return m ? (m[1] || true) : null; };
  const onl = arg('online'), adm = !!has('admin'), lob = arg('lobby'), upd = arg('update');
  const wantOnline = !!(onl || adm || lob || upd);
  const offline = onl === 'off', out = onl === 'out', waiting = onl === 'wait';
  const logged = wantOnline && !offline && !out && !waiting;
  const mode = has('multi') || has('audio') ? 'audio' : (has('room') || lob) ? 'room' : 'solo';
  const multiState = has('multi') ? (has('calibm') ? 'calibrating' : 'listening') : 'idle';
  const NOW = Date.now() / 1000;
  const MOCK_USER = {id: '204255221017214977', name: 'Dodo', username: 'Dodo', avatar: '', is_admin: adm};
  const MOCK_ITEMS = [
    {id: 11, title: 'AriaMath', artist: 'C418', uploader_name: 'Dodo', duration_s: 318, downloads: 128, sha256: 'a1',
     created_at: new Date(Date.now() - 3600e3 * 5).toISOString(), status: 'approved', local: null},
    {id: 12, title: 'Wish You Were Here', artist: 'Pink Floyd', uploader_name: 'Lila', duration_s: 95, downloads: 17, sha256: 'b2',
     created_at: new Date(Date.now() - 86400e3 * 2).toISOString(), status: 'approved', local: 'b'},
    {id: 13, title: 'Blinding Lights (version longue pour tester le debordement du titre)', artist: 'The Weeknd',
     uploader_name: 'Marin', duration_s: 124, downloads: 8, sha256: 'c3',
     created_at: new Date(Date.now() - 86400e3 * 9).toISOString(), status: 'approved', local: null}];
  const MOCK_PENDING = [
    {id: 21, title: 'Gymnopédie n°1', artist: 'Erik Satie', uploader_name: 'Nina', duration_s: 210,
     created_at: new Date(Date.now() - 3600e3 * 2).toISOString(), status: 'pending'},
    {id: 22, title: 'fichier-sans-titre', artist: '', uploader_name: 'Marin', duration_s: 12,
     created_at: new Date(Date.now() - 86400e3).toISOString(), status: 'pending'}];
  const MOCK_REPORTS = [
    {id: 5, song_id: 12, song_title: 'Wish You Were Here', reporter_name: 'Lila', reason: 'fichier tronqué, la moitié manque',
     created_at: new Date(Date.now() - 86400e3 * 3).toISOString()}];
  const MOCK_PLAYERS = [
    {id: 1, name: 'Dodo', avatar: '', instrument: 'piano', host: true, connected: true, have_song: true, ready: true, status: 'lobby'},
    {id: 2, name: 'Lila', avatar: '', instrument: 'flute', host: false, connected: true, have_song: true, ready: true, status: 'lobby'},
    {id: 3, name: 'Marin-au-pseudo-vraiment-long', avatar: '', instrument: 'luth', host: false, connected: false,
     have_song: lob === 'count', ready: lob === 'count', status: 'lobby'}];
  const MOCK_ROOM = !lob ? null : {
    enabled: true, state: lob === 'count' ? 'armed' : 'lobby', mode: 'room', role: 'host',
    seconds_left: lob === 'count' ? 4.2 : null, message: lob === 'count' ? 'Top départ : reste sur Heartopia.' : '',
    player_id: 1, leader_id: 1, players: [1, 2, 3],
    room: {code: 'K7P2QD', connected: true, state: lob === 'count' ? 'countdown' : 'lobby', host_id: 1,
      song: {sha256: 'a1', name: 'AriaMath', duration_ms: 318000, key_shift: 5, source: 'library', online_id: 11},
      players: MOCK_PLAYERS, countdown_s: 5, start_at_ms: 0, max_players: 8, seq: 12,
      clock: {offset_ms: 12.3, rtt_ms: 38, err_ms: lob === 'count' ? 19 : 64, age_s: 2, samples: 12, valid: true},
      net_offset_ms: -40, can_start: lob === 'count', start_blocker: lob === 'count' ? '' : 'Fichier pas encore reçu : Marin-au-pseudo-vraiment-long',
      me: {id: 1, ready: true, has_file: true, host: true, name: 'Dodo'}, error: '', last_room: 'K7P2QD', min_version: '1.6.0'}};
  const MOCK_IDLE_ROOM = {enabled: mode === 'room', state: 'idle', mode: 'room', role: '', seconds_left: null, message: '',
    player_id: null, leader_id: null, players: [],
    room: {code: null, connected: false, state: 'lobby', host_id: null, song: null, players: [], countdown_s: null,
      start_at_ms: null, max_players: null, seq: 0, clock: {}, net_offset_ms: 0, can_start: false,
      start_blocker: 'Pas de salon', me: {}, error: '', last_room: 'K7P2QD', min_version: '1.6.0'}};
  const MOCK_UPDATE = upd
    ? {state: upd === 'ready' ? 'ready' : 'downloading', current: '1.7.0', latest: '1.8.0',
       notes: 'Salons en ligne, bibliothèque partagée et mise à jour automatique.', mandatory: false, kind: 'setup',
       progress: 0.35, done_mb: 4.2, size_mb: 12.0, path: null, error: '', checked_at: NOW}
    : {state: offline ? 'idle' : 'uptodate', current: '1.7.0', latest: '1.7.0', notes: '', mandatory: false, kind: 'setup',
       progress: 0, done_mb: 0, size_mb: 0, path: null, error: '', checked_at: offline ? 0 : NOW};
  const MOCK_ONLINE = !wantOnline ? undefined : {
    server_url: 'https://dodotopia.cyber-dodo.fr', server_ok: !offline, server_version: '1.7.0', min_client: '1.6.0',
    client_too_old: false, offline_reason: offline ? 'connexion impossible (délai dépassé)' : '', checked_at: NOW,
    logged_in: logged, user: logged ? MOCK_USER : null, is_admin: adm && logged,
    login: waiting ? {state: 'waiting', url: 'https://dodotopia.cyber-dodo.fr/auth/discord/start?login_id=4f2b9c1e', error: '', expires_in: 540}
                   : {state: 'idle', url: '', error: '', expires_in: null},
    update: MOCK_UPDATE,
    library: {q: '', sort: 'recent', page: 1, pages: offline ? 0 : 2, total: offline ? 0 : 3,
      items: offline ? [] : MOCK_ITEMS, loading: false, error: '', at: offline ? 0 : NOW},
    pending: {page: 1, pages: 1, total: adm ? MOCK_PENDING.length : 0, items: adm ? MOCK_PENDING : [], loading: false, error: '', at: adm ? NOW : 0},
    reports: {items: adm ? MOCK_REPORTS : [], loading: false, error: '', at: adm ? NOW : 0},
    jobs: {downloads: logged && !offline ? {'13': {state: 'downloading', progress: 0.42, error: '', song_id: null}} : {}, uploads: {}},
    room: MOCK_ROOM || MOCK_IDLE_ROOM, clock: (MOCK_ROOM || MOCK_IDLE_ROOM).room.clock};
  const MOCK_TOASTS = [];
  if(location.search.includes('toast')) MOCK_TOASTS.push({id: 1, t: 0, msg: '2 musiques importées', kind: 'ok', sticky: false},
    {id: 2, t: 0, msg: 'Arrêt : touche pressée', kind: 'warn', sticky: false});
  if(upd) MOCK_TOASTS.push({id: 3, t: 0, msg: 'Version 1.8.0 disponible', kind: 'info', sticky: true,
    action: {label: 'Installer', method: 'update_install'}, progress: 35});
  render({version:'1.7.0', instruments:[{id:'piano',name:'Piano',kind:'chromatique',keys:keysP},{id:'flute',name:'Flûte',kind:'diatonique',keys:keysF},{id:'luth',name:'Luth',kind:'diatonique',keys:keysF}],
    instrument:2, songs: has('empty') ? [] : [{id:'a',name:'AriaMath',file:'AriaMath',fav:true,plays:12,added:1788700000,last_played:1788730000,duration:318,index:0},{id:'b',name:'Wish You Were Here',file:'P.FLOYD.Wish you were here K',fav:false,plays:0,added:1788720000,last_played:0,duration:95,index:1},{id:'c',name:'Blinding Lights',file:'The-Weeknd-Blinding-Lights',fav:false,plays:3,added:1788600000,last_played:1788600500,duration:124,index:2}],
    current: has('empty') ? -1 : 0, state: has('empty') || has('multi') || has('error') ? (has('multi') ? 'sync' : 'stopped') : 'playing', target: has('game') ? 'game' : 'preview',
    position:62, duration:318, speed:1, info: has('empty') || has('error') ? null : {shift:5,folded:272,snapped:67},
    hotkeys:{play_pause:'F6',stop:'F7',next_song:'F8',prev_song:'F9',speed_down:'F10',speed_up:'F11',next_instrument:'F12',draw_point:'F3'},
    settings:{input_mode:'scancode',hold_time:0.04,start_delay:1,transpose_semitones:2,stop_on_input:true,preview_volume:100,hold_mode:'note',
      multi:{enabled: mode === 'audio', mode, player_id:2, countdown:10, lead:1.5, offset_ms:-40, net_offset_ms:0, latency: has('nolat') ? null : 0.25, device:'',
             calib: has('nocalib') ? null : {role:'follower', when: Date.now()/1000 - 86400*3, leader:1, rtt_ms:180, offset_ms:-40}},
      draw:{outline:true, fill_background:true, skip_white:false}, online:{server_url:'', check_updates:true}},
    multi: MOCK_ROOM || (mode === 'room' ? MOCK_IDLE_ROOM : {enabled: mode === 'audio', state: multiState, mode: has('calibm') ? 'calibrate' : 'start', role: has('leader') ? 'leader' : (has('calibm') ? '' : 'follower'), leader_id:1,
           seconds_left: 7.4, message: has('calibm') ? 'Calibrage : meneur joueur 1, réponse dans 2,1 s' : 'Signal du joueur 1 : on se cale sur lui', player_id:2, players:[1,2], calib:null}),
    online: MOCK_ONLINE,
    error: has('error') ? {msg:'Sortie audio introuvable : mode Multi indisponible (la capture audio ne démarre pas)', kind:'danger', since: Date.now()/1000, target:'game', reason:'erreur'} : null,
    draw_stats: {available:true, pencil_cells:1830, fill_zones:42, fill_cells:3354, total_cells:5184},
    log:[], is_admin: !has('error'),
    toasts: MOCK_TOASTS,
    draw:{state: has('calib') ? 'calibrating' : has('drawing') ? 'drawing' : has('autocal') ? 'autocal' : 'idle', format:'16:9', step:2, progress_msg: has('autocal') ? 'mesure des cases…' : 'couleur 3 / 12',
      steps:[{key:'tl',title:'Coin haut-gauche du canevas',help:'Place la souris exactement sur le coin haut-gauche de la zone de dessin.'},{key:'br',title:'Coin bas-droit du canevas',help:'…'},{key:'pal0',title:'Première couleur de la palette',help:'Survole la première pastille de couleur (en haut à gauche de la palette).'},{key:'pal1',title:'Dernière couleur de la palette',help:'…'},{key:'pencil',title:'Outil crayon',help:'…'},{key:'bucket',title:'Outil pot de peinture',help:'…'}],
      done:1830, total:5184, elapsed:42, eta:75, countdown: has('countdown') ? 2.4 : 0, message:'', palette:null, shades_ok:true, formats:{'16:9':{cols:96,rows:54,calibrated:!has('nocal')},'4:3':{cols:72,rows:54,calibrated:false},'1:1':{cols:54,rows:54,calibrated:false},'3:4':{cols:40,rows:54,calibrated:false},'9:16':{cols:30,rows:54,calibrated:false}},
      validated:{'16:9':!has('noval') && !has('nocal'),'4:3':false,'1:1':false,'3:4':false,'9:16':false},
      tools:{pencil:true,bucket:true}, settings:{step_delay:0.012,click_delay:0.05,fill_background:true,skip_white:false}},
    cook:{state: has('cook') ? 'cooking' : has('ccalib') ? 'calibrating' : 'idle', phase:'cuisson', step:2,
      steps:[{key:'search_tl',title:'Zone de recherche : coin haut-gauche',help:'…'},{key:'search_br',title:'Zone de recherche : coin bas-droit',help:'…'},{key:'cook',title:'Bulle « cuisiner »',help:'Place la souris au centre de la bulle.'},{key:'tile',title:'Menu Recettes : la première tuile récente',help:'…'},{key:'cook_btn',title:'Menu Recettes : le bouton « Cuisiner »',help:'…'},{key:'spatula',title:'Bulle « spatule » (facultatif)',help:'…',optional:true},{key:'ready',title:'Bulle « récupérer » (gants)',help:'…'},{key:'neutral',title:'Un endroit vide où cliquer',help:'…'}],
      countdown: has('countdown') ? 2.4 : 0, elapsed:75, dishes:3, fires:5, message:'', stop_reason:'', calibrated: !has('nocal'), refs:{cook:!has('nocal'),ready:!has('nocal'),spatula:false}, ring_color:null,
      test_result: has('notest') || has('nocal') ? '' : 'bulle « cuisiner » en 820,440 (cook 0.91, ready 0.4, vert 0) ; menu fermé.',
      settings:{max_dishes:10,cook_timeout:240,match:0.55,click_delay:0.3,green_px:60}, screen_ok:true}});
  const mt = /tab=(music|image|cook|online)/.exec(location.search);
  if(mt) showTab(mt[1]);
  else if(wantOnline && !lob) showTab('online');
  if(adm){ $('onlinePendingDisc').open = true; $('onlineReportsDisc').open = true; }   // volets de moderation deplies
  if(has('image') || has('drawing') || has('autocal')) loadImageData({name: 'logo', data: '../assets/logo.png'});
  if(location.search.includes('dialog')) dialog({title:'Retirer la musique', icon:'🗑️', danger:true, ok:'Retirer', html:`Retirer <b>AriaMath</b> de la bibliothèque ?<br><small>Le fichier d'origine n'est pas touché.</small>`});

  // ?mock&settings[=multi] : panneau Réglages avec un schéma factice (même forme que get_settings_schema)
  const ms = /[?&]settings(?:=([a-z]+))?/.exec(location.search);
  if(ms){
    const F = {};
    const num = (p, sec, d, min, max, unit, step, v) => { F[p] = {type:'num', section:sec, default:d, value:v === undefined ? d : v, min, max, unit, step}; };
    const int = (p, sec, d, min, max, unit, v) => { F[p] = {type:'int', section:sec, default:d, value:v === undefined ? d : v, min, max, unit, step:1}; };
    const bool = (p, sec, d, v) => { F[p] = {type:'bool', section:sec, default:d, value:v === undefined ? d : v}; };
    const choice = (p, sec, d, choices) => { F[p] = {type:'choice', section:sec, default:d, value:d, choices}; };
    const str = (p, sec, d, v) => { F[p] = {type:'str', section:sec, default:d, value:v === undefined ? d : v}; };
    num('start_delay', 'lecture', 1, 0, 10, 's', 0.5, 1.5); bool('stop_on_input', 'lecture', true);
    choice('hold_mode', 'lecture', 'note', ['note', 'tap']); num('hold_time', 'lecture', 40, 10, 500, 'ms', 5);
    choice('input_mode', 'lecture', 'scancode', ['scancode', 'vk']); int('transpose_semitones', 'lecture', 0, -24, 24, '½ ton', 2);
    int('preview_volume', 'lecture', 100, 0, 100, '%');
    const HK = {play_pause:'F6', stop:'F7', next_song:'F8', prev_song:'F9', speed_down:'F10', speed_up:'F11', next_instrument:'F12', draw_point:'F3'};
    for(const k in HK) F['hotkeys.' + k] = {type:'hotkey', section:'hotkeys', default:HK[k], value:k === 'stop' ? 'ctrl+F7' : HK[k]};
    int('multi.player_id', 'multi', 1, 1, 5, '', 2); num('multi.countdown', 'multi', 10, 3, 30, 's', 1); num('multi.lead', 'multi', 1.5, 0.8, 3, 's', 0.1);
    int('multi.offset_ms', 'multi', 0, -500, 500, 'ms', -40); str('multi.device', 'multi', '', 'VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)');
    choice('multi.mode', 'multi', 'solo', ['solo', 'audio', 'room']); str('multi.name', 'multi', ''); int('multi.net_offset_ms', 'multi', 0, -300, 300, 'ms');
    num('draw.step_delay', 'draw', 20, 0, 500, 'ms', 5); num('draw.click_delay', 'draw', 50, 0, 1000, 'ms', 10); num('draw.glide_speed', 'draw', 1, 0.2, 4, '×', 0.1);
    for(const k of ['fill_background', 'verify', 'refine', 'outline', 'mouse_glide']) bool('draw.' + k, 'draw', true);
    bool('draw.skip_white', 'draw', false); bool('draw.dense', 'draw', false);
    const G = {'16:9':[140,84], '4:3':[150,114], '1:1':[150,150], '3:4':[114,150], '9:16':[84,150]};
    for(const f in G){ int(`draw.formats.${f}.cols`, 'grids', G[f][0], 4, 400, '', f === '16:9' ? 96 : (f === '4:3' ? 120 : undefined)); int(`draw.formats.${f}.rows`, 'grids', G[f][1], 4, 400, '', f === '16:9' ? 54 : undefined); }
    int('cook.max_dishes', 'cook', 0, 0, 999, '', 10); num('cook.cook_timeout', 'cook', 240, 30, 900, 's', 10); num('cook.match', 'cook', 0.62, 0.3, 0.9, '', 0.05);
    int('cook.green_px', 'cook', 60, 10, 2000, 'px'); num('cook.click_delay', 'cook', 300, 0, 1000, 'ms', 10);
    str('online.server_url', 'online', 'https://dodotopia.cyber-dodo.fr'); bool('online.check_updates', 'online', true);
    try{ localStorage.setItem('settingsSection', ms[1] || 'general'); }catch(e){}
    if(location.search.includes('adv')) SET.advOpen = true;   // &adv : « Avancé » déplié
    openSettings({fields:F, sections:['lecture', 'hotkeys', 'multi', 'draw', 'grids', 'cook', 'online'],
      hotkey_labels:{play_pause:'Jouer / pause', stop:'Arrêter', next_song:'Musique suivante', prev_song:'Musique précédente', speed_down:'Ralentir', speed_up:'Accélérer', next_instrument:'Instrument suivant', draw_point:'Repère (calibrage du dessin)'},
      multi_devices:['Digital Audio (S/PDIF) (High Definition Audio Device)', 'Casque (2- CORSAIR VOID ELITE Wireless Gaming Headset)', 'VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)'],
      songs_folder:'C:\\Users\\moi\\AppData\\Local\\DodoTopia\\songs', data_dir:'C:\\Users\\moi\\AppData\\Local\\DodoTopia', version:'1.7.0', install_kind:'setup',
      logs:{multi:true, dessin:true, cuisine:false, online:false}, online_ready:false});
  }
}
