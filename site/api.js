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
  'id,title,summit_alt,outing_date,country_code,country_name,dplus_m,dminus_m,score,flight_free_km,walk_km,user_id,status,verified,reject_reason,profiles(display_name)';

export async function getFilters() {
  const { data, error } = await sb.rpc('outing_filters');
  if (error) throw new Error(error.message);
  return data || { years: [], countries: [] };
}

function yearRange(q, year) {
  return year ? q.gte('outing_date', `${year}-01-01`).lte('outing_date', `${year}-12-31`) : q;
}

export async function listOutings({ year, country, offset = 0, limit = CONFIG.PAGE_SIZE }) {
  let q = sb.from('outings').select(LIST_COLUMNS, { count: 'exact' }).eq('status', 'published').eq('hidden', false);
  q = yearRange(q, year);
  if (country) q = q.eq('country_code', country);
  const { data, error, count } = await q
    .order('outing_date', { ascending: false })
    .order('created_at', { ascending: false })
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

/** Take-offs of the verified public outings: [[lat, lon, outings], …]. */
export async function getTakeoffHeat() {
  const { data, error } = await sb.rpc('takeoff_heat');
  if (error) throw new Error(error.message);
  return data || [];
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
  'score', 'flights', 'trace', 'warnings', 'places_pending'];

export async function submitTrack(file, onProgress, result) {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  const buffer = await file.arrayBuffer();
  const hash = await sha256Hex(buffer);
  const fields = {};
  for (const k of WRITABLE) if (result && result[k] !== undefined) fields[k] = result[k];
  const path = `${state.user.id}/${crypto.randomUUID()}.${ext}`;
  onProgress && onProgress('Uploading…');
  const up = await sb.storage.from(BUCKET).upload(path, file, { contentType: 'application/octet-stream', upsert: false });
  if (up.error) throw new Error(up.error.message || 'The file could not be uploaded.');
  const ins = await sb
    .from('outings')
    .insert({ ...fields, file_path: path, file_format: ext, file_size: file.size, file_sha256: hash, status: 'published' })
    .select('id')
    .single();
  if (ins.error) {
    await sb.storage.from(BUCKET).remove([path]);
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

export async function deleteOuting(outing) {
  const del = await sb.from('outings').delete().eq('id', outing.id);
  if (del.error) throw new Error(del.error.message);
  if (outing.file_path) await sb.storage.from(BUCKET).remove([outing.file_path]);
}

export async function reportOuting(outingId, reason) {
  const { error } = await sb.from('reports').insert({ outing_id: outingId, reason: reason.trim().slice(0, 500) });
  if (error) throw new Error(error.message);
}

export async function deleteAccount() {
  const rows = await listUserOutings(state.user.id);
  const paths = rows.map((r) => r.file_path).filter(Boolean);
  for (let i = 0; i < paths.length; i += 100) {
    const { error } = await sb.storage.from(BUCKET).remove(paths.slice(i, i + 100));
    if (error) throw new Error(error.message);
  }
  check(await sb.rpc('delete_my_account'));
  await sb.auth.signOut();
}
