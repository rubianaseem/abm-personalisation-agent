"""The in-memory pipeline. Pure apart from the optional model client, so evals and tests call it directly.

accounts + contacts + signals -> evidence packs -> tiers -> contact decisions -> drafts (validated) -> results.
`trace` receives one record per decision (see pipeline.py for the hash-chained file).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .contacts import apply_caps, decide_contact
from .drafting import draft_email, template_ad, template_landing
from .evidence import build_pack
from .tiering import TARGET_DECISIONS, apply_tier1_cap, decide
from .untrusted import screen
from .validate import validate_draft


def _ctx(account, contact, pack, accounts, contacts, brand, personas, brief, quarantined_texts):
    cta = personas["stage_cta"][account["journey_stage"]]
    fn = contact["first_name"] if contact else ""
    others = sorted({a["company_name"] for a in accounts.values() if a["company_name"] and a["domain"] != account["domain"]
                     and a["company_name"].lower() not in account["company_name"].lower()})
    people = sorted({f"{c['first_name']} {c['last_name']}" for c in contacts.values()
                     if c["first_name"] and c["last_name"] and (contact is None or c["email"] != contact["email"])})
    return {"brand": brand, "evidence": pack["items"], "claims": brand["approved_claims"],
            "company_name": account["company_name"], "first_name": fn, "industry_label": account["industry"],
            "allowed_greetings": {f"Hi {fn}," if fn else "Hello,"}, "cta_text": f"{cta['text']} {cta['url']}",
            "signoff": f"{brief['sender_name']}, {brief['sender_company']}", "other_company_names": others,
            "other_person_names": people, "quarantined_texts": quarantined_texts}


def plan_campaign(accounts: dict, contacts: dict, signals: list, policy: dict, brand: dict, personas: dict, brief: dict,
                  now: datetime, client=None, trace=None, sleep=None) -> dict:
    trace = trace or (lambda rec: None)
    by_domain = defaultdict(list)
    for s in signals:
        by_domain[s["domain"]].append(s)
    known_domains = {a["domain"] for a in accounts.values() if a["domain"]}
    orphans = [s["signal_id"] for s in signals if s["domain"] not in known_domains]
    for sid in orphans:
        trace({"step": "signal", "subject": sid, "decision": "ORPHAN_SIGNAL", "reasons": ["NO_MATCHING_ACCOUNT"]})

    # quarantined free text across ALL signals, used by the leak check on every draft
    quarantined_texts = [t for s in signals for t in (s["value"], s["text"]) if screen(t)["status"] == "quarantined"]

    packs, acc_dec = {}, {}
    customer_domains = {a["domain"] for a in accounts.values() if a["relationship"] == "customer" and a["domain"]}
    for key, acc in sorted(accounts.items()):
        packs[key] = build_pack(acc, by_domain.get(acc["domain"], []) if acc["domain"] else [], policy, now)
        acc_dec[key] = decide(acc, packs[key], policy, customer_domains)
    apply_tier1_cap(acc_dec, policy)
    for key in sorted(accounts):
        p = packs[key]
        trace({"step": "evidence", "subject": accounts[key]["domain"] or key, "decision": f"USABLE_{len(p['items'])}",
               "reasons": sorted({e["reason"] for e in p["excluded"]}), "evidence_ids": [i["id"] for i in p["items"]],
               "excluded": [{"signal_id": e["signal_id"], "reason": e["reason"]} for e in p["excluded"]]})
        trace({"step": "tier", "subject": accounts[key]["domain"] or key, "decision": acc_dec[key]["decision"],
               "reasons": acc_dec[key]["reasons"], "fit": acc_dec[key]["fit"], "intent": acc_dec[key]["intent"]})

    dom_to_key = {a["domain"]: k for k, a in accounts.items() if a["domain"]}
    contact_dec: dict[str, dict] = {}
    per_account = defaultdict(list)
    for email, c in sorted(contacts.items()):
        key = dom_to_key.get(c["company_domain"])
        acc = accounts.get(key) if key else None
        d = decide_contact(c, acc, acc_dec[key]["decision"] if key else None, policy, personas)
        d["account_key"] = key
        contact_dec[email] = d
        if key:
            per_account[key].append(d)
    for key, ds in per_account.items():
        apply_caps(ds, acc_dec[key]["decision"], policy, personas)
    for email, d in sorted(contact_dec.items()):
        trace({"step": "contact", "subject_email": email, "decision": d["action"], "reasons": [d["reason"]],
               "persona": d["persona"], "account": accounts[d["account_key"]]["domain"] if d["account_key"] else ""})

    drafts: list[dict] = []
    for email, d in sorted(contact_dec.items()):
        if d["action"] != "DRAFT_EMAIL":
            continue
        key = d["account_key"]
        acc, c, pack = accounts[key], contacts[email], packs[key]
        ctx = _ctx(acc, c, pack, accounts, contacts, brand, personas, brief, quarantined_texts)
        dr = draft_email(acc, c, d["persona"], pack["items"], brand, personas, brief, ctx, client=client,
                         log=lambda r, e=email: trace({"step": "model", "subject_email": e, "decision": r.get("event"),
                                                       "reasons": [r.get("error", "")]}), sleep=sleep)
        dr.update({"draft_id": f"email:{acc['domain']}:{c['contact_id']}", "account_domain": acc["domain"],
                   "contact_id": c["contact_id"], "contact_email": email, "tier": acc_dec[key]["decision"]})
        drafts.append(dr)
        trace({"step": "draft", "subject_email": email, "decision": "DRAFT_OK" if not dr["validation"]["errors"] else "DRAFT_REVIEW",
               "reasons": dr["validation"]["errors"] + [f"model:{x}" for x in dr["validation"]["model_errors"]],
               "source": dr["source"], "cites": sorted({ci for s in dr["sentences"] for ci in s.get("cites", [])})})

    clusters = defaultdict(list)
    for key in sorted(accounts):
        acc, dec = accounts[key], acc_dec[key]["decision"]
        if dec == "TIER_1":
            ctx = _ctx(acc, None, packs[key], accounts, contacts, brand, personas, brief, quarantined_texts)
            for maker, kind in ((lambda: template_ad(acc["company_name"], "C2", brand), "ad"),
                                (lambda: template_landing(acc, packs[key]["items"], brand), "landing")):
                dr = maker()
                dr["validation"] = {"errors": validate_draft(dr, ctx), "model_errors": [], "warnings": []}
                dr.update({"draft_id": f"{kind}:{acc['domain']}", "account_domain": acc["domain"], "contact_id": "",
                           "contact_email": "", "tier": dec})
                drafts.append(dr)
        elif dec == "TIER_2":
            clusters[acc["industry"] or "other"].append(key)
    for industry, keys in sorted(clusters.items()):
        label = {"saas": "SaaS", "other": "B2B", "information technology": "IT"}.get(industry, industry.title())
        first = accounts[keys[0]]
        ctx = _ctx({**first, "company_name": label, "domain": ""}, None, {"items": []}, accounts, contacts, brand,
                   personas, brief, quarantined_texts)
        ctx["other_company_names"] = []  # cluster ads name no account
        dr = template_ad(label, "C1", brand)
        dr["validation"] = {"errors": validate_draft(dr, ctx), "model_errors": [], "warnings": []}
        dr["personalisation"] = "industry_cluster"
        dr.update({"draft_id": f"ad:cluster:{industry}", "account_domain": "", "contact_id": "", "contact_email": "",
                   "tier": "TIER_2", "cluster_domains": [accounts[k]["domain"] for k in keys]})
        drafts.append(dr)

    return {"accounts": accounts, "account_decisions": acc_dec, "packs": packs, "contacts": contacts,
            "contact_decisions": contact_dec, "drafts": drafts, "orphan_signals": orphans,
            "quarantined_count": sum(p["quarantined"] for p in packs.values())}
