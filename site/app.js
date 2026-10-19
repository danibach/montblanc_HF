// Page of the in-browser track check. The analysis itself is the Python package mbhf, run by
// worker.js; this file only reads the files, shows the result and lets the participant fix the
// transitions. Everything a participant reads is in French.

const MAX_BYTES = 60 * 1024 * 1024;
const TZ = 'Europe/Paris';
const MODE_COLOUR = { bike: '#3b6ea5', walk: '#4f8a4b', flight: '#d9512c' };
const INK = '#0f2a35';
const MUTED = '#55696f';
const GRID = '#d3dde2';
const SVG_NS = 'http://www.w3.org/2000/svg';
const CUTS = [
  ['walk_start', 'Début de la montée à pied'],
  ['takeoff', 'Décollage'],
  ['landing', 'Atterrissage'],
  ['bike_return_start', 'Début du retour à vélo'],
];
const CONFIDENCE = { high: 'sûre', medium: 'assez sûre', low: 'à vérifier' };
const VERDICT = { ride: 'trajet probable', review: 'à examiner', clear: 'rien à signaler' };
const KIND = { tram: 'tramway', lift: 'remontée', gap: 'trou d’enregistrement' };

// ---------------------------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined) continue;
    if (k === 'text') el.textContent = v;
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat()) if (c) el.append(c);
  return el;
}

const num = (v) => String(v).replace('.', ',');
const pad = (n) => String(n).padStart(2, '0');

function hms(seconds) {
  if (seconds === null || seconds === undefined) return '';
  const v = Math.round(seconds);
  return `${Math.floor(v / 3600)}:${pad(Math.floor((v % 3600) / 60))}:${pad(v % 60)}`;
}

function dur(seconds) {
  if (seconds === null || seconds === undefined) return '';
  const v = Math.round(seconds);
  if (v >= 3600) return `${Math.floor(v / 3600)} h ${pad(Math.floor((v % 3600) / 60))} min`;
  if (v >= 60) return v < 600 && v % 60 ? `${Math.floor(v / 60)} min ${pad(v % 60)} s` : `${Math.floor(v / 60)} min`;
  return `${v} s`;
}

const clockFmt = new Intl.DateTimeFormat('fr-CH', { timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
const hourFmt = new Intl.DateTimeFormat('fr-CH', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const localClock = (ms) => clockFmt.format(new Date(ms));
const isoUtc = (ms) => new Date(Math.round(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
const coord = (p) => `${num(p.lat.toFixed(5))}, ${num(p.lon.toFixed(5))}`;

function niceStep(range, target) {
  const raw = range / Math.max(1, target);
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * mag >= raw) return m * mag;
  return 10 * mag;
}

// ---------------------------------------------------------------------------------------------
// the analysis engine (Python in a worker)
// ---------------------------------------------------------------------------------------------

const statusEl = $('#engine-status');
const submitBtn = $('#submit');
const formError = $('#form-error');
let worker = null;
let engineState = 'loading'; // loading | ready | failed
const pending = new Map();
let nextId = 1;

function startEngine() {
  if (!window.Worker || typeof WebAssembly !== 'object') {
    engineFailed();
    return;
  }
  try {
    worker = new Worker('worker.js', { type: 'module' });
  } catch (_) {
    engineFailed();
    return;
  }
  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === 'progress' && engineState === 'loading') statusEl.textContent = m.text;
    else if (m.type === 'ready') {
      engineState = 'ready';
      statusEl.textContent = 'Prêt. La première préparation télécharge environ 6 Mo, gardés ensuite par votre navigateur.';
      statusEl.dataset.state = 'ready';
    } else if (m.type === 'failed') engineFailed(m.payload && m.payload.detail);
    else if (m.type === 'result') {
      const cb = pending.get(m.id);
      pending.delete(m.id);
      if (cb) cb(m.payload);
    }
  };
  worker.onerror = () => engineFailed();
  worker.postMessage({ type: 'init' });
}

function engineFailed(detail) {
  engineState = 'failed';
  if (detail) console.error('engine:', detail);
  statusEl.textContent = '';
  showFormError(
    "L'outil d'analyse n'a pas pu se charger. Vérifiez votre connexion et rechargez la page. Il faut un navigateur récent (Firefox, Chrome, Edge ou Safari)."
  );
  for (const cb of pending.values()) cb({ ok: false, error: "L'outil d'analyse n'a pas pu se charger." });
  pending.clear();
}

function analyse(files, cuts) {
  return new Promise((resolve) => {
    if (engineState === 'failed' || !worker) {
      resolve({ ok: false, error: "L'outil d'analyse n'a pas pu se charger. Rechargez la page." });
      return;
    }
    const id = nextId++;
    pending.set(id, resolve);
    worker.postMessage({ type: 'analyse', id, files, cuts });
  });
}

// ---------------------------------------------------------------------------------------------
// upload form
// ---------------------------------------------------------------------------------------------

const rows = $('#file-rows');
$('#add-file').addEventListener('click', () => {
  const n = rows.children.length;
  const copy = rows.firstElementChild.cloneNode(true);
  const file = copy.querySelector('input[type=file]');
  const mode = copy.querySelector('select');
  file.id = `track-${n}`;
  file.value = '';
  copy.querySelector('label[for^=track]').setAttribute('for', file.id);
  mode.id = `mode-${n}`;
  mode.selectedIndex = 0;
  copy.querySelector('label[for^=mode]').setAttribute('for', mode.id);
  rows.append(copy);
  file.focus();
});

function showFormError(text) {
  formError.querySelector('p').textContent = text;
  formError.hidden = !text;
}

let lastFiles = null;  // [{name, bytes, mode}] of the current result, reused when transitions change
let current = null;    // the current result
let pinned = {};       // transitions chosen by the participant: key -> ISO UTC
let lastRunCuts = {};  // the pinned transitions the current result was computed with

$('#upload-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  showFormError('');
  const chosen = [];
  for (const row of rows.children) {
    const f = row.querySelector('input[type=file]').files[0];
    if (f) chosen.push({ file: f, mode: row.querySelector('select').value });
  }
  if (!chosen.length) {
    showFormError('Choisissez au moins un fichier de trace.');
    return;
  }
  const total = chosen.reduce((a, c) => a + c.file.size, 0);
  if (total > MAX_BYTES) {
    showFormError("Ces fichiers dépassent 60 Mo au total. Envoyez un enregistrement à la fois, ou exportez avec une fréquence d'enregistrement plus basse.");
    return;
  }
  submitBtn.disabled = true;
  submitBtn.textContent = 'Analyse en cours…';
  const previousStatus = statusEl.textContent;
  if (engineState === 'ready') statusEl.textContent = 'Analyse en cours, quelques secondes.';
  try {
    const files = await Promise.all(
      chosen.map(async (c) => ({ name: c.file.name, bytes: await c.file.arrayBuffer(), mode: c.mode }))
    );
    const out = await analyse(files, {});
    if (!out.ok) {
      showFormError(out.error);
      if (out.detail) console.error('analyse:', out.detail);
      return;
    }
    lastFiles = files;
    pinned = {};
    lastRunCuts = {};
    showResult(out.result, { scroll: true });
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Analyser ma trace';
    if (engineState === 'ready') statusEl.textContent = previousStatus;
  }
});

// ---------------------------------------------------------------------------------------------
// result
// ---------------------------------------------------------------------------------------------

const resultEl = $('#result');
let view = null; // drawing state: { r, modeAt, startMs, cursor, pickKey, redraw }

function showResult(r, { scroll = false, focusId = null } = {}) {
  current = r;
  $('#intro').hidden = true;
  $('#upload-form').hidden = true;
  resultEl.replaceChildren(...buildResult(r));
  resultEl.hidden = false;
  drawTrace();
  if (focusId) document.getElementById(focusId)?.focus();
  else if (scroll) window.scrollTo({ top: 0 });
}

function resetToForm() {
  current = null;
  view = null;
  lastFiles = null;
  resultEl.hidden = true;
  resultEl.replaceChildren();
  $('#intro').hidden = false;
  $('#upload-form').hidden = false;
  for (const row of [...rows.children].slice(1)) row.remove();
  rows.querySelector('input[type=file]').value = '';
  window.scrollTo({ top: 0 });
}

function buildResult(r) {
  const c = r.chrono;
  const rep = r.report;
  const out = [];

  // --- headline ----------------------------------------------------------------------------
  const head = h('section', { class: 'headline' });
  if (c && c.climb_hms) {
    head.append(
      h('p', { class: 'big-time', 'aria-label': `Temps de montée ${c.climb_hms}`, text: c.climb_hms }),
      h('p', { class: 'big-caption', text: `entre la sortie du Nid d'Aigle et l'entrée à pied dans le cylindre du sommet, à ${Math.round(c.uncertainty_s)} s près` })
    );
  } else {
    head.append(
      h('h1', { text: 'Pas de temps de montée pour cette trace' }),
      h('p', { class: 'big-caption', text: "La trace ne montre pas de montée à pied du Nid d'Aigle au sommet. Les raisons sont données plus bas." })
    );
  }
  const tp = c && c.transport;
  const transportClass = tp && tp.performed && tp.verdict === 'clear' ? 'ok' : c && c.flagged ? 'no' : 'unknown';
  const transportText = !tp || !tp.performed ? 'pas encore actif' : c.flagged ? 'trace signalée' : tp.verdict === 'review' ? 'à examiner' : 'rien à signaler';
  head.append(
    h('ul', { class: 'verdicts' },
      h('li', { class: c && c.ranking_eligible ? 'ok' : 'no' }, 'Classement : ', h('strong', { text: c && c.ranking_eligible ? 'éligible' : 'non éligible' })),
      h('li', { class: c && c.hf_conditions_met ? 'ok' : 'no' }, 'Conditions HF / BHF : ', h('strong', { text: c && c.hf_conditions_met ? 'remplies' : 'non remplies' })),
      h('li', { class: transportClass }, 'Contrôle tramway et remontées : ', h('strong', { text: transportText }))
    ),
    h('p', { class: 'notice notice-pending' },
      h('strong', { text: 'Résultat provisoire, en attente de validation. ' }),
      "Il est calculé sur votre appareil et rien n'a été envoyé. L'envoi pour validation par l'équipe sera ajouté prochainement."
    )
  );
  if (c && c.provisional) {
    head.append(h('p', { class: 'notice notice-info', text: "Le contrôle du tramway et des remontées mécaniques n'est pas encore actif : ce résultat ne permet pas d'exclure un trajet en tramway ou en télécabine." }));
  }
  if (c && c.flagged) {
    head.append(h('p', { class: 'notice notice-error', role: 'alert', text: "Cette trace est signalée : elle semble utiliser le tramway du Mont-Blanc ou une remontée mécanique. Elle n'a ni rang ni badge tant que l'équipe ne l'a pas examinée." }));
  }
  out.push(head);

  // --- the track ---------------------------------------------------------------------------
  out.push(
    h('section', { 'aria-labelledby': 'trace-title' },
      h('h2', { id: 'trace-title', text: 'Votre trace' }),
      h('p', { class: 'hint', text: "Les numéros renvoient aux lieux détectés, plus bas. Cliquez sur la trace ou sur le profil pour lire l'heure et l'altitude d'un point." }),
      h('div', { class: 'pick-banner', id: 'pick-banner', role: 'status', hidden: true }),
      h('figure', { class: 'trace-panel', id: 'trace-panel' },
        h('div', { class: 'plan-wrap', id: 'plan-wrap' }),
        h('div', { class: 'profile-wrap', id: 'profile-wrap', tabindex: '0', role: 'region', 'aria-label': "Profil d'altitude, faites défiler latéralement sur un petit écran" })
      ),
      h('p', { class: 'readout', id: 'readout', 'aria-live': 'polite' }),
      legend(rep.parts)
    )
  );

  // --- transitions -------------------------------------------------------------------------
  out.push(buildTransitions(r));

  // --- parts ribbon ------------------------------------------------------------------------
  out.push(
    h('section', { 'aria-labelledby': 'day' },
      h('h2', { id: 'day', text: 'Votre journée en parties' }),
      ribbon(rep.parts)
    )
  );

  // --- places ------------------------------------------------------------------------------
  const startDate = rep.track.start.local_date;
  const placeRows = rep.places.map((e, i) =>
    h('tr', {},
      h('th', { scope: 'row' },
        h('span', { class: 'marker-num', 'aria-hidden': 'true', text: String(i + 1) }),
        e.label,
        e.near ? h('span', { class: 'muted block', text: e.near }) : null,
        e.note ? h('span', { class: 'muted block', text: e.note }) : null
      ),
      h('td', {}, e.local_hms, e.local_date !== startDate ? h('span', { class: 'muted block', text: e.local_date }) : null),
      h('td', {},
        e.lat !== undefined
          ? [coord(e), h('span', { class: 'block' }, h('a', { href: e.map_url, rel: 'noopener noreferrer', target: '_blank', text: 'voir sur une carte' }))]
          : h('span', { class: 'muted', text: 'inconnue' })
      ),
      h('td', { class: 'num' }, e.alt_m !== undefined && e.alt_m !== null ? `${e.alt_m} m` : h('span', { class: 'muted', text: 'inconnue' })),
      h('td', {},
        e.confidence
          ? [e.user_fixed ? 'fixée par vous' : CONFIDENCE[e.confidence] || e.confidence,
             e.gap_s && e.gap_s >= 60 ? h('span', { class: 'muted block', text: `${dur(e.gap_s)} sans enregistrement ici` }) : null]
          : h('span', { class: 'muted', text: 'lue dans la trace' })
      )
    )
  );
  out.push(
    h('section', { 'aria-labelledby': 'places' },
      h('h2', { id: 'places', text: 'Lieux détectés' }),
      h('p', { class: 'hint', text: `Heures de Paris, le ${startDate} sauf indication d'une autre date. Les altitudes sont celles enregistrées par votre appareil.` }),
      h('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Lieux détectés, faites défiler latéralement sur un petit écran' },
        h('table', {},
          h('thead', {}, h('tr', {}, ...['Quoi', 'Heure', 'Position', 'Altitude', 'Détection'].map((t, i) => h('th', { scope: 'col', class: i === 3 ? 'num' : null, text: t })))),
          h('tbody', {}, placeRows)
        )
      ),
      rep.track.highest
        ? h('p', { class: 'hint', text: `Point le plus haut enregistré : ${rep.track.highest.alt_m} m à ${rep.track.highest.local_hms}, ${coord(rep.track.highest)}.` })
        : null
    )
  );

  // --- parts table -------------------------------------------------------------------------
  out.push(
    h('section', { 'aria-labelledby': 'parts' },
      h('h2', { id: 'parts', text: 'Détail de chaque partie' }),
      h('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Détail de chaque partie, faites défiler latéralement sur un petit écran' },
        h('table', {},
          h('thead', {}, h('tr', {}, ...['Partie', 'De', 'À', 'Durée', 'Distance', 'Montée', 'Descente', 'Vitesse moyenne'].map((t, i) => h('th', { scope: 'col', class: i >= 3 ? 'num' : null, text: t })))),
          h('tbody', {}, rep.parts.map((p) =>
            h('tr', {},
              h('th', { scope: 'row' }, swatch(p.mode), p.title),
              h('td', { text: p.start.local_hms }),
              h('td', { text: p.end.local_hms }),
              h('td', { class: 'num', text: hms(p.duration_s) }),
              h('td', { class: 'num', text: `${num(p.distance_km)} km` }),
              h('td', { class: 'num', text: p.ascent_m !== null ? `${p.ascent_m} m` : '' }),
              h('td', { class: 'num', text: p.descent_m !== null ? `${p.descent_m} m` : '' }),
              h('td', { class: 'num', text: `${num(p.mean_speed_kmh)} km/h` })
            )
          ))
        )
      )
    )
  );

  // --- checks ------------------------------------------------------------------------------
  const issues = [...((c && c.problems) || []), ...(r.warnings || [])];
  const notes = (c && c.notes) || [];
  if (issues.length || notes.length) {
    out.push(
      h('section', { 'aria-labelledby': 'checks' },
        h('h2', { id: 'checks', text: 'Contrôles et remarques' }),
        issues.length ? h('ul', { class: 'messages' }, issues.map((m) => h('li', { text: m }))) : null,
        notes.length ? h('ul', { class: 'messages muted-list' }, notes.map((m) => h('li', { text: m }))) : null
      )
    );
  }
  if (tp && tp.stretches && tp.stretches.length) {
    out.push(
      h('section', { 'aria-labelledby': 'transport' },
        h('h2', { id: 'transport', text: 'Voies et remontées pendant la montée' }),
        h('ul', { class: 'messages' }, tp.stretches.map((st) =>
          h('li', {}, h('strong', { text: VERDICT[st.verdict] || st.verdict }), `, ${KIND[st.kind] || st.kind} ${st.line} : ${st.reason}`)
        ))
      )
    );
  }

  // --- actions -----------------------------------------------------------------------------
  out.push(
    h('div', { class: 'actions' },
      h('button', { type: 'button', class: 'primary', text: 'Analyser une autre trace', onclick: resetToForm }),
      h('button', { type: 'button', class: 'link-button', text: 'Télécharger le résultat (JSON)', onclick: downloadJson })
    )
  );
  return out;
}

function swatch(mode) {
  return h('span', { class: `swatch part-${mode}`, 'aria-hidden': 'true' });
}

function legend(parts) {
  return h('ul', { class: 'legend' }, parts.map((p) =>
    h('li', {}, swatch(p.mode), p.title, h('span', { class: 'muted', text: ` ${dur(p.duration_s)}, ${num(p.distance_km)} km` }))
  ));
}

function ribbon(parts) {
  const svg = s('svg', { class: 'ribbon', viewBox: '0 0 1000 44', role: 'img', 'aria-label': 'Votre journée découpée en parties : ' + parts.map((p) => `${p.title} ${dur(p.duration_s)}`).join(', ') });
  let x = 0;
  parts.forEach((p, i) => {
    const w = Math.max(p.share * 1000, 3);
    svg.append(s('rect', { class: `part part-${p.mode}`, x: x.toFixed(1), y: 0, width: w.toFixed(1), height: 44 }, s('title', { text: `${p.title} : ${dur(p.duration_s)}` })));
    if (i > 0) svg.append(s('line', { class: 'cut', x1: x.toFixed(1), x2: x.toFixed(1), y1: 0, y2: 44 }));
    x += w;
  });
  return h('div', {}, svg, legend(parts));
}

function downloadJson() {
  if (!current) return;
  const blob = new Blob([JSON.stringify(current, null, 2)], { type: 'application/json' });
  const a = h('a', { href: URL.createObjectURL(blob), download: 'mont-blanc-track-result.json' });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ---------------------------------------------------------------------------------------------
// transitions the participant can fix
// ---------------------------------------------------------------------------------------------

function trackSpan(r) {
  const t0 = Date.parse(r.trace.t0);
  return { t0, end: t0 + r.trace.t[r.trace.t.length - 1] * 1000 };
}

function buildTransitions(r) {
  const list = h('div', { class: 'cut-list' });
  for (const [key, label] of CUTS) {
    const detected = r.transitions[key];
    const pin = pinned[key];
    const usedPin = lastRunCuts[key];
    let state;
    if (pin && pin === usedPin) state = 'fixée par vous';
    else if (pin) state = 'choisie, à recalculer';
    else if (detected) state = 'détectée';
    else state = 'aucune';
    const shownIso = pin || detected;
    const input = h('input', {
      type: 'time', step: '1', id: `cut-${key}`,
      value: shownIso ? localClock(Date.parse(shownIso)) : '',
      'aria-describedby': `cut-${key}-state`,
    });
    input.addEventListener('change', () => pinFromInput(key, input.value));
    list.append(
      h('div', { class: `cut-row${pin ? ' is-pinned' : ''}` },
        h('label', { for: `cut-${key}`, class: 'cut-label', text: label }),
        input,
        h('span', { class: 'cut-state muted', id: `cut-${key}-state`, text: state }),
        h('span', { class: 'cut-buttons' },
          h('button', { type: 'button', class: 'small-button', 'aria-pressed': view && view.pickKey === key ? 'true' : 'false', 'data-pick': key, text: 'Placer sur la trace', onclick: () => startPick(key, label) }),
          pin ? h('button', { type: 'button', class: 'link-button', text: 'Effacer', onclick: () => { delete pinned[key]; refreshTransitions(); } }) : null
        )
      )
    );
  }
  const changed = JSON.stringify(sortedCuts(pinned)) !== JSON.stringify(sortedCuts(lastRunCuts));
  const anyUsed = Object.keys(lastRunCuts).length > 0;
  return h('section', { 'aria-labelledby': 'cuts-title', id: 'cuts-section' },
    h('h2', { id: 'cuts-title', text: 'Corriger les transitions' }),
    h('p', { class: 'hint', text: "Si une partie de la journée est mal découpée, indiquez vous-même le moment du changement : choisissez « Placer sur la trace » puis cliquez sur le profil ou sur la trace, ou saisissez l'heure de Paris. Ne touchez pas à une transition qui n'a pas eu lieu." }),
    list,
    h('div', { class: 'actions' },
      h('button', { type: 'button', class: 'primary', id: 'recompute', disabled: !changed, text: 'Recalculer avec ces transitions', onclick: () => recompute(pinned) }),
      anyUsed ? h('button', { type: 'button', class: 'link-button', text: 'Revenir à la détection automatique', onclick: () => { pinned = {}; recompute({}); } }) : null
    ),
    h('p', { class: 'cut-status', id: 'cut-status', role: 'status' })
  );
}

function sortedCuts(c) {
  return Object.keys(c).sort().map((k) => [k, c[k]]);
}

function refreshTransitions(message) {
  const old = document.getElementById('cuts-section');
  if (!old || !current) return;
  const fresh = buildTransitions(current);
  old.replaceWith(fresh);
  if (message) setCutStatus(message.text, message.error);
}

function setCutStatus(text, error = false) {
  const el = document.getElementById('cut-status');
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('is-error', !!error);
  el.setAttribute('role', error ? 'alert' : 'status');
}

function pinFromInput(key, value) {
  if (!current) return;
  if (!value) {
    delete pinned[key];
    refreshTransitions();
    return;
  }
  const m = /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (!m) return;
  const start = current.report.track.start.local; // e.g. 2026-09-12T08:00:00+02:00
  const date = start.slice(0, 10);
  const offset = start.slice(19);
  const { t0, end } = trackSpan(current);
  let ms = Date.parse(`${date}T${m[1]}:${m[2]}:${m[3] || '00'}${offset}`);
  if (ms < t0 - 60000) ms += 86400000; // after midnight
  if (Number.isNaN(ms) || ms < t0 || ms > end) {
    refreshTransitions({ text: `Cette heure est en dehors de la trace, qui va de ${localClock(t0)} à ${localClock(end)}.`, error: true });
    return;
  }
  pinned[key] = isoUtc(ms);
  refreshTransitions();
}

function startPick(key, label) {
  if (!view) return;
  view.pickKey = view.pickKey === key ? null : key;
  const banner = document.getElementById('pick-banner');
  if (view.pickKey) {
    banner.textContent = `Cliquez sur le profil ou sur la trace à l'endroit du changement : ${label}. Échap pour annuler.`;
    banner.hidden = false;
    document.getElementById('trace-panel').classList.add('is-picking');
    document.getElementById('trace-title').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else {
    stopPick();
  }
  for (const b of document.querySelectorAll('[data-pick]')) b.setAttribute('aria-pressed', String(b.dataset.pick === view.pickKey));
}

function stopPick() {
  if (!view) return;
  view.pickKey = null;
  const banner = document.getElementById('pick-banner');
  if (banner) banner.hidden = true;
  document.getElementById('trace-panel')?.classList.remove('is-picking');
  for (const b of document.querySelectorAll('[data-pick]')) b.setAttribute('aria-pressed', 'false');
}

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && view && view.pickKey) stopPick();
});

async function recompute(cuts) {
  if (!lastFiles) return;
  const btn = document.getElementById('recompute');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Calcul en cours…';
  }
  setCutStatus('Nouvelle analyse en cours, quelques secondes.');
  const wanted = { ...cuts };
  const out = await analyse(lastFiles, wanted);
  if (!out.ok) {
    refreshTransitions({ text: out.error, error: true });
    return;
  }
  lastRunCuts = wanted;
  pinned = { ...wanted };
  showResult(out.result, { focusId: 'cut-status' });
  document.getElementById('cuts-section')?.scrollIntoView({ block: 'start' });
  setCutStatus(Object.keys(wanted).length ? 'Résultat recalculé avec vos transitions.' : 'Résultat recalculé avec la détection automatique.');
}

// ---------------------------------------------------------------------------------------------
// drawing: the track seen from above, and the altitude profile
// ---------------------------------------------------------------------------------------------

function drawTrace() {
  const r = current;
  const tr = r.trace;
  const n = tr.idx.length;
  const segs = r.segments;
  const modeAt = new Array(n);
  const segAt = new Array(n);
  let k = 0;
  for (let i = 0; i < n; i++) {
    const fix = tr.idx[i];
    while (k < segs.length - 1 && fix > segs[k].last_fix) k++;
    modeAt[i] = segs[k].mode;
    segAt[i] = k;
  }
  const { t0 } = trackSpan(r);
  view = { r, modeAt, segAt, t0, cursor: view && view.r === r ? view.cursor : null, pickKey: null };
  redraw();
}

function redraw() {
  if (!view) return;
  const plan = document.getElementById('plan-wrap');
  const prof = document.getElementById('profile-wrap');
  if (!plan || !prof) return;
  const width = Math.max(300, Math.round(plan.clientWidth || 800));
  plan.replaceChildren(drawPlan(width));
  prof.replaceChildren(drawProfile(Math.max(640, Math.round(prof.clientWidth || 800))));
  updateReadout();
}

let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(redraw, 150);
});

function markers() {
  // the detected places, numbered as in the table
  return view.r.report.places
    .map((e, i) => ({ ...e, n: i + 1, ms: Date.parse(e.utc) }))
    .filter((e) => e.lat !== undefined);
}

function runs(n) {
  // consecutive points of the same part, sharing their junction point
  const out = [];
  let start = 0;
  for (let i = 1; i <= n; i++) {
    if (i === n || view.segAt[i] !== view.segAt[start]) {
      out.push([start, Math.min(i, n - 1), view.modeAt[start]]);
      start = i;
    }
  }
  return out;
}

function drawPlan(W) {
  const tr = view.r.trace;
  const n = tr.lat.length;
  const latMid = (Math.min(...tr.lat) + Math.max(...tr.lat)) / 2;
  const kx = Math.cos((latMid * Math.PI) / 180);
  const xs = tr.lon.map((v) => v * kx);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...tr.lat), maxY = Math.max(...tr.lat);
  const pad = 40;
  const spanX = Math.max(maxX - minX, 1e-4), spanY = Math.max(maxY - minY, 1e-4);
  const maxH = Math.min(560, Math.round(W * 0.9));
  const scale = Math.min((W - 2 * pad) / spanX, (maxH - 2 * pad) / spanY);
  const H = Math.round(spanY * scale + 2 * pad);
  const offX = (W - spanX * scale) / 2;
  const px = (i) => offX + (xs[i] - minX) * scale;
  const py = (i) => pad + (maxY - tr.lat[i]) * scale;
  const toXY = (lat, lon) => [offX + (lon * kx - minX) * scale, pad + (maxY - lat) * scale];

  const svg = s('svg', {
    class: 'plan', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img',
    'aria-label': 'Votre trace vue de dessus, colorée selon les parties de la journée, avec les lieux détectés numérotés',
  });
  svg.append(s('rect', { x: 0, y: 0, width: W, height: H, fill: '#ffffff' }));

  for (const [a, b, mode] of runs(n)) {
    const pts = [];
    for (let i = a; i <= b; i++) pts.push(`${px(i).toFixed(1)},${py(i).toFixed(1)}`);
    svg.append(s('polyline', { points: pts.join(' '), fill: 'none', stroke: MODE_COLOUR[mode], 'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  }

  // scale bar
  const metresPerPx = (111320 * 1) / scale;
  const target = metresPerPx * W * 0.18;
  const bar = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000].find((m) => m >= target) || 50000;
  const barPx = bar / metresPerPx;
  const bx = 14, by = H - 12;
  svg.append(
    s('line', { x1: bx, x2: bx + barPx, y1: by, y2: by, stroke: INK, 'stroke-width': 2 }),
    s('line', { x1: bx, x2: bx, y1: by - 5, y2: by, stroke: INK, 'stroke-width': 2 }),
    s('line', { x1: bx + barPx, x2: bx + barPx, y1: by - 5, y2: by, stroke: INK, 'stroke-width': 2 }),
    s('text', { x: bx + barPx + 6, y: by + 4, 'font-size': 12, fill: INK, text: bar >= 1000 ? `${bar / 1000} km` : `${bar} m` }),
    s('text', { x: W - 14, y: 20, 'font-size': 12, fill: MUTED, 'text-anchor': 'end', text: 'Nord en haut' })
  );

  // numbered places, nudged apart when they overlap
  const placed = [];
  const R = 10;
  for (const m of markers()) {
    const [x, y] = toXY(m.lat, m.lon);
    const free = (cx, cy) =>
      cx >= R + 2 && cx <= W - R - 2 && cy >= R + 2 && cy <= H - R - 2 &&
      !placed.some(([qx, qy]) => Math.hypot(qx - cx, qy - cy) < 2 * R + 2);
    let lx = x, ly = y;
    if (!free(lx, ly)) {
      // look around the point, ring after ring, for a free spot inside the drawing
      search: for (let ring = 1; ring <= 4; ring++) {
        for (let a = 0; a < 8; a++) {
          const ang = (-Math.PI / 2) + (a * Math.PI) / 4;
          const cx = x + Math.cos(ang) * ring * (2 * R + 6);
          const cy = y + Math.sin(ang) * ring * (2 * R + 6);
          if (free(cx, cy)) { lx = cx; ly = cy; break search; }
        }
      }
    }
    placed.push([lx, ly]);
    const g = s('g', {}, s('title', { text: `${m.n}. ${m.label}, ${m.local_hms}` }));
    if (lx !== x || ly !== y) g.append(s('line', { x1: x, y1: y, x2: lx, y2: ly, stroke: INK, 'stroke-width': 1 }));
    g.append(
      s('circle', { cx: x, cy: y, r: 2.5, fill: INK }),
      s('circle', { cx: lx, cy: ly, r: R, fill: '#ffffff', stroke: INK, 'stroke-width': 1.5 }),
      s('text', { x: lx, y: ly + 4, 'font-size': 11.5, 'font-weight': 700, 'text-anchor': 'middle', fill: INK, text: String(m.n) })
    );
    svg.append(g);
  }

  if (view.cursor !== null) {
    svg.append(s('circle', { cx: px(view.cursor), cy: py(view.cursor), r: 6, fill: 'none', stroke: INK, 'stroke-width': 2.5 }));
  }

  svg.addEventListener('click', (ev) => {
    const [x, y] = svgPoint(svg, ev);
    let best = 0, bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const d = (px(i) - x) ** 2 + (py(i) - y) ** 2;
      if (d < bestD) { bestD = d; best = i; }
    }
    choosePoint(best);
  });
  return svg;
}

function drawProfile(W) {
  const tr = view.r.trace;
  const n = tr.t.length;
  const H = 260;
  const m = { l: 58, r: 14, t: 26, b: 30 };
  const T = Math.max(tr.t[n - 1], 1);
  const alts = tr.alt.filter((a) => a !== null);
  const svg = s('svg', {
    class: 'profile', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img',
    'aria-label': "Profil d'altitude en fonction de l'heure, coloré selon les parties de la journée",
  });
  svg.append(s('rect', { x: 0, y: 0, width: W, height: H, fill: '#ffffff' }));
  if (!alts.length) {
    svg.append(s('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', fill: MUTED, 'font-size': 13, text: "Pas d'altitude dans cette trace." }));
    return svg;
  }
  let lo = Math.min(...alts), hi = Math.max(...alts);
  if (hi - lo < 50) { lo -= 25; hi += 25; }
  const step = niceStep(hi - lo, 5);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const x = (sec) => m.l + (sec / T) * (W - m.l - m.r);
  const y = (alt) => m.t + (1 - (alt - lo) / (hi - lo)) * (H - m.t - m.b);
  const sec = (ms) => (ms - view.t0) / 1000;

  // grid: altitude
  for (let a = lo; a <= hi + 1e-6; a += step) {
    svg.append(
      s('line', { x1: m.l, x2: W - m.r, y1: y(a), y2: y(a), stroke: GRID, 'stroke-width': 1 }),
      s('text', { x: m.l - 6, y: y(a) + 4, 'text-anchor': 'end', 'font-size': 11, fill: MUTED, text: `${a} m` })
    );
  }
  // grid: local hours
  const hourStep = T > 10 * 3600 ? 2 : 1;
  const firstHour = Math.ceil(view.t0 / 3600000) * 3600000;
  for (let ms = firstHour; ms <= view.t0 + T * 1000; ms += hourStep * 3600000) {
    const xx = x(sec(ms));
    svg.append(
      s('line', { x1: xx, x2: xx, y1: m.t, y2: H - m.b, stroke: GRID, 'stroke-width': 1 }),
      s('text', { x: xx, y: H - m.b + 16, 'text-anchor': 'middle', 'font-size': 11, fill: MUTED, text: hourFmt.format(new Date(ms)) })
    );
  }

  // the curve, coloured by part
  for (const [a, b, mode] of runs(n)) {
    let line = '', area = '';
    let first = null, last = null;
    for (let i = a; i <= b; i++) {
      if (tr.alt[i] === null) continue;
      const pt = `${x(tr.t[i]).toFixed(1)},${y(tr.alt[i]).toFixed(1)}`;
      line += (line ? ' L' : 'M') + pt;
      if (first === null) first = i;
      last = i;
    }
    if (first === null) continue;
    area = `${line} L${x(tr.t[last]).toFixed(1)},${(H - m.b).toFixed(1)} L${x(tr.t[first]).toFixed(1)},${(H - m.b).toFixed(1)} Z`;
    svg.append(
      s('path', { d: area, fill: MODE_COLOUR[mode], 'fill-opacity': 0.16, stroke: 'none' }),
      s('path', { d: line, fill: 'none', stroke: MODE_COLOUR[mode], 'stroke-width': 2, 'stroke-linejoin': 'round' })
    );
  }

  // numbered places
  for (const p of markers()) {
    const xx = x(sec(p.ms));
    svg.append(
      s('g', {},
        s('title', { text: `${p.n}. ${p.label}, ${p.local_hms}` }),
        s('line', { x1: xx, x2: xx, y1: m.t - 2, y2: H - m.b, stroke: INK, 'stroke-width': 1, 'stroke-dasharray': '3 3', 'stroke-opacity': 0.55 }),
        s('circle', { cx: xx, cy: m.t - 12, r: 9, fill: '#ffffff', stroke: INK, 'stroke-width': 1.5 }),
        s('text', { x: xx, y: m.t - 8, 'text-anchor': 'middle', 'font-size': 10.5, 'font-weight': 700, fill: INK, text: String(p.n) })
      )
    );
  }

  if (view.cursor !== null) {
    const i = view.cursor;
    const xx = x(tr.t[i]);
    svg.append(s('line', { x1: xx, x2: xx, y1: m.t, y2: H - m.b, stroke: INK, 'stroke-width': 2 }));
    if (tr.alt[i] !== null) svg.append(s('circle', { cx: xx, cy: y(tr.alt[i]), r: 5, fill: '#ffffff', stroke: INK, 'stroke-width': 2.5 }));
  }

  svg.addEventListener('click', (ev) => {
    const [px] = svgPoint(svg, ev);
    const want = ((px - m.l) / (W - m.l - m.r)) * T;
    let lo2 = 0, hi2 = n - 1;
    while (hi2 - lo2 > 1) {
      const mid = (lo2 + hi2) >> 1;
      if (tr.t[mid] <= want) lo2 = mid; else hi2 = mid;
    }
    choosePoint(Math.abs(tr.t[lo2] - want) <= Math.abs(tr.t[hi2] - want) ? lo2 : hi2);
  });
  return svg;
}

function svgPoint(svg, ev) {
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX;
  pt.y = ev.clientY;
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  return [p.x, p.y];
}

function choosePoint(i) {
  view.cursor = i;
  if (view.pickKey) {
    const key = view.pickKey;
    const label = CUTS.find(([k]) => k === key)[1];
    pinned[key] = isoUtc(view.t0 + view.r.trace.t[i] * 1000);
    stopPick();
    refreshTransitions({ text: `${label} placé à ${localClock(Date.parse(pinned[key]))}. Cliquez sur « Recalculer avec ces transitions » pour mettre le résultat à jour.` });
  }
  redraw();
}

function updateReadout() {
  const el = document.getElementById('readout');
  if (!el) return;
  if (view.cursor === null) {
    el.textContent = '';
    return;
  }
  const i = view.cursor;
  const tr = view.r.trace;
  const part = view.r.report.parts[view.segAt[i]];
  const alt = tr.alt[i] === null ? 'altitude inconnue' : `${tr.alt[i]} m`;
  el.textContent = `Point choisi : ${localClock(view.t0 + tr.t[i] * 1000)}, ${alt}, ${part ? part.title.toLowerCase() : ''}.`;
}

startEngine();
