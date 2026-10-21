// The take-off map: a heat layer, one marker per take-off (grouped when zoomed out), and, for the take-off
// that is clicked, the climbs on foot that reached it and the list of its outings. Flights are never drawn.

import { CONFIG } from './config.js';
import { h, fmtInt, fmtKm, fmtDur, fmtDate, outingTitle } from './util.js';

// Take-offs closer than this are the same spot. Only for this page: nothing is stored.
const SAME_SPOT_M = 150;
// Markers whose centres are closer than this on screen are shown as one group, with the sum of their outings.
const GROUP_PX = 56;
// At most this many tracks are read for one take-off (the most recent ones).
const MAX_TRACES = 60;

// Heat layer: each take-off weighs its number of outings. Below HEAT.maxZoom the weight is halved at each zoom
// level out, while nearby spots add up; minOpacity keeps a lone take-off visible on the world view.
const HEAT = {
  radius: 18, blur: 15, maxZoom: 8, max: 5, minOpacity: 0.35,
  gradient: { 0.4: '#4aa3c8', 0.65: '#5fbf68', 0.85: '#f0c870', 1: '#f0693d' },
};
const CLIMB = { color: '#5fbf68', weight: 3, opacity: 0.55 };
const CLIMB_HOT = { color: '#f0693d', weight: 5, opacity: 1 };
const CLIMB_BACK = { color: '#5fbf68', weight: 2, opacity: 0.18 };

function metres(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * r) / 2) ** 2
    + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(a));
}

/** Outings whose take-offs are within SAME_SPOT_M of each other form one spot: [{lat, lon, alt, name, outings}]. */
export function groupTakeoffs(rows) {
  const spots = [];
  const grid = new Map(); // cells of about 1 km, so each outing is compared with nearby spots only
  const cell = (lat, lon) => `${Math.floor(lat * 100)}:${Math.floor(lon * 100)}`;
  for (const o of rows) {
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
    const alts = sp.outings.map((o) => o.takeoff_alt).filter((a) => a != null);
    sp.alt = alts.length ? alts.reduce((a, b) => a + b, 0) / alts.length : null;
    const names = new Map();
    for (const o of sp.outings) if (o.takeoff_name) names.set(o.takeoff_name, (names.get(o.takeoff_name) || 0) + 1);
    sp.name = [...names.entries()].sort((a, b) => b[1] - a[1]).map((e) => e[0])[0]
      || `Take-off${sp.alt != null ? ` · ${fmtInt(sp.alt)} m` : ''}`;
  }
  return spots;
}

/**
 * The climb on foot that reached the take-off: the run of walking fixes just before the main flight (the one
 * that loses the most height, as for the outing's take-off). Driving, lifts and flights are left out.
 * Returns {line, km, duration_s} or null.
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

/**
 * The page's map and side panel. ``rows`` are the outings of getMapOutings(); ``loadTraces(ids)`` reads tracks.
 * Returns {element, start}: start() is called once the element is in the page.
 */
export function buildExplorer(rows, loadTraces) {
  const mapBox = h('div', { class: 'map map-wide', role: 'region', 'aria-label': 'Map of the take-offs' });
  const side = h('aside', { class: 'side', 'aria-live': 'polite' });
  const element = h('div', { class: 'explorer' }, mapBox, side);
  const L = window.L;
  if (!L || !L.heatLayer) {
    mapBox.append(h('p', { class: 'hint pad' }, 'The map could not be loaded.'));
    return { element, start() {} };
  }
  const spots = groupTakeoffs(rows);
  let map;
  let markers;
  let climbs;
  let current = null; // the spot shown in the panel
  let request = 0; // a slow answer for a spot we already left must not draw over the new one

  function overview() {
    current = null;
    request += 1;
    if (climbs) climbs.clearLayers();
    element.classList.remove('has-spot');
    side.replaceChildren(
      h('h2', null, 'Take-offs'),
      h('p', { class: 'hint' }, `${fmtInt(spots.length)} take-off spot${spots.length === 1 ? '' : 's'}, ${fmtInt(rows.length)} confirmed outing${rows.length === 1 ? '' : 's'}.`),
      h('p', { class: 'hint' }, 'Click a take-off to see the climbs that reached it and its outings. Numbers on the map are outings; zoom in to split a group.'));
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
        mk.bindTooltip(h('span', null, `${sp.name} · ${n} outing${n === 1 ? '' : 's'}`), { direction: 'top', offset: [0, -14] });
        mk.on('click', () => openSpot(sp));
        markers.addLayer(mk);
      } else {
        const lat = group.reduce((a, sp) => a + sp.lat, 0) / group.length;
        const lon = group.reduce((a, sp) => a + sp.lon, 0) / group.length;
        const mk = L.marker([lat, lon], { icon: icon(n, 'group'), title: `${group.length} take-offs` });
        mk.bindTooltip(h('span', null, `${group.length} take-offs · ${n} outings — click to zoom in`), { direction: 'top', offset: [0, -16] });
        mk.on('click', () => map.fitBounds(L.latLngBounds(group.map((sp) => [sp.lat, sp.lon])), { padding: [60, 60], maxZoom: 15 }));
        markers.addLayer(mk);
      }
    }
  }

  async function openSpot(sp) {
    current = sp;
    const mine = ++request;
    climbs.clearLayers();
    element.classList.add('has-spot');
    draw();
    const list = h('ul', { class: 'out-list' });
    const status = h('p', { class: 'hint' }, 'Loading the climbs…');
    side.replaceChildren(
      h('div', { class: 'side-head' },
        h('div', null,
          h('h2', null, sp.name),
          h('p', { class: 'hint' }, `${fmtInt(sp.outings.length)} confirmed outing${sp.outings.length === 1 ? '' : 's'}${sp.alt != null ? ` · take-off at ${fmtInt(sp.alt)} m` : ''}`)),
        h('button', { class: 'link close', 'aria-label': 'Back to all take-offs', onclick: overview }, '×')),
      status, list);
    side.scrollTop = 0;
    map.setView([sp.lat, sp.lon], Math.max(map.getZoom(), 13));

    const recent = sp.outings.slice(0, MAX_TRACES);
    let tracks = [];
    try {
      tracks = await loadTraces(recent.map((o) => o.id));
    } catch (e) {
      if (mine !== request) return;
      status.textContent = `The tracks could not be loaded (${e.message}).`;
    }
    if (mine !== request) return;
    const byId = new Map(tracks.map((t) => [t.id, t]));
    const lines = new Map();
    const bounds = L.latLngBounds([[sp.lat, sp.lon]]);
    let selected = null;
    const restyle = (hot) => {
      for (const [id, line] of lines) {
        const style = id === hot || id === selected ? CLIMB_HOT : selected ? CLIMB_BACK : CLIMB;
        line.setStyle(style);
        if (style === CLIMB_HOT) line.bringToFront();
      }
      for (const li of list.children) li.classList.toggle('on', li.dataset.id === selected);
    };
    const select = (id) => { selected = selected === id ? null : id; restyle(null); };

    for (const o of recent) {
      const t = byId.get(o.id);
      const climb = t ? climbOf({ ...o, ...t }) : null;
      if (climb) {
        const line = L.polyline(climb.line, CLIMB).addTo(climbs);
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
      const li = h('li', { 'data-id': o.id, tabindex: '0' },
        h('b', null, outingTitle(o)),
        h('span', { class: 'hint' }, `${o.pilot || 'Anonymous'} · ${fmtDate(o.outing_date)}`),
        h('span', null, `From ${o.start_place || 'the valley'} to ${sp.name}`),
        h('span', { class: 'nums' },
          h('span', { title: 'D+ on foot (engine)' }, `↗ ${fmtInt(o.dplus_m)} m`),
          h('span', { title: 'Distance of the climb' }, climb ? fmtKm(climb.km) : fmtKm(o.walk_km)),
          h('span', { title: 'Time of the climb' }, climb ? `⏱ ${fmtDur(climb.duration_s)}` : '')),
        climb ? null : h('span', { class: 'hint' }, 'No climb track to draw.'),
        h('a', { href: `#/outing/${o.id}` }, 'Open the outing →'));
      li.addEventListener('mouseenter', () => restyle(o.id));
      li.addEventListener('mouseleave', () => restyle(null));
      li.addEventListener('focus', () => restyle(o.id));
      li.addEventListener('click', (ev) => { if (!ev.target.closest('a')) select(o.id); });
      li.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && ev.target === li) select(o.id); });
      list.append(li);
    }
    status.textContent = sp.outings.length > MAX_TRACES
      ? `The ${MAX_TRACES} most recent outings. Hover one to light its climb; click it to keep it lit.`
      : 'Hover an outing to light its climb; click it to keep it lit.';
    if (lines.size) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
  }

  const start = () => {
    map = L.map(mapBox, { worldCopyJump: true });
    L.tileLayer(CONFIG.TILES_URL, {
      subdomains: CONFIG.TILES_SUBDOMAINS,
      maxZoom: CONFIG.TILES_MAX_ZOOM,
      attribution: CONFIG.TILES_ATTRIBUTION,
    }).addTo(map);
    const heat = L.heatLayer(spots.map((sp) => [sp.lat, sp.lon, sp.outings.length]), HEAT).addTo(map);
    climbs = L.featureGroup().addTo(map);
    markers = L.layerGroup().addTo(map);
    L.control.layers(null, { 'Heat map': heat, 'Take-offs': markers }, { collapsed: false }).addTo(map);
    map.on('zoomend', draw);
    if (spots.length) map.fitBounds(L.latLngBounds(spots.map((sp) => [sp.lat, sp.lon])), { padding: [40, 40], maxZoom: 11 });
    else map.setView([45.92, 6.87], 9); // Mont Blanc, until the first outing is confirmed
    mapBox._map = map;
    overview();
  };
  return { element, start };
}
