from app import scoring


def _votes(*rows):
    return [dict(zip(("novel", "useful", "plausible", "investable"), r)) for r in rows]


def test_percentages_sum_to_100():
    for counts in ([1, 1, 1, 0, 0, 0], [3, 3, 1, 0, 0, 0], [7, 0, 0, 0, 0, 0], [2, 5, 9, 1, 1, 13]):
        assert sum(scoring.largest_remainder(counts)) == 100


def test_crowd_stats():
    room = scoring.crowd(_votes((5, 5, 5, 5), (3, 3, 3, 3), (1, 1, 1, 1)))
    assert room["n"] == 3
    assert room["means"]["novel"] == 3
    assert room["composite"] == 3.0
    assert sum(room["share"]["useful"]) == 100
    assert room["consensus"] > 1


def test_empty_crowd():
    assert scoring.crowd([])["n"] == 0


def test_lean():
    assert scoring.lean(4.0, 3.0) == "higher"
    assert scoring.lean(3.2, 3.0) == "with"
    assert scoring.lean(2.0, 3.0) == "lower"


def test_vote_weights_cap_guests():
    from app import config
    from app.scoring import vote_weights
    user, guest = {"user_id": 1}, {"user_id": None}
    assert vote_weights([guest, guest]) == [1.0, 1.0]  # nobody to weigh them against
    assert vote_weights([user, guest]) == [1.0, config.GUEST_WEIGHT]
    w = vote_weights([user] + [guest] * 100)
    assert abs(sum(w[1:]) / sum(w) - config.GUEST_MAX_SHARE) < 1e-9
