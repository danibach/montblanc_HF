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


def test_a_steep_fast_descent_from_a_summit_is_still_a_flight():
    assert "flight" in modes(steep_flight_then_bike())


def test_the_ride_after_landing_is_not_part_of_the_flight():
    g = steep_flight_then_bike()
    seg = segment_track(as_track(g), SegmenterConfig())
    fl = [s for s in seg.segments if s.mode == "flight"][0]
    assert abs((fl.t_end - g.marks["bike"]).total_seconds()) < 60
    assert seg.segments[-1].mode == "vehicle"
