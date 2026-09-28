// DodoTopia : apercu sans backend (tests) : index.html?mock[&image][&calib|&drawing|&autocal][&cook|&ccalib][&dialog][&toast][&help][&account][&tab=cook][&view=library|discover|together]
//   [&settings[=audio|hotkeys|draw|cook|online|general (Apparence)|storage|about]][&empty (bibliotheque vide)][&multi (compte a rebours Multi audio)][&audio (mode Multi audio au repos)]
//   [&game (lecture dans le jeu)][&error (arret anormal, non admin)]
//   Instruments : [&inst=<id> (instrument actif : piano, lute, conga, conch...)][&qwerty (libelles QWERTY)]
//   [&sel (selecteur ouvert)][&keys (panneau des touches)]
//   [&nocompat (aucun diagnostic de morceau)]
//   En ligne / Salon : [&online (connecte + catalogue)][&online=out (deconnecte)][&online=off (serveur injoignable)]
//   [&online=wait (connexion Discord en attente)][&admin (file de moderation)][&lobby (salon en attente, 3 joueurs)]
//   [&lobby=count (compte a rebours du salon)][&lobby=parts (Orchestre : pistes reparties)][&lobby=solo1 (seul dans
//   le salon)][&lobby=guest (invite)][&picker (selecteur de morceau du salon ouvert)]
//   [&update (mise a jour disponible : carte + toast persistant)]
//   Conditions d'utilisation : [&terms (modale bloquante, texte lorem fr)][&terms=en (ouverte en anglais)][&terms=fail (echec du chargement)]
//   [&terms=short (texte plus court que la zone : compte comme lu)]
//   Langue : [&lang=en|es|de|pt-BR|zh-CN|ja|th|id|fil (catalogue ui/i18n/<lang>.json charge par fetch : http seulement)]
//   Thème : [&theme=dark|light (data-theme force sur <html>)]
//   Phase 2 : [&onboarding (découverte ouverte)][&deeplink (lien dodotopia:// à confirmer : salon K7P2QD)]
//   [&gamewin=off|admin|none (fenêtre du jeu : non lancé, en administrateur alors que DodoTopia non, non vérifié ;
//    défaut : détecté)][&tracks (« Réglages du morceau » ouverts, pistes MIDI simulées)]
//   Phase 3 : [&gallery (galerie des dessins ouverte, connecté)][&share (Découvrir + menu Partager ouvert sur la
//   première ligne)][&importurl (dialogue « Importer depuis un lien »)][&shareform (formulaire de partage d'un
//   morceau)][&published (dessin converti, dépôt en attente de modération)][&tag=<tag> (filtre actif dans Découvrir)]
// &theme=dark|light : thème forcé (le mode headless ne lit pas localStorage de façon fiable)
if(location.search.includes('mock')){
  const themeArg = (/[?&]theme=(dark|light)/.exec(location.search) || [])[1];
  if(themeArg) document.documentElement.dataset.theme = themeArg;
  // ---- faux get_i18n : meme forme que le backend {lang, available, catalogue, fallback, meta}, catalogues assembles
  // (py .tools/i18n_merge.py) lus par fetch ; la liste des langues vient des _meta de chaque catalogue.
  const MOCK_LANGS = ['fr', 'en', 'es', 'de', 'pt-BR', 'zh-CN', 'ja', 'th', 'id', 'fil'];
  const catCache = {};
  const fetchCat = tag => catCache[tag] || (catCache[tag] = fetch('i18n/' + tag + '.json').then(r => r.ok ? r.json() : null).catch(() => null));
  window.MOCK_I18N = lang => {
    lang = MOCK_LANGS.includes(lang) ? lang : 'fr';
    return Promise.all(MOCK_LANGS.map(fetchCat)).then(all => {
      const cats = {}; MOCK_LANGS.forEach((tag, i) => { if(all[i]) cats[tag] = all[i]; });
      const available = MOCK_LANGS.filter(tag => cats[tag]).map(tag => ({tag, name: (cats[tag]._meta || {}).name || tag, beta: !!(cats[tag]._meta || {}).beta}));
      const cur = cats[lang] || cats.fr || {}, fb = cats.fr || {};
      const strip = c => { const o = Object.assign({}, c); delete o._meta; return o; };
      return {lang: cats[lang] ? lang : 'fr', available, catalogue: strip(cur), fallback: cur === fb ? {} : strip(fb), meta: cur._meta || {}};
    });
  };
  const langArg = (/[?&]lang=([A-Za-z-]+)/.exec(location.search) || [])[1] || 'fr';
  // la langue est chargee AVANT le rendu (comme onReady dans l'application) ; sans serveur http, on rend quand meme
  window.MOCK_I18N(langArg).then(applyI18nData, e => console.warn('mock : catalogue i18n non charge', e)).then(mockMain);
}
function mockMain(){
  const q = location.search;
  const has = k => new RegExp('[?&]' + k + '(?:&|$)').test(q);
  const keysP = [",","l",".",";","/","o","0","p","-","[","=","]","z","s","x","d","c","v","g","b","h","n","j","m","q","2","w","3","e","r","5","t","6","y","7","u","i"];
  const keysF = ["y","u","i","o","p","h","j","k","l",";","n","m",",",".","/"];
  const arg = k => { const m = new RegExp('[?&]' + k + '(?:=([a-z0-9-]*))?(?:&|$)').exec(q); return m ? (m[1] || true) : null; };

  // ---- catalogue simule : 19 types, un seul par type, au format leger de Instrument.to_dict()
  // Statuts volontairement varies : confirme, documente, personnalise, test rapide, percussif candidat, inconnu.
  const BLOCK_PERC = 'Profil de percussion candidat : les frappes n’ont pas encore été identifiées. Passe le test des percussions pour l’activer.';
  const BLOCK_UNKNOWN = 'Touches inconnues pour cet instrument : elles restent à relever dans le jeu.';
  const inst = (id, name, en, cat, o) => Object.assign({
    id, name, label_en: en, category: cat, image: 'instruments/' + id + '.png',
    kind: 'diatonique', keys: keysF, count: 15, layout_id: 'diatonic-15-3row', layout_label: '15 notes, 3 rangées',
    status: 'documented', ready: true, percussive: false, custom: false, blocked_reason: '',
    lowest: 60, span: 24, aliases: [], variant_count: 1}, o || {});
  const instUnknown = (id, name, en, cat, o) => inst(id, name, en, cat, Object.assign({
    kind: '', keys: [], count: 0, layout_id: null, layout_label: '', status: 'unknown', ready: false,
    blocked_reason: BLOCK_UNKNOWN, lowest: 60, span: 0}, o || {}));
  const MOCK_INSTRUMENTS = [
    inst('piano', 'Piano', 'Piano', 'keys', {kind: 'chromatique', keys: keysP, count: 37, layout_id: 'piano-chromatic-37',
      layout_label: '37 notes, piano chromatique', lowest: 48, span: 36, status: 'confirmed',
      aliases: ['clavier', 'piano'], variant_count: 9}),
    inst('recorder', 'Flûte à bec', 'Recorder', 'winds', {aliases: ['flute', 'flute a bec', 'recorder'], variant_count: 4}),
    inst('xiao', 'Xiao en bambou', 'Bamboo Xiao', 'winds', {aliases: ['xiao', 'flute chinoise']}),
    inst('lute', 'Luth', 'Lute', 'strings', {status: 'custom', custom: true, lowest: 48, span: 24,
      layout_label: '', aliases: ['guitare', 'lute', 'luth'], variant_count: 5}),
    inst('wooden-bass', 'Basse en bois', 'Wooden Bass', 'strings', {aliases: ['basse', 'contrebasse'], variant_count: 4}),
    inst('bagpipe', 'Cornemuse', 'Bagpipe', 'winds', {aliases: ['bagpipe', 'biniou'], variant_count: 2}),
    inst('concertina', 'Concertina', 'Concertina', 'keys', {aliases: ['accordeon', 'bandoneon'], variant_count: 4}),
    inst('mbira', 'Mbira', 'Mbira', 'percussion', {aliases: ['kalimba', 'sanza'], variant_count: 2}),
    inst('lyre', 'Lyre', 'Lyre', 'strings', {status: 'quick-tested', aliases: ['cithare', 'lyre'], variant_count: 5}),
    inst('violin', 'Violon', 'Violin', 'strings', {status: 'confirmed', aliases: ['violin', 'violon'], variant_count: 2}),
    inst('cello', 'Violoncelle', 'Cello', 'strings', {aliases: ['cello', 'violoncelle'], variant_count: 4}),
    inst('conga', 'Conga', 'Conga', 'percussion', {percussive: true, ready: false, blocked_reason: BLOCK_PERC,
      aliases: ['conga', 'djembe', 'tambour'], variant_count: 4}),
    inst('cajon', 'Cajón', 'Cajón', 'percussion', {percussive: true, ready: false, blocked_reason: BLOCK_PERC,
      aliases: ['cajon', 'caisse'], variant_count: 3}),
    instUnknown('xylophone', 'Xylophone à 8 notes', '8-Note Xylophone w/ Stand', 'percussion', {aliases: ['lames', 'xylophone'], variant_count: 2}),
    instUnknown('saxophone', 'Saxophone', 'Saxophone', 'winds', {aliases: ['sax', 'saxo'], variant_count: 2}),
    instUnknown('harp', 'Harpe', 'Harp', 'strings', {aliases: ['harp', 'harpe'], variant_count: 4}),
    instUnknown('steel-tongue-drum', 'Tambour à langues métalliques', 'Steel Tongue Drum', 'percussion', {aliases: ['handpan'], variant_count: 2}),
    instUnknown('ocarina', 'Ocarina', 'Ocarina', 'winds', {aliases: ['ocarina', 'ocarine'], variant_count: 2}),
    instUnknown('conch', 'Conque', 'Conch', 'winds', {aliases: ['conch', 'conque', 'coquillage'], variant_count: 2})];
  // ?mock&inst=<id> : instrument actif (defaut : le luth, profil personnalise herite d'une ancienne config)
  const instWanted = typeof arg('inst') === 'string' ? arg('inst') : 'lute';
  const instIdx = Math.max(0, MOCK_INSTRUMENTS.findIndex(x => x.id === instWanted));
  const instCur = MOCK_INSTRUMENTS[instIdx];
  // diagnostic du morceau : ce que compat_report renverrait pour ce couple morceau / profil
  const MOCK_COMPAT = (!instCur.ready || has('nocompat') || has('empty')) ? null : {
    notes: 1428, playable: 1216, out_of_range: 172, missing_accidental: 68, dropped: 40, drums: 96,
    shift: 5, coverage: 78, folded: 132, fold: true,
    options: [{kind: 'transpose', value: 7, coverage: 91, label: 'Transposer de +7 demi-tons : 91 % à la hauteur exacte'},
              {kind: 'octave', value: -12, coverage: 84, label: 'Descendre d’une octave : 84 % à la hauteur exacte'},
              {kind: 'omit', value: 132, coverage: 80, label: 'Omettre 132 notes hors registre : 80 % à la hauteur exacte, aucune note déplacée d’octave'}]};
  const onl = arg('online'), adm = !!has('admin'), lob = arg('lobby'), upd = arg('update');
  const galArg = has('gallery'), shareArg = has('share'), importArg = has('importurl'), formArg = has('shareform'), pubArg = has('published');
  const tagArg = typeof arg('tag') === 'string' ? arg('tag') : '';
  const wantOnline = !!(onl || adm || lob || upd || galArg || shareArg || importArg || formArg || pubArg || tagArg);
  const offline = onl === 'off', out = onl === 'out', waiting = onl === 'wait';
  const logged = wantOnline && !offline && !out && !waiting;
  const mode = has('multi') || has('audio') ? 'audio' : (has('room') || lob) ? 'room' : 'solo';
  const multiState = has('multi') ? (has('calibm') ? 'calibrating' : 'listening') : 'idle';
  const NOW = Date.now() / 1000;
  const MOCK_USER = {id: '204255221017214977', name: 'Dodo', username: 'Dodo', avatar: '', is_admin: adm};
  const MOCK_ITEMS = [
    {id: 11, title: 'AriaMath', artist: 'C418', uploader_name: 'Dodo', duration_s: 318, downloads: 128, sha256: 'a1',
     created_at: new Date(Date.now() - 3600e3 * 5).toISOString(), status: 'approved', local: null,
     tags: ['piano', 'jeu-video', 'calme'], likes: 42, liked_by_me: true, page_url: 'https://dodotopia.cyber-dodo.fr/fr/morceaux/11-ariamath'},
    {id: 12, title: 'Wish You Were Here', artist: 'Pink Floyd', uploader_name: 'Lila', duration_s: 95, downloads: 17, sha256: 'b2',
     created_at: new Date(Date.now() - 86400e3 * 2).toISOString(), status: 'approved', local: 'b',
     tags: ['rock', 'facile'], likes: 7, liked_by_me: false, page_url: 'https://dodotopia.cyber-dodo.fr/fr/morceaux/12-wish-you-were-here'},
    {id: 13, title: 'Blinding Lights (version longue pour tester le debordement du titre)', artist: 'The Weeknd',
     uploader_name: 'Marin', duration_s: 124, downloads: 8, sha256: 'c3',
     created_at: new Date(Date.now() - 86400e3 * 9).toISOString(), status: 'approved', local: null,
     tags: ['pop'], likes: 0, liked_by_me: false, page_url: 'https://dodotopia.cyber-dodo.fr/fr/morceaux/13-blinding-lights'}];
  // galerie : vignettes pixel art générées (palette du jeu), une sans grille, une à moi
  const mockThumb = (w, h, seed) => {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const x = c.getContext('2d'); const pal = DEFAULT_PALETTE;
    for(let j = 0; j < h; j++) for(let i = 0; i < w; i++){
      const d = Math.hypot(i - w / 2, j - h / 2), k = Math.floor(d / 3 + seed * 7 + ((i * seed) % 5 === 0 ? 1 : 0)) % 12;
      x.fillStyle = hex(pal[(10 + seed * 17 + k * 10) % pal.length]); x.fillRect(i, j, 1, 1);
    }
    return c.toDataURL('image/png');
  };
  const MOCK_DRAWINGS = [
    {id: 31, title: 'Chat roux au soleil', w: 48, h: 36, uploader_name: 'Lila', likes: 18, liked_by_me: true, has_cells: true, mine: false},
    {id: 32, title: 'Maison de Heartopia', w: 40, h: 40, uploader_name: 'Dodo', likes: 5, liked_by_me: false, has_cells: true, mine: true},
    {id: 33, title: 'Coucher de soleil sur la plage (titre long pour tester)', w: 64, h: 36, uploader_name: 'Marin', likes: 0, liked_by_me: false, has_cells: false, mine: false},
    {id: 34, title: 'Champignon', w: 30, h: 40, uploader_name: 'Nina', likes: 3, liked_by_me: false, has_cells: true, mine: false},
    {id: 35, title: 'Logo du club', w: 36, h: 36, uploader_name: 'Nino', likes: 11, liked_by_me: false, has_cells: true, mine: false}]
    .map((d, i) => Object.assign(d, {status: 'approved', thumb_url: mockThumb(d.w, d.h, i + 1), thumb_w: d.w * 6, thumb_h: d.h * 6,
      page_url: 'https://dodotopia.cyber-dodo.fr/fr/galerie/' + d.id, created_at: new Date(Date.now() - 86400e3 * (i + 1)).toISOString()}));
  const MOCK_PENDING = [
    {id: 21, title: 'Gymnopédie n°1', artist: 'Erik Satie', uploader_name: 'Nina', duration_s: 210,
     created_at: new Date(Date.now() - 3600e3 * 2).toISOString(), status: 'pending'},
    {id: 22, title: 'fichier-sans-titre', artist: '', uploader_name: 'Marin', duration_s: 12,
     created_at: new Date(Date.now() - 86400e3).toISOString(), status: 'pending'}];
  const MOCK_REPORTS = [
    {id: 5, song_id: 12, song_title: 'Wish You Were Here', reporter_name: 'Lila', reason: 'fichier tronqué, la moitié manque',
     created_at: new Date(Date.now() - 86400e3 * 3).toISOString()}];
  // instruments volontairement melanges : id du catalogue, deux anciens ids (flute, luth) et un id inconnu
  const MOCK_PLAYERS_ALL = [
    {id: 1, name: 'Dodo', avatar: '', instrument: 'lute', host: true, connected: true, have_song: true, ready: true, status: 'lobby', version: '2.1.0'},
    {id: 2, name: 'Lila', avatar: '', instrument: 'flute', host: false, connected: true, have_song: true, ready: true, status: 'lobby', version: '2.1.0'},
    {id: 3, name: 'Marin-au-pseudo-vraiment-long', avatar: '', instrument: 'luth', host: false, connected: false,
     have_song: lob === 'count', ready: lob === 'count', status: 'lobby'},
    {id: 4, name: 'Nino', avatar: '', instrument: 'theorbe-de-poche', host: false, connected: true,
     have_song: true, ready: false, status: 'lobby', version: '2.0.2'}];
  const MOCK_PLAYERS = lob === 'solo1' ? MOCK_PLAYERS_ALL.slice(0, 1) : MOCK_PLAYERS_ALL;
  const MOCK_TRACKS = [{index: 1, name: 'Piano droit', notes: 812, low: 60, high: 91, mean: 74.2},
    {index: 2, name: 'Basse', notes: 344, low: 31, high: 55, mean: 41.0}, {index: 3, name: '', notes: 176, low: 55, high: 72, mean: 63.5},
    {index: 4, name: 'Batterie', notes: 96, drums: true}];
  const MOCK_PARTS = lob === 'parts' || lob === 'guest' ? {enabled: true, parts: {'1': {tracks: [3], octave: null}, '2': {tracks: [1], octave: null},
    '3': {tracks: [2], octave: -1}, '4': {tracks: [1], octave: null}}} : null;
  const guest = lob === 'guest';
  const MOCK_ROOM = !lob ? null : {
    enabled: true, state: lob === 'count' ? 'armed' : 'lobby', mode: 'room', role: guest ? 'guest' : 'host',
    seconds_left: lob === 'count' ? 4.2 : null, message: lob === 'count' ? 'Top départ : reste sur Heartopia.' : '',
    player_id: 1, leader_id: 1, players: [1, 2, 3, 4],
    room: {code: 'K7P2QD', connected: true, state: lob === 'count' ? 'countdown' : 'lobby', host_id: 1,
      song: lob === 'solo1' ? null : {sha256: 'a1', name: 'AriaMath', duration_ms: 318000, key_shift: 5, source: 'library', online_id: 11, tracks: MOCK_TRACKS},
      parts: MOCK_PARTS, my_part: MOCK_PARTS ? (guest ? 'Piano droit' : 'Piste 4') : '',
      players: MOCK_PLAYERS, countdown_s: 5, start_at_ms: 0, max_players: 8, seq: 12,
      clock: {offset_ms: 12.3, rtt_ms: 38, err_ms: lob === 'count' ? 19 : 64, age_s: 2, samples: 12, valid: true},
      net_offset_ms: -40, can_start: lob === 'count', start_blocker: lob === 'count' ? '' : 'Fichier pas encore reçu : Marin-au-pseudo-vraiment-long',
      me: guest ? {id: 2, ready: false, has_file: true, host: false, name: 'Lila'} : {id: 1, ready: true, has_file: true, host: true, name: 'Dodo'},
      error: '', last_room: 'K7P2QD', min_version: '1.6.0'}};
  const MOCK_IDLE_ROOM = {enabled: mode === 'room', state: 'idle', mode: 'room', role: '', seconds_left: null, message: '',
    player_id: null, leader_id: null, players: [],
    room: {code: null, connected: false, state: 'lobby', host_id: null, song: null, players: [], countdown_s: null,
      start_at_ms: null, max_players: null, seq: 0, clock: {}, net_offset_ms: 0, can_start: false,
      start_blocker: 'Pas de salon', me: {}, error: '', last_room: 'K7P2QD', min_version: '1.6.0'}};
  const MOCK_UPDATE = upd
    ? {state: upd === 'ready' ? 'ready' : 'downloading', current: '2.0.1', latest: '2.0.2',
       notes: 'Salons en ligne, bibliothèque partagée et mise à jour automatique.', mandatory: false, kind: 'setup',
       progress: 0.35, done_mb: 4.2, size_mb: 12.0, path: null, error: '', checked_at: NOW}
    : {state: offline ? 'idle' : 'uptodate', current: '2.0.1', latest: '2.0.1', notes: '', mandatory: false, kind: 'setup',
       progress: 0, done_mb: 0, size_mb: 0, path: null, error: '', checked_at: offline ? 0 : NOW};
  const MOCK_ONLINE = !wantOnline ? undefined : {
    server_url: 'https://dodotopia.cyber-dodo.fr', server_ok: !offline, server_version: '2.0.0', min_client: '1.6.0',
    client_too_old: false, offline_reason: offline ? 'connexion impossible (délai dépassé)' : '', checked_at: NOW,
    logged_in: logged, user: logged ? MOCK_USER : null, is_admin: adm && logged,
    login: waiting ? {state: 'waiting', url: 'https://dodotopia.cyber-dodo.fr/auth/discord/start?login_id=4f2b9c1e', error: '', expires_in: 540}
                   : {state: 'idle', url: '', error: '', expires_in: null},
    update: MOCK_UPDATE,
    library: {q: '', sort: tagArg ? 'trending' : 'recent', tag: tagArg, instrument: '', page: 1, pages: offline ? 0 : 2, total: offline ? 0 : 3,
      items: offline ? [] : (tagArg ? MOCK_ITEMS.filter(it => it.tags.includes(tagArg)) : MOCK_ITEMS), loading: false, error: '', at: offline ? 0 : NOW},
    gallery: {sort: 'recent', page: 1, pages: 2, total: 29, items: offline ? [] : MOCK_DRAWINGS, loading: false, error: '', at: offline ? 0 : NOW},
    gallery_upload: pubArg ? {state: 'done', error: '', seq: 1, item: {id: 36, title: 'logo', status: 'pending', page_url: 'https://dodotopia.cyber-dodo.fr/fr/galerie/36'}}
                           : {state: 'idle', error: '', item: null, seq: 0},
    drawing_open: {state: 'idle', id: null, title: '', error: '', seq: 0},
    room_url: lob ? 'https://dodotopia.cyber-dodo.fr/fr/salon/K7P2QD' : null,
    meta: {tags: ['piano', 'flute', 'lute', 'violin', 'harp', 'percussion', 'pop', 'rock', 'classique', 'jeu-video', 'anime', 'film', 'folk', 'noel', 'calme', 'rapide', 'facile', 'difficile'], max_tags: 8, licenses: ['own', 'public_domain', 'cc', 'unknown']},
    pending: {page: 1, pages: 1, total: adm ? MOCK_PENDING.length : 0, items: adm ? MOCK_PENDING : [], loading: false, error: '', at: adm ? NOW : 0},
    reports: {items: adm ? MOCK_REPORTS : [], loading: false, error: '', at: adm ? NOW : 0},
    jobs: {downloads: logged && !offline ? {'13': {state: 'downloading', progress: 0.42, error: '', song_id: null}} : {}, uploads: {}, imports: {}},
    room: MOCK_ROOM || MOCK_IDLE_ROOM, clock: (MOCK_ROOM || MOCK_IDLE_ROOM).room.clock};
  // fenêtre du jeu (get_state().game_window) et réponses simulées des appels de la phase 2 (core.js : window.MOCK_API)
  const gw = arg('gamewin');
  const MOCK_GAME = {found: gw !== 'off', foreground: false, elevated: gw === 'admin', checked: gw !== 'none', process: 'xdt.exe, Heartopia.exe'};
  const later = (v, ms) => new Promise(res => setTimeout(() => res(v), ms));
  window.MOCK_API = {
    song_tracks: () => later({ok: true, off: [4], tracks: [
      {index: 0, name: '', notes: 0, channels: [], drums: false},
      {index: 1, name: 'Piano droit', notes: 812, channels: [0], drums: false},
      {index: 2, name: 'Basse', notes: 344, channels: [1], drums: false},
      {index: 3, name: '', notes: 176, channels: [2], drums: false},
      {index: 4, name: 'Batterie', notes: 96, channels: [9], drums: true}]}, 150),
    test_key: () => later({ok: true, reason: 'Touche « Z » envoyée au jeu : tu dois avoir entendu une note.'}, 1200),
    protocol_status: () => later({registered: false, command: '', current: false}, 120),
    register_protocol: () => later({ok: true, error: null}, 400),
    online_import_url: url => later(/^https:\/\//.test(url) ? {ok: true, key: '1', error: null} : {ok: false, key: null, error: 'Lien invalide : colle l’adresse complète (https://…).'}, 500),
    room_exists: code => later({ok: true, code, valid: true, exists: true, full: false}, 150),
    save_drawing_png: (u, name) => later({ok: true, name: name + '.png', path: 'exports/' + name + '.png'}, 300),
    gallery_share: () => later({ok: true, error: null}, 600),
    open_external: () => later({ok: true, error: null}, 50),
    diag_preview: () => later({ok: true, audio: true, files: [{name: 'dodotopia.log', size: 48213, kind: 'log'},
      {name: 'cuisine.log', size: 1048576, kind: 'log'}, {name: 'cuisine_echec.png', size: 91820, kind: 'image'},
      {name: 'config.json', size: 8603, kind: 'config'}, {name: 'multi_ecoute.wav', size: 2400000, kind: 'audio'}]}, 100),
    diag_send: () => later({ok: true, code: 'K7P2QDMN', files: 5}, 700),
    diag_save: () => later({ok: true, name: 'rapport-dodotopia-20260928-193000.zip'}, 300),
  };
  const MOCK_TOASTS = [];
  if(location.search.includes('toast')) MOCK_TOASTS.push({id: 1, t: 0, msg: '2 musiques importées', kind: 'ok', sticky: false},
    {id: 2, t: 0, msg: 'Arrêt : touche pressée', kind: 'warn', sticky: false});
  if(upd) MOCK_TOASTS.push({id: 3, t: 0, msg: 'Version 1.8.0 disponible', kind: 'info', sticky: true,
    action: {label: 'Installer', method: 'update_install'}, progress: 35});

  // ---- catalogue simule : memes tables que assets/instruments/layouts.json (genere, ne pas retoucher
  // a la main). Sans lui, INST.cat reste nul en mode mock et le selecteur n'a ni disposition ni touches.
  const MOCK_LAYOUTS = [
    ["diatonic-15-2row","15 notes, 2 rangées","Do4 à Do6, gamme de do majeur, touches sur deux rangées.","key",[7,8],[[60,"Do4","a"],[62,"Ré4","s"],[64,"Mi4","d"],[65,"Fa4","f"],[67,"Sol4","g"],[69,"La4","h"],[71,"Si4","j"],[72,"Do5","q"],[74,"Ré5","w"],[76,"Mi5","e"],[77,"Fa5","r"],[79,"Sol5","t"],[81,"La5","y"],[83,"Si5","u"],[84,"Do6","i"]]],
    ["diatonic-15-3row","15 notes, 3 rangées","Do4 à Do6, gamme de do majeur, touches sur trois rangées.","key",[5,5,5],[[60,"Do4","y"],[62,"Ré4","u"],[64,"Mi4","i"],[65,"Fa4","o"],[67,"Sol4","p"],[69,"La4","h"],[71,"Si4","j"],[72,"Do5","k"],[74,"Ré5","l"],[76,"Mi5",";"],[77,"Fa5","n"],[79,"Sol5","m"],[81,"La5",","],[83,"Si5","."],[84,"Do6","/"]]],
    ["piano-diatonic-22","22 notes, piano diatonique","Do3 à Do6, gamme de do majeur, trois rangées.","key",[7,7,8],[[48,"Do3","z"],[50,"Ré3","x"],[52,"Mi3","c"],[53,"Fa3","v"],[55,"Sol3","b"],[57,"La3","n"],[59,"Si3","m"],[60,"Do4","a"],[62,"Ré4","s"],[64,"Mi4","d"],[65,"Fa4","f"],[67,"Sol4","g"],[69,"La4","h"],[71,"Si4","j"],[72,"Do5","q"],[74,"Ré5","w"],[76,"Mi5","e"],[77,"Fa5","r"],[79,"Sol5","t"],[81,"La5","y"],[83,"Si5","u"],[84,"Do6","i"]]],
    ["piano-chromatic-37","37 notes, piano chromatique","Do3 à Do6, toutes les altérations, trois rangées.","octave",[12,12,13],[[48,"Do3",","],[49,"Do♯3","l"],[50,"Ré3","."],[51,"Ré♯3",";"],[52,"Mi3","/"],[53,"Fa3","o"],[54,"Fa♯3","0"],[55,"Sol3","p"],[56,"Sol♯3","-"],[57,"La3","["],[58,"La♯3","="],[59,"Si3","]"],[60,"Do4","z"],[61,"Do♯4","s"],[62,"Ré4","x"],[63,"Ré♯4","d"],[64,"Mi4","c"],[65,"Fa4","v"],[66,"Fa♯4","g"],[67,"Sol4","b"],[68,"Sol♯4","h"],[69,"La4","n"],[70,"La♯4","j"],[71,"Si4","m"],[72,"Do5","q"],[73,"Do♯5","2"],[74,"Ré5","w"],[75,"Ré♯5","3"],[76,"Mi5","e"],[77,"Fa5","r"],[78,"Fa♯5","5"],[79,"Sol5","t"],[80,"Sol♯5","6"],[81,"La5","y"],[82,"La♯5","7"],[83,"Si5","u"],[84,"Do6","i"]]]
  ].map(([layoutId, labelFr, descriptionFr, autoTranspose, rows, notes]) => ({
    layoutId, labelFr, descriptionFr, autoTranspose, rows, noteCount: notes.length,
    keyboardReference: 'QWERTY US', status: 'community-documented-not-tested-in-game',
    sourceUrls: ['https://github.com/Jed556/AutoMidiPlayer/wiki/Support'],
    notes: notes.map(([midi, solfege, key]) => ({midi, solfege, note: '', key}))}));
  INST.cat = {categories: [{id:"strings",labelFr:"Cordes"},{id:"winds",labelFr:"Vents"},{id:"keys",labelFr:"Claviers"},{id:"percussion",labelFr:"Percussions"}], layouts: MOCK_LAYOUTS,
    octave_convention: 'Do4 / C4 = MIDI 60', retrieved_at: '2026-09-15',
    source_urls: ['https://build-heartopia.com/items'],
    keyboard_layout: has('qwerty') ? 'qwerty' : 'azerty',
    keyboard_layout_detected: has('qwerty') ? null : 'azerty'};

  // ---- conditions d'utilisation : faux get_terms (api() renvoie null hors pywebview, terms.js lit window.MOCK_TERMS)
  const termsArg = arg('terms');
  if(termsArg){
    const LOREM = ['Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed non risus. Suspendisse lectus tortor, dignissim sit amet, adipiscing nec, ultricies sed, dolor.',
      'Cras elementum ultrices diam. Maecenas ligula massa, varius a, semper congue, euismod non, mi. Proin porttitor, orci nec nonummy molestie, enim est eleifend mi, non fermentum diam nisl sit amet erat.',
      'Duis semper. Duis arcu massa, scelerisque vitae, consequat in, pretium a, enim. Pellentesque congue. Ut in risus volutpat libero pharetra tempor. Cras vestibulum bibendum augue.',
      'Praesent egestas leo in pede. Praesent blandit odio eu enim. Pellentesque sed dui ut augue blandit sodales. Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere cubilia Curae.'];
    const T = {
      fr: {h1: 'Conditions générales d’utilisation de DodoTopia', art: 'Article', foi: 'La version française des CGU fait foi ; la traduction anglaise n’est fournie qu’à titre d’information.',
        summary: ['DodoTopia est gratuit, pour ton usage personnel. Tu ne peux ni le revendre, ni le redistribuer, ni le modifier, ni le décompiler.',
          'DodoTopia n’a aucun lien avec Heartopia ni avec XD Games. C’est un projet indépendant fait par des joueurs.',
          'DodoTopia automatise le jeu : il envoie des touches et des clics à ta place, et il lit ton écran. Si tu l’utilises, tu risques une sanction dans le jeu : c’est ton choix et ta responsabilité.',
          'Aucune garantie. L’outil est fourni « en l’état » : il peut cesser de fonctionner à la prochaine mise à jour du jeu.',
          'Ce que tu partages (fichiers MIDI) reste sous ta responsabilité : tu dois en avoir le droit.',
          'Ton compte Discord ne sert qu’à t’identifier ; aucune donnée n’est revendue.']},
      en: {h1: 'DodoTopia Terms of Use', art: 'Section', foi: 'The French version of the terms prevails; this English translation is provided for information only.',
        summary: ['DodoTopia is free, for your personal use. You may not sell, redistribute, modify or decompile it.',
          'DodoTopia is not affiliated with Heartopia or XD Games. It is an independent project made by players.',
          'DodoTopia automates the game: it sends keys and clicks on your behalf and reads your screen. Using it may get you sanctioned in the game: that is your choice and your responsibility.',
          'No warranty. The tool is provided “as is”: it may stop working with the next game update.',
          'What you share (MIDI files) remains your responsibility: you must have the right to share it.',
          'Your Discord account is only used to identify you; no data is ever sold.']}};
    window.MOCK_TERMS = lang => {
      if(termsArg === 'fail') return null;
      const t = T[lang] || T.fr;
      const nb = termsArg === 'short' ? 0 : 40;   // short : l'essentiel et une ligne, sans article (plus court que la zone)
      let html = nb ? `<h1>${t.h1}</h1><p>Version : 2026-10</p><p>${t.foi}</p>` : `<p>${t.foi}</p>`, md = `# ${t.h1}

Version : 2026-10

${t.foi}
`;
      for(let a = 1, p = 0; p < nb; a++){
        html += `<h2>${t.art} ${a} — Lorem ipsum ${a}</h2>`; md += `
## ${t.art} ${a} — Lorem ipsum ${a}
`;
        for(let k = 0; k < 4 && p < nb; k++, p++){ html += `<p>${LOREM[(p + a) % LOREM.length]}</p>`; md += `
${LOREM[(p + a) % LOREM.length]}
`; }
      }
      return {version: '2026-10', lang, summary: t.summary, markdown: md, html};
    };
    if(termsArg === 'en') TERMS.lang = 'en';
  }

  render({version:'2.0.1', instruments: MOCK_INSTRUMENTS,
    instrument: instIdx, instrument_id: instCur.id, instrument_ready: instCur.ready,
    instrument_blocked: instCur.ready ? '' : instCur.blocked_reason,
    instrument_favorites: ['piano', 'lyre'], instrument_wizard: null,
    keyboard_layout: has('qwerty') ? 'qwerty' : 'azerty', keyboard_layout_pref: has('qwerty') ? 'qwerty' : 'auto',
    song_compat: MOCK_COMPAT,
    debug: has('debug'),
    songs: has('empty') ? [] : [{id:'a',name:'AriaMath',file:'AriaMath',fav:true,plays:12,added:1788700000,last_played:1788730000,duration:318,index:0},{id:'b',name:'Wish You Were Here',file:'P.FLOYD.Wish you were here K',fav:false,plays:0,added:1788720000,last_played:0,duration:95,index:1},{id:'c',name:'Blinding Lights',file:'The-Weeknd-Blinding-Lights',fav:false,plays:3,added:1788600000,last_played:1788600500,duration:124,index:2}],
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
    log:[], is_admin: !has('error') && gw !== 'admin', game_window: MOCK_GAME,
    deeplink: has('deeplink') ? {id: 1, action: 'room', label: 'Rejoindre le salon K7P2QD ?', params: {code: 'K7P2QD'}} : null,
    terms: {required: !!termsArg, version: '2026-10', accepted_version: null, accepted_at: null},
    toasts: MOCK_TOASTS,
    draw:{state: has('calib') ? 'calibrating' : has('drawing') ? 'drawing' : has('autocal') ? 'autocal' : 'idle', format:'16:9', step:2, progress_msg: has('autocal') ? 'mesure des cases…' : 'couleur 3 / 12',
      steps:[{key:'tl',title:'Coin haut-gauche de la toile',help:'Place la souris exactement sur le coin haut-gauche de la zone rayée où l’on dessine (pas le cadre).'},{key:'br',title:'Coin bas-droit de la toile',help:'Place la souris sur le coin bas-droit de la zone rayée.'},{key:'pal0',title:'Première couleur de la palette',help:'Survole la première pastille de couleur (en haut à gauche de la palette).'},{key:'pal1',title:'Dernière couleur de la palette',help:'Survole la dernière pastille (en bas à droite de la palette).'},{key:'palbtn',title:'Bouton « palette » (ouvre les nuances)',help:'Sans cliquer, survole le bouton rond avec l’icône palette, à gauche des pastilles de couleur.'},{key:'strip',title:'Bande des familles : la pastille du centre',help:'Clique sur le bouton palette : un bloc de 10 nuances apparaît. Survole la pastille au centre de la bande (celle encadrée en blanc).'},{key:'prev',title:'Flèche « précédent » de la bande',help:'Survole la flèche < à gauche de la bande des familles.'},{key:'next',title:'Flèche « suivant » de la bande',help:'Survole la flèche > à droite de la bande des familles.'},{key:'sub0',title:'Nuances : celle en haut à gauche',help:'Survole la nuance en haut à gauche du bloc de 10 nuances.'},{key:'sub1',title:'Nuances : celle en bas à droite',help:'Survole la nuance en bas à droite du même bloc.'},{key:'pencil',title:'Outil crayon',help:'Survole le bouton du crayon, à gauche.'},{key:'bucket',title:'Outil pot de peinture',help:'Survole le bouton du pot de peinture (remplissage).'},{key:'undo',title:'Bouton Annuler',help:'Survole la flèche « Annuler » au-dessus de la toile (facultatif).'}],
      done:1830, total:5184, elapsed:42, eta:75, countdown: has('countdown') ? 2.4 : 0, message:'', palette:null, shades_ok:true, formats:{'16:9':{cols:96,rows:54,calibrated:!has('nocal')},'4:3':{cols:72,rows:54,calibrated:false},'1:1':{cols:54,rows:54,calibrated:false},'3:4':{cols:40,rows:54,calibrated:false},'9:16':{cols:30,rows:54,calibrated:false}},
      validated:{'16:9':!has('noval') && !has('nocal'),'4:3':false,'1:1':false,'3:4':false,'9:16':false},
      tools:{pencil:true,bucket:true}, settings:{step_delay:0.012,click_delay:0.05,fill_background:true,skip_white:false}},
    cook:{state: has('cook') ? 'cooking' : has('ccalib') ? 'calibrating' : 'idle', phase:'cuisson', step:2,
      steps:[{key:'search_tl',title:'Zone de recherche : coin haut-gauche',help:'…'},{key:'search_br',title:'Zone de recherche : coin bas-droit',help:'…'},{key:'cook',title:'Bulle « cuisiner »',help:'Place la souris au centre de la bulle.'},{key:'tile',title:'Menu Recettes : la première tuile récente',help:'…'},{key:'cook_btn',title:'Menu Recettes : le bouton « Cuisiner »',help:'…'},{key:'spatula',title:'Bulle « spatule » (facultatif)',help:'…',optional:true},{key:'ready',title:'Bulle « récupérer » (gants)',help:'…'},{key:'neutral',title:'Un endroit vide où cliquer',help:'…'}],
      countdown: has('countdown') ? 2.4 : 0, elapsed:75, dishes:3, fires:5, message:'', stop_reason:'', calibrated: !has('nocal'), refs:{cook:!has('nocal'),ready:!has('nocal'),spatula:false}, ring_color:null,
      test_result: has('notest') || has('nocal') ? '' : 'bulle « cuisiner » en 820,440 (cook 0.91, ready 0.4, vert 0) ; menu fermé.',
      settings:{cookers:1,max_dishes:10,cook_timeout:240,match:0.55,click_delay:0.3,green_px:60}, screen_ok:true}});
  // l'apercu navigateur montre le meme en-tete que l'application : le logo vient du dossier assets
  const lg = document.getElementById('logo');
  if(lg && !lg.src){ lg.src = '../assets/logo.png'; lg.style.display = ''; }
  const mt = /tab=(music|image|cook|online)/.exec(location.search);
  // ?mock&sel : selecteur ouvert ; &keys : panneau « Voir les touches » de l'instrument actif
  if(has('sel')) setTimeout(() => openInstrumentSelector(), 0);
  else if(has('keys')) setTimeout(() => openKeysPanel(instCur.id), 0);
  if(mt) showTab(mt[1]);
  else if(wantOnline && !lob) showMusicView('discover');
  const mv = /[?&]view=(library|discover|together)/.exec(location.search);
  if(mv) showMusicView(mv[1]);
  if(adm) setTimeout(adminPanel, 0);              // espace d'administration ouvert
  if(has('help')) setTimeout(() => helpPanel(S), 0);        // panneau Aide
  if(has('picker')) setTimeout(() => openSongPicker(), 0);   // sélecteur de morceau du salon
  if(has('report')) setTimeout(() => openDiagReport(), 0);    // « Envoyer un rapport »
  if(has('tracks')){ $('songSet').open = true; render(S); setTimeout(() => $('songSet').scrollIntoView({block: 'start'}), 400); }  // réglages du morceau ouverts : pistes MIDI
  if(has('account')) setTimeout(accountPanel, 0);           // panneau Mon compte
  if(has('image') || has('drawing') || has('autocal')) loadImageData({name: 'logo', data: '../assets/logo.png'});
  // &published : grille reprise de la galerie (cases générées) et dépôt en attente de modération
  if(pubArg){
    const W = 40, H = 40, cells = [];
    for(let j = 0; j < H; j++) for(let i = 0; i < W; i++){ const d = Math.hypot(i - 20, j - 20); cells.push(d > 19 ? -1 : [14, 54, 64, 44, 24, 34][Math.floor(d / 3.3) % 6]); }
    setTimeout(() => { loadGridJob({id: 36, title: 'Soleil de Heartopia', job: {format: '1:1', w: W, h: H, cells}}); DSHARE.upSeq = 1; render(S); }, 0);
  }
  if(galArg){ showTab('image'); setTimeout(() => showDrawView('gallery'), 0); }
  if(importArg) setTimeout(() => importUrlDialog(''), 0);
  if(shareArg || lob) window.MOCK_KEEP_MENU = true;
  if(shareArg) setTimeout(() => { showMusicView('discover'); const b = document.querySelector('#onlineList [data-act="share"]'); if(b) b.click(); }, 1500);
  if(formArg) setTimeout(() => shareSongDialog(Object.assign({}, S.songs[0], {source_url: 'https://onlinesequencer.net/1234567', source_name: 'Online Sequencer'})), 0);
  if(location.search.includes('dialog')) dialog({title:'Retirer la musique', icon:'trash', danger:true, ok:'Retirer', html:`Retirer <b>AriaMath</b> de la bibliothèque ?<br><small>Le fichier d'origine n'est pas touché.</small>`});

  // ?mock&settings[=multi] : panneau Réglages avec un schéma factice (même forme que get_settings_schema)
  const ms = /[?&]settings(?:=([a-z]+))?/.exec(location.search);   // section : id de SETTINGS_SECTIONS
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
    bool('online.auto_update', 'online', false); bool('online.rich_presence', 'online', true); bool('online.now_playing_file', 'online', false);
    choice('general.lang', 'general', 'auto', ['auto', 'fr', 'en', 'es', 'de', 'pt-BR', 'zh-CN', 'ja', 'th', 'id', 'fil']);
    if(location.search.includes('adv')) SET.advOpen = true;   // &adv : « Avancé » déplié
    openSettings({fields:F, sections:['general', 'lecture', 'hotkeys', 'multi', 'draw', 'grids', 'cook', 'online'],
      multi_devices:['Digital Audio (S/PDIF) (High Definition Audio Device)', 'Casque (2- CORSAIR VOID ELITE Wireless Gaming Headset)', 'VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)'],
      songs_folder:'C:\\Users\\moi\\AppData\\Local\\DodoTopia\\songs', data_dir:'C:\\Users\\moi\\AppData\\Local\\DodoTopia', version:'2.0.1', install_kind:'setup',
      logs:{multi:true, dessin:true, cuisine:false, online:false}, online_ready:false}, ms[1] || null);
    const sq = /[?&]settingsq=([^&]+)/.exec(location.search);   // &settingsq=texte : recherche dans les réglages
    if(sq){ const inp = $('settingsSearch'); inp.value = decodeURIComponent(sq[1]); inp.oninput(); }
  }
}
