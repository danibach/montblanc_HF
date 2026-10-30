// The site: a small single-page app. Routes are in the address after "#".
//   #/                 Home: the question and a search, the map, the latest outings, chained take-offs, sectors
//   #/me               My H&Fs: the signed-in person's own outings (filter by year and country)
//   #/all              All: the outings of everyone (filter by year and country)
//   #/outing/<id>      one outing: map, profile, numbers
//   #/user/<id>        a participant: statistics and outings
//   #/ranking          the pilots and their totals (by year or all time); no ranking: H&F Tracks is a library of outings.
//                      Out of the menu for now (Sarah, 30 October 2026): the community comes later
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
import { buildHome } from './home.js';
import { drawCardMaps, outingCard } from './cards.js';
import { $, h, notice, table, fmtInt, fmtKm, fmtDur, fmtDate, pilotName, outingTitle, placeName } from './util.js';
import { LANGS, getLang, initI18n, onLang, setLang, t, tr } from './i18n.js';

const view = $('#view');
let routeToken = 0;       // a slow answer for a page we already left must not draw over the new page

// ---------------------------------------------------------------- shell

// Signed in, the header is lighter (Sarah, 30 October 2026): the pilot's name opens a menu with their page, the
// language and « Sign out »; signed out, « Sign in » and the language stay in sight.
function renderAccount() {
  const box = $('#account');
  box.replaceChildren();
  if (api.state.user) {
    const name = api.state.profile && api.state.profile.display_name;
    const menu = h('details', { class: 'nav-more account-menu' },
      h('summary', null, name || t('account.yourPage')),
      h('div', { class: 'nav-menu' },
        h('a', { href: '#/me' }, t('account.yourPage')),
        h('label', { class: 'menu-lang' }, h('span', null, t('lang.label')), langSelect()),
        h('button', { class: 'link', onclick: async () => { await api.signOut(); location.hash = '#/'; } }, t('account.signOut'))));
    // a choice in the menu closes it
    menu.querySelector('.nav-menu').addEventListener('click', (ev) => { if (ev.target.closest('a, button')) menu.open = false; });
    box.append(menu);
  } else {
    box.append(h('a', { href: '#/login' }, t('account.signIn')));
  }
  renderLangPick();
}

/** The language selector. The names are written in their own language, so each can be found. */
function langSelect() {
  const select = h('select', { 'aria-label': t('lang.label'), title: t('lang.label') },
    LANGS.map((l) => h('option', { value: l.code, lang: l.code, selected: l.code === getLang() }, l.name)));
  select.addEventListener('change', () => setLang(select.value, { save: true }));
  return select;
}

/** The language in the header, for a visitor who is not signed in (signed in: in the menu of their name). */
function renderLangPick() {
  const pick = $('#lang-pick');
  if (api.state.user) pick.replaceChildren();
  else pick.replaceChildren(Object.assign(langSelect(), { id: 'lang' }));
}

/** The texts of index.html (menu, loading line): marked data-i18n, in English there as a fallback without script. */
function renderStatic() {
  for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll('[data-i18n-label]')) el.setAttribute('aria-label', t(el.dataset.i18nLabel));
}

function renderFooter() {
  const f = $('#footer');
  const lines = [
    h('p', null, t('footer.public')),
    h('p', null, t('footer.sources')),
  ];
  if (CONFIG.CONTACT_EMAIL) {
    lines.push(h('p', null, tr('footer.remove', { mail: h('a', { href: `mailto:${CONFIG.CONTACT_EMAIL}` }, CONFIG.CONTACT_EMAIL) })));
  }
  f.replaceChildren(...lines);
}

function setNav(name) {
  for (const a of document.querySelectorAll('#nav a, #cta')) {
    if (a.dataset.route === name) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  // « Explore » is lit when one of its entries is, and closes once an entry is picked
  const more = $('#nav-more');
  more.classList.toggle('on', !!more.querySelector('a[aria-current]'));
  more.open = false;
}

function show(...nodes) {
  view.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
}

function loading() {
  show(h('p', { class: 'hint pad' }, t('common.loading')));
}

function fail(err) {
  show(notice('error', h('p', null, (err && err.message) || t('common.error'))));
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
    { lat: o.start_lat, lon: o.start_lon, alt: o.start_alt, label: t('detail.startFoot'), colour: '#2b6cb0' },
    { lat: o.summit_lat, lon: o.summit_lon, alt: o.summit_alt, label: o.summit_name || t('detail.summit'), colour: '#3f8f46' },
    { lat: o.takeoff_lat, lon: o.takeoff_lon, alt: o.takeoff_alt, label: t('detail.takeoff'), colour: '#e0552b' },
    { lat: o.landing_lat, lon: o.landing_lon, alt: o.landing_alt, label: t('detail.landing'), colour: '#7b3fa0' },
  ]) : null;
  const detail = h('div', null,
    h('div', { class: 'stats' },
      stat(`${fmtInt(o.dplus_m)} m`, t('stat.dplus'), true),
      stat(`${fmtInt(o.dminus_m)} m`, t('stat.dminus'), true),
      stat(fmtKm(o.walk_km), t('stat.walk')),
      stat(fmtKm(o.flight_free_km), t('stat.freeFai')),
      stat(fmtDur(o.duration_s), t('stat.duration'))),
    h('dl', { class: 'places' },
      place(t('detail.startFoot'), [placeName(o.start_place), o.start_commune && o.start_commune !== o.start_place ? o.start_commune : null].filter(Boolean).join(', ') || coords(o.start_lat, o.start_lon)),
      place(t('detail.summit'), `${o.summit_name || coords(o.summit_lat, o.summit_lon) || '–'}${o.summit_alt != null ? ` · ${fmtInt(o.summit_alt)} m` : ''}`),
      place(t('detail.takeoff'), `${o.takeoff_name || coords(o.takeoff_lat, o.takeoff_lon) || '–'}${o.takeoff_alt != null ? ` · ${fmtInt(o.takeoff_alt)} m` : ''}`),
      place(t('detail.country'), o.country_name || o.country_code)),
    mapView ? mapView.element : null,
    trace ? legend() : null,
    trace ? buildProfile(trace) : null);
  if (mapView) requestAnimationFrame(() => mapView.start());
  return detail;
}

function outingRows(rows, { showPilot = true, showStatus = false } = {}) {
  return rows.map((r) => h('tr', null,
    h('td', null, fmtDate(r.outing_date)),
    showPilot ? h('td', null, initials(pilotName(r.profiles)), link(`#/user/${r.user_id}`, pilotName(r.profiles))) : null,
    h('td', { class: 'wrap' }, r.status === 'published' || !showStatus ? link(`#/outing/${r.id}`, outingTitle(r)) : (r.title || t('outing.uploadedTrack')),
      r.status === 'published' && r.verified === false ? [' ', statusBadge(r)] : null),
    h('td', { class: 'num up' }, fmtInt(r.dplus_m)),
    h('td', { class: 'num down' }, fmtInt(r.dminus_m)),
    h('td', { class: 'num' }, fmtDist(r.walk_km)),
    h('td', { class: 'num' }, fmtDist(r.flight_free_km)),
    showStatus ? h('td', null, statusBadge(r)) : null));
}

// A distance in km for the lists, without the unit (the header has it).
function fmtDist(n) {
  return n == null ? '–' : Number(n).toFixed(1);
}

function statusBadge(r) {
  if (r.status === 'pending') return h('span', { class: 'dot pending' }, t('status.processing'));
  if (r.status === 'published' && r.verified === false) return h('span', { class: 'dot pending', title: t('status.pendingHint') }, t('status.pending'));
  if (r.status === 'rejected') return h('span', { class: 'dot rejected', title: r.reject_reason || '' }, t('status.rejected'));
  return h('span', { class: 'dot' }, t('status.published'));
}

function listHeaders({ showPilot = true, showStatus = false } = {}) {
  return [
    { label: t('col.date'), key: 'date' },
    showPilot ? { label: t('col.pilot'), key: 'pilot' } : null,
    { label: t('col.outing'), key: 'outing' },
    { label: t('col.dplus'), key: 'dplus', num: true },
    { label: t('col.dminus'), key: 'dminus', num: true },
    { label: t('col.hike'), key: 'hike', num: true },
    { label: t('col.fly'), key: 'fly', num: true },
    showStatus ? { label: t('col.status') } : null,
  ].filter(Boolean);
}

async function filterBar(current, onChange, { yearLabel } = {}) {
  const f = await api.getFilters();
  const year = h('select', { id: 'f-year' }, h('option', { value: '' }, yearLabel || t('filter.allYears')),
    f.years.map((y) => h('option', { value: y, selected: String(y) === String(current.year || '') }, y)));
  const country = h('select', { id: 'f-country' }, h('option', { value: '' }, t('filter.allCountries')),
    f.countries.map((c) => h('option', { value: c.code, selected: c.code === current.country }, c.name)));
  const change = () => onChange({ year: year.value || '', country: country.value || '' });
  year.addEventListener('change', change);
  country.addEventListener('change', change);
  // one bar of rounded fields, as on the map (Sarah, 30 October 2026); their names stay for screen readers
  year.setAttribute('aria-label', t('filter.year'));
  country.setAttribute('aria-label', t('detail.country'));
  return h('div', { class: 'list-toolbar' }, year, country);
}

/** A pilot's initials in a round badge, before the name in the lists. */
function initials(name) {
  const letters = String(name || '?').split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
  return h('span', { class: 'ini', 'aria-hidden': 'true' }, letters || '?');
}

function query() {
  const q = location.hash.split('?')[1] || '';
  return Object.fromEntries(new URLSearchParams(q));
}

function goFilters(path, { year, country, sort, dir, page, view }) {
  const p = new URLSearchParams();
  if (view === 'list') p.set('view', 'list'); // the cards are the default view, out of the address
  if (year) p.set('year', year);
  if (country) p.set('country', country);
  // The default order (newest first) stays out of the address.
  if (sort && !(sort === 'date' && dir !== 'asc')) { p.set('sort', sort); p.set('dir', dir === 'asc' ? 'asc' : 'desc'); }
  if (page && page > 1) p.set('page', page);
  location.hash = `#/${path}${p.toString() ? `?${p}` : ''}`;
}

// ---------------------------------------------------------------- pages

// The filtered, sortable, paged list of outings (filter bar, table, pager). `path` is the page's address (the
// filters and the order live in it), `userId` limits it to one pilot. With `cards`, the outings are shown as cards
// with their map (as on the home page), and a « Cards | List » switch brings the sortable table. Returns the nodes
// to show, or null when the page has been left or redirected meanwhile.
const CARDS_PER_PAGE = 12;
async function outingsSection(token, { path, userId, showPilot, empty, cards = false }) {
  const q = query();
  const asCards = cards && q.view !== 'list';
  const sort = api.SORT_COLUMNS[q.sort] && !asCards ? q.sort : 'date';
  const dir = q.sort && q.dir === 'asc' ? 'asc' : (q.sort && q.dir === 'desc' ? 'desc' : (sort === 'date' ? 'desc' : 'asc'));
  const page = Math.max(1, parseInt(q.page, 10) || 1);
  const size = asCards ? CARDS_PER_PAGE : CONFIG.PAGE_SIZE;
  // Changing a filter or the order goes back to page 1; the order is kept when a filter changes.
  const go = (extra) => goFilters(path, { year: q.year, country: q.country, sort, dir, view: q.view, ...extra });
  const bar = await filterBar(q, (v) => go({ ...v, page: 1 }));
  if (cards) {
    const pick = (view, label) => h('button', { type: 'button', 'aria-pressed': String((view === 'list') === !asCards),
      onclick: () => go({ view, page: 1, sort: 'date', dir: 'desc' }) }, label);
    bar.append(h('div', { class: 'seg-big view-pick', role: 'group', 'aria-label': t('view.label') }, pick('cards', t('view.cards')), pick('list', t('view.list'))));
  }

  const { rows, total } = await api.listOutings({ userId, year: q.year, country: q.country, sort, dir, offset: (page - 1) * size, limit: size });
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
  const count = h('p', { class: 'hint' }, total ? t('list.range', { from: from + 1, to: from + rows.length, total, n: total }) : '');
  const pager = pages > 1 ? h('nav', { class: 'pager', 'aria-label': t('pager.label') },
    h('button', { disabled: page <= 1, onclick: () => go({ page: page - 1 }) }, t('pager.prev')),
    h('span', { class: 'hint' }, t('pager.page', { page, pages })),
    h('button', { disabled: page >= pages, onclick: () => go({ page: page + 1 }) }, t('pager.next'))) : null;

  if (asCards && total) {
    // an outing the server has not checked yet carries its badge on its card
    const grid = h('div', { class: 'climb-cards all-cards' }, rows.map((r) => outingCard(r, r.verified === false ? statusBadge(r) : null)));
    requestAnimationFrame(() => drawCardMaps(grid, api.getTraces));
    return [bar, grid, count, pager];
  }
  return [bar,
    total
      ? [table(listHeaders({ showPilot }), outingRows(rows, { showPilot }), '', { key: sort, dir, onSort }), count, pager]
      : notice('info', empty)];
}

// All: everyone's outings, as cards (or the table).
async function pageAll(token) {
  setNav('all');
  const section = await outingsSection(token, { path: 'all', showPilot: true, cards: true, empty: h('p', null, t('list.none')) });
  if (section) show(h('h1', null, t('page.all')), h('p', { class: 'sub' }, t(query().view === 'list' ? 'all.sub' : 'all.subCards')), section);
}

// My H&Fs is the pilot page of the signed-in person, at the address "#/me".
async function pageMine(token) {
  const me = api.state.user;
  // Signed out: there is no page of one's own, so the visitor is asked to sign in.
  if (!me) return location.replace(`${location.pathname}#/login`);
  await pageUser(token, me.id, { path: 'me' });
}

// Home: the same for everyone, signed in or not.
async function pageHome(token) {
  setNav('home');
  const [{ rows: latest }, mapRows, sites, routes, flown, ffvl] = await Promise.all([
    api.listOutings({ limit: 6 }), api.getMapOutings(), api.getMapSites(), api.getMapRoutes(), api.getFlownOutings(), api.getFfvlSites()]);
  if (token !== routeToken) return;
  // the outings the server has checked: one waiting for it may still be refused
  const home = buildHome({ latest: latest.filter((o) => o.verified !== false), mapRows, sites, routes, flown, ffvl, loadTraces: api.getTraces });
  show(home.element);
  requestAnimationFrame(() => home.start());
}

async function pageRanking(token) {
  setNav('ranking');
  const q = query();
  const bar = await filterBar(q, (v) => goFilters('ranking', v), { yearLabel: t('filter.allTime') });
  const rows = await api.getRanking({ year: q.year, country: q.country });
  if (token !== routeToken) return;
  // No ranking (Sarah, 29 October 2026: a library of outings, not a challenge): the pilots by name.
  const entries = rows.map((r) => ({ r, name: pilotName(r) })).sort((a, b) => a.name.localeCompare(b.name));
  // one card per pilot (Sarah, 30 October 2026): initials, name, outings, then the climb and the distances
  const cardOf = ({ r, name }) => h('a', { class: 'pilot-card', href: `#/user/${r.user_id}` },
    h('span', { class: 'ini big', 'aria-hidden': 'true' }, initials(name).textContent),
    h('span', { class: 'pc-body' },
      h('b', null, name),
      h('span', { class: 'hint' }, t('unit.outing', { n: r.outings })),
      h('span', { class: 'pc-nums' },
        h('span', { class: 'up' }, `+${fmtInt(r.dplus)} m`), ' · ', h('span', { class: 'down' }, `−${fmtInt(r.dminus)} m`)),
      h('span', { class: 'hint' }, t('rank.kms', { walk: fmtDist(r.walk_km), fly: fmtDist(r.flight_km) }))));
  const tableNode = rows.length ? h('div', { class: 'pilot-cards' }, entries.map(cardOf)) : null;

  // Search a pilot by name: case and accents ignored, every word must be found in the name.
  const fold = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const search = h('input', { type: 'search', id: 'f-pilot', placeholder: t('rank.searchPlaceholder'), autocomplete: 'off', 'aria-label': t('rank.search') });
  const found = h('p', { class: 'hint' });
  const none = h('div', null, notice('info', h('p', null, t('rank.noMatch'))));
  none.hidden = true;
  const apply = () => {
    const words = fold(search.value).split(/\s+/).filter(Boolean);
    const hits = entries.filter((e) => words.every((w) => fold(e.name).includes(w)));
    if (tableNode) {
      tableNode.replaceChildren(...hits.map(cardOf));
      tableNode.hidden = !hits.length;
    }
    none.hidden = !words.length || hits.length > 0;
    found.textContent = words.length && hits.length ? t('rank.found', { hits: hits.length, n: entries.length }) : '';
  };
  search.addEventListener('input', apply);
  // the search in the same bar as the year and country
  if (rows.length) bar.prepend(search);

  show(
    h('h1', null, t('page.ranking')),
    h('p', { class: 'sub' }, t('rank.sub')),
    bar,
    tableNode || notice('info', h('p', null, t('list.none'))),
    found,
    none);
}

async function pageMap(token) {
  setNav('map');
  const [rows, sites, routes, ffvl] = await Promise.all([api.getMapOutings(), api.getMapSites(), api.getMapRoutes(), api.getFfvlSites()]);
  if (token !== routeToken) return;
  const mapView = buildExplorer(rows, api.getTraces, sites, routes, { sites: ffvl, info: api.getFfvlInfo }, api.state.user ? api.state.user.id : null);
  show(mapView.element);
  requestAnimationFrame(() => mapView.start());
}

async function pageOuting(token, id) {
  setNav(null);   // an outing belongs to no entry of the menu
  const o = await api.getOuting(id);
  if (token !== routeToken) return;
  if (!o) return show(notice('error', h('p', null, t('outing.missing'))));
  const mine = api.state.user && api.state.user.id === o.user_id;
  const actions = h('div', { class: 'row' });
  if (o.status === 'published' && o.trace) {
    actions.append(h('button', { onclick: () => downloadText(`${outingTitle(o).replace(/[^\w-]+/g, '_')}.gpx`, trackToGpx(o.trace, outingTitle(o)), 'application/gpx+xml') }, t('outing.downloadGpx')));
  }
  if (mine) {
    actions.append(h('button', { class: 'danger', onclick: async () => {
      if (!confirm(t('outing.confirmDelete'))) return;
      try { await api.deleteOuting(o); location.hash = `#/user/${o.user_id}`; } catch (e) { fail(e); }
    } }, t('common.delete')));
  } else if (api.state.user && o.status === 'published') {
    actions.append(reportForm(o.id));
  }
  const head = h('div', { class: 'headline' },
    h('div', null,
      h('h1', null, outingTitle(o)),
      h('p', { class: 'sub' }, link(`#/user/${o.user_id}`, pilotName(o.profiles)), ` · ${fmtDate(o.outing_date)}`, o.country_name ? ` · ${o.country_name}` : '')),
    o.status !== 'published' || o.verified === false ? statusBadge(o) : null);
  if (o.status === 'pending') {
    return show(head, notice('pending', h('p', null, t('outing.pendingNote'))), actions);
  }
  if (o.status === 'rejected') {
    return show(head, notice('error', h('p', null, o.reject_reason || t('outing.notCounted'))), actions);
  }
  show(head, outingDetail(o), actions,
    (o.warnings && o.warnings.length) ? h('p', { class: 'hint' }, o.warnings.join(' · ')) : null);
}

function reportForm(outingId) {
  const reason = h('input', { type: 'text', maxlength: '500', placeholder: t('report.placeholder'), 'aria-label': t('report.reason') });
  const status = h('span', { class: 'hint' });
  const form = h('form', { class: 'row', onsubmit: async (ev) => {
    ev.preventDefault();
    if (!reason.value.trim()) return;
    try { await api.reportOuting(outingId, reason.value); status.textContent = t('report.thanks'); reason.value = ''; }
    catch (e) { status.textContent = e.message; }
  } }, reason, h('button', null, t('report.button')), status);
  return h('details', null, h('summary', { class: 'hint' }, t('report.summary')), form);
}

// A pilot's page. `path` is the address the filters and the order live in: "user/<id>", or "me" for My H&Fs.
async function pageUser(token, id, opts = {}) {
  setNav(null);   // one's own page is reached from the account bar, not the menu
  const [profile, rows] = await Promise.all([api.getProfile(id), api.listUserOutings(id)]);
  if (token !== routeToken) return;
  if (!profile) return show(notice('error', h('p', null, t('user.missing'))));
  const section = await outingsSection(token, { path: opts.path != null ? opts.path : `user/${id}`, userId: id, showPilot: false, empty: h('p', null, t('list.noneUser')) });
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
      stat(fmtInt(published.length), t('col.outings')),
      stat(`${fmtInt(sum('dplus_m'))} m`, t('stat.dplus')),
      stat(`${fmtInt(sum('dminus_m'))} m`, t('stat.dminus')),
      stat(fmtKm(sum('walk_km')), t('stat.walk')),
      stat(fmtKm(sum('flight_free_km')), t('stat.totalFlight'))),
  ];
  if (mine && !profile.display_name) nodes.push(nameForm(t('name.choose')));
  if (mine && others.length) {
    nodes.push(h('h2', null, t('user.others')),
      table(listHeaders({ showPilot: false, showStatus: true }), others.map((r) => h('tr', null,
        h('td', null, fmtDate(r.outing_date) === '–' ? fmtDate(r.created_at) : fmtDate(r.outing_date)),
        h('td', { class: 'wrap' }, r.status === 'rejected' ? (r.reject_reason || t('status.rejected')) : t('outing.uploadedTrack')),
        h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''),
        h('td', { class: 'num' }, ''), h('td', { class: 'num' }, ''),
        h('td', null, statusBadge(r), ' ', h('button', { class: 'link', onclick: async () => {
          if (!confirm(t('user.confirmDeleteUpload'))) return;
          try { await api.deleteOuting(r); pageUser(++routeToken, id, opts).catch(fail); } catch (e) { fail(e); }
        } }, t('common.delete')))))));
  }
  nodes.push(h('h2', null, t('col.outings')), section);
  if (mine) {
    nodes.push(h('h2', null, t('user.account')),
      h('div', { class: 'card' },
        h('p', { class: 'hint' }, t('user.accountNote', { email: api.state.user.email || '' })),
        h('button', { class: 'danger', onclick: async () => {
          if (!confirm(t('user.confirmDeleteAccount'))) return;
          try { await api.deleteAccount(); location.hash = '#/'; } catch (e) { fail(e); }
        } }, t('user.deleteAccount'))));
  }
  show(nodes);
}

function nameForm(title) {
  const input = h('input', { type: 'text', id: 'display-name', maxlength: '40', minlength: '2', required: true, value: (api.state.profile && api.state.profile.display_name) || '' });
  const msg = h('p', { class: 'hint', role: 'status' });
  return h('form', { class: 'card', onsubmit: async (ev) => {
    ev.preventDefault();
    try { await api.setDisplayName(input.value); msg.textContent = t('name.saved'); route(); } catch (e) { msg.textContent = e.message; }
  } },
    h('label', { for: 'display-name' }, title),
    h('div', { class: 'row' }, input, h('button', { class: 'primary' }, t('common.save'))),
    h('p', { class: 'hint' }, t('name.hint')), msg);
}

// ---------------------------------------------------------------- upload

// Tracks refused because they hold no flight, kept in memory (the files cannot go in the address) so the list
// survives a visit to the marking tool and back. Emptied when new files are chosen.
let noFlight = [];
let refusedBox = null;     // where the list is drawn on the Upload page
let markTarget = null;     // the entry the marking tool works on
let batchBusy = false;     // a batch of files is being analysed or published: a change of language must not redraw the page

function renderNoFlight() {
  if (!refusedBox) return;
  if (!noFlight.length) { refusedBox.replaceChildren(); return; }
  refusedBox.replaceChildren(
    h('h2', null, t('upload.noFlightTitle', { n: noFlight.length })),
    h('p', { class: 'hint' }, t('upload.noFlightNote')),
    ...noFlight.map((it) => h('div', { class: 'refused-item' },
      h('div', { class: 'why' }, h('b', null, fileLabel(it.file)), h('p', { class: 'hint' }, it.message)),
      h('a', { class: 'button', href: '#/mark', onclick: () => { markTarget = it; } }, t('upload.markButton')))));
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
    return show(h('h1', null, t('upload.title')),
      notice('info', h('p', null, tr('upload.needAccount', { link: link('#/login', t('account.signIn')) }))));
  }
  if (!api.state.profile || !api.state.profile.display_name) {
    return show(h('h1', null, t('upload.title')), nameForm(t('upload.chooseName')));
  }
  const engineMsg = h('span', { class: 'hint', role: 'status', id: 'engine-status' }, t('engine.preparing'));
  const unsubscribe = onEngineStatus((text, state) => { engineMsg.textContent = text; engineMsg.dataset.state = state; });
  const out = h('div', { id: 'preview' });
  refusedBox = h('div', { id: 'refused', class: 'refused' });
  const input = h('input', { type: 'file', id: 'track', accept: '.igc,.gpx,.kml,.tcx,.fit', multiple: true });
  const drop = h('div', { class: 'drop', id: 'drop' },
    h('p', null, tr('upload.drop', { b: h('b', null, t('upload.dropBold')) })),
    h('p', null, input),
    h('p', { class: 'hint' }, t('upload.formats', { mb: CONFIG.MAX_FILE_MB })),
    h('p', { class: 'hint' }, t('upload.severalFilesOne')),
    h('p', { class: 'hint' }, t('upload.severalFiles', { day: 20, first: 1000 })),
    h('p', { class: 'hint' }, h('b', null, t('upload.originalBold') + ' '), t('upload.original')));
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
  show(h('h1', null, t('upload.title')), drop, h('p', null, engineMsg), out, refusedBox);
  renderNoFlight();
  startEngine().catch(() => {});
  window.addEventListener('hashchange', unsubscribe, { once: true });
}

async function analyse(file, out) {
  out.replaceChildren(h('p', { class: 'hint pad', id: 'busy' }, t('upload.analysing')));
  if (file.size > CONFIG.MAX_FILE_MB * 1024 * 1024) {
    return out.replaceChildren(notice('error', h('p', null, t('upload.tooBig', { mb: CONFIG.MAX_FILE_MB }))));
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
    ? notice('ok', scoreLine(o))
    : notice('error', h('p', null, refusalText(o)));
  const others = (o.warnings || []).filter((w) => w !== o.reason_text);
  if (o.status !== 'ok' && others.length) verdict.append(h('p', { class: 'hint' }, others.join(' · ')));
  const publish = h('button', { class: 'primary', id: 'publish', disabled: o.status !== 'ok' }, t('upload.publish'));
  const status = h('span', { class: 'hint', role: 'status' });
  publish.addEventListener('click', async () => {
    publish.disabled = true;
    try {
      const id = await api.submitTrack(file, (t) => { status.textContent = t; }, pv);
      out.replaceChildren(notice('ok', h('p', null, t('upload.published')),
        h('p', null, link(`#/outing/${id}`, t('upload.seeOuting')))));
    } catch (e) {
      status.textContent = '';
      publish.disabled = false;
      out.prepend(notice('error', h('p', null, e.message)));
    }
  });
  const actions = h('div', { class: 'publish-bar' },
    h('div', { class: 'row' }, publish, status),
    h('p', { class: 'hint' }, t('upload.consent')));
  out.replaceChildren(...[
    verdict,
    o.status === 'ok' ? actions : null,
    h('h2', null, pv.title),
    outingDetail(pv),
    pv.warnings && pv.warnings.length ? h('p', { class: 'hint' }, pv.warnings.join(' · ')) : null,
  ].filter(Boolean));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** « 1,200 m climbed on foot and 1,100 m flown down. » */
function scoreLine(o) {
  return h('p', null, h('b', null, t('upload.verdictRest', { up: fmtInt(o.dplus_m), down: fmtInt(o.dminus_m) })));
}

/** Why the outing does not count and what to do: written by the engine (src/mbhf/advice.py), as on the server. */
function refusalText(o) {
  if (o.reason_text) return o.reason_text;
  if (o.reason === 'no_flight') {
    return (o.warnings || []).some((w) => w.includes('follows the ground')) ? t('refuse.ground') : t('refuse.noFlight');
  }
  return t('refuse.littleClimb');
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
  out.replaceChildren(h('p', { class: 'hint pad', id: 'busy' }, t('batch.grouping')));
  try {
    const groups = await groupFiles(files);
    if (groups.some((g) => g.length > 1)) units = await confirmGroups(groups.map((g) => g.map((k) => files[k])), out);
  } catch (_) { /* not essential: each file is then an outing of its own */ }
  const items = units.map((parts) => ({
    file: parts.length === 1 ? parts[0] : parts, parts, state: 'waiting', pv: null,
    cells: { name: h('td', { class: 'wrap file-cell' }), title: h('td', { class: 'hide-narrow' }), result: h('td', { class: 'wrap' }, t('batch.waiting')), dplus: h('td', { class: 'num' }), dminus: h('td', { class: 'num' }), notes: h('div', { class: 'hint note-line' }) },
  }));
  for (const it of items) it.cells.name.append(h('div', null, it.parts.map((f) => f.name).join(' + ')), it.cells.notes);
  const set = (it, state, text, kind) => {
    it.state = state;
    it.cells.result.replaceChildren(text);
    it.cells.result.className = kind || '';
  };
  const summary = h('p', { role: 'status', id: 'batch-summary' }, t('batch.preparing', { n: items.length }));
  const auto = h('input', { type: 'checkbox', id: 'send-as-you-go', checked: true });
  const publish = h('button', { class: 'primary', id: 'publish-all', disabled: true }, t('batch.publish'));
  const status = h('span', { class: 'hint', role: 'status' });
  const grid = table(
    [{ label: t('batch.colFile') }, { label: t('col.outing'), cls: 'hide-narrow' }, { label: t('batch.colResult') }, { label: t('col.dplus'), num: true }, { label: t('col.dminus'), num: true }],
    items.map((it) => h('tr', null, it.cells.name, it.cells.title, it.cells.result, it.cells.dplus, it.cells.dminus)));
  out.replaceChildren(
    summary,
    h('label', { class: 'row', for: 'send-as-you-go' }, auto, ' ' + t('batch.auto')),
    h('p', { class: 'hint' }, t('batch.consent')),
    h('div', { class: 'publish-bar' }, h('div', { class: 'row' }, publish, status)), grid);
  const alive = () => out.isConnected;
  batchBusy = true;
  const warn = (ev) => { if (batchBusy) { ev.preventDefault(); ev.returnValue = ''; } };
  window.addEventListener('beforeunload', warn);
  const finish = () => { batchBusy = false; window.removeEventListener('beforeunload', warn); };
  let limitReached = false;

  // Send one analysed outing; a duplicate or the daily limit are reported in the list, not thrown.
  const send = async (it) => {
    if (limitReached) { set(it, 'unsent', t('batch.limit'), 'warn-text'); return false; }
    set(it, 'busy', t('batch.publishing'));
    try {
      const id = await api.submitTrack(it.file, null, it.pv);
      set(it, 'published', '', 'ok-text');
      it.cells.result.append(link(`#/outing/${id}`, t('status.published')));
      return true;
    } catch (e) {
      if (e.code === 'duplicate_file') set(it, 'duplicate', t('batch.duplicate'), 'warn-text');
      else if (e.code === 'duplicate_flight') set(it, 'duplicate', e.message, 'warn-text');
      else if (e.code === 'daily_limit') { limitReached = true; set(it, 'unsent', t('batch.limit'), 'warn-text'); }
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
    for (const it of items) if (sent.has(it.hash)) { set(it, 'duplicate', t('batch.duplicate'), 'warn-text'); }
  } catch (_) { /* not essential */ }
  const todo = items.filter((it) => it.state === 'waiting');

  // 1. analyse, one file after the other (the map service asks for a pause between requests)
  let n = 0;
  for (const it of todo) {
    if (!alive()) { finish(); return; }
    n += 1;
    summary.textContent = t('batch.analysingFile', { n, total: todo.length });
    set(it, 'busy', t('upload.analysing'));
    try {
      if (it.parts.some((f) => f.size > CONFIG.MAX_FILE_MB * 1024 * 1024)) throw new Error(t('batch.tooBig', { mb: CONFIG.MAX_FILE_MB }));
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
        set(it, 'ready', t('batch.ready'), 'ok-text');
        if (auto.checked) await send(it);
      } else {
        noteNoFlight(it.file, res);
        set(it, 'refused', t('batch.notCounted', { reason: refusalText(o) }), 'warn-text');
      }
      // the notes folded under « 12 notes »: an outing in several files has many (pauses, rides, gaps)
      const notes = o.warnings || [];
      it.cells.notes.replaceChildren(...(notes.length ? [h('details', null,
        h('summary', null, t('batch.notes', { n: notes.length })),
        h('ul', null, notes.map((n) => h('li', null, n))))] : []));
    } catch (e) {
      set(it, 'error', e.message || t('engine.fileFailed'), 'error-text');
    }
  }
  finish();
  const count = (st) => items.filter((it) => it.state === st).length;
  const describe = () => [
    h('b', null, t('batch.sumPublished', { n: count('published') })),
    t('batch.sumRest', { ready: count('ready'), refused: count('refused'), duplicate: count('duplicate'), unsent: count('unsent'), error: count('error') }),
    count('published') ? ' ' + t('batch.sumChecked') : '',
  ];
  summary.replaceChildren(...describe());

  // 2. publish what is still waiting (the box was unticked, or a send failed)
  const waiting = () => items.filter((it) => it.state === 'ready');
  if (!waiting().length) return;
  publish.textContent = t('batch.publishN', { n: waiting().length });
  publish.disabled = false;
  publish.addEventListener('click', async () => {
    publish.disabled = true;
    batchBusy = true;
    window.addEventListener('beforeunload', warn);
    const list = waiting();
    let k = 0;
    for (const it of list) {
      if (!alive()) { finish(); return; }
      k += 1;
      status.textContent = t('batch.publishingK', { k, total: list.length });
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
    return h('li', null, h('label', { for: `join-${k}` }, box, ' ' + t('batch.join', { files: g.map(fmt).join(' → ') })));
  });
  return new Promise((resolve) => {
    const go = h('button', { class: 'primary', id: 'join-continue' }, t('common.continue'));
    go.addEventListener('click', () => {
      const joined = new Set(boxes.filter(([b]) => b.checked).map(([, g]) => g));
      resolve(groups.flatMap((g) => (g.length > 1 && joined.has(g) ? [g] : g.map((f) => [f]))));
    });
    out.replaceChildren(notice('info',
      h('p', null, h('b', null, t('batch.followBold') + ' '), t('batch.followText')),
      h('ul', null, ...rows),
      h('p', null, go)));
  });
}

// ---------------------------------------------------------------- mark flights by hand

function pageHelp() {
  setNav('help');
  show(buildHelp());
}

function pageMark() {
  setNav('upload');
  const item = markTarget;
  if (!api.state.user || !item) {
    return show(h('h1', null, t('mark.title')),
      notice('info', h('p', null, tr('mark.needTrack', { link: link('#/upload', t('mark.uploadPage')) }))));
  }
  const result = h('div', { id: 'mark-result' });
  const recalc = h('button', { class: 'primary', id: 'mark-recalc', disabled: true }, t('mark.recalc'));
  const tool = buildMarkTool(item.res.trace, (count) => { recalc.disabled = count === 0; });
  recalc.addEventListener('click', async () => {
    recalc.disabled = true;
    result.replaceChildren(h('p', { class: 'hint pad' }, t('upload.analysing')));
    try {
      const ranges = tool.ranges();
      const res = await analyseManual(item.file, ranges); // no ground check: the marking overrides it
      const o = res.outing;
      if (o.status === 'ok') {
        const places = await lookUpPlaces(o);
        const pv = { ...previewRow(res, places), manual_flights: ranges };
        const publish = h('button', { class: 'primary', id: 'mark-publish' }, t('upload.publish'));
        const status = h('span', { class: 'hint', role: 'status' });
        publish.addEventListener('click', async () => {
          publish.disabled = true;
          try {
            const id = await api.submitTrack(item.file, (t) => { status.textContent = t; }, pv);
            noFlight = noFlight.filter((it) => it !== item);
            result.replaceChildren(notice('ok', h('p', null, t('mark.published')),
              h('p', null, link(`#/outing/${id}`, t('upload.seeOuting')), ' · ', link('#/upload', t('mark.back')))));
          } catch (e) {
            status.textContent = '';
            publish.disabled = false;
            result.prepend(notice('error', h('p', null, e.message)));
          }
        });
        result.replaceChildren(
          notice('ok', scoreLine(o)),
          h('div', { class: 'publish-bar' },
            h('div', { class: 'row' }, publish, status),
            h('p', { class: 'hint' }, t('mark.consent'))));
      } else {
        result.replaceChildren(notice('error', h('p', null, refusalText(o))));
      }
    } catch (e) {
      result.replaceChildren(notice('error', h('p', null, e.message)));
    }
    recalc.disabled = tool.ranges().length === 0;
  });
  show(h('h1', null, t('mark.title')),
    h('p', null, h('b', null, fileLabel(item.file)), ' — ', item.message),
    h('p', { class: 'hint' }, t('mark.help')),
    tool.element,
    h('div', { class: 'row' }, recalc, link('#/upload', t('mark.back'))),
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
    // the highest summit on foot, made by the engine (src/mbhf/titles.py); the server then falls back on the take-off of the register
    title: pl.title || (pl.summit && pl.summit.name) || (pl.takeoff && pl.takeoff.kind === 'site' && pl.takeoff.name) || pl.start_place || 'Hike & Fly outing', // shown through outingTitle()
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
  const submit = h('button', { class: 'primary', disabled: needsCheck }, t('login.send'));
  const form = h('form', { class: 'card', onsubmit: async (ev) => {
    ev.preventDefault();
    submit.disabled = true;
    try {
      await api.sendLink(email.value.trim(), token);
      try { localStorage.setItem('after-login', '#/upload'); } catch (_) { /* ignore */ }
      msg.replaceChildren(notice('ok', h('p', null, t('login.sent', { email: email.value.trim() }))));
    } catch (e) {
      msg.replaceChildren(notice('error', h('p', null, e.message)));
      // a check can be used once: ask for a new one, and wait for it before the next try
      token = '';
      if (window.turnstile) window.turnstile.reset();
    } finally { submit.disabled = needsCheck && !token; }
  } },
    h('label', { for: 'email' }, t('login.email')),
    h('div', { class: 'row' }, email, submit), captcha, msg,
    h('p', { class: 'hint' }, t('login.hint')));
  const nodes = [h('h1', null, t('account.signIn')), form];
  if (CONFIG.GOOGLE_LOGIN) {
    nodes.push(h('div', { class: 'row' }, h('button', { onclick: () => api.signInWithGoogle().catch(fail) }, t('login.google'))));
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
    try { sessionStorage.setItem('signin-error', t('login.expired')); } catch (_) { /* ignore */ }
    history.replaceState(null, '', location.pathname + '#/login');
  }
  const path = (location.hash.replace(/^#\/?/, '').split('?')[0] || '').split('/');
  window.scrollTo(0, 0);
  document.body.classList.toggle('wide', path[0] === 'map');
  try {
    if (path[0] === '') { loading(); await pageHome(token); }
    else if (path[0] === 'me') { loading(); await pageMine(token); }
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
  await initI18n();   // the texts of the visitor's language, before the first page is drawn
  renderStatic();
  renderLangPick();
  renderFooter();
  let homeUser = null;     // who My H&Fs was drawn for: it is drawn again only when that changes
  api.onSession(() => {
    renderAccount();
    const here = (location.hash.replace(/^#\/?/, '').split('/')[0]);
    const id = api.state.user ? api.state.user.id : null;
    if (here === 'login' || here === 'upload' || (here === 'user' && api.state.user) || (here === 'me' && id !== homeUser)) route();
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
  // a change of language redraws the shell and the page; a batch of files in progress is not wiped (its page is
  // drawn again with the next visit)
  onLang(() => {
    renderStatic();
    renderLangPick();
    renderAccount();
    renderFooter();
    if (!batchBusy) route();
  });
  route();
})();
