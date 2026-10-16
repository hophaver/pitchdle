from app import scoring

ENGINE = {"novel": 2.0, "useful": 3.0, "plausible": 1.0, "investable": 4.5}


def test_perfect_read_scores_near_1000():
    exact = {"novel": 2, "useful": 3, "plausible": 1, "investable": 4}
    assert 900 < scoring.vote_points(exact, ENGINE) <= 1000


def test_points_decay_with_distance():
    assert scoring.axis_points(3, 3) > scoring.axis_points(4, 3) > scoring.axis_points(5, 3)


def test_tiles():
    assert scoring.tile(2, 2.4) == {"value": 2, "color": "green", "arrow": "✓"}
    assert scoring.tile(2, 3.0)["color"] == "yellow" and scoring.tile(2, 3.0)["arrow"] == "↑"
    assert scoring.tile(5, 1.0) == {"value": 5, "color": "grey", "arrow": "↓↓"}


def test_round_two_only_adds_half_of_improvement():
    assert scoring.card_points(600, 800, None) == 700
    assert scoring.card_points(600, 400, None) == 600
    assert scoring.card_points(600, None, 120) == 720


def test_percentages_sum_to_100():
    for counts in ([1, 1, 1, 0, 0, 0], [3, 3, 1, 0, 0, 0], [7, 0, 0, 0, 0, 0], [2, 5, 9, 1, 1, 13]):
        assert sum(scoring.largest_remainder(counts)) == 100


def _votes(*rows):
    return [dict(zip(("novel", "useful", "plausible", "investable"), r)) for r in rows]


def test_bonus_only_for_right_against_a_wrong_room():
    room = scoring.crowd(_votes(*([(5, 5, 5, 5)] * 9 + [(2, 3, 1, 4)])))
    bonus, axes = scoring.against_current_bonus({"novel": 2, "useful": 3, "plausible": 1, "investable": 4}, ENGINE, room)
    assert bonus > 0 and "plausible" in axes
    wrong, _ = scoring.against_current_bonus({"novel": 5, "useful": 5, "plausible": 5, "investable": 5}, ENGINE, room)
    assert wrong == 0


def test_bonus_waits_for_enough_votes():
    room = scoring.crowd(_votes((5, 5, 5, 5), (2, 3, 1, 4)))
    assert scoring.against_current_bonus({"novel": 2, "useful": 3, "plausible": 1, "investable": 4}, ENGINE, room) == (None, [])


def test_tiers():
    assert scoring.read_tier(100, [100, 200]) is None  # too few votes
    assert scoring.read_tier(10, [10, 20, 30, 40, 50, 60])["key"] == "surface"
    assert scoring.read_tier(60, [10, 20, 30, 40, 50, 60])["key"] == "deep"
    room = list(range(20))
    assert scoring.read_tier(19, room)["key"] == "one"


def test_zones():
    assert scoring.zone(0)["name"] == "Sunlight"
    assert scoring.zone(3870)["name"] == "Midnight"
    assert scoring.zone(9000)["name"] == "Hadal"
