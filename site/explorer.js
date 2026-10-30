// The take-off map: a heat map (take-offs when zoomed out, the ways up on foot when zoomed in), one marker per
// take-off (grouped when zoomed out), and, for the take-off that is clicked, the climbs on foot that reached it
// and the list of its outings. Flights are never drawn. Filters by season and year apply to everything.

import { groupName, sectorOf } from './sectors.js';
import { routeNumbers, routeSheet } from './routesheet.js';
import { can3D, fullScreenButton, mapPanel, view3D } from './basemaps.js';
import { h, s, fmtInt, fmtKm, fmtDur, fmtDate, outingTitle } from './util.js';
import { t, tr } from './i18n.js';
import { card as ffvlCard, ffvlLayer, windLabel } from './ffvl.js';
import { scaleAndRuler } from './ruler.js';

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
const CLIMB = { color: '#1f4fff', weight: 1.5, opacity: 0.9 };
const CLIMB_HOT = { color: '#e0161b', weight: 2.5, opacity: 1 };
// the routes of a take-off, as Strava or Komoot draw a way: a thin line on a white casing, one colour per start
const ROUTE_W = 2; // fine lines (Sarah, 27 October 2026); a wider invisible line catches the pointer
const HIT_W = 14;
const ROUTE_CASING = { color: '#fff', weight: ROUTE_W + 2, opacity: 0.9, lineCap: 'round', lineJoin: 'round' };
const PALETTE = ['#fc4c02', '#2b6cb0', '#2f855a', '#805ad5', '#b7791f', '#c53030'];
// ``label``: the key of the text in site/i18n (looked up when drawn)
const SEASONS = {
  summer: { label: 'season.summer', short: 'season.summerShort', months: [5, 6, 7, 8, 9, 10] },
  winter: { label: 'season.winter', short: 'season.winterShort', months: [11, 12, 1, 2, 3, 4] },
};

/** Buttons side by side, one of them pressed (« All seasons | Summer | Winter »). Like a select: ``value`` reads and
 *  sets the pressed one (without an event); a click sends « change ». ``options``: [[value, text], …]. */
function segmented(id, label, options) {
  const box = h('div', { class: 'seg-big', id, role: 'group', 'aria-label': label });
  let value = options[0][0];
  const buttons = options.map(([v, text]) => h('button', { type: 'button', 'data-value': v, 'aria-pressed': String(v === value), onclick: () => {
    if (value === v) return;
    box.value = v;
    box.dispatchEvent(new Event('change'));
  } }, text));
  box.append(...buttons);
  Object.defineProperty(box, 'value', {
    get: () => value,
    set: (v) => { value = v; for (const b of buttons) b.setAttribute('aria-pressed', String(b.dataset.value === v)); },
  });
  return box;
}

const PARKING_M = 30; // an itinerary's first point this close to a car park of OpenStreetMap starts at it
const parkingCache = new Map();
/** For each point ([lat, lon]), whether OpenStreetMap has a car park within PARKING_M; all false when it cannot say. */
async function parkingsNear(points) {
  const key = (p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
  const ask = points.filter((p) => !parkingCache.has(key(p)));
  if (ask.length) {
    try {
      const q = `[out:json][timeout:15];(${ask.map((p) => `nwr["amenity"="parking"](around:${PARKING_M},${p[0]},${p[1]});`).join('')});out center;`;
      const res = await fetch('https://overpass-api.de/api/interpreter', { method: 'POST', body: new URLSearchParams({ data: q }) });
      const found = ((await res.json()).elements || []).map((e) => (e.center ? [e.center.lat, e.center.lon] : [e.lat, e.lon])).filter((c) => c[0] != null);
      const r = Math.PI / 180;
      const m = (a, b) => 12742000 * Math.asin(Math.sqrt(Math.sin(((b[0] - a[0]) * r) / 2) ** 2
        + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(((b[1] - a[1]) * r) / 2) ** 2));
      // a car park's centre can be farther than its edge: the way's start is at its centre (src/mbhf/routes.py)
      for (const p of ask) parkingCache.set(key(p), found.some((c) => m(p, c) < PARKING_M * 2));
    } catch (_) {
      return points.map(() => false); // no answer: no P, asked again next time
    }
  }
  return points.map((p) => parkingCache.get(key(p)) || false);
}

const filterIcon = () => s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, s('path', { d: 'M4 6h16M7 12h10M10 18h4' }));

// « 3 outings », « 1 pilot »: the plural forms of the language (key of site/i18n/*.js)
const plural = (n, key) => t(key, { n });

// D+ of the climb when it is known, else the engine's D+ on foot
const climbDplus = (o, climb) => (climb && climb.dplus_m != null ? climb.dplus_m : o.dplus_m);
// orders of the list of a take-off's outings; ``climbs`` maps an outing id to its climb
const SORTS = {
  recent: { label: 'sort.recent', by: (a, b) => String(b.outing_date || '').localeCompare(String(a.outing_date || '')) },
  climb: { label: 'sort.climb', by: (a, b, climbs) => (climbDplus(b, climbs.get(b.id)) || 0) - (climbDplus(a, climbs.get(a.id)) || 0) },
  fast: {
    label: 'sort.fast',
    by: (a, b, climbs) => {
      // outings without a known climb time go last
      const [ta, tb] = [a, b].map((o) => (climbs.get(o.id) || {}).duration_s ?? Infinity);
      return ta === tb ? 0 : ta < tb ? -1 : 1;
    },
  },
};

/** The name of a route as the server wrote it (src/mbhf/routes.py: « From La Clusaz », « via Les Corbassières », « Main
 * way », « Way 2 »), in the language of the visitor. A name that is none of these is shown as it is. */
function routeName(name) {
  const text = String(name || '');
  if (text === 'From an unnamed start') return t('route.fromUnnamed');
  let m = /^From (.+)$/.exec(text);
  if (m) return t('route.from', { place: m[1] });
  m = /^via (.+)$/.exec(text);
  if (m) return t('route.via', { place: m[1] });
  if (text === 'Main way') return t('route.main');
  m = /^Way (\d+)$/.exec(text);
  return m ? t('route.n', { n: m[1] }) : text;
}
const fromPlace = (place) => (place ? t('route.from', { place }) : t('route.fromUnnamed'));

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
      || `${t('detail.takeoff')}${sp.alt != null ? ` · ${fmtInt(sp.alt)} m` : ''}`;
  }
  return mergeClose([...registered.values(), ...spots]);
}

const SOURCES = {
  ffvl: 'src.ffvl',
  osm: 'src.osm',
  provisional: 'src.provisional',
};

/** The good winds of a take-off, in a few words (« Good winds: NW, W »), or null. The FFVL writes the winds as French
 *  letters (O for ouest): shown with the letters of the language. */
function windsOf(sp) {
  const site = sp.site;
  return site && site.wind_ok ? t('site.goodWinds', { winds: site.wind_ok.split(/[;,\s]+/).filter(Boolean).map(windLabel).join(', ') }) : null;
}

/** Where the take-off comes from, the FFVL's hike & fly notes, and the ties left to confirm. */
function siteFacts(sp) {
  const site = sp.site;
  if (!site) return null;
  const toConfirm = sp.outings.filter((o) => o.takeoff_site_status === 'to_confirm').length;
  return h('div', { class: 'site-facts' },
    h('span', { class: `badge ${site.source}` }, t(SOURCES[site.source] || 'detail.takeoff')),
    toConfirm ? h('p', { class: 'hint' }, t('site.toConfirm', { n: toConfirm })) : null,
    site.hike_and_fly ? h('details', null, h('summary', null, t('site.hikeFly')), h('p', { class: 'hint' }, site.hike_and_fly)) : null);
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
// labels and bands: keys of the texts in site/i18n (looked up when drawn)
const CLIMB_FILTERS = {
  dplus: {
    label: 'climb.dplus',
    bands: [['', 'climb.dplus.any'], ['0-500', 'climb.dplus.b1'], ['500-1000', 'climb.dplus.b2'], ['1000-1500', 'climb.dplus.b3'], ['1500-', 'climb.dplus.b4']],
    value: (o) => climbDplus(o, storedClimb(o)),
  },
  km: {
    label: 'climb.km',
    bands: [['', 'climb.km.any'], ['0-5', 'climb.km.b1'], ['5-10', 'climb.km.b2'], ['10-', 'climb.km.b3']],
    value: (o) => (storedClimb(o) ? storedClimb(o).km : o.walk_km),
  },
  time: {
    label: 'climb.time',
    bands: [['', 'climb.time.any'], ['0-5400', 'climb.time.b1'], ['5400-10800', 'climb.time.b2'], ['10800-', 'climb.time.b3']],
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
 * full tracks; ``sites`` are the take-offs of the register (getMapSites()); ``me`` is the signed-in pilot's id (for
 * « My tracks »), or null. Returns {element, start}: start() is called once the element is in the page.
 */
export function buildExplorer(rows, loadTraces, sites = [], routes = [], ffvl = { sites: [], info: null }, me = null) {
  const mapBox = h('div', { class: 'map map-wide', role: 'region', 'aria-label': t('map.aria') });
  const side = h('aside', { class: 'side', 'aria-live': 'polite' });
  const years = [...new Set(rows.map((o) => String(o.outing_date || '').slice(0, 4)).filter(Boolean))].sort().reverse();
  const seasonPick = segmented('m-season', t('map.season'), [['', t('season.all')],
    ...Object.entries(SEASONS).map(([k, s]) => [k, t(s.short)])]);
  // everyone's outings, or one's own (signed in only)
  const whoPick = me ? segmented('m-who', t('map.who'), [['', t('map.allTracks')], ['mine', t('map.myTracks')]]) : null;
  const yearPick = h('select', { id: 'm-year' }, h('option', { value: '' }, t('filter.allYears')), years.map((y) => h('option', { value: y }, y)));
  // The map opens on the current season: summer and winter climbs do not take the same ways. All seasons when the
  // current one has no outing yet.
  const now = season({ outing_date: new Date().toISOString() });
  if (rows.some((o) => season(o) === now)) seasonPick.value = now;
  const climbPicks = Object.fromEntries(Object.entries(CLIMB_FILTERS).map(([k, f]) => [k,
    h('select', { id: `m-${k}`, 'aria-label': t(f.label) }, f.bands.map(([v, text]) => h('option', { value: v }, t(text))))]));
  // the year and the climb filters, in a panel under the « Filters » button
  const filtersButton = h('button', { type: 'button', class: 'filters-btn', id: 'm-filters', 'aria-expanded': 'false', 'aria-controls': 'm-filters-pop' });
  const shownButton = h('button', { type: 'button', class: 'primary' });
  const filtersPop = h('div', { class: 'filters-pop', id: 'm-filters-pop', hidden: true },
    h('div', { class: 'filters' },
      h('div', { class: 'field' }, h('label', { for: 'm-year' }, t('filter.year')), yearPick),
      Object.entries(CLIMB_FILTERS).map(([k, f]) =>
        h('div', { class: 'field' }, h('label', { for: `m-${k}` }, t(f.label)), climbPicks[k]))),
    h('div', { class: 'fp-foot' },
      h('button', { type: 'button', class: 'link', onclick: () => {
        yearPick.value = '';
        for (const p of Object.values(climbPicks)) p.value = '';
        applyFilters();
      } }, t('map.clearFilters')),
      shownButton));
  const openFilters = (open) => { filtersPop.hidden = !open; filtersButton.setAttribute('aria-expanded', String(open)); };
  filtersButton.addEventListener('click', () => openFilters(filtersPop.hidden));
  shownButton.addEventListener('click', () => openFilters(false));
  // search a take-off, a flying sector, or a start place (a village, a car park): the results open under the field
  const searchBox = h('input', { type: 'search', id: 'm-search', placeholder: t('map.searchPlaceholder'), autocomplete: 'off',
    'aria-controls': 'm-results', 'aria-expanded': 'false' });
  const results = h('ul', { class: 'search-results', id: 'm-results', role: 'listbox', hidden: true });
  const filtersWrap = h('div', { class: 'filters-wrap' }, filtersButton, filtersPop);
  const bar = h('div', { class: 'map-toolbar' },
    h('div', { class: 'field search' }, h('label', { for: 'm-search' }, t('map.search')), searchBox, results),
    seasonPick, filtersWrap, whoPick);
  // the legend, above the map (Sarah, 30 October 2026): the heat map, the itineraries, the climbs, the take-offs
  const legendRow = h('div', { class: 'map-legend' });
  const element = h('div', null, bar, legendRow, h('div', { class: 'explorer' }, mapBox, side));
  // from the home page: a search (#/map?q=…) or a sector (#/map?sector=…)
  const askedQuery = new URLSearchParams(location.hash.split('?')[1] || '');
  const L = window.L;
  if (!L || !L.heatLayer) {
    mapBox.append(h('p', { class: 'hint pad' }, t('map.failed')));
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
    renderOverview();
    if (markers) draw();
  }

  // the panel when no take-off is open (Sarah, 30 October 2026): three numbers, then the flying sectors in view, the
  // busiest first, each unfolding on its take-offs. It follows the map as it moves; the sectors left open stay open.
  const openSectors = new Set();
  let firstOverview = true;
  function renderOverview() {
    const siteIds = new Set(spots.flatMap((sp) => [...sp.siteIds]));
    const tile = (id, n, key) => h('div', { class: 'ov-tile' }, h('b', { id }, fmtInt(n)), h('span', null, t(key, { n })));
    let view = null;
    try { view = map && map.getBounds(); } catch (_) { /* no view yet: every take-off counts */ }
    const inView = spots.filter((sp) => !view || view.contains([sp.lat, sp.lon]));
    const bySector = new Map();
    for (const sp of inView) {
      const name = sectorOf(sp.lat, sp.lon) || '';
      bySector.set(name, [...(bySector.get(name) || []), sp]);
    }
    const outingsOf = (list) => list.reduce((n, sp) => n + sp.outings.length, 0);
    const sectors = [...bySector.entries()].sort((a, b) => (!a[0]) - (!b[0]) || outingsOf(b[1]) - outingsOf(a[1]));
    if (firstOverview && sectors.length) { openSectors.add(sectors[0][0]); firstOverview = false; }
    const sectorBox = ([name, list]) => {
      const box = h('details', { class: 'ov-sector', open: openSectors.has(name) },
        h('summary', null,
          h('span', { class: 'ov-name' }, h('b', null, name || t('sector.otherTakeoffs')),
            h('span', { class: 'hint' }, `${plural(list.length, 'unit.takeoff')} · ${plural(outingsOf(list), 'unit.outing')}`)),
          h('button', { type: 'button', class: 'link ov-frame', title: t('map.frameSector'), 'aria-label': t('map.frameSector'), onclick: (ev) => {
            ev.preventDefault();
            map.fitBounds(L.latLngBounds(list.map((sp) => [sp.lat, sp.lon])), { padding: [60, 60], maxZoom: 13 });
          } }, '⌖')),
        list.slice().sort((a, b) => b.outings.length - a.outings.length).map((sp) =>
          h('button', { type: 'button', class: 'ov-spot', onclick: () => openSpot(sp) },
            h('span', { class: 'ov-count' }, fmtInt(sp.outings.length)),
            h('span', null, h('b', null, sp.name), sp.alt != null ? h('span', { class: 'hint' }, ` · ${fmtInt(sp.alt)} m`) : null))));
      box.addEventListener('toggle', () => { if (box.open) openSectors.add(name); else openSectors.delete(name); });
      return box;
    };
    side.replaceChildren(
      h('div', { class: 'ov-tiles' },
        tile('m-count-spots', spots.length, 'map.tileTakeoffs'),
        tile('m-count-routes', routes.filter((r) => siteIds.has(r.site_id)).length, 'map.tileRoutes'),
        tile('m-count-outings', shown.length, 'map.tileOutings')),
      h('p', { class: 'hint' }, t('map.overviewHint')),
      h('h2', { class: 'ov-title' }, t('map.sectorsInView')),
      ...(sectors.length ? sectors.map(sectorBox) : [h('p', { class: 'hint' }, t('map.noneInView'))]));
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
        mk.bindTooltip(h('span', null, t('map.spotTip', { name: sp.name, outings: plural(n, 'unit.outing'), pilots: plural(sp.pilots, 'unit.pilot') })), { direction: 'top', offset: [0, -14] });
        mk.on('click', () => openSpot(sp));
        markers.addLayer(mk);
      } else {
        const lat = group.reduce((a, sp) => a + sp.lat, 0) / group.length;
        const lon = group.reduce((a, sp) => a + sp.lon, 0) / group.length;
        const mk = L.marker([lat, lon], { icon: icon(n, 'group') });
        // named by its flying sector(s) (site/sectors.js): « Lac d'Annecy · 8 take-offs », not « 8 take-offs »
        const where = groupName(group);
        mk.bindTooltip(h('span', null, tr('map.groupTip', { where: h('b', null, where), takeoffs: plural(group.length, 'unit.takeoff'), outings: plural(n, 'unit.outing') })), { direction: 'top', offset: [0, -16] });
        mk.on('add', () => mk.getElement().setAttribute('aria-label', t('map.groupAria', { where, takeoffs: plural(group.length, 'unit.takeoff') })));
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
  }

  function applyFilters() {
    const s = seasonPick.value;
    const y = yearPick.value;
    const mineOnly = whoPick && whoPick.value === 'mine';
    shown = rows.filter((o) => (!s || season(o) === s) && (!y || String(o.outing_date || '').startsWith(y))
      && (!mineOnly || o.user_id === me)
      && Object.entries(CLIMB_FILTERS).every(([k, f]) => inBand(f.value(o), climbPicks[k].value)));
    spots = groupTakeoffs(shown, sites);
    setPoints(heatSpots, spots.map((sp) => [sp.lat, sp.lon, sp.pilots]));
    setPoints(heatRoutes, routePoints(spots));
    const active = Object.values(climbPicks).filter((p) => p.value).length + (y ? 1 : 0);
    filtersButton.replaceChildren(filterIcon(), active ? `${t('map.filters')} (${active})` : t('map.filters'));
    shownButton.textContent = t('map.showOutings', { n: shown.length });
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
    // the flying sectors (« Aravis », « Lac d'Annecy »: site/sectors.js) that hold take-offs on the map
    const sectors = new Map();
    for (const sp of spots) {
      const name = sectorOf(sp.lat, sp.lon);
      if (!name || !hasText(name, q)) continue;
      const m = sectors.get(name) || { kind: 'sector', text: name, spots: new Set(), n: 0, rank: rank(name) - 0.5 };
      m.spots.add(sp);
      m.n += sp.outings.length;
      sectors.set(name, m);
    }
    found.push(...sectors.values());
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
          ? ` · ${m.spot.alt != null ? t('search.takeoffAt', { alt: fmtInt(m.spot.alt) }) : t('search.takeoff')} · ${plural(m.n, 'unit.outing')}`
          : ` · ${t(m.kind === 'sector' ? 'search.sector' : 'search.start')} · ${plural(m.spots.size, 'unit.takeoff')}, ${plural(m.n, 'unit.outing')}`));
      li.addEventListener('mousedown', (ev) => { ev.preventDefault(); choose(m); }); // before the field loses focus
      li.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') choose(m); });
      return li;
    }) : [h('li', { class: 'hint' }, searchBox.value.trim().length < 2 ? t('search.min') : t('search.none'))]));
    results.hidden = false;
    searchBox.setAttribute('aria-expanded', 'true');
  }

  function hideResults() {
    results.hidden = true;
    searchBox.setAttribute('aria-expanded', 'false');
  }

  // the FFVL card of a take-off of ours that is an official one: winds on a rose, walk, warnings, restrictions…
  function ffvlFacts(sp) {
    // the map's list of take-offs has no FFVL id: the FFVL take-off within about 100 m of ours
    const site = sp.site && sp.site.source === 'ffvl' && ffvl.sites.find((f) => f.kind.includes('T')
      && Math.abs(f.lat - sp.site.lat) < 0.0009 && Math.abs(f.lon - sp.site.lon) < 0.0013);
    if (!site) return null;
    const box = h('div', { class: 'ffvl-in-panel' }, h('p', { class: 'hint' }, t('ffvl.loadingCard')));
    ffvl.info(site.id).catch(() => ({})).then((info) => box.replaceChildren(ffvlCard(site, info)));
    return box;
  }

  // a P where an itinerary starts at a car park: the server starts it there when one is within 100 m
  // (src/mbhf/routes.py) but does not say so, so the car parks at the starts are asked from OpenStreetMap
  async function markParkings(rts, mine) {
    const at = await parkingsNear(rts.map((r) => r.line[0]));
    if (mine !== request) return;
    rts.forEach((r, i) => {
      if (!at[i]) return;
      L.marker(r.line[0], { icon: L.divIcon({ className: 'p-mark', html: 'P', iconSize: [16, 16] }), interactive: false, keyboard: false }).addTo(climbs);
    });
  }

  // the take-off's register entry and FFVL card, folded under its name (Sarah, 30 October 2026: short, but in sight)
  function moreAbout(sp) {
    const facts = [siteFacts(sp), ffvlFacts(sp)].filter(Boolean);
    return facts.length ? h('details', { class: 'spot-more' }, h('summary', null, t('spot.more')), facts) : null;
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
          h('p', { class: 'hint' }, [sectorOf(sp.lat, sp.lon), sp.alt != null ? t('search.takeoffAt', { alt: fmtInt(sp.alt) }) : null].filter(Boolean).join(' · ')),
          h('p', { class: 'hint' }, [plural(sp.outings.length, 'unit.confirmedOuting'), plural(sp.pilots, 'unit.pilot'), windsOf(sp)].filter(Boolean).join(' · '))),
        h('button', { class: 'link close', 'aria-label': t('map.back'), onclick: overview }, '×')),
      // replaceChildren would write a null as the text « null »
      ...[moreAbout(sp), status, list].filter(Boolean));
    side.scrollTop = 0;
    map.setView([sp.lat, sp.lon], Math.max(map.getZoom(), 13));

    // the climbs: stored by the server job; read from the full tracks only for outings that have none yet
    const climbOfId = new Map();
    for (const o of sp.outings) if (storedClimb(o)) climbOfId.set(o.id, storedClimb(o));
    const missing = sp.outings.filter((o) => !o.climb).slice(0, MAX_TRACES);
    if (missing.length) {
      status.textContent = t('climbs.loading');
      try {
        for (const t of await loadTraces(missing.map((o) => o.id))) {
          const c = climbOf({ ...missing.find((o) => o.id === t.id), ...t });
          if (c) climbOfId.set(t.id, c);
        }
      } catch (e) {
        if (mine !== request) return;
        status.textContent = t('climbs.partial', { error: e.message });
      }
      if (mine !== request) return;
    }
    // Many climbs: the heat map of the ways up (shown from ROUTES_ZOOM on) replaces a tangle of lines. With routes
    // (the climbs that follow the same way gathered by the server), one line per route instead. Either way an
    // outing's own line appears only while it is hovered or kept lit.
    const crowded = climbOfId.size > MANY_CLIMBS;
    const siteRoutes = new Map(routes.filter((r) => sp.siteIds.has(r.site_id)).map((r) => [r.id, r]));
    const byRoute = sp.outings.some((o) => siteRoutes.has(o.route_id));
    // only the itineraries are drawn (Sarah, 30 October 2026): the ways each pilot took are in the heat map, and an
    // outing's own climb appears while it is hovered or kept lit
    const lines = new Map();
    const bounds = L.latLngBounds([[sp.lat, sp.lon]]);
    let selected = null;
    const restyle = (hot) => {
      for (const [id, line] of lines) {
        const lit = id === hot || id === selected;
        // through the group: a line only taken off the map would stay in it and never come back
        if (lit) climbs.addLayer(line.setStyle(CLIMB_HOT));
        else climbs.removeLayer(line);
        if (lit) line.bringToFront();
      }
      for (const li of list.querySelectorAll('li[data-id]')) li.classList.toggle('on', li.dataset.id === selected);
    };
    const select = (id) => { selected = selected === id ? null : id; restyle(null); };

    for (const o of sp.outings) {
      const climb = climbOfId.get(o.id);
      if (!climb) continue;
      const line = L.polyline(climb.line, CLIMB);
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
        h('span', { class: 'hint' }, `${o.pilot || t('pilot.anonymous')} · ${fmtDate(o.outing_date)}`),
        h('span', { class: 'nums' },
          h('span', { title: climb && climb.dplus_m != null ? t('item.dplusClimb') : t('stat.dplus') }, `↗ ${fmtInt(climbDplus(o, climb))} m`),
          h('span', { title: t('item.distance') }, climb ? fmtKm(climb.km) : fmtKm(o.walk_km)),
          h('span', { title: t('item.time') }, climb ? `⏱ ${fmtDur(climb.duration_s)}` : '')),
        climb ? null : h('span', { class: 'hint' }, t('item.noClimb')),
        h('a', { href: `#/outing/${o.id}` }, t('item.open')));
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
      labels.set(key, route ? routeName(route.name) : fromPlace(o.start_place));
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
      const line = L.polyline(route.line, { ...style, interactive: false }).addTo(climbs);
      // the line is fine: an invisible wider one above it takes the pointer
      const hit = L.polyline(route.line, { color: '#000', opacity: 0, weight: HIT_W }).addTo(climbs);
      const place = placeOf.get(key);
      const several = (starts.get(place) || []).length > 1;
      hit.bindTooltip(h('span', null, `${several ? `${fromPlace(place)} · ` : ''}${routeName(route.name)} · ${plural(outings.length, 'unit.outing')}`), { sticky: true });
      // a route lights up under the pointer; a click keeps it lit (and opens it in the list), a second click lets it go
      // one label at a time, whatever the browser says of the lines the pointer left
      hit.on('mouseover', () => {
        for (const drawn of routeLines.values()) if (drawn.hit !== hit) drawn.hit.closeTooltip();
        paintRoutes([key]);
      });
      hit.on('mouseout', () => paintRoutes([]));
      // a click opens the itinerary: its sheet, and the climbs of its outings around it
      hit.on('click', () => showSheet(key));
      routeLines.set(key, { line, casing, hit, style });
      bounds.extend(line.getBounds());
    }
    let selectedRoute = null;
    // the lit routes (hovered, kept) stand out; when some are lit, the others fade
    const paintRoutes = (keys) => {
      const lit = new Set([...keys, ...(selectedRoute ? [selectedRoute] : [])]);
      for (const [key, drawn] of routeLines) {
        const on = lit.has(key);
        if (!keys.includes(key)) drawn.hit.closeTooltip(); // only the hovered line has its label
        drawn.casing.setStyle({ ...ROUTE_CASING, weight: ROUTE_CASING.weight + (on ? 1 : 0), opacity: lit.size && !on ? 0.3 : ROUTE_CASING.opacity });
        drawn.line.setStyle({ ...drawn.style, weight: drawn.style.weight + (on ? 1 : 0), opacity: lit.size && !on ? 0.35 : drawn.style.opacity });
        // only a kept route comes to the front: moving the hovered line in the page lost its mouseout, so its
        // label stayed on the map
        if (key === selectedRoute) { drawn.casing.bringToFront(); drawn.line.bringToFront(); drawn.hit.bringToFront(); }
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
      const dur = median(cs.map((c) => c.duration_s));
      return [d != null ? `↗ ${fmtInt(d)} m` : null, km != null ? fmtKm(km) : null, dur != null ? `⏱ ${fmtDur(dur)}` : null]
        .filter(Boolean).join(' · ') + (outings.length > 1 ? ' ' + t('route.median') : '');
    }
    const sortPick = h('select', { id: 'm-sort', 'aria-label': t('sort.aria') },
      Object.entries(SORTS).map(([k, s]) => h('option', { value: k }, t(s.label))));
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
        ? h('button', { class: 'link sheet-link', onclick: () => showSheet(key) }, t('route.sheetLink')) : null;
      const left = items.length - n;
      const more = left > 0
        ? h('button', { class: 'more', onclick: () => { pages.set(key, n + PAGE); renderList(); } },
          left > PAGE ? t('list.more', { page: PAGE, left }) : t('list.showLast', { n: left }))
        : null;
      const numbers = typical(outings);
      const summary = h('summary', null, routeLines.has(key) ? swatch(key) : null, labels.get(key),
        h('span', { class: 'badge', title: plural(outings.length, 'unit.outing') }, fmtInt(outings.length)),
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
        const summary = h('summary', null, swatch(keys[0]), fromPlace(place),
          h('span', { class: 'hint' }, ` · ${t('route.ways', { n: ways.length })}`), h('span', { class: 'badge' }, fmtInt(count(ways))));
        summary.addEventListener('mouseenter', () => paintRoutes(keys));
        summary.addEventListener('mouseleave', () => paintRoutes([]));
        const folder = h('details', { class: 'start-folder', 'data-key': fkey, open: open.has(fkey) }, summary,
          h('div', { class: 'ways' }, ways.map(([key, outings]) => wayGroup(key, outings, by))));
        folder.addEventListener('toggle', () => { if (folder.open) open.add(fkey); else open.delete(fkey); });
        return folder;
      }));
    }
    // the sheet of one way, in place of the take-off's panel (back to it with its button); another itinerary clicked
    // on the map first closes the sheet that is open
    let closeSheet = null;
    function showSheet(key) {
      if (closeSheet) closeSheet();
      const route = siteRoutes.get(Number(key.slice(6)));
      const outings = groups.get(key) || [];
      const place = placeOf.get(key);
      const several = (starts.get(place) || []).length > 1;
      // « From La Clusaz · via Bois de la Colombière »; a start's only way is already named « From Les Verrier »
      const way = !several && /^from /i.test(route.name) ? routeName(route.name) : `${fromPlace(place)} · ${routeName(route.name)}`;
      const panel = [...side.childNodes];
      const scroll = side.scrollTop;
      setHash(`#/map/route/${route.id}`);
      selectedRoute = key;
      paintRoutes([]);
      // the climbs of the itinerary's outings, thin, in its colour (one lights up in red when hovered in the sheet)
      const colour = look.get(key).color;
      const traces = L.layerGroup(outings.map((o) => climbOfId.get(o.id)).filter(Boolean)
        .map((c) => L.polyline(c.line, { color: colour, weight: 1.2, opacity: 0.45, interactive: false }))).addTo(climbs);
      const drawn = routeLines.get(key);
      if (drawn) { drawn.casing.bringToFront(); drawn.line.bringToFront(); drawn.hit.bringToFront(); }
      const back = () => {
        closeSheet = null;
        setHash('#/map');
        selectedRoute = null;
        climbs.removeLayer(traces);
        paintRoutes([]);
        side.replaceChildren(...panel);
        side.scrollTop = scroll;
      };
      closeSheet = back;
      side.replaceChildren(routeSheet({
        route, way, link: `${location.origin}${location.pathname}#/map/route/${route.id}`, onBack: back,
        takeoff: { name: sp.name, alt: sp.alt }, swatch: swatch(key),
        on3D: can3D() ? () => view3D({ line: route.line, title: `${sp.name} · ${way}`, winter: seasonPick.value === 'winter' }) : null,
        numbers: routeNumbers(outings, (o) => climbOfId.get(o.id)),
        outings: h('ul', { class: 'out-list' }, outings.slice().sort((a, b) => SORTS.recent.by(a, b, climbOfId)).map(item)),
      }));
      side.scrollTop = 0;
      map.fitBounds(L.latLngBounds(route.line), { padding: [30, 30], maxZoom: 15 });
    }
    sortPick.addEventListener('change', () => { pages.clear(); renderList(); });
    list.before(h('div', { class: 'row sort-row' }, h('label', { for: 'm-sort' }, t('sort.label')), sortPick));
    renderList();
    markParkings(ordered.map(([key]) => siteRoutes.get(Number(key.slice(6)))).filter((r) => r && r.line && r.line.length > 1), mine);
    status.textContent = byRoute
      ? t('status.byRoute', { n: routeLines.size })
      : crowded
        ? t('status.crowded', { n: climbOfId.size })
        : t('status.hover');
    if (lines.size) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
    if (crowded && map.getZoom() < ROUTES_ZOOM) map.setZoom(ROUTES_ZOOM); // close enough for the heat of the ways up
    if (routeId && siteRoutes.has(routeId)) showSheet(`route:${routeId}`);
  }

  const start = () => {
    map = L.map(mapBox, { worldCopyJump: true });
    fullScreenButton(L, map); // the map fills the screen (a phone's map is small)
    scaleAndRuler(L, map); // the scale bar, and a ruler to measure a way with its D+ (site/ruler.js)
    // no flag, to keep the credits short on a phone
    map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
    // the take-off register's sources, as their licences ask (Licence Ouverte 2.0, ODbL): one short line for both
    // the take-offs and the FFVL sites
    if (sites.length || ffvl.sites.length) map.attributionControl.addAttribution('FFVL (Licence Ouverte), OSM (ODbL)');
    heatSpots = L.heatLayer([], HEAT_SPOTS);
    heatRoutes = L.heatLayer([], HEAT_ROUTES);
    heat = L.layerGroup().addTo(map);
    climbs = L.featureGroup().addTo(map);
    markers = L.layerGroup().addTo(map);
    // the official FFVL take-offs ▲ and landings ▼ (from zoom 10 on), with their card on a click (site/ffvl.js)
    const shown = { takeoffs: markers, heat, ffvl: null };
    if (ffvl.sites.length) {
      // where a take-off of ours is drawn (within 100 m), the ▲ goes beside its marker
      const taken = (lat, lon) => spots.some((sp) => Math.abs(sp.lat - lat) < 0.0009 && Math.abs(sp.lon - lon) < 0.0013);
      shown.ffvl = ffvlLayer(L, map, ffvl.sites, ffvl.info, taken).addTo(map);
    }
    // the « Map » button and its panel (site/basemaps.js): map style, points of interest, layers in an order of
    // one's own; the style follows the season picked in the filter
    const backgrounds = mapPanel(L, map, shown, () => seasonPick.value === 'winter');

    // the legend above the map: the heat map (shown with it), the itineraries, the climbs, the take-offs
    // (Sarah, 30 October 2026: one word for the heat, no « few / many », no pilot's climb: they are only drawn on demand)
    const tri = (cls, down) => s('svg', { class: `k-tri ${cls}`, viewBox: '0 0 12 11', 'aria-hidden': 'true' }, s('path', { d: down ? 'M1 1 L11 1 L6 10Z' : 'M6 1 L11 10 L1 10Z' }));
    const legendBox = h('div', { class: 'heat-legend' }, h('i', { class: 'heat-bar' }), t('legend.heat'));
    legendRow.replaceChildren(legendBox,
      h('span', { class: 'key' }, h('i', { class: 'k-route' }), t('legend.route')),
      h('span', { class: 'key' }, h('b', { class: 'k-spot' }), t('legend.takeoff')),
      ffvl.sites.length ? h('span', { class: 'key' }, tri('ffvl'), t('legend.ffvl')) : null,
      ffvl.sites.length ? h('span', { class: 'key' }, tri('ffvl', true), t('legend.ffvlLanding')) : null,
      h('span', { class: 'key' }, h('b', { class: 'k-parking' }, 'P'), t('legend.parking')));
    map.on('overlayadd overlayremove', (e) => { if (e.layer === heat) legendBox.hidden = e.type === 'overlayremove'; });

    map.on('zoomend', () => { pickHeat(); draw(); });
    map.on('moveend', () => { if (!current) renderOverview(); }); // the sectors in view follow the map
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
    // from the home page: a sector is framed; a search shows its results
    const sector = askedQuery.get('sector');
    const inSector = sector ? spots.filter((sp) => sectorOf(sp.lat, sp.lon) === sector) : [];
    if (inSector.length) map.fitBounds(L.latLngBounds(inSector.map((sp) => [sp.lat, sp.lon])), { padding: [60, 60], maxZoom: 13 });
    if (askedQuery.get('q')) { searchBox.value = askedQuery.get('q'); searchBox.focus(); showResults(); }
    if (sector || askedQuery.get('q')) setHash('#/map');
    seasonPick.addEventListener('change', () => { applyFilters(); backgrounds.followSeason(); });
    if (whoPick) whoPick.addEventListener('change', applyFilters);
    // the filters' panel closes on a click elsewhere
    document.addEventListener('click', (ev) => { if (!filtersPop.hidden && !filtersWrap.contains(ev.target)) openFilters(false); });
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
