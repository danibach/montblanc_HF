from mbhf.duplicates import duplicate_message, same_flight


def fl(t0, t1):
    return {"takeoff": {"t": f"2026-10-06T{t0}:00+00:00"}, "landing": {"t": f"2026-10-06T{t1}:00+00:00"}}


def test_same_flight_from_two_files():
    # the watch's FIT and its Strava export: a few seconds apart
    assert same_flight([fl("15:00", "15:13")], [fl("15:00", "15:14")])


def test_two_flights_the_same_day_both_count():
    # 6 Oct 2026: same take-off at noon and in the afternoon
    assert not same_flight([fl("12:50", "13:04")], [fl("15:00", "15:13")])


def test_small_overlap_is_not_enough():
    assert not same_flight([fl("12:00", "12:20")], [fl("12:18", "12:40")])


def test_one_of_several_flights():
    assert same_flight([fl("09:00", "09:10"), fl("14:00", "14:30")], [fl("14:05", "14:28")])


def test_missing_or_broken_times():
    assert not same_flight([], [fl("15:00", "15:13")])
    assert not same_flight([{"takeoff": {}, "landing": None}], [fl("15:00", "15:13")])


def test_message():
    assert "“Mont Charvin” (2026-10-03)" in duplicate_message("Mont Charvin", "2026-10-03")
    assert "another of your outings" in duplicate_message(None, None)
