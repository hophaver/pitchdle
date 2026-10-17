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
| `/play` | The game: today's set (5 cards), results at the end. Players get the simple card, investors the full one | – |
| `/host` | Dashboard: the radar. Find startups; each card's call and its reviews' average (N U P I), sortable by any of them; details with the profile, readiness, thesis fit, every review and ranked next steps | admin |
| `/game` | Players, past games (crowd vs engine), next games queued | admin |
| `/admin` | The background AI work (last run, errors, run missing now), exports and resets | admin |
| `/moderate` | Review investor sign-ups, set member badges, make moderators; give A'Pelago's read of each startup | moderator account or admin |

Host and admin pages use a browser login prompt. Any username works; the password is
`ADMIN_PASSWORD` (default `admin`). `/moderate` takes the admin password too, and moderators sign in with their
own account: already logged in on `/play`, or with their username and password at the prompt.

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
| `TEST_MODERATOR_USERNAME` / `TEST_MODERATOR_PASSWORD` | empty | A moderator account made on startup, for testing. Keep it off public deployments |
| `GUEST_WEIGHT` / `INVESTOR_WEIGHT` | `0.5` / `2` | How much a guest's and an investor's answer count next to a player's (1) |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | |
| `APP_MODE` | `demo` | Starting mode on a fresh database; the Admin toggle overrides it |
| `DISCOVER_AUTO` | `1` | Search for real startups when Live mode is switched on |
| `DISCOVER_FIELDS` | `ocean tech,blue economy,aquaculture` | Fields to search, one search each |
| `DISCOVER_REGION` | empty | Added to every search, e.g. `Finland` |
| `DISCOVER_DEPTH` | `3` | Startups added per field per run (1–10) |
| `DISCOVER_MAX` | `10` | Most auto-found startups kept |
| `DISCOVER_EXCLUDE` | empty | Comma list of words/names to skip (whole words, in the name or headline) |
| `DISCOVER_EXCLUDE_NAMES` | `fund,funds,capital,ventures,…` | Words that make a *name* a fund, publisher or lab (name only) |
| `OPENROUTER_API_KEY` | empty | Optional: AI screens discovery hits, writes found startups' cards, fills their profiles and evidence, and reviews every card |
| `OPENROUTER_MODEL` | `anthropic/claude-haiku-5.5` | The model for every AI task but the reviews (screening, cards, profiles, evidence): pick a cheap one with structured outputs |
| `CLAUDE_MODEL` / `GPT_MODEL` / `GROK_MODEL` | empty | The review models: AI ratings and social media (see below) |

### Demo and live mode

The Demo/Live switch in the nav switches the game and the dashboard together: **Demo** uses only the seeded
sample companies, **Live** only real ones. Each mode has its own daily set and sets list. The two pools never mix:
a company's pool is fixed when it's created, a set can only hold its own pool's companies (and only ever yields
them), and players only reach the current mode's sets.

In Live mode the app searches open feeds (Hacker News, Google News) for the `DISCOVER_*` fields in the background
and adds what it finds to the dashboard. Startups players suggest show there too, labelled **Sent in by a player**,
to **Track** or **Dismiss** like any find. A tracked startup joins the daily game by itself (see the game check
below); players see a "check back soon" notice until one has.

On the Dashboard (Live mode), search by **country**, by **field**, or both. A country search also runs under its demonym
("Finnish startup X raises"). Raw hits are screened before they're stored: exclusions first, then, with
`OPENROUTER_API_KEY` set, one AI call keeps only real startups that fit the field and are clearly based in the
country, inferred from each company's website text and headline (feeds don't geocode). Hits that fail are filed
under Dismissed with the reason ("based in Sweden, not Finland"); a later search for their own country revives them.
If the screen errors, or there's no key, nothing is dropped: hits are kept and marked unconfirmed.

**Track** on a new find writes its card with AI straight away (sector, pitch, ask, facts, from headlines and
site) and adds it to the radar. If writing fails, it's kept with its headline as the pitch. The card writer never
invents amounts; the profile and evidence are filled right after (below).

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

**The game check.** Once a tracked startup's card is filled, one small call on `OPENROUTER_MODEL` checks the card
players would see: an operating startup (not a fund, news site or misparsed headline), a pitch that says what the
product does, nothing offensive or misleading, and a business in the event's fields. It passes into the daily game
by itself, or is kept out with the reason, shown on its card (**In game** / **Not in game**). Each startup is
checked once. Nobody edits companies by hand: everything on a card comes from discovery, the fill and the reviews.

**Profiles and evidence fill themselves.** Discovery only stores a headline and a website, so each real startup's
card is filled by AI in the background, right after it's tracked (and on startup for any not filled yet), before
its AI ratings, from its website and news headlines, on `OPENROUTER_MODEL`:

- the profile: money raised, investors, stages passed, vision, country. Only what the sources say; the rest stays
  empty. Amounts in other currencies are turned into euros at rough rates, with the original kept in the stage line.
- the evidence: every engine factor the sources speak to, scored 0–5 against written definitions, plus the tech
  stage (from pilots and deployments, never a claim) and patents. Unknowns stay unknown. That gives the readiness
  levels, thesis fit and the call; the evidence is marked **Estimated by AI · host confirms**, so the call is never
  Back until the host confirms it.

Only empty fields are filled, and evidence the host confirmed is never touched. Each startup is filled once. The
details card says when its profile came from AI, and while a fill runs it updates by itself.

**Reviews on the card.** The details card's "What everyone makes of it" has one **Refresh reviews** button: Claude,
GPT and Grok rate the startup and, for a real one, social media is read; the card updates when they land. Its top
row is the **Average** of the game, the AI models and social media on each call, each counting once. The same
average shows on every dashboard card (Novel, Useful, Plausible, Investable and their mean), and the dashboard sorts
by any of the five, high to low or low to high; startups with no reviews yet come last.

**Reviews cost little.** The reviewers don't read the whole profile: `OPENROUTER_MODEL` first condenses it, with
the evidence, into a brief of about 100 words that keeps every fact a rating rests on. The brief is kept and only
rewritten when the profile changes. The reviewers then answer with low reasoning effort and capped output, and
each social platform gets at most two searches.

Before the fill, a found startup carries only what discovery can show: a tech stage, when its site or a headline
states one ("pilot", "deployed"). Until the host confirms its evidence the call says so.

Engine weights are in `weights.json`. After editing them, run `.venv/bin/python -m app.seed --rescore`.

## Accounts: players and investors

Everyone plays as a guest (a device cookie) until they log in. Signing up starts with a toggle:

- **Player:** a username and password, and you're in at once. Players rate the simple card: the pitch and the
  four calls, then their read next to everyone else's.
- **Investor:** a username and password plus what a moderator needs to judge the person: full name, email, what
  they do, optionally organisation, location and expertise, at least one link (LinkedIn, GitHub, portfolio, CV or
  another), and why they want to join. An investor sign-up waits on `/moderate` until a moderator approves it;
  until then it can't log in and plays on as a guest. Investors rate the full card (below), and their results set
  their read beside A'Pelago's, the AI models' and social media's.

The first login moves whatever that device played as a guest onto the account. Guests get today's set only; an
account keeps history, stats and streaks, and opens earlier daily sets. Players delete their own account from the
menu under their username; moderators can delete any member's account, and the host can in `/game` → Players.

Moderators are members an admin has promoted: on `/moderate` → Members, open a row → **Make moderator**. Each
review and badge records who did it (the admin login shows as "admin"). Only admins make or remove moderators or
change a moderator's account (badge, deletion), a moderator's own included. A moderator's account menu on
`/play` links to the moderation page.

### How much an answer counts

Guests count least, players 1, investors most:

| Who | An answer counts |
|---|---|
| Guest | `GUEST_WEIGHT` (0.5), and all guests together at most `GUEST_MAX_SHARE` (40%) of a card once members have answered it |
| Player | 1 |
| Investor | `INVESTOR_WEIGHT` (2) |

A moderator can give any member a badge, which multiplies that: **High priority** ×`HIGH_PRIORITY_WEIGHT` (2),
none ×1, **Low priority** ×`LOW_PRIORITY_WEIGHT` (0.5), **Muted** ×0 (left out everywhere). A high-priority
investor counts 4. The Members tab shows how each one plays: answers, how far their reads sit from the engine's
on average, and how often they give all four calls the same number. Badges are only shown to moderators. These
weights apply to player results, the dashboard and exports. Accounts from before account kinds count as players.

## The startup card and its opinions

Investors see a card with everything there is to weigh before rating it, and the dashboard shows the same on
every startup (the facts and the reviews' average on the card, and all of it under **Details**). On a wide screen
the investor's card fills nearly the whole window, with the facts left and the opinions right; on a phone the
sections stack.

- **The pitch:** picture, sector, one line, the ask, the name and a link to the startup's page.
- **The facts:** money raised, the investor count and the latest stage; every incubation programme or funding
  round passed; and the investors, with how much each put in, or marked as only interested.
- **The vision**, up to 400 words.
- **What others make of it**, each as a small bar chart of the same four calls on 0–5 with its reason beside it:
  **A'Pelago**, the **AI models** (Claude, GPT, Grok) and **social media** (X, Threads, LinkedIn, Reddit,
  Bluesky).

The crowd's read is the one thing a card holds back: each result card then sets you and everyone else beside all the opinions above.

- **A'Pelago** is the average of its representatives' evaluations: moderators and admins rate each startup on
  `/moderate` → Startups, as representatives rather than players. A representative sees the average there only
  after giving their own, their comment stays with the team, and deleting an account removes its evaluations.
- **AI models** rate the card's profile.
- **Social media**: Grok searches X itself and Claude searches each other platform's own site. A platform's read
  only counts posts the model cited on that platform; with none it shows as "no posts found".

The AI and social reads happen by themselves: a card gets them in the background as soon as it's added (tracked
from discovery or a player's suggestion), and every card still missing one gets it when the app starts. Sample
startups are made up, so they get AI ratings only; a social search could only find their namesakes. Admin
shows the last run, with a **Run missing now** button; per company, **Refresh reviews** on its Dashboard details card
reads it again. A failed read stays missing until the next run.

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

## Rehearsing the demo

In `/game` → Next games, click **Demo answers** on a set. This adds 30 fake players, flagged as demo votes, so
the dashboard has a crowd in its reviews. Clear them in `/admin` → Reset before the real run; exports always exclude
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
next move, player and investor sign-up, investor review with moderator access, vote weights and badges, the card
profile and every kind of opinion. The AI and social reads run against canned API answers through the real SDKs.
No network needed.

## Layout

```
app/
  main.py        routes: pages, player API, dashboard, game, admin
  service.py     player results (you vs crowd), host overview, the call and the next move
  landscape.py   matches startups to landscape.json (investors, grants, partners, clients)
  engine.py      evidence → per-axis engine read + coverage (weights.json)
  scoring.py     crowd stats, vote weights (guests, players, investors, badges) and lean (higher / with / lower)
  accounts.py    sign-up (player or investor), login, sessions, guests' answers moving onto an account
  moderation.py  investor sign-up review, member badges, how each member plays
  opinions.py    A'Pelago's, AI models' and social media's opinions, as the cards show them
  reads.py       asking the AI models and reading social media (never on the game's path)
  autoread.py    reading each new card in the background, and cards missing reads on startup
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
