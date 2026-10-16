# Pitchdle

A daily-puzzle crowd game for startup pitches, built for the JunctionX Turku blue-economy challenge.
Players read a one-line pitch, guess how a scoring engine rates it on four axes, and see their read
against the room's. The host dashboard turns those reads into perception-vs-reality flags and ranked
next actions. The full design is in [plan.md](plan.md).

## Run it locally (no Docker)

You only need Python 3.12 or newer.

```bash
./run.sh
```

Open http://localhost:8000/play. The first run creates `.venv`, installs `requirements.txt`, creates
`data/pitchdle.db` and loads the seed companies and dives. It needs no other setup.

| Page | What it's for | Password |
|---|---|---|
| `/play` | Today's solo dive (5 cards) | – |
| `/live` | Join the host-paced live room | – |
| `/wall` | Projector view: QR, live card, reveal, depth chart | – |
| `/host` | Dashboard: crowd vs engine, flags, next actions, leaderboards | admin |
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
| `DECAY_K` | `1.5` | Points decay; bigger is more forgiving |
| `LIVE_SECONDS` | `25` | Live-round timer |

Engine weights are in `weights.json`. After editing them, run `.venv/bin/python -m app.seed --rescore`.

## Rehearsing the live demo

1. Open `/wall` on the projector and `/host/live` on your laptop.
2. In `/admin` → Dives, click **Load demo votes** on "JunctionX live". This adds 30 fake players,
   flagged as seed votes, so the wall has a room even with two real phones.
3. In `/host/live`: **Start lobby** → phones scan the QR → **Open first card** → **Reveal** → **Next card** … → final depths.
4. Back in `/admin` → Session, click **Clear demo votes** before the real run. Exports always exclude demo votes.

The two designed demo cases are **TideLedger** (polished pitch, engine 1.7: the room overrates it) and
**Rakko Feed** (dull pitch, engine 4.0: the room underrates it, and the second look moves it up).

## Seed data

All 12 seed companies are **fictional**. Add real startups in `/admin` using verified public facts. The
"Hide real companies" button takes them all out of rotation if a team on the floor objects.
`python -m app.seed --reset` wipes everything and reseeds.

## Tests

```bash
.venv/bin/pytest
```

They cover the engine (including both demo cases), scoring maths, a full solo dive, the answer-key guard,
a 3-phone live round, the timer lock, admin add-and-score, and the demo-vote flags. No network needed.

## Layout

```
app/
  main.py        routes: pages, player API, live room, host, admin, QR
  service.py     reveal payloads, room sheet, summaries, leaderboards, host overview
  engine.py      evidence → per-axis engine read + coverage (weights.json)
  scoring.py     points, tiles, Against the Current bonus, depth zones, read tiers
  live.py        live-room state machine
  seed.py        seed / reset / rescore CLI and demo votes
  seed_data.py   the fictional seed companies and dives
  crawler/       optional website + news hints for admins; never on the game path
static/          plain HTML/CSS/JS, no build step
tests/
```

## Later: Proxmox

Docker is step 10 in the plan: a `python:3.12-slim` image running the same uvicorn command without
`--reload`, with `HOST=0.0.0.0`, a volume for `DB_PATH`, and `BASE_URL` set to the public URL. Nothing in the
code depends on Docker.
