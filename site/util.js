// Small helpers: DOM building, number and date formats.

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
  return n == null || Number.isNaN(Number(n)) ? '–' : Math.round(Number(n)).toLocaleString('en-US');
}
export function fmtKm(n) {
  return n == null ? '–' : `${Number(n).toFixed(1)} km`;
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
  return (profile && profile.display_name) || 'Anonymous';
}

export function table(headers, rows, cls) {
  return h('div', { class: 'table-wrap' },
    h('table', { class: cls },
      h('thead', null, h('tr', null, headers.map((x) => h('th', { class: [x.num ? 'num' : '', x.cls || ''].join(' ').trim() || null }, x.label)))),
      h('tbody', null, rows)));
}

export function notice(kind, ...children) {
  return h('div', { class: `notice notice-${kind}`, role: kind === 'error' ? 'alert' : 'status' }, ...children);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** The title to show: the stored one, or "Hike & Fly · 29 Sep 2021 · 1,606 m" when OpenStreetMap gave no name. */
export function outingTitle(o) {
  if (o.title && o.title !== 'Hike & Fly outing') return o.title;
  const parts = ['Hike & Fly'];
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(o.outing_date || '');
  if (m) parts.push(`${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`);
  if (o.summit_alt != null) parts.push(`${Math.round(o.summit_alt).toLocaleString('en-US')} m`);
  return parts.join(' · ');
}
