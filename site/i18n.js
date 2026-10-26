// Languages of the site: French, English, German and Italian (the languages of the Alps).
//
// The language is chosen in this order: the one the visitor picked with the selector in the header (kept in this
// browser), else the first language of the browser's own list (navigator.languages) that the site has, else English.
// The browser's language, not the place of the connection: it is what the visitor reads, it works on a static site
// (a page on GitHub Pages never sees the visitor's address), and a French speaker in Zurich keeps French.
//
// The texts are in site/i18n/<code>.js, one file per language with the same keys (tests/test_i18n.py checks it).
// English is always loaded, and is what a missing key falls back to. The other languages are loaded on demand.
// Nothing here is a service: no text leaves the site, and nothing is translated on the fly.
//
// A text is a string with {name} places, or an object with the forms of a plural ({ one, other }, chosen by the
// language's own rules from the number n). A number given as a parameter is written in the visitor's format.

import en from './i18n/en.js';

export const LANGS = [
  { code: 'fr', name: 'Français' },
  { code: 'en', name: 'English' },
  { code: 'de', name: 'Deutsch' },
  { code: 'it', name: 'Italiano' },
];
export const DEFAULT_LANG = 'en';
const STORE = 'lang';
// Swiss German (gsw) has no written form of its own on the web: it is read in standard German
const ALIASES = { gsw: 'de' };

const catalogues = { en };
let lang = DEFAULT_LANG;
let messages = en;
let locale = 'en-US';
let plurals = new Intl.PluralRules('en');
let numbers = new Intl.NumberFormat('en-US');
let decimals = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const listeners = new Set();

/** The site language for a language tag of the browser ("fr-CH", "de", "gsw"), or null when the site has none. */
export function langOf(tag) {
  const primary = String(tag || '').toLowerCase().split(/[-_]/)[0];
  const code = ALIASES[primary] || primary;
  return LANGS.some((l) => l.code === code) ? code : null;
}

/** The languages the browser lists, most wanted first. */
export function browserLanguages() {
  if (typeof navigator === 'undefined') return [];
  return navigator.languages && navigator.languages.length ? [...navigator.languages] : [navigator.language].filter(Boolean);
}

function savedLang() {
  try { return langOf(localStorage.getItem(STORE)); } catch (_) { return null; }
}

/** The language to start with: the saved choice, else the first of the browser's languages the site has, else English. */
export function detectLang(preferred = browserLanguages(), saved = savedLang()) {
  if (saved) return saved;
  for (const tag of preferred) {
    const code = langOf(tag);
    if (code) return code;
  }
  return DEFAULT_LANG;
}

/** The tag for numbers and dates: the browser's own regional one when it is of this language (fr-CH writes 1 234
 * with another space than fr-FR, de-CH writes 1’234), else the language itself. */
export function localeFor(code, preferred = browserLanguages()) {
  for (const tag of preferred) {
    const primary = String(tag || '').toLowerCase().split(/[-_]/)[0];
    if (primary === 'gsw' && code === 'de') return 'de-CH';
    if (primary === code) {
      try { return new Intl.NumberFormat(tag) && tag; } catch (_) { return code; }
    }
  }
  return code;
}

async function load(code) {
  if (catalogues[code]) return catalogues[code];
  try {
    catalogues[code] = (await import(`./i18n/${code}.js`)).default;
  } catch (_) {
    return null;   // the file did not come: the site stays in the language it has
  }
  return catalogues[code];
}

/** Switch language: loads its texts, then tells the listeners. ``save``: keep the choice in this browser (a choice
 * made with the selector; the language found from the browser is not kept, so a change of browser language shows). */
export async function setLang(code, { save = false } = {}) {
  const next = langOf(code) || DEFAULT_LANG;
  const text = await load(next);
  if (!text) return lang;
  lang = next;
  messages = text;
  locale = localeFor(next);
  plurals = new Intl.PluralRules(locale);
  numbers = new Intl.NumberFormat(locale);
  decimals = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (typeof document !== 'undefined') document.documentElement.lang = next;
  if (save) { try { localStorage.setItem(STORE, next); } catch (_) { /* private mode: the choice lasts until the page closes */ } }
  listeners.forEach((f) => f(next));
  return lang;
}

/** Start the site in the visitor's language (call once, before the first page is drawn). */
export const initI18n = () => setLang(detectLang());

export const getLang = () => lang;
export const getLocale = () => locale;
export const onLang = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };

const raw = (key) => (key in messages ? messages[key] : (key in en ? en[key] : key));

function pick(value, params) {
  if (value && typeof value === 'object') {
    const form = plurals.select(Number(params && params.n));
    return value[form] ?? value.other ?? '';
  }
  return value;
}

/** A number as the visitor writes it (1 234 or 1,234 or 1’234), rounded to a whole number. */
export const fmtNumber = (n) => numbers.format(Math.round(Number(n)));
/** A number with one decimal (12.3 or 12,3). */
export const fmtDecimal = (n) => decimals.format(Number(n));

/** The text for ``key``; ``{name}`` places are filled from ``params``, a plural form is chosen from ``params.n``. */
export function t(key, params) {
  const text = pick(raw(key), params);
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name) => {
    if (!(name in params)) return whole;
    const v = params[name];
    return typeof v === 'number' ? fmtNumber(v) : String(v);
  });
}

/** Like t(), for a text that holds a link or other nodes: returns the pieces (strings and the given nodes) to give
 * to h(); ``{name}`` is replaced by the node ``params.name``. */
export function tr(key, params = {}) {
  const text = pick(raw(key), params);
  return text.split(/(\{\w+\})/g).filter(Boolean).map((part) => {
    const m = /^\{(\w+)\}$/.exec(part);
    if (!m || !(m[1] in params)) return part;
    const v = params[m[1]];
    return typeof v === 'number' ? fmtNumber(v) : v;
  });
}

/** A date such as "29 Sep 2021" (the month shortened in the visitor's language), from an ISO date "2021-09-29". */
export function fmtDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  if (!m) return null;
  if (lang === 'en') {
    return `${Number(m[3])} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(m[2]) - 1]} ${m[1]}`;
  }
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(d);
}
