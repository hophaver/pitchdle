from app import engine
from app.seed_data import COMPANIES

BY_NAME = {c["name"]: c for c in COMPANIES}


def test_designed_demo_cases_land_where_the_script_needs_them():
    assert engine.score(BY_NAME["TideLedger"]["evidence"])["composite"] <= 2.2
    assert engine.score(BY_NAME["Rakko Feed"]["evidence"])["composite"] >= 3.8


def test_deterministic():
    ev = BY_NAME["BrineWorks"]["evidence"]
    assert engine.score(ev) == engine.score(ev)


def test_unknowns_are_reported_not_invented():
    result = engine.score({"redstone": {"team": 4}})
    assert result["coverage"]["assessed"] == 1
    assert result["coverage"]["total"] == len(engine.factor_keys())
    assert "Tech readiness (TRL)" in result["coverage"]["unknown"]
    # Investable is scored from the one known factor; axes with nothing known fall back to the default.
    assert result["axes"]["investable"] == 4.0
    assert result["axes"]["useful"] == engine.load_weights()["unknown_axis_default"]


def test_trl_is_derived_from_stage():
    assert engine.factor_value({"trl_stage": "commercial"}, "trl") == 5.0
    assert engine.factor_value({"trl_stage": "idea"}, "trl") == 0.0
    assert engine.factor_value({"trl_stage": "made-up"}, "trl") is None


def test_readiness_levels_match_the_brief():
    rd = engine.readiness(BY_NAME["Rakko Feed"]["evidence"])
    assert set(rd) == {"ocean_impact", "business", "tech", "investment"}
    for key, spec in rd.items():
        assert spec["label"] and spec["coverage"]["assessed"] >= 1
    assert rd["tech"]["trl"] == 8  # "deployed" stage in seed data
    assert rd["tech"]["score"] is not None
    assert rd["ocean_impact"]["score"] is not None


def test_readiness_is_honest_about_missing_evidence():
    rd = engine.readiness({})
    assert rd["tech"]["trl"] is None and rd["tech"]["score"] is None
    assert rd["ocean_impact"]["coverage"]["assessed"] == 0


def test_theses_return_score_and_evidence_grounded_why():
    th = engine.theses(BY_NAME["Rakko Feed"]["evidence"])
    assert set(th) == {"apelago", "redstone"}
    for key, spec in th.items():
        assert spec["score"] is not None
        assert spec["why"]
        assert spec["strengths"] and spec["coverage"]["assessed"] >= 1
    # Rakko Feed is strong on fundamentals, so the investment fit should be high.
    assert th["redstone"]["score"] >= 3.8
    # The demo case with a weak team scores low on the accelerator/team-weighted fit.
    assert engine.theses(BY_NAME["TideLedger"]["evidence"])["apelago"]["score"] <= 3.0


def test_theses_unknown_evidence_reports_not_invented():
    th = engine.theses({})["redstone"]
    assert th["score"] is None and th["why"] == "Not enough evidence to assess fit."


def test_factor_trail_lists_every_known_factor():
    trail = engine.factor_trail(BY_NAME["BrineWorks"]["evidence"])
    assert trail and all({"key", "label", "value"} <= set(f) for f in trail)
    labels = [f["label"] for f in trail]
    assert "Patents" in labels  # BrineWorks has patents: 0 -> a 1.0 factor is present
    assert "Tech readiness (TRL)" in labels
