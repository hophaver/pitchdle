# Pitchdle — Patch spec: full brief coverage, gamified, dashboard standalone

_Hand this file to the coding agent (Claude). It builds on the existing Pitchdle codebase. Read the repo first; hook into and extend the named functions, don't rewrite the world._

## Important note about repo state
The working tree may contain **partial, incomplete implementations** of exactly these features (added in an earlier session, possibly reverted by now — check before you start). They may show up as: `engine.readiness()`, `engine.theses()`, `engine.factor_trail()`, `engine.full_score()` in `app/engine.py`; a `readiness`/`theses`/`factors` block and thesis-aware action boosting inside `service.company_insight()`; extra CSV columns in `app/main.py`; and dashboard rendering in `static/js/host.js` + CSS in `static/css/app.css`.

- **If those are present and working (tests pass):** reconcile any drift against this spec, don't duplicate.
- **If they are absent or broken:** implement them fully from scratch per this spec.
In both cases the **end state must match this spec exactly**, and the full test suite must pass before you're done. If the DB/seed is in a weird state, run `.venv/bin/python -m app.seed --reset` to restore the designed demo cases, but be aware that wipes votes.

---

## 1. What the original challenge brief asks for (the source of truth)
The brief says this is NOT "summarise a pitch deck with AI". It asks the tool to answer:
1. Which startups/opportunities are most promising?
2. **Why**, and **how they fit the relevant investment/accelerator thesis** ← the big gap today
3. Their **Ocean Impact Readiness, Business Readiness, Technological Readiness (TRL), Investment Readiness** levels ← named, surfaced
4. Which **investors / funding / partners / clients** are relevant **next, in prioritized order**
5. **What the startup or ecosystem actor should do next**

Judges: Creativity, Usability, Actionability, Scalability, Technical execution, Visual appeal.

**Product stance (keep throughout):** the game is the engagement + data-collection layer and the stand-out; the **host dashboard is the deliverable and must be a complete decision tool even with zero players**. Crowd opinion is an *overlay* that fills in once people vote — never a prerequisite. The `app/engine.py` docstring already enforces "never in the game's request path"; keep that.

---

## 2. The gaps and the fixes (summary)

| Gap | Fix |
|---|---|
| No thesis-fit score | Add A'Pelago accelerator fit + Redstone investment fit, from evidence, with a grounded "why", and use it to order the ranked next-actions |
| Named readiness levels not surfaced | Add & expose Ocean Impact / Business (BRL) / Tech (TRL 1–9) / Investment readiness, each with score + coverage |
| Evidence trail not provable | Expose the actual factor values behind every score (the "decision-ready" proof) |
| Dashboard useless before players | Evidence-based "Thesis read" panel + full per-company details visible with 0 votes; crowd fills in later |
| Where do scores come from | Surface `evidence_note`/sources on the host next to the readiness levels |

---

## 3. Backend — engine (`app/engine.py`)

All new functions are **pure and deterministic** projections of the stored `evidence` dict (what the evidence form already saves). No DB migration needed — compute fresh. Keep `score()`/`composite_of()`/`factor_value()`/`factor_keys()`/`TRL_STAGES` as-is.

### 3a. Weighted mean of known factors (shared helper)
```python
def _weighted_known(evidence, spec, weights) -> (score|None, assessed:int, total:int)
```
`spec` is a `[[factor_key, weight], ...]` list (same shape as the existing `axes` specs in `weights.json`). Unknown factors drop out of the mean; coverage records `assessed`/`total`. Returns `(None, 0, total)` if nothing known. Essentially reuse the same loop logic already in `score()`.

### 3b. Readiness levels
```python
def readiness(evidence, weights=None) -> dict
```
Input: `evidence`. Output: the four named levels, each:
```python
{
  "key": "ocean_impact",
  "label": "Ocean Impact Readiness",
  "score": 0.0..5.0 | None,     # None = unevidenced (honest)
  "trl": int|None,              # ONLY on the 'tech' level: TRL 1-9 from evidence.trl_stage
  "coverage": {"assessed": n, "total": m},
}
```
Level → factors mapping (put the factor lists in `weights.json` under a new `"levels"` key so weights are editable, matching the existing `"axes"` pattern):
- `ocean_impact` — `impact.measurability`, `impact.problem_pressure`, `impact.solution_potential`
- `business` — `brl.market`, `brl.value_prop`, `brl.business_model`, `brl.scalability`
- `tech` — single factor `trl` (TRL 1–9 → also report `score` on 0–5 via `(trl-1)/8*5`, and keep `trl` as the 1–9 number)
- `investment` — the ten `redstone.*` factors

All scores `round(.,1)` except `trl` which stays an int. A missing read is `None`, never fabricated — matching the existing "unknown is a real state" rule in the docstrings.

### 3c. Thesis-fit
```python
def theses(evidence, weights=None) -> dict
```
Two holders, each scored 0–5 from evidence with a **grounded "why"**:
```python
{
  "apelago": {
    "key": "apelago",
    "label": "A'Pelago accelerator",
    "description": "Early-stage blue-economy accelerator: ocean impact, business readiness, founding team.",
    "score": 0.0..5.0 | None,
    "why": "Fits on team 4.0, problem pressure 4.5; watch financials 1.0.",   # generated from actual factor values
    "strengths": [{"label","value"},...],   # top factors >= 3.5
    "risks":     [{"label","value"},...],   # factors <= 2.0
    "coverage": {"assessed","total"},
  },
  "redstone": { ... same shape ... },
}
```
- `apelago` factors (weights in `weights.json` → `"theses".apelago`): leans on impact + BRL + team + product + TRL (an early-stage accelerator cares about these).
- `redstone` factors (→ `"theses".redstone`): leans on the ten `redstone.*` investment factors.
- `why` is computed, not an LLM: sort known factors by `(value - 2.5) * weight` descending; "Fits on {top strengths} … watch {top risks}." If nothing known → `"Not enough evidence to assess fit."`
- **This directly answers the brief's "how does it fit the relevant investment or accelerator thesis."**

### 3d. Evidence trail
```python
def factor_trail(evidence, weights=None) -> list[dict]
```
List every **known** factor as `{"key","label","value"}` (label via `factor_label()`). This is the provable reasoning behind each number. Example: `[{"key":"redstone.team","label":"Team (Redstone)","value":4.0}, ...]`.

### 3e. Aggregator (optional convenience)
```python
def full_score(evidence, weights=None) -> dict
```
Returns `score() + {readiness, theses, factors}`. Use it in the service so one call yields everything.

---

## 4. Backend — `weights.json` additions (editable, matches existing pattern)
Add two top-level keys (keep all existing keys untouched):
- `"levels"`: `{ocean_impact:{label,factors}, business:{...}, tech:{label, factor:"trl"}, investment:{...}}`
- `"theses"`: `{apelago:{label,description,factors}, redstone:{label,description,factors}}`

Give the seed's designed demo cases the intended result: **Rakko Feed** scores high on `redstone`/`business` (revenue, trials, sensible ask) and **TideLedger** scores low on `investment`/`business` but moderate on `impact`. Verify the actual numbers after wiring.

---

## 5. Backend — service (`app/service.py`)
Extend `company_insight()` (used by `/api/host/overview`) to **add** (don't remove anything) per company:
- `readiness` — from `engine.readiness(j(comp["evidence"], {}))`
- `theses` — from `engine.theses(...)`
- `factors` — from `engine.factor_trail(...)`

**Thesis-aware next-actions:** in the existing opportunity loop, after the current flag-based boost, add a boost so the ranked list better matches fit:
- opportunity `kind in (partner, grant, customer)` → `score += (apelago.score - 2.5) * 0.15`, append reason `"fits the accelerator thesis"` when positive.
- opportunity `kind == investor` → `score += (redstone.score - 2.5) * 0.15`, append reason `"fits the investment thesis"` when positive.
- Keep flags boost unchanged. This makes the "who next / in what order" output thesis-aware.

These run from stored `evidence` so they compute **with zero votes** — the standalone read.

---

## 6. Backend — exports (`app/main.py`)
- `export_json` already serializes `overview` (now includes readiness/theses/factors automatically). Fine.
- Extend `export_csv` row/headers to include: `ocean_impact`, `business_ready`, `tech_trl`, `investment_ready`, `thesis_apelago`, `thesis_redstone` (empty string when `None`). Keep existing columns.

---

## 7. Frontend — host dashboard (`static/js/host.js` + `static/css/app.css`)
Goal: **fully useful with zero players.** Two changes:

### 7a. Top "Thesis read (no crowd needed)" panel
Above the Flags section, render the top ~4 companies ranked by `theses.redstone.score` (descending, evidences scored first). Each card: name, sector, engine composite, the two thesis fit scores (color-coded: `≥3.5` green/`fit-hi`, `≤2.0` red/`fit-lo`, else neutral), and the redstone `why`. Header reads: *"Thesis read (no crowd needed)"* with a muted note *"Evidence-based view — plays work as soon as anyone votes."*

### 7b. Per-company expanded details (click a company row)
Already shows "Ranked next actions" + "Flags". **Add:**
1. **Readiness levels** — the four named levels with score + coverage (and TRL 1–9 for tech).
2. **Thesis fit** — both theses, score + `why`.
3. **Evidence trail** — the `factors` list rendered as chips (`Label: value`), plus the company's `evidence_note` (sources) when present.
4. Add a heading + muted note when there are no votes yet: *"No crowd answers yet — showing evidence-based assessment."*

Do **not** touch the player game flow (`play.js`, `wall.js`) — this feature is host-side only.

---

## 8. The two designed demo cases must land correctly (they are your proof)
- **TideLedger** ("pick up a bottle, scan, earn a token") — polished pitch, weak fundamentals. Engine composite ≤ 2.2. `readiness`: impact moderate, investment low. `theses`: apelago/redstone both **low**. Top action = a partner/customer ("prove it with a pilot before raising"). This is the "crowd overrates it / story > substance" case.
- **Rakko Feed** (seaweed cow feed) — dull pitch, real revenue + trials. Engine composite ≥ 3.8. `readiness`: investment + business high. `theses`: redstone **high (≥ 3.8)**, apelago high. Top action = an **investor** (thesis boosted). This is the "substance > story / strong fundamentals" case.

Write/extend tests that lock these in (see §10). The demo script for judges: show the dashboard with zero votes → top "Thesis read" correctly ranks Rakko Feed high and TideLedger low, with provable evidence → then load demo votes and watch the perception-gap flags appear. That single arc covers Actionability, Usability, Creativity, and Technical execution.

---

## 9. Gamified / awareness / monetization seams (already largely architected)
- **Game = the stand-out + data-collection layer.** Keep it. Don't weaken the crowd-vs-reality mechanic; it's the differentiator.
- **Monetization-ready (no code now, just don't box it in):** `service.needs_account()` already gates non-today daily sets behind login. That's the natural paywall seam for later: free = today's set + today's thesis read; account = history + streaks; paid tier = earlier-set archives + full deep-dive + the ranked list export. Design the host/export pieces so they could be gated by tier later — avoid hard-coding "free forever" anywhere.
- **Awareness hook (publishing):** the perception-gap line ("84% of players overrated this") is shareable per startup. Keep the host/wall able to produce one per company (already the `callout`).
- Do NOT build the paywall during the hackathon — just don't preclude it.

---

## 10. Tests
Extend `tests/test_engine.py` and `tests/test_api.py` (match existing style, no network):
- `readiness` returns exactly the 4 levels, each labeled, coverage ≥1 for seeded evidence; tech has correct `trl` (Rakko Feed `deployed` → 8); missing evidence → `score`/`trl` `None`.
- `theses` returns apelago + redstone with `why`s and strengths; Rakko redstone ≥ 3.8; TideLedger apelago low; empty evidence → score `None`, why `"Not enough evidence to assess fit."`
- `factor_trail` lists only known factors with key/label/value.
- `/api/host/overview` (fresh DB, zero votes): every company has `readiness`/`theses`/`factors`, empty crowd; at least one company has both theses scored → proves the dashboard runs standalone.
- Demo-votes test: Rakko Feed's top action is `investor` and boosted with a thesis reason; a boring-but-solid company outranks a pure-story one on the thesis read.
- Run the **entire** existing suite; all must pass before done.

## 11. Definition of done
- `readiness`, `theses`, `factor_trail` (or equivalent) exist in `engine.py`; `weights.json` has `levels` + `theses`.
- `company_insight` returns readiness/theses/factors and thesis-aware actions; computed with zero votes.
- `/api/host/overview` returns the new fields with no players; both demo cases rank as intended; CSV/JSON exports include the new columns.
- Host dashboard shows the "Thesis read" top panel and per-company readiness/thesis/evidence details, and reads clearly with 0 votes.
- All tests (new + existing) pass. The player game flow is untouched.

## 12. Non-goals (protect scope)
- No changes to `play.js`, `wall.js`, the live-room state machine, or the vote rules.
- No DB migrations / schema changes (everything derives from the stored `evidence`).
- No paywall implementation (just don't preclude it). No new paid APIs. No ML model.
- No broad crawler additions (the web-pulse and candidate-discovery specs are separate, optional features — do not fold them in here unless asked).