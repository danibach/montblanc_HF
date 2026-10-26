// The backgrounds of the take-off map (Sarah, 26 October 2026): our own topographic map, in a summer and a winter
// colouring, drawn by MapLibre from OpenFreeMap's vector tiles (OpenStreetMap data, free, no key) with the relief
// and contour lines of Mapterhorn's open terrain (5 m in France, 2 m in Switzerland); and, to pick in the layers
// box, aerial photos (IGN in France, swisstopo in Switzerland), the IGN and swisstopo maps, OpenTopoMap, and two
// overlays: slopes over 30° (IGN) and ski pistes (OpenSnowMap).
// MapLibre is loaded only here, when the map opens. Without WebGL, or if OpenFreeMap does not answer, the map
// keeps OpenTopoMap as before.

import { CONFIG } from './config.js';

const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';
const DEM_URL = 'https://tiles.mapterhorn.com/{z}/{x}/{y}.webp';
const DEM_MAX_ZOOM = 12;
const VENDOR = 'vendor/maplibre/';
const OFM = '<a href="https://openfreemap.org">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/">OpenMapTiles</a>, OSM';
const RELIEF = 'relief <a href="https://mapterhorn.com/attribution">© Mapterhorn</a>';

// Two palettes in the manner of Apple Maps: a warm, light ground with soft greens and a clear blue in summer; snow,
// frosted forests and cold shadows in winter. Roads stay white and quiet; the labels are dark grey.
export const PALETTES = {
  summer: {
    land: '#f6f3ee', park: '#d3ebc2', wood: '#bfe2a8', grass: '#dff0cf', ice: '#f4f9fd', sand: '#f0e7d2',
    residential: '#ebe6dd', water: '#a9d4f2', waterLine: '#8cc3ec', road: '#ffffff', casing: '#ddd5c7',
    major: '#ffe2a6', majorCasing: '#e8c27c', path: '#b09f86', rail: '#c8c2b8', building: '#e4ded3', boundary: '#b8a8c8',
    label: '#3a3a3c', labelSoft: '#6e6e73', halo: 'rgba(255,255,255,0.92)', waterLabel: '#3b7db6',
    shadow: '#4b5160', highlight: '#ffffff', accent: '#8c93a3', exaggeration: 0.3,
    contour: '#c29f78', contourIndex: '#a8835b', contourLabel: '#8f6c47', peak: '#5e4630',
  },
  winter: {
    land: '#f8fbfd', park: '#eaf1f3', wood: '#cfded9', grass: '#f1f6f9', ice: '#ffffff', sand: '#eef1f4',
    residential: '#e6ebf0', water: '#9bc3e2', waterLine: '#86b5da', road: '#ffffff', casing: '#cbd5df',
    major: '#eef3f8', majorCasing: '#b1c0cf', path: '#93a3b4', rail: '#c1cbd5', building: '#dfe5eb', boundary: '#a7b3cf',
    label: '#27374a', labelSoft: '#5b6a7a', halo: 'rgba(255,255,255,0.94)', waterLabel: '#3d70a2',
    shadow: '#7a90aa', highlight: '#ffffff', accent: '#a3b5c9', exaggeration: 0.26,
    contour: '#8fa9c4', contourIndex: '#6f8cab', contourLabel: '#5d7896', peak: '#2f4a68',
  },
};

// contour interval (thin, thick) by zoom, in metres
const CONTOURS = { 11: [200, 1000], 12: [100, 500], 13: [50, 250], 14: [20, 100], 15: [10, 50] };

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`${src} did not load`));
    document.head.append(s);
  });
}

function loadCss(href) {
  if (document.querySelector(`link[href="${href}"]`)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = href;
  document.head.append(l);
}

function webgl() {
  try {
    const c = document.createElement('canvas');
    return Boolean(c.getContext('webgl2') || c.getContext('webgl'));
  } catch (_) {
    return false;
  }
}

let ready = null;
/** MapLibre, its Leaflet bridge and the contour lines, loaded once; rejects without WebGL. */
function loadMaplibre() {
  if (!ready) {
    ready = (async () => {
      if (!webgl()) throw new Error('no WebGL');
      loadCss(`${VENDOR}maplibre-gl.css`);
      await loadScript(`${VENDOR}maplibre-gl-csp.js`);
      // the build without eval or blob workers, for the page's security policy (worker-src 'self')
      window.maplibregl.setWorkerUrl(`${VENDOR}maplibre-gl-csp-worker.js`);
      await loadScript(`${VENDOR}leaflet-maplibre-gl.js`);
      await loadScript(`${VENDOR}maplibre-contour.js`);
      const dem = new window.mlcontour.DemSource({ url: DEM_URL, encoding: 'terrarium', maxzoom: DEM_MAX_ZOOM, worker: false });
      dem.setupMaplibre(window.maplibregl);
      return dem;
    })();
  }
  return ready;
}

/** Set ``prop`` of a layer's paint when the layer draws that kind of thing. */
function paint(layer, prop, value) {
  layer.paint = { ...(layer.paint || {}), [prop]: value };
}

/** OpenFreeMap's Liberty style in our colours, with relief and contour lines. */
export function hfStyle(base, p, dem) {
  const style = JSON.parse(JSON.stringify(base));
  style.layers = style.layers.filter((l) => l.id !== 'natural_earth' && l.id !== 'building-3d');
  delete style.sources.ne2_shaded;
  for (const l of style.layers) {
    const id = l.id;
    if (l.type === 'background') paint(l, 'background-color', p.land);
    else if (l.type === 'fill') {
      const colour = id === 'park' ? p.park : id === 'landcover_wood' ? p.wood
        : /grass|wetland|pitch|track|cemetery/.test(id) ? p.grass : id === 'landcover_ice' ? p.ice
          : id === 'landcover_sand' ? p.sand : id === 'water' ? p.water : id === 'building' ? p.building
            : /residential|hospital|school/.test(id) ? p.residential : /aeroway/.test(id) ? p.casing : null;
      if (colour) paint(l, 'fill-color', colour);
      // Liberty draws forests and meadows at 30-40 %: solid and soft, as on Apple's maps
      const opacity = { landcover_wood: 0.95, landcover_grass: 0.7, park: 0.8, landcover_ice: 1, landuse_residential: 0.75 }[id];
      if (opacity !== undefined) paint(l, 'fill-opacity', opacity);
      if (id === 'park') paint(l, 'fill-outline-color', p.park);
      if (id === 'building') paint(l, 'fill-outline-color', p.casing);
    } else if (l.type === 'line') {
      const colour = /^waterway/.test(id) ? p.waterLine : /^boundary/.test(id) ? p.boundary
        : id === 'park_outline' ? p.park : /rail/.test(id) ? p.rail
          : /path_pedestrian/.test(id) && !/casing/.test(id) ? p.path
            : /casing/.test(id) ? (/motorway|trunk/.test(id) ? p.majorCasing : p.casing)
              : /^(road|bridge|tunnel)_/.test(id) ? (/motorway|trunk/.test(id) ? p.major : p.road)
                : /aeroway/.test(id) ? p.road : null;
      if (colour) paint(l, 'line-color', colour);
    } else if (l.type === 'symbol' && l.layout && l.layout['text-field']) {
      paint(l, 'text-color', /^water/.test(id) ? p.waterLabel : /^poi/.test(id) ? p.labelSoft : p.label);
      paint(l, 'text-halo-color', p.halo);
      paint(l, 'text-halo-width', 1.4);
    }
  }
  style.sources.relief = { type: 'raster-dem', encoding: 'terrarium', tiles: [dem.sharedDemProtocolUrl], tileSize: 512, maxzoom: DEM_MAX_ZOOM };
  style.sources.contours = {
    type: 'vector', maxzoom: 15,
    tiles: [dem.contourProtocolUrl({ thresholds: CONTOURS, elevationKey: 'ele', levelKey: 'level', contourLayer: 'contours' })],
  };
  const font = (style.layers.find((l) => l.layout && l.layout['text-font']) || { layout: { 'text-font': ['Noto Sans Regular'] } }).layout['text-font'];
  const under = (pred) => {
    const i = style.layers.findIndex(pred);
    return i < 0 ? style.layers.length : i;
  };
  // relief and contour lines above the ground and the water, under the roads and the labels
  style.layers.splice(under((l) => /^aeroway|^tunnel_|^road_/.test(l.id)), 0,
    { id: 'relief', type: 'hillshade', source: 'relief', paint: {
      'hillshade-shadow-color': p.shadow, 'hillshade-highlight-color': p.highlight, 'hillshade-accent-color': p.accent,
      'hillshade-exaggeration': p.exaggeration, 'hillshade-illumination-direction': 315 } },
    { id: 'contours', type: 'line', source: 'contours', 'source-layer': 'contours', minzoom: 11,
      filter: ['==', ['get', 'level'], 0],
      paint: { 'line-color': p.contour, 'line-width': 0.7, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 11, 0.45, 14, 0.8] } },
    { id: 'contours-index', type: 'line', source: 'contours', 'source-layer': 'contours', minzoom: 11,
      filter: ['>', ['get', 'level'], 0],
      paint: { 'line-color': p.contourIndex, 'line-width': 1.2, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 11, 0.6, 14, 0.9] } });
  style.layers.splice(under((l) => l.type === 'symbol'), 0,
    { id: 'contour-labels', type: 'symbol', source: 'contours', 'source-layer': 'contours', minzoom: 12,
      filter: ['>', ['get', 'level'], 0],
      layout: { 'symbol-placement': 'line', 'text-field': ['concat', ['number-format', ['get', 'ele'], {}], ' m'], 'text-font': font, 'text-size': 10 },
      paint: { 'text-color': p.contourLabel, 'text-halo-color': p.halo, 'text-halo-width': 1.2 } });
  // summits with their altitude: the first thing a pilot looks for (Liberty shows none)
  style.layers.splice(under((l) => /^label_/.test(l.id)), 0,
    { id: 'peaks', type: 'symbol', source: 'openmaptiles', 'source-layer': 'mountain_peak', minzoom: 10,
      filter: ['all', ['has', 'name'], ['has', 'ele']],
      layout: {
        'text-field': ['format', ['get', 'name'], { 'font-scale': 1 }, '\n', {}, ['concat', ['number-format', ['get', 'ele'], {}], ' m'], { 'font-scale': 0.85 }],
        'text-font': font, 'text-size': ['interpolate', ['linear'], ['zoom'], 10, 10, 14, 12], 'text-anchor': 'top',
        'text-offset': [0, 0.3], 'symbol-sort-key': ['-', ['to-number', ['get', 'ele']]], 'text-max-width': 8,
      },
      paint: { 'text-color': p.peak, 'text-halo-color': p.halo, 'text-halo-width': 1.4 } });
  return style;
}

const ign = (layer, format, extra = {}) => `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}&STYLE=normal&TILEMATRIXSET=PM&FORMAT=${format}&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}${Object.entries(extra).map(([k, v]) => `&${k}=${v}`).join('')}`;
const swiss = (layer) => `https://wmts.geo.admin.ch/1.0.0/${layer}/default/current/3857/{z}/{x}/{y}.jpeg`;
const FRANCE = [[41.3, -5.3], [51.2, 9.7]];
const SWITZERLAND = [[45.81, 5.95], [47.81, 10.5]];

function rasterLayers(L) {
  const topo = () => L.tileLayer(CONFIG.TILES_URL, { subdomains: CONFIG.TILES_SUBDOMAINS, maxZoom: CONFIG.TILES_MAX_ZOOM, attribution: CONFIG.TILES_ATTRIBUTION });
  return {
    // IGN answers a grey « no data » tile outside France: swisstopo's photo (Switzerland and its border, Chamonix
    // included) is laid over it, IGN's shows everywhere else in France
    satellite: L.layerGroup([
      L.tileLayer(ign('ORTHOIMAGERY.ORTHOPHOTOS', 'image/jpeg'), { bounds: FRANCE, maxZoom: 19, attribution: '© IGN' }),
      L.tileLayer(swiss('ch.swisstopo.swissimage'), { bounds: SWITZERLAND, maxZoom: 19, attribution: '© swisstopo' }),
    ]),
    ign: L.tileLayer(ign('GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2', 'image/png'), { bounds: FRANCE, maxZoom: 18, attribution: '© IGN' }),
    swisstopo: L.tileLayer(swiss('ch.swisstopo.pixelkarte-farbe'), { maxZoom: 18, attribution: '© swisstopo' }),
    swissWinter: L.tileLayer(swiss('ch.swisstopo.pixelkarte-farbe-winter'), { maxZoom: 18, attribution: '© swisstopo' }),
    opentopo: topo(),
    slopes: L.tileLayer(ign('GEOGRAPHICALGRIDSYSTEMS.SLOPES.MOUNTAIN', 'image/png'), { bounds: FRANCE, maxZoom: 17, opacity: 0.55, attribution: 'slopes © IGN' }),
    pistes: L.tileLayer('https://tiles.opensnowmap.org/pistes/{z}/{x}/{y}.png', { maxZoom: 18, attribution: 'pistes © OpenSnowMap (CC-BY-SA)' }),
  };
}

const KEY = 'hf-map-base'; // a background chosen by hand among the « More maps » or Satellite (this browser only)
const TERRAIN_KEY = 'hf-map-terrain'; // the terrain overlays switched on
const load = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
const save = (k, v) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (_) { /* private window */ } };

const SVG = 'http://www.w3.org/2000/svg';
/** The « stacked sheets » icon of the Map button, drawn from fixed shapes (no markup from outside). */
function stackIcon() {
  const s = document.createElementNS(SVG, 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('aria-hidden', 'true');
  for (const d of ['M12 4 3 9l9 5 9-5-9-5z', 'M3 13.5l9 5 9-5', 'M3 17.5l9 5 9-5']) {
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', d);
    s.append(path);
  }
  return s;
}

/**
 * The « Map » button and its panel (Sarah, 26 October 2026, after Apple's and Google's maps), in place of Leaflet's
 * layers box: the map style in pictures (Topo, Winter, Satellite), switches for what is shown on the map and for the
 * terrain, and the specialist maps folded under « More maps ». On a phone the panel rises from the bottom.
 * ``overlays``: {label: layer} shown on the map (on at the start). ``winter()``: is the season shown winter?
 * The style follows the season: picking one in the filter sets Topo or Winter, unless Satellite was chosen.
 * Returns {followSeason()} to call when the season filter changes.
 */
export function mapPanel(L, map, overlays, winter) {
  const r = rasterLayers(L);
  const layers = { satellite: r.satellite, ign: r.ign, swisstopo: r.swisstopo, swissWinter: r.swissWinter, opentopo: r.opentopo };
  let current = null;
  let chosen = load(KEY); // satellite, ign… or null: Topo / Winter by the season
  if (chosen && !layers[chosen]) chosen = null;
  let seasonal = winter() ? 'winter' : 'summer';

  const box = L.DomUtil.create('div', 'map-panel');
  box.hidden = true;
  L.DomEvent.disableClickPropagation(box);
  L.DomEvent.disableScrollPropagation(box);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };

  const head = el('div', 'mp-head');
  const close = el('button', 'mp-close', '×');
  close.setAttribute('aria-label', 'Close');
  head.append(el('b', null, 'Map'), close);

  const styles = el('div', 'mp-styles');
  const tile = (key, label) => {
    const b = el('button', `mp-style ${key}`);
    b.type = 'button';
    b.append(el('i', `mp-thumb ${key}`), el('span', null, label));
    b.addEventListener('click', () => {
      if (key === 'satellite') choose('satellite');
      else { seasonal = key === 'winter' ? 'winter' : 'summer'; choose(null); }
    });
    styles.append(b);
    return b;
  };
  const tiles = { summer: tile('summer', 'Topo'), winter: tile('winter', 'Winter'), satellite: tile('satellite', 'Satellite') };
  const seasonNote = el('p', 'mp-note', 'Topo or Winter follows the season you pick.');

  const toggle = (label, on, set) => {
    const row = el('label', 'mp-row');
    const input = el('input');
    input.type = 'checkbox';
    input.setAttribute('role', 'switch');
    input.checked = on;
    input.addEventListener('change', () => set(input.checked));
    row.append(el('span', null, label), input);
    return row;
  };
  const shown = el('div', 'mp-group');
  shown.append(el('p', 'mp-label', 'On the map'));
  for (const [label, layer] of Object.entries(overlays)) {
    shown.append(toggle(label, map.hasLayer(layer), (on) => {
      if (on) map.addLayer(layer); else map.removeLayer(layer);
      map.fire(on ? 'overlayadd' : 'overlayremove', { layer, name: label }); // the heat map legend follows
    }));
  }
  const terrainOn = new Set((load(TERRAIN_KEY) || '').split(',').filter(Boolean));
  const terrain = el('div', 'mp-group');
  terrain.append(el('p', 'mp-label', 'Terrain'));
  for (const [key, label, layer] of [['slopes', 'Slopes over 30° (France)', r.slopes], ['pistes', 'Ski pistes', r.pistes]]) {
    if (terrainOn.has(key)) layer.addTo(map);
    terrain.append(toggle(label, terrainOn.has(key), (on) => {
      if (on) { layer.addTo(map); terrainOn.add(key); } else { map.removeLayer(layer); terrainOn.delete(key); }
      save(TERRAIN_KEY, [...terrainOn].join(',') || null);
    }));
  }

  const more = el('details', 'mp-more');
  more.append(el('summary', null, 'More maps'));
  const moreButtons = {};
  for (const [key, label] of [['ign', 'IGN (France)'], ['swisstopo', 'swisstopo'], ['swissWinter', 'swisstopo winter'], ['opentopo', 'OpenTopoMap']]) {
    const b = el('button', 'mp-chip', label);
    b.type = 'button';
    b.addEventListener('click', () => choose(key));
    more.append(b);
    moreButtons[key] = b;
  }
  box.append(head, styles, seasonNote, shown, terrain, more);
  map.getContainer().append(box);

  // the button, where Leaflet's layers box was
  const button = L.control({ position: 'topright' });
  button.onAdd = () => {
    const b = el('button', 'map-button');
    b.type = 'button';
    b.setAttribute('aria-expanded', 'false');
    b.append(stackIcon(), el('span', null, 'Map'));
    L.DomEvent.disableClickPropagation(b);
    b.addEventListener('click', () => open(box.hidden));
    return b;
  };
  button.addTo(map);
  const open = (yes) => {
    box.hidden = !yes;
    button.getContainer().setAttribute('aria-expanded', String(yes));
  };
  close.addEventListener('click', () => open(false));
  map.on('click', () => open(false));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') open(false); });

  // our own maps once MapLibre and the style are there; OpenTopoMap and swisstopo winter until then (or for good)
  let ours = null;
  const background = () => {
    if (chosen) return layers[chosen];
    if (ours) return ours[seasonal];
    return r.opentopo;
  };
  const render = () => {
    const next = background();
    if (next !== current) {
      if (current) map.removeLayer(current);
      current = next;
      current.addTo(map);
      if (current.bringToBack) current.bringToBack();
    }
    // the site dims the tiles for its dark theme; our own maps are drawn soft already and are not dimmed
    map.getContainer().classList.toggle('hf-base', Boolean(ours) && !chosen);
    tiles.summer.classList.toggle('on', !chosen && seasonal === 'summer');
    tiles.winter.classList.toggle('on', !chosen && seasonal === 'winter');
    tiles.satellite.classList.toggle('on', chosen === 'satellite');
    for (const [key, b] of Object.entries(moreButtons)) b.classList.toggle('on', chosen === key);
    if (chosen && chosen !== 'satellite') more.open = true;
  };
  function choose(key) {
    chosen = key;
    save(KEY, key);
    render();
  }
  render();

  (async () => {
    const dem = await loadMaplibre();
    const res = await fetch(STYLE_URL);
    if (!res.ok) throw new Error(`style ${res.status}`);
    const base = await res.json();
    const make = (palette) => L.maplibreGL({ style: hfStyle(base, palette, dem), attribution: `${OFM} · ${RELIEF}`, interactive: false });
    ours = { summer: make(PALETTES.summer), winter: make(PALETTES.winter) };
    render();
  })().catch(() => { /* no WebGL or no OpenFreeMap: OpenTopoMap stays */ });

  return {
    /** The season filter changed: Topo or Winter with it (only Satellite stays as chosen: it has no winter). */
    followSeason() {
      seasonal = winter() ? 'winter' : 'summer';
      if (chosen && chosen !== 'satellite') { chosen = null; save(KEY, null); }
      render();
    },
  };
}
