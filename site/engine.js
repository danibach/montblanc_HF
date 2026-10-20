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

/** Names from OpenStreetMap for an outing. Resolves to the places object, or null if unavailable. */
export async function lookUpPlaces(outing) {
  try {
    await startEngine();
    const { query } = await call({ type: 'places_query', outing });
    if (!query) return null;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 20000);
    let response;
    try {
      const r = await fetch(CONFIG.OVERPASS_URL, {
        method: 'POST',
        body: new URLSearchParams({ data: query }),
        signal: ctl.signal,
      });
      if (!r.ok) return null;
      response = await r.json();
    } finally {
      clearTimeout(timer);
    }
    const places = await call({ type: 'places', outing, overpass: response });
    return places && places.ok === false ? null : places;
  } catch (_) {
    return null;
  }
}
