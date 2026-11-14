/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- 主题与字号（1.3.0）。在 <head> 里最先加载，所以页面第一次绘制前就已经是正确的主题，不会闪白/闪黑。
   - 主题偏好 theme：'system' | 'paper'（浅色纸感）| 'glass'（夜蓝玻璃）| 'dark'（暗室）。
     <html data-theme> 永远只写 paper / glass / dark；'system' 时系统浅色→paper、系统深色→dark，并监听系统变化（同时写 data-theme-pref）。
     旧值兼容：'light' 当作 'paper'；读到不认识的值一律回落 'system'。
   - 字号 font_size：'small' | 'standard' | 'large' | 'xlarge'，对应根字体缩放 90% / 100% / 112% / 125%（CSS 变量 --fscale）。
   - 设置读回之前先用 localStorage 里缓存的上一次值；读回后以设置为准（boot.js / settings.js 调 applyAppearance）。
   localStorage 可能不可用（隐私模式等），读写全部包在 try/catch 里。 */
const THEME_KEY = 'lh_theme', FSIZE_KEY = 'lh_font_size';
const FSIZE_SCALE = {small: 0.9, standard: 1, large: 1.12, xlarge: 1.25};
const THEME_OK = ['system', 'paper', 'glass', 'dark'];
const THEME_MQ = (window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null);
let themePref = 'system', fontSizePref = 'standard';
function cacheGet(k){ try { return window.localStorage.getItem(k); } catch(e){ return null; } }
function cacheSet(k, v){ try { window.localStorage.setItem(k, v); } catch(e){} }
function themeNormalize(t){ if (t === 'light') return 'paper'; return THEME_OK.indexOf(t) >= 0 ? t : 'system'; }
function themeResolved(pref){ if (pref === 'system') return (THEME_MQ && THEME_MQ.matches) ? 'dark' : 'paper'; return pref; }
function themeRender(){
  const root = document.documentElement;
  root.setAttribute('data-theme', themeResolved(themePref));
  root.setAttribute('data-theme-pref', themePref);
  root.setAttribute('data-font-size', fontSizePref);
  root.style.setProperty('--fscale', String(FSIZE_SCALE[fontSizePref]));
}
/* 应用并缓存。参数不合法（后端缺字段、旧版本设置）就当没给：主题退回“跟随系统”，字号退回“标准”。 */
function applyAppearance(theme, fontSize){
  themePref = themeNormalize(theme);
  fontSizePref = Object.prototype.hasOwnProperty.call(FSIZE_SCALE, fontSize) ? fontSize : 'standard';
  themeRender(); cacheSet(THEME_KEY, themePref); cacheSet(FSIZE_KEY, fontSizePref);
}
function appearanceNow(){ return {theme: themePref, font_size: fontSizePref}; }
(function(){
  const t = cacheGet(THEME_KEY), f = cacheGet(FSIZE_KEY);
  themePref = themeNormalize(t);
  fontSizePref = (f && Object.prototype.hasOwnProperty.call(FSIZE_SCALE, f)) ? f : 'standard';
  themeRender();
  if (THEME_MQ){
    const onChange = () => { if (themePref === 'system') themeRender(); };
    if (THEME_MQ.addEventListener) THEME_MQ.addEventListener('change', onChange); else if (THEME_MQ.addListener) THEME_MQ.addListener(onChange);
  }
})();
