// Small helpers: DOM building, number and date formats (in the visitor's language: site/i18n.js).

import { fmtDay, fmtDecimal, fmtNumber, getLang, t } from './i18n.js';

export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, '');
    else node.setAttribute(k, v);
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export const SVG_NS = 'http://www.w3.org/2000/svg';
export function s(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) node.setAttribute(k, v);
  append(node, children);
  return node;
}

export const $ = (sel, root = document) => root.querySelector(sel);

export function fmtInt(n) {
  return n == null || Number.isNaN(Number(n)) ? '–' : fmtNumber(n);
}
export function fmtKm(n) {
  return n == null ? '–' : `${fmtDecimal(n)} km`;
}
export function fmtDur(seconds) {
  if (seconds == null) return '–';
  const m = Math.round(seconds / 60);
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
}
export function fmtDate(iso) {
  return iso ? String(iso).slice(0, 10) : '–';
}
export function pilotName(profile) {
  return (profile && profile.display_name) || t('pilot.anonymous');
}

/**
 * A table. With `sorting` ({ key, dir, onSort(key) }), a header that has a `key` becomes a button
 * that sorts the table by that column; the current column shows an arrow.
 */
export function table(headers, rows, cls, sorting) {
  const head = (x) => {
    const sortable = sorting && x.key;
    const active = sortable && sorting.key === x.key;
    const arrow = active ? (sorting.dir === 'asc' ? ' ▲' : ' ▼') : '';
    return h('th', {
      class: [x.num ? 'num' : '', x.cls || ''].join(' ').trim() || null,
      'aria-sort': active ? (sorting.dir === 'asc' ? 'ascending' : 'descending') : null,
    }, sortable
      ? h('button', { class: 'sort', type: 'button', title: t('table.sortBy', { label: x.label }), onclick: () => sorting.onSort(x.key) }, x.label + arrow)
      : x.label);
  };
  return h('div', { class: 'table-wrap' },
    h('table', { class: cls },
      h('thead', null, h('tr', null, headers.map(head))),
      h('tbody', null, rows)));
}

export function notice(kind, ...children) {
  return h('div', { class: `notice notice-${kind}`, role: kind === 'error' ? 'alert' : 'status' }, ...children);
}

const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const FALLBACK_TITLE = new RegExp(`^Hike & Fly · (\\d{1,2}) (${EN_MONTHS.join('|')}) (\\d{4})(?: · ([\\d,]+) m)?$`);

/**
 * A title the engine stored, in the language of the visitor. The engine and the server write titles in English
 * (src/mbhf/titles.py: « Pointe de Beauregard from Les Verrier », and rows.py: « Hike & Fly · 29 Sep 2021 · 1,606 m »
 * when OpenStreetMap gave no name); the stored title is not changed, only what is shown. A name from OpenStreetMap
 * or the FFVL is shown as it is.
 */
function localTitle(title) {
  if (getLang() === 'en') return title;
  const day = FALLBACK_TITLE.exec(title);
  if (day) {
    const iso = `${day[3]}-${String(EN_MONTHS.indexOf(day[2]) + 1).padStart(2, '0')}-${day[1].padStart(2, '0')}`;
    return ['Hike & Fly', fmtDay(iso), day[4] ? `${fmtNumber(day[4].replace(/,/g, ''))} m` : null].filter(Boolean).join(' · ');
  }
  const parts = title.split(' from ');
  return parts.length === 2 && parts[0] && parts[1] ? t('title.from', { takeoff: parts[0], start: parts[1] }) : title;
}

/** The title to show: the stored one, or "Hike & Fly · 29 Sep 2021 · 1,606 m" when OpenStreetMap gave no name. */
export function outingTitle(o) {
  if (o.title && o.title !== 'Hike & Fly outing') return localTitle(o.title);
  const parts = ['Hike & Fly'];
  const day = fmtDay(o.outing_date);
  if (day) parts.push(day);
  if (o.summit_alt != null) parts.push(`${fmtNumber(o.summit_alt)} m`);
  return parts.join(' · ');
}
