// The site: a small single-page app. Routes are in the address after "#".
//   #/                 My H&Fs: the signed-in person's own outings (filter by year and country)
//   #/all              All: the outings of everyone (filter by year and country)
//   #/outing/<id>      one outing: map, profile, numbers
//   #/user/<id>        a participant: statistics and outings
//   #/ranking          ranking of participants (by year or all time)
//   #/map              map of the take-offs: heat map, take-off markers, climbs and outings of a take-off
//   #/upload           send a track (needs an account)
//   #/mark             mark the flights of a refused track by hand, on a map (opened from the Upload page)
//   #/login            sign in

import { CONFIG } from './config.js';
import * as api from './api.js';
import { analyseFile, analyseFiles, analyseManual, checkTerrain, groupFiles, lookUpPlaces, onEngineStatus, startEngine } from './engine.js';
import { buildMap, buildProfile, legend, downloadText, trackToGpx } from './charts.js';
import { buildExplorer } from './explorer.js';
import { buildMarkTool } from './mark.js';
import { buildHelp } from './help.js';
import { $, h, notice, table, fmtInt, fmtKm, fmtDur, fmtDate, pilotName, outingTitle } from './util.js';

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
  box.append(h('a', { href: '#/help', class: 'help-link' }, 'Help'));
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
  view.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
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
      stat(fmtKm(o.flight_free_km), 'Free distance FAI'),
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
    h('td', { class: 'wrap' }, r.status === 'published' || !showStatus ? link(`#/outing/${r.id}`, outingTitle(r)) : (r.title || 'Uploaded track'),
      r.status === 'published' && r.verified === false ? [' ', statusBadge(r)] : null),
    h('td', { class: 'num' }, fmtInt(r.dplus_m)),
    h('td', { class: 'num' }, fmtInt(r.dminus_m)),
    h('td', { class: 'num' }, fmtDist(r.walk_km)),
    h('td', { class: 'num' }, fmtDist(r.flight_path_km)),
    h('td', { class: 'num score' }, fmtInt(r.score)),
    showStatus ? h('td', null, statusBadge(r)) : null));
}

// A distance in km for the lists, without the unit (the header has it).
function fmtDist(n) {
  return n == null ? '–' : Number(n).toFixed(1);
}

function statusBadge(r) {
  if (r.status === 'pending') return h('span', { class: 'dot pending' }, 'Processing');
  if (r.status === 'published' && r.verified === false) return h('span', { class: 'dot pending', title: 'Published on the first analysis; the server is checking it.' }, 'Validation pending');
  if (r.status === 'rejected') return h('span', { class: 'dot rejected', title: r.reject_reason || '' }, 'Not counted');
  return h('span', { class: 'dot' }, 'Published');
}

function listHeaders({ showPilot = true, showStatus = false } = {}) {
  return [
    { label: 'Date', key: 'date' },
    showPilot ? { label: 'Pilot', key: 'pilot' } : null,
    { label: 'Outing', key: 'outing' },
    { label: 'D+ (m)', key: 'dplus', num: true },
    { label: 'D− (m)', key: 'dminus', num: true },
    { label: 'Hike (km)', key: 'hike', num: true },
    { label: 'Fly (km)', key: 'fly', num: true },
    { label: 'Score', key: 'score', num: true },
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

function goFilters(path, { year, country, sort, dir, page }) {
  const p = new URLSearchParams();
  if (year) p.set('year', year);
  if (country) p.set('country', country);
  // The default order (newest first) stays out of the address.
  if (sort && !(sort === 'date' && dir !== 'asc')) { p.set('sort', sort); p.set('dir', dir === 'asc' ? 'asc' : 'desc'); }
  if (page && page > 1) p.set('page', page);
  location.hash = `#/${path}${p.toString() ? `?${p}` : ''}`;
}

// ---------------------------------------------------------------- pages

// The filtered, sortable, paged list of outings (filter bar, table, pager). `path` is the page's address (the
// filters and the order live in it), `userId` limits it to one pilot. Returns the nodes to show, or null when
// the page has been left or redirected meanwhile.
async function outingsSection(token, { path, userId, showPilot, empty }) {
  const q = query();
  const sort = api.SORT_COLUMNS[q.sort] ? q.sort : 'date';
  const dir = q.sort && q.dir === 'asc' ? 'asc' : (q.sort && q.dir === 'desc' ? 'desc' : (sort === 'date' ? 'desc' : 'asc'));
  const page = Math.max(1, parseInt(q.page, 10) || 1);
  const size = CONFIG.PAGE_SIZE;
  // Changing a filter or the order goes back to page 1; the order is kept when a filter changes.
  const go = (extra) => goFilters(path, { year: q.year, country: q.country, sort, dir, ...extra });
  const bar = await filterBar(q, (v) => go({ ...v, page: 1 }));

  const { rows, total } = await api.listOutings({ userId, year: q.year, country: q.country, sort, dir, offset: (page - 1) * size });
  if (token !== routeToken) return null;
  const pages = Math.max(1, Math.ceil(total / size));
  if (page > pages) { go({ page: pages }); return null; }   // a page that no longer exists (filters changed): go to the last one

  // A click on a header: the same column flips the order; a new column starts with text A to Z,
  // numbers from the biggest, dates from the newest.
  const onSort = (key) => {
    const text = ['pilot', 'outing'].includes(key);
    go({ sort: key, dir: key === sort ? (dir === 'asc' ? 'desc' : 'asc') : (text ? 'asc' : 'desc'), page: 1 });
  };

  const from = (page - 1) * size;
  const count = h('p', { class: 'hint' }, total ? `${from + 1}–${from + rows.length} of ${total} outings` : '');
  const pager = pages > 1 ? h('nav', { class: 'pager', 'aria-label': 'Pages' },
    h('button', { disabled: page <= 1, onclick: () => go({ page: page - 1 }) }, '‹ Previous'),
    h('span', { class: 'hint' }, `Page ${page} of ${pages}`),
    h('button', { disabled: page >= pages, onclick: () => go({ page: page + 1 }) }, 'Next ›')) : null;

  return [bar,
    total
      ? [table(listHeaders({ showPilot }), outingRows(rows, { showPilot }), '', { key: sort, dir, onSort }), count, pager]
      : notice('info', empty)];
}

// All: everyone's outings.
async function pageAll(token) {
  setNav('all');
  const section = await outingsSection(token, { path: 'all', showPilot: true, empty: h('p', null, 'No outing yet for these filters.') });
  if (section) show(h('h1', null, 'Outings'), section);
}

// My H&Fs is the pilot page of the signed-in person, at the address "#/".
async function pageMine(token) {
  const me = api.state.user;
  // Signed out: there is no page of one's own, so the visitor lands on everyone's outings.
  if (!me) return location.replace(`${location.pathname}#/all`);
  await pageUser(token, me.id, { path: '' });
}

async function pageRanking(token) {
  setNav('ranking');
  const q = query();
  const bar = await filterBar(q, (v) => goFilters('ranking', v), { yearLabel: 'All time' });
  const rows = await api.getRanking({ year: q.year, country: q.country });
  if (token !== routeToken) return;
  // The rank is the place in the full ranking, so it stays the same when the search narrows the list.
  const entries = rows.map((r, i) => ({ r, rank: i + 1, name: pilotName(r) }));
  const rowOf = ({ r, rank, name }) => h('tr', null,
    h('td', { class: 'num' }, rank),
    h('td', null, link(`#/user/${r.user_id}`, name)),
    h('td', { class: 'num' }, fmtInt(r.outings)),
    h('td', { class: 'num' }, fmtInt(r.dplus)),
    h('td', { class: 'num' }, fmtInt(r.dminus)),
    h('td', { class: 'num' }, fmtDist(r.walk_km)),
    h('td', { class: 'num' }, fmtDist(r.flight_km)),
    h('td', { class: 'num score' }, fmtInt(r.score)));
  const tableNode = rows.length
    ? table([{ label: '#', num: true }, { label: 'Pilot' }, { label: 'Outings', num: true }, { label: 'D+ (m)', num: true }, { label: 'D− (m)', num: true }, { label: 'Hike (km)', num: true }, { label: 'Fly (km)', num: true }, { label: 'Score', num: true }], entries.map(rowOf))
    : null;

  // Search a pilot by name: case and accents ignored, every word must be found in the name.
  const fold = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const search = h('input', { type: 'search', id: 'f-pilot', placeholder: 'Search a pilot…', autocomplete: 'off', 'aria-label': 'Search a pilot' });
  const found = h('p', { class: 'hint' });
  const none = h('div', null, notice('info', h('p', null, 'No pilot matches this search.')));
  none.hidden = true;
  const apply = () => {
    const words = fold(search.value).split(/\s+/).filter(Boolean);
    const hits = entries.filter((e) => words.every((w) => fold(e.name).includes(w)));
    if (tableNode) {
      tableNode.querySelector('tbody').replaceChildren(...hits.map(rowOf));
      tableNode.hidden = !hits.length;
    }
    none.hidden = !words.length || hits.length > 0;
    found.textContent = words.length && hits.length ? `${hits.length} of ${entries.length} pilots` : '';
  };
  search.addEventListener('input', apply);
  const searchBox = rows.length
    ? h('div', { class: 'filters' }, h('div', { class: 'field' }, h('label', { for: 'f-pilot' }, 'Pilot'), search))
    : null;

  show(
    h('h1', null, 'Pilots'),
    h('p', { class: 'sub' }, 'Sum of the scores of all outings. Score = D+ on foot + D− in flight (metres).'),
    bar,
    searchBox,
    tableNode || notice('info', h('p', null, 'No outing yet for these filters.')),
    found,
    none);
}

async function pageMap(token) {
  setNav('map');
  const [rows, sites, routes, ffvl] = await Promise.all([api.getMapOutings(), api.getMapSites(), api.getMapRoutes(), api.getFfvlSites()]);
  if (token !== routeToken) return;
  const mapView = buildExplorer(rows, api.getTraces, sites, routes, { sites: ffvl, info: api.getFfvlInfo });
  show(
    h('h1', null, 'Take-off map'),
    h('p', { class: 'sub' }, 'Where pilots took off after the climb, and the ways up on foot. The warmer the colour, the more outings.'),
    mapView.element);
  requestAnimationFrame(() => mapView.start());
}

async function pageOuting(token, id) {
  setNav(null);   // an outing belongs to no entry of the menu
  const o = await api.getOuting(id);
  if (token !== routeToken) return;
  if (!o) return show(notice('error', h('p', null, 'This outing does not exist, or is not public.')));
  const mine = api.state.user && api.state.user.id === o.user_id;
  const actions = h('div', { class: 'row' });
  if (o.status === 'published' && o.trace) {
    actions.append(h('button', { onclick: () => downloadText(`${outingTitle(o).replace(/[^\w-]+/g, '_')}.gpx`, trackToGpx(o.trace, outingTitle(o)), 'application/gpx+xml') }, 'Download GPX'));
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
      h('h1', null, outingTitle(o)),
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

// A pilot's page. `path` is the address the filters and the order live in: "user/<id>", or "" for My H&Fs.
async function pageUser(token, id, opts = {}) {
  // The entry "My H&Fs" is lit on one's own page, and only there.
  setNav(api.state.user && api.state.user.id === id ? 'home' : null);
  const [profile, rows] = await Promise.all([api.getProfile(id), api.listUserOutings(id)]);
  if (token !== routeToken) return;
  if (!profile) return show(notice('error', h('p', null, 'This page does not exist.')));
  const section = await outingsSection(token, { path: opts.path != null ? opts.path : `user/${id}`, userId: id, showPilot: false, empty: h('p', null, 'No published outing for these filters.') });
  if (!section) return;
  const mine = api.state.user && api.state.user.id === id;
  // The totals follow the year and country filters, like the list below them.
  const q = query();
  const published = rows.filter((r) => r.status === 'published'
    && (!q.year || String(r.outing_date || '').slice(0, 4) === String(q.year))
    && (!q.country || r.country_code === q.country));
  const sum = (k) => published.reduce((a, r) => a + (r[k] || 0), 0);
  const others = rows.filter((r) => r.status !== 'published');

  const nodes = [
    h('h1', null, pilotName(profile)),
    h('div', { class: 'stats' },
      stat(fmtInt(published.length), 'Outings'),
      stat(fmtInt(sum('score')), 'Total score', true),
      stat(`${fmtInt(sum('dplus_m'))} m`, 'D+ on foot'),
      stat(`${fmtInt(sum('dminus_m'))} m`, 'D− in flight'),
      stat(fmtKm(sum('walk_km')), 'Distance on foot'),
      stat(fmtKm(sum('flight_path_km')), 'Total distance on flight')),
  ];
  if (mine && !profile.display_name) nodes.push(nameForm('Choose the name shown next to your outings'));
  if (mine && others.length) {
    nodes.push(h('h2', null, 'Waiting or not counted'),
      table(listHeaders({ showPilot: false, showStatus: true }), others.map((r) => h('tr', null,
        h('td', null, fmtDate(r.outing_date) === '–' ? fmtDate(r.created_at) : fmtDate(r.outing_date)),
        h('td', { class: 'wrap' }, r.status === 'rejected' ? (r.reject_reason || 'Not counted') : 'Uploaded track'),
        h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''),
        h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''),
        h('td', null, statusBadge(r), ' ', h('button', { class: 'link', onclick: async () => {
          if (!confirm('Delete this upload?')) return;
          try { await api.deleteOuting(r); pageUser(++routeToken, id, opts).catch(fail); } catch (e) { fail(e); }
        } }, 'Delete'))))));
  }
  nodes.push(h('h2', null, 'Outings'), section);
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

// Tracks refused because they hold no flight, kept in memory (the files cannot go in the address) so the list
// survives a visit to the marking tool and back. Emptied when new files are chosen.
let noFlight = [];
let refusedBox = null;     // where the list is drawn on the Upload page
let markTarget = null;     // the entry the marking tool works on

function renderNoFlight() {
  if (!refusedBox) return;
  if (!noFlight.length) { refusedBox.replaceChildren(); return; }
  refusedBox.replaceChildren(
    h('h2', null, `Without a flight (${noFlight.length})`),
    h('p', { class: 'hint' }, 'No flight was found in these tracks, so they do not count. If one of them does hold a flight, mark it yourself on the map.'),
    ...noFlight.map((it) => h('div', { class: 'refused-item' },
      h('div', { class: 'why' }, h('b', null, fileLabel(it.file)), h('p', { class: 'hint' }, it.message)),
      h('a', { class: 'button', href: '#/mark', onclick: () => { markTarget = it; } }, 'Mark the flight by hand'))));
}

/** The name of a track: a File, or the Files of one outing in several files (« a.gpx + b.gpx »). */
const fileLabel = (f) => (Array.isArray(f) ? f.map((x) => x.name).join(' + ') : f.name);

/** Remember a refused track when the reason is that it holds no flight (res: the result of the analysis). ``file``
 * is a File, or the Files of one outing in several files: the flight is then marked on the joined track. */
function noteNoFlight(file, res) {
  const o = res.outing;
  if (o.status === 'ok' || o.reason !== 'no_flight' || !res.trace) return;
  if (noFlight.some((it) => it.file === file)) return;
  noFlight.push({ file, res, message: refusalText(o) });
  renderNoFlight();
}


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
  refusedBox = h('div', { id: 'refused', class: 'refused' });
  const input = h('input', { type: 'file', id: 'track', accept: '.igc,.gpx,.kml,.tcx,.fit', multiple: true });
  const drop = h('div', { class: 'drop', id: 'drop' },
    h('p', null, h('b', null, 'Drop your tracks here'), ' or choose one or several files'),
    h('p', null, input),
    h('p', { class: 'hint' }, `IGC, GPX, KML, TCX or FIT with timestamps and altitude, up to ${CONFIG.MAX_FILE_MB} MB each. The analysis runs in your browser: a single file is sent only when you publish it.`),
    h('p', { class: 'hint' }, `One outing in several files (a bike ride to the start, the climb and flight, the ride home): drop them together, they are offered to be joined.`),
    h('p', { class: 'hint' }, `Several files at once: each one is analysed and, by default, published as soon as it is ready. Keep the page open until the list is finished. At most 20 uploads per day, and up to 1,000 per day during the first two weeks of your account.`),
    h('p', { class: 'hint' }, h('b', null, 'Original file only. '), 'Send the recording exactly as your device or app saved it. Do not edit it, merge it or correct its elevation with a track tool: flight altitudes must be the measured ones, not adjusted to the terrain. Such tracks are refused, unless you mark the flight by hand afterwards.'));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files[0]) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event('change')); }
  });
  input.addEventListener('change', () => {
    const files = Array.from(input.files);
    noFlight = [];
    renderNoFlight();
    if (files.length === 1) analyse(files[0], out).catch(fail);
    else if (files.length > 1) analyseBatch(files, out).catch(fail);
  });
  show(h('h1', null, 'Upload a track'), drop, h('p', null, engineMsg), out, refusedBox);
  renderNoFlight();
  startEngine().catch(() => {});
  window.addEventListener('hashchange', unsubscribe, { once: true });
}

async function analyse(file, out) {
  out.replaceChildren(h('p', { class: 'hint pad', id: 'busy' }, 'Analysing…'));
  if (file.size > CONFIG.MAX_FILE_MB * 1024 * 1024) {
    return out.replaceChildren(notice('error', h('p', null, `This file is larger than ${CONFIG.MAX_FILE_MB} MB. Export only this activity, not a whole year.`)));
  }
  let res;
  try {
    res = await analyseFile(file);
    res = await checkTerrain(res);
  } catch (e) {
    return out.replaceChildren(notice('error', h('p', null, e.message)));
  }
  const o = res.outing;
  noteNoFlight(file, res);
  const places = await lookUpPlaces(o);
  const pv = previewRow(res, places);

  const verdict = o.status === 'ok'
    ? notice('ok', h('p', null, h('b', null, `${fmtInt(o.score)} points`), ` — ${fmtInt(o.dplus_m)} m climbed on foot and ${fmtInt(o.dminus_m)} m flown down.`))
    : notice('error', h('p', null, refusalText(o)));
  const others = (o.warnings || []).filter((w) => w !== o.reason_text);
  if (o.status !== 'ok' && others.length) verdict.append(h('p', { class: 'hint' }, others.join(' · ')));
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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Why the outing does not count and what to do: written by the engine (src/mbhf/advice.py), as on the server. */
function refusalText(o) {
  if (o.reason_text) return o.reason_text;
  if (o.reason === 'no_flight') {
    return (o.warnings || []).some((w) => w.includes('follows the ground')) ? 'The descent follows the ground (ski, bike or run): no flight' : 'No flight found';
  }
  return 'Less than 200 m climbed on foot';
}

/**
 * Several files at once. Each is analysed in the browser (the same steps as a single file). By default each
 * outing that counts is published as soon as it is analysed, so a long batch loses nothing if the page is
 * closed; untick the box to review the whole list first and publish with one click at the end.
 */
async function analyseBatch(fileList, out) {
  const files = fileList.slice().sort((a, b) => a.name.localeCompare(b.name));
  // files that follow one another (a ride to the start, the climb and flight, the ride home) make one outing
  // if the pilot agrees (src/mbhf/multi.py)
  let units = files.map((f) => [f]);
  out.replaceChildren(h('p', { class: 'hint pad', id: 'busy' }, 'Looking for files that make one outing…'));
  try {
    const groups = await groupFiles(files);
    if (groups.some((g) => g.length > 1)) units = await confirmGroups(groups.map((g) => g.map((k) => files[k])), out);
  } catch (_) { /* not essential: each file is then an outing of its own */ }
  const items = units.map((parts) => ({
    file: parts.length === 1 ? parts[0] : parts, parts, state: 'waiting', pv: null,
    cells: { name: h('td', { class: 'wrap file-cell' }), title: h('td', { class: 'hide-narrow' }), result: h('td', { class: 'wrap' }, 'Waiting'), score: h('td', { class: 'num' }), dplus: h('td', { class: 'num' }), dminus: h('td', { class: 'num' }), notes: h('div', { class: 'hint note-line' }) },
  }));
  for (const it of items) it.cells.name.append(h('div', null, it.parts.map((f) => f.name).join(' + ')), it.cells.notes);
  const set = (it, state, text, kind) => {
    it.state = state;
    it.cells.result.replaceChildren(text);
    it.cells.result.className = kind || '';
  };
  const summary = h('p', { role: 'status', id: 'batch-summary' }, `Preparing ${items.length} files…`);
  const auto = h('input', { type: 'checkbox', id: 'send-as-you-go', checked: true });
  const publish = h('button', { class: 'primary', id: 'publish-all', disabled: true }, 'Publish');
  const status = h('span', { class: 'hint', role: 'status' });
  const grid = table(
    [{ label: 'File and notes' }, { label: 'Outing', cls: 'hide-narrow' }, { label: 'Result' }, { label: 'Score', num: true }, { label: 'D+ (m)', num: true }, { label: 'D− (m)', num: true }],
    items.map((it) => h('tr', null, it.cells.name, it.cells.title, it.cells.result, it.cells.score, it.cells.dplus, it.cells.dminus)));
  out.replaceChildren(
    summary,
    h('label', { class: 'row', for: 'send-as-you-go' }, auto, ' Publish each outing as soon as it is analysed (recommended for long lists: nothing is lost if you close the page)'),
    h('p', { class: 'hint' }, 'By publishing you agree that these tracks — map, profile and statistics — are shown publicly. The original files stay private. Each result is computed again on our side before it is confirmed. There is a daily limit on uploads: if it is reached, the rest is kept in the list so you can send those files again tomorrow. Keep this page open until the list is finished.'),
    h('div', { class: 'publish-bar' }, h('div', { class: 'row' }, publish, status)), grid);
  const alive = () => out.isConnected;
  let busy = true;
  const warn = (ev) => { if (busy) { ev.preventDefault(); ev.returnValue = ''; } };
  window.addEventListener('beforeunload', warn);
  const finish = () => { busy = false; window.removeEventListener('beforeunload', warn); };
  let limitReached = false;

  // Send one analysed outing; a duplicate or the daily limit are reported in the list, not thrown.
  const send = async (it) => {
    if (limitReached) { set(it, 'unsent', 'Not sent: daily limit reached. Send this file again tomorrow.', 'warn-text'); return false; }
    set(it, 'busy', 'Publishing…');
    try {
      const id = await api.submitTrack(it.file, null, it.pv);
      set(it, 'published', '', 'ok-text');
      it.cells.result.append(link(`#/outing/${id}`, 'Published'));
      return true;
    } catch (e) {
      if (/already submitted/i.test(e.message)) set(it, 'duplicate', 'Already submitted before', 'warn-text');
      else if (/flight is already in/i.test(e.message)) set(it, 'duplicate', e.message, 'warn-text');
      else if (/daily upload limit/i.test(e.message)) { limitReached = true; set(it, 'unsent', 'Not sent: daily limit reached. Send this file again tomorrow.', 'warn-text'); }
      else set(it, 'error', e.message, 'error-text');
      return false;
    }
  };

  // 0. skip what this account has already sent (a restarted batch picks up where it stopped)
  try {
    const hashes = await Promise.all(items.map(async (it) => {
      const own = await Promise.all(it.parts.map(async (f) => api.sha256Hex(await f.arrayBuffer())));
      it.hash = own.length === 1 ? own[0] : await api.combinedSha256(own);
      return it.hash;
    }));
    const sent = await api.alreadySent(hashes);
    for (const it of items) if (sent.has(it.hash)) { set(it, 'duplicate', 'Already submitted before', 'warn-text'); it.cells.score.textContent = '–'; }
  } catch (_) { /* not essential */ }
  const todo = items.filter((it) => it.state === 'waiting');

  // 1. analyse, one file after the other (the map service asks for a pause between requests)
  let n = 0;
  for (const it of todo) {
    if (!alive()) { finish(); return; }
    n += 1;
    summary.textContent = `Analysing file ${n} of ${todo.length}…`;
    set(it, 'busy', 'Analysing…');
    try {
      if (it.parts.some((f) => f.size > CONFIG.MAX_FILE_MB * 1024 * 1024)) throw new Error(`Larger than ${CONFIG.MAX_FILE_MB} MB: export only this activity, not a whole year`);
      let res = it.parts.length === 1 ? await analyseFile(it.file) : await analyseFiles(it.parts);
      res = await checkTerrain(res);
      const o = res.outing;
      it.cells.dplus.textContent = fmtInt(o.dplus_m);
      it.cells.dminus.textContent = fmtInt(o.dminus_m);
      if (o.status === 'ok') {
        const places = await lookUpPlaces(o);
        await sleep(1100);
        it.pv = previewRow(res, places);
        it.cells.title.textContent = it.pv.title;
        it.cells.score.textContent = fmtInt(o.score);
        set(it, 'ready', 'Ready', 'ok-text');
        if (auto.checked) await send(it);
      } else {
        it.cells.score.textContent = '–';
        noteNoFlight(it.file, res);
        set(it, 'refused', `Not counted: ${refusalText(o)}`, 'warn-text');
      }
      // the notes folded under « 12 notes »: an outing in several files has many (pauses, rides, gaps)
      const notes = o.warnings || [];
      it.cells.notes.replaceChildren(...(notes.length ? [h('details', null,
        h('summary', null, `${notes.length} note${notes.length > 1 ? 's' : ''}`),
        h('ul', null, notes.map((n) => h('li', null, n))))] : []));
    } catch (e) {
      set(it, 'error', e.message || 'This file could not be analysed.', 'error-text');
    }
  }
  finish();
  const count = (st) => items.filter((it) => it.state === st).length;
  const describe = () => [
    h('b', null, `${count('published')} published`),
    ` · ${count('ready')} ready to publish · ${count('refused')} not counted · ${count('duplicate')} already submitted · ${count('unsent')} not sent (daily limit) · ${count('error')} with a problem.`,
    count('published') ? ' The server now checks each result: the "Validation pending" badge disappears within a few minutes once it is confirmed.' : '',
  ];
  summary.replaceChildren(...describe());

  // 2. publish what is still waiting (the box was unticked, or a send failed)
  const waiting = () => items.filter((it) => it.state === 'ready');
  if (!waiting().length) return;
  publish.textContent = `Publish ${waiting().length} outing${waiting().length > 1 ? 's' : ''}`;
  publish.disabled = false;
  publish.addEventListener('click', async () => {
    publish.disabled = true;
    busy = true;
    window.addEventListener('beforeunload', warn);
    const list = waiting();
    let k = 0;
    for (const it of list) {
      if (!alive()) { finish(); return; }
      k += 1;
      status.textContent = `Publishing ${k} of ${list.length}…`;
      await send(it);
    }
    finish();
    status.textContent = '';
    summary.replaceChildren(...describe());
  });
}

/** Ask whether the files that follow one another make one outing (one box per group, ticked). Resolves to the
 * outings to analyse: each a list of Files in time order. */
function confirmGroups(groups, out) {
  const fmt = (f) => f.name;
  const boxes = [];
  const rows = groups.filter((g) => g.length > 1).map((g, k) => {
    const box = h('input', { type: 'checkbox', id: `join-${k}`, checked: true });
    boxes.push([box, g]);
    return h('li', null, h('label', { for: `join-${k}` }, box, ` Join as one outing: ${g.map(fmt).join(' → ')}`));
  });
  return new Promise((resolve) => {
    const go = h('button', { class: 'primary', id: 'join-continue' }, 'Continue');
    go.addEventListener('click', () => {
      const joined = new Set(boxes.filter(([b]) => b.checked).map(([, g]) => g));
      resolve(groups.flatMap((g) => (g.length > 1 && joined.has(g) ? [g] : g.map((f) => [f]))));
    });
    out.replaceChildren(notice('info',
      h('p', null, h('b', null, 'These files follow one another. '), 'Each file starts soon after the previous one ended, close to where it ended: together they can make one outing (for example a bike ride to the start, the climb and the flight, the ride home). The original files are kept and joined again on our side.'),
      h('ul', null, ...rows),
      h('p', null, go)));
  });
}

// ---------------------------------------------------------------- mark flights by hand

function pageHelp() {
  setNav(null);
  show(buildHelp());
}

function pageMark() {
  setNav('upload');
  const item = markTarget;
  if (!api.state.user || !item) {
    return show(h('h1', null, 'Mark a flight by hand'),
      notice('info', h('p', null, 'Choose the track on the ', link('#/upload', 'Upload page'), ' first: the file has to be there for the map.')));
  }
  const result = h('div', { id: 'mark-result' });
  const recalc = h('button', { class: 'primary', id: 'mark-recalc', disabled: true }, 'Recalculate with these flights');
  const tool = buildMarkTool(item.res.trace, (count) => { recalc.disabled = count === 0; });
  recalc.addEventListener('click', async () => {
    recalc.disabled = true;
    result.replaceChildren(h('p', { class: 'hint pad' }, 'Analysing…'));
    try {
      const ranges = tool.ranges();
      const res = await analyseManual(item.file, ranges); // no ground check: the marking overrides it
      const o = res.outing;
      if (o.status === 'ok') {
        const places = await lookUpPlaces(o);
        const pv = { ...previewRow(res, places), manual_flights: ranges };
        const publish = h('button', { class: 'primary', id: 'mark-publish' }, 'Publish this outing');
        const status = h('span', { class: 'hint', role: 'status' });
        publish.addEventListener('click', async () => {
          publish.disabled = true;
          try {
            const id = await api.submitTrack(item.file, (t) => { status.textContent = t; }, pv);
            noFlight = noFlight.filter((it) => it !== item);
            result.replaceChildren(notice('ok', h('p', null, 'Published with the flights you marked. The server uses them too when it checks the result: the "Validation pending" badge disappears within a few minutes.'),
              h('p', null, link(`#/outing/${id}`, 'See your outing'), ' · ', link('#/upload', 'Back to the list'))));
          } catch (e) {
            status.textContent = '';
            publish.disabled = false;
            result.prepend(notice('error', h('p', null, e.message)));
          }
        });
        result.replaceChildren(
          notice('ok', h('p', null, h('b', null, `${fmtInt(o.score)} points`), ` — ${fmtInt(o.dplus_m)} m climbed on foot and ${fmtInt(o.dminus_m)} m flown down.`)),
          h('div', { class: 'publish-bar' },
            h('div', { class: 'row' }, publish, status),
            h('p', { class: 'hint' }, 'Not published yet. By publishing you agree that this track — map, profile and statistics — is shown publicly. The original file stays private. Your marked flights are published with it and are not checked against the ground.')));
      } else {
        result.replaceChildren(notice('error', h('p', null, refusalText(o))));
      }
    } catch (e) {
      result.replaceChildren(notice('error', h('p', null, e.message)));
    }
    recalc.disabled = tool.ranges().length === 0;
  });
  show(h('h1', null, 'Mark a flight by hand'),
    h('p', null, h('b', null, fileLabel(item.file)), ' — ', item.message),
    h('p', { class: 'hint' }, 'The track is drawn in green on foot, orange in flight and grey in a vehicle. Click the take-off, then the landing: the stretch between them becomes a flight (in blue). Your marking overrides the automatic ground check, so a track whose altitudes were flattened onto the terrain can still be entered: only mark what was really a flight.'),
    tool.element,
    h('div', { class: 'row' }, recalc, link('#/upload', 'Back to the list')),
    result);
  tool.start();
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
    // « {take-off} from {start} », made by the engine (src/mbhf/titles.py); the server then names the take-off of the register
    title: pl.title || (pl.takeoff && pl.takeoff.kind === 'site' && pl.takeoff.name) || (pl.summit && pl.summit.name) || pl.start_place || 'Hike & Fly outing', // shown through outingTitle()
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
    window.turnstile.render(box, { sitekey: CONFIG.TURNSTILE_SITE_KEY, theme: 'dark', callback: onToken, 'expired-callback': () => onToken('') });
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
  document.body.classList.toggle('wide', path[0] === 'map');
  try {
    if (path[0] === '') { loading(); await pageMine(token); }
    else if (path[0] === 'all') { loading(); await pageAll(token); }
    else if (path[0] === 'ranking') { loading(); await pageRanking(token); }
    else if (path[0] === 'map') { loading(); await pageMap(token); }
    else if (path[0] === 'outing' && path[1]) { loading(); await pageOuting(token, path[1]); }
    else if (path[0] === 'user' && path[1]) { loading(); await pageUser(token, path[1]); }
    else if (path[0] === 'upload') await pageUpload();
    else if (path[0] === 'mark') pageMark();
    else if (path[0] === 'help') pageHelp();
    else if (path[0] === 'login') pageLogin();
    else { location.hash = '#/'; }
  } catch (err) {
    if (token === routeToken) fail(err);
  }
}

(async function main() {
  renderFooter();
  let homeUser = null;     // who My H&Fs was drawn for: it is drawn again only when that changes
  api.onSession(() => {
    renderAccount();
    const here = (location.hash.replace(/^#\/?/, '').split('/')[0]);
    const id = api.state.user ? api.state.user.id : null;
    if (here === 'login' || here === 'upload' || (here === 'user' && api.state.user) || (here === '' && id !== homeUser)) route();
    homeUser = id;
  });
  await api.refreshSession();
  homeUser = api.state.user ? api.state.user.id : null;
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
