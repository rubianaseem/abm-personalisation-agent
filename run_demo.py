"""End-to-end demo on the synthetic sample. Offline, no API key, fixed clock so the output is reproducible.

  python run_demo.py
Writes outputs/sample_run/ and outputs/demo_transcript.txt.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path

from abm import approval
from abm.audit import verify
from abm.pipeline import ROOT, load_config, run
from abm.research_mock import MockFirmographics, ResearchError
from abm.util import parse_dt
from evals.models import compromised_model

NOW = parse_dt("2026-11-18T09:00:00Z")
EXPORTED = "2026-11-18T08:30:00Z"
CSV = [ROOT / "sample_target_accounts.csv", ROOT / "sample_buying_committee.csv", ROOT / "sample_account_signals.csv"]
OUT = ROOT / "outputs" / "sample_run"


def main():
    cfg = load_config(ROOT / "config")
    if OUT.exists():
        shutil.rmtree(OUT)  # regenerated demo output only
    mock = json.loads((ROOT / "sample_firmographics_mock.json").read_text())["companies"]
    api = MockFirmographics(mock, {"halcyon.example": [ResearchError("rate_limited", True, 1.0)]})

    print("1. Plan the campaign (templates only, mocked firmographic fill with one injected 429)")
    r = run(*CSV, OUT, NOW, EXPORTED, research_api=api, sleep=lambda s: None)
    print(r["summary"]["markdown"])

    print("2. One tier 1 draft, as the reviewer sees it")
    text = (OUT / "drafts_review.md").read_text().split("\n## ")
    print("## " + next(t for t in text if t.startswith("email:brightwave.example:C001")).strip() + "\n")

    print("3. A compromised model on the same data (scripted: invents a customer result with a number)")
    tmp = Path(tempfile.mkdtemp())
    rb = run(*CSV, tmp, NOW, EXPORTED, client=compromised_model(["Lumiere is already a customer of ours"], "invent"), sleep=lambda s: None)
    fb = [d for d in rb["result"]["drafts"] if d["validation"]["model_errors"]]
    print(f"model drafts rejected and replaced by templates: {len(fb)} of {sum(1 for d in rb['result']['drafts'] if d['asset'] == 'email')}")
    print(f"example reasons: {fb[0]['validation']['model_errors']}\n")
    shutil.rmtree(tmp, ignore_errors=True)

    print("4. Approval gate")
    h = r["manifest"]["artifacts"]["campaign_bundle.json"]["sha256"]
    print(f"bundle sha256: {h}")
    for who, sha in (("claude", h), ("maya.campaigns", "0" * 64)):
        try:
            approval.approve(OUT, "campaign_bundle.json", sha, who, NOW, cfg["approvers"], cfg["policy"])
        except approval.ApprovalError as e:
            print(f"refused ({who}): {e}")
    rec = approval.approve(OUT, "campaign_bundle.json", h, "maya.campaigns", NOW + timedelta(minutes=20), cfg["approvers"], cfg["policy"])
    print(f"approved by {rec['approver_name']}, expires {rec['expires_at']}")
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(OUT, tmp / "copy")
    p = tmp / "copy" / "drafts.json"
    p.write_text(p.read_text().replace("Hi Priya,", "Hi Priya, quick one,"))
    try:
        approval.release(tmp / "copy", "campaign_bundle.json", NOW + timedelta(minutes=30), cfg["policy"])
    except approval.ApprovalError as e:
        print(f"refused (draft edited after approval, on a copy): {e}")
    shutil.rmtree(tmp, ignore_errors=True)
    rel = approval.release(OUT, "campaign_bundle.json", NOW + timedelta(minutes=30), cfg["policy"])
    print(f"released to {rel.parent.relative_to(ROOT)}; next step is manual in HubSpot and the ad platform\n")

    print("5. Audit trail")
    for name in ("trace.jsonl", "approvals.jsonl"):
        ok, why = verify(OUT / name)
        print(f"{name}: {why if ok else 'FAILED ' + why}")
    print("\nNothing was sent, nothing was written to a CRM, no enrichment vendor was called.")


if __name__ == "__main__":
    buf = io.StringIO()
    with redirect_stdout(buf):
        main()
    out = buf.getvalue()
    print(out, end="")
    (ROOT / "outputs" / "demo_transcript.txt").write_text(out)
