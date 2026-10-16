# Pitchdle — Feature Spec 1: Web pulse + triangulation verdict

_Hand this file to the coding agent. It builds on the existing codebase layout; do not re-read the world, hook into the existing functions named here._

> **Refinements applied during implementation** (these override the text below where they differ)
> - Paths are `app/crawler/pulse.py` and `app/crawler/discovery.py` (the package lives under `app/`).
> - The pulse is stored as a JSON `pulse` column on `companies` (latest snapshot, like `crawl`), not a separate `company_pulse` table. Candidates store the same payload inline, so approving copies one field.
> - Feeds: Google News RSS and HN Algolia only. Product Hunt (token), Dealroom (auth) and BlueInvest (JS-rendered) are non-goals.
> - `lean`: `silent` if 0 items; `neutral` if no good/risk hits; `positive` if good ≥ 2×risk; `negative` if risk ≥ 2×good; else `mixed`.
> - `coverage`: `silent` (0), `high` (≥ 10 items or ≥ 3 in the last 30 days), else `low`.
> - Triangulation, checked in order: n < MIN_VOTES → unknown; |gap| ≥ 1.0 → divergent; 0.5 ≤ |gap| < 1.0 → unknown (leaning apart);
>   no pulse → unknown ("run web pulse"); lean negative with mean composite ≥ 3, or lean positive with mean < 2 → divergent; else convergent
>   (a silent pulse is noted as a possible discovery gap).
> - Discovery names come from "Show HN: Name – …" titles or "Name raises/secures/lands/closes/bags …" headlines; items without a name are dropped. Dedupe on a normalised name key.
> - Candidates keep one `status` (`new`/`queued`/`approved`/`dismissed`) plus `company_id`; no separate `queued`/`approved` ints.
> - Primed evidence is `trl_stage` only (strongest stage keyword on the site). A patent *mention* is not a granted patent; funding is a flag, not a score.

## Goal
Surface, for every active company in the host dashboard, an **external "web pulse"** (news/coverage volume + sentiment lean) and a three-way **triangulation verdict** that combines three independent reads:
- **Crowd** (the game's votes) — already computed in `service.company_insight()`.
- **Engine** (evidence-based readiness) — already computed and stored on the `companies` row.
- **Web pulse** (NEW) — coverage amount + sentiment lean from public feeds.

The verdict renders as: ✅ **convergent** (all three roughly agree) / ⚠ **divergent** (crowd and engine disagree, or web pulse contradicts both). Divergence is the actionable output — it flags startups with a *discovery or positioning problem*, which is the differentiating insight for the fund/accelerator hosts.

**Hard rule:** the web pulse is a *hint for the host*, never the game path. It never changes engine scores and never blocks or gates any player request. It lives entirely on the host/admin side, exactly like the existing crawler (`crawler/__init__.py` docstring: "never change engine scores by themselves").

## Why this feature
This is the "connect different types of information" criterion from the brief. The triangulation view is what separates this from a generic score-a-deck: an operator can't act on crowd opinion alone, but a *divergent* crowd-vs-reality signal tells them exactly where to intervene.

---

## 1. Data model — new table: `company_pulse`

```
company_pulse
  id             INTEGER PK
  company_id     INT NOT NULL → companies(id)      # UNIQUE per company (latest snapshot)
  fetched_at     TEXT NOT NULL                      # ISO timestamp (db.now())
  items_total    INT                                # articles / hits found
  items_recent   INT                                # hits within the last 30 days (momentum)
  good_count     INT                                # sentiment-lean positives
  risk_count     INT                                # sentiment-lean risk/negatives
  lean           TEXT                               # 'positive' | 'negative' | 'neutral' | 'mixed' | 'silent'
  top_hits       JSON                               # [{title, link, published, lean}] — cap ~8 most recent
  sources        JSON                               # ["news.google", "hackernews", ...] which feeds ran
  coverage       TEXT                               # 'high' | 'low' | 'silent' (volume band)
```

A single latest-snapshot-per-company is enough for v1. Do not build history tables yet.

## 2. Backend — extend `crawler/`
Create `crawler/pulse.py` with a `compute_pulse(name: str, limit: int = 20) -> dict` that:
- Collects items from **multiple open feeds** (no auth, no paid API):
  - Google News RSS — reuse the pattern in `crawler/news.py:fetch()` (same `FEED`, `TIMEOUT`, UA header). Keep `news.py` for the per-company crawler; `pulse.py` can call `news.fetch` OR re-implement the request with a blob of items. Prefer calling `news.fetch` and extending it to accept a higher limit.
  - **Hacker News** (Algolia public API, no key): `https://hn.algolia.com/api/v1/search?query=<name>&tags=story`.
  - **Product Hunt** public feed if reachable (optional, degrade silently).
  - Any feed that fails must be caught and logged into `sources`/errors, never raised.
- From each item's `title` (and `link`), run a **sentiment-lean** on the text using the **existing keyword approach** — do NOT add an ML model. Add two word lists to the module (tiny dict is fine):
  - positive: raises, raised, funding, wins, launch(ed), partnership, grant, award, pilot, expansion, growth, contract, backed
  - risk: lawsuit, delay, layoffs, regulator, investigation, default, cancels, halts, downgrading, probe, allegations
  - A `title` counts once toward `good_count` or `risk_count` only if it clearly matches one side; a title matching both or neither → neutral.
- Compute **lean** and **coverage**:
  - `lean`: root-positive vs root-negative → 'positive'/'negative'/'mixed'; if items_total == 0 → 'silent'; otherwise 'neutral'.
  - `coverage`: 'high' (≥ 10 items OR ≥ 3 recent), 'low' (1–9 items), 'silent' (0 items).
  - `items_recent`: published within the last 30 days (parse `published` when present; treat unknowns as not-recent).
- Return the payload matching the `company_pulse` columns above.

## 3. Backend — routes in `app/main.py`
- `POST /api/admin/pulse/run/{company_id}` (admin-guarded) → recompute & store for one company; return the stored row. Mirror `admin_recrawl`'s pattern.
- `POST /api/admin/pulse/run-all` (admin-guarded, body `{active_only: bool, limit?: int}`) → loop over companies, compute + store each; return `{ran: n, skipped: n, errors: [...]}`. Must be resumable/idempotent and must **not** block: run each in the loop with its own try/except so one failure doesn't stop the batch. Simple sequential loop is fine for v1 (event-scale; no async workers).
- Store results via `db.execute("INSERT OR REPLACE ...")` on the UNIQUE `company_id`.

## 4. Backend — host endpoint
In `service.py`, extend `company_insight()` (and thus `/api/host/overview`) with two new fields per company:
- `pulse`: the latest `company_pulse` row or `None` (never synthetic defaults).
- `verdict`: computed **triangulation** as one of:
  - `convergent` — crowd and engine within ±0.8 gap AND (pulse silent, or lean matches the crowd/engine direction).
  - `divergent` — crowd-engine gap ≥ 1.0 (reuse the existing `callout`/flag threshold), OR (crowd ≈ engine but pulse lean is negative while composite ≥ 3, i.e. the market disagrees with the room).
  - `unknown` — not enough data (n < MIN_VOTES, or no pulse, or gap between 0.5 and 1.0).
- Add `verdict_reason`: a short human string ("Crowd 4.1 vs engine 2.8 — room overrates it", "Web negative while room positive").
Keep the existing `gap`, `flags`, `actions` untouched — add to them, don't replace. Do this as a pure function `triangulate(crowd, engine, pulse, min_votes) -> (verdict, reason)` so it's unit-testable.

## 5. Frontend — `static/js/host.js`
In the host dashboard:
- Add a **"Web pulse"** column to the companies table (volume + lean badge: e.g. `12 hits · pos`, or an empty/`—` cell when silent).
- Add a **verdict** column (✅/⚠/?) using the new `verdict` field.
- Add a "Run pulse for all" button in the header row (calls `/api/admin/pulse/run-all`), plus per-row on click of a company's pulse cell.
- In the expanded row (`companyRow` detail), add a **Triangulation** section showing the three reads side by side (crowd, engine, web pulse with its top ~5 hits as titled links) and the verdict/reason.

## 6. Admin — `static/js/admin.js`
In the company editor, show the latest pulse result in `crawlView`-style block (reuse the pattern): volume, lean, coverage, top hits with links, and a "Run pulse" button calling `/api/admin/pulse/run/{id}`.

## 7. Tests — `tests/`
- `test_pulse.py`: `compute_pulse` given mocked feed responses (monkeypatch the URL openers) → returns correct lean/coverage/items_recent; feed failure returns empty, never raises.
- `test_triangulation.py`: `triangulate()` across the three verdicts + unknown; boundary at threshold values.
- `test_api.py` additions: `/run-all` with one company that fails feed fetch → returns `errors` + `ran` for the rest, no 500.
All network mocked — no live calls in tests (matches existing `test_scoring.py`/`test_api.py` "no network needed" convention).

## 8. Non-goals (protect scope)
- No sentiment ML model, no paid APIs, no auth walls (no LinkedIn/X/Reddit).
- No pulse history / time-series charts (latest snapshot only).
- No async worker/queue — a simple sequential batch endpoint is fine.
- Pulse never feeds engine scores, gating, or any player-visible value.

---

# Pitchdle — Feature Spec 2: Web candidate discovery + queue

_Companion to Spec 1; same rules. Builds on Spec 1's `crawler/pulse.py` and the existing `admin.js` submissions/CRUD queue._

## Goal
Let the host **discover candidate startups from the open web** (filtered by sector/country), see the **same web pulse + an auto-scored engine read** for each, and push promising ones into a **private review **queue** to activate for future games** — closing the loop from "the single pipeline basis" to "automatically sourced pipeline." This is the **scalability** criterion (re-skin-able beyond blue economy) and the manual-to-automated pipeline the brief asks for.

**Rule identical to Spec 1:** candidates and their auto-scores are *hints for the host*; nothing auto-activates. A real startup only enters rotation when the host approves it in admin (matching how submissions already work: approve → becomes real+inactive → host adds evidence → activates).

## Why this feature
It turns Pitchdle from "already had startups handed to it" into "finds its own startups the same way," which is exactly the "fetch startups around the web and queue them" you asked for, grounded in feeds the codebase already talks to.

---

## 1. Backend — `crawler/discovery.py`
Functions:
- `search_candidates(q: str, limit: int = 10) -> list[dict]` → returns `[{name, url, source, snippet, fetched_at}]` from open feeds (no auth):
  - **Hacker News Algolia** (`https://hn.algolia.com/api/v1/search`?) — search `<q> startup` — gives names+links (often the company site).
  - **Google News RSS** (reuse pattern) `<q> startup funding`.
  - **BlueInvest public pages / Dealroom-listing pages** — only if reachable and scrapeable in plain HTML; if not reachable, degrade silently. These are optional.
- `expand_candidate(d)` → given a name+URL, reuse `crawler/website.py:fetch()` for a short text slice and `crawler/signals()` for evidence hints → produce `{url_text, signals}`. Guarded and cached like `website.py` already does.

Do **not** build country detection beyond a `country_tag` string passed by the host in the query (open feeds don't reliably geocode). Keep it honest: sector = query keyword, country = optional explicit keyword in the query.

## 2. Data model — new table: `candidates`

```
candidates
  id              INTEGER PK
  name            TEXT NOT NULL
  url             TEXT
  source          TEXT
  snippet         TEXT
  sector_query    TEXT          # the query used to find it
  country_tag     TEXT          # optional, from query
  engine_hint     JSON          # partial auto-score from crawl signals (primed evidence)
  coverage_note   TEXT          # how many factors auto-primed
  pulse           JSON          # reuse Spec 1 pulse payload, stored inline
  queued          INT DEFAULT 0 # host queue priority; 0 = not queued
  approved        INT DEFAULT 0 # 1 → became a company (keep link)
  status          TEXT DEFAULT 'new'  # 'new' | 'queued' | 'approved' | 'dismissed'
  created_at      TEXT
```

Keep this as a separate "pipeline" table; do NOT pollute `companies` with half-sourced rows.

## 3. Backend — routes in `app/main.py` (all admin-guarded)
- `POST /api/admin/discover/search` `{query, limit?}` → runs `search_candidates`, for each upserts into `candidates` (dedupe by name+url, keep earliest), triggers a background-ish per-candidate `expand_candidate` + `pulse` compute inline in the same request (event-scale, loop is fine), returns the merged list with `{name, url, sector_query, country_tag, engine_hint, pulse, status}`.
- `GET /api/admin/discover` → all candidates by status, filtered by `?status=` and `?sector=`/`?country=`.
- `POST /api/admin/discover/{cand_id}/queue` `{queued: bool}` → set `queued` (the "give priority for next game" toggle).
- `POST /api/admin/discover/{cand_id}/approve` → turn a queued candidate into a real `companies` row (name, sector from `sector_query`, website from `url`, `is_real=1`, `active=0`), copying `engine_hint` + `pulse` over, mirror `admin_approve_submission`'s flow. Then the host finalizes evidence in the existing company editor (already scored on save).
- `DELETE /api/admin/discover/{cand_id}` → dismiss (softly: set status='dismissed' rather than hard delete).

## 4. Frontend — `static/js/admin.js`
Add a **"Discover"** section (above the existing "Submitted startups"):
- A query form: sector keyword + optional country tag + limit, and a **Search** button → calls `/api/admin/discover/search`.
- A results table: name, source, sector/country, engine_hint (auto composite + "N/M factors"), pulse (volume+lean badge), status — with per-row action buttons: **Queue for next game**, **Approve into companies**, **Dismiss**.
- A filter row (status / sector / country) over all stored candidates.
- Add a small "Queued for next game" readout so the host sees the pending pipeline at a glance.

## 5. Tests — `tests/`
- `test_discovery.py`: `search_candidates` with mocked feed responses → returns deduped candidate dicts; feed failure → empty, no raise.
- `test_discovery_api.py`: subscribe+approve flow — a candidate becomes a `companies` row (inactive, real) with engine_hint copied; a search with one failing feed still returns results for the others; queued toggle persists.
All network mocked, no live calls.

## 6. Auto-score honesty (important — maps to the judge's "does it evaluate precisely" test)
`expand_candidate` produces **primed evidence** from crawl signals (e.g. patent mention → `patents`, TRL-stage keywords → `trl_stage`, funding phrase → not a score but a flag). The engine (`engine.py:score()`) runs on that evidence and yields a partial composite + `coverage` showing exactly how few factors were actually learned. **Label it "auto-estimate" and show coverage** — never present a half-scored candidate as a fully-scored company. This is the same "unknown is a real state" rule the engine already enforces.

## 7. Non-goals
- No LinkedIn/X/Reddit, no paid APIs, no geocoding beyond the explicit query tag.
- No fully-automatic activation — a human approves before a candidate touches game rotation.
- No broad crawl of "every startup" — discovery is query-driven (sector/country), bounded by `limit`.
- Don't move discovery into the game critical path or any player-visible route.

---

_End of specs. Implement Spec 1 and Spec 2 in this order; Spec 2 depends on Spec 1's `crawler/pulse.py` + `compute_pulse` (share it, don't duplicate). Both must pass existing `tests/` and add the new tests listed, with network fully mocked._