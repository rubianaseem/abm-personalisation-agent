"""Evidence pack per account, built from supplied signals only.

Each usable signal becomes an evidence item with an id (E1, E2, ...), the source field it came from, its date
and its age. Drafts may only state account facts that cite one of these ids. A signal is excluded when it is:
  UNDATED / FUTURE_DATED  - no trustworthy date, so freshness can't be shown
  STALE                   - older than signal_max_age_days for its type (a 9-month-old funding round is not news)
  UNKNOWN_TYPE / EMPTY    - nothing we know how to use
  QUARANTINED_INJECTION   - value or text reads like instructions to a model (see untrusted.py)
Free-text types (research notes, website snippets) are usable as model context only after screening, and never
as template hooks: templates use short structured values (funding round, job title posted, tool adopted, news).
"""
from __future__ import annotations

from datetime import datetime

from .untrusted import redact, screen
from .util import iso


def build_pack(account: dict, signals: list[dict], policy: dict, now: datetime) -> dict:
    max_age = policy["signal_max_age_days"]
    hook_types = set(policy["template_hook_types"])
    free_types = set(policy["free_text_types"])
    usable, excluded, quarantined = [], [], 0
    for s in signals:
        reason = None
        st = s["signal_type"]
        if st not in max_age:
            reason = "UNKNOWN_TYPE"
        elif not s["value"] and not s["text"]:
            reason = "EMPTY"
        else:
            scr_v, scr_t = screen(s["value"]), screen(s["text"])
            if scr_v["status"] == "quarantined" or scr_t["status"] == "quarantined":
                reason = "QUARANTINED_INJECTION"
                quarantined += 1
            elif s["observed_at"] is None:
                reason = "UNDATED"
            elif s["observed_at"] > now:
                reason = "FUTURE_DATED"
            elif (now - s["observed_at"]).days > max_age[st]:
                reason = "STALE"
        if reason:
            excluded.append({"signal_id": s["signal_id"], "signal_type": st, "reason": reason})
            continue
        usable.append(s)
    usable.sort(key=lambda s: (-s["observed_at"].timestamp(), s["signal_id"]))
    items = []
    for n, s in enumerate(usable, 1):
        items.append({
            "id": f"E{n}",
            "signal_id": s["signal_id"],
            "signal_type": s["signal_type"],
            "value": redact(s["value"])[:160],
            "text": redact(s["text"])[:400] if s["signal_type"] in free_types else "",
            "observed_at": iso(s["observed_at"]),
            "age_days": (now - s["observed_at"]).days,
            "source_field": s["source_field"],
            "source_url": s["source_url"],
            "template_hook": s["signal_type"] in hook_types and bool(s["value"]),
        })
    return {"domain": account["domain"], "items": items, "excluded": excluded, "quarantined": quarantined}


def intent_points(pack: dict, policy: dict) -> int:
    types = {i["signal_type"] for i in pack["items"] if i["signal_type"] in policy["intent_signal_types"]}
    return min(len(types), policy["intent_points_cap"])
