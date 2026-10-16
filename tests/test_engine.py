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
