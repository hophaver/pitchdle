"""The explainable engine: ladders with blockers, coverage that can't pass for confidence, patents as not
applicable, distinct labels, and thesis fit as gates plus a stage window."""
from app import engine, service
from app.seed_data import COMPANIES

BY_NAME = {c["name"]: c for c in COMPANIES}


def quoted(answer: str, quote: str = "Three paying pilots signed with Baltic ports", source: str = "news") -> dict:
    return {"answer": answer, "quote": quote, "source": source}


def brl(answers: dict) -> dict:
    return {"checklist": {f"business.{n}": a for n, a in answers.items()}}


# --- ladders -------------------------------------------------------------------------------------------------

def test_a_company_stuck_at_brl_3_reports_the_blocker():
    ev = brl({1: quoted("yes"), 2: quoted("yes"), 3: quoted("yes"), 4: quoted("no", "No revenue model yet"),
              6: quoted("yes")})
    lv = engine.readiness(ev)["business"]
    assert lv["method"] == "ladder" and lv["scale"] == "BRL"
    assert lv["level"] == 3 and lv["claimed_max"] == 6  # a later 'yes' doesn't skip the gap
    assert lv["blocker"] == {"n": 4, "text": "no full business model with revenues and costs", "kind": "no"}
    assert lv["source"] == "news" and lv["score"] == round(2 / 8 * 5, 1)


def test_an_unquoted_or_inferred_yes_is_unverified_not_counted():
    no_quote = engine.ladder(brl({1: quoted("yes"), 2: quoted("yes", quote="")}), "business")
    assert no_quote["level"] == 1 and no_quote["blocker"]["kind"] == "unverified"
    inferred = engine.ladder(brl({1: quoted("yes", source="ai")}), "business")
    assert inferred["level"] is None and inferred["score"] is None and inferred["blocker"]["n"] == 1
    # The host's own word counts without a quote.
    host = engine.ladder(brl({1: {"answer": "yes", "by": "host"}}), "business")
    assert host["level"] == 1 and host["source"] == "host"


def test_the_level_stands_on_its_weakest_source():
    ev = brl({1: quoted("yes", source="registry"), 2: quoted("yes", source="site")})
    assert engine.ladder(ev, "business")["source"] == "site"


def test_ladders_are_deterministic_and_absent_without_answers():
    ev = BY_NAME["Rakko Feed"]["evidence"]
    assert engine.ladder(ev, "business") == engine.ladder(ev, "business")
    assert engine.ladder({}, "business") is None
    assert engine.readiness({"brl": {"market": 4}})["business"]["method"] == "factors"


def test_the_trl_ladder_overrides_the_stage_and_feeds_landscape_matching():
    ev = {"trl_stage": "commercial", "checklist": {f"tech.{n}": quoted("yes") for n in range(1, 5)}}
    assert engine.TRL_number(ev) == 4 and engine.readiness(ev)["tech"]["trl"] == 4


def test_the_demo_cases_show_their_blockers():
    tide = engine.readiness(BY_NAME["TideLedger"]["evidence"])
    assert tide["business"]["level"] == 2 and tide["business"]["blocker"]["kind"] == "unverified"
    assert tide["tech"]["level"] == 2 and tide["tech"]["blocker"]["text"] == "no proof of concept"
    rakko = engine.readiness(BY_NAME["Rakko Feed"]["evidence"])
    assert rakko["business"]["level"] == 8 and rakko["business"]["source"] == "deck"


# --- coverage, patents, labels ---------------------------------------------------------------------------------

def test_low_coverage_is_pulled_toward_the_prior():
    lv = engine.readiness({"brl": {"market": 5}})["business"]  # 1 of 4 factors known
    assert lv["raw"] == 5.0 and lv["score"] < 5.0 and lv["low_coverage"]
    assert lv["score"] == 3.5  # prior 2 + (5 - 2) x (1/4) / 0.5
    full = engine.readiness({"brl": {"market": 5, "value_prop": 5}})["business"]  # half known: left alone
    assert full["score"] == 5.0 and not full["low_coverage"]
    assert engine.readiness({})["business"]["score"] is None  # unknown is never filled in


def test_zero_patents_is_not_applicable_not_a_bad_score():
    ev = {"patents": 0, "redstone": {"team": 4}}
    assert engine.factor_value(ev, "patents") is None and engine.factor_na(ev, "patents")
    cov = engine.score(ev)["coverage"]
    assert "Patents" in cov["na"] and "Patents" not in cov["unknown"]
    assert cov["total"] == len(engine.factor_keys()) - 1
    assert engine.factor_value({"patents": 2}, "patents") == 4.0


def test_shared_factor_names_stay_distinguishable():
    shorts = {f["key"]: f["short_label"] for f in engine.factor_trail(BY_NAME["Rakko Feed"]["evidence"])}
    assert shorts["brl.market"] == "Market · BRL" and shorts["redstone.market"] == "Market · Redstone"
    assert shorts["brl.business_model"] != shorts["redstone.business_model"]
    assert shorts["redstone.team"] == "Team"  # no clash, no tag


def test_an_ai_only_investment_factor_is_capped():
    ev = {"redstone": {"market": 5}, "support": {"redstone.market": {"source": "ai", "quote": ""}}}
    assert engine.readiness(ev)["investment"]["raw"] == 3.5
    sourced = {"redstone": {"market": 5}, "support": {"redstone.market": {"source": "registry", "quote": "x"}}}
    assert engine.readiness(sourced)["investment"]["raw"] == 5.0


# --- thesis gates and the stage window ---------------------------------------------------------------------------

OCEAN = {"sector": "aquaculture", "one_liner": "Seaweed farms for the Baltic", "country": "Finland",
         "claim_ask": "€800k seed"}


def test_a_non_ocean_company_is_out_of_scope_with_the_reason():
    ev = BY_NAME["Rakko Feed"]["evidence"]
    th = engine.theses(ev, company={"sector": "fintech", "one_liner": "Payroll for dentists", "country": "Finland"})
    for t in th.values():
        assert t["fit"] == "out" and t["score"] is None
        assert t["why"].startswith("Out of scope:") and "fintech" in t["why"]
    c = {"theses": th, "flags": [], "pulse": None, "review": {"pending": False, "label": ""}}
    call = service.call(c)
    assert call["label"] == "Out of scope" and call["key"] == "avoid" and "fintech" in call["reasons"][0]


def test_unknown_inputs_pass_the_gates_with_a_note(monkeypatch):
    rubric = engine.load_rubric()
    gates = rubric["theses"]["redstone"]["gates"] | {"countries": ["Nordic"], "ticket_eur": [100_000, 2_000_000]}
    checks = engine.gates(gates, {"sector": "", "one_liner": "", "country": "", "claim_ask": ""})
    assert {g["status"] for g in checks} == {"na"} and all("not applied" in g["note"] for g in checks)


def test_country_and_ticket_gates():
    gates = {"sectors": "*", "countries": ["Nordic"], "ticket_eur": [100_000, 2_000_000]}
    ok = engine.gates(gates, OCEAN)
    assert [g["status"] for g in ok] == ["pass", "pass"]
    far = engine.gates(gates, OCEAN | {"country": "Brazil"})
    assert far[0]["status"] == "fail" and "Brazil" in far[0]["note"]
    big = engine.gates(gates, OCEAN | {"claim_ask": "€3M to launch in 40 countries"})
    assert big[1]["status"] == "fail" and "€3M" in big[1]["note"]
    assert engine.ticket_eur("€800k to double its drying plant") == 800_000
    assert engine.ticket_eur("$5M seed") == 4_500_000 and engine.ticket_eur("no ask") is None


def test_the_accelerator_fits_less_past_its_stage_band():
    base = {"impact": {"problem_pressure": 4, "solution_potential": 4, "measurability": 4},
            "brl": {"market": 4, "value_prop": 4, "business_model": 4, "scalability": 4},
            "redstone": {"team": 4, "product": 4}}
    mid = engine.theses(base | {"trl_stage": "pilot"}, company=OCEAN)["apelago"]         # TRL 6: inside 4-7
    late = engine.theses(base | {"trl_stage": "commercial"}, company=OCEAN)["apelago"]   # TRL 9: past it
    early = engine.theses(base | {"trl_stage": "idea"}, company=OCEAN)["apelago"]        # TRL 1: before it
    assert mid["window"]["value"] == 1.0 and late["window"]["value"] < 1.0 and early["window"]["value"] < 1.0
    assert mid["score"] > late["score"] and mid["score"] > early["score"]
    assert "past the 4–7 band" in late["why"]


# --- the perception gap: crowd, evidence and the outside world on one scale ------------------------------------

def test_divergence_names_the_widest_gap_and_what_it_means():
    d = service.divergence({"crowd": 3.5, "engine": 1.7, "outside": 2.0})
    assert d["diverges"] and d["max_gap"] == 1.8 and (d["high"], d["low"]) == ("crowd", "engine")
    assert d["text"] == "Crowd 3.5 vs evidence 1.7: the pitch outsells the evidence."
    calm = service.divergence({"crowd": 3.0, "engine": 3.2, "outside": None})
    assert not calm["diverges"] and calm["text"] == "Crowd and evidence agree within 0.2. No outside read yet."
    alone = service.divergence({"crowd": None, "engine": 3.0, "outside": None})
    assert alone["max_gap"] is None and "Needs two reads" in alone["text"]


def test_the_outside_read_counts_ai_and_social_once_each():
    tile = lambda group, v: {"group": group, "scores": {a: v for a in engine.AXES}}
    out = service.outside_read([tile("ai", 4), tile("ai", 2), tile("social", 1), tile("people", 5)])
    assert out == {"ai": 3.0, "social": 1.0, "composite": 2.0, "n": 3}
    assert service.outside_read([])["composite"] is None
