"""Money in card text reads in euros, converted with fixed rates and no model call."""
from app import money
from app.db import connect, dumps, j, now


def test_foreign_amounts_read_in_euros():
    assert money.in_euros("Sizable Energy raises $8M for its ocean energy system") == \
        "Sizable Energy raises €7.2M for its ocean energy system"
    assert money.in_euros("SEK 50M from Almi") == "€4.3M from Almi"
    assert money.in_euros("raised 50 MSEK") == "raised €4.3M"
    assert money.in_euros("8 million USD round") == "€7.2M round"
    assert money.in_euros("£250k grant") == "€288k grant"
    assert money.in_euros("US$ 1.5 million seed") == "€1.4M seed"


def test_euros_and_plain_numbers_stay():
    for text in ("€15M from NATO", "10 sensors in 2026", "Series B", "", None):
        assert money.in_euros(text) == text


def test_stored_cards_are_tidied_once(client):
    db = connect()
    cid = db.execute("INSERT INTO companies (name, name_key, one_liner, claim_ask, facts, is_real, created_at) "
                     "VALUES ('Sizable', 'sizable', 'Raises $8M', '$8M Series B', ?, 1, ?)",
                     (dumps([{"label": "Funding round", "value": "$8M (2026)"}]), now())).lastrowid
    db.commit()
    assert money.tidy(db) >= 1
    row = db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
    assert row["claim_ask"] == "€7.2M Series B" and j(row["facts"])[0]["value"] == "€7.2M (2026)"
    assert money.tidy(db) == 0
    db.close()
