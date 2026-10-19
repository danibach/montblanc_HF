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

The JSON output lists each part, its confidence (how sharply the evidence flips at its start; `low` means "check this transition") and the transition times in the form the options above accept.

## Honest limits

* The thresholds are first guesses. The tests use **synthetic** tracks (invented but realistic numbers); they show the code does what it is designed to do, **not** that it works on real tracks. Real tracks still have to be tried and the thresholds tuned.
* The FIT reader has no test file yet.
* Not built yet: the Nid d'Aigle and summit cylinders, the speed-based detection of the tramway on the approach, GNSS altitude bias correction, the IGC signature check, biplace comparison, the website and storage.
* Transitions can currently be fixed by time only, not by place.

## Privacy

Real tracks show where people live. `tracks/` and common track extensions are git-ignored so they are never committed by accident.

## Tests

```bash
pytest
```
