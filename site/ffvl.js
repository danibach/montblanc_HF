// The official FFVL take-offs (▲) and landings (▼) on the take-off map, coloured by their status, with their card on
// a click: good winds on a rose, walk from the car park, warnings, restrictions, ideal conditions, gear, notes.
// Source: FFVL « Terrains de pratique » (Licence Ouverte 2.0), copied each week by scripts/sync_sites.py.

import { h } from './util.js';

// only from this zoom on, and only the ones in view: 2,000 markers at once would hide everything else
const MIN_ZOOM = 10;
const STATUS = {
  actif: { cls: 'ok', label: 'Active' },
  actif_autorisation_systematique_requise: { cls: 'ask', label: 'Permission needed each time' },
  interdit_sauf_autorisation: { cls: 'ask', label: 'Forbidden without permission' },
  interdit: { cls: 'no', label: 'Forbidden' },
};
const KIND = { T: 'Take-off', L: 'Landing', TL: 'Take-off and landing' };
// the FFVL writes the winds in French: N, NE, E, SE, S, SO, O, NO
const DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];
const EN = { N: 'N', NE: 'NE', E: 'E', SE: 'SE', S: 'S', SO: 'SW', O: 'W', NO: 'NW' };
const SVG = 'http://www.w3.org/2000/svg';

function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const c of children) node.append(c);
  return node;
}

/** ▲, ▼ or both, as markup for the marker (built from fixed strings only). */
function triangles(kind, cls) {
  const up = '<path d="M9 1 L17 15 L1 15 Z"/>';
  const down = '<path d="M1 1 L17 1 L9 15 Z"/>';
  const one = (d) => `<svg class="tri ${cls}" width="18" height="16" viewBox="0 0 18 16">${d}</svg>`;
  return (kind.includes('T') ? one(up) : '') + (kind.includes('L') ? one(down) : '');
}

/** The good winds on a rose: the sectors the FFVL lists are filled. */
function rose(winds) {
  const ok = new Set(String(winds || '').toUpperCase().split(/[;,\s]+/).filter(Boolean));
  const box = svg('svg', { class: 'rose', width: 76, height: 76, viewBox: '-38 -38 76 76', role: 'img', 'aria-label': 'Good winds' },
    svg('circle', { r: 30 }));
  DIRS.forEach((d, i) => {
    const a0 = ((i * 45 - 22.5 - 90) * Math.PI) / 180;
    const a1 = ((i * 45 + 22.5 - 90) * Math.PI) / 180;
    if (ok.has(d)) {
      box.append(svg('path', { class: 'on', d: `M0 0 L${30 * Math.cos(a0)} ${30 * Math.sin(a0)} A30 30 0 0 1 ${30 * Math.cos(a1)} ${30 * Math.sin(a1)} Z` }));
    }
    const am = ((i * 45 - 90) * Math.PI) / 180;
    const label = svg('text', { x: 27 * Math.cos(am), y: 27 * Math.sin(am) + 3, 'text-anchor': 'middle' });
    label.textContent = EN[d];
    box.append(label);
  });
  return box;
}

/** Text with its web addresses made into links (as nodes: the text comes from the FFVL file). */
function linked(text) {
  return String(text).split(/(https?:\/\/[^\s]+)/g).map((part, i) => (i % 2
    ? h('a', { href: part, target: '_blank', rel: 'noopener noreferrer' }, part)
    : part));
}

function card(site, info) {
  const st = STATUS[site.status] || { cls: 'unknown', label: site.status || 'Status unknown' };
  const winds = String(site.winds || '').toUpperCase().split(/[;,\s]+/).filter(Boolean).map((d) => EN[d] || d);
  const row = (label, value) => (value == null || value === '' ? null : [h('dt', null, label), h('dd', null, linked(value))]);
  const head = h('h3', null);
  head.innerHTML = triangles(site.kind, st.cls); // fixed markup, no text from the file
  head.append(` ${site.name}`);
  return h('div', { class: 'ffvl-card' },
    head,
    h('p', { class: 'hint' }, `FFVL ${(KIND[site.kind] || 'site').toLowerCase()}${site.alt != null ? ` · ${Math.round(site.alt)} m` : ''}${info.city ? ` · ${info.city}` : ''}`),
    h('span', { class: `chip ${st.cls}` }, st.label),
    h('div', { class: 'ffvl-top' }, rose(site.winds),
      h('dl', null, row('Good winds', winds.join(' · ') || '–'),
        info.walk_min ? row('From the car park', `${info.walk_min} min on foot`) : null, row('Gear', info.gear))),
    h('dl', null, row('Ideal conditions', info.ideal), row('Warnings', info.warnings), row('Restrictions', info.restrictions),
      row('Experience', info.experience), row('Access', info.access), row('Notes', info.notes)),
    h('p', { class: 'src' }, `Source: FFVL, « Terrains de pratique » (Licence Ouverte 2.0)${info.league ? ` · ${String(info.league).replace(/^\d+\s*-\s*/, '')}` : ''}${info.updated ? ` · updated ${String(info.updated).slice(0, 10)}` : ''}`));
}

/**
 * A layer of the FFVL sites for ``map``: markers for the ones in view from MIN_ZOOM on, redrawn as the map moves.
 * ``loadInfo(id)`` reads a site's card when it is clicked.
 */
export function ffvlLayer(L, map, sites, loadInfo) {
  const layer = L.layerGroup();
  const shown = new Map();
  const cards = new Map(); // the cards already read
  function redraw() {
    if (!map.hasLayer(layer)) return;
    if (map.getZoom() < MIN_ZOOM) { layer.clearLayers(); shown.clear(); return; }
    const view = map.getBounds().pad(0.2);
    for (const [id, mk] of shown) if (!view.contains(mk.getLatLng())) { layer.removeLayer(mk); shown.delete(id); }
    for (const s of sites) {
      if (shown.has(s.id) || !view.contains([s.lat, s.lon])) continue;
      const st = STATUS[s.status] || { cls: 'unknown' };
      const icon = L.divIcon({ className: 'ffvl-mark', html: triangles(s.kind, st.cls), iconSize: [s.kind === 'TL' ? 36 : 18, 16] });
      const mk = L.marker([s.lat, s.lon], { icon, title: `${s.name} (FFVL ${(KIND[s.kind] || '').toLowerCase()})`, zIndexOffset: -500 });
      mk.bindPopup(h('div', { class: 'ffvl-card' }, h('p', { class: 'hint' }, 'Loading…')), { maxWidth: 320, minWidth: 260 });
      mk.on('popupopen', async () => {
        if (!cards.has(s.id)) cards.set(s.id, await loadInfo(s.id).catch(() => ({})));
        mk.setPopupContent(card(s, cards.get(s.id)));
      });
      layer.addLayer(mk);
      shown.set(s.id, mk);
    }
  }
  map.on('moveend zoomend', redraw);
  layer.on('add', () => map.whenReady(redraw)); // the layer can be added before the map has a view
  return layer;
}
