// DodoTopia : thème de l'interface (clair, sombre, ou celui du système). Script classique chargé juste après
// i18n.js, AVANT le premier rendu : l'attribut data-theme est posé sur <html> au plus tôt, sans flash.
// Préférence purement locale (localStorage « dodotopia.theme » = auto | light | dark) : aucun appel api.
//   auto  : pas d'attribut, tokens.css suit prefers-color-scheme ;
//   light / dark : data-theme force le thème, quel que soit le système.
const THEME_KEY = 'dodotopia.theme';
const THEMES = ['auto', 'light', 'dark'];
function getTheme(){
  try{ const v = localStorage.getItem(THEME_KEY); return THEMES.includes(v) ? v : 'auto'; }catch(e){ return 'auto'; }
}
function applyTheme(v){
  const root = document.documentElement;
  if(v === 'light' || v === 'dark') root.dataset.theme = v;
  else delete root.dataset.theme;
}
function setTheme(v){
  v = THEMES.includes(v) ? v : 'auto';
  try{ if(v === 'auto') localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, v); }catch(e){}
  applyTheme(v);
  return v;
}
applyTheme(getTheme());
