# Pitchdle — Build Plan (v3)

**Event:** JunctionX Turku, Redstone x A'Pelago blue-economy challenge
**Product concept:** a daily-puzzle-style crowd game ("Wordle for startup pitches") where players guess how
an engine scores a startup, plus a host dashboard that overlays crowd opinion against the engine's
readiness score and produces decision-ready venture intelligence (perception gaps, ranked
investors/grants/partners, next steps).
**Working name:** *Pitchdle* (repo name). The earlier draft called it *Ocean Opportunity Radar*; keep that as
the host-dashboard name if the team prefers it.
**Status:** Steps 1–9 built and running locally (`./run.sh`, see README). Step 10 (Docker on Proxmox) not started.
Seed companies are all fictional for now; real ones are added through `/admin`.

---

## What changed from v1

| Area | v1 | v2 (this doc) |
|---|---|---|
| Answer key | One composite 0–5 "expert score", but the leaderboard compared it per axis against 4 player sliders: the axes didn't line up | Engine outputs an **expert value per player axis** (Novel / Useful / Plausible / Investable) plus a composite. Mapping in §5 |
| Reveal | Text-only "you said X, crowd said Y" | **Per-axis feedback tiles** (green / yellow / grey + ↑↓ arrow), flipped one at a time, like Wordle and Loldle |
| Scoring | Raw sum of absolute errors (favours people who play fewer cards) | **0–1000 points per card** with decaying curve (GeoGuessr-style), fixed card set so everyone's totals compare |
| Session shape | Open-ended rotation | A **fixed set of 5 cards** ("today's Dive"), same for everyone, ending in a stats screen and a **spoiler-free emoji share grid** |
| Pacing | Self-paced, plus an unexplained "live now" admin toggle | Two explicit modes: **Solo / Daily** (self-paced) and **Live room** (host-paced, Kahoot-style) |
| Second look | Optional for player | Always shown, but one tap to **"Stick"**, so the round-2 signal is near-complete without adding friction |
| Input | 4 sliders | **6 big tap buttons (0–5) per axis**; sliders are fiddly on phones |
| Data model | No table for next actions, no coverage column, no duplicate-vote guard | Adds `opportunities`, `expert_coverage`, device token + unique vote constraint |
| Nickname | "3-char" and "≤12 chars" both stated | **3-letter arcade initials**, optional, default a random sea-creature emoji handle |
| Undefined terms | "invert axes", "large gap" | Formulas and thresholds stated in §4 and §9 |

### v3: Krillion-style "you vs the room" presentation

Krillion (a daily trivia dive where rarer answers sink you deeper) does two things this game needs:
it makes **your answer vs everyone else's** the centrepiece of the reveal, and it turns score into an
**ocean depth**, which fits a blue-economy event perfectly. Applied here as:

| Krillion | Pitchdle adaptation |
|---|---|
| Rare answers score more than popular ones | Rarity only pays when you're **also right**: being accurate on an axis where most of the room is wrong earns an *Against the Current* bonus (§1.3). Pure rarity would reward random contrarians and ruin the data |
| Named rarity tiers per answer | A **read tier** per card (Surface → Trench), from how few people in the room read it as well as you did (§1.3) |
| Points → metres → ocean zones | Dive score shown as **depth in metres**, through real ocean zones (Sunlight → Hadal), with a diver sinking as you play (§1.4) |
| End-of-dive answer sheet grouped by tier | Per-card **room sheet**: every 0–5 bucket per axis with its % of the room, your bucket, the crowd's favourite and the engine's answer marked (§1.2, §1.4) |
| Share your depth to the group chat | Share text leads with depth and zone, then the tile grid (§1.4) |
| Daily leaders | Wall shows the **whole room as divers at their depth** in a live depth chart (§9) |

Unlike Krillion, whose tiers are hand-assigned, our tiers are **measured** from the room's actual votes.

---

## 0. Context for the builder

- The player side is a **game**; the host side is an **intelligence tool**. The game is the *data-collection
  instrument*, not the deliverable. The host dashboard (divergence + ranked next actions) is the payoff.
- **Now:** runs on **localhost with no Docker** (plain Python venv, see §10.1). **Later:** self-hosted on a
  Proxmox/LXC Linux box (Docker), reachable on LAN and over the web. Nothing in the code may assume Docker.
- It must be playable on **phones with zero friction** (QR → URL → tap → submit → reveal). No install, no account.
- The event demo is a **live multiplayer round**: audience scans QR, plays on phones, a wall/projector
  screen shows crowd opinion colliding with engine scores in real time.
- The **core game must never depend on live web crawling** (event wi-fi is unreliable). Crawling is an
  OPTIONAL enrichment layer with graceful degradation. All authoritative scores live in the DB.
- Roles:
  - **Player**: scans, plays the card set, compares their take vs the crowd vs the engine.
  - **Host / operator (A'Pelago, Redstone)**: runs live mode, watches the dashboard, reads divergence and ranked next steps.
  - **Admin**: manual CRUD for companies (fake AND real; no crawl needed).

---

## 1. Design references (what we borrow from the "-dle" genre)

The genre works because of a few repeatable mechanics. Each one below maps to a specific feature.

| Game | Mechanic | Where it shows up in Pitchdle |
|---|---|---|
| **Wordle** | One shared puzzle per day, so everyone plays the same thing and can compare | Fixed 5-card **Dive** per day / per event session (§1.3) |
| **Wordle** | Colored tiles flip one at a time; the reveal *is* the dopamine | Per-axis tiles flip left-to-right after submit (§1.2) |
| **Wordle** | Spoiler-free emoji grid you can paste anywhere | Share grid: `Pitchdle #3 🌊 3870` + one tile row per card (§1.4) |
| **Wordle** | End screen with guess-distribution histogram + streak | Room depth chart (replaces the histogram), "your rank", streak (localStorage) |
| **Loldle / Poeltl** | Guess against several attributes at once; each column goes green / orange / red with ↑↓ arrows for numeric ones | 4 axes, each tile is green / yellow / grey with an arrow saying whether the engine is higher or lower |
| **Costcodle / Higher-Lower** | Guess a hidden number; feedback is "higher" or "lower" | The arrows on each tile; the hidden number is the engine's axis value |
| **Worldle / Globle** | Feedback tells you *how far* off, not just right/wrong | Tile color bands come from absolute error, and points decay smoothly with distance |
| **GeoGuessr** | Points decay continuously with distance; max per round, fixed number of rounds | 0–1000 points per card with exponential decay (§1.3) |
| **Heardle / Framed** | Clues revealed progressively; using fewer clues is worth more | Second look reveals facts; round-2 points are worth half (§1.1) |
| **Kahoot** | Host-paced room, everyone answers the same question on their phones, big screen shows results and a podium | Live room mode + wall view (§2, §9) |
| **Krillion** | Same daily set for all; your answer is graded against what everyone else answered; rare answers sink you deeper; score is an ocean depth | Room sheet per card, read tiers, Against the Current bonus, depth-in-metres score and zones, depth-chart wall (§1.2–§1.4, §9) |

Things we deliberately **don't** borrow: multiple guesses per card (one guess + one revision is enough
signal and keeps a card under ~30 s), hard mode, and accounts for cross-device streaks.

### 1.1 The card and the guess

A company is shown as a card with:
- **name + sector chip** (e.g. 🌊 wave energy)
- **one line on what the company does**
- **one line on its claim / ask** (e.g. "raising €500k to scale its floating desalination pilot")

The player rates it on 4 axes, each a row of **6 tap buttons, 0–5** (no sliders):
1. **Novel**: is this new or surprising?
2. **Useful**: would people actually use it?
3. **Plausible**: can this actually work / be built?
4. **Investable**: would you put money in?

Submit is enabled once all 4 are set. Crowd numbers are **never shown before you submit** (no herding;
also keeps the vote data clean).

**Second look (round 2).** Right after the round-1 reveal, a "flip the card" step shows 1–2 engine facts
(team size, funding stage, traction, revenue, pilots). The player either taps **Stick** (one tap, keeps
round-1 answers) or adjusts and resubmits. Round 2 is always shown; Stick keeps it frictionless.
- Score rose on facts → substance > story; host flag "needs a product traction story."
- Score fell on facts → story > substance; host flag "overclaims; needs repositioning."

### 1.2 The reveal (the Wordle moment)

After round-1 submit, four tiles flip one at a time (~250 ms apart):

```
 NOVEL     USEFUL    PLAUSIBLE  INVESTABLE
 [ 4 ↓ ]   [ 3 ✓ ]   [ 5 ↓↓ ]   [ 2 ↑ ]
  yellow    green     grey       yellow
```

- Tile shows **your** number. Color from absolute error `e = |you − engine|`:
  🟩 `e ≤ 0.5` · 🟨 `0.5 < e ≤ 1.5` · ⬛ `e > 1.5`
- Arrow = where the engine is relative to you (↑ higher, ↓ lower, ✓ on it; double arrow if ⬛).
- Below the tiles, three lines:
  1. *"You: 3.5 · Crowd: 4.1 · Engine: 2.6"* (composite)
  2. Points for this card, counting up.
  3. Verdict: *"You read it like the engine"* (all 🟩/🟨), or the **perception-gap callout** when the crowd
     diverges: *"84% of the room scored this 4+. The engine says 2.0: this pitch reads better than its
     fundamentals."* The callout only appears once a card has ≥ 5 votes.

**Room sheet (Krillion-style, you vs everyone).** Under the tiles, each axis expands into a row of six
buckets (0–5) showing what the room answered:

```
 PLAUSIBLE                                    you ● crowd ◆ engine ▼
  0      1      2      3      4      5
  ░2%   ░4%   ▓9%   ▓18%  █41%  ▓26%
                ▼            ◆●
  "41% of the room said 4, like you. Only 9% said 2, the engine's read."
```

- Bar height / shade = share of the room in that bucket (round-1 votes for this card, this dive).
- Markers: your bucket ●, the crowd's most common bucket ◆, the engine's value ▼ (engine values are
  fractional; ▼ sits between buckets).
- One generated sentence per axis, picked from templates: *with the crowd and right*, *with the crowd
  and wrong*, *against the crowd and right* (the Against the Current case, highlighted), *against the
  crowd and wrong*.
- Collapsed to the single most interesting axis by default (largest crowd-vs-engine gap); tap to see all four.
- Hidden until the card has ≥ 5 votes; below that it says "You're one of the first divers. Check back
  at the end." (solo mode) and the end screen re-renders the sheet with the latest numbers.

The engine number is labelled **"Engine read"**, not "Expert", in the UI. It is a model, and naming it
honestly matters when real startups are on screen (see §7).

### 1.3 Sessions, points and the leaderboard

- A **Dive** = a fixed ordered set of **5 cards**, the same for everyone in that session (Wordle's
  "everyone gets the same puzzle"). The admin picks the set; default is a daily rotation from active
  companies, seeded by date so it's deterministic.
- **Points per card** (GeoGuessr-style continuous decay):
  `axis_points = 250 · exp(−e / k)`, with `k = 1.5` (configurable), summed over 4 axes → max 1000.
  Round 1 counts in full; any improvement in round 2 counts at half value:
  `card_points = r1 + 0.5 · max(0, r2 − r1)`. Revising toward the engine earns a bonus; revising away
  costs nothing. (Heardle-style: using the clue is worth less than knowing without it.)
- **Against the Current bonus** (Krillion's "rare answers score more", but only when correct): per axis,
  if your round-1 error `e ≤ 0.5` *and* the crowd mean's error on that axis is `> 1.0`, add
  `bonus = 250 · (1 − share_of_room_within_0.5_of_engine)`. Max +250 per axis, +1000 per card. Computed
  at reveal against the room at that moment (live mode: after lock, so it's the same for everyone);
  needs ≥ 5 votes, otherwise 0. Stored on the vote and not recomputed, so scores don't drift.
- **Depth.** 1 point = 1 metre. Base max is 5,000 m per Dive; with bonuses a perfect contrarian Dive
  reaches ~10,000 m, the Challenger Deep. Zones (real oceanography, the same bands everywhere in the UI):

  | Zone | Depth |
  |---|---|
  | ☀️ Sunlight | 0–200 m |
  | 🌗 Twilight | 200–1,000 m |
  | 🌑 Midnight | 1,000–4,000 m |
  | 🦑 Abyss | 4,000–6,000 m |
  | 🕳️ Hadal | 6,000 m + |

- **Read tier per card** (Krillion's named tiers, measured instead of hand-assigned). Rank your card
  points against everyone's for that card in this dive; percentile → tier:

  | Tier | You beat… | Label on card |
  |---|---|---|
  | 🫧 Surface | < 40% of the room | "Floating with the crowd" |
  | 🐠 Reef | 40–70% | "Solid read" |
  | 🐡 Twilight | 70–90% | "Sharper than most" |
  | 🦑 Deep read | 90–99% | "Most divers never got this deep" |
  | 🐋 One in the room | top 1, ≥ 20 votes | "Nobody read it better" |

  Tier names are ours, in the same spirit; don't copy Krillion's tier names or branding. Tiers are
  display-only and recomputed whenever shown (in solo mode a card's tier can rise or fall as more people
  play); stored points and bonuses never change.
- **Dive score** = sum over 5 cards, shown as depth. Because every player gets the same cards, depths
  compare fairly.
- **Leaderboards** (room / session scoped):
  - **Deepest dive**: highest Dive depth.
  - **Against the Current**: most bonus metres (contrarians who were right; the most valuable signal for the host).
  - **Most moved**: biggest round-2 deltas (who changes their mind when shown facts).

### 1.4 End screen and share grid

**During the Dive:** a slim depth gauge on the left edge of the phone screen. The background shades from
light to deep blue as you sink, and a small diver drops to your running depth after each reveal, with
the metres counting up. Zone names appear as you cross them ("Entering the Midnight zone").

After card 5:
- **Final depth + zone** ("3,870 m · Midnight zone"), rank in room ("#7 of 63").
- **Room depth chart**: a vertical ocean strip with every player in this dive as a dot at their depth,
  yours highlighted (replaces the Wordle-style histogram; same information, on theme).
- **Answer sheet** (Krillion's end-of-dive sheet): the 5 cards listed with your read tier, points, any
  Against the Current bonus, and the room sheet for each one re-rendered with the final numbers. Cards
  are grouped by tier, deepest first, so the best calls are at the top.
- Streak / games played (localStorage only; nice-to-have).
- **Share** button copies spoiler-free text (no company names, no per-axis numbers):

```
Pitchdle #3 🤿 3,870 m · 🌑 Midnight
🟩🟨⬛🟨 🐠
🟩🟩🟩🟨 🦑
⬛⬛🟨🟩 🫧
🟨🟩🟩🟩 🐡
🟩🟨🟨⬛ 🐠
🌊 2× against the current
pitchdle.example/play
```

Uses the Web Share API on phones, falls back to clipboard.

### 1.5 Identity

- No account, no password. On first visit the client gets a random **device token** (UUID in a cookie +
  localStorage), which identifies the player server-side and prevents double votes.
- Optional **3-letter arcade initials** for the leaderboard. Default handle: random sea-creature emoji +
  number (🐙 41). Basic profanity blocklist on initials.

---

## 2. Modes

| | **Solo / Daily** | **Live room** (event demo) |
|---|---|---|
| Pacing | Player moves through the 5 cards at their own pace | Host advances; all phones show the same card |
| Timer | None | 25 s per card, shown on phone + wall; late votes are rejected |
| Reveal | Right after the player submits | Phones show "locked in" until the host hits Reveal; then all phones and the wall flip together |
| Wall | Shows aggregates only | Shows current card, live vote count, then the room sheet reveal, then the live depth chart, and at the end the 5 deepest divers |
| Join | `/play` | `/live` (QR on the wall) |

Live mode is a thin state machine on the server: `lobby → card(n) open → card(n) locked → card(n) revealed
→ … → final`. Phones and wall poll `/api/live/state` every 2 s (cheap: one small JSON row). The host
drives it from `/host/live` with big Next / Reveal buttons.

---

## 3. System architecture

```
                 ┌─────────────── players on phones ───────────────┐
QR ──► browser ──► static SPA (mobile-first)                       │
                 │  card → tap 0–5 ×4 → submit → tiles flip →      │
                 │  second look → stick/revise → next … → share     │
                 └───────────────┬─────────────────────────────────┘
                                 │ REST (FastAPI), polling
┌────────────────────────────────▼──────────────────────────────────┐
│  Backend  (FastAPI, Python)                                       │
│   ├─ GET  /api/dive/today          → 5 card ids for the session   │
│   ├─ GET  /api/company/{id}        → card (no answer)             │
│   ├─ POST /api/vote                → round 1 / round 2            │
│   ├─ GET  /api/company/{id}/reveal → only after caller has voted: │
│   │                                  engine axes, crowd stats,    │
│   │                                  tiles, points, facts         │
│   ├─ GET  /api/leaderboard         → deepest / current / moved    │
│   ├─ GET  /api/live/state          → live-room state machine      │
│   ├─ POST /api/host/live/*         → next / lock / reveal         │
│   ├─ GET  /api/host/*              → dashboard aggregates         │
│   └─ /api/admin/*                  → CRUD, dives, reset, export   │
│                                                                   │
│  Engine (pure Python, deterministic, never in the request path)   │
│   ├─ score(company) → per-axis engine values + composite +        │
│   │                   coverage                                    │
│   └─ divergence / sensitivity calcs (host dashboard)              │
│                                                                   │
│  Crawler (OPTIONAL adapter, never on critical path)               │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│  SQLite (file-backed volume)                                      │
└───────────────────────────────────────────────────────────────────┘
```

**Answer-key rule:** `/reveal` refuses to return engine values to a device that hasn't voted on that
card (and in live mode, until the host reveals). The answer key must not be readable from devtools
before you guess.

---

## 4. Data model (SQLite)

```
companies
  id               INTEGER PK
  name             TEXT
  sector           TEXT          # "wave energy", "aquaculture", ...
  one_liner        TEXT          # what the company does
  claim_ask        TEXT          # their claim / the ask
  facts            JSON          # [{label, value}] 1–2 second-look facts
  evidence         JSON          # structured inputs the engine scores from (see §5)
  evidence_note    TEXT          # hand-written source notes
  engine_axes      JSON          # {novel, useful, plausible, investable} 0.0–5.0
  engine_composite REAL          # 0.0–5.0
  engine_coverage  JSON          # {assessed: 6, total: 10, unknown: [...]}
  scored_at        TEXT
  is_real          INT           # 0 fictional, 1 real
  active           INT

opportunities                    # "ranked next actions" (hand-seeded)
  id            INTEGER PK
  company_id    INT → companies
  kind          TEXT             # investor | grant | partner | customer
  name          TEXT             # e.g. "BlueInvest", "Business Finland"
  why           TEXT             # one-line "why this one next"
  fit           REAL             # 0–1, used to rank
  stage_fit     TEXT             # pre-seed | seed | A

dives
  id            INTEGER PK
  label         TEXT             # "#3" or "JunctionX live"
  date          TEXT
  company_ids   JSON             # ordered list of 5
  mode          TEXT             # daily | live

players
  id            INTEGER PK
  device_token  TEXT UNIQUE
  initials      TEXT NULL        # 3 letters
  handle        TEXT             # default emoji handle
  created_at    TEXT

votes
  id            INTEGER PK
  player_id     INT → players
  dive_id       INT → dives
  company_id    INT → companies
  round         INT              # 1 pitch-only, 2 after facts
  novel, useful, plausible, investable   INT 0–5
  stuck         INT              # round 2: 1 if player tapped Stick
  points        INT              # accuracy points, computed at insert
  bonus         INT              # Against the Current metres, set once at reveal (round 1 only)
  is_seed       INT              # 1 = demo seed vote (excluded from exports, wiped by reset)
  created_at    TEXT
  UNIQUE(player_id, dive_id, company_id, round)

live_state                       # single row
  dive_id, card_index, phase, phase_started_at
```

Computed on the fly:
- **Crowd mean per axis** = AVG(round-1 votes) per company (excluding `is_seed` when "real votes only" is on).
- **Crowd composite** = mean of the 4 crowd axis means (same weights as the engine composite).
- **Perception gap** = crowd composite − engine composite. Positive = *story > substance* (the room likes
  it more than the fundamentals justify); negative = *substance > story* (hidden gem).
- **Sensitivity** = crowd mean(round 2) − crowd mean(round 1), per axis and composite.
- **Consensus** = std-dev of round-1 composites (low = the room agrees).

---

## 5. Scoring engine (the answer key)

Pure, deterministic function, run at import / edit / recrawl, results stored on the company row.

**Framework inputs** (from `evidence`, hand-authored or crawl-assisted):
- **Ocean Impact Readiness**: impact measurability, problem pressure, solution potential (Ocean Impact Navigator framing).
- **Business Readiness (KTH BRL)**: market, value prop, business model, scalability.
- **Tech Readiness (TRL 1–9 → 0–5)**: derived from evidence (pilot, prototype, patents, certifications,
  deployed units). Never trust self-claimed TRL.
- **Investment Potential (Redstone 10 factors)**: Market, Product, Team, Business Model, Competition,
  Marketing & Distribution, Financials, Tech, Deal Dynamics, Impact.

**Mapping to the four player axes** (this is the v1 gap; weights in `weights.json`):

| Player axis | Engine sources |
|---|---|
| **Novel** | Redstone *Competition* + *Tech* differentiation, patents |
| **Useful** | Ocean Impact (problem pressure, solution potential) + BRL value prop / market |
| **Plausible** | TRL (evidence-derived) + Redstone *Team* + BRL business model |
| **Investable** | Redstone 10-factor aggregate (Market, Financials, Deal Dynamics weighted up) |

`engine_composite = Σ wᵢ · axisᵢ`, default equal weights, normalised to 0–5, rounded to 0.1.

**Honesty rule:** unknown data is a real state. Score only known evidence, and record coverage
("assessed on 6/10 factors; Financials, Team, Deal Dynamics unknown"). The dashboard shows coverage per
company; surfacing blind spots is a feature. On the player card, low-coverage companies get a small
"thin evidence" badge after the reveal.

**Unit-test the engine**: fixed evidence → fixed outputs; the two designed demo cases (§7) must land
where the demo script needs them (mismatch case: composite ≤ 2.2; diamond: ≥ 3.8).

---

## 6. Crawler (optional, swappable)

Module `crawler/`, one adapter per source:
- `website.py`: fetch site text (robots.txt, page + byte caps, on-disk cache).
- `news.py`: optional RSS/news for the company name.
- `linkedin.py`: explicitly optional, off the critical path; log and continue if blocked.
- FlareSolverr on the LAN if present for Cloudflare-walled pages; otherwise skip them.

Crawl output is **evidence for a human to confirm in admin**, then the engine rescored. A failed crawl
never blocks the game; the game always uses the last stored engine values.

---

## 7. Seed dataset

10–15 blue-economy companies:
- **3–5 real, recognisable** ones, to ground the demo ("oh, I know them").
- **3–5 clearly fictional / joke** ones (gives the game spread; nonsense scoring low is satisfying).
- Varied sector and stage (pre-seed → Series A).
- **Two designed demo cases:**
  - *Polished pitch, weak fundamentals*: reads great, engine composite ≤ 2.2 → crowd overshoots → gap lights up.
  - *Diamond in the rough*: reads dull or odd, strong evidence (pilot, revenue) → crowd undershoots, round-2 facts push it up.
- Each row: name, sector, one_liner, claim_ask, facts, evidence, evidence_note, is_real, 2–4 opportunities.
- Pre-built dives: `#1`–`#3` for solo play and one `JunctionX live` dive ordered for the demo script.

**Real-company caution:** showing a model's "readiness" number next to a real startup's name on a
projector can land badly. Label it "Engine read (demo model, public info only)", use only public facts,
and let admin hide `is_real` companies with one toggle if a team on the floor objects.

---

## 8. Admin panel

`/admin`, shared password from an env var (hackathon-grade).
- Company list (name, sector, active, is_real, composite, coverage) with edit / delete / toggle.
- **Add / edit company**: all fields + evidence form → on save, engine scores it → stored. New fake or
  real startups go in with no code change.
- **Opportunities** editor per company.
- **Dives**: build a 5-card set (pick + reorder), or auto-generate today's.
- **Recrawl** per company (optional).
- **Session controls**: reset votes (real, seed or both), clear leaderboard, load demo seed votes.
- **Export** host insights as JSON / CSV (seed votes excluded).

---

## 9. Host dashboard (the payoff)

1. **Live wall** (`/wall`, projector): big type, high contrast. Lobby with QR and joined count → current
   card + 25 s timer + vote count ticking → reveal: the **room sheet** for all 4 axes at once (bucket
   bars, crowd ◆, engine ▼ dropping in last for drama), gap callout, and a count of "N divers went
   against the current" → **depth chart**: the whole room as divers at their running depth on a dark
   ocean gradient with zone lines; they sink in an animation after each card → the 5 deepest at the end.
2. **Companies table**: crowd means (4 axes), engine axes, composite, coverage, **perception gap**
   (red when |gap| ≥ 1.0, amber ≥ 0.5), **sensitivity**, consensus, vote count.
3. **Perception-vs-reality flags**, auto-labelled with the numbers behind them:
   - *Story > substance*: gap ≥ +1.0
   - *Substance > story*: gap ≤ −1.0
   - *Transparency helps*: sensitivity ≥ +0.4
   - *Transparency hurts*: sensitivity ≤ −0.4
   - *Room split*: consensus std-dev ≥ 1.2 (the room can't agree, which is worth a conversation)
   Flags only fire with ≥ 5 real votes.
4. **Ranked next actions** per company from `opportunities`, ranked by `fit`, re-ordered by the flags
   (e.g. *story > substance* puts "get a pilot customer" partners above investors), each with its
   one-line "why this one next."
5. **Leaderboards**: deepest dive, against the current, most moved.
6. **Contrarian signal** (comes free from the bonus): per company, who was right against the crowd and
   on which axis. If the room overrates a startup's Plausible but 10% called it correctly, those 10%
   are the people worth asking why.

This is the screen the judges see; the ranking + gap flags are the "decision-ready" proof.

---

## 10. Stack (locked)

- **Backend:** Python 3.12 + FastAPI + uvicorn.
- **DB:** SQLite (stdlib `sqlite3`), WAL mode, single file at `DB_PATH` (default `./data/pitchdle.db`;
  a Docker volume later).
- **Frontend:** static HTML + vanilla JS + one CSS file, mobile-first, served by FastAPI. No build step,
  no npm, no framework. CSS `transform: rotateX` for the tile flip.
- **Live updates:** polling (2 s live state, 5 s dashboard). No websockets.
- **QR:** `segno` (pure Python) at `/qr?path=/live`, renders `BASE_URL` from env.
- **Deploy (later, step 10):** Docker + docker-compose on Proxmox, one service. LAN IP + optional
  reverse proxy for web access. Docker only wraps the same command used locally; no Docker-only code paths.
- **Deliverable now:** one directory, one command (`./run.sh`), open `http://localhost:8000` → play.

### 10.1 Running locally (no Docker)

Requirements: Python 3.12+ only. No Node, no database server, no Docker.

```bash
./run.sh
```

`run.sh` creates `.venv` if missing, installs `requirements.txt`, and starts
`uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`. Equivalent by hand:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- **First run is zero-setup:** on startup the app creates `./data/`, the schema, and loads the seed
  (companies, opportunities, dives) if the DB is empty. `python -m app.seed --reset` wipes and reseeds.
- **Config** via environment variables, optionally from a git-ignored `.env`; every one has a dev default
  so nothing is required locally:

  | Var | Default | Notes |
  |---|---|---|
  | `DB_PATH` | `./data/pitchdle.db` | |
  | `ADMIN_PASSWORD` | `admin` | Logs a warning at startup when left at the default |
  | `BASE_URL` | derived from the request | Used for the QR code and share text |
  | `HOST` / `PORT` | `127.0.0.1` / `8000` | |

- **Testing on your phone before Proxmox:** `HOST=0.0.0.0 ./run.sh`, then open
  `http://<your-mac's-LAN-IP>:8000` on a phone on the same wi-fi (macOS may ask to allow incoming
  connections). Without `BASE_URL` set, the QR uses the URL the wall page was opened with, so open
  `/wall` via the LAN IP, not `localhost`, when testing QR joins.
- **Pages:** `/play` (solo), `/live` (join live room), `/wall`, `/host`, `/host/live`, `/admin`.
- **Tests:** `.venv/bin/pytest` (engine + scoring + API), no network needed.
- Ship a `.env.example` listing the vars above.

---

## 11. Build order (do in this sequence)

1. **Scaffold**: FastAPI + schema + static shell + `requirements.txt` + `run.sh` + `.env.example`.
   `./run.sh` on a clean checkout serves `/play` at `http://localhost:8000`.
2. **Engine + seed**: evidence → per-axis values + composite + coverage; seed companies, opportunities,
   dives; engine unit tests including the two demo cases.
3. **Solo flow**: dive → card → tap buttons → submit → tile flip reveal → room sheet → second look
   (Stick / revise) → next → end screen with depth, room depth chart, answer sheet, share text. Depth
   gauge during play. Test on a real phone.
4. **Points + depth + leaderboards**: accuracy points at insert; Against the Current bonus at reveal;
   read tiers; deepest / against the current / most moved.
5. **Live room**: state machine, host controls, timer, phones synced, wall room sheet + depth chart.
6. **Host dashboard**: table, flags, ranked next actions.
7. **Admin**: CRUD, evidence form → rescore, dives, resets, export.
8. **Crawler (optional)**: website / RSS adapter, cache, failure path, wired to recrawl.
9. **Demo polish**: demo-seed votes (flagged `is_seed`) so the wall looks alive with 2 players; a
   written demo script; README for the team.
10. **Proxmox deploy (later)**: `Dockerfile` (python:3.12-slim, same uvicorn command without
    `--reload`, `HOST=0.0.0.0`), `docker-compose.yml` with a volume for `DB_PATH`, `BASE_URL` set to the
    public URL, optional reverse proxy. Not needed for local development.

### Definition of done (verify each before moving on)
- On a clean checkout, `./run.sh` → `http://localhost:8000/play` works with no other setup and no Docker.
- With `HOST=0.0.0.0`, a phone on the same wi-fi can play, and the QR on `/wall` points at a URL it can open.
- A player completes a full 5-card Dive (guess → tiles → second look → share grid) with **no outbound network**.
- `/reveal` returns nothing useful before the caller has voted.
- A live round with 3+ phones stays in sync through lock → reveal → depth chart → final top 5.
- The room sheet's percentages for each card add up to 100%, and its ◆ / ▼ markers match the dashboard numbers.
- A scripted seed scenario (room wrong, one player right) awards that player the bonus and puts them top of Against the Current.
- Admin adds a new company, it scores on save and can be put in a dive, no code change.
- Dashboard shows crowd vs engine, a perception gap, a sensitivity delta, flags and ranked next actions.
- Seed includes both demo cases and they produce the intended flags with the seeded votes.

---

## 12. Non-goals (48 h hackathon scope)
- No accounts, no auth beyond the admin password, no payments.
- No websockets; polling is fine.
- No frontend framework / build step.
- Live crawling is optional and never required for gameplay.
- No multi-tenant; one room is enough.
- No multi-guess cards, hard mode, or cross-device streaks.

---

## 13. Pitch notes (for the demo, not for building)
- Frame: **"crowd-sourced venture intelligence."** The game collects; the divergence engine delivers.
  Player votes are a structured data source, not just entertainment.
- One-liner: *"We measure perception vs reality at scale, and tell funds exactly where the gap is and who
  to call next."*
- Demo beat: open with the polished-pitch card in live mode → the room overshoots → wall flips → gap
  flag lights up on the dashboard → ranked next actions for that company. Then the diamond card, where
  the second look visibly moves the room.
- The ocean-depth theme isn't decoration: it's a blue-economy challenge, and "the crowd stays at the
  surface, the sharp reads go deep" is the product thesis in one image.
- End on the depth chart on the wall, then the share text: it's instantly recognisable and gets a laugh.

---

*This plan is the contract for the build. If anything is ambiguous, ask rather than guess. The
hosting, phone-play, optional-crawling, and answer-key rules above are fixed.*
