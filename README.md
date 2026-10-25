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

An outing counts if it has at least one flight and at least 200 m of climb on foot. On foot, the climbing counts once the track holds a flight: the walk before each flight, and every walk after the last one (back to the car, up to the bivouac). A climb given up in the middle of the day, followed by a ride before any flight, is left out. Across a recording gap of more than 10 minutes the climb and the distance count only if the gap was more likely walked than driven (`gap_verdict` in `src/mbhf/outing.py`): no speed limit can tell a slow car from a fast walker, so the clues are weighed into a probability — a ride recorded just before or after the gap, the time an average walker needs for it and the share of walkers that fast; a gap with no move is a pause. When in doubt the outing says « to be checked ». A pause with the recorder on changes nothing. Otherwise it is rejected with a reason (`no_flight`, `too_little_climb`).
Rides (car, bike, lift, skis) are detected and left out. A descent is a flight only if it is above the terrain: the engine asks Open-Meteo for the ground altitude under a few dozen points of each flight (`src/mbhf/terrain.py`), and a descent that follows the ground (ski, bike, run) is not counted. If the service is unreachable, the flight is kept and a warning says so. Accepted files: IGC, GPX, KML, TCX, FIT, with timestamps and altitude, up to 10 MB. Altitude readings that are plainly wrong (exactly 0 m because the receiver had no altitude fix, or a one-fix spike) are ignored and a warning says how many (`clean_altitudes` in `src/mbhf/parsers/common.py`); without this, a block of zeros in the mountains counted as thousands of metres climbed.

## Pages

My H&Fs (the entry page: the signed-in person's own pilot page) and All (everyone's outings), both with distances and filters by year and country · outing page (map, profile, stats, GPX download) · user page (totals, filters by year and country, sortable list) · user ranking (sum of scores, by year or all time) · take-off map (heat map of the take-offs zoomed out and of the ways up on foot zoomed in, weighted by pilots; take-off markers; filters by season and year, opening on the current season, and by D+, distance and time of the climb; outings shown at the take-off of the register (`takeoff_sites`: FFVL open data, Licence Ouverte 2.0, and OpenStreetMap, ODbL, refreshed weekly by `scripts/sync_sites.py`; under 100 m tied at once, 100–200 m to confirm, farther a provisional take-off), with its source, good winds and FFVL hike & fly notes; its climbs gathered into routes (`routes`, `src/mbhf/routes.py`: starts under 500 m apart and lines within 150 m along 90 % of the way), one line per route drawn thicker the more it is climbed, with median D+, distance and time; search for a take-off, a summit or a start place; a click shows the climbs on foot that reached the take-off (past 30, only their heat map, and one outing's climb on hover) and its outings, grouped by start place, sorted, 20 at a time, never the flights; `map_outings()` in the database, `site/explorer.js`; the climbs are stored by the server job, `src/mbhf/climb.py`) · upload (one file, or several at once: each is analysed in the browser, the list is reviewed, then published together; at most 20 uploads per day, 1,000 during the first two weeks of an account) · sign in.

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

Code: `src/mbhf/` (engine), `scripts/process_pending.py` (server job), `site/` (front end), `supabase/schema-v2.sql` (database).

## Set-up (once)

1. **Database**: Supabase > SQL Editor > run `supabase/schema-v2.sql`.
   On a database created before 2026-10-21, also run `supabase/migration-2026-10-21-tcx.sql` (accepts TCX files)
   and `supabase/migration-2026-10-21-map-outings.sql` (take-off map), then run the "Process new outings" action
   once with "climbs" ticked (climbs of the outings already published). Then `supabase/migration-2026-10-23-takeoff-sites.sql`
   and `supabase/migration-2026-10-23-routes.sql`, then the "Take-off register" action once (fills the register,
   ties the published outings, makes the routes).
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
