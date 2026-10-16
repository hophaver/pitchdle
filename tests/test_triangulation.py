"""Crowd x engine x web pulse verdicts, including the threshold boundaries."""
from app.service import triangulate


def pulse(lean):
    return {"lean": lean}


def test_too_few_answers_is_unknown():
    assert triangulate(4, 4.0, 2.0, pulse("positive"), 5)[0] == "unknown"
    assert triangulate(0, None, 2.0, None, 5)[0] == "unknown"


def test_big_gap_is_divergent_either_way():
    verdict, reason = triangulate(10, 4.1, 2.8, None, 5)
    assert verdict == "divergent" and "overrates" in reason
    verdict, reason = triangulate(10, 1.8, 3.0, None, 5)
    assert verdict == "divergent" and "underrates" in reason


def test_gap_boundaries():
    assert triangulate(10, 4.0, 3.0, None, 5)[0] == "divergent"          # exactly 1.0
    assert triangulate(10, 3.9, 3.0, pulse("neutral"), 5)[0] == "unknown"  # 0.9: leaning apart
    assert triangulate(10, 3.5, 3.0, pulse("neutral"), 5)[0] == "unknown"  # exactly 0.5
    assert triangulate(10, 3.4, 3.0, pulse("neutral"), 5)[0] == "convergent"


def test_web_names_a_side_when_crowd_and_engine_disagree():
    assert "sides with the room" in triangulate(10, 4.2, 2.8, pulse("positive"), 5)[1]
    assert "sides with the engine" in triangulate(10, 4.2, 2.8, pulse("negative"), 5)[1]


def test_agreement_needs_a_pulse():
    verdict, reason = triangulate(10, 3.2, 3.0, None, 5)
    assert verdict == "unknown" and "web pulse" in reason


def test_web_against_room_and_engine_is_divergent():
    assert triangulate(10, 3.4, 3.2, pulse("negative"), 5)[0] == "divergent"
    assert triangulate(10, 1.6, 1.5, pulse("positive"), 5)[0] == "divergent"
    assert triangulate(10, 2.5, 2.4, pulse("negative"), 5)[0] == "convergent"  # middling: no contradiction


def test_silent_web_is_convergent_with_a_discovery_note():
    verdict, reason = triangulate(10, 3.2, 3.0, pulse("silent"), 5)
    assert verdict == "convergent" and "discovery" in reason
