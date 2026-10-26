// The sheet of one way up to a take-off (Sarah, 25 October 2026, after Komoot): its numbers from the climbs of its
// outings (distance, D+, time: the median, and how long most pilots take), the altitude profile of its middle line
// and the line itself as a GPX file, to follow it on a watch or a phone.
// The profile asks Open-Meteo for the ground altitude under the line (the page already uses it for the uploads); the
// sheet shows without it when the service cannot be reached.

import { CONFIG } from './config.js';
import { h, fmtInt, fmtKm, fmtDur } from './util.js';

const SVG = 'http://www.w3.org/2000/svg';
const MAX_COORDINATES = 100; // the service takes at most 100 per request

function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const c of children) node.append(c);
  return node;
}

function metres(a, b) {
  const r = Math.PI / 180;
  const s = Math.sin(((b[0] - a[0]) * r) / 2) ** 2
    + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(((b[1] - a[1]) * r) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(s));
}

/** The value at fraction ``q`` of the sorted values (0.5: the median), or null. */
export function quantile(values, q) {
  const v = values.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  return v[Math.min(v.length - 1, Math.max(0, Math.round((v.length - 1) * q)))];
}

/**
 * The numbers of a way up from its outings and their climbs ({km, dplus_m, duration_s} or undefined):
 * medians, and the time most pilots take (the middle half, from 4 climbs on; else the fastest and the slowest).
 */
export function routeNumbers(outings, climbOf) {
  const cs = outings.map((o) => climbOf(o)).filter(Boolean);
  const times = cs.map((c) => c.duration_s);
  const middle = times.length >= 4;
  return {
    outings: outings.length,
    pilots: new Set(outings.map((o) => o.user_id || o.pilot)).size,
    climbs: cs.length,
    km: quantile(cs.map((c) => c.km), 0.5),
    dplus: quantile(outings.map((o) => (climbOf(o) && climbOf(o).dplus_m != null ? climbOf(o).dplus_m : o.dplus_m)), 0.5),
    time: quantile(times, 0.5),
    timeLow: quantile(times, middle ? 0.25 : 0),
    timeHigh: quantile(times, middle ? 0.75 : 1),
  };
}

/** The ground altitude under each point of ``line`` ([[lat, lon], …]), or null when the service does not answer. */
export async function groundAltitudes(line) {
  const out = [];
  try {
    for (let i = 0; i < line.length; i += MAX_COORDINATES) {
      const part = line.slice(i, i + MAX_COORDINATES);
      const q = `latitude=${part.map((p) => p[0].toFixed(5)).join(',')}&longitude=${part.map((p) => p[1].toFixed(5)).join(',')}`;
      const r = await fetch(`${CONFIG.ELEVATION_URL}?${q}`);
      if (!r.ok) return null;
      const alts = (await r.json()).elevation;
      if (!Array.isArray(alts) || alts.length !== part.length) return null;
      out.push(...alts);
    }
  } catch (_) {
    return null;
  }
  return out;
}

/** Distance from the start (km) of each point of ``line``. */
export function distances(line) {
  const d = [0];
  for (let i = 1; i < line.length; i += 1) d.push(d[i - 1] + metres(line[i - 1], line[i]) / 1000);
  return d;
}

/** The altitude profile: altitude against distance, the start and the take-off written at its ends. */
function profile(line, alts) {
  const W = 320;
  const H = 110;
  const pad = { l: 34, r: 8, t: 10, b: 18 };
  const d = distances(line);
  const total = d[d.length - 1] || 1;
  const lo = Math.min(...alts);
  const hi = Math.max(...alts);
  const span = Math.max(hi - lo, 50);
  const x = (km) => pad.l + (km / total) * (W - pad.l - pad.r);
  const y = (a) => pad.t + (1 - (a - lo) / span) * (H - pad.t - pad.b);
  const top = alts.map((a, i) => `${x(d[i]).toFixed(1)},${y(a).toFixed(1)}`).join(' ');
  const text = (attrs, s) => { const t = svg('text', attrs); t.textContent = s; return t; };
  return svg('svg', { class: 'route-profile', viewBox: `0 0 ${W} ${H}`, role: 'img',
    'aria-label': `Altitude profile: from ${fmtInt(alts[0])} m to ${fmtInt(alts[alts.length - 1])} m over ${fmtKm(total)}` },
  svg('polygon', { class: 'area', points: `${x(0)},${H - pad.b} ${top} ${x(total)},${H - pad.b}` }),
  svg('polyline', { class: 'line', points: top }),
  text({ x: pad.l - 4, y: y(hi) + 4, 'text-anchor': 'end' }, fmtInt(hi)),
  text({ x: pad.l - 4, y: y(lo) + 4, 'text-anchor': 'end' }, fmtInt(lo)),
  text({ x: pad.l, y: H - 4 }, '0'),
  text({ x: W - pad.r, y: H - 4, 'text-anchor': 'end' }, fmtKm(total)));
}

/** The middle line of a way up as a GPX track, with the ground altitudes when known. */
export function routeGpx(line, alts, name, about) {
  const esc = (s) => String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c]);
  const pts = line.map((p, i) => `<trkpt lat="${p[0]}" lon="${p[1]}">${alts && alts[i] != null ? `<ele>${Math.round(alts[i])}</ele>` : ''}</trkpt>`);
  return `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="${esc(CONFIG.SITE_NAME)}" xmlns="http://www.topografix.com/GPX/1/1">`
    + `<metadata><name>${esc(name)}</name><desc>${esc(about)}</desc></metadata>`
    + `<trk><name>${esc(name)}</name><desc>${esc(about)}</desc><trkseg>${pts.join('')}</trkseg></trk></gpx>`;
}

function download(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/gpx+xml' }));
  const a = h('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * The sheet of a way up, for the side panel of the map.
 * ``takeoff``: the take-off's name and altitude; ``way``: « From La Clusaz · via Bois de la Colombière »;
 * ``numbers``: routeNumbers(); ``link``: the address of the sheet; ``onBack``: back to the take-off;
 * ``on3D``: opens the way up in 3D (none without WebGL).
 */
export function routeSheet({ route, takeoff, way, numbers, link, onBack, swatch, outings, on3D }) {
  const n = numbers;
  const fact = (label, value, hint) => h('div', { class: 'fact' }, h('span', { class: 'hint' }, label), h('b', null, value),
    hint ? h('span', { class: 'hint' }, hint) : null);
  const profileBox = h('div', { class: 'route-profile-box' }, h('p', { class: 'hint' }, 'Loading the altitude profile…'));
  const name = `${takeoff.name} · ${way}`;
  const about = `The way up to ${takeoff.name}, down the middle of ${n.climbs} climbs of pilots (H&F Tracks). Not a marked trail: check the way on the ground.`;
  let alts = null;
  const gpx = h('button', { class: 'primary' }, 'Download the way up (GPX)');
  gpx.addEventListener('click', () => download(`${name.replace(/[^\p{L}\p{N}]+/gu, '_').replace(/^_|_$/g, '')}.gpx`, routeGpx(route.line, alts, name, about)));
  const copy = h('button', null, 'Copy the link');
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(link); copy.textContent = 'Link copied'; } catch (_) { copy.textContent = link; }
    setTimeout(() => { copy.textContent = 'Copy the link'; }, 2500);
  });
  const sheet = h('div', { class: 'route-sheet' },
    h('button', { class: 'link back', onclick: onBack }, `← ${takeoff.name}`),
    h('h2', null, swatch, way),
    h('p', { class: 'hint' }, `Up to ${takeoff.name}${takeoff.alt != null ? ` (${fmtInt(takeoff.alt)} m)` : ''} · ${n.outings} outing${n.outings > 1 ? 's' : ''} · ${n.pilots} pilot${n.pilots > 1 ? 's' : ''}`),
    h('div', { class: 'facts' },
      n.km != null ? fact('Distance', fmtKm(n.km)) : null,
      n.dplus != null ? fact('D+', `${fmtInt(n.dplus)} m`) : null,
      n.time != null ? fact('Time up', fmtDur(n.time),
        n.climbs > 1 ? (n.climbs >= 4 ? `most: ${fmtDur(n.timeLow)} – ${fmtDur(n.timeHigh)}` : `${fmtDur(n.timeLow)} – ${fmtDur(n.timeHigh)}`) : null) : null),
    profileBox,
    h('div', { class: 'row route-actions' }, gpx, on3D ? h('button', { onclick: on3D }, 'View in 3D') : null, copy),
    h('p', { class: 'hint' }, `${n.climbs > 1 ? `Medians of ${n.climbs} climbs; the line runs down their middle` : 'From one climb'}. Not a marked trail: check the way, the snow and the weather on the ground.`),
    outings);
  groundAltitudes(route.line).then((a) => {
    alts = a;
    if (a && a.every((v) => v != null)) {
      profileBox.replaceChildren(profile(route.line, a),
        h('p', { class: 'hint' }, `${fmtInt(a[0])} m → ${fmtInt(a[a.length - 1])} m · ground altitude: Open-Meteo`));
    } else {
      profileBox.replaceChildren(h('p', { class: 'hint' }, 'No altitude profile: the elevation service did not answer.'));
    }
  });
  return sheet;
}
