// Runs the Python analysis (package mbhf) in the participant's browser, off the page's main thread.
// Nothing is sent anywhere: the files' bytes stay in this worker.

import { loadPyodide } from './pyodide/pyodide.mjs';

let ready = null;

async function boot() {
  const manifest = await (await fetch('manifest.json', { cache: 'no-cache' })).json();
  post({ type: 'progress', text: 'Chargement de Python dans votre navigateur…' });
  const py = await loadPyodide({ indexURL: new URL('./pyodide/', import.meta.url).href });
  post({ type: 'progress', text: "Installation du programme d'analyse…" });
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
  return { py, analyse: py.globals.get('mbhf').browser.analyse_json, version: manifest.version };
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
      return;
    }
    if (msg.type === 'analyse') {
      const files = engine.py.toPy(
        msg.files.map((f) => [f.name, new Uint8Array(f.bytes), f.mode || null])
      );
      const cuts = engine.py.toPy(msg.cuts || {});
      let text;
      try {
        text = engine.analyse(files, cuts);
      } finally {
        files.destroy();
        cuts.destroy();
      }
      post({ type: 'result', id: msg.id, payload: JSON.parse(text) });
    }
  } catch (err) {
    ready = msg.type === 'init' ? null : ready;
    post({
      type: msg.type === 'analyse' ? 'result' : 'failed',
      id: msg.id,
      payload: { ok: false, error: "L'analyse n'a pas pu démarrer dans votre navigateur.", detail: String(err && err.message || err) },
    });
  }
};
