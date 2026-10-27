// The tool to mark flights by hand on the map, for a track the analysis found no flight in.
// Click the take-off on the track, then the landing: that stretch is a flight. Several flights can be marked.

import { h, fmtInt } from './util.js';
import { t } from './i18n.js';
import { MODE_COLOURS, runs } from './charts.js';
import { fullScreenButton, inWinter, simpleBackground } from './basemaps.js';

const PICK_PX = 40;          // a click this close to the track (in pixels) picks its nearest fix
const MARK_COLOUR = '#4aa3c8';

/** Marks as sorted, non-overlapping [a, b] pairs of trace indexes. */
export function mergeMarks(marks) {
  const sorted = marks.map((m) => ({ a: Math.min(m.a, m.b), b: Math.max(m.a, m.b) })).sort((x, y) => x.a - y.a);
  const out = [];
  for (const m of sorted) {
    const last = out[out.length - 1];
    if (last && m.a <= last.b) last.b = Math.max(last.b, m.b);
    else out.push({ ...m });
  }
  return out;
}

/**
 * Returns {element, start, ranges()}. `start()` is called once the element is in the page.
 * `onChange(count)` is called whenever the marked flights change.
 */
export function buildMarkTool(trace, onChange) {
  const box = h('div', { class: 'map map-tall', role: 'application', 'aria-label': t('mark.mapAria') });
  const status = h('p', { class: 'hint', role: 'status' }, t('mark.clickTakeoff'));
  const list = h('ul', { class: 'mark-list' });
  const element = h('div', null, status, box, list);
  let marks = [];
  let pending = null;
  let map = null;
  let layer = null;

  const alt = (i) => (trace.alt[i] == null ? '–' : `${fmtInt(trace.alt[i])} m`);

  const renderList = () => {
    list.replaceChildren(...marks.map((m, k) => {
      const minutes = Math.max(1, Math.round((trace.t[m.b] - trace.t[m.a]) / 60));
      return h('li', null,
        h('span', null, h('b', null, t('mark.flightN', { n: k + 1 })), ` · ${alt(m.a)} → ${alt(m.b)} · ${minutes} min`),
        h('button', { type: 'button', class: 'link', onclick: () => { marks.splice(k, 1); redraw(); } }, t('mark.remove')));
    }));
  };

  const redraw = () => {
    if (layer) {
      layer.clearLayers();
      for (const m of marks) {
        const line = [];
        for (let i = m.a; i <= m.b; i++) line.push([trace.lat[i], trace.lon[i]]);
        window.L.polyline(line, { color: MARK_COLOUR, weight: 5, opacity: 0.85 }).addTo(layer);
      }
      if (pending != null) {
        window.L.circleMarker([trace.lat[pending], trace.lon[pending]], { radius: 8, color: '#fff', weight: 2, fillColor: MARK_COLOUR, fillOpacity: 1 }).addTo(layer);
      }
    }
    status.textContent = pending != null
      ? t('mark.pending', { alt: alt(pending) })
      : (marks.length ? t('mark.another') : t('mark.clickTakeoff'));
    renderList();
    onChange(marks.length);
  };

  const nearest = (latlng) => {
    const p = map.latLngToContainerPoint(latlng);
    let best = -1;
    let bestD = Infinity;
    for (let i = 0; i < trace.lat.length; i++) {
      const q = map.latLngToContainerPoint([trace.lat[i], trace.lon[i]]);
      const d = Math.hypot(q.x - p.x, q.y - p.y);
      if (d < bestD) { bestD = d; best = i; }
    }
    return bestD <= PICK_PX ? best : -1;
  };

  const onClick = (ev) => {
    const i = nearest(ev.latlng);
    if (i < 0) { status.textContent = t('mark.closer'); return; }
    if (pending == null) { pending = i; redraw(); return; }
    if (i === pending) { pending = null; redraw(); return; }  // the same point again: cancel
    marks = mergeMarks([...marks, { a: pending, b: i }]);
    pending = null;
    redraw();
  };

  const start = () => {
    if (!window.L) { box.append(h('p', { class: 'hint pad' }, t('map.failed'))); return; }
    const L = window.L;
    map = L.map(box);
    simpleBackground(L, map, inWinter(trace.t0)); // the site's own map (site/basemaps.js)
    fullScreenButton(L, map);
    const all = [];
    for (const r of runs(trace)) {
      const line = [];
      for (let i = r.from; i <= Math.min(r.to + 1, trace.m.length - 1); i++) line.push([trace.lat[i], trace.lon[i]]);
      L.polyline(line, { color: MODE_COLOURS[r.m], weight: 2, opacity: 0.95, interactive: false }).addTo(map);
      all.push(...line);
    }
    layer = L.layerGroup().addTo(map);
    map.fitBounds(L.latLngBounds(all), { padding: [20, 20] });
    map.on('click', onClick);
    box._map = map;
    redraw();
  };

  return {
    element,
    start,
    /** The marked flights as [from, to] in seconds after the trace's t0. */
    ranges: () => marks.map((m) => [trace.t[m.a], trace.t[m.b]]),
  };
}
