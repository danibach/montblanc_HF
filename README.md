# H&F Tracks (montblanc_HF, V2)

An XContest-style Hike & Fly platform. A contributor sends **only the track**; the engine reads it and publishes the outing.
The rules and the concept stay in Notion (source of truth): *Projet // Mont-Blanc Hike & Fly*.

## What the engine extracts

| value | how |
|---|---|
| walk start | first fix on foot; place and country from OpenStreetMap |
| highest summit on foot | highest point of the walking parts; named summit within 500 m |
| take-off | first fix of the first flight; named peak/saddle within 600 m |
| D+ on foot (m) | sum of climbs on foot, 30 s-smoothed altitude, 15 m hysteresis |
| D− in flight (m) | take-off altitude minus landing altitude, per flight |
| walk distance (km) | path length on foot |
| flight distance (km) | FAI free distance, up to 3 turnpoints |
| score | D+ on foot + D− in flight (`score_version` 1) |

An outing counts if it has at least one flight and at least 200 m of climb on foot. On foot, the climbing counts once the track holds a flight: the walk before each flight, and every walk after the last one (back to the car, up to the bivouac). A climb given up in the middle of the day, followed by a ride before any flight, is left out. Across a recording gap of more than 10 minutes the climb and the distance count only if the gap was more likely walked than driven (`gap_verdict` in `src/mbhf/outing.py`): no speed limit can tell a slow car from a fast walker, so the clues are weighed into a probability — a ride recorded just before or after the gap, the time an average walker needs for it and the share of walkers that fast; a gap with no move is a pause. When in doubt the outing says « to be checked ». A pause with the recorder on changes nothing. Otherwise it is rejected with a reason (`no_flight`, `too_little_climb`), and words that say what to do (`src/mbhf/advice.py`): a fast descent from the top read as a ride, or a GPX written by a track editor (Adze, gpx.studio…, from its `creator`), asks for the original recording, since an edited file often carries the map's ground altitude instead of the measured one.
Rides (car, bike, lift, skis) are detected and left out. A descent is a flight only if it is above the terrain: the engine asks Open-Meteo for the ground altitude under a few dozen points of each flight (`src/mbhf/terrain.py`), and a descent that follows the ground (ski, bike, run) is not counted. If the service is unreachable, the flight is kept and a warning says so. Accepted files: IGC, GPX, KML, TCX, FIT, with timestamps and altitude, up to 10 MB. Altitude readings that are plainly wrong (exactly 0 m because the receiver had no altitude fix, or a one-fix spike) are ignored and a warning says how many (`clean_altitudes` in `src/mbhf/parsers/common.py`); without this, a block of zeros in the mountains counted as thousands of metres climbed.

## Pages

Titles: an outing is named after its take-off, « Pointe de Beauregard from Les Verrier » (`src/mbhf/titles.py`: FFVL names cleaned of opening dates, seasons in brackets and commune prefixes; given again by the server job and the weekly take-off sync).

My H&Fs (the entry page: the signed-in person's own pilot page) and All (everyone's outings), both with distances and filters by year and country · outing page (map, profile, stats, GPX download) · user page (totals, filters by year and country, sortable list) · user ranking (sum of scores, by year or all time) · take-off map (heat map of the take-offs zoomed out and of the ways up on foot zoomed in, weighted by pilots; take-off markers; filters by season and year, opening on the current season, and by D+, distance and time of the climb; outings shown at the take-off of the register (`takeoff_sites`: FFVL open data, Licence Ouverte 2.0, and OpenStreetMap, ODbL, refreshed weekly by `scripts/sync_sites.py`; under 100 m tied at once, 100–200 m to confirm, farther a provisional take-off; a provisional take-off of the same name within 150 m and 100 m of height is the same one; FFVL sites for speed riding, kites or hang gliders only are left out), with its source, good winds and FFVL hike & fly notes; its climbs gathered into routes (`routes`, `src/mbhf/routes.py`: starts under 500 m apart and lines within 150 m along 80 % of the way), one median line per route (every climb laid along the most central one, the middle of them kept), the ways of one start gathered in a folder and named « via … » after a place each goes by (OpenStreetMap), drawn thin on a white casing, one colour per start, with median D+, distance and time; search for a take-off, a summit or a start place; a click shows the climbs on foot that reached the take-off (past 30, only their heat map, and one outing's climb on hover) and its outings, grouped by start place, sorted, 20 at a time, never the flights; `map_outings()` in the database, `site/explorer.js`; the climbs are stored by the server job, `src/mbhf/climb.py`) · upload (one file, or several at once: each is analysed in the browser, the list is reviewed, then published together; at most 20 uploads per day, 1,000 during the first two weeks of an account; files that follow one another — each starting at most 14 h after the previous one ended and within 2 km of where it ended, without overlap, 7 days and 10 files at most — are offered to be joined into one outing, such as a bike ride to the start, the climb and flight and the ride home: `src/mbhf/multi.py`, the time between two files is a recording gap like any other, the original files are kept, listed in `file_parts`, and joined again by the server job) · sign in.

## Languages

The site is in French, English, German and Italian. The language is the one the visitor picked with the selector in the header (kept in this browser), else the first language of the browser's list (`navigator.languages`) that the site has (Swiss German is read in standard German), else English. The browser's language is used rather than the place of the connection: it is what the visitor reads, and a static page never sees the visitor's address. Numbers and dates are written by `Intl` in the visitor's own format (1 234 / 1,234 / 1’234; « 29 sept. 2021 »).

The texts are in `site/i18n/<code>.js`, one file per language with the same keys, loaded when needed (English is always loaded and is what a missing text falls back to); `site/i18n.js` holds the detection and `t()` / `tr()`. No text is translated on the fly and none leaves the site. A text is a string with `{name}` places, or `{ one, other }` for a plural. `tests/test_i18n.py` checks that the four files have the same keys, places and plural forms, and that every text the code asks for exists and is used.

To add a language: copy `site/i18n/en.js` to `<code>.js` and translate it, add the code to `LANGS` in `site/i18n.js`, and run `pytest tests/test_i18n.py`. The German and Italian texts have not yet been read by a native speaker.

Limits: the messages written by the engine and the server (warnings, the reason a track is refused) are English, and an outing's stored title keeps its English form in the database (it is written again in the visitor's language when shown).

## How it works

```
browser ── analysis in Python (Pyodide) ── preview ──┐
   │                                                  │ publish = file + result (unverified)
   ▼                                                  ▼
 GitHub Pages (static site)               Supabase Storage (private) + `outings` row (published, unverified)
                                                      │
                          GitHub Actions (every 10 min / on demand)
                          re-analyses the file with the same Python code,
                          fills in places (Overpass), confirms or rejects
```

The outing is published at once on the browser's analysis, with a "Validation pending" badge. Within ten minutes the server job recomputes it from the original file (overwriting the numbers if they differ), removes the badge, or rejects the outing (it then disappears from the public lists and the owner sees the reason). The database only accepts plausible values from the browser (D+ 200–30 000 m, the same floor as the engine, score = D+ + D−). Duplicates are detected by file hash, and the same flight sent from another file (a watch's FIT and its Strava export) is refused too: a pilot cannot fly twice at the same time, so a flight that overlaps one of their outings already counted for at least half of its time is the same flight (`src/mbhf/duplicates.py`, checked in the browser before sending and again by the server job).

| part | role |
|---|---|
| GitHub Pages | static site, built by `.github/workflows/site.yml` on every push to `main` |
| Supabase | Postgres (+ row level security), Auth (magic link, optional Google), private file storage |
| GitHub Actions | `.github/workflows/process.yml`: analysis of waiting tracks, keep-alive |
| Cloudflare Turnstile | anti-bot on sign-in (enabled in Supabase Auth) |
| OpenStreetMap | place names, country (Overpass), map tiles (OpenTopoMap, fair use) |
| Open-Meteo | ground altitude under the flights (free, no key; terms: non-commercial use) |

Code: `src/mbhf/` (engine), `scripts/process_pending.py` (server job), `site/` (front end; its texts in `site/i18n/`), `supabase/schema-v2.sql` (database).

## Set-up (once)

1. **Database**: Supabase > SQL Editor > run `supabase/schema-v2.sql`.
   On a database created before 2026-10-21, also run `supabase/migration-2026-10-21-tcx.sql` (accepts TCX files)
   and `supabase/migration-2026-10-21-map-outings.sql` (take-off map), then run the "Process new outings" action
   once with "climbs" ticked (climbs of the outings already published). Then `supabase/migration-2026-10-23-takeoff-sites.sql`
   and `supabase/migration-2026-10-23-routes.sql`, then the "Take-off register" action once (fills the register,
   ties the published outings, makes the routes). Then `supabase/migration-2026-10-25-file-parts.sql` (one outing
   in several files).
2. **Secrets** (GitHub > Settings > Secrets and variables > Actions): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service role key, never in the site).
3. **Supabase Auth**:
   - URL configuration: add `https://danibach.github.io/montblanc_HF/**` as redirect URL.
   - SMTP: the default mailer is limited to 2 e-mails per hour and to team members, so set a custom SMTP (Resend, Brevo…).
   - Attack protection: enable CAPTCHA (Turnstile) with the Turnstile secret key.
   - Optional Google: enable the provider, then set `GOOGLE_LOGIN: true` in `site/config.js`.
4. **Pages**: Settings > Pages > Source: GitHub Actions.
5. `site/config.js`: set `CONTACT_EMAIL`.
6. The free Supabase plan has no backups and pauses after a week without activity (the keep-alive in `process.yml` prevents it).
7. **Backups**: add the secret `BACKUP_PASSPHRASE` (a long random passphrase, kept in a password manager outside
   GitHub too); see below.

## Automatic migrations

When a pull request that adds a `supabase/migration-AAAA-MM-JJ-….sql` file is merged, the "Migrate" action
(`.github/workflows/migrate.yml`, script `scripts/apply_migrations.sh`) applies it to the Supabase database: no more
SQL Editor by hand. Each file runs in **one transaction** (all or nothing) and is then noted in the table
`public.applied_migrations` (row level security on, no policy: the public API cannot touch it), so it is never run
twice. Files are applied in name order, so the date in the name is the order. A migration that fails turns the run red
and changes nothing. Write migrations so that they can be run again (`if not exists`, `create or replace`,
`drop policy if exists`): the first run applies every existing file once.

Once (Dani): Supabase > Connect > "Session pooler" connection string (the direct one is IPv6 only, which GitHub cannot
reach), with the database password put in place of `[YOUR-PASSWORD]`, saved as the secret `SUPABASE_DB_URL`. This secret
gives full rights on the database: only in GitHub secrets, never in the repository or in Notion. Without it the action
does nothing and stays green. First run by hand: Actions > Migrate > Run workflow with `dry_run` ticked (lists what would
be applied), then again without. Do not also run a new migration by hand in the SQL Editor: it would be applied twice
(harmless if it is re-runnable).

## Backups

Every Monday, the "Backup" action (`.github/workflows/backup.yml`, also run by hand from the Actions tab) copies the
tables (with the traces), the accounts and the original track files (`scripts/backup.py`), encrypts them with
`BACKUP_PASSPHRASE` (AES-256) and stores the file in a **private** repository, `danibach/montblanc_HF-backups` by
default (repository variable `BACKUP_REPO`), keeping the last 12 (about three months). Nothing is left in this public
repository. The private repository is written again each time (one commit), so it does not grow with the weeks.
Free, nothing outside GitHub. Without its secrets the run fails rather than store an unencrypted or public copy.

Once (Dani): create the private repository `montblanc_HF-backups` (empty is fine); a fine-grained personal access
token with "Contents: read and write" on that repository only, saved here as the secret `BACKUP_REPO_TOKEN`; a long
random passphrase saved as the secret `BACKUP_PASSPHRASE` and in a password manager (a secret cannot be read back).
Then run the action once by hand and check that a folder `hf-tracks-backup-YYYY-MM-DD` appears in the private repository.

To restore: take the folder of the backup from the private repository, then

```bash
cat hf-tracks-backup-YYYY-MM-DD.tar.gz.gpg.part-* > backup.tar.gz.gpg   # the parts of 90 MB, in order
gpg -d backup.tar.gz.gpg > backup.tar.gz && tar -xzf backup.tar.gz         # asks the passphrase
python scripts/restore_backup.py backup          # writes backup/restore.sql
```

Run `supabase/schema-v2.sql` (and the later migrations the backup has tables for), then `backup/restore.sql` in the
SQL Editor, then `SUPABASE_URL=… SUPABASE_SERVICE_KEY=… python scripts/restore_backup.py backup --upload-files` for the
track files. Rows still there are kept. The accounts are recreated in `auth.users` (id, e-mail), a way Supabase does
not document: try a restore once on a test project.

## Develop

```bash
pip install -e ".[dev]"
pytest -q                                   # engine tests (synthetic tracks)
mbhf analyse day.gpx --places               # analysis of one file, JSON
python scripts/build_site.py --out _site    # site (downloads pinned Pyodide and supabase-js)
pip install playwright && python scripts/check_site.py _site --shots shots   # end-to-end check with mocks
python scripts/preview_map.py --real        # the take-off map with the live public outings (read-only), http://127.0.0.1:8765/#/map
python scripts/preview_map.py --crowded     # the same with made-up outings, one take-off with 120 of them
python scripts/preview_map.py --real --sites   # live outings tied to the take-off register, in memory (--no-osm when Overpass is down)
```

## Known limits

- Thresholds were tuned on synthetic tracks only: calibrate on real ones (`SegmenterConfig`, `OutingConfig`).
- Ski or bike descents are told from flights by the height above the terrain (model resolution 30-90 m, GPS altitude drifts 10-30 m): thresholds in `TerrainConfig` are first guesses, untested against the live service.
- The preview sends start, summit and take-off coordinates to overpass-api.de, and a few dozen flight points to api.open-meteo.com (stated in the footer).
- Display names are unique (to confirm in Notion).
- Real tracks show where people live: never commit them (`.gitignore`).

`supabase/legacy/` keeps the SQL of the former `tracks` repository, which this repository replaces.
