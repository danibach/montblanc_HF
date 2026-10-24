// The analysis program (Python in a worker). One shared worker, started on first use.

import { CONFIG } from './config.js';

let worker = null;
let readyPromise = null;
let nextId = 1;
const waiting = new Map();
const listeners = new Set();

function status(text, state) {
  for (const f of listeners) f(text, state);
}

export function onEngineStatus(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function startEngine() {
  if (readyPromise) return readyPromise;
  readyPromise = new Promise((resolve, reject) => {
    worker = new Worker('worker.js', { type: 'module' });
    worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === 'progress') status(m.text, 'loading');
      else if (m.type === 'ready') {
        status('Analysis ready', 'ready');
        resolve(m.version);
      } else if (m.type === 'failed') {
        status('The analysis could not start.', 'failed');
        readyPromise = null;
        reject(new Error(m.payload.error));
      } else if (m.type === 'result') {
        const w = waiting.get(m.id);
        if (w) {
          waiting.delete(m.id);
          w(m.payload);
        }
      }
    };
    worker.onerror = (e) => {
      status('The analysis could not start.', 'failed');
      readyPromise = null;
      reject(new Error(e.message || 'worker error'));
    };
    worker.postMessage({ type: 'init' });
  });
  return readyPromise;
}

function call(message, transfer) {
  const id = nextId++;
  return new Promise((resolve) => {
    waiting.set(id, resolve);
    worker.postMessage({ ...message, id }, transfer || []);
  });
}

/** Analyse a File. Resolves to {file, outing, trace, engine}; throws an Error with a readable message. */
export async function analyseFile(file) {
  await startEngine();
  const bytes = await file.arrayBuffer();
  const res = await call({ type: 'analyse', name: file.name, bytes }, [bytes]);
  if (!res.ok) throw new Error(res.error || 'This file could not be analysed.');
  return res.result;
}

async function fetchJson(url, options, ms) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { ...options, signal: ctl.signal });
    return r.ok ? await r.json() : null;
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Tell a flight from a descent on the ground (ski, bike) with the height above the terrain, and a recording
 * gap that may be a flight from a ride with the roads and lifts near it (OpenStreetMap).
 * Takes the result of analyseFile; resolves to the result again, with the checks applied, or to the
 * same result if neither service can be reached.
 */
export async function checkTerrain(result) {
  const query = result.terrain && result.terrain.query;
  const access = result.terrain && result.terrain.access;
  if (!query && !access) return result;
  const [response, accessResponse] = await Promise.all([
    query ? fetchJson(`${CONFIG.ELEVATION_URL}?${query}`, {}, 15000) : null,
    access ? fetchJson(CONFIG.OVERPASS_URL, { method: 'POST', body: new URLSearchParams({ data: access }) }, 90000) : null,
  ]);
  if (!response && !accessResponse) return result; // the server checks again anyway
  const res = await call({ type: 'terrain', sha256: result.file.sha256, response, access: accessResponse });
  return res && res.ok ? res.result : result;
}

/** Names from OpenStreetMap for an outing. Resolves to the places object, or null if unavailable. */
export async function lookUpPlaces(outing) {
  try {
    await startEngine();
    const { query } = await call({ type: 'places_query', outing });
    if (!query) return null;
    let response = null;
    for (let attempt = 0; attempt < 3 && !response; attempt += 1) { // Overpass often answers 502/504 when busy
      if (attempt) await new Promise((resolve) => setTimeout(resolve, 2000 * attempt));
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 20000);
      try {
        const r = await fetch(CONFIG.OVERPASS_URL, {
          method: 'POST',
          body: new URLSearchParams({ data: query }),
          signal: ctl.signal,
        });
        if (r.ok) response = await r.json();
      } catch (_) {
        response = null;
      } finally {
        clearTimeout(timer);
      }
    }
    if (!response) return null;
    const places = await call({ type: 'places', outing, overpass: response });
    return places && places.ok === false ? null : places;
  } catch (_) {
    return null;
  }
}
