"""Live room: a host-paced state machine stored in a single row.

idle → lobby → open(card n) → locked → revealed (wall only) → open(card n+1) … → final
Phones never see per-card results; they get everything at "final".
"""
import time

from . import config, service


def get_state(db) -> dict:
    st = dict(db.execute("SELECT * FROM live_state WHERE id = 1").fetchone())
    if st["phase"] == "open" and time.time() > (st["phase_started_at"] or 0) + config.LIVE_SECONDS:
        _set(db, phase="locked")
        st = dict(db.execute("SELECT * FROM live_state WHERE id = 1").fetchone())
    return st


def remaining(st: dict) -> int | None:
    if st["phase"] != "open":
        return None
    return max(0, round((st["phase_started_at"] or 0) + config.LIVE_SECONDS - time.time()))


def current_company(db, st: dict):
    if st["dive_id"] is None or st["card_index"] < 0:
        return None
    dive = service.get_dive(db, st["dive_id"])
    if not dive:
        return None
    comps = service.dive_companies(db, dive)
    return comps[st["card_index"]] if st["card_index"] < len(comps) else None


def _set(db, **fields) -> None:
    fields["phase_started_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE live_state SET {cols} WHERE id = 1", list(fields.values()))
    db.commit()


class LiveError(ValueError):
    pass


def act(db, action: str, dive_id: int | None = None) -> dict:
    st = get_state(db)
    if action == "start":
        if not dive_id or not service.get_dive(db, dive_id):
            raise LiveError("Pick a set to start.")
        _set(db, dive_id=dive_id, card_index=-1, phase="lobby")
    elif action == "stop":
        _set(db, dive_id=None, card_index=-1, phase="idle")
    elif st["dive_id"] is None:
        raise LiveError("No live game running. Start one first.")
    elif action == "open":
        _set(db, card_index=max(0, st["card_index"]), phase="open")
    elif action == "lock":
        if st["phase"] != "open":
            raise LiveError("Only an open card can be locked.")
        _set(db, phase="locked")
    elif action == "reveal":
        if st["phase"] not in ("open", "locked"):
            raise LiveError("Open a card before revealing it.")
        _set(db, phase="revealed")
    elif action == "next":
        total = len(service.dive_companies(db, service.get_dive(db, st["dive_id"])))
        nxt = st["card_index"] + 1
        if nxt >= total:
            _set(db, phase="final")
        else:
            _set(db, card_index=nxt, phase="open")
    elif action == "final":
        _set(db, phase="final")
    else:
        raise LiveError(f"Unknown action: {action}")
    return get_state(db)
