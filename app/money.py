"""Money in card text, in euros: "$8M Series B" reads "€7.2M Series B". No model call, just a pattern and fixed rates
(crawler.profile.EUR_PER), applied when a card is written or filled and once over the stored cards on startup.

Only amounts with a clear currency are converted (a symbol like $ or £, or a code like USD or SEK next to the
number); euro amounts and bare numbers are left as they are, so running it twice changes nothing.
"""
import json
import re

from .crawler.profile import EUR_PER
from .db import dumps

# Prefix symbols and their currency. Longer ones first so "US$" isn't read as "$".
SYMBOLS = {"US$": "USD", "USD$": "USD", "CA$": "CAD", "C$": "CAD", "AU$": "AUD", "A$": "AUD", "S$": "SGD",
           "$": "USD", "£": "GBP", "¥": "JPY", "₪": "ILS"}
CODES = sorted((c for c in EUR_PER if c != "EUR"), key=len, reverse=True)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6, "millions": 1e6,
         "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9}

_NUM = r"(?P<num>\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
_SCALE = r"(?:\s?(?P<scale>thousand|millions?|billions?|mn|mm|bn|[kKmMbB])\b)?"
_SYM = "|".join(re.escape(s) for s in sorted(SYMBOLS, key=len, reverse=True))
_CODE = "|".join(CODES)
# $8M · US$ 1.5 million · USD 8M · SEK 50M · 8M USD · 50 million SEK · 50 MSEK
PATTERN = re.compile(
    rf"(?:(?P<sym>{_SYM})\s?|\b(?P<pre>{_CODE})\s?){_NUM}{_SCALE}"
    rf"|\b{_NUM.replace('num', 'num2')}{_SCALE.replace('scale', 'scale2')}\s?(?P<post>{_CODE})\b"
    rf"|\b{_NUM.replace('num', 'num3')}\s?(?P<mcode>M)(?P<mcur>{_CODE})\b")


def short(eur: float) -> str:
    """€650k, €1.2M, €3B: the same style as the cards' own euro figures."""
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if eur >= size:
            v = round(eur / size, 1 if size > 1e3 else 0)
            return f"€{v:g}{unit}"
    return f"€{round(eur):,}"


def _number(text: str) -> float | None:
    text = text.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", text):
        text = text.replace(",", "")
    elif re.fullmatch(r"\d+,\d+", text):
        text = text.replace(",", ".")  # 1,5M: a decimal comma
    try:
        return float(text)
    except ValueError:
        return None


def _convert(m: re.Match) -> str:
    g = m.groupdict()
    if g["num3"]:
        num, scale, cur = g["num3"], "m", g["mcur"]
    elif g["num2"]:
        num, scale, cur = g["num2"], g["scale2"], g["post"]
    else:
        num, scale, cur = g["num"], g["scale"], SYMBOLS.get(g["sym"]) if g["sym"] else g["pre"]
    amount, rate = _number(num), EUR_PER.get((cur or "").upper())
    if amount is None or not rate:
        return m.group(0)
    return short(amount * SCALE.get((scale or "").lower(), 1) * rate)


def in_euros(text: str | None) -> str | None:
    """The text with every foreign-currency amount written in euros."""
    return PATTERN.sub(_convert, text) if text else text


def card(c: dict) -> dict:
    """A written card (one_liner, claim_ask, facts) with its amounts in euros."""
    out = dict(c)
    for key in ("one_liner", "claim_ask"):
        if out.get(key):
            out[key] = in_euros(out[key])
    if out.get("facts"):
        out["facts"] = [f | {"value": in_euros(f.get("value", ""))} for f in out["facts"]]
    return out


def tidy(db) -> int:
    """Every stored card and find in euros. Returns how many rows changed; a second run changes none."""
    changed = 0
    for row in db.execute("SELECT id, one_liner, claim_ask, facts, vision FROM companies").fetchall():
        facts = json.loads(row["facts"] or "[]") if row["facts"] else []
        new = {"one_liner": in_euros(row["one_liner"]), "claim_ask": in_euros(row["claim_ask"]),
               "vision": in_euros(row["vision"]),
               "facts": dumps([f | {"value": in_euros(f.get("value", ""))} for f in facts])
               if facts else row["facts"]}
        if any(new[k] != row[k] for k in new):
            db.execute("UPDATE companies SET one_liner = ?, claim_ask = ?, vision = ?, facts = ? WHERE id = ?",
                       (new["one_liner"], new["claim_ask"], new["vision"], new["facts"], row["id"]))
            changed += 1
    for row in db.execute("SELECT id, card FROM candidates WHERE card IS NOT NULL").fetchall():
        try:
            old = json.loads(row["card"])
        except ValueError:
            continue
        new = card(old)
        if new != old:
            db.execute("UPDATE candidates SET card = ? WHERE id = ?", (dumps(new), row["id"]))
            changed += 1
    db.commit()
    return changed
