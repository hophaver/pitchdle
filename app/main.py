"""Pitchdle: FastAPI app serving the API and the static pages."""
import csv
import io
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager

import segno
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, live, scoring, seed, service
from .db import connect, dumps, get_db, init_db, j, now
from .engine import AXES

log = logging.getLogger("pitchdle")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db = connect()
    init_db(db)
    if seed.seed_if_empty(db):
        log.warning("Pitchdle: empty database, loaded seed data into %s", config.DB_PATH)
    db.close()
    if config.ADMIN_PASSWORD == "admin":
        log.warning("Pitchdle: ADMIN_PASSWORD is the default 'admin'. Set it before exposing this beyond localhost.")
    yield


app = FastAPI(title="Pitchdle", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """No build step means no hashed filenames, so make browsers revalidate JS/CSS on every load."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

# --- auth & identity -------------------------------------------------------------------------------

basic = HTTPBasic(realm="Pitchdle host")


def require_admin(creds: HTTPBasicCredentials = Depends(basic)) -> None:
    if not secrets.compare_digest(creds.password.encode(), config.ADMIN_PASSWORD.encode()):
        raise HTTPException(401, "Wrong password", headers={"WWW-Authenticate": 'Basic realm="Pitchdle host"'})


def get_player(request: Request, response: Response, db=Depends(get_db)):
    """Anonymous device identity from a cookie; created on first contact."""
    token = request.cookies.get("pd_token")
    row = db.execute("SELECT * FROM players WHERE device_token = ?", (token,)).fetchone() if token else None
    if row is None:
        token = uuid.uuid4().hex
        db.execute("INSERT INTO players (device_token, handle, created_at) VALUES (?, ?, ?)",
                   (token, service.new_handle(), now()))
        db.commit()
        row = db.execute("SELECT * FROM players WHERE device_token = ?", (token,)).fetchone()
    response.set_cookie("pd_token", token, max_age=365 * 24 * 3600, samesite="lax", httponly=True)
    return row


def base_url(request: Request) -> str:
    return config.BASE_URL or str(request.base_url).rstrip("/")


# --- pages -----------------------------------------------------------------------------------------

def page(name: str) -> FileResponse:
    return FileResponse(config.STATIC_DIR / name, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/play")


@app.get("/play", include_in_schema=False)
@app.get("/live", include_in_schema=False)
def play_page():
    return page("play.html")


@app.get("/wall", include_in_schema=False)
def wall_page():
    return page("wall.html")


@app.get("/host", include_in_schema=False, dependencies=[Depends(require_admin)])
def host_page():
    return page("host.html")


@app.get("/host/live", include_in_schema=False, dependencies=[Depends(require_admin)])
def host_live_page():
    return page("hostlive.html")


@app.get("/admin", include_in_schema=False, dependencies=[Depends(require_admin)])
def admin_page():
    return page("admin.html")


@app.get("/qr", include_in_schema=False)
def qr(request: Request, path: str = "/live"):
    if not path.startswith("/"):
        path = "/" + path
    out = io.BytesIO()
    segno.make(base_url(request) + path, error="m").save(out, kind="svg", scale=10, border=2,
                                                         dark="#04162b", light="#ffffff")
    return Response(out.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})


# --- player API ------------------------------------------------------------------------------------

@app.get("/api/me")
def me(player=Depends(get_player)):
    """Called first by every player page so the device cookie exists before anything else."""
    return {"ok": True}


def set_response(db, dive, player) -> dict:
    comps = service.dive_companies(db, dive)
    done = service.answered(db, player["id"], dive["id"])
    return {
        "dive": service.dive_payload(dive),
        "cards": [service.public_card(c) for c in comps],
        "answered": [c["id"] for c in comps if c["id"] in done],
    }


@app.get("/api/dive/today")
def dive_today(player=Depends(get_player), db=Depends(get_db)):
    return set_response(db, service.todays_dive(db), player)


@app.get("/api/dive/{dive_id}")
def dive_by_id(dive_id: int, player=Depends(get_player), db=Depends(get_db)):
    dive = service.get_dive(db, dive_id)
    if not dive:
        raise HTTPException(404, "No such set.")
    return set_response(db, dive, player)


class Scores(BaseModel):
    novel: int = Field(ge=0, le=5)
    useful: int = Field(ge=0, le=5)
    plausible: int = Field(ge=0, le=5)
    investable: int = Field(ge=0, le=5)


class VoteIn(BaseModel):
    dive_id: int
    company_id: int
    scores: Scores


@app.post("/api/vote")
def vote(body: VoteIn, player=Depends(get_player), db=Depends(get_db)):
    """One answer per card, final: there's no way to revise it."""
    dive = service.get_dive(db, body.dive_id)
    if not dive or body.company_id not in j(dive["company_ids"], []):
        raise HTTPException(404, "That card isn't in this set.")
    comp = service.get_company(db, body.company_id)
    if not comp:
        raise HTTPException(404, "No such company.")
    if dive["mode"] == "live":
        st = live.get_state(db)
        cur = live.current_company(db, st)
        if st["dive_id"] != dive["id"] or not cur or cur["id"] != comp["id"]:
            raise HTTPException(409, "That's not the live card right now.")
        if st["phase"] != "open":
            raise HTTPException(409, "Voting is closed for this card.")
    if comp["id"] in service.answered(db, player["id"], dive["id"]):
        raise HTTPException(409, "You've already answered this card.")
    s = body.scores
    db.execute(
        "INSERT INTO votes (player_id, dive_id, company_id, round, novel, useful, plausible, investable, created_at) "
        "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)",
        (player["id"], dive["id"], comp["id"], s.novel, s.useful, s.plausible, s.investable, now()))
    db.commit()
    return {"ok": True}


@app.get("/api/dive/{dive_id}/results")
def results(dive_id: int, player=Depends(get_player), db=Depends(get_db)):
    """You vs the crowd, only once every card is answered (or the live set has finished)."""
    dive = service.get_dive(db, dive_id)
    if not dive:
        raise HTTPException(404, "No such set.")
    if dive["mode"] == "live":
        st = live.get_state(db)
        if st["dive_id"] == dive_id and st["phase"] != "final":
            raise HTTPException(403, "Results appear when the live set is over.")
    else:
        total = len(service.dive_companies(db, dive))
        if len(service.answered(db, player["id"], dive_id)) < total:
            raise HTTPException(403, "Answer every card first.")
    return service.results(db, dive, player["id"])


# --- live room -------------------------------------------------------------------------------------

def joined_count(db, since: float = 30) -> int:
    return db.execute("SELECT COUNT(*) FROM players WHERE is_seed = 0 AND last_seen > ?",
                      (time.time() - since,)).fetchone()[0]


def live_base(db, st: dict) -> dict:
    dive = service.get_dive(db, st["dive_id"]) if st["dive_id"] else None
    comp = live.current_company(db, st)
    total = len(service.dive_companies(db, dive)) if dive else 0
    return {
        "phase": st["phase"],
        "dive": service.dive_payload(dive) | {"total": total} if dive else None,
        "card_index": st["card_index"],
        "card": service.public_card(comp) if comp and st["phase"] in ("open", "locked", "revealed") else None,
        "remaining": live.remaining(st),
        "seconds": config.LIVE_SECONDS,
        "joined": joined_count(db),
        "votes": len(service.card_votes(db, dive["id"], comp["id"])) if dive and comp else 0,
        "key": f"{st['phase']}:{st['dive_id']}:{st['card_index']}",
    }


@app.get("/api/live/state")
def live_state(player=Depends(get_player), db=Depends(get_db)):
    db.execute("UPDATE players SET last_seen = ? WHERE id = ?", (time.time(), player["id"]))
    db.commit()
    st = live.get_state(db)
    out = live_base(db, st)
    comp = live.current_company(db, st)
    out["voted"] = bool(comp) and comp["id"] in service.answered(db, player["id"], st["dive_id"])
    return out


def wall_card(db, dive_id: int, comp) -> dict:
    room = scoring.crowd(service.card_votes(db, dive_id, comp["id"]))
    return {
        "card": service.public_card(comp),
        "engine": {"axes": j(comp["engine_axes"]), "composite": comp["engine_composite"]},
        "room": {"n": room["n"], "means": room["means"], "composite": room["composite"],
                 "share": room["share"], "mode": room["mode"]},
        "callout": service.callout(room, comp["engine_composite"]),
        "facts": j(comp["facts"], []),
    }


@app.get("/api/live/wall")
def live_wall(request: Request, db=Depends(get_db)):
    st = live.get_state(db)
    out = live_base(db, st)
    out["join_url"] = base_url(request) + "/live"
    comp = live.current_company(db, st)
    if st["phase"] == "revealed" and comp:
        out["reveal"] = wall_card(db, st["dive_id"], comp)
    if st["phase"] == "final" and st["dive_id"]:
        dive = service.get_dive(db, st["dive_id"])
        out["cards"] = [wall_card(db, dive["id"], c) for c in service.dive_companies(db, dive)]
    return out


class LiveAction(BaseModel):
    action: str
    dive_id: int | None = None


@app.post("/api/host/live", dependencies=[Depends(require_admin)])
def live_action(body: LiveAction, db=Depends(get_db)):
    try:
        st = live.act(db, body.action, body.dive_id)
    except live.LiveError as e:
        raise HTTPException(409, str(e))
    return live_base(db, st)


@app.get("/api/host/live", dependencies=[Depends(require_admin)])
def live_host_state(db=Depends(get_db)):
    return live_base(db, live.get_state(db))


# --- host dashboard --------------------------------------------------------------------------------

@app.get("/api/host/overview", dependencies=[Depends(require_admin)])
def host_overview(real_only: bool = False, db=Depends(get_db)):
    return service.overview(db, real_only)


@app.get("/api/host/dives", dependencies=[Depends(require_admin)])
def host_dives(db=Depends(get_db)):
    rows = db.execute("SELECT * FROM dives ORDER BY id DESC").fetchall()
    counts = {r["dive_id"]: r["n"] for r in db.execute(
        "SELECT dive_id, COUNT(DISTINCT player_id) AS n FROM votes GROUP BY dive_id")}
    return [service.dive_payload(d) | {"company_ids": j(d["company_ids"], []), "players": counts.get(d["id"], 0)}
            for d in rows]


# --- admin -----------------------------------------------------------------------------------------

class Fact(BaseModel):
    label: str
    value: str


class CompanyIn(BaseModel):
    name: str = Field(min_length=1)
    emoji: str = Field("", max_length=16)
    sector: str = ""
    one_liner: str = ""
    claim_ask: str = ""
    website: str = ""
    facts: list[Fact] = []
    evidence: dict = {}
    evidence_note: str = ""
    is_real: bool = False
    active: bool = True


def admin_company(db, row) -> dict:
    out = dict(row)
    for key, default in (("facts", []), ("evidence", {}), ("engine_axes", {}), ("engine_coverage", {}), ("crawl", None)):
        out[key] = j(row[key], default)
    out["opportunities"] = [dict(o) for o in db.execute("SELECT * FROM opportunities WHERE company_id = ? ORDER BY fit DESC",
                                                        (row["id"],))]
    out["votes"] = db.execute("SELECT COUNT(*) FROM votes WHERE company_id = ? AND round = 1", (row["id"],)).fetchone()[0]
    return out


@app.get("/api/admin/companies", dependencies=[Depends(require_admin)])
def admin_companies(db=Depends(get_db)):
    return [admin_company(db, r) for r in db.execute("SELECT * FROM companies ORDER BY name")]


@app.get("/api/admin/factors", dependencies=[Depends(require_admin)])
def admin_factors():
    from .engine import FACTOR_GROUPS, GROUP_LABELS, TRL_STAGES
    return {"groups": FACTOR_GROUPS, "group_labels": GROUP_LABELS, "trl_stages": TRL_STAGES}


def save_company(db, body: CompanyIn, cid: int | None) -> int:
    values = (body.name.strip(), body.emoji.strip(), body.sector, body.one_liner, body.claim_ask, body.website,
              dumps([f.model_dump() for f in body.facts]), dumps(body.evidence), body.evidence_note,
              int(body.is_real), int(body.active))
    if cid is None:
        cid = db.execute(
            "INSERT INTO companies (name, emoji, sector, one_liner, claim_ask, website, facts, evidence, evidence_note, "
            "is_real, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values + (now(),)).lastrowid
    else:
        db.execute("UPDATE companies SET name = ?, emoji = ?, sector = ?, one_liner = ?, claim_ask = ?, website = ?, facts = ?, "
                   "evidence = ?, evidence_note = ?, is_real = ?, active = ? WHERE id = ?", values + (cid,))
    seed.score_company(db, cid)
    db.commit()
    return cid


@app.post("/api/admin/companies", dependencies=[Depends(require_admin)])
def admin_create(body: CompanyIn, db=Depends(get_db)):
    return admin_company(db, service.get_company(db, save_company(db, body, None)))


@app.put("/api/admin/companies/{cid}", dependencies=[Depends(require_admin)])
def admin_update(cid: int, body: CompanyIn, db=Depends(get_db)):
    if not service.get_company(db, cid):
        raise HTTPException(404, "No such company.")
    return admin_company(db, service.get_company(db, save_company(db, body, cid)))


@app.delete("/api/admin/companies/{cid}", dependencies=[Depends(require_admin)])
def admin_delete(cid: int, db=Depends(get_db)):
    db.execute("DELETE FROM companies WHERE id = ?", (cid,))
    db.commit()
    return {"ok": True}


class Opportunity(BaseModel):
    kind: str
    name: str
    why: str = ""
    fit: float = Field(0.5, ge=0, le=1)
    stage_fit: str = ""


@app.put("/api/admin/companies/{cid}/opportunities", dependencies=[Depends(require_admin)])
def admin_opportunities(cid: int, body: list[Opportunity], db=Depends(get_db)):
    if not service.get_company(db, cid):
        raise HTTPException(404, "No such company.")
    db.execute("DELETE FROM opportunities WHERE company_id = ?", (cid,))
    for o in body:
        db.execute("INSERT INTO opportunities (company_id, kind, name, why, fit, stage_fit) VALUES (?, ?, ?, ?, ?, ?)",
                   (cid, o.kind, o.name, o.why, o.fit, o.stage_fit))
    db.commit()
    return admin_company(db, service.get_company(db, cid))


@app.post("/api/admin/companies/{cid}/recrawl", dependencies=[Depends(require_admin)])
def admin_recrawl(cid: int, db=Depends(get_db)):
    from .crawler import run_crawl
    comp = service.get_company(db, cid)
    if not comp:
        raise HTTPException(404, "No such company.")
    result = run_crawl(comp["name"], comp["website"])
    db.execute("UPDATE companies SET crawl = ? WHERE id = ?", (dumps(result), cid))
    db.commit()
    return result


class HideReal(BaseModel):
    hide: bool


@app.post("/api/admin/hide-real", dependencies=[Depends(require_admin)])
def admin_hide_real(body: HideReal, db=Depends(get_db)):
    db.execute("UPDATE companies SET active = ? WHERE is_real = 1", (0 if body.hide else 1,))
    db.commit()
    return {"ok": True}


class DiveIn(BaseModel):
    label: str = Field(min_length=1)
    company_ids: list[int] = Field(min_length=1)
    mode: str = Field("daily", pattern="^(daily|live)$")
    date: str | None = None


@app.post("/api/admin/dives", dependencies=[Depends(require_admin)])
def admin_create_dive(body: DiveIn, db=Depends(get_db)):
    cid = db.execute("INSERT INTO dives (label, date, company_ids, mode, created_at) VALUES (?, ?, ?, ?, ?)",
                     (body.label, body.date, dumps(body.company_ids), body.mode, now())).lastrowid
    db.commit()
    return service.dive_payload(service.get_dive(db, cid))


@app.delete("/api/admin/dives/{dive_id}", dependencies=[Depends(require_admin)])
def admin_delete_dive(dive_id: int, db=Depends(get_db)):
    db.execute("DELETE FROM dives WHERE id = ?", (dive_id,))
    db.execute("UPDATE live_state SET dive_id = NULL, card_index = -1, phase = 'idle' WHERE dive_id = ?", (dive_id,))
    db.commit()
    return {"ok": True}


class ResetIn(BaseModel):
    scope: str = Field(pattern="^(real|seed|all|everything)$")


@app.post("/api/admin/reset", dependencies=[Depends(require_admin)])
def admin_reset(body: ResetIn, db=Depends(get_db)):
    if body.scope == "everything":
        seed.reset(db)
        return {"ok": True}
    if body.scope in ("seed", "all"):
        db.execute("DELETE FROM votes WHERE is_seed = 1")
        db.execute("DELETE FROM players WHERE is_seed = 1")
    if body.scope in ("real", "all"):
        db.execute("DELETE FROM votes WHERE is_seed = 0")
    db.commit()
    return {"ok": True}


class DemoIn(BaseModel):
    dive_id: int
    players: int = Field(30, ge=5, le=200)


@app.post("/api/admin/demo-votes", dependencies=[Depends(require_admin)])
def admin_demo_votes(body: DemoIn, db=Depends(get_db)):
    if not service.get_dive(db, body.dive_id):
        raise HTTPException(404, "No such dive.")
    return {"inserted": seed.demo_votes(db, body.dive_id, body.players, rng_seed=int(time.time()))}


@app.get("/api/admin/export.json", dependencies=[Depends(require_admin)])
def export_json(db=Depends(get_db)):
    data = service.overview(db, real_only=True)
    return Response(dumps(data), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="pitchdle-insights.json"'})


@app.get("/api/admin/export.csv", dependencies=[Depends(require_admin)])
def export_csv(db=Depends(get_db)):
    data = service.overview(db, real_only=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "sector", "votes", *[f"crowd_{a}" for a in AXES], "crowd_composite",
                *[f"engine_{a}" for a in AXES], "engine_composite", "gap", "coverage", "flags",
                "top_action"])
    for c in data["companies"]:
        cm = c["crowd"]["means"] or {}
        w.writerow([c["name"], c["sector"], c["crowd"]["n"], *[cm.get(a, "") for a in AXES], c["crowd"]["composite"] or "",
                    *[c["engine"]["axes"].get(a, "") for a in AXES], c["engine"]["composite"],
                    "" if c["gap"] is None else c["gap"],
                    f"{c['coverage'].get('assessed', '')}/{c['coverage'].get('total', '')}",
                    "; ".join(f["label"] for f in c["flags"]),
                    c["actions"][0]["name"] if c["actions"] else ""])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="pitchdle-insights.csv"'})
