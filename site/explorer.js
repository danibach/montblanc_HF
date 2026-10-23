// The take-off map: a heat map (take-offs when zoomed out, the ways up on foot when zoomed in), one marker per
// take-off (grouped when zoomed out), and, for the take-off that is clicked, the climbs on foot that reached it
// and the list of its outings. Flights are never drawn. Filters by season and year apply to everything.

import { CONFIG } from './config.js';
import { h, fmtInt, fmtKm, fmtDur, fmtDate, outingTitle } from './util.js';

// Take-offs closer than this are the same spot. Only for this page: nothing is stored.
const SAME_SPOT_M = 150;
// Markers whose centres are closer than this on screen are shown as one group, with the sum of their outings.
const GROUP_PX = 56;
// At most this many tracks are read for one take-off whose outings have no stored climb yet.
const MAX_TRACES = 60;
// From this zoom on, the heat map shows the ways up instead of the take-offs.
const ROUTES_ZOOM = 11;
// Past this many climbs at one take-off, they are not drawn one by one: the heat map shows them.
const MANY_CLIMBS = 30;
// Outings listed at a time in each start-place group ("Show more" for the next ones).
const PAGE = 20;
// Points are laid along each climb this far apart for the heat map of the ways up.
const ROUTE_STEP_M = 40;

// Heat of the take-offs: each spot weighs its number of pilots. Below maxZoom the weight is halved at each zoom
// level out, while nearby spots add up; minOpacity keeps a lone take-off visible on the world view.
const GRADIENT = { 0.4: '#4aa3c8', 0.65: '#5fbf68', 0.85: '#f0c870', 1: '#f0693d' };
const HEAT_SPOTS = { radius: 18, blur: 15, maxZoom: 8, max: 5, minOpacity: 0.35, gradient: GRADIENT };
// Heat of the ways up: each pilot counts once per take-off, spread along their climbs; 3 pilots on the same
// path make it hot.
const HEAT_ROUTES = { radius: 7, blur: 9, maxZoom: 14, max: 3, minOpacity: 0.25, gradient: GRADIENT };
const CLIMB = { color: '#5fbf68', weight: 3, opacity: 0.55 };
const CLIMB_HOT = { color: '#f0693d', weight: 5, opacity: 1 };
const CLIMB_BACK = { color: '#5fbf68', weight: 2, opacity: 0.18 };
const SEASONS = {
  summer: { label: 'Summer (May–Oct)', months: [5, 6, 7, 8, 9, 10] },
  winter: { label: 'Winter (Nov–Apr)', months: [11, 12, 1, 2, 3, 4] },
};

const plural = (n, word) => `${fmtInt(n)} ${word}${n === 1 ? '' : 's'}`;

// D+ of the climb when it is known, else the engine's D+ on foot
const climbDplus = (o, climb) => (climb && climb.dplus_m != null ? climb.dplus_m : o.dplus_m);
// orders of the list of a take-off's outings; ``climbs`` maps an outing id to its climb
const SORTS = {
  recent: { label: 'Most recent', by: (a, b) => String(b.outing_date || '').localeCompare(String(a.outing_date || '')) },
  climb: { label: 'Most D+', by: (a, b, climbs) => (climbDplus(b, climbs.get(b.id)) || 0) - (climbDplus(a, climbs.get(a.id)) || 0) },
  fast: {
    label: 'Fastest climb',
    by: (a, b, climbs) => {
      // outings without a known climb time go last
      const [ta, tb] = [a, b].map((o) => (climbs.get(o.id) || {}).duration_s ?? Infinity);
      return ta === tb ? 0 : ta < tb ? -1 : 1;
    },
  },
};

function metres(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * r) / 2) ** 2
    + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(a));
}

const pilotOf = (o) => o.user_id || o.pilot || o.id;

/**
 * The spots of the map: [{lat, lon, alt, name, outings, pilots, site}]. An outing tied to a take-off of the register
 * (FFVL, OpenStreetMap or provisional: ``sites`` from map_takeoff_sites()) is shown at that take-off, under its name;
 * the others (not tied yet) are grouped when their take-offs are within SAME_SPOT_M of each other.
 */
export function groupTakeoffs(rows, sites = []) {
  const byId = new Map(sites.map((s) => [s.id, s]));
  const registered = new Map();
  const loose = [];
  for (const o of rows) {
    const site = byId.get(o.takeoff_site_id);
    if (!site) { loose.push(o); continue; }
    if (!registered.has(site.id)) registered.set(site.id, { lat: site.lat, lon: site.lon, alt: site.alt, name: site.name, site, outings: [] });
    registered.get(site.id).outings.push(o);
  }
  for (const sp of registered.values()) sp.pilots = new Set(sp.outings.map(pilotOf)).size;

  const spots = [];
  const grid = new Map(); // cells of about 1 km, so each outing is compared with nearby spots only
  const cell = (lat, lon) => `${Math.floor(lat * 100)}:${Math.floor(lon * 100)}`;
  for (const o of loose) {
    const [ci, cj] = cell(o.takeoff_lat, o.takeoff_lon).split(':').map(Number);
    let best = null;
    let bestD = SAME_SPOT_M;
    for (let di = -1; di <= 1; di++) {
      for (let dj = -1; dj <= 1; dj++) {
        for (const sp of grid.get(`${ci + di}:${cj + dj}`) || []) {
          const d = metres(sp.lat, sp.lon, o.takeoff_lat, o.takeoff_lon);
          if (d < bestD) { best = sp; bestD = d; }
        }
      }
    }
    if (!best) {
      best = { lat: o.takeoff_lat, lon: o.takeoff_lon, outings: [] };
      const key = cell(best.lat, best.lon);
      grid.set(key, [...(grid.get(key) || []), best]);
      spots.push(best);
    }
    best.outings.push(o);
  }
  for (const sp of spots) {
    const n = sp.outings.length;
    sp.lat = sp.outings.reduce((a, o) => a + o.takeoff_lat, 0) / n;
    sp.lon = sp.outings.reduce((a, o) => a + o.takeoff_lon, 0) / n;
    sp.pilots = new Set(sp.outings.map(pilotOf)).size;
    const alts = sp.outings.map((o) => o.takeoff_alt).filter((a) => a != null);
    sp.alt = alts.length ? alts.reduce((a, b) => a + b, 0) / alts.length : null;
    const names = new Map();
    for (const o of sp.outings) if (o.takeoff_name) names.set(o.takeoff_name, (names.get(o.takeoff_name) || 0) + 1);
    sp.name = [...names.entries()].sort((a, b) => b[1] - a[1]).map((e) => e[0])[0]
      || `Take-off${sp.alt != null ? ` · ${fmtInt(sp.alt)} m` : ''}`;
  }
  return [...registered.values(), ...spots];
}

const SOURCES = {
  ffvl: 'Official FFVL take-off',
  osm: 'Take-off from OpenStreetMap',
  provisional: 'Take-off found from the outings',
};

/** Where the take-off comes from, its good winds, the FFVL's hike & fly notes, and the ties left to confirm. */
function siteFacts(sp) {
  const site = sp.site;
  if (!site) return null;
  const toConfirm = sp.outings.filter((o) => o.takeoff_site_status === 'to_confirm').length;
  return h('div', { class: 'site-facts' },
    h('span', { class: `badge ${site.source}` }, SOURCES[site.source] || 'Take-off'),
    // the FFVL writes French directions (O for ouest): shown in English like the site
    site.wind_ok ? h('span', { class: 'hint' }, ` · good winds ${site.wind_ok.split(/[;,\s]+/).filter(Boolean).map((w) => w.toUpperCase().replace(/O/g, 'W')).join(', ')}`) : null,
    toConfirm ? h('p', { class: 'hint' }, `${plural(toConfirm, 'outing')} took off 100 to 200 m away: tied to this take-off, to be confirmed.`) : null,
    site.hike_and_fly ? h('details', null, h('summary', null, 'Hike & fly notes (FFVL)'), h('p', { class: 'hint' }, site.hike_and_fly)) : null);
}

/**
 * The climb on foot to the take-off, from a full trace, for outings whose climb is not stored yet (the server
 * job stores it: src/mbhf/climb.py, same rule). Returns {line, km, duration_s} or null.
 */
export function climbOf(o) {
  const tr = o.trace;
  if (!tr || !tr.m || !tr.m.length) return null;
  const main = (o.flights || []).reduce((b, f) => (!b || (f.drop_m || 0) > (b.drop_m || 0) ? f : b), null);
  let end = -1;
  if (main && main.takeoff && main.takeoff.t) {
    const at = (Date.parse(main.takeoff.t) - Date.parse(tr.t0)) / 1000;
    end = tr.t.findIndex((x) => x >= at);
  }
  if (end < 0) end = tr.m.indexOf(1);
  if (end <= 0) return null;
  let last = end - 1;
  while (last >= 0 && tr.m[last] !== 0) last -= 1;
  let first = last;
  while (first > 0 && tr.m[first - 1] === 0) first -= 1;
  if (last < 1 || last - first < 1) return null;
  const line = [];
  let m = 0;
  for (let i = first; i <= last; i++) {
    line.push([tr.lat[i], tr.lon[i]]);
    if (i > first) m += metres(tr.lat[i - 1], tr.lon[i - 1], tr.lat[i], tr.lon[i]);
  }
  line.push([tr.lat[end], tr.lon[end]]); // up to the take-off itself
  m += metres(tr.lat[last], tr.lon[last], tr.lat[end], tr.lon[end]);
  return { line, km: m / 1000, duration_s: tr.t[end] - tr.t[first] };
}

const storedClimb = (o) => (o.climb && o.climb.line && o.climb.line.length > 1 ? o.climb : null);

/** Heat points of the ways up: points every ROUTE_STEP_M along each stored climb; a pilot weighs 1 per spot. */
function routePoints(spots) {
  const pts = [];
  for (const sp of spots) {
    const climbsOf = new Map();
    for (const o of sp.outings) {
      const c = storedClimb(o);
      if (c) climbsOf.set(pilotOf(o), [...(climbsOf.get(pilotOf(o)) || []), c.line]);
    }
    for (const lines of climbsOf.values()) {
      const w = 1 / lines.length;
      for (const line of lines) {
        for (let i = 1; i < line.length; i++) {
          const [a, b] = [line[i - 1], line[i]];
          const steps = Math.max(1, Math.round(metres(a[0], a[1], b[0], b[1]) / ROUTE_STEP_M));
          for (let k = 0; k < steps; k++) {
            const f = k / steps;
            pts.push([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, w]);
          }
        }
      }
    }
  }
  return pts;
}

// Leaflet.heat 0.2 draws on the next frame and expects to be on a visible map by then, but it can lose track of
// that frame: a layer taken off the map (zoom switch) or a hidden map (no size) made it throw. It now skips the
// drawing in those cases; a layer that is not shown only keeps its points.
if (window.L && window.L.HeatLayer && !window.L.HeatLayer.prototype._safe) {
  const draw = window.L.HeatLayer.prototype._redraw;
  window.L.HeatLayer.prototype._redraw = function redraw() {
    if (this._map && this._map.getContainer().clientWidth && this._map.getContainer().clientHeight) draw.call(this);
    else this._frame = null;
  };
  window.L.HeatLayer.prototype._safe = true;
}

function setPoints(layer, pts) {
  if (layer._map) layer.setLatLngs(pts);
  else layer._latlngs = pts;
}

// Filters on the climb itself (brief, section 7): bands of D+, distance and time. The stored climb's own numbers
// when there is one, otherwise the engine's D+ and distance on foot; an outing with no known climb time is left out
// by the time filter.
const CLIMB_FILTERS = {
  dplus: {
    label: 'Climb D+',
    bands: [['', 'Any D+'], ['0-500', 'Under 500 m'], ['500-1000', '500–1,000 m'], ['1000-1500', '1,000–1,500 m'], ['1500-', 'Over 1,500 m']],
    value: (o) => climbDplus(o, storedClimb(o)),
  },
  km: {
    label: 'Climb distance',
    bands: [['', 'Any distance'], ['0-5', 'Under 5 km'], ['5-10', '5–10 km'], ['10-', 'Over 10 km']],
    value: (o) => (storedClimb(o) ? storedClimb(o).km : o.walk_km),
  },
  time: {
    label: 'Climb time',
    bands: [['', 'Any time'], ['0-5400', 'Under 1 h 30'], ['5400-10800', '1 h 30–3 h'], ['10800-', 'Over 3 h']],
    value: (o) => (storedClimb(o) ? storedClimb(o).duration_s : null),
  },
};

function inBand(value, band) {
  if (!band) return true;
  if (value == null) return false;
  const [lo, hi] = band.split('-');
  return value >= Number(lo) && (hi === '' || value < Number(hi));
}

// for search: no accents, no case ("Frêtes" is found by "fretes"); and without spaces or hyphens, so that
// "plan praz" finds Planpraz
const fold = (text) => String(text || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const squash = (text) => fold(text).replace(/[\s'’-]+/g, '');
const hasText = (text, query) => fold(text).includes(fold(query)) || squash(text).includes(squash(query));

function season(o) {
  const month = Number(String(o.outing_date || '').slice(5, 7));
  return Object.keys(SEASONS).find((k) => SEASONS[k].months.includes(month)) || '';
}

/**
 * The page's filters, map and side panel. ``rows`` are the outings of getMapOutings(); ``loadTraces(ids)`` reads
 * full tracks; ``sites`` are the take-offs of the register (getMapSites()). Returns {element, start}: start() is
 * called once the element is in the page.
 */
export function buildExplorer(rows, loadTraces, sites = []) {
  const mapBox = h('div', { class: 'map map-wide', role: 'region', 'aria-label': 'Map of the take-offs' });
  const side = h('aside', { class: 'side', 'aria-live': 'polite' });
  const years = [...new Set(rows.map((o) => String(o.outing_date || '').slice(0, 4)).filter(Boolean))].sort().reverse();
  const seasonPick = h('select', { id: 'm-season' }, h('option', { value: '' }, 'All seasons'),
    Object.entries(SEASONS).map(([k, s]) => h('option', { value: k }, s.label)));
  const yearPick = h('select', { id: 'm-year' }, h('option', { value: '' }, 'All years'), years.map((y) => h('option', { value: y }, y)));
  // The map opens on the current season: summer and winter climbs do not take the same ways. All seasons when the
  // current one has no outing yet.
  const now = season({ outing_date: new Date().toISOString() });
  if (rows.some((o) => season(o) === now)) seasonPick.value = now;
  const climbPicks = Object.fromEntries(Object.entries(CLIMB_FILTERS).map(([k, f]) => [k,
    h('select', { id: `m-${k}`, 'aria-label': f.label }, f.bands.map(([v, text]) => h('option', { value: v }, text)))]));
  const climbBox = h('details', { class: 'climb-filters' },
    h('summary', null, 'Climb filters'),
    h('div', { class: 'filters' }, Object.entries(CLIMB_FILTERS).map(([k, f]) =>
      h('div', { class: 'field' }, h('label', { for: `m-${k}` }, f.label), climbPicks[k]))));
  // search a take-off, or a start place (a village, a car park): the results open under the field
  const searchBox = h('input', { type: 'search', id: 'm-search', placeholder: 'Take-off, summit, village…', autocomplete: 'off',
    'aria-controls': 'm-results', 'aria-expanded': 'false' });
  const results = h('ul', { class: 'search-results', id: 'm-results', role: 'listbox', hidden: true });
  const bar = h('div', { class: 'filters' },
    h('div', { class: 'field search' }, h('label', { for: 'm-search' }, 'Search'), searchBox, results),
    h('div', { class: 'field' }, h('label', { for: 'm-season' }, 'Season'), seasonPick),
    h('div', { class: 'field' }, h('label', { for: 'm-year' }, 'Year'), yearPick));
  const element = h('div', null, bar, climbBox, h('div', { class: 'explorer' }, mapBox, side));
  const L = window.L;
  if (!L || !L.heatLayer) {
    mapBox.append(h('p', { class: 'hint pad' }, 'The map could not be loaded.'));
    return { element, start() {} };
  }
  let shown = rows;
  let spots = [];
  let map;
  let markers;
  let climbs;
  let heat; // holds the heat layer that suits the zoom
  let heatSpots;
  let heatRoutes;
  let legendText;
  let current = null; // the spot shown in the panel
  let request = 0; // a slow answer for a spot we already left must not draw over the new one

  function overview() {
    current = null;
    request += 1;
    if (climbs) climbs.clearLayers();
    element.querySelector('.explorer').classList.remove('has-spot');
    side.replaceChildren(
      h('h2', null, 'Take-offs'),
      h('p', { class: 'hint' }, `${plural(spots.length, 'take-off spot')}, ${plural(shown.length, 'confirmed outing')}.`),
      h('p', { class: 'hint' }, 'Click a take-off to see the climbs that reached it and its outings. Numbers on the map are outings; zoom in to split a group.'),
      h('p', { class: 'hint' }, `Zoomed out, the heat map shows the take-offs; from zoom ${ROUTES_ZOOM} on, the ways up on foot. Warmer means more pilots: someone who goes up the same way many times counts once.`));
    if (markers) draw();
  }

  function icon(n, cls) {
    const size = n >= 100 ? 40 : n >= 10 ? 34 : 28;
    return L.divIcon({ className: `tk ${cls}`, html: `<span>${n}</span>`, iconSize: [size, size] });
  }

  // markers again after each move: spots close on screen become one group
  function draw() {
    markers.clearLayers();
    const zoom = map.getZoom();
    const cells = new Map();
    for (const sp of spots) {
      const p = map.project([sp.lat, sp.lon], zoom);
      const key = `${Math.floor(p.x / GROUP_PX)}:${Math.floor(p.y / GROUP_PX)}`;
      cells.set(key, [...(cells.get(key) || []), sp]);
    }
    for (const group of cells.values()) {
      const n = group.reduce((a, sp) => a + sp.outings.length, 0);
      if (group.length === 1) {
        const sp = group[0];
        const mk = L.marker([sp.lat, sp.lon], { icon: icon(n, sp === current ? 'spot on' : 'spot'), title: sp.name, riseOnHover: true });
        // a node, not a string: Leaflet would read a string as HTML, and names come from OpenStreetMap
        mk.bindTooltip(h('span', null, `${sp.name} · ${plural(n, 'outing')} · ${plural(sp.pilots, 'pilot')}`), { direction: 'top', offset: [0, -14] });
        mk.on('click', () => openSpot(sp));
        markers.addLayer(mk);
      } else {
        const lat = group.reduce((a, sp) => a + sp.lat, 0) / group.length;
        const lon = group.reduce((a, sp) => a + sp.lon, 0) / group.length;
        const mk = L.marker([lat, lon], { icon: icon(n, 'group'), title: `${group.length} take-offs` });
        mk.bindTooltip(h('span', null, `${group.length} take-offs · ${plural(n, 'outing')} — click to zoom in`), { direction: 'top', offset: [0, -16] });
        mk.on('click', () => map.fitBounds(L.latLngBounds(group.map((sp) => [sp.lat, sp.lon])), { padding: [60, 60], maxZoom: 15 }));
        markers.addLayer(mk);
      }
    }
  }

  // the heat map of the take-offs zoomed out, of the ways up zoomed in
  function pickHeat() {
    // a hidden map has no size: Leaflet.heat cannot draw it (called again on resize)
    if (!mapBox.clientWidth || !mapBox.clientHeight) return;
    const routes = map.getZoom() >= ROUTES_ZOOM;
    const want = routes ? heatRoutes : heatSpots;
    if (!heat.hasLayer(want)) {
      heat.clearLayers();
      heat.addLayer(want);
    }
    legendText.textContent = routes ? 'Ways up on foot · pilots' : 'Take-offs · pilots';
  }

  function applyFilters() {
    const s = seasonPick.value;
    const y = yearPick.value;
    shown = rows.filter((o) => (!s || season(o) === s) && (!y || String(o.outing_date || '').startsWith(y))
      && Object.entries(CLIMB_FILTERS).every(([k, f]) => inBand(f.value(o), climbPicks[k].value)));
    spots = groupTakeoffs(shown, sites);
    setPoints(heatSpots, spots.map((sp) => [sp.lat, sp.lon, sp.pilots]));
    setPoints(heatRoutes, routePoints(spots));
    const active = Object.values(climbPicks).filter((p) => p.value).length;
    climbBox.querySelector('summary').textContent = active ? `Climb filters (${active})` : 'Climb filters';
    if (searchBox.value) showResults(); // the results follow the filters
    overview();
  }

  // ---- search: the take-offs whose name matches, and the start places (villages, car parks) that match, among
  // the outings the filters keep
  function matches(query) {
    const q = fold(query.trim());
    if (q.length < 2) return [];
    const rank = (text) => (fold(text).startsWith(q) ? 0 : fold(text).split(/[\s'’-]+/).some((w) => w.startsWith(q)) ? 1 : 2);
    const found = [];
    for (const sp of spots) {
      const hit = [sp.name, ...sp.outings.map((o) => o.title)].find((t) => hasText(t, q));
      if (hit) found.push({ kind: 'spot', text: sp.name, spot: sp, rank: rank(hit), n: sp.outings.length });
    }
    const places = new Map();
    for (const sp of spots) {
      for (const o of sp.outings) {
        if (o.start_place && hasText(o.start_place, q)) {
          const p = places.get(o.start_place) || { kind: 'place', text: o.start_place, spots: new Set(), n: 0, rank: rank(o.start_place) };
          p.spots.add(sp);
          p.n += 1;
          places.set(o.start_place, p);
        }
      }
    }
    return [...found, ...places.values()].sort((a, b) => a.rank - b.rank || b.n - a.n).slice(0, 8);
  }

  function choose(m) {
    hideResults();
    if (m.kind === 'spot') {
      map.setView([m.spot.lat, m.spot.lon], Math.max(map.getZoom(), 13));
      openSpot(m.spot);
    } else {
      overview();
      map.fitBounds(L.latLngBounds([...m.spots].map((sp) => [sp.lat, sp.lon])), { padding: [60, 60], maxZoom: 13 });
    }
  }

  function showResults() {
    const found = matches(searchBox.value);
    results.replaceChildren(...(found.length ? found.map((m) => {
      const li = h('li', { role: 'option', tabindex: '-1' },
        h('b', null, m.text),
        h('span', { class: 'hint' }, m.kind === 'spot'
          // the altitude tells apart two take-offs of the same name
          ? ` · take-off${m.spot.alt != null ? ` at ${fmtInt(m.spot.alt)} m` : ''} · ${plural(m.n, 'outing')}`
          : ` · start · ${plural(m.spots.size, 'take-off')}, ${plural(m.n, 'outing')}`));
      li.addEventListener('mousedown', (ev) => { ev.preventDefault(); choose(m); }); // before the field loses focus
      li.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') choose(m); });
      return li;
    }) : [h('li', { class: 'hint' }, searchBox.value.trim().length < 2 ? 'Type at least 2 letters' : 'Nothing found with these filters')]));
    results.hidden = false;
    searchBox.setAttribute('aria-expanded', 'true');
  }

  function hideResults() {
    results.hidden = true;
    searchBox.setAttribute('aria-expanded', 'false');
  }

  async function openSpot(sp) {
    current = sp;
    const mine = ++request;
    climbs.clearLayers();
    element.querySelector('.explorer').classList.add('has-spot');
    draw();
    const list = h('div', { class: 'start-groups' });
    const status = h('p', { class: 'hint' });
    side.replaceChildren(
      h('div', { class: 'side-head' },
        h('div', null,
          h('h2', null, sp.name),
          h('p', { class: 'hint' }, `${plural(sp.outings.length, 'confirmed outing')} · ${plural(sp.pilots, 'pilot')}${sp.alt != null ? ` · take-off at ${fmtInt(sp.alt)} m` : ''}`)),
        h('button', { class: 'link close', 'aria-label': 'Back to all take-offs', onclick: overview }, '×')),
      siteFacts(sp), status, list);
    side.scrollTop = 0;
    map.setView([sp.lat, sp.lon], Math.max(map.getZoom(), 13));

    // the climbs: stored by the server job; read from the full tracks only for outings that have none yet
    const climbOfId = new Map();
    for (const o of sp.outings) if (storedClimb(o)) climbOfId.set(o.id, storedClimb(o));
    const missing = sp.outings.filter((o) => !o.climb).slice(0, MAX_TRACES);
    if (missing.length) {
      status.textContent = 'Loading the climbs…';
      try {
        for (const t of await loadTraces(missing.map((o) => o.id))) {
          const c = climbOf({ ...missing.find((o) => o.id === t.id), ...t });
          if (c) climbOfId.set(t.id, c);
        }
      } catch (e) {
        if (mine !== request) return;
        status.textContent = `Some tracks could not be loaded (${e.message}).`;
      }
      if (mine !== request) return;
    }
    // Many climbs: the heat map of the ways up (shown from ROUTES_ZOOM on) replaces a tangle of lines, and an
    // outing's line appears only while it is hovered or kept lit.
    const crowded = climbOfId.size > MANY_CLIMBS;
    const lines = new Map();
    const bounds = L.latLngBounds([[sp.lat, sp.lon]]);
    let selected = null;
    const restyle = (hot) => {
      for (const [id, line] of lines) {
        const lit = id === hot || id === selected;
        if (crowded) {
          // through the group: a line only taken off the map would stay in it and never come back
          if (lit) climbs.addLayer(line.setStyle(CLIMB_HOT));
          else climbs.removeLayer(line);
          if (lit) line.bringToFront();
        } else {
          line.setStyle(lit ? CLIMB_HOT : selected ? CLIMB_BACK : CLIMB);
          if (lit) line.bringToFront();
        }
      }
      for (const li of list.querySelectorAll('li[data-id]')) li.classList.toggle('on', li.dataset.id === selected);
    };
    const select = (id) => { selected = selected === id ? null : id; restyle(null); };

    for (const o of sp.outings) {
      const climb = climbOfId.get(o.id);
      if (!climb) continue;
      const line = L.polyline(climb.line, CLIMB);
      if (!crowded) line.addTo(climbs);
      line.on('mouseover', () => restyle(o.id));
      line.on('mouseout', () => restyle(null));
      line.on('click', () => {
        select(o.id);
        const li = list.querySelector(`[data-id="${o.id}"]`);
        if (li) li.scrollIntoView({ block: 'nearest' });
      });
      lines.set(o.id, line);
      bounds.extend(line.getBounds());
    }

    function item(o) {
      const climb = climbOfId.get(o.id);
      const li = h('li', { 'data-id': o.id, tabindex: '0', class: o.id === selected ? 'on' : null },
        h('b', null, outingTitle(o)),
        h('span', { class: 'hint' }, `${o.pilot || 'Anonymous'} · ${fmtDate(o.outing_date)}`),
        h('span', { class: 'nums' },
          h('span', { title: climb && climb.dplus_m != null ? 'D+ of the climb' : 'D+ on foot' }, `↗ ${fmtInt(climbDplus(o, climb))} m`),
          h('span', { title: 'Distance of the climb' }, climb ? fmtKm(climb.km) : fmtKm(o.walk_km)),
          h('span', { title: 'Time of the climb' }, climb ? `⏱ ${fmtDur(climb.duration_s)}` : '')),
        climb ? null : h('span', { class: 'hint' }, 'No climb track to draw.'),
        h('a', { href: `#/outing/${o.id}` }, 'Open the outing →'));
      li.addEventListener('mouseenter', () => restyle(o.id));
      li.addEventListener('mouseleave', () => restyle(null));
      li.addEventListener('focus', () => restyle(o.id));
      li.addEventListener('click', (ev) => { if (!ev.target.closest('a')) select(o.id); });
      li.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && ev.target === li) select(o.id); });
      return li;
    }

    // the list: one group per start place (largest first), sorted as chosen, PAGE outings at a time
    const groups = new Map();
    for (const o of sp.outings) {
      const place = o.start_place || 'an unnamed start';
      groups.set(place, [...(groups.get(place) || []), o]);
    }
    const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    const sortPick = h('select', { id: 'm-sort', 'aria-label': 'Sort the outings' },
      Object.entries(SORTS).map(([k, s]) => h('option', { value: k }, s.label)));
    const open = new Set(sp.outings.length <= PAGE ? ordered.map((g) => g[0]) : [ordered[0][0]]);
    const pages = new Map();
    function renderList() {
      const by = SORTS[sortPick.value].by;
      list.replaceChildren(...ordered.map(([place, outings]) => {
        const items = outings.slice().sort((a, b) => by(a, b, climbOfId));
        const n = pages.get(place) || PAGE;
        const body = h('ul', { class: 'out-list' }, items.slice(0, n).map(item));
        const left = items.length - n;
        const more = left > 0
          ? h('button', { class: 'more', onclick: () => { pages.set(place, n + PAGE); renderList(); } },
            left > PAGE ? `Show ${PAGE} more (${left} left)` : `Show the last ${plural(left, 'outing')}`)
          : null;
        const group = h('details', { class: 'start-group', open: open.has(place) },
          h('summary', null, `From ${place}`, h('span', { class: 'hint' }, ` · ${plural(outings.length, 'outing')}`)), body, more);
        group.addEventListener('toggle', () => { if (group.open) open.add(place); else open.delete(place); });
        return group;
      }));
    }
    sortPick.addEventListener('change', () => { pages.clear(); renderList(); });
    list.before(h('div', { class: 'row sort-row' }, h('label', { for: 'm-sort' }, 'Sort'), sortPick));
    renderList();
    status.textContent = crowded
      ? `${plural(climbOfId.size, 'climb')}: the heat map shows the ways up. Hover an outing to see its climb; click it to keep it.`
      : 'Hover an outing to light its climb; click it to keep it lit.';
    if (lines.size) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
    if (crowded && map.getZoom() < ROUTES_ZOOM) map.setZoom(ROUTES_ZOOM); // close enough for the heat of the ways up
  }

  const start = () => {
    map = L.map(mapBox, { worldCopyJump: true });
    L.tileLayer(CONFIG.TILES_URL, {
      subdomains: CONFIG.TILES_SUBDOMAINS,
      maxZoom: CONFIG.TILES_MAX_ZOOM,
      attribution: CONFIG.TILES_ATTRIBUTION,
    }).addTo(map);
    // the take-off register's sources, as their licences ask (Licence Ouverte 2.0, ODbL)
    if (sites.length) map.attributionControl.addAttribution('Take-offs: FFVL (Licence Ouverte), OpenStreetMap (ODbL)');
    heatSpots = L.heatLayer([], HEAT_SPOTS);
    heatRoutes = L.heatLayer([], HEAT_ROUTES);
    heat = L.layerGroup().addTo(map);
    climbs = L.featureGroup().addTo(map);
    markers = L.layerGroup().addTo(map);
    L.control.layers(null, { 'Heat map': heat, 'Take-offs': markers }, { collapsed: false }).addTo(map);

    // legend of the heat map, shown with it
    const legend = L.control({ position: 'bottomleft' });
    legendText = h('span');
    const legendBox = h('div', { class: 'heat-legend' }, legendText, h('i', { class: 'heat-bar' }), h('span', { class: 'heat-ends' }, h('span', null, 'few'), h('span', null, 'many')));
    legend.onAdd = () => legendBox;
    legend.addTo(map);
    map.on('overlayadd overlayremove', (e) => { if (e.layer === heat) legendBox.hidden = e.type === 'overlayremove'; });

    map.on('zoomend', () => { pickHeat(); draw(); });
    map.on('resize', pickHeat);
    applyFilters();
    if (spots.length) map.fitBounds(L.latLngBounds(spots.map((sp) => [sp.lat, sp.lon])), { padding: [40, 40], maxZoom: 11 });
    else map.setView([45.92, 6.87], 9); // Mont Blanc, until the first outing is confirmed
    pickHeat();
    seasonPick.addEventListener('change', applyFilters);
    yearPick.addEventListener('change', applyFilters);
    for (const pick of Object.values(climbPicks)) pick.addEventListener('change', applyFilters);
    searchBox.addEventListener('input', () => (searchBox.value ? showResults() : hideResults()));
    searchBox.addEventListener('focus', () => { if (searchBox.value) showResults(); });
    // close the results when the focus leaves both the field and the list (arrow down moves it into the list)
    const closeIfAway = () => setTimeout(() => {
      if (document.activeElement !== searchBox && !results.contains(document.activeElement)) hideResults();
    }, 0);
    searchBox.addEventListener('blur', closeIfAway);
    results.addEventListener('focusout', closeIfAway);
    searchBox.addEventListener('keydown', (ev) => {
      const first = results.querySelector('li[role=option]');
      if (ev.key === 'Escape') hideResults();
      else if (ev.key === 'Enter' && first) { ev.preventDefault(); first.dispatchEvent(new MouseEvent('mousedown')); }
      else if (ev.key === 'ArrowDown' && first) { ev.preventDefault(); first.focus(); }
    });
    mapBox._map = map;
  };
  return { element, start };
}
