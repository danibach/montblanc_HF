// The map (Leaflet) and the altitude profile (SVG) of an outing, and the GPX download.

import { CONFIG } from './config.js';
import { h, s, fmtInt } from './util.js';

export const MODE_NAMES = ['On foot', 'Flight', 'Vehicle'];
export const MODE_COLOURS = ['#5fbf68', '#f0693d', '#8796a3'];
const INK = '#e6edf1';
const MUTED = '#9fb0b9';
const GRID = '#2b3b44';

/** Runs of consecutive fixes with the same mode: [{m, from, to}] (indexes into the trace arrays). */
export function runs(trace) {
  const out = [];
  let from = 0;
  for (let i = 1; i <= trace.m.length; i++) {
    if (i === trace.m.length || trace.m[i] !== trace.m[from]) {
      out.push({ m: trace.m[from], from, to: i - 1 });
      from = i;
    }
  }
  return out;
}

// ---------- map

export function buildMap(trace, markers) {
  const box = h('div', { class: 'map', role: 'img', 'aria-label': 'Map of the track' });
  if (!window.L) {
    box.append(h('p', { class: 'hint pad' }, 'The map could not be loaded.'));
    return { element: box, start() {} };
  }
  const L = window.L;
  // Leaflet needs the element in the page before it can measure it: start() is called after insertion.
  const start = () => {
    const map = L.map(box, { scrollWheelZoom: false });
    L.tileLayer(CONFIG.TILES_URL, {
      subdomains: CONFIG.TILES_SUBDOMAINS,
      maxZoom: CONFIG.TILES_MAX_ZOOM,
      attribution: CONFIG.TILES_ATTRIBUTION,
    }).addTo(map);
    const all = [];
    for (const r of runs(trace)) {
      const line = [];
      // overlap by one fix so the parts touch
      for (let i = r.from; i <= Math.min(r.to + 1, trace.m.length - 1); i++) line.push([trace.lat[i], trace.lon[i]]);
      L.polyline(line, { color: MODE_COLOURS[r.m], weight: 4, opacity: 0.9 }).addTo(map);
      all.push(...line);
    }
    for (const mk of markers) {
      if (mk.lat == null) continue;
      const dot = L.circleMarker([mk.lat, mk.lon], {
        radius: 7, color: '#fff', weight: 2, fillColor: mk.colour, fillOpacity: 1,
      }).addTo(map);
      dot.bindTooltip(`${mk.label}${mk.alt != null ? ` · ${fmtInt(mk.alt)} m` : ''}`);
    }
    map.fitBounds(L.latLngBounds(all), { padding: [20, 20] });
    box._map = map;
  };
  return { element: box, start };
}

// ---------- profile

function niceStep(range, target) {
  const raw = range / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
}

export function buildProfile(trace) {
  const W = 800, H = 240, ML = 52, MR = 12, MT = 12, MB = 28;
  const alts = trace.alt.map((a) => (a == null ? null : a));
  const known = alts.filter((a) => a != null);
  const wrap = h('div', { class: 'profile' });
  if (known.length < 2) return wrap.appendChild(h('p', { class: 'hint pad' }, 'No altitude to draw.')) && wrap;
  const T = trace.t[trace.t.length - 1] || 1;
  const step = niceStep(Math.max(...known) - Math.min(...known) || 100, 4);
  const y0 = Math.floor(Math.min(...known) / step) * step;
  const y1 = Math.ceil(Math.max(...known) / step) * step;
  const X = (t) => ML + (t / T) * (W - ML - MR);
  const Y = (a) => MT + (1 - (a - y0) / (y1 - y0 || 1)) * (H - MT - MB);

  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'profile-svg', role: 'img', 'aria-label': 'Altitude profile' });
  for (let a = y0; a <= y1 + 1e-6; a += step) {
    svg.append(s('line', { x1: ML, x2: W - MR, y1: Y(a), y2: Y(a), stroke: GRID, 'stroke-width': 1 }));
    svg.append(s('text', { x: ML - 6, y: Y(a) + 4, 'text-anchor': 'end', fill: MUTED, 'font-size': 11 }, fmtInt(a)));
  }
  const tickStep = niceStep(T / 3600, 5) * 3600;
  const t0 = new Date(trace.t0).getTime();
  for (let t = 0; t <= T; t += tickStep) {
    svg.append(s('line', { x1: X(t), x2: X(t), y1: MT, y2: H - MB, stroke: GRID, 'stroke-width': 1 }));
    svg.append(s('text', { x: X(t), y: H - 8, 'text-anchor': 'middle', fill: MUTED, 'font-size': 11 },
      new Date(t0 + t * 1000).toISOString().slice(11, 16) + ' UTC'));
  }
  for (const r of runs(trace)) {
    const pts = [];
    for (let i = r.from; i <= Math.min(r.to + 1, trace.m.length - 1); i++) {
      if (alts[i] != null) pts.push(`${X(trace.t[i]).toFixed(1)},${Y(alts[i]).toFixed(1)}`);
    }
    if (pts.length > 1) {
      svg.append(s('polyline', { points: pts.join(' '), fill: 'none', stroke: MODE_COLOURS[r.m], 'stroke-width': 2.4, 'stroke-linejoin': 'round' }));
    }
  }
  svg.append(s('text', { x: 4, y: 12, fill: MUTED, 'font-size': 11 }, 'm'));

  const readout = h('p', { class: 'readout hint', role: 'status' }, 'Move over the profile to read a point.');
  const cursor = s('line', { y1: MT, y2: H - MB, stroke: INK, 'stroke-width': 1, 'stroke-dasharray': '3 3', visibility: 'hidden' });
  svg.append(cursor);
  svg.addEventListener('pointermove', (ev) => {
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * W;
    const t = Math.max(0, Math.min(T, ((x - ML) / (W - ML - MR)) * T));
    let best = 0;
    for (let i = 0; i < trace.t.length; i++) if (Math.abs(trace.t[i] - t) < Math.abs(trace.t[best] - t)) best = i;
    cursor.setAttribute('x1', X(trace.t[best]));
    cursor.setAttribute('x2', X(trace.t[best]));
    cursor.setAttribute('visibility', 'visible');
    const clock = new Date(t0 + trace.t[best] * 1000).toISOString().slice(11, 19);
    readout.textContent = `${clock} UTC · ${trace.alt[best] == null ? '–' : fmtInt(trace.alt[best])} m · ${MODE_NAMES[trace.m[best]]}`;
  });
  svg.addEventListener('pointerleave', () => cursor.setAttribute('visibility', 'hidden'));

  wrap.append(svg, readout);
  return wrap;
}

export function legend() {
  return h('p', { class: 'legend' }, MODE_NAMES.map((n, i) =>
    h('span', null, h('i', { class: `m${i}` }), n)));
}

// ---------- GPX

export function trackToGpx(trace, title) {
  const t0 = new Date(trace.t0).getTime();
  const esc = (x) => String(x).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c]);
  const pts = trace.t.map((t, i) => {
    const ele = trace.alt[i] == null ? '' : `<ele>${trace.alt[i]}</ele>`;
    return `<trkpt lat="${trace.lat[i]}" lon="${trace.lon[i]}">${ele}<time>${new Date(t0 + t * 1000).toISOString()}</time></trkpt>`;
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="${esc(CONFIG.SITE_NAME)}" xmlns="http://www.topografix.com/GPX/1/1">` +
    `<trk><name>${esc(title)}</name><trkseg>${pts.join('')}</trkseg></trk></gpx>`;
}

export function downloadText(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
