# Pitchdle — Build Plan (v4)

**Event:** JunctionX Turku, Redstone x A'Pelago blue-economy challenge
**Product concept:** a daily card game where players read short startup pitches and rate them on gut
feel, then see how their reads compare with everyone else's. A host dashboard sets the crowd against an
engine-computed readiness score and turns that into decision-ready venture intelligence (perception gaps,
ranked investors / grants / partners, next steps).
**Status:** Built and running locally (`./run.sh`, see README). Docker on Proxmox (step 10) not started.
Seed companies are all fictional; real ones are added through `/admin`.

---

## What changed in v4

| Area                         | v3                                                              | v4 (this doc)                                                                                                              |
| ---------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Look and feel                | Dark ocean "dive" theme: depth gauge, zones, metres             | **Fermi.gg-style**: warm paper page, one big bold-coloured card at a time, heavy sans + a handwritten accent, pill buttons |
| Theme borrowed from Krillion | Depth score, read tiers, Against the Current bonus, depth chart | **Dropped.** No points, depth or tiers                                                                                     |
| Reveal                       | After every card (tiles, room sheet)                            | **None between cards.** Every comparison comes **after the last card**                                                     |
| Second look                  | Facts shown, then revise or stick                               | **Removed.** One answer per card, final; no revisions                                                                      |
| Share / identity             | Emoji share grid, 3-letter initials, three leaderboards         | **Removed.** No share, no initials, no rankings                                                                            |
| Comparison                   | You vs engine (points) and vs room (tiers)                      | **You vs the public opinion only**, per card and overall                                                                   |
| Card copy                    | "AI and blockchain marketplace that…"                           | **Show, don't tell**: one concrete line + the ask + a picture                                                              |

The engine is still the "reality" side of perception vs reality, but only the host dashboard and the
projector wall show it. Players never see it.

---

## 0. Context for the builder

- The player side is a **game**; the host side is an **intelligence tool**. The game is the _data-collection
  instrument_, not the deliverable. The host dashboard (divergence + ranked next actions) is the payoff.
- **Now:** runs on **localhost with no Docker** (plain Python venv, see §8.1). **Later:** self-hosted on a
  Proxmox/LXC Linux box (Docker), reachable on LAN and over the web. Nothing in the code may assume Docker.
- It must be playable on **phones with zero friction** (QR → URL → tap → done). No install, no account.
- The event demo is a **live round**: the audience scans a QR, plays on phones, and the projector shows the
  crowd's reads colliding with the engine's, card by card.
- The **core game must never depend on live web crawling** (event wi-fi is unreliable). Crawling is an
  OPTIONAL enrichment layer with graceful degradation. All authoritative scores live in the DB.
- Roles: **Player** (plays, sees self vs crowd), **Host** (runs the live round, reads the dashboard),
  **Admin** (manual CRUD for companies, fake or real, no crawl needed).

---

## 1. The game

### 1.1 Design reference: fermi.gg

| Fermi                                                                                             | Pitchdle                                                                                |
| ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Warm off-white page (#e9e6de), one big rounded card (~30 px radius) in a bold colour per question | Same; card colour rotates orange → blue → green → navy → plum                           |
| Heavy white Helvetica question, a handwritten (Caveat) accent word in yellow                      | The pitch line in heavy sans; the ask in handwriting                                    |
| Photo "polaroid" tilted on the card                                                               | A picture tile (one emoji on a white tilted square)                                     |
| "Q1/3" and "No. 082" in the card header                                                           | Progress dots and "No. 3"                                                               |
| `LOCK IT IN ↵` pill with spaced capitals                                                          | Same, enabled once all four calls are made                                              |
| Results card: "You guessed" block, cream "Answer" block, "How everyone guessed" histogram         | "You said" block, cream "Everyone" block, per-axis histograms with your bar highlighted |

### 1.2 The card (show, don't tell)

Each card shows only:

- a **picture** (emoji tile)
- the **sector** in small capitals
- **one concrete line** of what it _is_ or _does_, never adjectives about how good it is.
  ✔ "Dried Baltic seaweed in cow feed. The cows burp less methane."
  ✘ "Innovative sustainable feed solution for the agri sector."
- **the ask** in handwriting: "€800k to double its drying plant"
- the company name, small: "— Rakko Feed"

Then four rows of round **0–5 tap buttons**, labelled only NOVEL / USEFUL / PLAUSIBLE / INVESTABLE. No
hints, no instructions, no crowd numbers. `LOCK IT IN ↵` sends the answer. It is final: there is no
second look and no revision. The card slides away and the next one comes in.

### 1.3 Results (after the last card)

Shown only once every card in the set is answered (the API refuses earlier).

1. **Summary card** (paper colour): a handwritten headline from the player's overall lean, e.g. "You're
   more _bullish_ than the crowd", "You're in _sync_ with the crowd", "You're _tougher_ than the crowd",
   plus three counts: Higher ↑ / With = / Lower ↓ (cards where your composite was ≥ 0.5 above, within 0.5
   of, or ≥ 0.5 below the crowd's).
2. **One result card per startup**, in that card's colour:
    - picture + name
    - **You said**: your four numbers
    - **Everyone · n**: the crowd's four averages (cream block with a yellow border, like Fermi's answer)
    - a handwritten verdict: "Higher than the crowd" / "With the crowd" / "Lower than the crowd"
    - **How everyone answered**: a 0–5 histogram per axis with your bar in solid white

No points, ranks, tiers, share button or initials. The only comparison is you vs the public.

### 1.4 Sets

- A **set** is a fixed ordered list of 5 cards, the same for everyone that day (database name: `dives`).
- Today's set is picked deterministically from active companies, seeded by date, unless admin made one.
- Progress is stored server-side per device, so a refresh resumes at the next unanswered card.

### 1.5 Identity

No account, no password, no name. A random **device token** cookie identifies the player server-side and
prevents double answers.

---

## 2. Modes

|                  | **Solo** (`/play`)                                 | **Live room** (`/live`, event demo)                                                                                                                                |
| ---------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Pacing           | Player moves through the 5 cards at their own pace | Host opens each card; every phone shows the same one                                                                                                               |
| Timer            | None                                               | 25 s per card; late answers are rejected                                                                                                                           |
| Between cards    | Next card straight away                            | "Locked in · next one soon" (or "Missed it"); after the host reveals, "Eyes up · on the big screen"                                                                |
| Results on phone | After the last card                                | When the host finishes the set                                                                                                                                     |
| Wall             | n/a                                                | QR lobby → card + timer + answer count → **crowd histograms vs a dashed engine line** for that card → final: every card's crowd dot vs engine dot on one 0–5 track |

Live state machine: `idle → lobby → open(card n) → locked → revealed (wall only) → … → final`.
Phones and wall poll `/api/live/state` and `/api/live/wall` every 2 s.

---

## 3. System architecture

```
QR ──► phone browser ──► static pages (no build step)
                          card → 4 × tap 0–5 → lock → next … → results
                                │ REST (FastAPI), polling
┌───────────────────────────────▼───────────────────────────────────┐
│  Backend (FastAPI)                                                │
│   GET  /api/dive/today | /api/dive/{id}  → cards (pitch only)      │
│   POST /api/vote                         → one final answer/card   │
│   GET  /api/dive/{id}/results            → you vs crowd, only when │
│                                             every card is answered │
│   GET  /api/live/state | /api/live/wall  → live room              │
│   /api/host/*  (password)                → dashboard, live control │
│   /api/admin/* (password)                → CRUD, sets, resets,     │
│                                             demo votes, export     │
│  Engine (pure Python, never in the request path)                  │
│  Crawler (optional hints for admins, never on the game path)      │
└───────────────────────────────┬───────────────────────────────────┘
                                ▼
                     SQLite (single file)
```

---

## 4. Data model (SQLite)

```
companies      id, name, emoji, sector, one_liner, claim_ask, website, facts (JSON, shown on the wall),
               evidence (JSON), evidence_note, engine_axes (JSON), engine_composite, engine_coverage (JSON),
               scored_at, crawl (JSON), is_real, active, created_at
opportunities  id, company_id, kind (investor|grant|partner|customer), name, why, fit 0–1, stage_fit
dives (sets)   id, label ("#3" or "JunctionX live"), date, company_ids (JSON, ordered), mode (daily|live)
players        id, device_token UNIQUE, handle, is_seed, last_seen, created_at
votes          id, player_id, dive_id, company_id, novel, useful, plausible, investable, is_seed, created_at
               UNIQUE(player_id, dive_id, company_id)
live_state     single row: dive_id, card_index, phase, phase_started_at
```

Computed on the fly:

- **Crowd mean per axis**, **crowd composite**, **share per 0–5 answer** (whole percentages that sum to 100).
- **Player lean** per card: player composite − crowd composite → higher (≥ +0.5) / with / lower (≤ −0.5).
- **Perception gap** (host only) = crowd composite − engine composite.
- **Consensus** (host only) = std-dev of answer composites.

---

## 5. Scoring engine (host-side "reality")

Pure, deterministic function, run at import / edit / recrawl, results stored on the company row.

**Framework inputs** (from `evidence`, hand-authored or crawl-assisted):

- **Ocean Impact Readiness**: impact measurability, problem pressure, solution potential (Ocean Impact Navigator framing).
- **Business Readiness (KTH BRL)**: market, value prop, business model, scalability.
- **Tech Readiness (TRL 1–9 → 0–5)**: derived from evidence (pilot, prototype, patents, certifications,
  deployed units). Never trust self-claimed TRL.
- **Investment Potential (Redstone 10 factors)**: Market, Product, Team, Business Model, Competition,
  Marketing & Distribution, Financials, Tech, Deal Dynamics, Impact.

**Mapping to the four player axes** (weights in `weights.json`):

| Player axis    | Engine sources                                                                |
| -------------- | ----------------------------------------------------------------------------- |
| **Novel**      | Redstone _Competition_ + _Tech_ differentiation, patents                      |
| **Useful**     | Ocean Impact (problem pressure, solution potential) + BRL value prop / market |
| **Plausible**  | TRL (evidence-derived) + Redstone _Team_ + BRL business model                 |
| **Investable** | Redstone 10-factor aggregate (Market, Financials, Deal Dynamics weighted up)  |

`engine_composite = Σ wᵢ · axisᵢ`, default equal weights, normalised to 0–5, rounded to 0.1.

**Honesty rule:** unknown data is a real state. Score only known evidence, and record coverage
("assessed on 6/10 factors; Financials, Team, Deal Dynamics unknown"). The dashboard shows coverage per
company; surfacing blind spots is a feature.

**Unit-test the engine**: fixed evidence → fixed outputs; the two designed demo cases (§6) must land
where the demo script needs them (mismatch case: composite ≤ 2.2; diamond: ≥ 3.8).

**Crawler (optional):** `app/crawler/` fetches a company site (robots.txt, size caps, disk cache) and news
headlines, and turns them into keyword hints for an admin to review. It never changes scores by itself
and never sits on the game path.

---

## 6. Seed dataset

12 fictional blue-economy companies, written show-don't-tell, each with a picture, 1–2 wall facts,
evidence and 1–3 opportunities. Spread of sectors and stages, including joke companies for range.
**Two designed demo cases:**

- _Polished pitch, weak fundamentals_: **TideLedger** ("Pick up a bottle on the beach, scan it, earn a
  token." Engine 1.7). The room overrates it.
- _Diamond in the rough_: **Rakko Feed** ("Dried Baltic seaweed in cow feed…" Engine 4.0). The room
  underrates it.

Pre-built sets: `#1`–`#3` for solo play and `JunctionX live` ordered for the demo script.

**Real companies** go in through `/admin` using verified public facts only. The engine read stays off the
phones; on the wall it's labelled "engine". "Hide real companies" takes them all out of rotation.

---

## 7. Host side

**Dashboard (`/host`)**

1. **Flags**, auto-labelled with the numbers behind them (fire at ≥ 5 answers):
    - _Story > substance_: gap ≥ +1.0
    - _Substance > story_: gap ≤ −1.0
    - _Room split_: consensus std-dev ≥ 1.2
2. **Companies table**: crowd / engine per axis, composites, gap (red ≥ 1.0, amber ≥ 0.5), split,
   coverage, answer count. "Real answers only" hides demo votes.
3. **Ranked next actions** per company from `opportunities`, ranked by `fit`, re-ordered by flags
   (_story > substance_ lifts partners/customers, i.e. "prove it with a pilot"; _substance > story_ lifts
   investors/grants), each with its one-line "why this one next."
4. **Export** CSV / JSON (real answers only).

**Live control (`/host/live`)**: pick a set, Start lobby → Open → Lock → Reveal → Next → Finish.

**Admin (`/admin`)**: company CRUD with an evidence form (scores on save), picture, opportunities, optional
recrawl; sets builder; "Load demo votes" (30 fake players flagged `is_seed`); resets; export.

---

## 8. Stack (locked)

- **Backend:** Python 3.12+ + FastAPI + uvicorn. **DB:** SQLite (stdlib), WAL, file at `DB_PATH`.
- **Frontend:** static HTML + vanilla JS + one CSS file, mobile-first, no build step. Caveat is loaded
  from Google Fonts and falls back to a system hand font offline.
- **Live updates:** polling. No websockets. **QR:** `segno` at `/qr?path=/live`.
- **Deploy (later, step 10):** Docker on Proxmox wrapping the same command used locally.

### 8.1 Running locally (no Docker)

```bash
./run.sh
```

`run.sh` creates `.venv` if missing, installs `requirements.txt`, and starts uvicorn with reload on
`127.0.0.1:8000`. First run creates the DB and loads the seed. `python -m app.seed --reset` wipes and
reseeds; `--rescore` recomputes engine scores after editing `weights.json`.

| Var              | Default              | Notes                                        |
| ---------------- | -------------------- | -------------------------------------------- |
| `DB_PATH`        | `./data/pitchdle.db` |                                              |
| `ADMIN_PASSWORD` | `admin`              | Warning logged while it's the default        |
| `BASE_URL`       | from the request     | Used for the QR code                         |
| `HOST` / `PORT`  | `127.0.0.1` / `8000` | `HOST=0.0.0.0` to test on a phone over wi-fi |
| `LIVE_SECONDS`   | `25`                 | Live-round timer                             |

---

## 9. Build order

1. Scaffold: FastAPI, schema, static shell, `run.sh`. ✔
2. Engine + seed, engine tests. ✔
3. Solo flow: start → 5 cards → results. ✔
4. Live room: state machine, host controls, timer, phones synced, wall. ✔
5. Host dashboard: table, flags, ranked next actions, export. ✔
6. Admin: CRUD, evidence → score, sets, resets, demo votes. ✔
7. Crawler (optional). ✔
8. v4 redesign: Fermi look, show-don't-tell cards, results at the end, no revisions / share / ranks. ✔
9. Demo polish: demo script rehearsal, real companies entered by the team.
10. **Proxmox deploy:** `Dockerfile` (python:3.12-slim, same uvicorn command without `--reload`,
    `HOST=0.0.0.0`), `docker-compose.yml` with a volume for `DB_PATH`, `BASE_URL` set to the public URL.

### Definition of done

- On a clean checkout, `./run.sh` → `/play` works with no other setup, no Docker, no outbound network.
- Cards show only the pitch (picture, sector, one line, ask, name); no scores leak.
- Results are refused until every card is answered; answers can't be changed.
- Results show you vs the crowd only: per card, per axis, and an overall lean.
- A live round with 3+ phones stays in sync; phones get results only when the host finishes.
- Admin adds a company, it scores on save and can be put in a set, no code change.
- Dashboard shows crowd vs engine, gaps, flags and ranked next actions; demo votes trigger both designed flags.

---

## 10. Non-goals

- No revisions or second look.
- No websockets, no frontend framework / build step, no multi-tenant.
- Live crawling is optional and never required for gameplay.

---

## 11. Pitch notes (for the demo)

- Frame: **"crowd-sourced venture intelligence."** The game collects; the divergence engine delivers.
- One-liner: _"We measure perception vs reality at scale, and tell funds exactly where the gap is and who
  to call next."_
- Demo beat: open the live round on TideLedger → the room rates it high → reveal: the wall's dashed engine
  line sits far left of the crowd's bars → _story > substance_ lights up on the dashboard with "get a pilot
  partner" ranked first. Then Rakko Feed, where the room is the sceptic and the engine isn't.
- End on the wall's "How the room read it" track, then everyone looks at their own results card.

---

_This plan is the contract for the build. If anything is ambiguous, ask rather than guess. The
hosting, phone-play, optional-crawling, and engine-stays-off-the-phones rules above are fixed._
