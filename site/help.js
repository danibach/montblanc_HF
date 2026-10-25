// The Help page: how to upload, what the columns of the lists mean, how the score is computed.
// Plain text only; keep it in step with the rules in src/mbhf (the engine) and with the Upload page.

import { CONFIG } from './config.js';
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
  return h('div', { class: 'help' },
    h('h1', null, 'Help'),
    h('p', { class: 'sub' }, 'How to send a track, what the columns mean, and how the score is worked out.'),
    h('nav', { class: 'help-toc', 'aria-label': 'On this page' },
      jump('help-upload', 'Upload'), jump('help-columns', 'The columns'),
      jump('help-score', 'The score'), jump('help-rules', 'What counts'),
      jump('help-pages', 'The pages')),

    h('section', { id: 'help-upload' },
      h('h2', null, 'Upload'),
      h('p', null, 'You need an account to send a track (a sign-in link by e-mail, no password). The analysis runs in your browser; nothing leaves it until you publish.'),
      dl([
        ['Files', `IGC, GPX, KML, TCX or FIT, up to ${CONFIG.MAX_FILE_MB} MB each, with time stamps and altitude. A plain KML line has no time stamps and is refused.`],
        ['One file', 'Choose it, read the preview (score, D+, D−, map, profile, place names), then press Publish. Nothing is public before that.'],
        ['Several files at once', 'Each one is analysed in turn. By default each outing is published as soon as it is ready, so nothing is lost if you close the page; untick the box to review the list first and publish together. Keep the page open until the list is finished.'],
        ['One outing in several files', 'A bike ride to the start, the climb and flight, the ride home: drop the files together. When one starts soon after the previous ended, close to where it ended, you are offered to join them as one outing. The original files are kept and joined again on the server.'],
        ['Original file only', 'Send the recording exactly as your device or app saved it. Do not edit it, merge it or correct its elevation with a track tool: the flight altitudes must be the measured ones, not adjusted to the terrain. A track whose altitudes follow the ground is refused, unless you then mark the flight by hand (see below).'],
        ['Daily limit', 'At most 20 uploads per day, and up to 1,000 per day during the first two weeks of an account, to move a whole logbook. When the limit is reached the rest stays in the list: send it again the next day.'],
        ['Duplicates', 'The same file twice, or the same flight sent from two files (a watch and a phone, say), counts once. To replace an outing, delete it first.'],
        ['Validation pending', 'A published outing appears at once, on the browser analysis. The server then runs the analysis again on the original file, in a few minutes: the badge disappears, the numbers are corrected, or the outing is refused.'],
        ['Refused tracks', 'The message says why and what to do (no flight found, less than 200 m of climbing on foot, the recording stops at take-off, no altitude, damaged file…). A track with no flight found goes to the list "Without a flight", where you can mark the flight by hand on a map: click the take-off, then the landing. Only mark what really was a flight.'],
        ['Privacy and deleting', 'A published outing is public: map, profile and statistics. The original file stays private. You can delete an outing from its page, an upload that is waiting or refused from your own page, and your whole account (with its outings and files) from your own page.'],
      ])),

    h('section', { id: 'help-columns' },
      h('h2', null, 'The columns of the lists'),
      h('p', null, 'The same columns appear in My H&Fs, All, the page of a pilot and, as totals, in Pilots. Click a heading to sort by it.'),
      dl([
        ['D+ (m)', 'Height climbed on foot, in metres: the sum of the climbs, on an altitude averaged over about a minute. A dip of less than 15 m does not end a climb, which keeps GPS noise out. The climb after the last flight counts too (back to the car, up to the bivouac); a climb given up before a ride in a vehicle does not.'],
        ['D− (m)', 'Height lost in flight, in metres: for each flight, the altitude at take-off minus the altitude at landing. Thermals are ignored: only the net difference counts, so climbing in a thermal does not add anything.'],
        ['Hike (km)', 'Distance covered on foot, in kilometres, summed over the whole track. Rides in a vehicle (car, lift, bike) are not counted.'],
        ['Fly (km)', 'The FAI free distance, in kilometres: the longest route flown from a start point through up to three turn points to a finish, summed over all the flights of the outing. It is the "Free distance FAI" of the page of an outing. It is not part of the score.'],
        ['Score', 'D+ on foot plus D− in flight, in metres (see below).'],
        ['Outings', 'In Pilots: the number of published outings of the pilot. The totals follow the year and country filters.'],
      ])),

    h('section', { id: 'help-score' },
      h('h2', null, 'The score'),
      h('p', { class: 'help-formula' }, 'Score = D+ on foot + D− in flight'),
      h('p', null, 'The score measures how much vertical height an outing covers, by its own effort and by its flight, with a formula anyone can redo. Distance does not enter the score: the aim is not to fly the farthest.'),
      h('ul', null,
        h('li', null, 'An outing with 1,200 m of D+ and 1,100 m of D− scores 2,300.'),
        h('li', null, 'Several walks and flights in one track are one adventure: the D+ and the D− are added.'),
        h('li', null, 'A pilot\'s total (page Pilots) is the sum of the scores of all their published outings, for a year or all time. Every outing counts, not only the best ones.'),
        h('li', null, 'The score is computed by the same code in your browser and on the server, so the preview and the final result agree.'))),

    h('section', { id: 'help-rules' },
      h('h2', null, 'What counts as an outing'),
      h('ul', null,
        h('li', null, 'At least one flight, and at least 200 m of climbing on foot, both within the recorded track, in any order (e.g. a flight followed by a hike to the next take-off counts). Climbs by motorised means, such as a lift ride or a vehicle, do not count.'),
        h('li', null, 'A flight must lose at least 30 m of height and glide with a ratio of at least 4 (a speed-riding wing 4 to 5, a paraglider 7 to 9). Take-off does not have to be at the summit.'),
        h('li', null, 'A descent slower than about 18 km/h, or one that follows the ground (ski, run, bike), is not a flight. The tracks are compared with the ground altitude (Open-Meteo).'),
        h('li', null, 'Altitudes recorded as 0 m are ignored, with a warning: a receiver without an altitude fix would otherwise count thousands of metres of climb.'),
        h('li', null, 'A recording gap of more than 10 minutes is judged walked or driven, from what was recorded around it, the time it took and what a walker could do. If it was probably walked it counts; if it was probably a ride, nothing is counted across it. A doubtful case is decided anyway and flagged "to be checked".'),
        h('li', null, 'Rides in a vehicle are marked and left out of the score.'))),

    h('section', { id: 'help-pages' },
      h('h2', null, 'The pages'),
      dl([
        ['My H&Fs', 'Your own page: your totals and your outings, with filters by year and country.'],
        ['All', 'The outings of everyone, with the same filters and sorting.'],
        ['Pilots', 'The ranking by total score, with each pilot\'s outings, D+, D−, distances on foot and in flight; search a pilot by name.'],
        ['Map', 'The take-offs and the ways up on foot. Zoomed out, a heat map of the take-offs; zoomed in, of the climbs. Click a take-off to see the routes that lead to it and their outings; hover or click a route line to light it.'],
        ['Upload', 'Send one or several tracks (see above).'],
      ]),
      h('p', { class: 'hint' }, 'Place names come from OpenStreetMap and the take-off register from FFVL open data (Licence Ouverte 2.0) and OpenStreetMap (ODbL).')));
}
