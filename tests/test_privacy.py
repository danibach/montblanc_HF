from mbhf.privacy import HIDE_M, public_climb, public_parts, public_span, public_trace
from mbhf.segment import FLIGHT, VEHICLE, WALK

# fixes every 100 m north (0.0009 degree), one a minute
def trace(modes):
    n = len(modes)
    return {"t0": "2026-10-03T08:00:00Z", "t": [60.0 * i for i in range(n)], "lat": [45.90 + 0.0009 * i for i in range(n)],
            "lon": [6.45] * n, "alt": [600.0 + 50 * i for i in range(n)], "m": list(modes)}


def test_the_first_500_m_of_the_climb_are_left_out():
    tr = trace([WALK] * 20 + [FLIGHT] * 5)
    first, last = public_span(tr)
    assert 5 <= first <= 6  # 500 m at 100 m a fix
    assert last == 24  # the trace ends in flight: nothing after a landing to hide


def test_a_drive_before_the_climb_is_left_out_whole():
    tr = trace([VEHICLE] * 15 + [WALK] * 20 + [FLIGHT] * 5)
    first, _ = public_span(tr)
    assert first >= 15 + 5  # the whole drive, then 500 m of the climb


def test_everything_after_the_last_landing_is_left_out():
    tr = trace([WALK] * 20 + [FLIGHT] * 5 + [WALK] * 10 + [VEHICLE] * 10)
    _, last = public_span(tr)
    assert last == 25  # the landing fix, nothing of the way back


def test_the_start_goes_up_to_where_the_trace_joins_the_itinerary():
    # 1.2 km in a field 400 m west of the path, then up the path the others take
    modes = [WALK] * 32 + [FLIGHT] * 5
    tr = trace(modes)
    tr["lon"] = [6.45 - (0.005 if i < 12 else 0) for i in range(len(modes))]
    itinerary = [[45.90 + 0.0009 * i, 6.45] for i in range(40)]
    first, _ = public_span(tr, itinerary)
    assert first == 12


def test_the_public_trace_starts_its_clock_at_its_first_fix():
    tr = trace([WALK] * 20 + [FLIGHT] * 5)
    pub = public_trace(tr, 6, 24)
    assert pub["t"][0] == 0 and pub["t0"] == "2026-10-03T08:06:00Z"
    assert len(pub["lat"]) == len(pub["m"]) == 19 and pub["lat"][0] == tr["lat"][6]


def test_the_map_climb_starts_where_the_public_trace_does():
    tr = trace([WALK] * 20 + [FLIGHT] * 5)
    climb = {"line": [[tr["lat"][i], tr["lon"][i]] for i in range(0, 21, 2)], "dplus_m": 1000}
    pub = public_climb(climb, tr, 6)
    assert pub["line"][0] == [tr["lat"][6], tr["lon"][6]] and pub["dplus_m"] == 1000


def test_no_trace_no_public_trace():
    assert public_parts(None, None) == {"trace_public": None, "climb_public": None}
    assert HIDE_M == 500.0
