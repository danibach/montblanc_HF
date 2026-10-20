// Runs the Python analysis (package mbhf) in the participant's browser, off the page's main thread.
// Nothing is sent anywhere from here: the file's bytes stay in this worker.

import { loadPyodide } from './pyodide/pyodide.mjs';

let ready = null;

async function boot() {
  const manifest = await (await fetch('manifest.json', { cache: 'no-cache' })).json();
  post({ type: 'progress', text: 'Loading Python in your browser…' });
  const py = await loadPyodide({ indexURL: new URL('./pyodide/', import.meta.url).href });
  post({ type: 'progress', text: 'Installing the analysis program…' });
  for (const name of manifest.wheels) {
    const buf = await (await fetch(`py/${name}`)).arrayBuffer();
    py.unpackArchive(new Uint8Array(buf), 'wheel');
  }
  const src = await (await fetch(`py/${manifest.engine}`)).arrayBuffer();
  py.unpackArchive(new Uint8Array(src), 'zip', { extractDir: '/home/pyodide/engine' });
  py.runPython(`
import sys
sys.path.insert(0, "/home/pyodide/engine")
import mbhf.browser
`);
  const browser = py.globals.get('mbhf').browser;
  return { py, browser, version: manifest.version };
}

function post(msg) {
  self.postMessage(msg);
}

self.onmessage = async (ev) => {
  const msg = ev.data;
  try {
    if (!ready) ready = boot();
    const engine = await ready;
    if (msg.type === 'init') {
      post({ type: 'ready', version: engine.version });
    } else if (msg.type === 'analyse') {
      const data = engine.py.toPy(new Uint8Array(msg.bytes));
      let text;
      try {
        text = engine.browser.analyse_json(msg.name, data);
      } finally {
        data.destroy();
      }
      post({ type: 'result', id: msg.id, payload: JSON.parse(text) });
    } else if (msg.type === 'terrain') {
      const text = engine.browser.terrain_json(msg.sha256, JSON.stringify(msg.response));
      post({ type: 'result', id: msg.id, payload: JSON.parse(text) });
    } else if (msg.type === 'places_query') {
      const q = engine.browser.places_query(JSON.stringify(msg.outing));
      post({ type: 'result', id: msg.id, payload: { query: q === undefined ? null : q } });
    } else if (msg.type === 'places') {
      const text = engine.browser.resolve_places_json(JSON.stringify(msg.outing), JSON.stringify(msg.overpass));
      post({ type: 'result', id: msg.id, payload: JSON.parse(text) });
    }
  } catch (err) {
    ready = msg.type === 'init' ? null : ready;
    post({
      type: msg.type === 'init' ? 'failed' : 'result',
      id: msg.id,
      payload: { ok: false, error: 'The analysis could not start in your browser.', detail: String((err && err.message) || err) },
    });
  }
};
