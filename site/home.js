// The home page (Sarah, 30 October 2026): the question, a search and the flying sectors, the map of the take-offs,
// the latest outings, and for inspiration the outings that chain several take-offs.
// H&F Tracks is a library of outings: nothing here ranks the pilots.

import { sectorOf } from './sectors.js';
import { h, s, fmtInt, fmtDate, outingTitle, pilotName } from './util.js';
import { t } from './i18n.js';

// Two take-offs of one outing closer than this are the same one (a second flight from the same place is a lap, not
// a chain).
const SAME_TAKEOFF_M = 300;
// A flight's take-off is named after the take-off of the register (or of another outing) within this distance.
const NAME_M = 300;
const LATEST = 3;
const COMBOS = 3;
const SECTORS = 8;

function metres(a, b) {
  const r = Math.PI / 180;
  const x = Math.sin(((b[0] - a[0]) * r) / 2) ** 2
    + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(((b[1] - a[1]) * r) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(x));
}

/** A small drawing of a line ([[lat, lon], …]) in a 200 × 80 box. ``parts``: [{line, colour, dash}]. */
function mini(parts) {
  const all = parts.flatMap((p) => p.line);
  if (all.length < 2) return null;
  const k = Math.cos((all[0][0] * Math.PI) / 180);
  const xs = all.map((p) => p[1] * k);
  const ys = all.map((p) => p[0]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const span = Math.max(x1 - x0, (y1 - y0) * 2.5, 1e-6); // the box is 2.5 times wider than high
  const scale = Math.min(176 / span, 64 / Math.max(y1 - y0, 1e-6));
  const ox = 100 - ((x0 + x1) / 2) * scale;
  const oy = 40 + ((y0 + y1) / 2) * scale;
  const d = (line) => line.map((p, i) => `${i ? 'L' : 'M'}${(p[1] * k * scale + ox).toFixed(1)} ${(oy - p[0] * scale).toFixed(1)}`).join(' ');
  return s('svg', { viewBox: '0 0 200 80', class: 'mini', 'aria-hidden': 'true' },
    parts.map((p) => s('path', { d: d(p.line), fill: 'none', stroke: '#ece0cf', 'stroke-width': 9, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })),
    parts.map((p) => s('path', { d: d(p.line), fill: 'none', stroke: p.colour, 'stroke-width': 2, 'stroke-dasharray': p.dash || null, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })));
}

const nums = (o) => h('span', { class: 'cc-nums' },
  h('span', { class: 'up' }, `+${fmtInt(o.dplus_m)} m`), ' · ', h('span', { class: 'down' }, `−${fmtInt(o.dminus_m)} m`));

function outingCard(o, line) {
  return h('a', { class: 'climb-card', href: `#/outing/${o.id}` },
    line && line.length > 1 ? mini([{ line, colour: '#1f7a4d' }]) : null,
    h('span', { class: 'cc-body' },
      h('span', { class: 'cc-who' }, pilotName(o.profiles), ' · ', fmtDate(o.outing_date)),
      h('b', { class: 'cc-title' }, outingTitle(o)),
      nums(o)));
}

/** The distinct take-offs of an outing's flights, in the order flown: [[lat, lon, alt], …]. */
function takeoffsOf(o) {
  const out = [];
  for (const f of o.flights || []) {
    const p = f && f.takeoff;
    if (!p || p.lat == null) continue;
    if (!out.some((q) => metres(q, [p.lat, p.lon]) < SAME_TAKEOFF_M)) out.push([p.lat, p.lon, p.alt]);
  }
  return out;
}

/** The outings that chain take-offs, the most take-offs first, then the highest climb. */
export function combos(rows) {
  return rows.map((o) => ({ o, takeoffs: takeoffsOf(o) })).filter((c) => c.takeoffs.length >= 2)
    .sort((a, b) => b.takeoffs.length - a.takeoffs.length || (b.o.dplus_m || 0) - (a.o.dplus_m || 0));
}

function comboCard({ o, takeoffs }, names) {
  // the drawing: each flight in orange, from its take-off to its landing, and the way on foot to the next take-off
  const flights = (o.flights || []).filter((f) => f && f.takeoff && f.landing);
  const parts = [];
  flights.forEach((f, i) => {
    parts.push({ line: [[f.takeoff.lat, f.takeoff.lon], [f.landing.lat, f.landing.lon]], colour: '#ff5a1f', dash: '4 3' });
    const next = flights[i + 1];
    if (next) parts.push({ line: [[f.landing.lat, f.landing.lon], [next.takeoff.lat, next.takeoff.lon]], colour: '#1f7a4d' });
  });
  const chain = [];
  takeoffs.forEach((p, i) => { if (i) chain.push(h('i', null, '→')); chain.push(h('span', null, names(p))); });
  return h('a', { class: 'climb-card', href: `#/outing/${o.id}` },
    mini(parts),
    h('span', { class: 'cc-body' },
      h('span', { class: 'cc-who' }, pilotName(o.profiles), ' · ', fmtDate(o.outing_date)),
      h('b', { class: 'cc-title' }, outingTitle(o)),
      h('span', { class: 'hint' }, t('home.takeoffs', { n: takeoffs.length })),
      h('span', { class: 'chain' }, chain),
      nums(o)));
}

const HERO = () => s('svg', { class: 'warm-sky', viewBox: '0 0 1000 380', preserveAspectRatio: 'xMidYMax slice', 'aria-hidden': 'true' },
  s('defs', null, s('linearGradient', { id: 'dawn', x1: 0, y1: 0, x2: 0, y2: 1 },
    s('stop', { offset: 0, 'stop-color': '#f4d3b4' }), s('stop', { offset: 0.6, 'stop-color': '#fae6d2' }), s('stop', { offset: 1, 'stop-color': '#fbf8f4' }))),
  s('rect', { width: 1000, height: 380, fill: 'url(#dawn)' }),
  s('circle', { cx: 760, cy: 150, r: 46, fill: '#ffd9ad', opacity: 0.9 }),
  s('path', { d: 'M0 270 L120 215 L220 240 L350 150 L440 190 L530 120 L630 175 L730 140 L850 200 L1000 165 L1000 380 L0 380Z', fill: '#e9c6ad' }),
  s('path', { d: 'M0 305 L130 262 L250 282 L370 220 L480 255 L600 205 L700 240 L820 215 L1000 258 L1000 380 L0 380Z', fill: '#d8aa8f' }),
  s('path', { d: 'M0 345 L170 312 L320 326 L470 292 L630 318 L790 296 L1000 320 L1000 380 L0 380Z', fill: '#bb8c75' }));

const MAP_PICTURE = () => s('svg', { viewBox: '0 0 400 240', preserveAspectRatio: 'xMidYMid slice', 'aria-hidden': 'true' },
  s('rect', { width: 400, height: 240, fill: '#f4ece1' }),
  s('g', { fill: 'none', stroke: '#e6d8c6' },
    ['M0 40 C60 30 90 60 150 50 S260 20 400 40', 'M0 80 C70 70 120 100 190 88 S300 60 400 80', 'M0 125 C80 112 130 150 210 132 S320 108 400 124',
      'M0 170 C70 160 140 190 220 176 S330 150 400 168', 'M0 210 C90 200 150 228 230 214 S340 196 400 210'].map((d) => s('path', { d }))),
  s('path', { d: 'M40 20 C70 40 60 80 90 110 S80 170 110 220', fill: 'none', stroke: '#cfe0ea', 'stroke-width': 9, opacity: 0.8 }),
  s('g', { opacity: 0.5 }, [[150, 120, 26], [160, 132, 18], [236, 96, 20], [290, 150, 16], [200, 176, 14]].map(([cx, cy, r]) => s('circle', { cx, cy, r, fill: '#ff8a4c', opacity: 0.45 }))),
  s('path', { d: 'M118 176 C130 160 140 146 150 134 S158 122 162 116', fill: 'none', stroke: '#1f7a4d', 'stroke-width': 1.8, 'stroke-linecap': 'round' }),
  s('path', { d: 'M200 160 C214 140 226 120 232 106', fill: 'none', stroke: '#1f7a4d', 'stroke-width': 1.8, 'stroke-linecap': 'round' }),
  s('g', { fill: '#ff5a1f', stroke: '#fff', 'stroke-width': 1 }, ['M157 118 L162 109 L167 118Z', 'M228 108 L233 99 L238 108Z', 'M285 152 L290 143 L295 152Z', 'M196 178 L201 169 L206 178Z'].map((d) => s('path', { d }))));

/**
 * The home page. ``latest``: the newest outings (listOutings); ``mapRows``: the outings of the map (getMapOutings);
 * ``sites``, ``routes``: the take-offs and the itineraries of the map; ``flown``: the newest outings with their flights.
 */
export function buildHome({ latest, mapRows, sites, routes, flown }) {
  const search = h('input', { type: 'search', name: 'q', placeholder: t('home.search'), 'aria-label': t('home.search'), autocomplete: 'off' });
  const form = h('form', { class: 'warm-search', role: 'search', onsubmit: (ev) => {
    ev.preventDefault();
    location.hash = search.value.trim() ? `#/map?q=${encodeURIComponent(search.value.trim())}` : '#/map';
  } }, s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, s('circle', { cx: 11, cy: 11, r: 7 }), s('path', { d: 'M20 20l-3.5-3.5' })), search);

  // the take-offs of the map: those of the register the outings are tied to, else the outings' own take-offs
  const spotKey = (o) => o.takeoff_site_id || `${(o.takeoff_lat || 0).toFixed(3)},${(o.takeoff_lon || 0).toFixed(3)}`;
  const spots = new Map();
  for (const o of mapRows) if (o.takeoff_lat != null && !spots.has(spotKey(o))) spots.set(spotKey(o), o);

  const climbOf = new Map(mapRows.map((o) => [o.id, o.climb && o.climb.line]));
  const named = [...sites.map((x) => [x.lat, x.lon, x.name]), ...mapRows.map((o) => [o.takeoff_lat, o.takeoff_lon, o.takeoff_name])]
    .filter((x) => x[0] != null && x[2]);
  const names = (p) => {
    let best = null;
    let bestM = NAME_M;
    for (const x of named) {
      const m = metres(p, x);
      if (m < bestM) { bestM = m; best = x[2]; }
    }
    return best || (p[2] != null ? `${fmtInt(p[2])} m` : '?');
  };

  // the sectors, with their number of take-offs
  const sectors = new Map();
  for (const o of spots.values()) {
    const name = sectorOf(o.takeoff_lat, o.takeoff_lon);
    if (name) sectors.set(name, (sectors.get(name) || 0) + 1);
  }
  const chained = combos(flown).slice(0, COMBOS);
  // the sectors, under the search in the same box (Sarah, 30 October 2026)
  const sectorChips = sectors.size ? h('div', { class: 'hero-sectors' },
    h('span', { class: 'hint' }, t('home.sectors')),
    h('div', { class: 'chips' }, [...sectors.entries()].sort((a, b) => b[1] - a[1]).slice(0, SECTORS).map(([name, n]) =>
      h('a', { class: 'chip', href: `#/map?sector=${encodeURIComponent(name)}` }, name, h('span', { class: 'hint' }, `· ${t('home.sectorTakeoffs', { n })}`))))) : null;

  return h('div', { class: 'home' },
    h('div', { class: 'warm-hero' }, HERO(),
      h('div', { class: 'warm-text' },
        h('h1', null, t('home.title')),
        h('p', { class: 'claim' }, t('home.claim1'), h('br'), t('home.claim2')),
        form,
        sectorChips)),

    h('a', { class: 'map-card', href: '#/map' },
      h('span', { class: 'mc-text' },
        h('span', { class: 'tag' }, t('home.mapTag')),
        h('b', { class: 'mc-title' }, t('home.mapTitle')),
        h('span', { class: 'hint' }, t('home.mapText')),
        h('span', { class: 'hint' }, `${t('home.sectorTakeoffs', { n: spots.size })} · ${t('home.routes', { n: routes.length })}`),
        h('span', { class: 'mc-btn' }, t('home.openMap'))),
      MAP_PICTURE()),

    latest.length ? [
      h('div', { class: 'sec-head' }, h('h2', null, t('home.latest')), h('a', { href: '#/all' }, t('home.seeAll'))),
      h('div', { class: 'climb-cards' }, latest.slice(0, LATEST).map((o) => outingCard(o, climbOf.get(o.id)))),
    ] : null,

    chained.length ? h('section', { class: 'inspiration' },
      h('div', { class: 'sec-head' }, h('div', null, h('span', { class: 'tag' }, t('home.inspiration')), h('h2', null, t('home.combos')))),
      h('p', { class: 'hint' }, t('home.combosText')),
      h('div', { class: 'climb-cards' }, chained.map((c) => comboCard(c, names)))) : null);
}
