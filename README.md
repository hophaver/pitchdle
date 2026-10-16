# Pitchdle

A daily card game for startup pitches, built for the JunctionX Turku blue-economy challenge.
Players read five short pitches, rate each on four quick calls (Novel, Useful, Plausible, Investable), and
after the last card see how their reads compare with everyone else's. The host dashboard sets the crowd
against an evidence-based engine score and turns the gaps into ranked next actions. The look follows
fermi.gg. The full design is in [plan.md](plan.md).

## Run it locally (no Docker)

You only need Python 3.12 or newer.

```bash
./run.sh
```

Open http://localhost:8000/play. The first run creates `.venv`, installs `requirements.txt`, creates
`data/pitchdle.db` and loads the seed companies and dives. It needs no other setup.

| Page | What it's for | Password |
|---|---|---|
| `/play` | Today's set (5 cards), results at the end | – |
| `/live` | Join the host-paced live room | – |
| `/wall` | Projector view: QR, live card, crowd vs engine per card, final overview | – |
| `/host` | Dashboard: crowd vs engine, flags, next actions | admin |
| `/host/live` | Run the live room (open, lock, reveal, next) | admin |
| `/admin` | Companies, evidence, opportunities, dives, resets, export | admin |

Host and admin pages use a browser login prompt. Any username works; the password is
`ADMIN_PASSWORD` (default `admin`).

### Play on your phone before it's on Proxmox

```bash
HOST=0.0.0.0 ./run.sh
```

Then open `http://<your-mac's-LAN-IP>:8000/play` on a phone on the same wi-fi. macOS may ask you to allow
incoming connections. Open `/wall` via the LAN IP too, so the QR code points at an address phones can reach,
or set `BASE_URL`.

### Config

Copy `.env.example` to `.env` to override any of these:

| Var | Default | |
|---|---|---|
| `DB_PATH` | `./data/pitchdle.db` | |
| `ADMIN_PASSWORD` | `admin` | A warning is logged while it's the default |
| `BASE_URL` | from the request | Used for the QR code |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | |
| `LIVE_SECONDS` | `25` | Live-round timer |
| `APP_MODE` | `demo` | Starting mode on a fresh database; the Admin toggle overrides it |
| `DISCOVER_AUTO` | `1` | Search for real startups when Live mode is switched on |
| `DISCOVER_FIELDS` | `ocean tech,blue economy,aquaculture` | Fields to search, one search each |
| `DISCOVER_REGION` | empty | Added to every search, e.g. `Finland` |
| `DISCOVER_DEPTH` | `3` | Startups added per field per run (1–10) |
| `DISCOVER_MAX` | `10` | Most auto-found startups kept |
| `DISCOVER_EXCLUDE` | empty | Comma list of words/names to skip |

### Demo and live mode

The toggle at the top of Admin switches the game and the host dashboard together: **Demo** uses the seeded
sample companies, **Live** uses real ones. Each mode has its own daily set and its own sets list.

In Live mode the app searches open feeds (Hacker News, Google News) for the `DISCOVER_*` fields in the background
and adds what it finds to the dashboard, inactive. Players see a "check back soon" notice until you press
**Add to game** on at least one. Name extraction from headlines is heuristic, so check each one first
(funds and news aggregators slip through; add them to `DISCOVER_EXCLUDE`).

Engine weights are in `weights.json`. After editing them, run `.venv/bin/python -m app.seed --rescore`.

## Accounts and guests

Everyone plays as a guest (a device cookie) until they sign up or log in with a username and password.
Guests get today's set only; an account keeps history, stats and streaks, and opens earlier daily sets.
Logging in moves whatever the device played as a guest onto the account. Players delete their account from
the menu under their username; the host can list and delete accounts in `/admin` → Users.

To blunt bot farms, crowd scores (player results, host dashboard, exports) weigh guests down: each guest
answer counts `GUEST_WEIGHT` (0.5) of a signed-in one, and once anyone signed in has answered a card, all
guests together make up at most `GUEST_MAX_SHARE` (40%) of its score. The live wall counts the room evenly.

## Rehearsing the live demo

1. Open `/wall` on the projector and `/host/live` on your laptop.
2. In `/admin` → Sets, click **Load demo votes** on "JunctionX live". This adds 30 fake players,
   flagged as demo votes, so the wall has a room even with two real phones.
3. In `/host/live`: **Start lobby** → phones scan the QR → **Open first card** → **Reveal** → **Next card** … → **Finish**.
   Phones show each player their results when you finish.
4. Back in `/admin` → Session, click **Clear demo votes** before the real run. Exports always exclude demo votes.

The two designed demo cases are **TideLedger** (sounds great, engine 1.7: the room overrates it) and
**Rakko Feed** (sounds dull, engine 4.0: the room underrates it).

## Seed data

All 12 seed companies are **fictional**. Add real startups in `/admin` using verified public facts, and
write the pitch as one concrete line (show, don't tell): what it is or does, not how good it is. The
"Hide real companies" button takes them all out of rotation if a team on the floor objects.
`python -m app.seed --reset` wipes everything and reseeds.

## Tests

```bash
.venv/bin/pytest
```

They cover the engine (including both demo cases), crowd maths, a full solo set with results locked until
the last card, final answers, a 3-phone live round, the timer lock, admin add-and-score, and the demo-vote
flags. No network needed.

## Layout

```
app/
  main.py        routes: pages, player API, live room, host, admin, QR
  service.py     player results (you vs crowd), wall callout, host overview
  engine.py      evidence → per-axis engine read + coverage (weights.json)
  scoring.py     crowd stats and lean (higher / with / lower)
  live.py        live-room state machine
  seed.py        seed / reset / rescore CLI and demo votes
  seed_data.py   the fictional seed companies and sets
  crawler/       optional website + news hints for admins; never on the game path
static/          plain HTML/CSS/JS, no build step
tests/
```

## Later: Proxmox

Docker is step 10 in the plan: a `python:3.12-slim` image running the same uvicorn command without
`--reload`, with `HOST=0.0.0.0`, a volume for `DB_PATH`, and `BASE_URL` set to the public URL. Nothing in the
code depends on Docker.
