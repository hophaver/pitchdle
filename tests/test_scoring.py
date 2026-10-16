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


def test_badges_scale_a_members_vote():
    from app import config
    from app.scoring import vote_weights
    member = lambda badge: {"user_id": 1, "badge": badge}
    guest = {"user_id": None}
    assert vote_weights([member("high"), member(""), member("low"), member("muted")]) == [
        config.HIGH_PRIORITY_WEIGHT, 1.0, config.LOW_PRIORITY_WEIGHT, 0.0]
    # The guest cap is measured against the members' total weight...
    w = vote_weights([member("high")] + [guest] * 100)
    assert abs(sum(w[1:]) / sum(w) - config.GUEST_MAX_SHARE) < 1e-9
    # ...so with only muted members there's nothing to cap guests against.
    assert vote_weights([member("muted"), guest, guest]) == [0.0, 1.0, 1.0]


def test_muted_answers_never_count():
    muted, plain = _votes((5, 5, 5, 5), (1, 1, 1, 1))
    muted |= {"user_id": 1, "badge": "muted"}
    plain |= {"user_id": 2, "badge": ""}
    for weighted in (True, False):
        room = scoring.crowd([muted, plain], weighted=weighted)
        assert room["n"] == 1 and room["signed_in"] == 1 and room["means"]["novel"] == 1
    assert scoring.crowd([muted])["n"] == 0  # all muted: no crowd, and no division by zero
