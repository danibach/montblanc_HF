// The home page (Sarah, 30 October 2026): the question, a search and the flying sectors, the map of the take-offs,
// the latest outings, and for inspiration the outings that chain several take-offs.
// H&F Tracks is a library of outings: nothing here ranks the pilots.
// The maps are the site's own (site/basemaps.js), with the real tracks: the climb on foot in green, the flights in
// orange; they are only pictures (no dragging, no zoom): a click opens the outing or the map page.

import { sectorOf } from './sectors.js';
import { simpleBackground } from './basemaps.js';
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
// colours of a trace by mode (0 on foot, 1 flight, 2 vehicle: as on an outing's page); a ride is not drawn
const MODE_COLOUR = ['#1f7a4d', '#ff5a1f'];
const MAX_POINTS = 600; // a card's track is drawn from at most this many points
const FRAME_M = 120000; // the map of the take-offs shows those within this distance of their middle
const HEAT = { radius: 18, blur: 16, maxZoom: 9, max: 4, minOpacity: 0.4, gradient: { 0.4: '#f2c79a', 0.7: '#ff8a4c', 1: '#ff5a1f' } };
// a map that is only a picture
const STILL = { zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false,
  keyboard: false, touchZoom: false, tap: false, zoomSnap: 0.25 }; // a quarter zoom step: the track fills its card

// a soft colour per flying sector, the same for a sector everywhere (from its name)
const SECTOR_COLOURS = ['#7fb3d5', '#9cc58f', '#e2b38f', '#c7a4c9', '#e8c36a', '#8fc7c0', '#d99a9a', '#a9b8d9'];
function sectorDot(name) {
  let n = 0;
  for (const c of name) n = (n * 31 + c.codePointAt(0)) >>> 0;
  const dot = h('span', { class: 'sector-dot', 'aria-hidden': 'true' });
  dot.style.background = SECTOR_COLOURS[n % SECTOR_COLOURS.length]; // a property, not an attribute: the page's CSP
  return dot;
}

function metres(a, b) {
  const r = Math.PI / 180;
  const x = Math.sin(((b[0] - a[0]) * r) / 2) ** 2
    + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(((b[1] - a[1]) * r) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(x));
}

/** The parts of a trace in one mode each: [{mode, line}], from at most MAX_POINTS points. */
function tracePieces(trace) {
  const n = trace.lat.length;
  const step = Math.max(1, Math.ceil(n / MAX_POINTS));
  const out = [];
  for (let i = 0; i < n; i += step) {
    const mode = trace.m ? trace.m[i] : 0;
    const p = [trace.lat[i], trace.lon[i]];
    const last = out[out.length - 1];
    if (last && last.mode === mode) last.line.push(p);
    else {
      if (last) last.line.push(p); // the parts touch
      out.push({ mode, line: [p] });
    }
  }
  return out.filter((x) => x.line.length > 1 && MODE_COLOUR[x.mode]);
}

const nums = (o) => h('span', { class: 'cc-nums' },
  h('span', { class: 'up' }, `+${fmtInt(o.dplus_m)} m`), ' · ', h('span', { class: 'down' }, `−${fmtInt(o.dminus_m)} m`));

const who = (o) => h('span', { class: 'cc-who' }, pilotName(o.profiles), ' · ', fmtDate(o.outing_date));

function outingCard(o) {
  return h('a', { class: 'climb-card', href: `#/outing/${o.id}` },
    h('div', { class: 'cc-map', 'data-outing': o.id, role: 'img', 'aria-label': t('home.trackAria', { title: outingTitle(o) }) }),
    h('span', { class: 'cc-body' }, who(o), h('b', { class: 'cc-title' }, outingTitle(o)), nums(o)));
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
  const chain = [];
  takeoffs.forEach((p, i) => { if (i) chain.push(h('i', null, '→')); chain.push(h('span', null, names(p))); });
  return h('a', { class: 'climb-card', href: `#/outing/${o.id}` },
    h('div', { class: 'cc-map', 'data-outing': o.id, role: 'img', 'aria-label': t('home.trackAria', { title: outingTitle(o) }) }),
    h('span', { class: 'cc-body' }, who(o),
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

/**
 * The home page. ``latest``: the newest outings (listOutings); ``mapRows``: the outings of the map (getMapOutings);
 * ``sites``, ``routes``: the take-offs and the itineraries of the map; ``flown``: the newest outings with their flights;
 * ``ffvl``: the FFVL's official sites (getFfvlSites), to name the take-offs of a chain; ``loadTraces(ids)``: the
 * tracks to draw (getTraces). Returns {element, start}: start() draws the maps once the element is in the page.
 */
export function buildHome({ latest, mapRows, sites, routes, flown, ffvl = [], loadTraces = null }) {
  const search = h('input', { type: 'search', name: 'q', placeholder: t('home.search'), 'aria-label': t('home.search'), autocomplete: 'off' });
  const form = h('form', { class: 'warm-search', role: 'search', onsubmit: (ev) => {
    ev.preventDefault();
    location.hash = search.value.trim() ? `#/map?q=${encodeURIComponent(search.value.trim())}` : '#/map';
  } }, s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, s('circle', { cx: 11, cy: 11, r: 7 }), s('path', { d: 'M20 20l-3.5-3.5' })), search);

  // the take-offs of the map: those of the register the outings are tied to, else the outings' own take-offs
  const spotKey = (o) => o.takeoff_site_id || `${(o.takeoff_lat || 0).toFixed(3)},${(o.takeoff_lon || 0).toFixed(3)}`;
  const spots = new Map();
  for (const o of mapRows) {
    if (o.takeoff_lat == null) continue;
    const sp = spots.get(spotKey(o)) || { lat: o.takeoff_lat, lon: o.takeoff_lon, pilots: new Set() };
    sp.pilots.add(o.user_id || o.pilot || o.id);
    spots.set(spotKey(o), sp);
  }

  // the names of take-offs: the register's, the outings', then the FFVL's official ones (Prarion, Tête du Mottey…)
  const named = [...sites.map((x) => [x.lat, x.lon, x.name]), ...mapRows.map((o) => [o.takeoff_lat, o.takeoff_lon, o.takeoff_name]),
    ...ffvl.filter((f) => String(f.kind || '').includes('T')).map((f) => [f.lat, f.lon, f.name])]
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
  for (const sp of spots.values()) {
    const name = sectorOf(sp.lat, sp.lon);
    if (name) sectors.set(name, (sectors.get(name) || 0) + 1);
  }
  const chained = combos(flown).slice(0, COMBOS);
  const shownLatest = latest.slice(0, LATEST);
  // the sectors, under the search in the same box (Sarah, 30 October 2026)
  const sectorChips = sectors.size ? h('div', { class: 'hero-sectors' },
    h('span', { class: 'hint' }, t('home.sectors')),
    h('div', { class: 'chips' }, [...sectors.entries()].sort((a, b) => b[1] - a[1]).slice(0, SECTORS).map(([name, n]) =>
      h('a', { class: 'chip', href: `#/map?sector=${encodeURIComponent(name)}` }, sectorDot(name), name, ' ', h('span', { class: 'hint' }, `· ${t('home.sectorTakeoffs', { n })}`))))) : null;

  const overview = h('div', { class: 'mc-map', role: 'img', 'aria-label': t('home.mapAria') });
  const element = h('div', { class: 'home' },
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
      overview),

    shownLatest.length ? [
      h('div', { class: 'sec-head' }, h('h2', null, t('home.latest')), h('a', { href: '#/all' }, t('home.seeAll'))),
      h('div', { class: 'climb-cards' }, shownLatest.map(outingCard)),
    ] : null,

    chained.length ? h('section', { class: 'inspiration' },
      h('div', { class: 'sec-head' }, h('div', null, h('span', { class: 'tag' }, t('home.inspiration')), h('h2', null, t('home.combos')))),
      h('p', { class: 'hint' }, t('home.combosText')),
      h('div', { class: 'climb-cards' }, chained.map((c) => comboCard(c, names)))) : null);

  const start = () => {
    const L = window.L;
    if (!L) return;
    // the take-offs: their heat (each weighs its number of pilots) and a dot each
    if (spots.size) {
      const map = L.map(overview, STILL);
      simpleBackground(L, map);
      const points = [...spots.values()];
      if (L.heatLayer) L.heatLayer(points.map((sp) => [sp.lat, sp.lon, sp.pilots.size]), HEAT).addTo(map);
      for (const sp of points) L.circleMarker([sp.lat, sp.lon], { radius: 3, color: '#fff', weight: 1, fillColor: '#ff5a1f', fillOpacity: 1, interactive: false }).addTo(map);
      // framed on where most take-offs are: a lone one in Spain would show half of Europe
      const median = (xs) => xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)];
      const middle = [median(points.map((sp) => sp.lat)), median(points.map((sp) => sp.lon))];
      const near = points.filter((sp) => metres(middle, [sp.lat, sp.lon]) < FRAME_M);
      map.fitBounds(L.latLngBounds((near.length ? near : points).map((sp) => [sp.lat, sp.lon])), { padding: [24, 24], maxZoom: 11 });
    }
    // each card: its track, read once for all the cards
    const boxes = [...element.querySelectorAll('.cc-map')];
    if (!boxes.length || !loadTraces) return;
    const ids = [...new Set(boxes.map((b) => b.dataset.outing))];
    loadTraces(ids).then((rows) => {
      const traces = new Map(rows.map((r) => [r.id, r.trace]));
      for (const box of boxes) {
        const trace = traces.get(box.dataset.outing);
        if (!trace || !trace.lat || !box.isConnected) continue;
        const pieces = tracePieces(trace);
        if (!pieces.length) continue;
        const map = L.map(box, { ...STILL, attributionControl: false });
        simpleBackground(L, map);
        // the climb in full green on a white casing; the flight softer: a plain light orange line (Sarah, 30 October 2026)
        for (const p of pieces) {
          const flight = p.mode === 1;
          if (!flight) L.polyline(p.line, { color: '#fff', weight: 5, opacity: 0.85, interactive: false }).addTo(map);
          L.polyline(p.line, { color: MODE_COLOUR[p.mode], weight: flight ? 2 : 2.5, opacity: flight ? 0.6 : 1, interactive: false }).addTo(map);
        }
        map.fitBounds(L.latLngBounds(pieces.flatMap((p) => p.line)), { padding: [14, 14] });
      }
    }).catch(() => { /* the cards stay without their map */ });
  };
  return { element, start };
}
