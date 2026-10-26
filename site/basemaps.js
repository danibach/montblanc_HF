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

const KEY = 'hf-map-base'; // the background a visitor chose by hand (this browser only)
const remembered = () => { try { return localStorage.getItem(KEY); } catch (_) { return null; } };
const remember = (name) => { try { localStorage.setItem(KEY, name); } catch (_) { /* private window */ } };

/**
 * Put the backgrounds on ``map`` and in the layers box ``control``. ``winter()`` says whether the season shown is
 * winter. Returns {followSeason()}: call it when the season filter changes; the background follows the season
 * (summer or winter colouring) until the visitor picks one by hand.
 */
export function installBasemaps(L, map, control, winter) {
  const r = rasterLayers(L);
  const bases = {};
  let current = null;
  // the site dims the map tiles for its dark theme; our own maps are drawn soft already and are not dimmed
  const mark = () => map.getContainer().classList.toggle('hf-base', current === bases['H&F Topo'] || current === bases['H&F Winter']);
  const show = (name) => {
    if (!bases[name] || current === bases[name]) return;
    if (current) map.removeLayer(current);
    current = bases[name];
    current.addTo(map);
    mark();
  };
  // Leaflet says « baselayerchange » also when a background is put on the map here: only a click in the layers
  // box is a choice by hand, kept for the next visits
  let byHand = false;
  control.getContainer().addEventListener('click', () => { byHand = true; setTimeout(() => { byHand = false; }, 0); }, true);
  map.on('baselayerchange', (e) => {
    current = e.layer;
    mark();
    const name = Object.keys(bases).find((k) => bases[k] === e.layer);
    if (name && byHand) remember(name);
  });
  const add = (name, layer) => { bases[name] = layer; control.addBaseLayer(layer, name); };
  const pick = () => {
    const chosen = remembered();
    if (chosen && bases[chosen]) return chosen;
    if (bases['H&F Topo']) return winter() ? 'H&F Winter' : 'H&F Topo';
    return 'OpenTopoMap';
  };

  // the raster backgrounds at once, so the map is never empty
  add('Satellite', r.satellite);
  add('IGN (France)', r.ign);
  add('swisstopo (Switzerland)', r.swisstopo);
  add('swisstopo winter', r.swissWinter);
  add('OpenTopoMap', r.opentopo);
  control.addOverlay(r.slopes, 'Slopes over 30° (France)');
  control.addOverlay(r.pistes, 'Ski pistes');
  show('OpenTopoMap');

  const ours = (async () => {
    const dem = await loadMaplibre();
    const r2 = await fetch(STYLE_URL);
    if (!r2.ok) throw new Error(`style ${r2.status}`);
    const base = await r2.json();
    const make = (palette) => L.maplibreGL({ style: hfStyle(base, palette, dem), attribution: `${OFM} · ${RELIEF}`, interactive: false });
    // first in the box: remove and add the raster ones again after them
    const raster = Object.entries(bases);
    for (const [, layer] of raster) control.removeLayer(layer);
    add('H&F Topo', make(PALETTES.summer));
    add('H&F Winter', make(PALETTES.winter));
    for (const [name, layer] of raster) add(name, layer);
    show(pick());
  })().catch(() => { show(pick()); }); // OpenTopoMap and the others stay

  return {
    followSeason() {
      if (remembered()) return;
      ours.then(() => show(pick()));
    },
  };
}
