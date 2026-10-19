# montblanc_HF

Track analysis tools for the Mont-Blanc Hike & Fly challenge. The rules are still a working draft in Notion; this repository follows them (Notion stays the source of truth).

## What exists today

`mbhf segment` takes a recorded track and splits it into the parts of the challenge:

| part | meaning |
|---|---|
| `bike_out` | optional ride to the mountain |
| `ascent` | the walk up (this is where the Nid d'Aigle and summit cylinders will be applied) |
| `flight` | the paraglider descent |
| `walk_after_landing` | optional walk to the bike |
| `bike_return` | optional ride back |

Accepted files: IGC, GPX, KML (`gx:Track` only) and FIT. **Timestamps are mandatory**: a file without them is refused.

### How it decides

The challenge has a fixed order (bike, walk, flight, walk, bike, every part optional), so each fix is labelled with one of five ordered states and the cheapest labelling that only moves forward is found (Viterbi). The cost of a state at a fix comes from smoothed ground speed, vertical speed and altitude (no road in the Alps goes above about 2 900 m, which is what separates a flight from a steep bike descent). Everything is tunable in `SegmenterConfig`.

### Options

```bash
pip install -e ".[plot,dev]"

# one file holding the whole adventure, automatic
mbhf segment day.gpx --json result.json --plot result.png

# separate files; pin each to its mode (the program then only has to find the rest)
mbhf segment bike=ride_out.gpx walk=ascent.gpx flight=flight.igc bike=ride_back.gpx

# a watch recording the whole day + the vario's IGC for the flight: the specific file wins
# where they overlap (flight > walk > bike > unlabelled)
mbhf segment day.fit flight=vario.igc

# fix a transition by hand after looking at the plot (ISO 8601, UTC unless an offset is given)
mbhf segment day.gpx --takeoff 2026-09-12T09:41:10Z
# also: --walk-start  --landing  --bike-return-start
```

### The climbing chrono

After segmenting, `mbhf segment` also computes the chrono from leaving the Nid d'Aigle cylinder to entering the summit cylinder, with the cylinders taken from the ruleset (`src/mbhf/data/ruleset-draft.json`, or `--rules file.json`):

* Nid d'Aigle: the clock starts at the **last exit** before the summit cylinder is entered (sideways or upward), so GPS jitter on the edge cannot restart it.
* Summit: the clock stops at the first entry, which must be **on foot**. The final exit must be **by flight** for the HF/BHF conditions; a flight from a lower point still counts for the ranking.
* Crossing times are interpolated between fixes, and the result carries its uncertainty (time between the fixes around each crossing).

Only what the track contains is judged. A track that **starts at Nid d'Aigle** (the tram ride is not in it) is valid: HF badge and the Nid d'Aigle to summit rank. A track that contains a tram or lift section is not. (An unrecorded tram ride cannot be detected: that is accepted.) Later the origin of the climb (Nid d'Aigle, Bionnassay, Passy, Aiguille du Midi, Courmayeur...) can be used to filter or label results; it is not computed yet.

Hiking up by **any other route** than Nid d'Aigle is authorised: such a track has no climbing chrono and no ranking, but can still earn the HF/BHF badge (on foot to the summit, take-off from it).

### Was the approach on foot? Tram and lifts

Before the summit is entered, `mbhf.transport` looks for rides on the Mont-Blanc tramway and on lifts. A ride **flags** the track: no ranking and no badge until a human decides (the flag is evidence, not a final verdict).

* **Tramway**: a ride is a stretch that (1) follows the rail line (within 30 m for 500 m or more), (2) is at a time the tram runs, and (3) climbs at 1 200 m/h or more over a window of up to 10 min. Walking along the rails is fine: it is slow (best hikers measured so far: 600 to 800 m/h). Fast on the rails while the tram is *not* running is only reported for review.
* **Other lifts** (cable cars, gondolas, chairlifts, funiculars): a stretch following the lift line for 400 m or more at 8 km/h or more. No timetable needed. Slow lifts (fixed-grip chairlifts, drag lifts) cannot be told from walking and are **not** detected.
* **Recording gaps** (phone off in the cabin): the climb or speed implied between the last and next fix is tested the same way.
* A stretch the segmenter labelled as *bike* is ambiguous (a tram ride looks like a bike ride to it, and a cyclist beside the rails looks like a tram). It counts as a ride only if its median distance to the line is 12 m or less; otherwise it is a review item.

Line geometry comes from OpenStreetMap (© OpenStreetMap contributors, ODbL). Export the tram line and the lifts from [overpass-turbo](https://overpass-turbo.eu) (GeoJSON) and import them:

```bash
mbhf import-osm export.geojson --out src/mbhf/data/transport-osm.json
```

**Until that file is filled, the check is not performed and every result says so** ("provisional"). The tram timetable (`data/tmb-schedule.json`) is also incomplete and must be checked with the operator for each season; a date without data counts as "tram possibly running".

The JSON output lists each part, its confidence (how sharply the evidence flips at its start; `low` means "check this transition") and the transition times in the form the options above accept.

## The web app

Participants upload a track and get the climbing time, the places detected (start, transitions, Nid d'Aigle exit, summit entry and exit, each with position and altitude), the parts of the day, the checks, and the graphs.

```bash
pip install -e ".[web]"
flask --app mbhf.web:create_app run          # http://127.0.0.1:5000
# production: gunicorn "mbhf.web:create_app()"   (see the Dockerfile)
docker build -t mbhf-web . && docker run -p 8000:8000 mbhf-web
```

* **Nothing is stored.** Uploads are analysed in memory and in a temporary directory that is deleted before the page is sent. The app has no database, no cookies and no accounts, and logs neither file names nor contents. Put it behind HTTPS and make sure your proxy does not log request bodies.
* The analysis takes one to two seconds of CPU, so rate-limit uploads at the proxy. The app itself limits a request to 60 MB and a track to 200 000 points.
* Strict content security policy (no inline scripts or styles, no external requests); the page loads nothing from third parties. The only outgoing links are the "open on a map" links, which the participant clicks.
* The result is marked provisional until the tram and lift geometry is loaded (see above). It is an automatic check: the organisers still review every submission.

## Honest limits

* The thresholds are first guesses. The tests use **synthetic** tracks (invented but realistic numbers); they show the code does what it is designed to do, **not** that it works on real tracks. Real tracks still have to be tried and the thresholds tuned.
* The FIT reader has no test file yet.
* The cylinder coordinates are provisional (read from Google Maps links) and the altitude bands were tuned on a single real track.
* The tram and lift thresholds (1 200 m/h, 8 km/h, 12 m, 30 m) were set from two hiking tracks and the tram's published average; they have never seen a real tram or lift ride. The lift line geometry and the tram timetable are not loaded yet.
* Not built yet: storing submissions (the web app is stateless), a French interface, GNSS altitude bias correction, the IGC signature check, biplace comparison, the website and storage.
* Transitions can currently be fixed by time only, not by place.

## Privacy

Real tracks show where people live. `tracks/` and common track extensions are git-ignored so they are never committed by accident.

## Tests

```bash
pytest
```
