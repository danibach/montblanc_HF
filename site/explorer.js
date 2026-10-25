// The take-off map: a heat map (take-offs when zoomed out, the ways up on foot when zoomed in), one marker per
// take-off (grouped when zoomed out), and, for the take-off that is clicked, the climbs on foot that reached it
// and the list of its outings. Flights are never drawn. Filters by season and year apply to everything.

import { groupName, sectorOf } from './sectors.js';
import { routeNumbers, routeSheet } from './routesheet.js';
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
const HEAT_SPOTS = { radius: 20, blur: 15, maxZoom: 8, max: 4, minOpacity: 0.45, gradient: GRADIENT };
// Heat of the ways up: each pilot counts once per take-off, spread along their climbs; 2 pilots on the same
// path make it hot.
const HEAT_ROUTES = { radius: 7, blur: 9, maxZoom: 14, max: 2, minOpacity: 0.35, gradient: GRADIENT };
const CLIMB = { color: '#1f4fff', weight: 3, opacity: 0.9 };
const CLIMB_HOT = { color: '#e0161b', weight: 5, opacity: 1 };
const CLIMB_BACK = { color: '#1f4fff', weight: 2, opacity: 0.25 };
// the routes of a take-off, as Strava or Komoot draw a way: a thin line on a white casing, one colour per start
const ROUTE_W = 4;
const ROUTE_CASING = { color: '#fff', weight: ROUTE_W + 3, opacity: 0.9, lineCap: 'round', lineJoin: 'round' };
const PALETTE = ['#fc4c02', '#2b6cb0', '#2f855a', '#805ad5', '#b7791f', '#c53030'];
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

// Spots closer than this are shown as one, with the outings of all of them. A take-off made from an outing can sit a
// few metres from an official one (the Mont Blanc: 7 m): two markers on top of each other, each hiding the other and
// its outings. The same distance as SAME_SPOT_M in src/mbhf/sites.py. Only for this page: nothing is stored.
const MERGE_M = 50;
const SOURCE_ORDER = { ffvl: 0, osm: 1, provisional: 2 };

const isOfficial = (sp) => !!sp.site && sp.site.source !== 'provisional';

/** A spot that is not an official take-off (provisional, or not tied yet) within MERGE_M of another spot joins the
 *  nearest one; the official take-off (else the busiest spot) keeps its name and point. Two official take-offs stay
 *  apart even 40 m away (the Suchet's two summits are mapped on purpose). ``siteIds`` lists the take-offs of the
 *  register a spot stands for, ``pilots`` counts each pilot once. */
function mergeClose(spots) {
  const order = (sp) => (sp.site ? SOURCE_ORDER[sp.site.source] ?? 3 : 4);
  const merged = [];
  for (const sp of spots.slice().sort((a, b) => order(a) - order(b) || b.outings.length - a.outings.length)) {
    const near = isOfficial(sp) ? [] : merged.map((m) => [metres(m.lat, m.lon, sp.lat, sp.lon), m]).filter(([d]) => d <= MERGE_M);
    const into = near.length ? near.reduce((a, b) => (b[0] < a[0] ? b : a))[1] : null;
    if (!into) { merged.push(sp); continue; }
    into.outings = into.outings.concat(sp.outings);
    for (const id of sp.siteIds) into.siteIds.add(id);
  }
  for (const sp of merged) sp.pilots = new Set(sp.outings.map(pilotOf)).size;
  return merged;
}

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
    if (!registered.has(site.id)) registered.set(site.id, { lat: site.lat, lon: site.lon, alt: site.alt, name: site.name, site, siteIds: new Set([site.id]), outings: [] });
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
      best = { lat: o.takeoff_lat, lon: o.takeoff_lon, siteIds: new Set(), outings: [] };
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
  return mergeClose([...registered.values(), ...spots]);
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
export function buildExplorer(rows, loadTraces, sites = [], routes = []) {
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
  // a sheet's address (#/map/route/12) is written without a page change: the map stays as it is. The one the page
  // was opened with is read before anything rewrites it.
  const setHash = (hash) => { if (location.hash !== hash) history.replaceState(null, '', hash); };
  const asked = location.hash.match(/^#\/map\/route\/(\d+)/);
  let sheetToOpen = null;
  let request = 0; // a slow answer for a spot we already left must not draw over the new one

  function overview() {
    setHash('#/map');
    current = null;
    request += 1;
    if (climbs) { climbs.eachLayer((l) => l.closeTooltip()); climbs.clearLayers(); }
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
    // a marker taken away under the pointer gets no mouseout: its tooltip would stay on the map
    markers.eachLayer((mk) => mk.closeTooltip());
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
        const mk = L.marker([sp.lat, sp.lon], { icon: icon(n, sp === current ? 'spot on' : 'spot'), riseOnHover: true });
        // no `title`: the browser's own tooltip came on top of this one and stayed while the pointer did not move;
        // the name stays readable for a screen reader
        mk.on('add', () => mk.getElement().setAttribute('aria-label', sp.name));
        // a node, not a string: Leaflet would read a string as HTML, and names come from OpenStreetMap
        mk.bindTooltip(h('span', null, `${sp.name} · ${plural(n, 'outing')} · ${plural(sp.pilots, 'pilot')}`), { direction: 'top', offset: [0, -14] });
        mk.on('click', () => openSpot(sp));
        markers.addLayer(mk);
      } else {
        const lat = group.reduce((a, sp) => a + sp.lat, 0) / group.length;
        const lon = group.reduce((a, sp) => a + sp.lon, 0) / group.length;
        const mk = L.marker([lat, lon], { icon: icon(n, 'group') });
        // named by its flying sector(s) (site/sectors.js): « Lac d'Annecy · 8 take-offs », not « 8 take-offs »
        const where = groupName(group);
        mk.bindTooltip(h('span', null, h('b', null, where), ` · ${group.length} take-offs · ${plural(n, 'outing')} — click to zoom in`), { direction: 'top', offset: [0, -16] });
        mk.on('add', () => mk.getElement().setAttribute('aria-label', `${where}, ${group.length} take-offs`));
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
    const routeId = sheetToOpen; // the sheet the page's address asks for (once)
    sheetToOpen = null;
    if (!routeId) setHash('#/map');
    climbs.eachLayer((l) => l.closeTooltip()); // a line taken away under the pointer keeps its tooltip otherwise
    climbs.clearLayers();
    element.querySelector('.explorer').classList.add('has-spot');
    draw();
    const list = h('div', { class: 'start-groups' });
    const status = h('p', { class: 'hint' });
    side.replaceChildren(
      h('div', { class: 'side-head' },
        h('div', null,
          h('h2', null, sp.name),
          h('p', { class: 'hint' }, `${sectorOf(sp.lat, sp.lon) ? `${sectorOf(sp.lat, sp.lon)} · ` : ''}${plural(sp.outings.length, 'confirmed outing')} · ${plural(sp.pilots, 'pilot')}${sp.alt != null ? ` · take-off at ${fmtInt(sp.alt)} m` : ''}`)),
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
    // Many climbs: the heat map of the ways up (shown from ROUTES_ZOOM on) replaces a tangle of lines. With routes
    // (the climbs that follow the same way gathered by the server), one line per route instead. Either way an
    // outing's own line appears only while it is hovered or kept lit.
    const crowded = climbOfId.size > MANY_CLIMBS;
    const siteRoutes = new Map(routes.filter((r) => sp.siteIds.has(r.site_id)).map((r) => [r.id, r]));
    const byRoute = sp.outings.some((o) => siteRoutes.has(o.route_id));
    const onDemand = crowded || byRoute;
    const lines = new Map();
    const bounds = L.latLngBounds([[sp.lat, sp.lon]]);
    let selected = null;
    const restyle = (hot) => {
      for (const [id, line] of lines) {
        const lit = id === hot || id === selected;
        if (onDemand) {
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
      if (!onDemand) line.addTo(climbs);
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

    // the list: one group per route (or per start place for the outings not in a route yet), gathered under their
    // start: a start with several ways is a folder (« From La Clusaz » holds « via Bois de la Colombière » and « via
    // Les Corbassières »). Largest first, sorted as chosen, PAGE outings at a time
    const groups = new Map();
    const labels = new Map();
    const placeOf = new Map();
    for (const o of sp.outings) {
      const route = siteRoutes.get(o.route_id);
      const key = route ? `route:${route.id}` : `place:${o.start_place || ''}`;
      labels.set(key, route ? route.name : `From ${o.start_place || 'an unnamed start'}`);
      groups.set(key, [...(groups.get(key) || []), o]);
    }
    // a route's start: the start place most of its outings share (as the server names it, src/mbhf/routes.py)
    for (const [key, outings] of groups) {
      const tally = new Map();
      for (const o of outings) if (o.start_place) tally.set(o.start_place, (tally.get(o.start_place) || 0) + 1);
      placeOf.set(key, [...tally.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || '');
    }
    const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    const starts = new Map();
    for (const [key, outings] of ordered) starts.set(placeOf.get(key), [...(starts.get(placeOf.get(key)) || []), [key, outings]]);
    const count = (ways) => ways.reduce((n, [, outings]) => n + outings.length, 0);
    const startList = [...starts.entries()].sort((a, b) => count(b[1]) - count(a[1]));
    // one colour per start; its busiest way in a full line, the others dotted
    const look = new Map();
    startList.forEach(([, ways], i) => ways.forEach(([key], j) => look.set(key, { color: PALETTE[i % PALETTE.length], main: j === 0 })));

    // a thin line per route on a white casing (the number of outings is in the list, not in the width)
    const routeLines = new Map();
    for (const [key, outings] of ordered) {
      const route = key.startsWith('route:') ? siteRoutes.get(Number(key.slice(6))) : null;
      if (!route || !route.line || route.line.length < 2) continue;
      const { color, main } = look.get(key);
      const style = { color, weight: ROUTE_W, opacity: 0.95, lineCap: 'round', lineJoin: 'round', dashArray: main ? null : '1 8' };
      const casing = L.polyline(route.line, { ...ROUTE_CASING, interactive: false }).addTo(climbs);
      const line = L.polyline(route.line, style).addTo(climbs);
      const place = placeOf.get(key);
      const several = (starts.get(place) || []).length > 1;
      line.bindTooltip(h('span', null, `${several ? `From ${place} · ` : ''}${route.name} · ${plural(outings.length, 'outing')}`), { sticky: true });
      // a route lights up under the pointer; a click keeps it lit (and opens it in the list), a second click lets it go
      // one label at a time, whatever the browser says of the lines the pointer left
      line.on('mouseover', () => {
        for (const drawn of routeLines.values()) if (drawn.line !== line) drawn.line.closeTooltip();
        paintRoutes([key]);
      });
      line.on('mouseout', () => paintRoutes([]));
      line.on('click', () => selectRoute(key));
      routeLines.set(key, { line, casing, style });
      bounds.extend(line.getBounds());
    }
    let selectedRoute = null;
    // the lit routes (hovered, kept) stand out; when some are lit, the others fade
    const paintRoutes = (keys) => {
      const lit = new Set([...keys, ...(selectedRoute ? [selectedRoute] : [])]);
      for (const [key, drawn] of routeLines) {
        const on = lit.has(key);
        if (!keys.includes(key)) drawn.line.closeTooltip(); // only the hovered line has its label
        drawn.casing.setStyle({ ...ROUTE_CASING, weight: ROUTE_CASING.weight + (on ? 2 : 0), opacity: lit.size && !on ? 0.3 : ROUTE_CASING.opacity });
        drawn.line.setStyle({ ...drawn.style, weight: drawn.style.weight + (on ? 2 : 0), opacity: lit.size && !on ? 0.35 : drawn.style.opacity });
        // only a kept route comes to the front: moving the hovered line in the page lost its mouseout, so its
        // label stayed on the map
        if (key === selectedRoute) { drawn.casing.bringToFront(); drawn.line.bringToFront(); }
      }
    };
    function selectRoute(key) {
      selectedRoute = selectedRoute === key ? null : key;
      paintRoutes([]);
      if (selectedRoute) { open.add(selectedRoute); open.add(`start:${placeOf.get(selectedRoute)}`); }
      renderList();
      const group = selectedRoute && list.querySelector(`[data-key="${selectedRoute}"]`);
      if (group) group.scrollIntoView({ block: 'nearest' });
    }
    const swatch = (key) => {
      const i = h('i', { class: look.get(key) && !look.get(key).main ? 'swatch dotted' : 'swatch' });
      if (look.get(key)) i.style.setProperty('--c', look.get(key).color); // a property, not an attribute: the page's CSP
      return i;
    };
    const median = (xs) => {
      const v = xs.filter((x) => x != null).sort((a, b) => a - b);
      return v.length ? v[Math.floor((v.length - 1) / 2)] : null;
    };
    // median numbers of a group's climbs: « ↗ 630 m · 6.4 km · 1 h 50 »
    function typical(outings) {
      const cs = outings.map((o) => climbOfId.get(o.id)).filter(Boolean);
      if (!cs.length) return '';
      const d = median(outings.map((o) => climbDplus(o, climbOfId.get(o.id))));
      const km = median(cs.map((c) => c.km));
      const t = median(cs.map((c) => c.duration_s));
      return [d != null ? `↗ ${fmtInt(d)} m` : null, km != null ? fmtKm(km) : null, t != null ? `⏱ ${fmtDur(t)}` : null]
        .filter(Boolean).join(' · ') + (outings.length > 1 ? ' (median)' : '');
    }
    const sortPick = h('select', { id: 'm-sort', 'aria-label': 'Sort the outings' },
      Object.entries(SORTS).map(([k, s]) => h('option', { value: k }, s.label)));
    const small = sp.outings.length <= PAGE;
    const open = new Set(small ? [...ordered.map((g) => g[0]), ...startList.map(([p]) => `start:${p}`)]
      : [ordered[0][0], `start:${placeOf.get(ordered[0][0])}`]);
    const pages = new Map();
    // one way: its outings under « From La Clusaz » or « via Les Corbassières »
    function wayGroup(key, outings, by) {
      const items = outings.slice().sort((a, b) => by(a, b, climbOfId));
      const n = pages.get(key) || PAGE;
      const body = h('ul', { class: 'out-list' }, items.slice(0, n).map(item));
      // a way of the server has its sheet: numbers, altitude profile, GPX (site/routesheet.js)
      const sheetLink = key.startsWith('route:') && siteRoutes.has(Number(key.slice(6)))
        ? h('button', { class: 'link sheet-link', onclick: () => showSheet(key) }, 'Route sheet: profile, time, GPX →') : null;
      const left = items.length - n;
      const more = left > 0
        ? h('button', { class: 'more', onclick: () => { pages.set(key, n + PAGE); renderList(); } },
          left > PAGE ? `Show ${PAGE} more (${left} left)` : `Show the last ${plural(left, 'outing')}`)
        : null;
      const numbers = typical(outings);
      const summary = h('summary', null, routeLines.has(key) ? swatch(key) : null, labels.get(key),
        h('span', { class: 'badge', title: plural(outings.length, 'outing') }, fmtInt(outings.length)),
        key.startsWith('route:') && numbers ? h('span', { class: 'route-nums' }, numbers) : null);
      if (routeLines.has(key)) {
        summary.addEventListener('mouseenter', () => paintRoutes([key]));
        summary.addEventListener('mouseleave', () => paintRoutes([]));
      }
      const group = h('details', { class: selectedRoute === key ? 'start-group on' : 'start-group', 'data-key': key, open: open.has(key) }, summary, sheetLink, body, more);
      group.addEventListener('toggle', () => { if (group.open) open.add(key); else open.delete(key); });
      return group;
    }
    function renderList() {
      const by = SORTS[sortPick.value].by;
      list.replaceChildren(...startList.map(([place, ways]) => {
        if (ways.length === 1) return wayGroup(ways[0][0], ways[0][1], by);
        // a start with several ways: a folder of them
        const fkey = `start:${place}`;
        const keys = ways.map(([key]) => key);
        const summary = h('summary', null, swatch(keys[0]), `From ${place || 'an unnamed start'}`,
          h('span', { class: 'hint' }, ` · ${ways.length} ways`), h('span', { class: 'badge' }, fmtInt(count(ways))));
        summary.addEventListener('mouseenter', () => paintRoutes(keys));
        summary.addEventListener('mouseleave', () => paintRoutes([]));
        const folder = h('details', { class: 'start-folder', 'data-key': fkey, open: open.has(fkey) }, summary,
          h('div', { class: 'ways' }, ways.map(([key, outings]) => wayGroup(key, outings, by))));
        folder.addEventListener('toggle', () => { if (folder.open) open.add(fkey); else open.delete(fkey); });
        return folder;
      }));
    }
    // the sheet of one way, in place of the take-off's panel (back to it with its button)
    function showSheet(key) {
      const route = siteRoutes.get(Number(key.slice(6)));
      const outings = groups.get(key) || [];
      const place = placeOf.get(key);
      const several = (starts.get(place) || []).length > 1;
      // « From La Clusaz · via Bois de la Colombière »; a start's only way is already named « From Les Verrier »
      const way = !several && /^from /i.test(route.name) ? route.name : `From ${place || 'an unnamed start'} · ${route.name}`;
      const panel = [...side.childNodes];
      const scroll = side.scrollTop;
      setHash(`#/map/route/${route.id}`);
      selectedRoute = key;
      paintRoutes([]);
      const back = () => {
        setHash('#/map');
        selectedRoute = null;
        paintRoutes([]);
        side.replaceChildren(...panel);
        side.scrollTop = scroll;
      };
      side.replaceChildren(routeSheet({
        route, way, link: `${location.origin}${location.pathname}#/map/route/${route.id}`, onBack: back,
        takeoff: { name: sp.name, alt: sp.alt }, swatch: swatch(key),
        numbers: routeNumbers(outings, (o) => climbOfId.get(o.id)),
        outings: h('ul', { class: 'out-list' }, outings.slice().sort((a, b) => SORTS.recent.by(a, b, climbOfId)).map(item)),
      }));
      side.scrollTop = 0;
      map.fitBounds(L.latLngBounds(route.line), { padding: [30, 30], maxZoom: 15 });
    }
    sortPick.addEventListener('change', () => { pages.clear(); renderList(); });
    list.before(h('div', { class: 'row sort-row' }, h('label', { for: 'm-sort' }, 'Sort'), sortPick));
    renderList();
    status.textContent = byRoute
      ? `${plural(routeLines.size, 'way')} up to this take-off, one colour per start (a dotted line: another way from the same start). Each line runs down the middle of its outings' climbs. Hover a way to light it and click it to keep it lit; hover an outing to see its own climb.`
      : crowded
        ? `${plural(climbOfId.size, 'climb')}: the heat map shows the ways up. Hover an outing to see its climb; click it to keep it.`
        : 'Hover an outing to light its climb; click it to keep it lit.';
    if (lines.size) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
    if (crowded && map.getZoom() < ROUTES_ZOOM) map.setZoom(ROUTES_ZOOM); // close enough for the heat of the ways up
    if (routeId && siteRoutes.has(routeId)) showSheet(`route:${routeId}`);
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
    // a sheet's address: its take-off opened on it (in all seasons if the season shown hides it)
    const wantedRoute = asked && routes.find((r) => r.id === Number(asked[1]));
    if (wantedRoute) {
      const holder = () => spots.find((s) => s.siteIds.has(wantedRoute.site_id));
      if (!holder() && seasonPick.value) { seasonPick.value = ''; applyFilters(); }
      if (holder()) { sheetToOpen = wantedRoute.id; openSpot(holder()); }
    }
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
