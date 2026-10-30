// The Help page, as questions and answers (Sarah, 30 October 2026): a list of topics beside them, and a search
// through all the questions. The texts are in site/i18n/<language>.js (help.<topic>.<n>.q and .a): keep them in step
// with the rules in src/mbhf (the engine), with the Upload page and with what the map shows.

import { CONFIG } from './config.js';
import { t } from './i18n.js';
import { h } from './util.js';

// the topics, and the number of questions of each
const TOPICS = [['start', 4], ['upload', 6], ['refused', 5], ['numbers', 5], ['map', 6], ['privacy', 4]];

const fold = (text) => String(text || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

export function buildHelp() {
  // what the answers may quote: the size of a file, and the uploads per day (in the first two weeks of an account)
  const values = { mb: CONFIG.MAX_FILE_MB, day: 20, first: 1000 };
  const topics = TOPICS.map(([id, n]) => {
    const items = Array.from({ length: n }, (_, i) => h('details', null,
      h('summary', null, t(`help.${id}.${i + 1}.q`)),
      h('p', null, t(`help.${id}.${i + 1}.a`, values))));
    return { id, items, section: h('section', { id: `help-${id}` }, h('h2', null, t(`help.${id}.h`)), items) };
  });
  const buttons = topics.map(({ id }) => h('button', { type: 'button', 'data-topic': id, 'aria-pressed': 'false', onclick: () => {
    search.value = '';
    show(id);
  } }, t(`help.${id}.h`)));
  const none = h('p', { class: 'hint', hidden: true }, t('help.none'));

  // one topic, or every question the search finds (opened)
  const show = (id) => {
    for (const b of buttons) b.setAttribute('aria-pressed', String(b.dataset.topic === id));
    for (const tp of topics) {
      tp.section.hidden = tp.id !== id;
      for (const d of tp.items) d.hidden = false;
    }
    none.hidden = true;
  };
  const search = h('input', { type: 'search', id: 'help-search', placeholder: t('help.search'), 'aria-label': t('help.search'), autocomplete: 'off' });
  search.addEventListener('input', () => {
    const words = fold(search.value).split(/\s+/).filter(Boolean);
    if (!words.length) { show(topics[0].id); return; }
    for (const b of buttons) b.setAttribute('aria-pressed', 'false');
    let any = false;
    for (const tp of topics) {
      let hit = false;
      for (const d of tp.items) {
        const ok = words.every((w) => fold(d.textContent).includes(w));
        d.hidden = !ok;
        d.open = ok;
        hit = hit || ok;
      }
      tp.section.hidden = !hit;
      any = any || hit;
    }
    none.hidden = any;
  });

  const page = h('div', null,
    h('h1', null, t('help.title')),
    h('p', { class: 'sub' }, t('help.sub')),
    h('div', { class: 'help' },
      h('nav', { class: 'help-nav', 'aria-label': t('help.toc') }, buttons),
      h('div', { class: 'help-body' }, search, none, topics.map((tp) => tp.section),
        h('p', { class: 'hint' }, t('help.credits')))));
  show(topics[0].id);
  return page;
}
