"""The baseline: a plain mail-merge script, the way many ABM sends are built today.

- Tier by employee count only (>=1000 tier 1, >=200 tier 2, else tier 3). No competitor, customer, open-deal or
  partner checks.
- Every contact with an email gets a draft unless the email_opt_out column is ticked (it does honour that).
  No dedupe, no notes, no bounce, no lawful-basis or persona checks.
- The hook is "I saw {latest signal}" using the newest signal for the account's domain, value or free text,
  whatever its age. Then the C1 claim, the stage call to action and the sign-off.
It is deterministic and uses the same draft format, so the same grader scores both.
"""
from __future__ import annotations

import re

from abm.util import parse_dt, truthy


def run_baseline(case: dict, brand: dict, personas: dict, brief: dict) -> dict:
    accs = {}
    for a in case["accounts"]:
        key = a["domain"].strip().lower() or a["account_id"]
        digits = re.sub(r"\D", "", a.get("employees", ""))
        emp = int(digits) if digits else 0
        accs[key] = {"name": a["company_name"], "stage": (a.get("journey_stage") or "aware").lower(),
                     "decision": "TIER_1" if emp >= 1000 else "TIER_2" if emp >= 200 else "TIER_3"}
    sigs = {}
    for s in case["signals"]:
        dt = parse_dt(s["observed_at"])
        if dt is None:
            continue
        dom = s["domain"].strip().lower()
        if dom not in sigs or dt > sigs[dom][0]:
            sigs[dom] = (dt, s["text"] or s["value"])
    contacts, drafts = {}, []
    for c in case["contacts"]:
        email = c["email"].strip().lower()
        if truthy(c.get("email_opt_out")):
            contacts.setdefault(email, "SUPPRESS_OPT_OUT")
            continue
        contacts[email] = "DRAFT_EMAIL"
        dom = c["company_domain"].strip().lower()
        a = accs.get(dom, {"name": "", "stage": "aware"})
        stage = a["stage"] if a["stage"] in personas["stage_cta"] else "aware"
        cta = personas["stage_cta"][stage]
        sents = [{"kind": "greeting", "text": f"Hi {c['first_name']},", "cites": []}]
        if dom in sigs:
            sents.append({"kind": "claim", "text": f"I saw {sigs[dom][1]}", "cites": []})
        sents += [{"kind": "claim", "text": brand["approved_claims"]["C1"], "cites": ["C1"]},
                  {"kind": "cta", "text": f"{cta['text']} {cta['url']}", "cites": []},
                  {"kind": "signoff", "text": f"{brief['sender_name']}, {brief['sender_company']}", "cites": []}]
        drafts.append({"asset": "email", "contact_email": email, "account_domain": dom, "sentences": sents,
                       "subject": f"{a['name']}: quick idea", "source": "baseline"})
    return {"accounts": {k: v["decision"] for k, v in accs.items()}, "contacts": contacts, "drafts": drafts}
