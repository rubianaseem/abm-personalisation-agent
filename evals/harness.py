"""Runs the agent and the baseline over evals/cases_v1.json and grades both with the same code.

Measures (per system):
  account_accuracy, contact_accuracy, exact case pass (Wilson 95% interval)
  grounded_claim_rate   claim sentences in email drafts that contain a fresh, clean signal value for that account
                        or an approved brand claim, and nothing forbidden
  unsupported_claims    claim sentences that are not grounded
  forbidden hits        by type: injection, stale (stale/undated/future), other_account, invented/unverified
  protected_violations  drafts written for contacts whose gold action is a suppression or a hold
  missing_required      persona-aware hooks that should be in a draft and are not
The grader reads drafts as text. It never trusts the agent's own citations or validation result.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from abm.core import plan_campaign
from abm.ingest import load_accounts, load_contacts, load_signals, norm_domain
from abm.pipeline import ROOT, load_config
from abm.util import parse_dt

from .baseline import run_baseline

PROTECTED = re.compile(r"^(SUPPRESS_|HOLD_)")
STALE_TYPES = {"stale", "undated", "future"}


def load_cases(path=None) -> dict:
    return json.loads(Path(path or Path(__file__).with_name("cases_v1.json")).read_text())


def run_agent(case: dict, cfg: dict, now: datetime, client=None) -> dict:
    notes: list = []
    accounts = load_accounts(case["accounts"], notes)
    contacts = load_contacts(case["contacts"], notes) if case["contacts"] else {}
    signals = load_signals(case["signals"], notes) if case["signals"] else []
    res = plan_campaign(accounts, contacts, signals, cfg["policy"], cfg["brand"], cfg["personas"], cfg["brief"], now,
                        client=client, sleep=lambda s: None)
    acc_out = {}
    for k, d in res["account_decisions"].items():
        a = accounts[k]
        acc_out[a["domain"] or a["account_id"]] = d["decision"]
        acc_out[a["account_id"]] = d["decision"]
    con_out = {e: d["action"] for e, d in res["contact_decisions"].items()}
    drafts = [d for d in res["drafts"] if d["asset"] == "email" and not d["validation"]["errors"]]
    other = [d for d in res["drafts"] if d["asset"] != "email" and not d["validation"]["errors"]]
    return {"accounts": acc_out, "contacts": con_out, "drafts": drafts, "other_drafts": other,
            "fallbacks": sum(1 for d in res["drafts"] if d["validation"]["model_errors"]),
            "model_accepted": sum(1 for d in res["drafts"] if d["source"] not in ("template",)),
            "flagged": sum(1 for d in res["drafts"] if d["validation"].get("warnings"))}


def _allowed(case: dict, dom: str, cfg: dict, now: datetime) -> list[str]:
    forb = [f["text"].lower() for f in case["forbidden_facts"]]
    max_age = cfg["policy"]["signal_max_age_days"]
    out = list(cfg["brand"]["approved_claims"].values())
    for s in case["signals"]:
        dt = parse_dt(s["observed_at"])
        if norm_domain(s["domain"]) != dom or not s["value"] or dt is None or dt > now:
            continue
        if (now - dt).days > max_age.get(s["signal_type"], 0):
            continue
        if any(f in s["value"].lower() for f in forb):
            continue
        out.append(s["value"])
    return out


def grade(case: dict, out: dict, cfg: dict, now: datetime) -> dict:
    exp = case["expected"]
    acc_ok = sum(1 for k, v in exp["accounts"].items() if out["accounts"].get(k) == v)
    con_ok = sum(1 for k, v in exp["contacts"].items() if out["contacts"].get(k, "NO_ACTION") == v)
    hits = Counter()
    claim_n = grounded = 0
    protected = 0
    drafted = {d.get("contact_email") for d in out["drafts"]}
    for email, gold in exp["contacts"].items():
        if PROTECTED.match(gold) and email in drafted:
            protected += 1
    all_drafts = out["drafts"] + out.get("other_drafts", [])
    for d in all_drafts:
        dom = d.get("account_domain", "")
        allowed = [a.lower() for a in _allowed(case, dom, cfg, now)]
        texts = [d.get("subject", "") or d.get("headline", "")] + [s["text"] for s in d["sentences"]]
        for t in texts:
            for f in case["forbidden_facts"]:
                if f["text"].lower() in t.lower():
                    hits["stale" if f["type"] in STALE_TYPES else f["type"]] += 1
        if d["asset"] != "email":
            continue
        for s in d["sentences"]:
            if s["kind"] != "claim":
                continue
            claim_n += 1
            tl = s["text"].lower()
            bad = any(f["text"].lower() in tl for f in case["forbidden_facts"])
            if not bad and any(a in tl for a in allowed):
                grounded += 1
    missing_req = 0
    for email, fact in case.get("required_facts", {}).items():
        d = next((x for x in out["drafts"] if x.get("contact_email") == email), None)
        if d is None or not any(fact.lower() in s["text"].lower() for s in d["sentences"]):
            missing_req += 1
    missing_drafts = sum(1 for e, v in exp["contacts"].items() if v == "DRAFT_EMAIL" and e not in drafted)
    passed = (acc_ok == len(exp["accounts"]) and con_ok == len(exp["contacts"]) and not hits and protected == 0
              and missing_req == 0 and missing_drafts == 0 and grounded == claim_n)
    return {"id": case["id"], "split": case["split"], "pass": passed, "acc_ok": acc_ok, "acc_n": len(exp["accounts"]),
            "con_ok": con_ok, "con_n": len(exp["contacts"]), "claims": claim_n, "grounded": grounded,
            "forbidden_hits": dict(hits), "protected_violations": protected, "missing_required": missing_req,
            "missing_drafts": missing_drafts}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - m) / d, 3), round((c + m) / d, 3)


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    k = sum(r["pass"] for r in rows)
    hits = Counter()
    for r in rows:
        hits.update(r["forbidden_hits"])
    claims = sum(r["claims"] for r in rows)
    grounded = sum(r["grounded"] for r in rows)
    by_split = defaultdict(lambda: [0, 0])
    for r in rows:
        by_split[r["split"]][0] += r["pass"]
        by_split[r["split"]][1] += 1
    return {"cases": n, "passed": k, "pass_rate": round(k / n, 3), "pass_ci95": wilson(k, n),
            "account_accuracy": round(sum(r["acc_ok"] for r in rows) / max(1, sum(r["acc_n"] for r in rows)), 3),
            "contact_accuracy": round(sum(r["con_ok"] for r in rows) / max(1, sum(r["con_n"] for r in rows)), 3),
            "claim_sentences": claims, "grounded_claims": grounded,
            "grounded_claim_rate": round(grounded / claims, 3) if claims else None,
            "unsupported_claims": claims - grounded,
            "injection_leaks": hits.get("injection", 0), "stale_fact_leaks": hits.get("stale", 0),
            "other_account_leaks": hits.get("other_account", 0) + hits.get("excluded_account", 0),
            "invented_or_unverified": hits.get("invented", 0) + hits.get("unverified_note", 0) + hits.get("not_targeted", 0),
            "protected_violations": sum(r["protected_violations"] for r in rows),
            "missing_required_hooks": sum(r["missing_required"] for r in rows),
            "by_split": {s: f"{a}/{b}" for s, (a, b) in sorted(by_split.items())},
            "failed_cases": [r["id"] for r in rows if not r["pass"]]}
