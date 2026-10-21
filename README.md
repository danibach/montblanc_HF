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

An outing counts if it has at least one flight and at least 200 m of climb on foot. Otherwise it is rejected with a reason (`no_flight`, `too_little_climb`).
Rides (car, bike, lift, skis) are detected and left out. A descent is a flight only if it is above the terrain: the engine asks Open-Meteo for the ground altitude under a few dozen points of each flight (`src/mbhf/terrain.py`), and a descent that follows the ground (ski, bike, run) is not counted. If the service is unreachable, the flight is kept and a warning says so. Accepted files: IGC, GPX, KML, TCX, FIT, with timestamps and altitude, up to 10 MB. Altitude readings that are plainly wrong (exactly 0 m because the receiver had no altitude fix, or a one-fix spike) are ignored and a warning says how many (`clean_altitudes` in `src/mbhf/parsers/common.py`); without this, a block of zeros in the mountains counted as thousands of metres climbed.

## Pages

List of outings (filter by year and country) · outing page (map, profile, stats, GPX download) · user page · user ranking (sum of scores, by year or all time) · upload (one file, or several at once: each is analysed in the browser, the list is reviewed, then published together; at most 20 uploads per day) · sign in.

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

The outing is published at once on the browser's analysis, with a "Validation pending" badge. Within ten minutes the server job recomputes it from the original file (overwriting the numbers if they differ), removes the badge, or rejects the outing (it then disappears from the public lists and the owner sees the reason). The database only accepts plausible values from the browser (D+ 100–30 000 m, score = D+ + D−). Duplicates are detected by file hash.

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
   On a database created before 2026-10-21, also run `supabase/migration-2026-10-21-tcx.sql` (accepts TCX files).
2. **Secrets** (GitHub > Settings > Secrets and variables > Actions): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service role key, never in the site).
3. **Supabase Auth**:
   - URL configuration: add `https://danibach.github.io/montblanc_HF/**` as redirect URL.
   - SMTP: the default mailer is limited to 2 e-mails per hour and to team members, so set a custom SMTP (Resend, Brevo…).
   - Attack protection: enable CAPTCHA (Turnstile) with the Turnstile secret key.
   - Optional Google: enable the provider, then set `GOOGLE_LOGIN: true` in `site/config.js`.
4. **Pages**: Settings > Pages > Source: GitHub Actions.
5. `site/config.js`: set `CONTACT_EMAIL`.
6. The free Supabase plan has no backups and pauses after a week without activity (the keep-alive in `process.yml` prevents it).

## Develop

```bash
pip install -e ".[dev]"
pytest -q                                   # engine tests (synthetic tracks)
mbhf analyse day.gpx --places               # analysis of one file, JSON
python scripts/build_site.py --out _site    # site (downloads pinned Pyodide and supabase-js)
pip install playwright && python scripts/check_site.py _site --shots shots   # end-to-end check with mocks
```

## Known limits

- Thresholds were tuned on synthetic tracks only: calibrate on real ones (`SegmenterConfig`, `OutingConfig`).
- Ski or bike descents are told from flights by the height above the terrain (model resolution 30-90 m, GPS altitude drifts 10-30 m): thresholds in `TerrainConfig` are first guesses, untested against the live service.
- The preview sends start, summit and take-off coordinates to overpass-api.de, and a few dozen flight points to api.open-meteo.com (stated in the footer).
- Display names are unique (to confirm in Notion).
- Real tracks show where people live: never commit them (`.gitignore`).

`supabase/legacy/` keeps the SQL of the former `tracks` repository, which this repository replaces.
