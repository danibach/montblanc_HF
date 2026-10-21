from synth import (as_track, drive_then_walk, hike_and_fly, hike_then_drive_home, lift_then_fly,
                   steep_flight_then_bike, two_flights)

from mbhf.segment import SegmenterConfig, segment_track


def modes(g):
    return [s.mode for s in segment_track(as_track(g), SegmenterConfig()).segments]


def test_walk_flight_walk():
    assert modes(hike_and_fly()) == ["walk", "flight", "walk"]


def test_two_flights_are_both_found():
    assert modes(two_flights()) == ["walk", "flight", "walk", "flight", "walk"]


def test_a_walk_only_track_has_no_flight():
    assert modes(drive_then_walk()) == ["walk"]


def test_a_cable_car_is_a_vehicle_not_a_climb():
    m = modes(lift_then_fly())
    assert "vehicle" in m and m.count("flight") == 1


def test_a_drive_home_after_the_hike_is_not_a_flight():
    m = modes(hike_then_drive_home())
    assert "flight" not in m and m[-1] == "vehicle"


def test_flight_boundaries_are_close_to_the_truth():
    g = hike_and_fly()
    seg = segment_track(as_track(g), SegmenterConfig())
    fl = [s for s in seg.segments if s.mode == "flight"][0]
    assert abs((fl.t_start - g.marks["flight"]).total_seconds()) < 60
    assert abs((fl.t_end - g.marks["landing_walk"]).total_seconds()) < 60


def test_a_speed_riding_descent_from_a_summit_is_still_a_flight():
    assert "flight" in modes(steep_flight_then_bike())


def test_the_ride_after_landing_is_not_part_of_the_flight():
    g = steep_flight_then_bike()
    seg = segment_track(as_track(g), SegmenterConfig())
    fl = [s for s in seg.segments if s.mode == "flight"][0]
    assert abs((fl.t_end - g.marks["bike"]).total_seconds()) < 60
    assert seg.segments[-1].mode == "vehicle"


def test_a_descent_steeper_than_any_wing_glides_is_not_a_flight():
    """4.5 m/s of sink at 38 km/h is a glide of 2.3:1: a slope under the feet (ski, bike)."""
    assert "flight" not in modes(steep_flight_then_bike(sink=4.5))


def test_a_flight_after_a_ski_descent_is_found():
    """The ski descent is labelled walking, which lowers the take-off far below the summit: the launch rule
    must not throw out a steady glide for that."""
    from synth import ski_then_fly

    m = modes(ski_then_fly())
    assert m.count("flight") == 1


def test_a_slow_descent_is_not_a_flight():
    """14 km/h is a ski or a walk, not a wing: a flight has a median ground speed of at least 18 km/h."""
    from synth import slow_ski_descent

    assert "flight" not in modes(slow_ski_descent())


def test_landing_spirals_belong_to_the_flight():
    # The last minute is spent circling over the landing field: little ground covered, but still flying.
    from synth import Gen

    g = Gen(seed=11, alt=600.0)
    g.leg("walk_up", 3600, 2.6, 600 / 3600, 60, wobble=12)
    g.leg("summit_pause", 5 * 60, 0, 0.0, 60)
    g.leg("flight", 300, 35, -1.9, 230, dt=3.0, ramp=10, circling=(240, 300, 18.0, -1.9))
    g.leg("landing_walk", 6 * 60, 3.0, -0.01, 250, wobble=15)
    seg = segment_track(as_track(g), SegmenterConfig())
    fl = [s for s in seg.segments if s.mode == "flight"][0]
    assert (g.marks["landing_walk"] - fl.t_end).total_seconds() < 15
