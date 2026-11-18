"""Deterministic account tiering: exclusions first, then fit + fresh-intent points, then the tier-1 capacity cap.

No model is involved. Order matters: a competitor or customer is never "promoted" by a strong signal, and an
account with an open deal is held for its owner rather than hit by a new-logo campaign.
"""
from __future__ import annotations

from .evidence import intent_points

EXCLUSION_DECISIONS = {"EXCLUDE_COMPETITOR", "EXCLUDE_CUSTOMER", "HOLD_OPEN_DEAL", "REVIEW_DATA", "REVIEW_PARTNER"}
TARGET_DECISIONS = {"TIER_1", "TIER_2", "TIER_3"}


def customer_family(account: dict, customer_domains: set[str]) -> str | None:
    dom, parent = account["domain"], account["parent_domain"]
    if parent and parent in customer_domains:
        return parent
    for cd in customer_domains:
        if dom and dom != cd and dom.endswith("." + cd):
            return cd
    return None


def fit_points(account: dict, policy: dict) -> tuple[int, list[str]]:
    fp, pts, why = policy["fit_points"], 0, []
    if account["industry"] in policy["icp_industries"]:
        pts += fp["icp_industry"]; why.append("FIT_ICP_INDUSTRY")
    emp = account["employees"]
    if emp is not None:
        if 200 <= emp <= 5000:
            pts += fp["employees_200_5000"]; why.append("FIT_SIZE_200_5000")
        elif 50 <= emp < 200:
            pts += fp["employees_50_199"]; why.append("FIT_SIZE_50_199")
        elif emp > 5000:
            pts += fp["employees_over_5000"]; why.append("FIT_SIZE_OVER_5000")
    else:
        why.append("SIZE_UNKNOWN")
    if account["target_list"]:
        pts += fp["named_target_list"]; why.append("FIT_NAMED_TARGET")
    if account["country"] in policy["target_countries"]:
        pts += fp["target_country"]; why.append("FIT_TARGET_COUNTRY")
    return pts, why


def decide(account: dict, pack: dict, policy: dict, customer_domains: set[str]) -> dict:
    reasons: list[str] = []
    closed = {s.lower() for s in policy["open_deal_closed_stages"]}
    if not account["domain"] or not account["company_name"]:
        return {"decision": "REVIEW_DATA", "fit": 0, "intent": 0, "reasons": ["MISSING_DOMAIN_OR_NAME"]}
    if account["relationship"] == "competitor":
        return {"decision": "EXCLUDE_COMPETITOR", "fit": 0, "intent": 0, "reasons": ["RELATIONSHIP_COMPETITOR"]}
    if account["relationship"] == "customer":
        return {"decision": "EXCLUDE_CUSTOMER", "fit": 0, "intent": 0, "reasons": ["RELATIONSHIP_CUSTOMER"]}
    fam = customer_family(account, customer_domains)
    if fam:
        return {"decision": "EXCLUDE_CUSTOMER", "fit": 0, "intent": 0, "reasons": [f"CUSTOMER_FAMILY:{fam}"]}
    if account["open_deal_stage"] and account["open_deal_stage"].lower() not in closed:
        return {"decision": "HOLD_OPEN_DEAL", "fit": 0, "intent": 0, "reasons": ["OPEN_DEAL"]}
    if account["relationship"] == "partner":
        return {"decision": "REVIEW_PARTNER", "fit": 0, "intent": 0, "reasons": ["RELATIONSHIP_PARTNER"]}
    fit, why = fit_points(account, policy)
    intent = intent_points(pack, policy)
    reasons += why + [f"INTENT_{intent}"]
    for tier in ("TIER_1", "TIER_2", "TIER_3"):
        rule = policy["tiers"][tier]
        if fit >= rule["min_fit"] and intent >= rule["min_intent"]:
            return {"decision": tier, "fit": fit, "intent": intent, "reasons": reasons}
    return {"decision": "NOT_TARGETED", "fit": fit, "intent": intent, "reasons": reasons}


def apply_tier1_cap(decisions: dict[str, dict], policy: dict) -> None:
    """1:1 work is expensive. Keep the strongest max_tier1_accounts; demote the rest to TIER_2 with a reason."""
    t1 = [(k, d) for k, d in decisions.items() if d["decision"] == "TIER_1"]
    t1.sort(key=lambda kd: (-(kd[1]["fit"] + kd[1]["intent"]), kd[0]))
    for k, d in t1[policy["max_tier1_accounts"]:]:
        d["decision"] = "TIER_2"
        d["reasons"].append("TIER1_CAPACITY_DEMOTED")
