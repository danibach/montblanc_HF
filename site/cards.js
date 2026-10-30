// The card of an outing (Sarah, 30 October 2026), on the home page and on All outings: the real map with the real
// track (the climb on foot in full green, the flights in a light orange line), the pilot, the date, the title and
// the numbers. The map is only a picture: a click opens the outing.

import { simpleBackground } from './basemaps.js';
import { h, fmtInt, fmtDate, outingTitle, pilotName } from './util.js';
import { t } from './i18n.js';

// colours of a trace by mode (0 on foot, 1 flight, 2 vehicle: as on an outing's page); a ride is not drawn
const MODE_COLOUR = ['#1f7a4d', '#ff5a1f'];
const MAX_POINTS = 600; // a card's track is drawn from at most this many points
// a map that is only a picture
export const STILL = { zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false,
  keyboard: false, touchZoom: false, tap: false, zoomSnap: 0.25 }; // a quarter zoom step: the track fills its card

/** The parts of a trace in one mode each: [{mode, line}], from at most MAX_POINTS points. */
function tracePieces(trace) {
  const n = trace.lat.length;
  const step = Math.max(1, Math.ceil(n / MAX_POINTS));
  const out = [];
  for (let i = 0; i < n; i += step) {
    const mode = trace.m ? trace.m[i] : 0;
    const p = [trace.lat[i], trace.lon[i]];
    const last = out[out.length - 1];
    if (last && last.mode === mode) last.line.push(p);
    else {
      if (last) last.line.push(p); // the parts touch
      out.push({ mode, line: [p] });
    }
  }
  return out.filter((x) => x.line.length > 1 && MODE_COLOUR[x.mode]);
}

export const nums = (o) => h('span', { class: 'cc-nums' },
  h('span', { class: 'up' }, `+${fmtInt(o.dplus_m)} m`), ' · ', h('span', { class: 'down' }, `−${fmtInt(o.dminus_m)} m`));

export const who = (o) => h('span', { class: 'cc-who' }, pilotName(o.profiles), ' · ', fmtDate(o.outing_date));

/** The box a card's map is drawn in (by drawCardMaps). */
export const cardMap = (o) => h('div', { class: 'cc-map', 'data-outing': o.id, role: 'img', 'aria-label': t('home.trackAria', { title: outingTitle(o) }) });

/** An outing's card; ``extra``: nodes under the title (a badge, a chain of take-offs). */
export function outingCard(o, ...extra) {
  return h('a', { class: 'climb-card', href: `#/outing/${o.id}` },
    cardMap(o),
    h('span', { class: 'cc-body' }, who(o), h('b', { class: 'cc-title' }, outingTitle(o)), extra, nums(o)));
}

/** Draws the map of every card under ``root``, its tracks read once for all (``loadTraces(ids)``: getTraces). */
export function drawCardMaps(root, loadTraces) {
  const L = window.L;
  const boxes = [...root.querySelectorAll('.cc-map')];
  if (!L || !boxes.length || !loadTraces) return;
  const ids = [...new Set(boxes.map((b) => b.dataset.outing))];
  loadTraces(ids).then((rows) => {
    const traces = new Map(rows.map((r) => [r.id, r.trace]));
    for (const box of boxes) {
      const trace = traces.get(box.dataset.outing);
      if (!trace || !trace.lat || !box.isConnected) continue;
      const pieces = tracePieces(trace);
      if (!pieces.length) continue;
      const map = L.map(box, { ...STILL, attributionControl: false });
      simpleBackground(L, map);
      // the climb in full green on a white casing; the flight softer: a plain light orange line
      for (const p of pieces) {
        const flight = p.mode === 1;
        if (!flight) L.polyline(p.line, { color: '#fff', weight: 5, opacity: 0.85, interactive: false }).addTo(map);
        L.polyline(p.line, { color: MODE_COLOUR[p.mode], weight: flight ? 2 : 2.5, opacity: flight ? 0.6 : 1, interactive: false }).addTo(map);
      }
      map.fitBounds(L.latLngBounds(pieces.flatMap((p) => p.line)), { padding: [14, 14] });
    }
  }).catch(() => { /* the cards stay without their map */ });
}
