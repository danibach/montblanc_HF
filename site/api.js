// Everything that talks to Supabase: sign-in, reading outings, uploading a track, deleting.

import { CONFIG } from './config.js';

const BUCKET = 'track-files';

export const sb = window.supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_PUBLISHABLE_KEY, {
  auth: { flowType: 'pkce', detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
});

function check({ data, error }) {
  if (error) throw new Error(error.message || 'Request failed');
  return data;
}

// ---------- session

export const state = { user: null, profile: null };
const subscribers = new Set();
export const onSession = (fn) => subscribers.add(fn);

export async function refreshSession() {
  const before = state.user ? state.user.id : null;
  const beforeName = state.profile ? state.profile.display_name : null;
  const { data } = await sb.auth.getSession();
  state.user = data.session ? data.session.user : null;
  state.profile = null;
  if (state.user) {
    const { data: p } = await sb.from('profiles').select('id,display_name').eq('id', state.user.id).maybeSingle();
    state.profile = p || { id: state.user.id, display_name: null };
  }
  // Supabase fires "signed in" again each time the tab comes back to the front. Tell the pages only when
  // something really changed: re-drawing the Upload page would wipe a batch in progress.
  const after = state.user ? state.user.id : null;
  const afterName = state.profile ? state.profile.display_name : null;
  if (after !== before || afterName !== beforeName) subscribers.forEach((f) => f());
}

sb.auth.onAuthStateChange((event) => {
  if (event === 'SIGNED_IN' || event === 'SIGNED_OUT' || event === 'USER_UPDATED') {
    // do not call Supabase from inside this callback: schedule it
    setTimeout(refreshSession, 0);
  }
});

export async function sendLink(email, captchaToken) {
  const options = { emailRedirectTo: location.origin + location.pathname };
  if (captchaToken) options.captchaToken = captchaToken;
  check(await sb.auth.signInWithOtp({ email, options }));
}

export async function signInWithGoogle() {
  check(await sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: location.origin + location.pathname } }));
}

export async function signOut() {
  await sb.auth.signOut();
}

export async function setDisplayName(name) {
  const clean = name.replace(/\s+/g, ' ').trim();
  if (clean.length < 2 || clean.length > 40) throw new Error('The name must have 2 to 40 characters.');
  const { error } = await sb.from('profiles').update({ display_name: clean }).eq('id', state.user.id);
  if (error) {
    if (error.code === '23505') throw new Error('This name is already taken.');
    throw new Error(error.message);
  }
  await refreshSession();
}

// ---------- reading

const LIST_COLUMNS =
  'id,title,summit_alt,outing_date,country_code,country_name,dplus_m,dminus_m,score,flight_free_km,flight_path_km,walk_km,user_id,status,verified,reject_reason,profiles(display_name)';

// The columns the home list can be sorted by (a name from the address -> the database column).
export const SORT_COLUMNS = {
  date: 'outing_date',
  pilot: 'profiles(display_name)',
  outing: 'title',
  country: 'country_name',
  dplus: 'dplus_m',
  dminus: 'dminus_m',
  hike: 'walk_km',
  fly: 'flight_free_km',
  score: 'score',
};

export async function getFilters() {
  const { data, error } = await sb.rpc('outing_filters');
  if (error) throw new Error(error.message);
  return data || { years: [], countries: [] };
}

function yearRange(q, year) {
  return year ? q.gte('outing_date', `${year}-01-01`).lte('outing_date', `${year}-12-31`) : q;
}

export async function listOutings({ userId, year, country, sort = 'date', dir = 'desc', offset = 0, limit = CONFIG.PAGE_SIZE }) {
  let q = sb.from('outings').select(LIST_COLUMNS, { count: 'exact' }).eq('status', 'published').eq('hidden', false);
  q = yearRange(q, year);
  if (userId) q = q.eq('user_id', userId);
  if (country) q = q.eq('country_code', country);
  const column = SORT_COLUMNS[sort] || SORT_COLUMNS.date;
  // Empty values go last in both directions; the date and the id then keep the pages stable.
  const { data, error, count } = await q
    .order(column, { ascending: dir === 'asc', nullsFirst: false })
    .order('outing_date', { ascending: false })
    .order('id', { ascending: true })
    .range(offset, offset + limit - 1);
  if (error) throw new Error(error.message);
  return { rows: data || [], total: count || 0 };
}

export async function getOuting(id) {
  const { data, error } = await sb.from('outings').select('*,profiles(id,display_name)').eq('id', id).maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function getProfile(id) {
  const { data, error } = await sb.from('profiles').select('id,display_name').eq('id', id).maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function listUserOutings(userId) {
  const { data, error } = await sb
    .from('outings')
    .select(LIST_COLUMNS + ',created_at,file_path')
    .eq('user_id', userId)
    .order('outing_date', { ascending: false, nullsFirst: true })
    .order('created_at', { ascending: false })
    .limit(1000);
  if (error) throw new Error(error.message);
  return data || [];
}

const MAP_FIELDS = ['id', 'takeoff_lat', 'takeoff_lon', 'takeoff_alt', 'takeoff_name', 'title', 'outing_date',
  'dplus_m', 'walk_km', 'start_place', 'pilot', 'summit_alt', 'user_id', 'climb', 'takeoff_site_id', 'takeoff_site_status', 'route_id'];
const SITE_FIELDS = ['id', 'name', 'lat', 'lon', 'alt', 'source', 'wind_ok', 'hike_and_fly'];
const ROUTE_FIELDS = ['id', 'site_id', 'name', 'line'];

const FFVL_FIELDS = ['id', 'name', 'lat', 'lon', 'alt', 'kind', 'status', 'winds'];

/** The official FFVL take-offs and landings for the map (map_ffvl()); none before the table exists. */
export async function getFfvlSites() {
  const { data, error } = await sb.rpc('map_ffvl');
  if (error) return []; // migration-2026-10-25-ffvl-terrains.sql not run yet: the map shows no FFVL site
  return (data || []).map((a) => Object.fromEntries(FFVL_FIELDS.map((k, i) => [k, a[i]])));
}

/** The card of one FFVL site (walk from the car park, warnings, restrictions…), read when it is clicked. */
export async function getFfvlInfo(id) {
  const { data, error } = await sb.from('ffvl_terrains').select('info').eq('suid', id).maybeSingle();
  if (error) throw new Error(error.message);
  return (data && data.info) || {};
}

/** The routes of the map's outings (the climbs that follow the same way up); none before the routes table exists. */
export async function getMapRoutes() {
  const { data, error } = await sb.rpc('map_routes');
  if (error) return []; // migration-2026-10-23-routes.sql not run yet: the outings are grouped by start place
  return (data || []).map((a) => Object.fromEntries(ROUTE_FIELDS.map((k, i) => [k, a[i]])));
}

/** The take-offs of the register the map's outings are tied to; none before the register exists. */
export async function getMapSites() {
  const { data, error } = await sb.rpc('map_takeoff_sites');
  if (error) return []; // migration-2026-10-23-takeoff-sites.sql not run yet: the map groups the outings itself
  return (data || []).map((a) => Object.fromEntries(SITE_FIELDS.map((k, i) => [k, a[i]])));
}

/** The verified public outings for the take-off map (no track): the order of MAP_FIELDS, as in map_outings(). */
export async function getMapOutings() {
  const { data, error } = await sb.rpc('map_outings');
  if (error) throw new Error(error.message);
  return (data || []).map((a) => Object.fromEntries(MAP_FIELDS.map((k, i) => [k, a[i]])));
}

/** The tracks and flights of these outings, read only when their take-off is clicked. */
export async function getTraces(ids) {
  const out = [];
  for (let i = 0; i < ids.length; i += 25) {
    const { data, error } = await sb.from('outings').select('id,trace,flights').in('id', ids.slice(i, i + 25));
    if (error) throw new Error(error.message);
    out.push(...data);
  }
  return out;
}

export async function getRanking({ year, country }) {
  const { data, error } = await sb.rpc('ranking', { p_year: year || null, p_country: country || null, p_limit: 200 });
  if (error) throw new Error(error.message);
  return data || [];
}

// ---------- writing

export async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Store the original file privately and add the outing, which the analysis job will publish. */
// The columns the browser may write (the same list as the grant in schema-v2.sql).
const WRITABLE = ['status', 'engine_version', 'score_version', 'title', 'outing_date', 'started_at', 'duration_s',
  'country_code', 'country_name', 'start_lat', 'start_lon', 'start_alt', 'start_place', 'start_commune',
  'summit_name', 'summit_lat', 'summit_lon', 'summit_alt', 'takeoff_name', 'takeoff_lat', 'takeoff_lon', 'takeoff_alt',
  'landing_lat', 'landing_lon', 'landing_alt', 'dplus_m', 'dminus_m', 'walk_km', 'flight_free_km', 'flight_path_km',
  'score', 'flights', 'trace', 'warnings', 'places_pending', 'manual_flights']; // file_parts: set by submitTrack

/** Two flights are the same when they overlap for at least half of the shorter one (src/mbhf/duplicates.py). */
function sameFlight(a, b) {
  const span = (f) => {
    const t0 = Date.parse(f && f.takeoff && f.takeoff.t);
    const t1 = Date.parse(f && f.landing && f.landing.t);
    return t1 > t0 ? [t0, t1] : null;
  };
  const sb2 = (b || []).map(span).filter(Boolean);
  return (a || []).map(span).filter(Boolean).some((x) => sb2.some((y) => {
    const overlap = Math.min(x[1], y[1]) - Math.max(x[0], y[0]);
    return overlap > 0 && overlap >= 0.5 * Math.min(x[1] - x[0], y[1] - y[0]);
  }));
}

/** The pilot's outing (still counted) that already holds a flight of this result, or null. One pilot cannot
 * fly twice at the same time: the same flight sent from another file (a watch's FIT and its Strava export)
 * has another fingerprint, so the file hash does not catch it. */
export async function sameFlightAs(result) {
  if (!result || !result.outing_date || !(result.flights || []).length) return null;
  const { data, error } = await sb.from('outings').select('id,title,outing_date,flights')
    .eq('user_id', state.user.id).eq('outing_date', result.outing_date).in('status', ['pending', 'published']);
  if (error) return null; // not essential: the server job checks it again
  return (data || []).find((o) => sameFlight(result.flights, o.flights)) || null;
}

export function duplicateMessage(o) {
  const what = o && o.title ? `“${o.title}”` : 'another of your outings';
  const when = o && o.outing_date ? ` (${o.outing_date})` : '';
  return `This flight is already in ${what}${when}, sent from another file. The same flight counts once: to replace it, delete that outing first.`;
}

/** The fingerprint of an outing in several files: the SHA-256 of their own, one per line, in time order
 * (src/mbhf/multi.py, combined_sha256). */
export async function combinedSha256(hashes) {
  return sha256Hex(new TextEncoder().encode(hashes.join('\n')));
}

/** Store the original file(s) privately and add the outing. ``file`` is a File, or the Files of one outing in
 * several files (in time order): they are all stored, listed in file_parts, and the server joins them again. */
export async function submitTrack(file, onProgress, result) {
  const files = Array.isArray(file) ? file : [file];
  const twin = await sameFlightAs(result);
  if (twin) throw new Error(duplicateMessage(twin));
  const fields = {};
  for (const k of WRITABLE) if (result && result[k] !== undefined) fields[k] = result[k];
  const parts = [];
  for (const f of files) {
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    parts.push({ file: f, ext, path: `${state.user.id}/${crypto.randomUUID()}.${ext}`, size: f.size,
      sha256: await sha256Hex(await f.arrayBuffer()) });
  }
  const paths = parts.map((p) => p.path);
  onProgress && onProgress('Uploading…');
  for (const p of parts) {
    const up = await sb.storage.from(BUCKET).upload(p.path, p.file, { contentType: 'application/octet-stream', upsert: false });
    if (up.error) {
      await sb.storage.from(BUCKET).remove(paths);
      throw new Error(up.error.message || 'The file could not be uploaded.');
    }
  }
  const row = { ...fields, file_path: parts[0].path, file_format: parts[0].ext, status: 'published' };
  if (parts.length === 1) Object.assign(row, { file_size: parts[0].size, file_sha256: parts[0].sha256 });
  else {
    Object.assign(row, {
      file_size: parts.reduce((s, p) => s + p.size, 0),
      file_sha256: await combinedSha256(parts.map((p) => p.sha256)),
      file_parts: parts.map((p) => ({ path: p.path, format: p.ext, size: p.size, sha256: p.sha256, name: p.file.name.slice(0, 80) })),
    });
  }
  const ins = await sb.from('outings').insert(row).select('id').single();
  if (ins.error) {
    await sb.storage.from(BUCKET).remove(paths);
    if (ins.error.code === '23505') throw new Error('This track was already submitted.');
    if (ins.error.code === 'P0001') throw new Error('You reached the daily upload limit. Try again tomorrow.');
    throw new Error(ins.error.message);
  }
  return ins.data.id;
}

/** Which of these file fingerprints (SHA-256) this account already sent and that still count. */
export async function alreadySent(hashes) {
  const found = new Set();
  for (let i = 0; i < hashes.length; i += 50) {
    const { data, error } = await sb.from('outings').select('file_sha256')
      .eq('user_id', state.user.id).in('status', ['pending', 'published']).in('file_sha256', hashes.slice(i, i + 50));
    if (error) return found; // not essential: the insert refuses duplicates anyway
    for (const r of data) found.add(r.file_sha256);
  }
  return found;
}

/** Every stored file of an outing (one, or the parts of an outing in several files). */
function filePaths(outing) {
  const parts = (outing.file_parts || []).map((p) => p && p.path);
  return [...new Set([outing.file_path, ...parts].filter(Boolean))];
}

/** The outing's file_parts, when the row at hand was read without them (lists) — empty on a database that does
 * not have the column yet (migration-2026-10-25-file-parts.sql). */
async function withParts(outing) {
  if ('file_parts' in outing) return outing;
  const { data, error } = await sb.from('outings').select('file_parts').eq('id', outing.id).maybeSingle();
  return error || !data ? outing : { ...outing, file_parts: data.file_parts };
}

export async function deleteOuting(outing) {
  outing = await withParts(outing);
  const del = await sb.from('outings').delete().eq('id', outing.id);
  if (del.error) throw new Error(del.error.message);
  const paths = filePaths(outing);
  if (paths.length) await sb.storage.from(BUCKET).remove(paths);
}

export async function reportOuting(outingId, reason) {
  const { error } = await sb.from('reports').insert({ outing_id: outingId, reason: reason.trim().slice(0, 500) });
  if (error) throw new Error(error.message);
}

export async function deleteAccount() {
  const rows = await listUserOutings(state.user.id);
  const withAll = await sb.from('outings').select('id,file_path,file_parts').eq('user_id', state.user.id).limit(1000);
  const paths = (withAll.error ? rows : withAll.data || []).flatMap(filePaths);
  for (let i = 0; i < paths.length; i += 100) {
    const { error } = await sb.storage.from(BUCKET).remove(paths.slice(i, i + 100));
    if (error) throw new Error(error.message);
  }
  check(await sb.rpc('delete_my_account'));
  await sb.auth.signOut();
}
