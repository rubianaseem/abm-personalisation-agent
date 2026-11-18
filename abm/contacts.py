"""Per-contact decisions for the buying committee. Deterministic, ordered, one reason code each.

Contact-level suppression runs first (it is the most specific and the most restrictive), then the account's
decision is inherited, then data checks, then the per-account cap. A model never decides who is contacted.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SUPPRESS = {"SUPPRESS_OPT_OUT", "SUPPRESS_BOUNCED", "SUPPRESS_NOTE_OPTOUT", "SUPPRESS_COMPETITOR", "SUPPRESS_CUSTOMER"}
HOLD = {"HOLD_OPEN_DEAL", "HOLD_ACCOUNT_REVIEW", "HOLD_BASIS_UNKNOWN", "HOLD_CAP"}
REVIEW = {"REVIEW_DATA", "REVIEW_PERSONAL_EMAIL", "REVIEW_DOMAIN_MISMATCH", "REVIEW_PERSONA", "REVIEW_NO_ACCOUNT"}
ACT = {"DRAFT_EMAIL", "ADD_TO_PROGRAM_LIST"}
NO_DRAFT = SUPPRESS | HOLD | REVIEW | {"NO_ACTION", "ADD_TO_PROGRAM_LIST"}


def load_personas(path: str | Path) -> dict:
    p = json.loads(Path(path).read_text())
    p["_compiled"] = [(r["persona"], [re.compile(x, re.I) for x in r["patterns"]]) for r in p["rules"]]
    return p


def persona_for(title: str, personas: dict) -> str | None:
    for persona, pats in personas["_compiled"]:
        if any(p.search(title or "") for p in pats):
            return persona
    return None


def decide_contact(c: dict, account: dict | None, acc_decision: str | None, policy: dict, personas: dict) -> dict:
    persona = persona_for(c["job_title"], personas)
    base = {"contact_id": c["contact_id"], "persona": persona}
    notes_l = c["notes"].lower()
    if not c["email_valid"]:
        return {**base, "action": "REVIEW_DATA", "reason": "INVALID_OR_MISSING_EMAIL"}
    if c["email_opt_out"]:
        return {**base, "action": "SUPPRESS_OPT_OUT", "reason": "EMAIL_OPT_OUT_FLAG"}
    if c["hard_bounced"]:
        return {**base, "action": "SUPPRESS_BOUNCED", "reason": "HARD_BOUNCE"}
    hit = next((p for p in policy["note_optout_phrases"] if p in notes_l), None)
    if hit:
        return {**base, "action": "SUPPRESS_NOTE_OPTOUT", "reason": f"NOTE_PHRASE:{hit}"}
    if account is None:
        return {**base, "action": "REVIEW_NO_ACCOUNT", "reason": "NO_MATCHING_TARGET_ACCOUNT"}
    inherit = {"EXCLUDE_COMPETITOR": "SUPPRESS_COMPETITOR", "EXCLUDE_CUSTOMER": "SUPPRESS_CUSTOMER",
               "HOLD_OPEN_DEAL": "HOLD_OPEN_DEAL", "REVIEW_DATA": "HOLD_ACCOUNT_REVIEW",
               "REVIEW_PARTNER": "HOLD_ACCOUNT_REVIEW", "NOT_TARGETED": "NO_ACTION"}
    if acc_decision in inherit:
        return {**base, "action": inherit[acc_decision], "reason": f"ACCOUNT_{acc_decision}"}
    edom = c["email"].split("@")[-1]
    if edom in policy["personal_email_domains"]:
        return {**base, "action": "REVIEW_PERSONAL_EMAIL", "reason": "PERSONAL_EMAIL_DOMAIN"}
    adom = account["domain"]
    if edom != adom and not edom.endswith("." + adom):
        return {**base, "action": "REVIEW_DOMAIN_MISMATCH", "reason": f"EMAIL_DOMAIN_NOT_{adom}"}
    if c["lawful_basis"] not in policy["email_lawful_bases_allowed"]:
        return {**base, "action": "HOLD_BASIS_UNKNOWN", "reason": "LAWFUL_BASIS_MISSING_OR_UNKNOWN"}
    if persona is None:
        return {**base, "action": "REVIEW_PERSONA", "reason": "TITLE_NOT_MAPPED"}
    if acc_decision == "TIER_3":
        return {**base, "action": "ADD_TO_PROGRAM_LIST", "reason": "TIER_3_PROGRAM"}
    return {**base, "action": "DRAFT_EMAIL", "reason": f"{acc_decision}_BUYING_COMMITTEE"}


def apply_caps(decisions: list[dict], acc_decision: str, policy: dict, personas: dict) -> None:
    cap = policy["max_contacts_per_account"].get(acc_decision)
    if cap is None:
        return
    drafts = [d for d in decisions if d["action"] == "DRAFT_EMAIL"]
    order = {p: i for i, p in enumerate(personas["priority"])}
    drafts.sort(key=lambda d: (order.get(d["persona"], 99), d["contact_id"]))
    for d in drafts[cap:]:
        d["action"], d["reason"] = "HOLD_CAP", f"ACCOUNT_CAP_{cap}"
