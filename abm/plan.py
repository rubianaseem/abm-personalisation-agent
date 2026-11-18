"""Turn decisions and drafts into the reviewable campaign plan and the review queue.

Everything in the plan is a PROPOSAL for a person to carry out in their own tools: static lists, a suppression
list, sequence assignments, ad company lists and landing-page heroes. Contact ids only, no emails.
"""
from __future__ import annotations

from collections import defaultdict

from .contacts import HOLD, REVIEW, SUPPRESS
from .util import canonical_json, sha256_bytes

TIER_LABEL = {"TIER_1": "Tier 1 (1:1)", "TIER_2": "Tier 2 (1:few)", "TIER_3": "Tier 3 (1:many)"}


def draft_hash(d: dict) -> str:
    keep = {k: d.get(k) for k in ("draft_id", "asset", "subject", "headline", "sentences")}
    return sha256_bytes(canonical_json(keep).encode())


def build_plan(res: dict, brief: dict, policy: dict, run_id: str) -> dict:
    accs, adec, cdec = res["accounts"], res["account_decisions"], res["contact_decisions"]
    prefix = brief["hubspot_list_prefix"]
    lists = defaultdict(list)
    suppress, seqs = [], []
    drafts_ok = {d["draft_id"]: d for d in res["drafts"] if not d["validation"]["errors"]}
    for email, d in sorted(cdec.items()):
        cid = res["contacts"][email]["contact_id"]
        tier = adec[d["account_key"]]["decision"] if d["account_key"] else ""
        if d["action"] in SUPPRESS:
            suppress.append(cid)
        elif d["action"] == "ADD_TO_PROGRAM_LIST":
            lists[f"{prefix} {TIER_LABEL['TIER_3']} program"].append(cid)
        elif d["action"] == "DRAFT_EMAIL":
            did = f"email:{accs[d['account_key']]['domain']}:{cid}"
            if did in drafts_ok:
                lists[f"{prefix} {TIER_LABEL[tier]}"].append(cid)
                seqs.append({"contact_id": cid, "sequence": brief["sequence_names"][tier], "draft_id": did,
                             "draft_sha256": draft_hash(drafts_ok[did]), "enrolled_by": "account owner, manually"})
    by_dec = defaultdict(list)
    for key, d in sorted(adec.items()):
        by_dec[d["decision"]].append(accs[key]["domain"] or accs[key]["account_id"])
    return {
        "schema": "abm_campaign_plan.v1", "run_id": run_id, "campaign_id": brief["campaign_id"],
        "policy_version": policy["policy_version"], "status": "proposed", "writes_performed": False,
        "accounts": [{"domain": accs[k]["domain"], "account_id": accs[k]["account_id"], "company_name": accs[k]["company_name"],
                      "decision": d["decision"], "fit": d["fit"], "intent": d["intent"], "reasons": d["reasons"],
                      "evidence_ids": [i["id"] for i in res["packs"][k]["items"]],
                      "filled_fields": accs[k].get("filled_fields", {})} for k, d in sorted(adec.items())],
        "proposed_hubspot_static_lists": [{"name": n, "contact_ids": ids} for n, ids in sorted(lists.items())],
        "proposed_suppression_list": {"name": f"{prefix} Suppressed - exclude from all sends", "contact_ids": suppress},
        "proposed_sequence_assignments": seqs,
        "proposed_ad_company_lists": {
            "tier1_domains": by_dec.get("TIER_1", []), "tier2_domains": by_dec.get("TIER_2", []),
            "tier3_domains": by_dec.get("TIER_3", []),
            "exclude_domains": sorted(by_dec.get("EXCLUDE_COMPETITOR", []) + by_dec.get("EXCLUDE_CUSTOMER", [])
                                      + by_dec.get("HOLD_OPEN_DEAL", []))},
        "proposed_landing_pages": [d["draft_id"] for d in res["drafts"] if d["asset"] == "landing" and d["draft_id"] in drafts_ok],
        "draft_hashes": {d["draft_id"]: draft_hash(d) for d in res["drafts"]},
    }


def review_rows(res: dict, data_notes: list[dict]) -> list[dict]:
    rows = []
    accs = res["accounts"]
    for key, d in sorted(res["account_decisions"].items()):
        if d["decision"].startswith(("REVIEW", "HOLD", "EXCLUDE")):
            rows.append({"item_type": "account", "ref": accs[key]["domain"] or accs[key]["account_id"], "decision": d["decision"],
                         "reason": ";".join(d["reasons"]), "suggested_action": {
                             "EXCLUDE_COMPETITOR": "Confirm competitor flag; keep out of all ABM lists",
                             "EXCLUDE_CUSTOMER": "Route to account manager or expansion play, not new-logo ABM",
                             "HOLD_OPEN_DEAL": "Ask the deal owner whether marketing air cover helps",
                             "REVIEW_DATA": "Fix domain or company name in the CRM and re-export",
                             "REVIEW_PARTNER": "Check with partnerships before targeting"}.get(d["decision"], "Review")})
        pack = res["packs"][key]
        for e in pack["excluded"]:
            if e["reason"] in {"QUARANTINED_INJECTION", "UNDATED", "FUTURE_DATED"}:
                rows.append({"item_type": "signal", "ref": e["signal_id"], "decision": e["reason"], "reason": e["signal_type"],
                             "suggested_action": "Quarantined text is not shown here; open the source row and clean it"
                             if e["reason"] == "QUARANTINED_INJECTION" else "Add a reliable observed_at date or drop the signal"})
    for email, d in sorted(res["contact_decisions"].items()):
        if d["action"] in REVIEW or d["action"] in HOLD - {"HOLD_OPEN_DEAL", "HOLD_ACCOUNT_REVIEW"}:
            rows.append({"item_type": "contact", "ref": res["contacts"][email]["contact_id"], "decision": d["action"],
                         "reason": d["reason"], "suggested_action": "Fix in CRM or decide manually; no draft was written"})
    for dr in res["drafts"]:
        v = dr["validation"]
        if v["errors"] or v["model_errors"] or v.get("warnings"):
            rows.append({"item_type": "draft", "ref": dr["draft_id"],
                         "decision": "DRAFT_BLOCKED" if v["errors"] else "MODEL_FALLBACK" if v["model_errors"] else "READ_CLOSELY",
                         "reason": ";".join(v["errors"] + [f"model:{x}" for x in v["model_errors"]] + v.get("warnings", [])),
                         "suggested_action": "Rewrite by hand; draft excluded from plan" if v["errors"] else
                         "Template draft used; check wording" if v["model_errors"] else
                         "Model added words beyond the quoted evidence; check every reason it gives"})
    for n in data_notes:
        rows.append({"item_type": "data_quality", "ref": n["subject"], "decision": "NOTE", "reason": n["note"], "suggested_action": "Fix at source"})
    return rows
