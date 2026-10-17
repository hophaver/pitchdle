# Pitchdle

An ocean opportunity radar for fund and accelerator operators (the Redstone × A'Pelago challenge at JunctionX
Turku), with a daily pitch game as one of its signals. The dashboard shows which startups to back, watch or
avoid and why: the four readiness levels (ocean impact, business, technology, investment), fit with the
Redstone and A'Pelago theses, how a crowd of players read the pitch, and web coverage. For each startup it
ranks investors, grants, partners and clients to go to next, and names the next move. The look follows
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
| `/play` | The game: today's set (5 cards), results at the end | – |
| `/host` | Dashboard: the radar. Find startups, call, lenses (thesis, readiness, game, web), details with ranked next steps | admin |
| `/game` | Players, past games (crowd vs engine), next games queued | admin |
| `/admin` | Which companies are in the game, player submissions, exports and resets | admin |

Host and admin pages use a browser login prompt. Any username works; the password is
`ADMIN_PASSWORD` (default `admin`).

### Play on your phone before it's on Proxmox

```bash
HOST=0.0.0.0 ./run.sh
```

Then open `http://<your-mac's-LAN-IP>:8000/play` on a phone on the same wi-fi. macOS may ask you to allow
incoming connections.

### Config

Copy `.env.example` to `.env` to override any of these:

| Var | Default | |
|---|---|---|
| `DB_PATH` | `./data/pitchdle.db` | |
| `ADMIN_PASSWORD` | `admin` | A warning is logged while it's the default |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | |
| `APP_MODE` | `demo` | Starting mode on a fresh database; the Admin toggle overrides it |
| `DISCOVER_AUTO` | `1` | Search for real startups when Live mode is switched on |
| `DISCOVER_FIELDS` | `ocean tech,blue economy,aquaculture` | Fields to search, one search each |
| `DISCOVER_REGION` | empty | Added to every search, e.g. `Finland` |
| `DISCOVER_DEPTH` | `3` | Startups added per field per run (1–10) |
| `DISCOVER_MAX` | `10` | Most auto-found startups kept |
| `DISCOVER_EXCLUDE` | empty | Comma list of words/names to skip (whole words, in the name or headline) |
| `DISCOVER_EXCLUDE_NAMES` | `fund,funds,capital,ventures,…` | Words that make a *name* a fund, publisher or lab (name only) |
| `OPENROUTER_API_KEY` | empty | Optional: AI writes found startups' cards and skips non-startups |
| `OPENROUTER_MODEL` | `anthropic/claude-haiku-5.5` | Any OpenRouter model with structured outputs |

### Demo and live mode

The Demo/Live switch in the nav switches the game and the dashboard together: **Demo** uses only the seeded
sample companies, **Live** only real ones. Each mode has its own daily set and sets list. The two pools never mix:
a company's pool is fixed when it's created, a set can only hold its own pool's companies (and only ever yields
them), and players only reach the current mode's sets.

In Live mode the app searches open feeds (Hacker News, Google News) for the `DISCOVER_*` fields in the background
and adds what it finds, not in the game yet. Players see a "check back soon" notice until you switch **In game**
on at least one in Admin.

On the Dashboard (Live mode), search by **country**, by **field**, or both. A country search also runs under its demonym
("Finnish startup X raises"). Raw hits are screened before they're stored: exclusions first, then, with
`OPENROUTER_API_KEY` set, one AI call keeps only real startups that fit the field and are clearly based in the
country, inferred from each company's website text and headline (feeds don't geocode). Hits that fail are filed
under Dismissed with the reason ("based in Sweden, not Finland"); a later search for their own country revives them.
If the screen errors, or there's no key, nothing is dropped: hits are kept and marked unconfirmed.

**Track** on a new find writes its card with AI straight away (sector, pitch, ask, facts, from headlines and
site) and adds it to the radar. If writing fails, it's kept with its headline as the pitch. The AI only writes
card text, never evidence scores, and never invents amounts.

### The radar

Each startup gets a **call**: Back (best thesis fit ≥ 3.5), Watch, or Avoid (< 2.5), softened to Watch when the
room overrates the pitch, web coverage leans negative, or the evidence isn't confirmed. With no thesis factor
evidenced it says **Needs evidence** and never guesses.

**Next steps** come from hand-entered opportunities plus `landscape.json`, an editable list of real investors,
grants, partners and clients (Business Finland, EIC Accelerator, EMFAF, Nordic VCs, ocean funds, research
institutes, shipyards, ports, ferry operators…). Each is matched on sector keywords, the startup's evidenced TRL
against the entry's range, and region, with the reason shown; unknowns count as neutral. Thesis fit and the
room's read then reorder them. The **next move** is the weakest readiness level (or the first unknown one) and
the top match that addresses it. Check landscape entries before relying on them.

Some names are never filed as startups, whatever the AI says: the event's partners (Redstone, A'Pelago) and
publishers/databases (TechCrunch, Crunchbase, …, also matched in the website's domain), plus any name containing a
`DISCOVER_EXCLUDE_NAMES` word (fund, capital, VC, institute, summit, …). These match whole words of the name, so
"Blue Ocean Capital" is skipped and "Fundbox" isn't. Player submissions under those names can't be approved either. One real company per name:
a second "Granarium" is linked to the first, never added again, and duplicates left by older builds are merged on startup.

Found startups carry only what discovery can show: a tech stage, when their site or a headline states one
("pilot", "deployed"); otherwise nothing. Until the host confirms their evidence the call says so.

Engine weights are in `weights.json`. After editing them, run `.venv/bin/python -m app.seed --rescore`.

## Accounts and guests

Everyone plays as a guest (a device cookie) until they sign up or log in with a username and password.
Guests get today's set only; an account keeps history, stats and streaks, and opens earlier daily sets.
Logging in moves whatever the device played as a guest onto the account. Players delete their account from
the menu under their username; the host can list and delete accounts in `/game` → Players.

To blunt bot farms, crowd scores (player results, host dashboard, exports) weigh guests down: each guest
answer counts `GUEST_WEIGHT` (0.5) of a signed-in one, and once anyone signed in has answered a card, all
guests together make up at most `GUEST_MAX_SHARE` (40%) of its score.

## Rehearsing the demo

In `/game` → Next games, click **Demo answers** on a set. This adds 30 fake players, flagged as demo votes, so
the dashboard's Game lens has a crowd. Clear them in `/admin` → Data before the real run; exports always exclude
demo votes.

The two designed demo cases are **TideLedger** (sounds great, engine 1.7: the room overrates it) and
**Rakko Feed** (sounds dull, engine 4.0: the room underrates it).

## Seed data

All 12 seed companies are **fictional**. Real startups come from discovery in Live mode.
`python -m app.seed --reset` wipes everything and reseeds.

## Tests

```bash
.venv/bin/pytest
```

They cover the engine (including both demo cases), crowd maths, a full solo set with results locked until
the last card, discovery screening and exclusions, the demo/live pool rule, landscape matching, the call and the
next move. No network needed.

## Layout

```
app/
  main.py        routes: pages, player API, dashboard, game, admin
  service.py     player results (you vs crowd), host overview, the call and the next move
  landscape.py   matches startups to landscape.json (investors, grants, partners, clients)
  engine.py      evidence → per-axis engine read + coverage (weights.json)
  scoring.py     crowd stats and lean (higher / with / lower)
  seed.py        seed / reset / rescore CLI and demo votes
  seed_data.py   the fictional seed companies and sets
  crawler/       optional website + news hints for admins; never on the game path
static/          plain HTML/CSS/JS, no build step
tests/
```

## Later: Proxmox

Docker is step 10 in the plan: a `python:3.12-slim` image running the same uvicorn command without
`--reload`, with `HOST=0.0.0.0` and a volume for `DB_PATH`. Nothing in the
code depends on Docker.
