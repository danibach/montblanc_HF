// The site: a small single-page app. Routes are in the address after "#".
//   #/                 list of outings (filter by year and country)
//   #/outing/<id>      one outing: map, profile, numbers
//   #/user/<id>        a participant: statistics and outings
//   #/ranking          ranking of participants (by year or all time)
//   #/upload           send a track (needs an account)
//   #/login            sign in

import { CONFIG } from './config.js';
import * as api from './api.js';
import { analyseFile, checkTerrain, lookUpPlaces, onEngineStatus, startEngine } from './engine.js';
import { buildMap, buildProfile, legend, downloadText, trackToGpx } from './charts.js';
import { $, h, notice, table, fmtInt, fmtKm, fmtDur, fmtDate, pilotName } from './util.js';

const view = $('#view');
let routeToken = 0;       // a slow answer for a page we already left must not draw over the new page

// ---------------------------------------------------------------- shell

function renderAccount() {
  const box = $('#account');
  box.replaceChildren();
  if (api.state.user) {
    const name = api.state.profile && api.state.profile.display_name;
    box.append(
      h('a', { href: `#/user/${api.state.user.id}` }, name || 'Your page'),
      h('button', { class: 'link', onclick: async () => { await api.signOut(); location.hash = '#/'; } }, 'Sign out'),
    );
  } else {
    box.append(h('a', { href: '#/login' }, 'Sign in'));
  }
}

function renderFooter() {
  const f = $('#footer');
  const lines = [
    h('p', null, 'Published tracks are public: map, profile and statistics. The original file stays private.'),
    h('p', null, 'Place names come from OpenStreetMap and ground altitudes from Open-Meteo (the preview sends them a few points of the flight). Scores are automatic: D+ on foot plus D− in flight, in metres.'),
  ];
  if (CONFIG.CONTACT_EMAIL) {
    lines.push(h('p', null, 'To remove a track or an account: ', h('a', { href: `mailto:${CONFIG.CONTACT_EMAIL}` }, CONFIG.CONTACT_EMAIL), ' (or use the delete buttons).'));
  }
  f.replaceChildren(...lines);
}

function setNav(name) {
  for (const a of document.querySelectorAll('#nav a')) {
    if (a.dataset.route === name) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
}

function show(...nodes) {
  view.replaceChildren(...nodes.flat().filter(Boolean));
}

function loading() {
  show(h('p', { class: 'hint pad' }, 'Loading…'));
}

function fail(err) {
  show(notice('error', h('p', null, (err && err.message) || 'Something went wrong. Try again.')));
}

// ---------------------------------------------------------------- shared pieces

const link = (href, text) => h('a', { href }, text);

function stat(value, label, big) {
  return h('div', { class: `stat${big ? ' big' : ''}` }, h('b', null, value), h('span', null, label));
}

function place(label, text) {
  return h('div', null, h('dt', null, label), h('dd', null, text || '–'));
}

function coords(lat, lon) {
  return lat == null ? null : `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

/** Numbers, places, map and profile of one outing (a database row or a preview). */
function outingDetail(o) {
  const trace = o.trace;
  const mapView = trace ? buildMap(trace, [
    { lat: o.start_lat, lon: o.start_lon, alt: o.start_alt, label: 'Start on foot', colour: '#2b6cb0' },
    { lat: o.summit_lat, lon: o.summit_lon, alt: o.summit_alt, label: o.summit_name || 'Highest point on foot', colour: '#3f8f46' },
    { lat: o.takeoff_lat, lon: o.takeoff_lon, alt: o.takeoff_alt, label: 'Take-off', colour: '#e0552b' },
    { lat: o.landing_lat, lon: o.landing_lon, alt: o.landing_alt, label: 'Landing', colour: '#7b3fa0' },
  ]) : null;
  const detail = h('div', null,
    h('div', { class: 'stats' },
      stat(fmtInt(o.score), 'Score', true),
      stat(`${fmtInt(o.dplus_m)} m`, 'D+ on foot'),
      stat(`${fmtInt(o.dminus_m)} m`, 'D− in flight'),
      stat(fmtKm(o.walk_km), 'Distance on foot'),
      stat(fmtKm(o.flight_free_km), 'Free distance (FAI)'),
      stat(fmtDur(o.duration_s), 'Duration')),
    h('dl', { class: 'places' },
      place('Start on foot', [o.start_place, o.start_commune && o.start_commune !== o.start_place ? o.start_commune : null].filter(Boolean).join(', ') || coords(o.start_lat, o.start_lon)),
      place('Highest point on foot', `${o.summit_name || coords(o.summit_lat, o.summit_lon) || '–'}${o.summit_alt != null ? ` · ${fmtInt(o.summit_alt)} m` : ''}`),
      place('Take-off', `${o.takeoff_name || coords(o.takeoff_lat, o.takeoff_lon) || '–'}${o.takeoff_alt != null ? ` · ${fmtInt(o.takeoff_alt)} m` : ''}`),
      place('Country', o.country_name || o.country_code)),
    mapView ? mapView.element : null,
    trace ? legend() : null,
    trace ? buildProfile(trace) : null);
  if (mapView) requestAnimationFrame(() => mapView.start());
  return detail;
}

function outingRows(rows, { showPilot = true, showStatus = false } = {}) {
  return rows.map((r) => h('tr', null,
    h('td', null, fmtDate(r.outing_date)),
    showPilot ? h('td', null, link(`#/user/${r.user_id}`, pilotName(r.profiles))) : null,
    h('td', { class: 'wrap' }, r.status === 'published' || !showStatus ? link(`#/outing/${r.id}`, r.title || 'Outing') : (r.title || 'Uploaded track'),
      r.status === 'published' && r.verified === false ? [' ', statusBadge(r)] : null),
    h('td', null, r.country_name || r.country_code || ''),
    h('td', { class: 'num' }, fmtInt(r.dplus_m)),
    h('td', { class: 'num' }, fmtInt(r.dminus_m)),
    h('td', { class: 'num score' }, fmtInt(r.score)),
    showStatus ? h('td', null, statusBadge(r)) : null));
}

function statusBadge(r) {
  if (r.status === 'pending') return h('span', { class: 'dot pending' }, 'Processing');
  if (r.status === 'published' && r.verified === false) return h('span', { class: 'dot pending', title: 'Published on the first analysis; the server is checking it.' }, 'Validation pending');
  if (r.status === 'rejected') return h('span', { class: 'dot rejected', title: r.reject_reason || '' }, 'Not counted');
  return h('span', { class: 'dot' }, 'Published');
}

function listHeaders({ showPilot = true, showStatus = false } = {}) {
  return [
    { label: 'Date' },
    showPilot ? { label: 'Pilot' } : null,
    { label: 'Outing' },
    { label: 'Country' },
    { label: 'D+ (m)', num: true },
    { label: 'D− (m)', num: true },
    { label: 'Score', num: true },
    showStatus ? { label: 'Status' } : null,
  ].filter(Boolean);
}

async function filterBar(current, onChange, { yearLabel = 'All years' } = {}) {
  const f = await api.getFilters();
  const year = h('select', { id: 'f-year' }, h('option', { value: '' }, yearLabel),
    f.years.map((y) => h('option', { value: y, selected: String(y) === String(current.year || '') }, y)));
  const country = h('select', { id: 'f-country' }, h('option', { value: '' }, 'All countries'),
    f.countries.map((c) => h('option', { value: c.code, selected: c.code === current.country }, c.name)));
  const change = () => onChange({ year: year.value || '', country: country.value || '' });
  year.addEventListener('change', change);
  country.addEventListener('change', change);
  return h('div', { class: 'filters' },
    h('div', { class: 'field' }, h('label', { for: 'f-year' }, 'Year'), year),
    h('div', { class: 'field' }, h('label', { for: 'f-country' }, 'Country'), country));
}

function query() {
  const q = location.hash.split('?')[1] || '';
  return Object.fromEntries(new URLSearchParams(q));
}

function goFilters(path, { year, country }) {
  const p = new URLSearchParams();
  if (year) p.set('year', year);
  if (country) p.set('country', country);
  location.hash = `#/${path}${p.toString() ? `?${p}` : ''}`;
}

// ---------------------------------------------------------------- pages

async function pageHome(token) {
  setNav('home');
  const q = query();
  const bar = await filterBar(q, (v) => goFilters('', v));
  let offset = 0;
  const body = h('tbody');
  const wrap = table(listHeaders(), [], '');
  wrap.querySelector('table').replaceChild(body, wrap.querySelector('tbody'));
  const more = h('button', null, 'Load more');
  const count = h('p', { class: 'hint' });
  const empty = notice('info', h('p', null, 'No outing yet for these filters.'));
  empty.hidden = true;

  async function load() {
    more.disabled = true;
    const { rows, total } = await api.listOutings({ year: q.year, country: q.country, offset });
    if (token !== routeToken) return;
    body.append(...outingRows(rows));
    offset += rows.length;
    count.textContent = total ? `${offset} of ${total} outings` : '';
    empty.hidden = total > 0;
    wrap.hidden = total === 0;
    more.hidden = offset >= total;
    more.disabled = false;
  }
  more.addEventListener('click', () => load().catch(fail));
  show(h('h1', null, 'Hike & Fly outings'), bar, empty, wrap, count, more);
  await load();
}

async function pageRanking(token) {
  setNav('ranking');
  const q = query();
  const bar = await filterBar(q, (v) => goFilters('ranking', v), { yearLabel: 'All time' });
  const rows = await api.getRanking({ year: q.year, country: q.country });
  if (token !== routeToken) return;
  const body = rows.map((r, i) => h('tr', null,
    h('td', { class: 'num' }, i + 1),
    h('td', null, link(`#/user/${r.user_id}`, pilotName(r))),
    h('td', { class: 'num' }, fmtInt(r.outings)),
    h('td', { class: 'num' }, fmtInt(r.dplus)),
    h('td', { class: 'num' }, fmtInt(r.dminus)),
    h('td', { class: 'num score' }, fmtInt(r.score))));
  show(
    h('h1', null, 'Ranking'),
    h('p', { class: 'sub' }, 'Sum of the scores of all outings. Score = D+ on foot + D− in flight (metres).'),
    bar,
    rows.length
      ? table([{ label: '#', num: true }, { label: 'Pilot' }, { label: 'Outings', num: true }, { label: 'D+ (m)', num: true }, { label: 'D− (m)', num: true }, { label: 'Score', num: true }], body)
      : notice('info', h('p', null, 'No outing yet for these filters.')));
}

async function pageOuting(token, id) {
  setNav('home');
  const o = await api.getOuting(id);
  if (token !== routeToken) return;
  if (!o) return show(notice('error', h('p', null, 'This outing does not exist, or is not public.')));
  const mine = api.state.user && api.state.user.id === o.user_id;
  const actions = h('div', { class: 'row' });
  if (o.status === 'published' && o.trace) {
    actions.append(h('button', { onclick: () => downloadText(`${(o.title || 'outing').replace(/[^\w-]+/g, '_')}.gpx`, trackToGpx(o.trace, o.title || 'Outing'), 'application/gpx+xml') }, 'Download GPX'));
  }
  if (mine) {
    actions.append(h('button', { class: 'danger', onclick: async () => {
      if (!confirm('Delete this outing and its file? This cannot be undone.')) return;
      try { await api.deleteOuting(o); location.hash = `#/user/${o.user_id}`; } catch (e) { fail(e); }
    } }, 'Delete'));
  } else if (api.state.user && o.status === 'published') {
    actions.append(reportForm(o.id));
  }
  const head = h('div', { class: 'headline' },
    h('div', null,
      h('h1', null, o.title || 'Outing'),
      h('p', { class: 'sub' }, link(`#/user/${o.user_id}`, pilotName(o.profiles)), ` · ${fmtDate(o.outing_date)}`, o.country_name ? ` · ${o.country_name}` : '')),
    o.status !== 'published' || o.verified === false ? statusBadge(o) : null);
  if (o.status === 'pending') {
    return show(head, notice('pending', h('p', null, 'Your track is being analysed. This usually takes a few minutes; reload this page later.')), actions);
  }
  if (o.status === 'rejected') {
    return show(head, notice('error', h('p', null, o.reject_reason || 'This track does not count.')), actions);
  }
  show(head, outingDetail(o), actions,
    (o.warnings && o.warnings.length) ? h('p', { class: 'hint' }, o.warnings.join(' · ')) : null);
}

function reportForm(outingId) {
  const reason = h('input', { type: 'text', maxlength: '500', placeholder: 'What is wrong with this outing?', 'aria-label': 'Reason' });
  const status = h('span', { class: 'hint' });
  const form = h('form', { class: 'row', onsubmit: async (ev) => {
    ev.preventDefault();
    if (!reason.value.trim()) return;
    try { await api.reportOuting(outingId, reason.value); status.textContent = 'Thank you, the report was sent.'; reason.value = ''; }
    catch (e) { status.textContent = e.message; }
  } }, reason, h('button', null, 'Report'), status);
  return h('details', null, h('summary', { class: 'hint' }, 'Report a problem'), form);
}

async function pageUser(token, id) {
  setNav(api.state.user && api.state.user.id === id ? 'me' : 'home');
  const [profile, rows] = await Promise.all([api.getProfile(id), api.listUserOutings(id)]);
  if (token !== routeToken) return;
  if (!profile) return show(notice('error', h('p', null, 'This page does not exist.')));
  const mine = api.state.user && api.state.user.id === id;
  const published = rows.filter((r) => r.status === 'published');
  const sum = (k) => published.reduce((a, r) => a + (r[k] || 0), 0);
  const countries = new Set(published.map((r) => r.country_code).filter(Boolean));
  const best = published.reduce((m, r) => Math.max(m, r.flight_free_km || 0), 0);
  const others = rows.filter((r) => r.status !== 'published');

  const nodes = [
    h('h1', null, pilotName(profile)),
    h('div', { class: 'stats' },
      stat(fmtInt(published.length), 'Outings'),
      stat(fmtInt(sum('score')), 'Total score', true),
      stat(`${fmtInt(sum('dplus_m'))} m`, 'D+ on foot'),
      stat(`${fmtInt(sum('dminus_m'))} m`, 'D− in flight'),
      stat(fmtKm(published.reduce((a, r) => a + (r.walk_km || 0), 0)), 'Distance on foot'),
      stat(fmtKm(best), 'Longest free distance'),
      stat(fmtInt(countries.size), 'Countries')),
  ];
  if (mine && !profile.display_name) nodes.push(nameForm('Choose the name shown next to your outings'));
  if (mine && others.length) {
    nodes.push(h('h2', null, 'Waiting or not counted'),
      table(listHeaders({ showPilot: false, showStatus: true }), others.map((r) => h('tr', null,
        h('td', null, fmtDate(r.outing_date) === '–' ? fmtDate(r.created_at) : fmtDate(r.outing_date)),
        h('td', { class: 'wrap' }, r.status === 'rejected' ? (r.reject_reason || 'Not counted') : 'Uploaded track'),
        h('td', null, ''), h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''),
        h('td', null, statusBadge(r), ' ', h('button', { class: 'link', onclick: async () => {
          if (!confirm('Delete this upload?')) return;
          try { await api.deleteOuting(r); pageUser(++routeToken, id).catch(fail); } catch (e) { fail(e); }
        } }, 'Delete'))))));
  }
  nodes.push(h('h2', null, 'Outings'),
    published.length
      ? table(listHeaders({ showPilot: false }), outingRows(published, { showPilot: false }))
      : notice('info', h('p', null, 'No published outing yet.')));
  if (mine) {
    nodes.push(h('h2', null, 'Your account'),
      h('div', { class: 'card' },
        h('p', { class: 'hint' }, `Signed in as ${api.state.user.email || ''}. Deleting your account deletes your page, your outings and your original files.`),
        h('button', { class: 'danger', onclick: async () => {
          if (!confirm('Delete your account, all your outings and your files? This cannot be undone.')) return;
          try { await api.deleteAccount(); location.hash = '#/'; } catch (e) { fail(e); }
        } }, 'Delete my account')));
  }
  show(nodes);
}

function nameForm(title) {
  const input = h('input', { type: 'text', id: 'display-name', maxlength: '40', minlength: '2', required: true, value: (api.state.profile && api.state.profile.display_name) || '' });
  const msg = h('p', { class: 'hint', role: 'status' });
  return h('form', { class: 'card', onsubmit: async (ev) => {
    ev.preventDefault();
    try { await api.setDisplayName(input.value); msg.textContent = 'Saved.'; route(); } catch (e) { msg.textContent = e.message; }
  } },
    h('label', { for: 'display-name' }, title),
    h('div', { class: 'row' }, input, h('button', { class: 'primary' }, 'Save')),
    h('p', { class: 'hint' }, 'Shown publicly. Pick a name or pseudonym of your choice (2 to 40 characters).'), msg);
}

// ---------------------------------------------------------------- upload

async function pageUpload() {
  setNav('upload');
  if (!api.state.user) {
    return show(h('h1', null, 'Upload a track'),
      notice('info', h('p', null, 'You need an account to upload a track. ', link('#/login', 'Sign in'), ' — it takes one e-mail link.')));
  }
  if (!api.state.profile || !api.state.profile.display_name) {
    return show(h('h1', null, 'Upload a track'), nameForm('First, choose the name shown next to your outings'));
  }
  const engineMsg = h('span', { class: 'hint', role: 'status', id: 'engine-status' }, 'Preparing the analysis…');
  const unsubscribe = onEngineStatus((text, state) => { engineMsg.textContent = text; engineMsg.dataset.state = state; });
  const out = h('div', { id: 'preview' });
  const input = h('input', { type: 'file', id: 'track', accept: '.igc,.gpx,.kml,.fit' });
  const drop = h('div', { class: 'drop', id: 'drop' },
    h('p', null, h('b', null, 'Drop your track here'), ' or choose a file'),
    h('p', null, input),
    h('p', { class: 'hint' }, `IGC, GPX, KML or FIT with timestamps and altitude, up to ${CONFIG.MAX_FILE_MB} MB. The analysis runs in your browser: nothing is sent until you publish.`));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files[0]) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event('change')); }
  });
  input.addEventListener('change', () => { if (input.files[0]) analyse(input.files[0], out).catch(fail); });
  show(h('h1', null, 'Upload a track'), drop, h('p', null, engineMsg), out);
  startEngine().catch(() => {});
  window.addEventListener('hashchange', unsubscribe, { once: true });
}

async function analyse(file, out) {
  out.replaceChildren(h('p', { class: 'hint pad', id: 'busy' }, 'Analysing…'));
  if (file.size > CONFIG.MAX_FILE_MB * 1024 * 1024) {
    return out.replaceChildren(notice('error', h('p', null, `This file is larger than ${CONFIG.MAX_FILE_MB} MB.`)));
  }
  let res;
  try {
    res = await analyseFile(file);
    res = await checkTerrain(res);
  } catch (e) {
    return out.replaceChildren(notice('error', h('p', null, e.message)));
  }
  const o = res.outing;
  const places = await lookUpPlaces(o);
  const pv = previewRow(res, places);

  const verdict = o.status === 'ok'
    ? notice('ok', h('p', null, h('b', null, `${fmtInt(o.score)} points`), ` — ${fmtInt(o.dplus_m)} m climbed on foot and ${fmtInt(o.dminus_m)} m flown down.`))
    : notice('error', h('p', null, o.reason === 'no_flight' ? ((o.warnings || []).some((w) => w.includes('follows the ground')) ? 'The descent follows the ground (ski, bike or run): no flight found, so it does not count.' : 'No flight found in this track, so it does not count.') : 'Not enough climbing on foot before the flight (at least 100 m), so it does not count.'));
  if (o.status !== 'ok' && (o.warnings || []).length) verdict.append(h('p', { class: 'hint' }, o.warnings.join(' · ')));
  const publish = h('button', { class: 'primary', id: 'publish', disabled: o.status !== 'ok' }, 'Publish this outing');
  const status = h('span', { class: 'hint', role: 'status' });
  publish.addEventListener('click', async () => {
    publish.disabled = true;
    try {
      const id = await api.submitTrack(file, (t) => { status.textContent = t; }, pv);
      out.replaceChildren(notice('ok', h('p', null, 'Published. The server now checks the result: the "Validation pending" badge disappears within a few minutes once it is confirmed.'),
        h('p', null, link(`#/outing/${id}`, 'See your outing'))));
    } catch (e) {
      status.textContent = '';
      publish.disabled = false;
      out.prepend(notice('error', h('p', null, e.message)));
    }
  });
  const actions = h('div', { class: 'publish-bar' },
    h('div', { class: 'row' }, publish, status),
    h('p', { class: 'hint' }, 'Not published yet. By publishing you agree that this track — map, profile and statistics — is shown publicly. The original file stays private. The result is computed again on our side before it is confirmed.'));
  out.replaceChildren(...[
    verdict,
    o.status === 'ok' ? actions : null,
    h('h2', null, pv.title),
    outingDetail(pv),
    pv.warnings && pv.warnings.length ? h('p', { class: 'hint' }, pv.warnings.join(' · ')) : null,
  ].filter(Boolean));
}

/** A preview shaped like a database row, from the browser's own analysis. */
function previewRow(res, places) {
  const o = res.outing;
  const pl = places || {};
  const pick = (p, k) => (p ? p[k] : null);
  return {
    engine_version: res.engine && res.engine.version, score_version: o.score_version, started_at: o.started_at,
    flight_path_km: o.flight_path_km, places_pending: !places,
    flights: (o.flights || []).map(({ i_start, i_end, ...rest }) => rest),
    title: (pl.summit && pl.summit.name) || pl.start_place || 'Hike & Fly outing',
    outing_date: o.date, duration_s: o.duration_s, score: o.score, dplus_m: o.dplus_m, dminus_m: o.dminus_m,
    walk_km: o.walk_km, flight_free_km: o.flight_free_km, warnings: o.warnings,
    country_name: pl.country && pl.country.name, country_code: pl.country && pl.country.code,
    start_place: pl.start_place, start_commune: pl.commune,
    start_lat: pick(o.start, 'lat'), start_lon: pick(o.start, 'lon'), start_alt: pick(o.start, 'alt'),
    summit_name: pl.summit && pl.summit.name, summit_lat: pick(o.summit, 'lat'), summit_lon: pick(o.summit, 'lon'), summit_alt: pick(o.summit, 'alt'),
    takeoff_name: pl.takeoff && pl.takeoff.name, takeoff_lat: pick(o.takeoff, 'lat'), takeoff_lon: pick(o.takeoff, 'lon'), takeoff_alt: pick(o.takeoff, 'alt'),
    landing_lat: pick(o.landing, 'lat'), landing_lon: pick(o.landing, 'lon'), landing_alt: pick(o.landing, 'alt'),
    trace: res.trace,
  };
}

// ---------------------------------------------------------------- sign in

function pageLogin() {
  setNav('login');
  if (api.state.user) { location.hash = '#/upload'; return; }
  const email = h('input', { type: 'email', id: 'email', required: true, autocomplete: 'email', placeholder: 'you@example.com' });
  const msg = h('div');
  let token = '';
  const needsCheck = Boolean(CONFIG.TURNSTILE_SITE_KEY);
  const captcha = h('div', { id: 'captcha' });
  const submit = h('button', { class: 'primary', disabled: needsCheck }, 'Send me a sign-in link');
  const form = h('form', { class: 'card', onsubmit: async (ev) => {
    ev.preventDefault();
    submit.disabled = true;
    try {
      await api.sendLink(email.value.trim(), token);
      try { localStorage.setItem('after-login', '#/upload'); } catch (_) { /* ignore */ }
      msg.replaceChildren(notice('ok', h('p', null, `We sent a sign-in link to ${email.value.trim()}. Open it on this device.`)));
    } catch (e) {
      msg.replaceChildren(notice('error', h('p', null, e.message)));
      // a check can be used once: ask for a new one, and wait for it before the next try
      token = '';
      if (window.turnstile) window.turnstile.reset();
    } finally { submit.disabled = needsCheck && !token; }
  } },
    h('label', { for: 'email' }, 'Your e-mail address'),
    h('div', { class: 'row' }, email, submit), captcha, msg,
    h('p', { class: 'hint' }, 'No password: you receive a link by e-mail each time you sign in. A first sign-in creates your account.'));
  const nodes = [h('h1', null, 'Sign in'), form];
  if (CONFIG.GOOGLE_LOGIN) {
    nodes.push(h('div', { class: 'row' }, h('button', { onclick: () => api.signInWithGoogle().catch(fail) }, 'Continue with Google')));
  }
  const hashError = sessionStorageGet('signin-error');
  if (hashError) nodes.unshift(notice('error', h('p', null, hashError)));
  show(nodes);
  loadTurnstile(captcha, (t) => { token = t; submit.disabled = needsCheck && !token; });
}

function sessionStorageGet(key) {
  try { const v = sessionStorage.getItem(key); sessionStorage.removeItem(key); return v; } catch (_) { return null; }
}

function loadTurnstile(box, onToken) {
  if (!CONFIG.TURNSTILE_SITE_KEY) return;
  const render = () => {
    if (!window.turnstile || !box.isConnected) return;
    window.turnstile.render(box, { sitekey: CONFIG.TURNSTILE_SITE_KEY, callback: onToken, 'expired-callback': () => onToken('') });
  };
  if (window.turnstile) return render();
  if (document.getElementById('turnstile-script')) return void setTimeout(render, 800);
  const sc = document.createElement('script');
  sc.id = 'turnstile-script';
  sc.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
  sc.async = true;
  sc.onload = render;
  document.head.append(sc);
}

// ---------------------------------------------------------------- router

async function route() {
  const token = ++routeToken;
  const raw = location.hash.replace(/^#/, '');
  if (raw.startsWith('error')) {
    try { sessionStorage.setItem('signin-error', 'That sign-in link is no longer valid. Ask for a new one.'); } catch (_) { /* ignore */ }
    history.replaceState(null, '', location.pathname + '#/login');
  }
  const path = (location.hash.replace(/^#\/?/, '').split('?')[0] || '').split('/');
  window.scrollTo(0, 0);
  try {
    if (path[0] === '') { loading(); await pageHome(token); }
    else if (path[0] === 'ranking') { loading(); await pageRanking(token); }
    else if (path[0] === 'outing' && path[1]) { loading(); await pageOuting(token, path[1]); }
    else if (path[0] === 'user' && path[1]) { loading(); await pageUser(token, path[1]); }
    else if (path[0] === 'upload') await pageUpload();
    else if (path[0] === 'login') pageLogin();
    else { location.hash = '#/'; }
  } catch (err) {
    if (token === routeToken) fail(err);
  }
}

(async function main() {
  renderFooter();
  api.onSession(() => {
    renderAccount();
    const here = (location.hash.replace(/^#\/?/, '').split('/')[0]);
    if (here === 'login' || here === 'upload' || (here === 'user' && api.state.user)) route();
  });
  await api.refreshSession();
  renderAccount();
  try {
    const next = localStorage.getItem('after-login');
    if (next && api.state.user) { localStorage.removeItem('after-login'); history.replaceState(null, '', location.pathname + next); }
  } catch (_) { /* ignore */ }
  // After the e-mail link, Supabase brings the person back with ?code=…: it has been used, hide it.
  if (location.search) history.replaceState(null, '', location.pathname + location.hash);
  window.addEventListener('hashchange', route);
  route();
})();
