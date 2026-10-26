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
    land: '#f6f3ee', park: '#d3ebc2', wood: '#bfe2a8', grass: '#dff0cf', ice: '#eef7fc', sand: '#f0e7d2',
    rock: '#e2ddd5', scree: '#ebe7e0', iceLine: '#b5d5ea', trail: '#c4692f',
    residential: '#ebe6dd', water: '#a9d4f2', waterLine: '#8cc3ec', road: '#ffffff', casing: '#ddd5c7',
    major: '#ffe2a6', majorCasing: '#e8c27c', path: '#b09f86', rail: '#c8c2b8', building: '#e4ded3', boundary: '#b8a8c8',
    label: '#3a3a3c', labelSoft: '#6e6e73', halo: 'rgba(255,255,255,0.92)', waterLabel: '#3b7db6',
    shadow: '#4b5160', highlight: '#ffffff', accent: '#8c93a3', exaggeration: 0.3,
    contour: '#c29f78', contourIndex: '#a8835b', contourLabel: '#8f6c47', peak: '#5e4630', pass: '#7b6a58',
  },
  winter: {
    land: '#f8fbfd', park: '#eaf1f3', wood: '#cfded9', grass: '#f1f6f9', ice: '#ffffff', sand: '#eef1f4',
    rock: '#dde4eb', scree: '#e7ecf1', iceLine: '#a6c4dd', trail: '#a0603a',
    residential: '#e6ebf0', water: '#9bc3e2', waterLine: '#86b5da', road: '#ffffff', casing: '#cbd5df',
    major: '#eef3f8', majorCasing: '#b1c0cf', path: '#93a3b4', rail: '#c1cbd5', building: '#dfe5eb', boundary: '#a7b3cf',
    label: '#27374a', labelSoft: '#5b6a7a', halo: 'rgba(255,255,255,0.94)', waterLabel: '#3d70a2',
    shadow: '#7a90aa', highlight: '#ffffff', accent: '#a3b5c9', exaggeration: 0.26,
    contour: '#8fa9c4', contourIndex: '#6f8cab', contourLabel: '#5d7896', peak: '#2f4a68', pass: '#55708e',
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

let baseStyle = null;
/** OpenFreeMap's Liberty style, read once. */
async function libertyStyle() {
  if (!baseStyle) {
    const res = await fetch(STYLE_URL);
    if (!res.ok) throw new Error(`style ${res.status}`);
    baseStyle = await res.json();
  }
  return baseStyle;
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
      // the trails: what a pilot follows on foot, so drawn clearly from a valley's zoom on
      if (/path_pedestrian/.test(id) && !/casing/.test(id)) {
        l.minzoom = Math.min(l.minzoom ?? 12, 12);
        paint(l, 'line-dasharray', [2, 1.2]);
        paint(l, 'line-width', ['interpolate', ['linear'], ['zoom'], 12, 0.8, 14, 1.4, 17, 2.6]);
      }
      const colour = /path_pedestrian/.test(id) && !/casing/.test(id) ? p.trail : /^waterway/.test(id) ? p.waterLine : /^boundary/.test(id) ? p.boundary
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
  const under = (pred) => {
    const i = style.layers.findIndex(pred);
    return i < 0 ? style.layers.length : i;
  };
  // rock, scree and glaciers, which Liberty does not draw: above the forests the mountain was plain beige
  style.layers.splice(under((l) => l.id === 'landcover_ice') + 1, 0,
    { id: 'landcover_rock', type: 'fill', source: 'openmaptiles', 'source-layer': 'landcover',
      filter: ['==', ['get', 'class'], 'rock'],
      paint: { 'fill-color': ['match', ['get', 'subclass'], 'scree', p.scree, p.rock], 'fill-opacity': 0.95, 'fill-antialias': false } },
    { id: 'landcover_ice_edge', type: 'line', source: 'openmaptiles', 'source-layer': 'landcover', minzoom: 10,
      filter: ['==', ['get', 'class'], 'ice'],
      paint: { 'line-color': p.iceLine, 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.5, 15, 1.2] } });
  style.sources.relief = { type: 'raster-dem', encoding: 'terrarium', tiles: [dem.sharedDemProtocolUrl], tileSize: 512, maxzoom: DEM_MAX_ZOOM };
  style.sources.contours = {
    type: 'vector', maxzoom: 15,
    tiles: [dem.contourProtocolUrl({ thresholds: CONTOURS, elevationKey: 'ele', levelKey: 'level', contourLayer: 'contours' })],
  };
  const font = (style.layers.find((l) => l.layout && l.layout['text-font']) || { layout: { 'text-font': ['Noto Sans Regular'] } }).layout['text-font'];
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
      filter: ['all', ['has', 'name'], ['has', 'ele'], ['!=', ['get', 'class'], 'saddle']],
      layout: {
        'text-field': ['format', ['get', 'name'], { 'font-scale': 1 }, '\n', {}, ['concat', ['number-format', ['get', 'ele'], {}], ' m'], { 'font-scale': 0.85 }],
        'text-font': font, 'text-size': ['interpolate', ['linear'], ['zoom'], 10, 10, 14, 12], 'text-anchor': 'top',
        'text-offset': [0, 0.3], 'symbol-sort-key': ['-', ['to-number', ['get', 'ele']]], 'text-max-width': 8,
      },
      paint: { 'text-color': p.peak, 'text-halo-color': p.halo, 'text-halo-width': 1.4 } },
    // the passes (cols), lighter than the summits
    { id: 'passes', type: 'symbol', source: 'openmaptiles', 'source-layer': 'mountain_peak', minzoom: 11,
      filter: ['all', ['has', 'name'], ['==', ['get', 'class'], 'saddle']],
      layout: {
        'text-field': ['case', ['has', 'ele'], ['format', ['get', 'name'], {}, '\n', {}, ['concat', ['number-format', ['get', 'ele'], {}], ' m'], { 'font-scale': 0.85 }], ['get', 'name']],
        'text-font': font, 'text-size': ['interpolate', ['linear'], ['zoom'], 11, 9.5, 14, 11.5], 'text-max-width': 8,
      },
      paint: { 'text-color': p.pass, 'text-halo-color': p.halo, 'text-halo-width': 1.4 } });
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
    slopes: L.tileLayer(ign('GEOGRAPHICALGRIDSYSTEMS.SLOPES.MOUNTAIN', 'image/png'), { bounds: FRANCE, maxZoom: 17, opacity: 0.55, pane: 'hf-slopes', attribution: 'slopes © IGN' }),
    pistes: L.tileLayer('https://tiles.opensnowmap.org/pistes/{z}/{x}/{y}.png', { maxZoom: 18, pane: 'hf-pistes', attribution: 'pistes © OpenSnowMap (CC-BY-SA)' }),
  };
}

const KEY = 'hf-map-base'; // a background chosen by hand among the « More maps » or Satellite (this browser only)
const TERRAIN_KEY = 'hf-map-terrain'; // the terrain overlays switched on
const POI_KEY = 'hf-map-poi'; // summits, passes, airports: shown or not
const ORDER_KEY = 'hf-map-order'; // the order of the layers, top first
const load = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
const save = (k, v) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (_) { /* private window */ } };

const SVG = 'http://www.w3.org/2000/svg';
// line icons of the panel, drawn from fixed shapes (no markup from outside)
const ICONS = {
  stack: ['M12 4 3 9l9 5 9-5-9-5z', 'M3 13.5l9 5 9-5', 'M3 17.5l9 5 9-5'],
  takeoff: ['M12 5l7 13H5z'],
  ffvl: ['M7 4l5 8H2z', 'M17 20l5-8H12z'],
  summit: ['M3 19l6-10 3.5 5L15 11l6 8z'],
  pass: ['M3 8c4 0 5 7 9 7s5-7 9-7', 'M3 19h18'],
  airport: ['M10.5 4.5v5L3 14v2l7.5-2.5V18L8.5 19.5V21l3.5-1 3.5 1v-1.5L13.5 18v-4.5L21 16v-2l-7.5-4.5v-5a1.5 1.5 0 0 0-3 0z'],
  heat: ['M12 3c.5 3 4.5 5 4.5 10a4.5 4.5 0 0 1-9 0c0-2.5 1.5-3.5 2-6 1.5 1.2 2.5 3 2.5 5'],
  slopes: ['M3 20h18', 'M3 20 19 6', 'M14 20a7 7 0 0 0-2-5'],
  pistes: ['M4 19 20 13', 'M6 9l5 3 2 4', 'M9 6.5a1.5 1.5 0 1 0 0-.1'],
  grip: ['M9 6h.01', 'M15 6h.01', 'M9 12h.01', 'M15 12h.01', 'M9 18h.01', 'M15 18h.01'],
};
function icon(name, cls = 'mp-icon') {
  const s = document.createElementNS(SVG, 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('aria-hidden', 'true');
  s.setAttribute('class', `${cls} ${name}`);
  for (const d of ICONS[name]) {
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', d);
    s.append(path);
  }
  return s;
}
const stackIcon = () => icon('stack', 'mp-button-icon');

/**
 * The « Map » button and its panel (Sarah, 26 October 2026, after Apple's and Google's maps), in place of Leaflet's
 * layers box: the map style in pictures (Topo, Winter, Satellite); the points of interest (take-offs, FFVL sites,
 * summits, passes, airports); the layers (heat map, slopes, ski pistes), which can be put in any order by dragging
 * them, as in Notion (top over the others); the specialist maps folded under « More maps ». On a phone the panel
 * rises from the bottom. ``shown``: {takeoffs, heat, ffvl} layers of the page (on at the start; ffvl may be null).
 * ``winter()``: is the season shown winter?
 * The style follows the season: picking one in the filter sets Topo or Winter, unless Satellite was chosen.
 * Returns {followSeason()} to call when the season filter changes.
 */
export function mapPanel(L, map, shown, winter) {
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

  const toggle = (name, label, on, set) => {
    const row = el('label', 'mp-row');
    const input = el('input');
    input.type = 'checkbox';
    input.setAttribute('role', 'switch');
    input.checked = on;
    input.addEventListener('change', () => set(input.checked));
    const text = el('span', 'mp-text');
    text.append(icon(name), el('span', null, label));
    row.append(text, input);
    return row;
  };
  const addOrRemove = (layer, on) => { if (on) map.addLayer(layer); else map.removeLayer(layer); };

  // points of interest: our take-offs and the FFVL sites (layers of the page), summits, passes and airports (in our
  // own map's style: shown or hidden in it)
  let poi = { summits: true, passes: true, airports: false };
  try { poi = { ...poi, ...JSON.parse(load(POI_KEY) || '{}') }; } catch (_) { /* kept as is */ }
  const STYLE_LAYERS = { summits: ['peaks'], passes: ['passes'], airports: ['airport'] };
  let ours = null;
  const applyPoi = () => {
    for (const layer of ours ? Object.values(ours) : []) {
      for (const [key, ids] of Object.entries(STYLE_LAYERS)) {
        for (const l of layer.options.style.layers) if (ids.includes(l.id)) l.layout = { ...(l.layout || {}), visibility: poi[key] ? 'visible' : 'none' };
        const gl = layer.getMaplibreMap && layer.getMaplibreMap();
        if (gl && gl.isStyleLoaded()) for (const id of ids) if (gl.getLayer(id)) gl.setLayoutProperty(id, 'visibility', poi[key] ? 'visible' : 'none');
      }
    }
  };
  const points = el('div', 'mp-group');
  points.append(el('p', 'mp-label', 'Points of interest'));
  points.append(toggle('takeoff', 'Take-offs', map.hasLayer(shown.takeoffs), (on) => addOrRemove(shown.takeoffs, on)));
  if (shown.ffvl) points.append(toggle('ffvl', 'FFVL sites', map.hasLayer(shown.ffvl), (on) => addOrRemove(shown.ffvl, on)));
  for (const [key, label] of [['summits', 'Summits'], ['passes', 'Passes'], ['airports', 'Airports']]) {
    points.append(toggle({ summits: 'summit', passes: 'pass', airports: 'airport' }[key], label, poi[key], (on) => {
      poi[key] = on;
      save(POI_KEY, JSON.stringify(poi));
      applyPoi();
    }));
  }

  // the layers, in an order of one's own: each in a pane of its own between the map and the routes
  const terrainOn = new Set((load(TERRAIN_KEY) || '').split(',').filter(Boolean));
  const LAYERS = {
    heat: { label: 'Heat map', layer: shown.heat },
    slopes: { label: 'Slopes over 30° (France)', layer: r.slopes, terrain: true },
    pistes: { label: 'Ski pistes', layer: r.pistes, terrain: true },
  };
  for (const key of Object.keys(LAYERS)) map.createPane(`hf-${key}`).style.pointerEvents = 'none';
  // Leaflet.heat draws in the overlay pane: its canvas is moved into the heat map's pane, each time it is added; it
  // takes it out of the overlay pane when removed, so the canvas goes back there just before
  if (L.HeatLayer && !L.HeatLayer.prototype._paneSafe) {
    const off = L.HeatLayer.prototype.onRemove;
    L.HeatLayer.prototype.onRemove = function onRemove(m) {
      const overlayPane = m.getPanes().overlayPane;
      if (this._canvas && this._canvas.parentNode !== overlayPane) overlayPane.append(this._canvas);
      return off.call(this, m);
    };
    L.HeatLayer.prototype._paneSafe = true;
  }
  const moveHeat = (layer) => { if (layer._canvas && layer instanceof L.HeatLayer) map.getPane('hf-heat').append(layer._canvas); };
  map.on('layeradd', (e) => moveHeat(e.layer));
  map.eachLayer(moveHeat);
  let order = (load(ORDER_KEY) || '').split(',').filter((k) => LAYERS[k]);
  for (const k of Object.keys(LAYERS)) if (!order.includes(k)) order.push(k);
  const stackPanes = () => order.forEach((k, i) => { map.getPane(`hf-${k}`).style.zIndex = String(395 - i * 5); });
  stackPanes();
  const stacked = el('div', 'mp-group');
  stacked.append(el('p', 'mp-label', 'Layers · drag to put one over another'));
  const list = el('div', 'mp-stack');
  const reorder = () => {
    order = [...list.children].map((row) => row.dataset.key);
    save(ORDER_KEY, order.join(','));
    stackPanes();
  };
  for (const key of order) {
    const { label, layer, terrain } = LAYERS[key];
    if (terrain && terrainOn.has(key)) layer.addTo(map);
    const row = toggle(key, label, terrain ? terrainOn.has(key) : map.hasLayer(layer), (on) => {
      addOrRemove(layer, on);
      if (terrain) {
        if (on) terrainOn.add(key); else terrainOn.delete(key);
        save(TERRAIN_KEY, [...terrainOn].join(',') || null);
      } else map.fire(on ? 'overlayadd' : 'overlayremove', { layer, name: label }); // the heat map legend follows
    });
    row.dataset.key = key;
    // the grip: dragged with a mouse or a finger, or moved with the arrow keys
    const grip = el('button', 'mp-grip');
    grip.type = 'button';
    grip.setAttribute('aria-label', `Move ${label} up or down`);
    grip.append(icon('grip', 'mp-grip-icon'));
    grip.addEventListener('click', (e) => e.preventDefault()); // a click on the grip does not flip the switch
    grip.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowUp' && row.previousElementSibling) list.insertBefore(row, row.previousElementSibling);
      else if (e.key === 'ArrowDown' && row.nextElementSibling) list.insertBefore(row.nextElementSibling, row);
      else return;
      e.preventDefault();
      grip.focus();
      reorder();
    });
    // moving the row in the page would drop a pointer captured by the grip: the page listens instead
    grip.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      row.classList.add('dragging');
      const move = (ev) => {
        const below = [...list.children].find((o) => o !== row && ev.clientY < o.getBoundingClientRect().top + o.offsetHeight / 2);
        if (below) { if (row.nextElementSibling !== below) list.insertBefore(row, below); } else if (list.lastElementChild !== row) list.append(row);
      };
      const up = () => {
        row.classList.remove('dragging');
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        reorder();
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', up);
    });
    row.prepend(grip);
    list.append(row);
  }
  stacked.append(list);

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
  box.append(head, styles, seasonNote, points, stacked, more);
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

  // our own maps once MapLibre and the style are there; OpenTopoMap until then (or for good)
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
    const base = await libertyStyle();
    const make = (palette) => L.maplibreGL({ style: hfStyle(base, palette, dem), attribution: `${OFM} · ${RELIEF}`, interactive: false });
    ours = { summer: make(PALETTES.summer), winter: make(PALETTES.winter) };
    for (const layer of Object.values(ours)) layer.on('add', () => { const gl = layer.getMaplibreMap(); if (gl) gl.once('styledata', applyPoi); });
    applyPoi();
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

/** Whether this browser can draw the 3D view (WebGL). */
export const can3D = () => webgl();

function bearing(a, b) {
  const r = Math.PI / 180;
  const y = Math.sin((b[1] - a[1]) * r) * Math.cos(b[0] * r);
  const x = Math.cos(a[0] * r) * Math.sin(b[0] * r) - Math.sin(a[0] * r) * Math.cos(b[0] * r) * Math.cos((b[1] - a[1]) * r);
  return (Math.atan2(y, x) / r + 360) % 360;
}

/**
 * The way up on the relief in 3D (Sarah, 26 October 2026, after FATMAP and Strava's flyover), in a window over the
 * page: ``line`` [[lat, lon], …] from the start to the take-off, ``title``, ``winter`` for the winter colouring.
 * « Fly over » follows the way up from the start to the take-off; the view can be turned and tilted by hand.
 */
export async function view3D({ line, title, winter }) {
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
  const shade = el('div', 'view3d');
  const win = el('div', 'v3-box');
  win.setAttribute('role', 'dialog');
  win.setAttribute('aria-modal', 'true');
  win.setAttribute('aria-label', `${title} in 3D`);
  const fly = el('button', 'primary', 'Fly over');
  const shut = el('button', 'v3-close', '×');
  shut.setAttribute('aria-label', 'Close the 3D view');
  const box = el('div', 'v3-map');
  const status = el('p', 'hint v3-status', 'Loading the relief…');
  const head = el('div', 'v3-head');
  head.append(el('b', null, title), el('span', 'v3-tools'));
  head.lastChild.append(fly, shut);
  win.append(head, box, status);
  shade.append(win);
  document.body.append(shade);

  let map = null;
  let frame = 0;
  const stop = () => { cancelAnimationFrame(frame); frame = 0; fly.textContent = 'Fly over'; };
  const close = () => {
    stop();
    if (map) map.remove();
    shade.remove();
    document.removeEventListener('keydown', onKey);
  };
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);
  shut.addEventListener('click', close);
  shade.addEventListener('click', (e) => { if (e.target === shade) close(); });

  try {
    const dem = await loadMaplibre();
    const style = hfStyle(await libertyStyle(), winter ? PALETTES.winter : PALETTES.summer, dem);
    // the terrain read straight from Mapterhorn (MapLibre decodes the heights itself)
    style.sources.terrain = { type: 'raster-dem', encoding: 'terrarium', tiles: [DEM_URL], tileSize: 512, maxzoom: DEM_MAX_ZOOM };
    style.terrain = { source: 'terrain', exaggeration: 1.3 };
    style.sources.way = { type: 'geojson', data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: line.map(([la, lo]) => [lo, la]) } } };
    const round = { 'line-cap': 'round', 'line-join': 'round' };
    style.layers.push(
      { id: 'way-casing', type: 'line', source: 'way', layout: round, paint: { 'line-color': '#ffffff', 'line-width': 8, 'line-opacity': 0.9 } },
      { id: 'way', type: 'line', source: 'way', layout: round, paint: { 'line-color': '#f0693d', 'line-width': 4.5 } });
    const ml = window.maplibregl;
    const start = line[0];
    const top = line[line.length - 1];
    const look = bearing(start, top); // from the start, looking up the way
    const middle = line[Math.floor(line.length / 2)];
    map = new ml.Map({ container: box, style, center: [middle[1], middle[0]], zoom: 13, pitch: 62, bearing: look, maxPitch: 80, attributionControl: false });
    // OpenFreeMap's credit comes with its style; the relief's is added
    map.addControl(new ml.AttributionControl({ compact: true, customAttribution: RELIEF }));
    map.addControl(new ml.NavigationControl({ visualizePitch: true }), 'top-right');
    new ml.Marker({ color: '#f0693d' }).setLngLat([top[1], top[0]]).addTo(map);
    const bounds = line.reduce((b, [la, lo]) => b.extend([lo, la]), new ml.LngLatBounds([start[1], start[0]], [start[1], start[0]]));
    // fitBounds does not fit a tilted view: the camera is found flat, then tilted (a little farther out)
    const overview = (duration) => {
      const cam = map.cameraForBounds(bounds, { padding: 60, maxZoom: 15 });
      if (cam) map.easeTo({ center: cam.center, zoom: cam.zoom - 0.4, pitch: 62, bearing: look, duration });
    };
    map.on('load', () => { overview(0); status.textContent = 'Drag to move, right-click or two fingers to turn and tilt.'; });

    // the flyover: the camera follows the way up, looking a little ahead
    const dist = [0];
    for (let i = 1; i < line.length; i += 1) dist.push(dist[i - 1] + Math.hypot(line[i][0] - line[i - 1][0], (line[i][1] - line[i - 1][1]) * Math.cos(line[i][0] * Math.PI / 180)));
    const total = dist[dist.length - 1] || 1;
    const at = (f) => {
      const d = Math.min(Math.max(f, 0), 1) * total;
      let i = dist.findIndex((x) => x >= d);
      if (i <= 0) return line[0];
      const k = (d - dist[i - 1]) / ((dist[i] - dist[i - 1]) || 1);
      return [line[i - 1][0] + k * (line[i][0] - line[i - 1][0]), line[i - 1][1] + k * (line[i][1] - line[i - 1][1])];
    };
    const km = total * 111;
    const ms = Math.min(40000, Math.max(12000, km * 3500));
    fly.addEventListener('click', () => {
      if (frame) { stop(); return; }
      fly.textContent = 'Pause';
      let t0 = null;
      let heading = map.getBearing();
      const step = (now) => {
        if (t0 === null) t0 = now;
        const f = (now - t0) / ms;
        if (f >= 1) { stop(); overview(2500); return; }
        const here = at(f);
        const ahead = at(f + 0.06);
        const want = bearing(here, ahead);
        const turn = ((want - heading + 540) % 360) - 180; // the shorter way round, smoothed
        heading = (heading + turn * 0.04 + 360) % 360;
        map.jumpTo({ center: [here[1], here[0]], bearing: heading, pitch: 66, zoom: 14.6 });
        frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    });
  } catch (e) {
    status.textContent = 'The 3D view needs a recent browser with WebGL, and the map service to answer.';
    fly.hidden = true;
  }
}
