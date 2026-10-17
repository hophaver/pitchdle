"""Pitchdle: FastAPI app serving the API and the static pages."""
import csv
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import date

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from . import accounts, autofill, autoread, brief, config, engine, moderation, money, opinions, reads, refresh, scoring, seed, service
from .db import connect, dumps, get_db, init_db, j, name_key, now
from .crawler import checklist, pitch
from .engine import AXES, full_score as engine_full

log = logging.getLogger("pitchdle")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db = connect()
    init_db(db)
    if seed.seed_if_empty(db):
        log.warning("Pitchdle: empty database, loaded seed data into %s", config.DB_PATH)
    seed.fill_profiles(db)  # sample companies from before card profiles get theirs
    accounts.ensure_test_accounts(db)
    moderation.load_weights(db)  # the admin's vote weights over the .env defaults
    money.tidy(db)  # amounts on stored cards in euros (no model call)
    fixed = autofill.tidy(db)
    if fixed["removed"]:
        log.warning("Pitchdle: removed excluded names discovery had filed as startups: %s", ", ".join(fixed["removed"]))
    autofill.maybe_start(db)  # live mode tops itself up in the background; demo mode does nothing
    autoread.kick()  # cards still missing AI ratings or a social media read get them, in the background
    db.close()
    if config.ADMIN_PASSWORD == "admin":
        log.warning("Pitchdle: ADMIN_PASSWORD is the default 'admin'. Set it before exposing this beyond localhost.")
    if config.TEST_MODERATOR_USERNAME and config.TEST_MODERATOR_PASSWORD:
        log.warning("Pitchdle: test moderator '%s' is set up from .env. Before exposing this beyond localhost, unset "
                    "TEST_MODERATOR_* and delete the account on /moderate.", config.TEST_MODERATOR_USERNAME)
    yield


app = FastAPI(title="Startup game", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """No build step means no hashed filenames, so make browsers revalidate JS/CSS on every load."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

# --- auth & identity -------------------------------------------------------------------------------

basic = HTTPBasic(realm="Host", auto_error=False)

SESSION_COOKIE = "pd_session"
DEVICE_COOKIE = "pd_token"
YEAR = 365 * 24 * 3600


def current_user(request: Request, db=Depends(get_db)):
    return accounts.user_for_session(db, request.cookies.get(SESSION_COOKIE))


# Signed in with the admin password on the sign-in page: a cookie derived from the password, so changing
# ADMIN_PASSWORD signs everyone out.
ADMIN_COOKIE = "pd_admin"


def is_admin_password(password: str) -> bool:
    return secrets.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode())


def admin_token() -> str:
    return hmac.new(config.ADMIN_PASSWORD.encode(), b"pitchdle admin session", hashlib.sha256).hexdigest()


def staff_for(request: Request, creds: HTTPBasicCredentials | None, user, db) -> moderation.Staff | None:
    """Who's acting, if they're staff: the admin password (the sign-in page's cookie, or Basic auth for scripts),
    or a moderator's or admin's own account (logged in, or Basic auth). None for everyone else."""
    if secrets.compare_digest(request.cookies.get(ADMIN_COOKIE, "").encode(), admin_token().encode()):
        return moderation.Staff("admin", admin=True)
    if creds and is_admin_password(creds.password):
        return moderation.Staff("admin", admin=True)
    if not (user and (user["is_moderator"] or user["is_admin"])) and creds:
        user = accounts.staff_login(db, creds.username, creds.password)
    if user and (user["is_moderator"] or user["is_admin"]):
        return moderation.Staff(user["username"], admin=bool(user["is_admin"]))
    return None


def optional_staff(request: Request, creds: HTTPBasicCredentials | None = Depends(basic), user=Depends(current_user),
                   db=Depends(get_db)) -> moderation.Staff | None:
    return staff_for(request, creds, user, db)


def require_admin(staff: moderation.Staff | None = Depends(optional_staff)) -> None:
    """The admin password, or an admin account."""
    if not (staff and staff.admin):
        raise HTTPException(401, "Sign in with an admin account or the admin password.")


def require_moderator(staff: moderation.Staff | None = Depends(optional_staff)) -> moderation.Staff:
    """The admin password, or a moderator's or admin's own account. Returns who's acting, which goes on each
    review."""
    if not staff:
        raise HTTPException(401, "Sign in with a moderator or admin account, or the admin password.")
    return staff


def get_player(request: Request, response: Response, db=Depends(get_db), user=Depends(current_user)):
    """The signed-in player's own row, or else an anonymous guest identity per device, created on first contact."""
    if user:
        return accounts.player_for(db, user)
    token = request.cookies.get(DEVICE_COOKIE)
    row = db.execute("SELECT * FROM players WHERE device_token = ?", (token,)).fetchone() if token else None
    if row is None:
        token = uuid.uuid4().hex
        db.execute("INSERT INTO players (device_token, handle, created_at) VALUES (?, ?, ?)",
                   (token, service.new_handle(), now()))
        db.commit()
        row = db.execute("SELECT * FROM players WHERE device_token = ?", (token,)).fetchone()
    response.set_cookie(DEVICE_COOKIE, token, max_age=YEAR, samesite="lax", httponly=True)
    return row


def is_guest(player) -> bool:
    return player["user_id"] is None


# --- pages -----------------------------------------------------------------------------------------

def page(name: str) -> FileResponse:
    return FileResponse(config.STATIC_DIR / name, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/play")


@app.get("/play", include_in_schema=False)
def play_page():
    return page("play.html")


def staff_page(name: str, staff: moderation.Staff | None, admin: bool) -> FileResponse:
    """The page, or the sign-in page in its place (same URL, so signing in just reloads it)."""
    if staff and (staff.admin or not admin):
        return page(name)
    response = page("login.html")
    response.status_code = 401
    return response


@app.get("/host", include_in_schema=False)
def host_page(staff=Depends(optional_staff)):
    return staff_page("host.html", staff, admin=True)


@app.get("/game", include_in_schema=False)
def game_page(staff=Depends(optional_staff)):
    return staff_page("game.html", staff, admin=True)


@app.get("/admin", include_in_schema=False)
def admin_page(staff=Depends(optional_staff)):
    return staff_page("admin.html", staff, admin=True)


@app.get("/moderate", include_in_schema=False)
def moderate_page(staff=Depends(optional_staff)):
    return staff_page("moderate.html", staff, admin=False)


# Review: A'Pelago's own read of each startup, on the moderation page's code.
@app.get("/review", include_in_schema=False)
def review_page(staff=Depends(optional_staff)):
    return staff_page("moderate.html", staff, admin=False)


# --- player API ------------------------------------------------------------------------------------

@app.get("/api/me")
def me(player=Depends(get_player), user=Depends(current_user)):
    """Called first by every player page so the device cookie exists before anything else."""
    return {"ok": True, "user": accounts.public_user(user) if user else None}


# --- text from players ----------------------------------------------------------------------------

def clean_text(value: str) -> str:
    """One line of plain text: no control characters, single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", value)).strip()


def clean_paragraph(value: str) -> str:
    """Plain text that keeps its line breaks, with at most one blank line in a row."""
    lines = [clean_text(line) for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def web_link(value: str, label: str = "link") -> str:
    """A plain http(s) address, with https:// added when it's left off."""
    value = value.strip()
    if value and "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    host = parts.hostname or ""
    if (len(value) > 200 or parts.scheme not in ("http", "https") or "." not in host
            or parts.username or parts.password or re.search(r"\s", value)):
        raise ValueError(f"{label} must be a web address like https://example.com")
    return value


# --- accounts --------------------------------------------------------------------------------------
# Everyone starts as a guest. A player signs up with a username and password and is logged in at once. An
# investor gives the full profile below and waits for a moderator on /moderate. Either way, the first login moves
# the guest's answers onto the account.

class Credentials(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


# What a sign-up tells the moderators. Mirrored by SIGNUP_SECTIONS in play.js, and ROLES by PD.ROLES.
SIGNUP_TEXT = {  # field: (name in messages, min, max)
    "full_name": ("name", 2, 80), "organisation": ("organisation", 0, 80), "location": ("location", 0, 80),
    "expertise": ("what you know well", 0, 160), "motivation": ("why you want to join", 20, 600),
}
ROLES = ("founder", "investor", "industry", "research", "engineer", "public", "student", "other")
# Profile links, and the site each one has to be on (None: anywhere). At least one is needed.
LINKS = {"linkedin": "linkedin.com", "github": "github.com", "portfolio": None, "cv": None, "other": None}
LINK_NAMES = {"linkedin": "LinkedIn", "github": "GitHub", "cv": "CV"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_PENDING_SIGNUPS = 500


class PlayerSignUp(Credentials):
    kind: str = Field("player", pattern="^player$")


class SignUp(Credentials):
    """An investor's sign-up."""
    kind: str = Field("investor", pattern="^investor$")
    full_name: str
    email: str
    role: str
    organisation: str = ""
    location: str = ""
    expertise: str = ""
    motivation: str
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    cv: str = ""
    other: str = ""

    @field_validator(*SIGNUP_TEXT)
    @classmethod
    def plain_text(cls, value: str, info) -> str:
        value = clean_paragraph(value) if info.field_name == "motivation" else clean_text(value)
        label, lo, hi = SIGNUP_TEXT[info.field_name]
        if not lo <= len(value) <= hi:
            raise ValueError(f"{label} must be {lo}-{hi} characters" if lo else f"{label} must be at most {hi} characters")
        return value

    @field_validator("email")
    @classmethod
    def email_shape(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 120 or not EMAIL_RE.match(value):
            raise ValueError("email must look like name@example.com")
        return value

    @field_validator("role")
    @classmethod
    def known_role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError("pick what you do from the list")
        return value

    @field_validator(*LINKS)
    @classmethod
    def profile_link(cls, value: str, info) -> str:
        if not value.strip():
            return ""
        name = LINK_NAMES.get(info.field_name, info.field_name)
        value = web_link(value, f"{name} link")
        site, host = LINKS[info.field_name], urlsplit(value).hostname
        if site and host != site and not host.endswith("." + site):
            raise ValueError(f"{name} link must be on {site}")
        return value

    @model_validator(mode="after")
    def has_a_link(self):
        if not any(getattr(self, key) for key in LINKS):
            raise ValueError("add at least one link so a moderator can see who you are")
        return self

    def profile(self) -> dict:
        """What moderators see: everything but the credentials, with only the links that were given."""
        out = self.model_dump(exclude={"username", "password", "kind", *LINKS})
        return out | {"links": {key: getattr(self, key) for key in LINKS if getattr(self, key)}}


def sign_in(request: Request, response: Response, db, user) -> dict:
    moved = accounts.claim_guest(db, user, request.cookies.get(DEVICE_COOKIE))
    response.set_cookie(SESSION_COOKIE, accounts.start_session(db, user), max_age=YEAR, samesite="lax", httponly=True)
    return {"user": accounts.public_user(user), "claimed": moved}


@app.post("/api/account/register")
def register(request: Request, response: Response, payload: dict = Body(...), db=Depends(get_db)):
    """A player is in at once and logged in. An investor's sign-up waits for a moderator and doesn't log in: until
    it's approved, they play on as a guest."""
    investor = payload.get("kind") == "investor"
    try:
        body = (SignUp if investor else PlayerSignUp).model_validate(payload)
    except ValidationError as e:
        raise RequestValidationError(e.errors(include_url=False, include_context=False))
    if not investor:
        try:
            user = accounts.register(db, body.username, body.password, status="approved")
        except accounts.AccountError as e:
            raise HTTPException(400, str(e))
        return {"status": "approved"} | sign_in(request, response, db, user)
    if db.execute("SELECT COUNT(*) FROM users WHERE status = 'pending'").fetchone()[0] >= MAX_PENDING_SIGNUPS:
        raise HTTPException(503, "Sign-ups are paused while the moderators catch up. Try again later.")
    try:
        accounts.register(db, body.username, body.password, body.profile(), kind="investor")
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    return {"status": "pending"}


@app.post("/api/account/login")
def login(body: Credentials, request: Request, response: Response, db=Depends(get_db)):
    try:
        user = accounts.authenticate(db, body.username, body.password)
    except accounts.NotApproved as e:
        raise HTTPException(403, str(e))
    except accounts.AccountError as e:
        raise HTTPException(401, str(e))
    return sign_in(request, response, db, user)


class StaffCredentials(BaseModel):
    username: str = Field("", max_length=40)
    password: str = Field(max_length=200)
    need: str = Field("admin", pattern="^(admin|moderator)$")  # what the page being opened needs


@app.post("/api/staff/login")
def staff_login(body: StaffCredentials, request: Request, response: Response, db=Depends(get_db)):
    """The sign-in page for the host and moderation pages: a staff account signs in as itself (the same login as on
    /play), the admin password with any or no username."""
    user = None
    if body.username.strip():
        try:
            user = accounts.authenticate(db, body.username, body.password)
        except accounts.NotApproved as e:
            raise HTTPException(403, str(e))
        except accounts.AccountError:
            pass
    if user:
        if not (user["is_admin"] or (body.need == "moderator" and user["is_moderator"])):
            raise HTTPException(403, "This page needs an admin account." if body.need == "admin"
                                else "This page needs a moderator or admin account.")
        return sign_in(request, response, db, user)
    if is_admin_password(body.password):
        response.set_cookie(ADMIN_COOKIE, admin_token(), max_age=30 * 24 * 3600, samesite="lax", httponly=True)
        return {"user": None, "admin": True}
    raise HTTPException(401, "Wrong username or password.")


@app.post("/api/staff/logout")
def staff_logout(request: Request, response: Response, db=Depends(get_db)):
    """Signs out of the host pages: the admin password's cookie and any account login."""
    accounts.end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(ADMIN_COOKIE)
    return {"ok": True}


@app.post("/api/account/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    accounts.end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.delete("/api/account")
def delete_account(response: Response, user=Depends(current_user), db=Depends(get_db)):
    if not user:
        raise HTTPException(401, "You're not logged in.")
    accounts.delete_user(db, user["id"])
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.post("/api/account/reset")
def reset_account(user=Depends(current_user), db=Depends(get_db)):
    """Test account only: forget every answer so the game can be played through again."""
    if not user or not accounts.is_test(user):
        raise HTTPException(403, "Only the test account can reset its data.")
    return {"removed": accounts.reset_player_data(db, user["id"])}


@app.get("/api/account/history")
def account_history(player=Depends(get_player), db=Depends(get_db)):
    if is_guest(player):
        raise HTTPException(401, "Log in to see your history.")
    return service.history(db, player["id"])


def is_investor(user) -> bool:
    return bool(user) and user["kind"] == "investor"


def set_response(db, dive, player, user) -> dict:
    """Investors rate the full card (profile and outside opinions); players and guests the pitch alone."""
    comps = service.dive_companies(db, dive)
    done = service.answered(db, player["id"], dive["id"])
    card = service.play_card if is_investor(user) else lambda _db, c: service.public_card(c)
    return {
        "dive": service.dive_payload(dive),
        "cards": [card(db, c) for c in comps],
        "answered": [c["id"] for c in comps if c["id"] in done],
        "notice": None if comps else service.pool_notice(db, dive["pool"]),
    }


@app.get("/api/dive/today")
def dive_today(player=Depends(get_player), user=Depends(current_user), db=Depends(get_db)):
    return set_response(db, service.todays_dive(db), player, user)


@app.get("/api/dive/{dive_id}")
def dive_by_id(dive_id: int, player=Depends(get_player), user=Depends(current_user), db=Depends(get_db)):
    dive = service.get_dive(db, dive_id)
    if not dive or not service.in_mode(db, dive):
        raise HTTPException(404, "No such set.")
    if is_guest(player) and service.guest_locked(db, dive, player["id"]):
        raise HTTPException(401, "Log in to play earlier sets.")
    return set_response(db, dive, player, user)


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
    if not dive or not service.in_mode(db, dive) or body.company_id not in j(dive["company_ids"], []):
        raise HTTPException(404, "That card isn't in this set.")
    comp = service.get_company(db, body.company_id)
    if not comp:
        raise HTTPException(404, "No such company.")
    if is_guest(player) and service.needs_account(dive):
        raise HTTPException(401, "Log in to play earlier sets.")
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
    """You vs the crowd, only once every card is answered."""
    dive = service.get_dive(db, dive_id)
    if not dive:
        raise HTTPException(404, "No such set.")
    total = len(service.dive_companies(db, dive))
    if len(service.answered(db, player["id"], dive_id)) < total:
        raise HTTPException(403, "Answer every card first.")
    return service.results(db, dive, player["id"])


# --- startup submissions --------------------------------------------------------------------------
# Anyone can suggest a startup; it waits in /admin until the host approves it. Limits match what fits
# on a card (the seed pitches run 50-75 characters) and are mirrored as maxlength in play.js.

SUBMIT_LIMITS = {"name": (2, 30), "sector": (2, 24), "one_liner": (20, 90), "claim_ask": (10, 60)}
MAX_PENDING_PER_DEVICE = 3
MAX_PENDING_TOTAL = 200


class SubmissionIn(BaseModel):
    name: str
    sector: str
    one_liner: str
    claim_ask: str
    website: str

    @field_validator("name", "sector", "one_liner", "claim_ask")
    @classmethod
    def fits_on_a_card(cls, value: str, info) -> str:
        value = clean_text(value)
        lo, hi = SUBMIT_LIMITS[info.field_name]
        label = info.field_name.replace("_", " ")
        if not lo <= len(value) <= hi:
            raise ValueError(f"{label} must be {lo}-{hi} characters")
        if re.search(r"https?://|www\.", value, re.I):
            raise ValueError(f"put links in the link field, not the {label}")
        return value

    @field_validator("website")
    @classmethod
    def plain_web_link(cls, value: str) -> str:
        return web_link(value)


@app.post("/api/submit")
def submit_startup(body: SubmissionIn, player=Depends(get_player), db=Depends(get_db)):
    mine = db.execute("SELECT COUNT(*) FROM submissions WHERE player_id = ?", (player["id"],)).fetchone()[0]
    if mine >= MAX_PENDING_PER_DEVICE:
        raise HTTPException(429, "You've already sent a few. We'll look at those first.")
    if db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] >= MAX_PENDING_TOTAL:
        raise HTTPException(503, "The review queue is full right now. Try again later.")
    db.execute("INSERT INTO submissions (player_id, name, sector, one_liner, claim_ask, website, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)",
               (player["id"], body.name, body.sector, body.one_liner, body.claim_ask, body.website, now()))
    db.commit()
    return {"ok": True}


# --- host dashboard --------------------------------------------------------------------------------

@app.get("/api/host/overview", dependencies=[Depends(require_admin)])
def host_overview(real_only: bool = False, db=Depends(get_db)):
    return service.overview(db, real_only)


@app.get("/api/host/radar", dependencies=[Depends(require_admin)])
def host_radar(real_only: bool = False, db=Depends(get_db)):
    """The dashboard: the current pool's companies with their call, readiness, thesis fit and ranked next steps,
    plus (live mode only, as they're real startups) the open discovery candidates not yet tracked."""
    out = service.overview(db, real_only)
    out["candidates"] = [candidate_out(r) for r in db.execute(
        "SELECT * FROM candidates WHERE status IN ('new', 'queued') ORDER BY id DESC")] if out["mode"] == "live" else []
    # Startups players suggested, shown beside discovery's finds (real startups, so live mode only).
    out["submissions"] = [dict(r) for r in db.execute(
        "SELECT id, name, sector, one_liner, claim_ask, website, created_at FROM submissions ORDER BY id DESC")] \
        if out["mode"] == "live" else []
    # Whether cards are being filled and read in the background, and with what, so an open card can update and
    # its review buttons know which models are set up.
    out["reads"] = {"auto": autoread.status(db), "ready": reads.setup(), "models": reads.models(),
                    "fill": pitch.available(), "fill_model": config.OPENROUTER_MODEL}
    out["refresh"] = refresh.status(db)
    return out


@app.get("/api/host/dives", dependencies=[Depends(require_admin)])
def host_dives(db=Depends(get_db)):
    """The current mode's sets, newest first, each marked past, today or upcoming (future or undated).
    Sets left over from the removed live room are not listed."""
    rows = db.execute("SELECT * FROM dives WHERE pool = ? AND mode = 'daily' ORDER BY id DESC",
                      (service.get_mode(db),)).fetchall()
    counts = {r["dive_id"]: (r["n"], r["answers"]) for r in db.execute(
        "SELECT dive_id, COUNT(DISTINCT player_id) AS n, COUNT(*) AS answers FROM votes GROUP BY dive_id")}
    today = date.today().isoformat()
    when = lambda d: "past" if d["date"] and d["date"] < today else "today" if d["date"] == today else "upcoming"
    return [service.dive_payload(d) | {"company_ids": j(d["company_ids"], []), "players": counts.get(d["id"], (0, 0))[0],
                                       "answers": counts.get(d["id"], (0, 0))[1], "when": when(d)} for d in rows]


@app.get("/api/host/game-pool", dependencies=[Depends(require_admin)])
def host_game_pool(db=Depends(get_db)):
    """Which in-game startups a new set can still use (live ones play one day only), and which of those a major
    update brought back."""
    pool = service.get_mode(db)
    ids = service.eligible_ids(db, pool)
    back = [r["id"] for r in db.execute(
        "SELECT id FROM companies WHERE major_update_at IS NOT NULL AND id IN (SELECT value FROM dives, json_each(dives.company_ids) WHERE pool = ?)",
        (pool,)) if r["id"] in ids]
    return {"mode": pool, "eligible": ids, "updated": back, "repeats": pool == "demo"}


@app.get("/api/host/dives/{dive_id}", dependencies=[Depends(require_admin)])
def host_dive(dive_id: int, db=Depends(get_db)):
    """One set's cards with the crowd read next to the engine's, for the Game page."""
    dive = service.get_dive(db, dive_id)
    if not dive or not service.in_mode(db, dive):
        raise HTTPException(404, "No such set.")
    cards = []
    for comp in service.dive_companies(db, dive):
        room = scoring.crowd(service.card_votes(db, dive_id, comp["id"]))
        cards.append({"id": comp["id"], "name": comp["name"], "sector": comp["sector"], "website": comp["website"] or "",
                      "crowd": {"n": room["n"], "composite": room["composite"]}, "engine": comp["engine_composite"]})
    return service.dive_payload(dive) | {"cards": cards}


# --- moderation ------------------------------------------------------------------------------------
# Sign-ups wait on /moderate until a moderator lets them in.



def mod_user(db, uid: int):
    user = moderation.get_user(db, uid)
    if not user:
        raise HTTPException(404, "No such user.")
    return user


@contextmanager
def refusals():
    """A moderation action's refusals as HTTP errors: admins only (403), or not possible as things stand (409)."""
    try:
        yield
    except moderation.NotAllowed as e:
        raise HTTPException(403, str(e))
    except moderation.ModerationError as e:
        raise HTTPException(409, str(e))


@app.get("/api/mod/users")
def mod_users(staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    return moderation.overview(db) | {"viewer": {"name": staff.name, "admin": staff.admin}}


class ReviewIn(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")


@app.post("/api/mod/users/{uid}/review")
def mod_review(uid: int, body: ReviewIn, staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    with refusals():
        moderation.review(db, mod_user(db, uid), body.status, staff)
    return moderation.member(db, uid)


class ModeratorIn(BaseModel):
    moderator: bool


@app.put("/api/mod/users/{uid}/moderator")
def mod_moderator(uid: int, body: ModeratorIn, staff: moderation.Staff = Depends(require_moderator),
                  db=Depends(get_db)):
    with refusals():
        moderation.set_moderator(db, mod_user(db, uid), body.moderator, staff)
    return moderation.member(db, uid)


class AdminIn(BaseModel):
    admin: bool


@app.put("/api/mod/users/{uid}/admin")
def mod_admin(uid: int, body: AdminIn, staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    with refusals():
        moderation.set_admin(db, mod_user(db, uid), body.admin, staff)
    return moderation.member(db, uid)


class PasswordIn(BaseModel):
    password: str


@app.put("/api/mod/users/{uid}/password")
def mod_password(uid: int, body: PasswordIn, staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    with refusals():
        moderation.check_manageable(mod_user(db, uid), staff)
    try:
        accounts.set_password(db, uid, body.password)
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/mod/users/{uid}")
def mod_delete_user(uid: int, staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    with refusals():
        moderation.check_manageable(mod_user(db, uid), staff)
    accounts.delete_user(db, uid)
    return {"ok": True}


# A'Pelago's own opinion: moderators and admins evaluate as A'Pelago representatives, not as players. Each keeps
# one evaluation per startup and can change it; the card shows the average of all of them.

def evaluation_card(db, comp, staff: moderation.Staff) -> dict:
    mine = db.execute("SELECT * FROM opinions WHERE company_id = ? AND source = ? AND author = ?",
                      (comp["id"], opinions.APELAGO, staff.name)).fetchone()
    return service.public_card(comp) | {
        "active": bool(comp["active"]),
        "mine": {"scores": opinions.scores_of(mine), "note": mine["note"], "updated_at": mine["updated_at"]} if mine else None,
        # The team's average shows once you've given your own, so it can't steer yours.
        "apelago": opinions.apelago(db, comp["id"]) if mine else None,
    }


def evaluated_company(db, cid: int):
    comp = service.get_company(db, cid)
    if not comp:
        raise HTTPException(404, "No such company.")
    return comp


class WeightsIn(BaseModel):
    player: float = Field(ge=0, le=10)
    investor: float = Field(ge=0, le=10)
    guest: float = Field(ge=0, le=10)
    guest_max_share: float = Field(ge=0, le=0.95)


@app.put("/api/mod/weights")
def mod_weights(body: WeightsIn, staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    """How much each kind of answer counts in crowd scores. Admin only; scores use the new weights at once."""
    if not staff.admin:
        raise HTTPException(403, "Only the admin can change the weights.")
    return moderation.save_weights(db, body.model_dump())


@app.get("/api/mod/evaluations")
def mod_evaluations(staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    """The current mode's startups (sample ones in demo, real ones in live), those in the game first."""
    mode = service.get_mode(db)
    comps = db.execute("SELECT * FROM companies WHERE is_real = ? ORDER BY active DESC, name",
                       (service.pool_is_real(mode),)).fetchall()
    return {"mode": mode, "companies": [evaluation_card(db, c, staff) for c in comps]}


class EvaluationIn(BaseModel):
    scores: Scores
    note: str = Field("", max_length=600)  # stays with the staff; players only see the scores


@app.put("/api/mod/evaluations/{cid}")
def mod_evaluate(cid: int, body: EvaluationIn, staff: moderation.Staff = Depends(require_moderator),
                 db=Depends(get_db)):
    comp = evaluated_company(db, cid)
    opinions.save(db, cid, opinions.APELAGO, body.scores.model_dump(), clean_paragraph(body.note), author=staff.name)
    return evaluation_card(db, comp, staff)


@app.delete("/api/mod/evaluations/{cid}")
def mod_withdraw_evaluation(cid: int, staff: moderation.Staff = Depends(require_moderator), db=Depends(get_db)):
    comp = evaluated_company(db, cid)
    opinions.remove(db, cid, opinions.APELAGO, staff.name)
    return evaluation_card(db, comp, staff)


# --- admin -----------------------------------------------------------------------------------------

class Fact(BaseModel):
    label: str
    value: str


class Investor(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    status: str = Field("invested", pattern="^(invested|interested)$")
    amount_eur: int | None = Field(None, ge=0)  # what an investor has put in; none for the interested

    @field_validator("name")
    @classmethod
    def one_line(cls, value: str) -> str:
        if not clean_text(value):
            raise ValueError("an investor needs a name")
        return clean_text(value)


VISION_WORDS = 400


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
    # Which pool a new company joins: real (live mode) or sample (demo mode). Left out, it's the current mode's.
    # Fixed once created: an update never moves a company between pools.
    is_real: bool | None = None
    active: bool = True
    # Sent by the editor's "Save and score": the host has reviewed the evidence and the card. Quick toggles
    # (Active) leave them out, so ticking a box never passes an auto-estimate or an unchecked card off as checked.
    evidence_reviewed: bool = False
    card_reviewed: bool = False
    # The profile on the card: the vision behind "Read more", the stages passed, money raised and investors.
    vision: str = Field("", max_length=4000)
    stages: list[str] = Field([], max_length=12)
    raised_eur: int | None = Field(None, ge=0)
    investors: list[Investor] = Field([], max_length=30)

    @field_validator("vision")
    @classmethod
    def vision_fits(cls, value: str) -> str:
        value = clean_paragraph(value)
        if len(value.split()) > VISION_WORDS:
            raise ValueError(f"the vision must be {VISION_WORDS} words or fewer")
        return value

    @field_validator("stages")
    @classmethod
    def stage_names(cls, value: list[str]) -> list[str]:
        return [stage for stage in (clean_text(v)[:60] for v in value) if stage]


def admin_company(db, row) -> dict:
    out = dict(row)
    for key, default in (("facts", []), ("evidence", {}), ("engine_axes", {}), ("engine_coverage", {}), ("crawl", None),
                         ("pulse", None), ("stages", []), ("investors", [])):
        out[key] = j(row[key], default)
    out["vision"] = row["vision"] or ""
    out["opportunities"] = [dict(o) for o in db.execute("SELECT * FROM opportunities WHERE company_id = ? ORDER BY fit DESC",
                                                        (row["id"],))]
    out["votes"] = db.execute("SELECT COUNT(*) FROM votes WHERE company_id = ? AND round = 1", (row["id"],)).fetchone()[0]
    out["theses"] = {k: {"label": t["label"], "score": t["score"]}
                     for k, t in engine_full(out["evidence"], company=out)["theses"].items()}
    out["opinions"] = opinions.outside(db, row["id"])
    out["apelago"] = opinions.apelago(db, row["id"])
    return out


@app.get("/api/admin/companies", dependencies=[Depends(require_admin)])
def admin_companies(pool: str = "", db=Depends(get_db)):
    """Every company, or one pool: pool=current (the mode's), live (real) or demo (sample)."""
    if pool == "current":
        pool = service.get_mode(db)
    if pool not in ("", "live", "demo"):
        raise HTTPException(400, "pool is current, live or demo.")
    where, args = (" WHERE is_real = ?", (service.pool_is_real(pool),)) if pool else ("", ())
    return [admin_company(db, r) for r in db.execute(f"SELECT * FROM companies{where} ORDER BY name", args)]


@app.get("/api/admin/factors", dependencies=[Depends(require_admin)])
def admin_factors():
    from .engine import FACTOR_GROUPS, GROUP_LABELS, TRL_STAGES
    return {"groups": FACTOR_GROUPS, "group_labels": GROUP_LABELS, "trl_stages": TRL_STAGES}


def save_company(db, body: CompanyIn, cid: int | None, evidence_status: str = "confirmed") -> int:
    """Insert or update a company. A new one's evidence is the host's own unless evidence_status says otherwise;
    an update keeps the stored status unless the host reviewed the evidence. A company's pool (real or sample)
    is set when it's created and never changes, so no edit can slip a sample company into live mode or a
    real one into demo mode."""
    new = cid is None
    name = body.name.strip()
    if cid is None:
        is_real = body.is_real if body.is_real is not None else bool(service.pool_is_real(service.get_mode(db)))
    else:
        is_real = bool(service.get_company(db, cid)["is_real"])
    values = (name, name_key(name), body.emoji.strip(), body.sector, body.one_liner, body.claim_ask, body.website,
              dumps([f.model_dump() for f in body.facts]), dumps(body.evidence), body.evidence_note,
              int(is_real), int(body.active), body.vision, dumps(body.stages), body.raised_eur,
              dumps([i.model_dump() for i in body.investors]))
    try:
        if cid is None:
            cid = db.execute(
                "INSERT INTO companies (name, name_key, emoji, sector, one_liner, claim_ask, website, facts, evidence, "
                "evidence_note, is_real, active, vision, stages, raised_eur, investors, evidence_status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values + (evidence_status, now())).lastrowid
        else:
            db.execute("UPDATE companies SET name = ?, name_key = ?, emoji = ?, sector = ?, one_liner = ?, claim_ask = ?, "
                       "website = ?, facts = ?, evidence = ?, evidence_note = ?, is_real = ?, active = ?, vision = ?, "
                       "stages = ?, raised_eur = ?, investors = ? WHERE id = ?", values + (cid,))
            if body.evidence_reviewed:
                db.execute("UPDATE companies SET evidence_status = 'confirmed' WHERE id = ?", (cid,))
            if body.card_reviewed:
                db.execute("UPDATE companies SET card_status = '' WHERE id = ?", (cid,))
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(409, f"There's already a real company called {name}.")
    seed.score_company(db, cid)
    db.commit()
    if new:
        autoread.kick()  # a new card gets its AI ratings and social media read in the background
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


@app.get("/api/admin/submissions", dependencies=[Depends(require_admin)])
def admin_submissions(db=Depends(get_db)):
    return [dict(r) for r in db.execute(
        "SELECT id, name, sector, one_liner, claim_ask, website, created_at FROM submissions ORDER BY id")]


@app.post("/api/admin/submissions/{sid}/approve", dependencies=[Depends(require_admin)])
def admin_approve_submission(sid: int, db=Depends(get_db)):
    """Turn a submission into a real company, kept out of rotation until the host adds evidence and activates it."""
    sub = db.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone()
    if not sub:
        raise HTTPException(404, "No such submission.")
    if hit := autofill.exclusion(sub["name"], url=sub["website"] or ""):
        raise HTTPException(409, f"{sub['name']} is excluded (matches “{hit}”): funds, publishers and the event's "
                                 "partners are never rated as startups.")
    body = CompanyIn(name=sub["name"], sector=sub["sector"], one_liner=sub["one_liner"], claim_ask=sub["claim_ask"],
                     website=sub["website"], is_real=True, active=False)
    cid = save_company(db, body, None, evidence_status="pending")
    db.execute("DELETE FROM submissions WHERE id = ?", (sid,))
    db.commit()
    return admin_company(db, service.get_company(db, cid))


@app.delete("/api/admin/submissions/{sid}", dependencies=[Depends(require_admin)])
def admin_reject_submission(sid: int, db=Depends(get_db)):
    db.execute("DELETE FROM submissions WHERE id = ?", (sid,))
    db.commit()
    return {"ok": True}


@app.get("/api/admin/users", dependencies=[Depends(require_admin)])
def admin_users(db=Depends(get_db)):
    return {"users": accounts.list_users(db), "guests": accounts.guest_count(db),
            "guest_weight": config.GUEST_WEIGHT, "guest_max_share": config.GUEST_MAX_SHARE,
            "investor_weight": config.INVESTOR_WEIGHT, "player_weight": config.PLAYER_WEIGHT}


@app.delete("/api/admin/users/{uid}", dependencies=[Depends(require_admin)])
def admin_delete_user(uid: int, db=Depends(get_db)):
    if not accounts.delete_user(db, uid):
        raise HTTPException(404, "No such user.")
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


# --- outside opinions: AI models and social media (fetched from the dashboard, never on the game's path) --

@app.post("/api/admin/companies/{cid}/reads/{kind}", dependencies=[Depends(require_admin)])
def admin_reads(cid: int, kind: str, db=Depends(get_db)):
    """Ask the AI models (kind=ai) or read social media (kind=social) about one company, and keep the results."""
    comp = service.get_company(db, cid)
    if not comp or kind not in ("ai", "social"):
        raise HTTPException(404, "No such company or read.")
    results = reads.rate_all(comp, brief=brief.for_review(db, comp)) if kind == "ai" else reads.social_all(comp)
    return {"report": autoread.store(db, cid, results), "company": admin_company(db, service.get_company(db, cid))}


@app.post("/api/admin/autoread", dependencies=[Depends(require_admin)])
def admin_autoread(db=Depends(get_db)):
    """Read every card still missing AI ratings or a social media read, in the background (also done on startup)."""
    return {"started": autoread.kick(), "status": autoread.status(db)}


@app.delete("/api/admin/autoread/errors", dependencies=[Depends(require_admin)])
def admin_autoread_clear_errors(db=Depends(get_db)):
    """Clear the problems list on Admin. Not while a run is going: it keeps its own list and would write it back."""
    if autoread.status(db)["running"]:
        raise HTTPException(409, "Wait for the run to finish, then clear its errors.")
    autoread.clear_errors(db)
    return {"status": autoread.status(db)}


@app.post("/api/admin/refresh", dependencies=[Depends(require_admin)])
def admin_refresh(db=Depends(get_db)):
    """Update all cards: look at every real startup's sources again, cheap model first (refresh.py)."""
    if not refresh.kick():
        raise HTTPException(409, "Updating cards needs an OpenRouter key (OPENROUTER_API_KEY).")
    return refresh.status(db)


@app.get("/api/admin/refresh", dependencies=[Depends(require_admin)])
def admin_refresh_status(db=Depends(get_db)):
    return refresh.status(db)


# --- web pulse (host hint only: never feeds engine scores or player routes) ---------------------------

def store_pulse(db, cid: int, name: str) -> dict:
    from .crawler.pulse import compute_pulse
    result = compute_pulse(name)
    db.execute("UPDATE companies SET pulse = ? WHERE id = ?", (dumps(result), cid))
    db.commit()
    return result


@app.post("/api/admin/pulse/run/{cid}", dependencies=[Depends(require_admin)])
def admin_pulse_one(cid: int, db=Depends(get_db)):
    comp = service.get_company(db, cid)
    if not comp:
        raise HTTPException(404, "No such company.")
    return store_pulse(db, cid, comp["name"])


class PulseAll(BaseModel):
    active_only: bool = True
    limit: int | None = Field(None, ge=1)


@app.post("/api/admin/pulse/run-all", dependencies=[Depends(require_admin)])
def admin_pulse_all(body: PulseAll, db=Depends(get_db)):
    """One company at a time, each stored as it finishes, so a failure or a re-run picks up where it left off."""
    where = " WHERE active = 1" if body.active_only else ""
    rows = db.execute(f"SELECT id, name FROM companies{where} ORDER BY id").fetchall()
    ran, errors = 0, []
    for row in rows[:body.limit] if body.limit else rows:
        try:
            result = store_pulse(db, row["id"], row["name"])
        except Exception as e:  # noqa: BLE001 - one bad company never stops the batch
            errors.append({"id": row["id"], "name": row["name"], "error": str(e)})
            continue
        ran += 1
        if result["errors"]:
            errors.append({"id": row["id"], "name": row["name"], "error": "; ".join(result["errors"])})
    return {"ran": ran, "skipped": len(rows) - ran, "errors": errors}


# --- discovery: candidate startups from the open web, queued for the host ---------------------------

def candidate_out(row) -> dict:
    out = dict(row)
    for key in ("engine_hint", "pulse", "screen", "card"):
        out[key] = j(row[key])
    out["card_error"] = row["card_error"] or ""
    inside, why = engine.scope(autofill.scope_company(row))  # A'Pelago's or Redstone's thesis gates (rubric.json)
    out["scope"] = {"in": inside, "why": why}
    return out


class DiscoverIn(BaseModel):
    """Any one of: a field, a country, or scope "in". A country alone finds startups based there in any field.
    scope "in" keeps only finds inside A'Pelago's or Redstone's thesis gates (rubric.json); with no field it
    searches the in-scope fields (DISCOVER_FIELDS). scope "all" keeps everything screening lets through."""
    sector: str = Field("", max_length=60)
    country: str = Field("", max_length=40)
    scope: str = Field("all", pattern="^(all|in)$")
    limit: int = Field(8, ge=1, le=10)


@app.post("/api/admin/discover/search", dependencies=[Depends(require_admin)])
def admin_discover_search(body: DiscoverIn, db=Depends(get_db)):
    sector, country = clean_text(body.sector), clean_text(body.country)
    in_scope = body.scope == "in"
    if len(sector) < 2 and len(country) < 2 and not in_scope:
        raise HTTPException(422, "Enter a field or a country, or search in scope.")
    fields = [sector] if len(sector) >= 2 else (config.DISCOVER_FIELDS or ["blue economy"]) if in_scope else [""]
    rows, seen = [], set()
    for field in fields:
        for row in autofill.store_candidates(db, field, country, body.limit):
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
    if in_scope:
        rows = autofill.keep_in_scope(db, rows)
    rows = rows[:body.limit]
    autoread.kick()  # the new finds get their cards written in the background, so they show a proper pitch
    return [candidate_out(r) for r in rows]


@app.get("/api/admin/discover", dependencies=[Depends(require_admin)])
def admin_discover_list(status: str = "", sector: str = "", country: str = "", db=Depends(get_db)):
    sql, args = "SELECT * FROM candidates WHERE 1 = 1", []
    for col, value in (("status", status), ("sector_query", sector), ("country_tag", country)):
        if value:
            sql += f" AND {col} = ? COLLATE NOCASE"
            args.append(value)
    if not status:
        sql += " AND status != 'dismissed'"
    return [candidate_out(r) for r in db.execute(sql + " ORDER BY status = 'queued' DESC, id DESC", args)]


def get_candidate(db, cand_id: int):
    row = db.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No such candidate.")
    return row


class QueueIn(BaseModel):
    queued: bool


@app.post("/api/admin/discover/{cand_id}/queue", dependencies=[Depends(require_admin)])
def admin_discover_queue(cand_id: int, body: QueueIn, db=Depends(get_db)):
    """Queueing writes the game card straight away, so the startup arrives playable. If writing fails it's
    still queued, marked as needing a manual pass."""
    row = get_candidate(db, cand_id)
    if row["status"] == "approved":
        raise HTTPException(409, "Already approved into companies.")
    if hit := autofill.excluded(row):  # covers restoring a dismissed one too
        raise HTTPException(409, f"{row['name']} is excluded (matches “{hit}”): funds, publishers and the event's "
                                 "partners are never rated as startups.")
    db.execute("UPDATE candidates SET status = ? WHERE id = ?", ("queued" if body.queued else "new", cand_id))
    db.commit()
    if body.queued:
        autofill.write_candidate_card(db, get_candidate(db, cand_id))
    return candidate_out(get_candidate(db, cand_id))


@app.post("/api/admin/discover/{cand_id}/approve", dependencies=[Depends(require_admin)])
def admin_discover_approve(cand_id: int, db=Depends(get_db)):
    """Like approving a submission: a real company, out of rotation until the host checks evidence and activates it."""
    row = get_candidate(db, cand_id)
    if row["status"] == "approved":
        raise HTTPException(409, "Already approved into companies.")
    if hit := autofill.excluded(row):
        raise HTTPException(409, f"{row['name']} is excluded (matches “{hit}”): funds, publishers and the event's "
                                 "partners are never rated as startups.")
    return admin_company(db, service.get_company(db, track_candidate(db, row)))


def track_candidate(db, row) -> int:
    """File a find as a real company and return its id: the existing one if it's already there."""
    if same := autofill.existing_company(db, row["name"]):  # a second click, or filed under another candidate
        return autofill.link(db, row["id"], same["id"])
    # The card queued earlier, or one written now. The host chose it, so it's kept even if writing fails or the
    # AI doubts it: then the headline stands in as the pitch and it's marked for a manual pass.
    card = autofill.write_candidate_card(db, row)
    return autofill.approve_candidate(db, get_candidate(db, row["id"]), card=card)


@app.post("/api/admin/discover/track-in-scope", dependencies=[Depends(require_admin)])
def admin_discover_track_in_scope(db=Depends(get_db)):
    """Track every open find inside A'Pelago's or Redstone's thesis gates in one go. Out-of-scope finds stay where
    they are for the host to judge."""
    tracked, failed = [], []
    for row in db.execute("SELECT * FROM candidates WHERE status IN ('new', 'queued') ORDER BY id").fetchall():
        if autofill.excluded(row) or not engine.scope(autofill.scope_company(row))[0]:
            continue
        try:
            track_candidate(db, row)
            tracked.append(row["name"])
        except Exception as e:  # noqa: BLE001 - one bad find doesn't stop the rest
            failed.append({"name": row["name"], "error": reads.short_error(e)})
    if tracked:
        autoread.kick()  # the new companies get filled, checked and reviewed in the background
    return {"tracked": tracked, "failed": failed}


@app.post("/api/admin/companies/{cid}/rewrite", dependencies=[Depends(require_admin)])
def admin_rewrite_card(cid: int, db=Depends(get_db)):
    """Rewrite a real company's game card (emoji, sector, pitch, ask, facts) with AI from its headlines and site.

    Leaves evidence and scores alone. If the AI thinks it isn't a startup, nothing changes and the reason
    comes back so the host can decide.
    """
    comp = service.get_company(db, cid)
    if not comp:
        raise HTTPException(404, "No such company.")
    if not pitch.available():
        raise HTTPException(400, "Set OPENROUTER_API_KEY in .env to write cards with AI.")
    cand = db.execute("SELECT * FROM candidates WHERE company_id = ?", (cid,)).fetchone()
    try:
        card = autofill.write_card(comp["name"], cand["sector_query"] if cand else comp["sector"],
                                   cand["snippet"] if cand else "", j(comp["pulse"]), comp["website"] or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Card writer failed: {e}")
    if card["is_startup"]:
        note = comp["evidence_note"] or ""
        if "Card text written by AI" not in note:
            note = (note + " " + autofill.AI_NOTE.format(model=config.OPENROUTER_MODEL)).strip()
        db.execute("UPDATE companies SET emoji = ?, sector = ?, one_liner = ?, claim_ask = ?, facts = ?, evidence_note = ?, "
                   "card_status = 'ai' WHERE id = ?", (card["emoji"] or comp["emoji"], card["sector"] or comp["sector"], card["one_liner"],
                                    card["claim_ask"], dumps(card["facts"]), note, cid))
        db.commit()
    return {"company": admin_company(db, service.get_company(db, cid)), "is_startup": card["is_startup"],
            "reject_reason": card["reject_reason"]}


# --- the readiness checklists and the thesis criteria (rubric.json) -------------------------------------------

class ChecklistAnswer(BaseModel):
    answer: str = Field(pattern="^(yes|no|unknown)$")
    quote: str = Field("", max_length=checklist.QUOTE_MAX)
    url: str = Field("", max_length=500)
    source: str = ""


class FactorSupport(BaseModel):
    value: float | None = Field(None, ge=0, le=5)
    quote: str = Field("", max_length=checklist.QUOTE_MAX)
    url: str = Field("", max_length=500)
    source: str = ""


class ChecklistIn(BaseModel):
    """The host's own answers: rungs by "ladder.n" ("business.6"), investment factors by "redstone.name". An
    "unknown" answer or a null value clears it. confirm marks the company's evidence as reviewed by the host."""
    checklist: dict[str, ChecklistAnswer] = {}
    support: dict[str, FactorSupport] = {}
    confirm: bool = False


def _source_and_url(source: str, url: str) -> tuple[str, str]:
    ranks = engine.load_rubric()["sources"]["rank"]
    if source and source not in ranks:
        raise HTTPException(400, f"source is one of {', '.join(ranks)}.")
    url = url.strip()
    if url and not re.match(r"^https?://", url, re.I):
        raise HTTPException(400, "A source link starts with http:// or https://.")
    return source or "host", url


@app.get("/api/admin/rubric", dependencies=[Depends(require_admin)])
def admin_rubric():
    """The ladders, investment anchors, source ranks and thesis criteria the engine judges by."""
    return engine.load_rubric()


@app.put("/api/admin/companies/{cid}/checklist", dependencies=[Depends(require_admin)])
def admin_checklist(cid: int, body: ChecklistIn, db=Depends(get_db)):
    """Answer the readiness checklists and investment factors by hand: what the host stands behind, never touched
    by an AI run. Works without any API key."""
    comp = service.get_company(db, cid)
    if not comp:
        raise HTTPException(404, "No such company.")
    rubric = engine.load_rubric()
    ev = j(comp["evidence"], {}) or {}
    answers, support = dict(ev.get("checklist") or {}), dict(ev.get("support") or {})
    stamp = now()
    for key, a in body.checklist.items():
        ladder, _, n = key.partition(".")
        if ladder not in rubric["ladders"] or not any(str(r["n"]) == n for r in rubric["ladders"][ladder]["rungs"]):
            raise HTTPException(400, f"No checklist rung {key}.")
        if a.answer == "unknown":
            answers.pop(key, None)
            continue
        source, url = _source_and_url(a.source, a.url)
        answers[key] = {"answer": a.answer, "quote": " ".join(a.quote.split()), "url": url, "source": source,
                        "by": "host", "at": stamp}
    for key, s in body.support.items():
        group, _, name = key.partition(".")
        if group != "redstone" or name not in rubric["investment"]["factors"]:
            raise HTTPException(400, f"No investment factor {key}.")
        values = dict(ev.get(group) or {})
        if s.value is None:
            values.pop(name, None)
            support.pop(key, None)
        else:
            source, url = _source_and_url(s.source, s.url)
            values[name] = round(s.value * 2) / 2
            support[key] = {"quote": " ".join(s.quote.split()), "url": url, "source": source, "by": "host", "at": stamp}
        ev[group] = values
    ev["checklist"], ev["support"] = answers, support
    status = "confirmed" if body.confirm else comp["evidence_status"]
    db.execute("UPDATE companies SET evidence = ?, evidence_status = ? WHERE id = ?", (dumps(ev), status, cid))
    seed.score_company(db, cid)
    db.commit()
    return admin_company(db, service.get_company(db, cid))


@app.post("/api/admin/companies/{cid}/checklist/ai", dependencies=[Depends(require_admin)])
def admin_checklist_ai(cid: int, db=Depends(get_db)):
    """Answer a company's checklists with AI from its website and news, each answer quoted. The host's own answers
    stay as they are. Without a key, the host answers by hand instead."""
    comp = service.get_company(db, cid)
    if not comp:
        raise HTTPException(404, "No such company.")
    if not pitch.available():
        raise HTTPException(400, "Set OPENROUTER_API_KEY in .env to answer the checklist with AI, or answer it by hand.")
    try:
        tally = checklist.run(db, comp)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Checklist failed: {reads.short_error(e)}")
    return {"company": admin_company(db, service.get_company(db, cid)), "tally": tally}


class WindowIn(BaseModel):
    scale: str = Field("trl", pattern="^(trl|brl)$")
    peak: list[int] = Field(min_length=2, max_length=2)
    falloff: float = Field(3, gt=0, le=9)

    @field_validator("peak")
    @classmethod
    def peak_band(cls, value: list[int]) -> list[int]:
        if not (1 <= value[0] <= value[1] <= 9):
            raise ValueError("the peak band is two levels from 1 to 9, low first")
        return value


class ThesisIn(BaseModel):
    """One holder's criteria. An empty list (or ["*"]) accepts any sector or country; null ticket bounds are open."""
    sectors: list[str] = Field([], max_length=60)
    countries: list[str] = Field([], max_length=60)
    ticket_eur: list[int | None] | None = None
    window: WindowIn
    criteria_note: str = Field("", max_length=400)


@app.put("/api/admin/rubric/theses", dependencies=[Depends(require_admin)])
def admin_set_theses(body: dict[str, ThesisIn]):
    """Edit the thesis criteria (gates, stage window, note) in rubric.json: where the partners' real criteria go."""
    rubric = json.loads(config.RUBRIC_PATH.read_text())
    for holder, t in body.items():
        if holder not in rubric["theses"] or holder.startswith("_"):
            raise HTTPException(400, f"No thesis {holder}.")
        words = lambda xs: [x.strip().lower() for x in xs if x.strip()]
        sectors, countries = words(t.sectors), [c.strip() for c in t.countries if c.strip()]
        ticket = t.ticket_eur if t.ticket_eur and any(v is not None for v in t.ticket_eur) else None
        if ticket is not None and len(ticket) != 2:
            raise HTTPException(400, "ticket_eur is [min, max].")
        rubric["theses"][holder]["gates"] = {"sectors": "*" if not sectors or sectors == ["*"] else sectors,
                                             "countries": "*" if not countries or countries == ["*"] else countries,
                                             "ticket_eur": ticket}
        rubric["theses"][holder]["window"] = t.window.model_dump()
        rubric["theses"][holder]["criteria_note"] = t.criteria_note.strip()
    config.RUBRIC_PATH.write_text(json.dumps(rubric, indent=2, ensure_ascii=False) + "\n")
    engine.reload()
    return engine.load_rubric()["theses"]


@app.delete("/api/admin/discover/{cand_id}", dependencies=[Depends(require_admin)])
def admin_discover_dismiss(cand_id: int, db=Depends(get_db)):
    get_candidate(db, cand_id)
    db.execute("UPDATE candidates SET status = 'dismissed' WHERE id = ? AND status != 'approved'", (cand_id,))
    db.commit()
    return {"ok": True}


class HideReal(BaseModel):
    hide: bool


@app.post("/api/admin/hide-real", dependencies=[Depends(require_admin)])
def admin_hide_real(body: HideReal, db=Depends(get_db)):
    db.execute("UPDATE companies SET active = ? WHERE is_real = 1", (0 if body.hide else 1,))
    db.commit()
    return {"ok": True}


# --- demo / live mode -------------------------------------------------------------------------------

def mode_payload(db) -> dict:
    counts = db.execute(
        "SELECT SUM(is_real = 0) AS demo, SUM(is_real = 1 AND active = 1) AS live_active, "
        "SUM(is_real = 1 AND active = 0) AS live_pending FROM companies").fetchone()
    cands = db.execute("SELECT SUM(status = 'new') AS new, SUM(status = 'queued') AS queued FROM candidates").fetchone()
    return {"mode": service.get_mode(db), "autofill": autofill.status(db), "discover": autofill.settings_payload(),
            "counts": {k: counts[k] or 0 for k in ("demo", "live_active", "live_pending")},
            "candidates": {"new": cands["new"] or 0, "queued": cands["queued"] or 0,
                           "submissions": db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]},
            "reads": {"ready": reads.setup(), "models": reads.models(), "route": reads.route(),
                      "auto": autoread.status(db)}}


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(demo|live)$")


@app.get("/api/admin/mode", dependencies=[Depends(require_admin)])
def admin_mode(db=Depends(get_db)):
    return mode_payload(db)


@app.post("/api/admin/mode", dependencies=[Depends(require_admin)])
def admin_set_mode(body: ModeIn, db=Depends(get_db)):
    service.set_setting(db, "mode", body.mode)
    out = mode_payload(db)
    out["autofill_start"] = autofill.maybe_start(db) if body.mode == "live" else None
    return out | {"autofill": autofill.status(db)}


@app.post("/api/admin/autofill", dependencies=[Depends(require_admin)])
def admin_autofill(db=Depends(get_db)):
    started = autofill.maybe_start(db, force=True)
    return mode_payload(db) | {"autofill_start": started}


class DiveIn(BaseModel):
    label: str = Field(min_length=1)
    company_ids: list[int] = Field(min_length=1)
    mode: str = Field("daily", pattern="^daily$")
    date: str | None = None


@app.post("/api/admin/dives", dependencies=[Depends(require_admin)])
def admin_create_dive(body: DiveIn, db=Depends(get_db)):
    pool = service.get_mode(db)
    if service.outside_pool(db, body.company_ids, pool):
        raise HTTPException(409, f"A {pool} set can only hold {'real' if pool == 'live' else 'sample'} companies.")
    cid = db.execute("INSERT INTO dives (label, date, company_ids, mode, pool, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (body.label, body.date, dumps(body.company_ids), body.mode, service.get_mode(db), now())).lastrowid
    db.commit()
    return service.dive_payload(service.get_dive(db, cid))


class GenerateIn(BaseModel):
    count: int = Field(7, ge=1, le=60)
    cards: int = Field(5, ge=1, le=10)


@app.post("/api/admin/dives/generate", dependencies=[Depends(require_admin)])
def admin_generate_dives(body: GenerateIn, db=Depends(get_db)):
    """Queue the next `count` daily games automatically, on the next free days, rotating the in-game companies."""
    try:
        made = service.generate_dives(db, body.count, body.cards)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return [service.dive_payload(d) | {"company_ids": j(d["company_ids"], [])} for d in made]


@app.delete("/api/admin/dives/{dive_id}", dependencies=[Depends(require_admin)])
def admin_delete_dive(dive_id: int, db=Depends(get_db)):
    db.execute("DELETE FROM dives WHERE id = ?", (dive_id,))
    db.commit()
    return {"ok": True}


class ResetIn(BaseModel):
    scope: str = Field(pattern="^(real|seed|all|everything)$")


@app.post("/api/admin/reset", dependencies=[Depends(require_admin)])
def admin_reset(body: ResetIn, db=Depends(get_db)):
    if body.scope == "everything":
        seed.reset(db)
        accounts.ensure_test_accounts(db)  # the test account and test moderator from .env come straight back
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
                    headers={"Content-Disposition": 'attachment; filename="insights.json"'})


@app.get("/api/admin/export.csv", dependencies=[Depends(require_admin)])
def export_csv(db=Depends(get_db)):
    data = service.overview(db, real_only=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "sector", "votes", *[f"crowd_{a}" for a in AXES], "crowd_composite",
                *[f"engine_{a}" for a in AXES], "engine_composite",
                "ocean_impact", "business_ready", "tech_trl", "investment_ready",
                "thesis_apelago", "thesis_redstone",
                "gap", "coverage", "evidence_review", "origin", "flags", "top_action", "web_items", "web_lean", "verdict",
                "verdict_reason", "call", "call_reasons", "next_move", "next_steps",
                "brl_level", "brl_blocker", "trl_level", "ocean_level", "thesis_scope", "max_gap", "outside_composite"])
    blank = lambda v: "" if v is None else v
    for c in data["companies"]:
        cm = c["crowd"]["means"] or {}
        rd = c["readiness"]
        th = c["theses"]
        w.writerow([c["name"], c["sector"], c["crowd"]["n"], *[cm.get(a, "") for a in AXES], c["crowd"]["composite"] or "",
                    *[c["engine"]["axes"].get(a, "") for a in AXES], c["engine"]["composite"],
                    *[blank(v) for v in (rd["ocean_impact"]["score"], rd["business"]["score"], rd["tech"]["trl"],
                                         rd["investment"]["score"], th["apelago"]["score"], th["redstone"]["score"])],
                    "" if c["gap"] is None else c["gap"],
                    f"{c['coverage'].get('assessed', '')}/{c['coverage'].get('total', '')}",
                    c["review"]["status"], c["origin"],
                    "; ".join(f["label"] for f in c["flags"]),
                    c["actions"][0]["name"] if c["actions"] else "",
                    c["pulse"]["items_total"] if c["pulse"] else "", c["pulse"]["lean"] if c["pulse"] else "",
                    c["verdict"], c["verdict_reason"], c["call"]["label"], "; ".join(c["call"]["reasons"]),
                    f"{c['next']['text']}: {c['next']['with']}" if c["next"] and c["next"]["with"] else "",
                    "; ".join(f"{a['kind']}: {a['name']}" for a in c["actions"][:5]),
                    blank(rd["business"].get("level")), (rd["business"].get("blocker") or {}).get("text", ""),
                    blank(rd["tech"].get("trl")), blank(rd["ocean_impact"].get("level")),
                    "; ".join(f"{k}: {t['fit']}" for k, t in th.items()),
                    blank(c["divergence"]["max_gap"]), blank(c["outside"]["composite"])])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="insights.csv"'})
