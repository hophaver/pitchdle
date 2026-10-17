# Pitchdle

An ocean opportunity radar for fund and accelerator operators (Redstone × A'Pelago challenge, JunctionX Turku),
with a daily pitch game as one of its signals. For each startup it gives a call (Back / Watch / Avoid), readiness
levels, thesis fit, the crowd's and AI models' reads, and ranked next steps (investors, grants, partners,
clients). Full design: [plan.md](plan.md).

## Run

Needs Python 3.12+.

```bash
./run.sh                  # http://localhost:8000/play
HOST=0.0.0.0 ./run.sh     # reachable from a phone on the same wi-fi
```

The first run creates `.venv`, installs dependencies and seeds `data/pitchdle.db` with 12 fictional companies.

| Page | What it's for | Access |
|---|---|---|
| `/play` | The daily game (5 cards) | anyone |
| `/host` | Dashboard: the radar, calls, details, next steps | admin |
| `/game` | Players, past and upcoming games | admin |
| `/admin` | Background AI jobs, exports, resets | admin |
| `/moderate` | Approve investors, manage members, A'Pelago's ratings, vote weights | moderator or admin |

Admin pages use a browser login: any username, password `ADMIN_PASSWORD` (default `admin`).

## Config

Copy `.env.example` to `.env`. The main settings:

| Var | Default | |
|---|---|---|
| `ADMIN_PASSWORD` | `admin` | Change for any real deployment |
| `DB_PATH` | `./data/pitchdle.db` | |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | |
| `APP_MODE` | `demo` | `demo` = seeded companies, `live` = discovered ones |
| `OPENROUTER_API_KEY` | empty | Enables AI screening, profile fill, reviews and social reads |
| `OPENROUTER_MODEL` | `anthropic/claude-haiku-5.5` | Cheap model for all AI tasks but reviews |
| `CLAUDE_MODEL` / `GPT_MODEL` / `GROK_MODEL` | empty | Review models (sensible defaults) |
| `DISCOVER_FIELDS` / `DISCOVER_REGION` | ocean tech,… / empty | What Live mode searches for |

Instead of OpenRouter you can set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `XAI_API_KEY`; a model without a key
is skipped. See `.env.example` for the rest (discovery limits, exclusions, vote weights, test moderator).

## How it works

- **Demo / Live.** A nav toggle switches the game and dashboard together. Demo uses seed companies only; Live
  only real startups found on Hacker News and Google News. The pools never mix.
- **Discovery.** Live mode searches by field and/or country. With an API key, an AI screen keeps only real startups
  that fit; rejects are filed under Dismissed with a reason. Funds, publishers and event partners are never filed
  as startups.
- **Fill.** Each tracked startup's card, profile and evidence are filled by AI from its site and headlines. Only
  stated facts are used; AI evidence is marked unconfirmed, so the call is never Back until the host confirms it.
  A game check then decides if the card enters the daily game.
- **The call.** Back (best thesis fit ≥ 3.5), Watch, or Avoid (< 2.5), softened to Watch if the crowd overrates it,
  coverage is negative, or evidence is unconfirmed. **Needs evidence** when nothing is known.
- **Next steps** match the startup against `landscape.json` (sector, TRL, region). The next move targets the
  weakest readiness level.
- **Reviews.** Claude, GPT and Grok rate each card, and social media (X, LinkedIn, Reddit, …) is searched for real
  startups. This runs in the background, never on the game's path, and uses paid APIs (model calls plus web searches per card).
- **Accounts.** Guests play via a device cookie. Players sign up instantly; investors need moderator approval and
  rate a fuller card. Votes are weighted: guest 0.5 (capped at 40% of a card), player 1, investor 2.

Engine weights live in `weights.json`; after editing, run `.venv/bin/python -m app.seed --rescore`.

## Demo rehearsal

In `/game` → Next games, **Demo answers** adds 30 fake players. Clear them in `/admin` → Reset before going live
(exports always exclude them). The two designed cases: **TideLedger** (the room overrates it) and **Rakko Feed**
(the room underrates it). `python -m app.seed --reset` wipes and reseeds everything.

## Tests

```bash
.venv/bin/pytest
```

No network needed; AI calls run against canned responses.

## Layout

```
app/
  main.py        routes
  service.py     results, dashboard, the call and next move
  engine.py      evidence → readiness scores (weights.json)
  landscape.py   next-step matching (landscape.json)
  scoring.py     crowd stats and vote weights
  accounts.py    sign-up, login, sessions
  moderation.py  investor review, member stats
  opinions.py    A'Pelago, AI and social opinions
  reads.py       AI model and social media calls
  autoread.py    background reads
  seed.py        seed / reset / rescore CLI
  crawler/       optional website + news hints
static/          plain HTML/CSS/JS, no build step
tests/
```

