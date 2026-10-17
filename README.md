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
| `/moderate` | Review sign-ups, set member badges, make moderators; give A'Pelago's read of each startup | moderator account or admin |

Host and admin pages use a browser login prompt. Any username works; the password is
`ADMIN_PASSWORD` (default `admin`). `/moderate` takes the admin password too, and moderators sign in with their
own account: already logged in on `/play`, or with their username and password at the prompt.

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
| `TEST_MODERATOR_USERNAME` / `TEST_MODERATOR_PASSWORD` | empty | A moderator account made on startup, for testing. Keep it off public deployments |
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

## Accounts, sign-up review and badges

Everyone plays as a guest (a device cookie) until they log in. Signing up asks for a username and password plus
what a moderator needs to judge the person: full name, email, what they do, optionally organisation, location
and expertise, at least one link (LinkedIn, GitHub, portfolio, CV or another), and why they want to join. Every
sign-up waits on `/moderate` until a moderator approves it. Until then it can't log in, and the person plays on
as a guest; the first login after approval moves whatever that device played onto the account. Guests get
today's set only; an account keeps history, stats and streaks, and opens earlier daily sets. Players delete
their own account from the menu under their username; moderators can delete any member's account.

Moderators are members an admin has promoted: on `/moderate` → Members, open a row → **Make moderator**. Each
review and badge records who did it (the admin login shows as "admin"). Only admins make or remove moderators or
change a moderator's account (badge, deletion), a moderator's own included. A moderator's account menu on
`/play` links to the moderation page.

Members carry a badge a moderator sets, when approving or later. The Members tab shows how each one plays:
answers, how far their reads sit from the engine's on average, and how often they give all four calls the same
number. Badges are only shown to moderators.

| Badge | A member's answer counts | |
|---|---|---|
| High priority | `HIGH_PRIORITY_WEIGHT` (2) | |
| none | 1 | |
| Low priority | `LOW_PRIORITY_WEIGHT` (0.5) | |
| Muted | 0 | Left out everywhere, the live room included |

To blunt bot farms, each guest answer counts `GUEST_WEIGHT` (0.5), and once members have answered a card, all
guests together make up at most `GUEST_MAX_SHARE` (40%) of its score. These weights apply to player results,
the host dashboard and exports. The live room counts the people in it alike, except muted members. Accounts from
before sign-up review count as approved members with no badge.

## The startup card and its opinions

A card shows everything there is to weigh before rating it. On a wide screen it fills nearly the whole window,
with the facts left and the opinions right; on a phone the sections stack.

- **The pitch:** picture, sector, one line, the ask, the name and a link to the startup's page.
- **The facts:** money raised, the investor count and the latest stage; every incubation programme or funding
  round passed; and the investors, with how much each put in, or marked as only interested.
- **The vision**, up to 400 words.
- **What others make of it**, each as a small bar chart of the same four calls on 0–5 with its reason beside it:
  **A'Pelago**, the **AI models** (Claude, GPT, Grok) and **social media** (X, Threads, LinkedIn, Reddit,
  Bluesky).

All of the profile is edited in `/admin` on the company. The crowd's read is the one thing a card holds back: each
result card then sets you and everyone else beside all the opinions above.

- **A'Pelago** is the average of its representatives' evaluations: moderators and admins rate each startup on
  `/moderate` → Startups, as representatives rather than players. A representative sees the average there only
  after giving their own, their comment stays with the team, and deleting an account removes its evaluations.
- **AI models** rate the card's profile.
- **Social media**: Grok searches X itself and Claude searches each other platform's own site. A platform's read
  only counts posts the model cited on that platform; with none it shows as "no posts found".

The AI and social reads happen by themselves: a card gets them in the background as soon as it's added (in Admin,
from a player's submission or by discovery), and every card still missing one gets it when the app starts. Sample
startups are made up, so they get AI ratings only; a social search could only find their namesakes. Admin shows the
last run, with a **Read missing now** button; per company, **Ask the AIs** and **Read social media** read it again,
and any read can be typed in or corrected by hand, e.g. without a key. A failed read stays missing until the next
run.

These are paid APIs, never on the game's path: per card, three short model calls, and for a real startup up to 4
web searches per platform (Claude bills web search at $10 per 1,000) or X posts fetched by Grok ($5 per 1,000),
plus tokens. The first start with a key reads every card already there.

Keys go in `.env`, one of two ways:

- **One key for all three:** `OPENROUTER_API_KEY`. Every model call and social read goes through
  [OpenRouter](https://openrouter.ai), with each model's own search engine, and the provider keys below are
  ignored. Cited posts are checked against the platform's site; OpenRouter doesn't return the full search
  results, so they can't also be checked against what the search found. Claude's server-side refusal fallback is
  only on the direct route.
- **A key per provider:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`. A model without its key is
  skipped.

`CLAUDE_MODEL` / `GPT_MODEL` / `GROK_MODEL` pick other models. Left blank they default to `claude-opus-5-5`,
`gpt-6-astra` and `grok-4.7` directly, or `anthropic/claude-opus-5.5`, `openai/gpt-6-astra` and `x-ai/grok-4.7`
on OpenRouter, which names models differently.

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
the last card, final answers, a 3-phone live round, the timer lock, admin add-and-score, the demo-vote
flags, sign-up review with moderator access and badge weights, the card profile and every kind of opinion.
The AI and social reads run against canned API answers through the real SDKs. No network needed.

## Layout

```
app/
  main.py        routes: pages, player API, live room, host, admin, QR
  service.py     player results (you vs crowd), wall callout, host overview
  engine.py      evidence → per-axis engine read + coverage (weights.json)
  scoring.py     crowd stats, vote weights (guests, badges) and lean (higher / with / lower)
  accounts.py    sign-up, login, sessions, guests' answers moving onto an account
  moderation.py  sign-up review, member badges, how each member plays
  opinions.py    A'Pelago's, AI models' and social media's opinions, as the cards show them
  reads.py       asking the AI models and reading social media (never on the game's path)
  autoread.py    reading each new card in the background, and cards missing reads on startup
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
