"""The opportunity radar: landscape matching, the call, the dashboard payload, and the Game page's set list."""
from datetime import date, timedelta

import pytest

from app import landscape, service
from app.db import connect, now


def company(sector="", one_liner="", country=""):
    return {"sector": sector, "one_liner": one_liner, "claim_ask": "", "facts": [], "country": country}


# --- landscape -------------------------------------------------------------------------------------

def names(matches, kind=None):
    return [m["name"] for m in matches if kind is None or m["kind"] == kind]


def test_every_landscape_entry_is_well_formed():
    for e in landscape.entries():
        assert e["region"] in ("FI", "Nordic", "EU", "Global") and len(e["trl"]) == 2 and e["what"]
        assert not e["url"] or e["url"].startswith("https://")


def test_sector_specific_entries_only_match_their_sector():
    fish = landscape.match(company("aquaculture", "Feed for salmon farms"), trl=7)
    ships = landscape.match(company("maritime", "Hull sensors for ferries"), trl=7)
    assert "Aqua-Spark" in names(fish) and "Aqua-Spark" not in names(ships)
    assert "Viking Line" in names(ships) and "Viking Line" not in names(fish)


def test_stage_decides_who_fits():
    early = names(landscape.match(company("energy", "A fuel cell for boats"), trl=3, n_per_kind=99))
    late = names(landscape.match(company("energy", "A fuel cell for boats"), trl=8, n_per_kind=99))
    assert "Voima Ventures" in early and "Voima Ventures" not in late  # TRL 3-6
    assert "Wärtsilä" in late and "Wärtsilä" not in early               # TRL 6-9


def test_unknowns_are_neutral_and_reasons_say_why():
    unknown = landscape.match(company("aquaculture", "Feed for salmon farms"), trl=None)
    assert unknown and all(m["fit"] > 0 for m in unknown)
    known = landscape.match(company("aquaculture", "Feed for salmon farms", "Finland"), trl=7)
    ef = next(m for m in known if m["name"] == "Business Finland")
    assert "TRL 7 fits 3–8" in ef["reasons"] and "Finland" in ef["reasons"]


def test_region_keeps_national_programmes_national():
    us = names(landscape.match(company("aquaculture", "Feed for salmon farms", "United States"), trl=7))
    assert "Business Finland" not in us and "Hatch Blue" in us


def test_at_most_three_per_kind():
    m = landscape.match(company("maritime shipping port ferry", "Fuel savings for ferries"), trl=7)
    for kind in landscape.KINDS:
        assert len(names(m, kind)) <= 3


# --- the call --------------------------------------------------------------------------------------

def insight(redstone=None, apelago=None, flags=(), lean=None, pending=False):
    return {"theses": {"redstone": {"label": "Redstone investment", "score": redstone},
                       "apelago": {"label": "A'Pelago accelerator", "score": apelago}},
            "flags": [{"key": k, "detail": "x"} for k in flags], "pulse": {"lean": lean} if lean else None,
            "review": {"pending": pending, "label": "Awaiting host evidence review"}}


@pytest.mark.parametrize("kw, key", [
    ({}, "evidence"), ({"redstone": 4.0}, "back"), ({"redstone": 3.0}, "watch"), ({"apelago": 2.0}, "avoid"),
    ({"redstone": 4.0, "flags": ["story"]}, "watch"), ({"redstone": 4.0, "lean": "negative"}, "watch"),
    ({"redstone": 4.0, "pending": True}, "watch"), ({"redstone": 2.0, "apelago": 3.9}, "back"),
])
def test_call(kw, key):
    assert service.call(insight(**kw))["key"] == key


def test_no_evidence_never_gets_a_score():
    c = service.call(insight(pending=True))
    assert c["label"] == "Needs evidence" and c["reasons"] == ["Awaiting host evidence review"]


# --- the dashboard ---------------------------------------------------------------------------------

def test_radar_ranks_next_steps_and_names_the_move(client, admin):
    data = client.get("/api/host/radar", auth=admin).json()
    rakko = next(c for c in data["companies"] if c["name"] == "Rakko Feed")
    assert rakko["call"]["key"] == "back" and data["candidates"] == []
    kinds = {a["kind"] for a in rakko["actions"]}
    assert {"investor", "grant", "partner", "client"} <= kinds
    assert any(a["source"] == "landscape" for a in rakko["actions"]) and any(a["source"] == "manual" for a in rakko["actions"])
    assert rakko["next"]["text"] and rakko["next"]["with"]


def test_radar_in_live_mode_shows_only_real_startups_and_candidates(client, admin):
    db = connect()
    db.execute("INSERT INTO companies (name, name_key, is_real, active, created_at) VALUES ('Realwave', 'realwave', 1, 0, ?)", (now(),))
    db.execute("INSERT INTO candidates (name, name_key, status) VALUES ('Kelpo', 'kelpo', 'new')")
    db.execute("INSERT INTO candidates (name, name_key, status) VALUES ('Gone', 'gone', 'dismissed')")
    db.commit()
    db.close()
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    data = client.get("/api/host/radar", auth=admin).json()
    assert [c["name"] for c in data["companies"]] == ["Realwave"]
    assert data["companies"][0]["call"]["key"] == "evidence" and data["companies"][0]["next"] is None
    assert [c["name"] for c in data["candidates"]] == ["Kelpo"]


def test_an_unknown_level_is_the_gap_before_raising():
    lv = lambda k, score: {"key": k, "label": k, "score": score}
    c = {"readiness": {"ocean_impact": lv("ocean_impact", None), "business": lv("business", None),
                       "tech": lv("tech", 4.4), "investment": lv("investment", None)},
         "actions": [{"kind": "client", "name": "Port of Turku", "url": ""}, {"kind": "investor", "name": "FiBAN", "url": ""}]}
    move = service.next_move(c)
    assert move["gap"] == "business" and move["gap_score"] is None and move["with"] == "Port of Turku"
    for k in ("ocean_impact", "business", "investment"):
        c["readiness"][k]["score"] = 4.0
    assert service.next_move(c)["text"] == "Raise the next round" and service.next_move(c)["with"] == "FiBAN"


def test_approving_a_placed_candidate_records_its_country(client, admin):
    db = connect()
    db.execute("INSERT INTO candidates (name, name_key, status, source, snippet, screen) VALUES "
               "('Kelpo', 'kelpo', 'new', 'news.google', 'Kelpo raises', '{\"verdict\": \"kept\", \"based_in\": \"Finland\"}')")
    cid = db.execute("SELECT id FROM candidates").fetchone()[0]
    db.commit()
    db.close()
    assert client.post(f"/api/admin/discover/{cid}/approve", auth=admin).json()["country"] == "Finland"


# --- game page -------------------------------------------------------------------------------------

def test_sets_are_marked_past_today_or_upcoming(client, admin):
    ids = [c["id"] for c in client.get("/api/admin/companies?pool=current", auth=admin).json()[:2]]
    soon = (date.today() + timedelta(days=2)).isoformat()
    client.post("/api/admin/dives", json={"label": "Soon", "company_ids": ids, "date": soon}, auth=admin)
    when = {d["label"]: d["when"] for d in client.get("/api/host/dives", auth=admin).json()}
    assert when == {"Soon": "upcoming", "JunctionX final": "upcoming", "#3": "today", "#2": "past", "#1": "past"}


def test_a_set_shows_crowd_next_to_engine(client, admin):
    final = next(d for d in client.get("/api/host/dives", auth=admin).json() if d["label"] == "JunctionX final")
    client.post("/api/admin/demo-votes", json={"dive_id": final["id"], "players": 10}, auth=admin)
    detail = client.get(f"/api/host/dives/{final['id']}", auth=admin).json()
    assert len(detail["cards"]) == 5 and all(c["crowd"]["n"] == 10 and c["engine"] is not None for c in detail["cards"])
    assert client.get("/api/host/dives", auth=admin).json()[0]["answers"] >= 0


def test_the_live_room_is_gone(client, admin):
    for path in ("/live", "/wall", "/host/live", "/qr", "/api/live/state", "/api/live/wall"):
        assert client.get(path, auth=admin).status_code == 404, path
    assert client.post("/api/admin/dives", json={"label": "x", "company_ids": [1], "mode": "live"}, auth=admin).status_code == 422
    assert client.get("/game", auth=admin).status_code == 200
