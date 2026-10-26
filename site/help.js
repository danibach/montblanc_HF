// The Help page: how to upload, what the columns of the lists mean, how the score is computed.
// The texts are in site/i18n/<language>.js (help.*): keep them in step with the rules in src/mbhf (the engine) and
// with the Upload page.

import { CONFIG } from './config.js';
import { t } from './i18n.js';
import { h } from './util.js';

const dl = (items) => h('dl', { class: 'help-terms' },
  items.map(([term, text]) => [h('dt', null, term), h('dd', null, text)]));

// The address is the router's (#/…), so a link to a place in the page cannot be a plain "#anchor": scroll instead.
const jump = (id, text) => h('a', { href: `#/help`, onclick: (ev) => {
  ev.preventDefault();
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
} }, text);

export function buildHelp() {
  const limits = { day: 20, first: 1000 };   // uploads per day, and per day in the first two weeks of an account
  return h('div', { class: 'help' },
    h('h1', null, t('help.title')),
    h('p', { class: 'sub' }, t('help.sub')),
    h('nav', { class: 'help-toc', 'aria-label': t('help.toc') },
      jump('help-upload', t('help.tocUpload')), jump('help-columns', t('help.tocColumns')),
      jump('help-score', t('help.tocScore')), jump('help-rules', t('help.tocRules')),
      jump('help-pages', t('help.tocPages'))),

    h('section', { id: 'help-upload' },
      h('h2', null, t('help.up.h')),
      h('p', null, t('help.up.intro')),
      dl([
        [t('help.up.files'), t('help.up.files.d', { mb: CONFIG.MAX_FILE_MB })],
        [t('help.up.one'), t('help.up.one.d')],
        [t('help.up.several'), t('help.up.several.d')],
        [t('help.up.multi'), t('help.up.multi.d')],
        [t('help.up.original'), t('help.up.original.d')],
        [t('help.up.limit'), t('help.up.limit.d', limits)],
        [t('help.up.dup'), t('help.up.dup.d')],
        [t('status.pending'), t('help.up.pending.d')],
        [t('help.up.refused'), t('help.up.refused.d')],
        [t('help.up.privacy'), t('help.up.privacy.d')],
      ])),

    h('section', { id: 'help-columns' },
      h('h2', null, t('help.col.h')),
      h('p', null, t('help.col.intro')),
      dl([
        [t('col.dplus'), t('help.col.dplus.d')],
        [t('col.dminus'), t('help.col.dminus.d')],
        [t('col.hike'), t('help.col.hike.d')],
        [t('col.fly'), t('help.col.fly.d')],
        [t('col.score'), t('help.col.score.d')],
        [t('col.outings'), t('help.col.outings.d')],
      ])),

    h('section', { id: 'help-score' },
      h('h2', null, t('help.score.h')),
      h('p', { class: 'help-formula' }, t('help.score.formula')),
      h('p', null, t('help.score.intro')),
      h('ul', null,
        h('li', null, t('help.score.ex', { a: 1200, b: 1100, c: 2300 })),
        h('li', null, t('help.score.one')),
        h('li', null, t('help.score.total')),
        h('li', null, t('help.score.same')))),

    h('section', { id: 'help-rules' },
      h('h2', null, t('help.rules.h')),
      h('ul', null,
        h('li', null, t('help.rules.climb')),
        h('li', null, t('help.rules.flight')),
        h('li', null, t('help.rules.ground')),
        h('li', null, t('help.rules.zero')),
        h('li', null, t('help.rules.gap')),
        h('li', null, t('help.rules.rides')))),

    h('section', { id: 'help-pages' },
      h('h2', null, t('help.pages.h')),
      dl([
        [t('nav.home'), t('help.pages.home')],
        [t('nav.all'), t('help.pages.all')],
        [t('nav.ranking'), t('help.pages.ranking')],
        [t('nav.map'), t('help.pages.map')],
        [t('nav.upload'), t('help.pages.upload')],
      ]),
      h('p', { class: 'hint' }, t('help.credits'))));
}
