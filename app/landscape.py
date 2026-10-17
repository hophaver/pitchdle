"""The ecosystem a startup could turn to next: investors, grants, partners and clients from landscape.json,
matched to a company by what it does, how far its technology is, and where it is.

Rule-based and explainable: every match carries the reason it was picked. Unknowns never count against a
company (an unevidenced TRL or country is scored as neutral), and an entry outside a company's sector is
never offered.
"""
import json
import re
from functools import lru_cache

from . import config

PATH = config.ROOT / "landscape.json"
KINDS = ("investor", "grant", "partner", "client")
NEUTRAL = 0.6
# A match is a heuristic; an opportunity the host picked by hand outranks one of equal fit.
WEIGHT = 0.85
NORDIC = {"finland", "sweden", "norway", "denmark", "iceland", "estonia", "latvia", "lithuania"}
EU = NORDIC - {"norway", "iceland"} | {
    "germany", "france", "netherlands", "belgium", "spain", "portugal", "italy", "greece", "ireland", "poland",
    "austria", "czechia", "czech republic", "hungary", "romania", "croatia", "slovenia", "slovakia", "bulgaria",
    "luxembourg", "malta", "cyprus"}


@lru_cache(maxsize=1)
def entries() -> list[dict]:
    return [e for e in json.loads(PATH.read_text())["entries"] if e.get("kind") in KINDS]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zåäö]+", (text or "").lower()))


def _sector(entry: dict, words: set[str]) -> tuple[float, list[str]]:
    if entry["sectors"] == ["*"]:
        return 0.5, []
    # "fish" also matches "fisheries", "ship" matches "shipping"
    hits = [s for s in entry["sectors"] if any(w == s or w.startswith(s) for w in words)]
    return (min(1.0, 0.6 + 0.2 * (len(hits) - 1)), hits) if hits else (0.0, [])


def _stage(entry: dict, trl: int | None) -> tuple[float, str]:
    lo, hi = entry["trl"]
    if trl is None:
        return NEUTRAL, ""
    if lo <= trl <= hi:
        return 1.0, f"TRL {trl} fits {lo}–{hi}"
    off = lo - trl if trl < lo else trl - hi
    return (0.4, f"TRL {trl}, they take {lo}–{hi}") if off == 1 else (0.0, "")


def _region(entry: dict, country: str) -> tuple[float, str]:
    c = (country or "").strip().lower()
    if not c:
        return NEUTRAL, ""
    region = entry["region"]
    inside = {"FI": c == "finland", "Nordic": c in NORDIC, "EU": c in EU, "Global": True}[region]
    if not inside:
        return 0.0, ""
    return (1.0 if region != "Global" else 0.7), country.strip() if region != "Global" else ""


def match(company: dict, trl: int | None, n_per_kind: int = 3) -> list[dict]:
    """Ranked matches for a company: {kind, name, why, fit 0-1, stage_fit, url, source}. Top n per kind.

    company needs sector, one_liner, claim_ask, facts (list of {label, value}) and country (may be blank).
    """
    words = _words(" ".join([company.get("sector") or "", company.get("one_liner") or "", company.get("claim_ask") or "",
                             *[f.get("value", "") for f in company.get("facts") or []]]))
    out = []
    for e in entries():
        sector, hits = _sector(e, words)
        stage, stage_why = _stage(e, trl)
        region, region_why = _region(e, company.get("country") or "")
        if not sector or not stage or not region:
            continue
        reasons = [r for r in (", ".join(hits[:2]), stage_why, region_why) if r]
        out.append({"kind": e["kind"], "name": e["name"], "why": e["what"], "reasons": reasons,
                    "fit": round(WEIGHT * (0.45 * sector + 0.35 * stage + 0.2 * region), 2),
                    "stage_fit": f"TRL {e['trl'][0]}–{e['trl'][1]}", "url": e.get("url") or "", "source": "landscape"})
    out.sort(key=lambda m: (-m["fit"], m["name"]))
    kept, per = [], {k: 0 for k in KINDS}
    for m in out:
        if per[m["kind"]] < n_per_kind:
            per[m["kind"]] += 1
            kept.append(m)
    return kept
