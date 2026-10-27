// The scale bar and the ruler of the take-off map (Sarah, 27 October 2026): click points on the map to measure a
// way, its length and, from the ground under it (Mapterhorn, site/basemaps.js), how much it climbs and descends.
// A double click or the button ends the measure; the button again, or Escape, clears it.

import { h, fmtInt, fmtKm } from './util.js';
import { t } from './i18n.js';
import { icon, terrainAltitudes } from './basemaps.js';

const RULER_COLOUR = '#e0161b';
const STEP_M = 25;  // the ground is read every 25 m along the measured line
const NOISE_M = 5;  // climbs and descents under 5 m are terrain noise, not counted
const MAX_TERRAIN_KM = 30; // longer: the length only (the ground would take hundreds of terrain tiles)

function metres(a, b) {
  const r = Math.PI / 180;
  const s = Math.sin(((b[0] - a[0]) * r) / 2) ** 2
    + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(((b[1] - a[1]) * r) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(s));
}

/** Length of ``line`` ([[lat, lon], …]) in metres. */
export function lengthOf(line) {
  let m = 0;
  for (let i = 1; i < line.length; i += 1) m += metres(line[i - 1], line[i]);
  return m;
}

/** ``line`` with a point at least every STEP_M, to read the ground under it. */
export function densify(line, step = STEP_M) {
  const out = line.length ? [line[0]] : [];
  for (let i = 1; i < line.length; i += 1) {
    const [a, b] = [line[i - 1], line[i]];
    const n = Math.max(1, Math.ceil(metres(a, b) / step));
    for (let k = 1; k <= n; k += 1) out.push([a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n]);
  }
  return out;
}

/** Climb and descent (m) of altitudes, counting only moves of more than NOISE_M (hysteresis). */
export function upDown(alts, noise = NOISE_M) {
  let up = 0;
  let down = 0;
  let ref = alts[0];
  for (const a of alts.slice(1)) {
    if (a - ref > noise) { up += a - ref; ref = a; } else if (ref - a > noise) { down += ref - a; ref = a; }
  }
  return { up, down };
}

/** The metric scale bar (bottom left) and the ruler button (top left, under the full screen one). */
export function scaleAndRuler(L, map) {
  // bottom right, above the credits: bottom left holds the heat map's legend
  L.control.scale({ imperial: false, position: 'bottomright', maxWidth: 120 }).addTo(map);

  let on = false;
  let points = [];
  let asked = 0;
  const layer = L.layerGroup().addTo(map);
  const label = h('div', { class: 'ruler-box', role: 'status', hidden: true });
  const button = h('button', { type: 'button', class: 'map-full-button ruler-button' }, icon('ruler', 'mp-full-icon'));

  const show = (text) => { label.hidden = !text; label.textContent = text || ''; };
  const redraw = () => {
    layer.clearLayers();
    if (points.length > 1) {
      L.polyline(points, { color: '#fff', weight: 6, opacity: 0.9, interactive: false }).addTo(layer);
      L.polyline(points, { color: RULER_COLOUR, weight: 3, dashArray: '6 6', interactive: false }).addTo(layer);
    }
    for (const p of points) L.circleMarker(p, { radius: 4, color: '#fff', weight: 2, fillColor: RULER_COLOUR, fillOpacity: 1, interactive: false }).addTo(layer);
  };
  const measure = async () => {
    if (points.length < 2) { show(on ? t('ruler.hint') : ''); return; }
    const m = lengthOf(points);
    const km = fmtKm(m / 1000);
    show(km);
    const mine = ++asked;
    if (m > MAX_TERRAIN_KM * 1000) return;
    const alts = await terrainAltitudes(densify(points));
    if (mine !== asked || !alts) return;
    const { up, down } = upDown(alts);
    show(t('ruler.result', { km, up: fmtInt(up), down: fmtInt(down) }));
  };
  const set = (state) => {
    on = state;
    map.getContainer().classList.toggle('measuring', on);
    button.classList.toggle('on', on);
    button.setAttribute('aria-pressed', String(on));
    button.setAttribute('aria-label', on ? t('ruler.off') : t('ruler.on'));
    button.title = button.getAttribute('aria-label');
    if (on) { points = []; redraw(); }
    if (on) map.doubleClickZoom.disable(); else map.doubleClickZoom.enable();
    measure();
  };
  const clear = () => { points = []; asked += 1; redraw(); show(''); };

  map.on('click', (e) => {
    if (!on) return;
    points.push([e.latlng.lat, e.latlng.lng]);
    redraw();
    measure();
  });
  // a double click ends the measure: the line stays until the button is pressed again
  map.on('dblclick', () => {
    if (!on) return;
    points.pop(); // the double click's second click, on the same spot
    set(false);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && (on || points.length)) { set(false); clear(); } });
  button.addEventListener('click', () => {
    if (on) set(false);
    else if (points.length) clear();
    else set(true);
  });

  const control = L.control({ position: 'topleft' });
  control.onAdd = () => {
    const box = h('div', { class: 'ruler-control' }, button, label);
    L.DomEvent.disableClickPropagation(box);
    return box;
  };
  control.addTo(map);
  set(false);
}
