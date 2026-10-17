"""A short, fact-dense brief of a startup, written once by the cheap model for the expensive reviewers.

The reviews (Claude, GPT and Grok rating a card) are the costly calls. Instead of each reading the whole profile
(a vision of up to 400 words, every stage and investor), they read this brief: about 100 words written by
OPENROUTER_MODEL that keeps every fact a rating rests on (what it does, for whom, stage and proof, money, backers,
team, competition) and drops the rest. It's kept on the company and rewritten only when the profile or evidence
behind it changes, so asking the reviewers again costs no extra brief.

Without a key, or if writing it fails, the reviewers read the full profile as before.
"""
import hashlib
import json

from . import reads
from .crawler import pitch
from .db import j

BRIEF_WORDS = 110

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["brief"],
          "properties": {"brief": {"type": "string"}}}

SYSTEM = f"""Condense a startup's profile into a brief for investment analysts who will rate it. At most \
{BRIEF_WORDS} words, plain sentences or short clauses, no headings or lists.
Keep every fact a rating would rest on, with its numbers: what it does and for whom, the problem and its scale,
stage and proof (pilots, customers, revenue, trials), money raised and from whom, the ask, team, competition or edge,
and where it's based. Drop slogans, adjectives and repetition. Use only what the profile says; never add facts or
opinions."""


def source_text(comp) -> str:
    """Everything the brief is written from: the profile the reviewers would otherwise read, and the evidence
    factors with their basis."""
    evidence = j(comp["evidence"], {}) or {}
    parts = [reads.profile_text(comp)]
    if evidence:
        parts.append("Evidence scores (0-5, from public sources): " + json.dumps(evidence, sort_keys=True))
    facts = j(comp["facts"], []) or []
    if facts:
        parts.append("Facts: " + "; ".join(f"{f.get('label')}: {f.get('value')}" for f in facts))
    return "\n".join(parts)


def fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def for_review(db, comp) -> str:
    """What the reviewers read about a company: its brief (written now if the profile changed since the last one),
    or the full profile when no brief can be written."""
    source = source_text(comp)
    key = fingerprint(source)
    if comp["brief"] and comp["brief_key"] == key:
        return comp["brief"]
    if not pitch.available():
        return reads.profile_text(comp)
    try:
        raw = pitch._post("brief", SCHEMA, [{"role": "system", "content": SYSTEM},
                                            {"role": "user", "content": source}], task="brief")
        brief = " ".join((raw.get("brief") or "").split())
    except Exception:  # noqa: BLE001 - the reviewers just read the full profile instead
        return reads.profile_text(comp)
    words = brief.split()
    if not words:
        return reads.profile_text(comp)
    if len(words) > BRIEF_WORDS * 1.3:
        brief = " ".join(words[:int(BRIEF_WORDS * 1.3)]) + "…"
    brief = f"Name: {comp['name']}\n{brief}"
    db.execute("UPDATE companies SET brief = ?, brief_key = ? WHERE id = ?", (brief, key, comp["id"]))
    db.commit()
    return brief
