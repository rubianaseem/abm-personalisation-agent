"""File-level orchestration: read inputs, run core.plan_campaign, write reviewable outputs, bundle and trace.

Outputs (all local files):
  account_decisions.csv  evidence_packs.json  contact_decisions.csv  drafts.json  drafts_review.md
  review_queue.csv  campaign_plan.json  campaign_bundle.json  manifest.json  trace.jsonl  run_summary.md
The bundle holds the SHA-256 of campaign_plan.json, drafts.json, evidence_packs.json and review_queue.csv, so
approving it approves exactly what was reviewed. run_id is derived from the inputs, so the same inputs give the
same plan and the same hashes (idempotent re-runs).
"""
from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import AGENT_VERSION
from .audit import AuditLog
from .contacts import load_personas
from .core import plan_campaign
from .drafting import PROMPT_VERSION
from .ingest import load_all
from .plan import build_plan, review_rows
from .research_mock import fill_missing, load_mock
from .util import canonical_json, iso, parse_dt, pseudonym, sha256_bytes, sha256_file, write_csv

ROOT = Path(__file__).resolve().parent.parent
NS = uuid.UUID("6f1c7a52-3d0e-4d55-9b7e-1a2b3c4d5e6f")
BUNDLE_COMPONENTS = ["campaign_plan.json", "drafts.json", "evidence_packs.json", "review_queue.csv"]


def load_config(config_dir: str | Path) -> dict:
    c = Path(config_dir)
    return {"policy": json.loads((c / "policy.json").read_text()), "brand": json.loads((c / "brand_rules.json").read_text()),
            "personas": load_personas(c / "personas.json"), "brief": json.loads((c / "campaign_brief.json").read_text()),
            "approvers": json.loads((c / "approvers.json").read_text())}


def run(accounts_csv, contacts_csv, signals_csv, out_dir, now: datetime, exported_at: str, config_dir=ROOT / "config",
        client=None, research_mock=None, research_api=None, sleep=None) -> dict:
    cfg = load_config(config_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    accounts, contacts, signals, notes = load_all(accounts_csv, contacts_csv, signals_csv)
    input_hash = sha256_bytes("|".join(sha256_file(p) for p in (accounts_csv, contacts_csv, signals_csv)).encode()
                              + canonical_json(cfg["policy"]).encode() + iso(now).encode())
    run_id = "run_" + input_hash[:12]
    salt = os.environ.get("ABM_TRACE_SALT", "demo-salt-change-me")
    tpath = out / "trace.jsonl"
    if tpath.exists():
        tpath.unlink()  # this run's own trace file is rebuilt; it is regenerated, never edited
    log = AuditLog(tpath, clock=lambda: now)

    def trace(rec: dict):
        rec = dict(rec)
        if "subject_email" in rec:
            rec["subject"] = pseudonym(rec.pop("subject_email"), salt)
        rec.update({"decision_id": str(uuid.uuid5(NS, f"{run_id}|{rec['step']}|{rec['subject']}|{rec.get('decision')}")),
                    "run_id": run_id, "agent_version": AGENT_VERSION, "policy_version": cfg["policy"]["policy_version"],
                    "prompt_version": PROMPT_VERSION if client else None, "model": getattr(client, "name", None)})
        log.append(rec)

    research_stats = None
    if research_mock or research_api:
        api = research_api or load_mock(research_mock)
        research_stats = fill_missing(accounts, api, out / "research_checkpoint.json", sleep=sleep or (lambda s: None),
                                      log=lambda r: trace({"step": "research", "subject": r["domain"], "decision": r["event"],
                                                           "reasons": [r["error"]]}))
    res = plan_campaign(accounts, contacts, signals, cfg["policy"], cfg["brand"], cfg["personas"], cfg["brief"], now,
                        client=client, trace=trace, sleep=sleep)
    plan = build_plan(res, cfg["brief"], cfg["policy"], run_id)

    # files
    write_csv(out / "account_decisions.csv", [
        {"account_id": a["account_id"], "domain": a["domain"], "company_name": a["company_name"], "decision": d["decision"],
         "fit": d["fit"], "intent": d["intent"], "reasons": ";".join(d["reasons"]),
         "usable_evidence": len(res["packs"][k]["items"]), "excluded_signals": len(res["packs"][k]["excluded"])}
        for k, a in sorted(accounts.items()) for d in [res["account_decisions"][k]]],
        ["account_id", "domain", "company_name", "decision", "fit", "intent", "reasons", "usable_evidence", "excluded_signals"])
    (out / "evidence_packs.json").write_text(json.dumps({accounts[k]["domain"] or k: p for k, p in sorted(res["packs"].items())},
                                                        indent=2, sort_keys=True) + "\n")
    write_csv(out / "contact_decisions.csv", [
        {"contact_id": contacts[e]["contact_id"], "account": accounts[d["account_key"]]["domain"] if d["account_key"] else "",
         "persona": d["persona"] or "", "action": d["action"], "reason": d["reason"]}
        for e, d in sorted(res["contact_decisions"].items(), key=lambda kv: contacts[kv[0]]["contact_id"])],
        ["contact_id", "account", "persona", "action", "reason"])
    drafts_out = [{k: v for k, v in d.items() if k != "contact_email"} for d in res["drafts"]]
    (out / "drafts.json").write_text(json.dumps(drafts_out, indent=2, sort_keys=True) + "\n")
    (out / "drafts_review.md").write_text(render_drafts(res["drafts"]))
    rq = review_rows(res, notes)
    write_csv(out / "review_queue.csv", rq, ["item_type", "ref", "decision", "reason", "suggested_action"])
    (out / "campaign_plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    bundle = {"run_id": run_id, "components": {n: sha256_file(out / n) for n in BUNDLE_COMPONENTS}}
    (out / "campaign_bundle.json").write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    exp = parse_dt(exported_at)
    stale = exp is None or (now - exp).total_seconds() / 3600 > cfg["policy"]["snapshot_max_age_hours"]
    manifest = {"run_id": run_id, "as_of": iso(now), "exported_at": exported_at, "stale": stale,
                "stale_reason": "export older than snapshot_max_age_hours or undated" if stale else "",
                "agent_version": AGENT_VERSION, "model": getattr(client, "name", None),
                "artifacts": {"campaign_bundle.json": {"approvable": True, "sha256": sha256_file(out / "campaign_bundle.json")}}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    summary = summarise(res, plan, rq, research_stats, manifest)
    (out / "run_summary.md").write_text(summary["markdown"])
    return {"result": res, "plan": plan, "manifest": manifest, "review_rows": rq, "summary": summary, "out": out}


def render_drafts(drafts: list[dict]) -> str:
    lines = ["# Drafts for review (SYNTHETIC DATA)", "",
             "Citations in brackets point to evidence_packs.json (E ids, per account) or brand_rules.json (C ids).", ""]
    for d in drafts:
        lines.append(f"## {d['draft_id']} ({d['tier']}, {d['source']}, {d['personalisation']})")
        if d.get("subject"):
            lines.append(f"Subject: {d['subject']}")
        if d.get("headline") and d["asset"] != "email":
            lines.append(f"Headline: {d['headline']}")
        for s in d["sentences"]:
            if s["kind"] == "headline":
                continue
            cite = f" [{', '.join(s['cites'])}]" if s.get("cites") else ""
            lines.append(f"- ({s['kind']}) {s['text']}{cite}")
        v = d["validation"]
        lines.append(f"Validation: {'pass' if not v['errors'] else 'BLOCKED ' + ', '.join(v['errors'])}"
                     + (f"; model fallback: {', '.join(v['model_errors'])}" if v["model_errors"] else ""))
        lines.append("")
    return "\n".join(lines)


def summarise(res, plan, rq, research_stats, manifest) -> dict:
    ac = Counter(d["decision"] for d in res["account_decisions"].values())
    cc = Counter(d["action"] for d in res["contact_decisions"].values())
    dr = res["drafts"]
    blocked = sum(1 for d in dr if d["validation"]["errors"])
    fallback = sum(1 for d in dr if d["validation"]["model_errors"])
    signal_level = sum(1 for d in dr if d["asset"] == "email" and d["personalisation"] == "account_signal")
    emails = sum(1 for d in dr if d["asset"] == "email")
    excl = Counter(e["reason"] for p in res["packs"].values() for e in p["excluded"])
    md = ["# Run summary (SYNTHETIC DATA)", "", f"run_id: {manifest['run_id']}  as_of: {manifest['as_of']}  stale snapshot: {manifest['stale']}", "",
          "Accounts: " + ", ".join(f"{k} {v}" for k, v in sorted(ac.items())),
          "Contacts: " + ", ".join(f"{k} {v}" for k, v in sorted(cc.items())),
          "Signals excluded: " + (", ".join(f"{k} {v}" for k, v in sorted(excl.items())) or "none") + f"; orphan signals {len(res['orphan_signals'])}",
          f"Drafts: {len(dr)} ({emails} emails, {signal_level} with an account signal, {emails - signal_level} persona-only); "
          f"blocked {blocked}; model fallbacks {fallback}",
          f"Proposed lists: {len(plan['proposed_hubspot_static_lists'])}; sequence assignments {len(plan['proposed_sequence_assignments'])}; "
          f"suppression list {len(plan['proposed_suppression_list']['contact_ids'])} contacts",
          f"Review queue rows: {len(rq)}"]
    if research_stats:
        md.append("Mock research: " + ", ".join(f"{k} {v}" for k, v in research_stats.items()))
    md += ["", "Nothing was sent and nothing was written to a CRM. Approve campaign_bundle.json by its SHA-256 to release the plan."]
    return {"accounts": dict(ac), "contacts": dict(cc), "drafts": len(dr), "blocked": blocked, "fallback": fallback,
            "research": research_stats, "markdown": "\n".join(md) + "\n"}
