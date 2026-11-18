"""Command line for the ABM personalisation agent.

  python agent.py run      --out outputs/run_local            # plan a campaign from the sample CSVs
  python agent.py show     --out outputs/run_local            # summary + the bundle SHA-256 to approve
  python agent.py approve  --out outputs/run_local --sha256 <hash> --approver maya.campaigns
  python agent.py release  --out outputs/run_local
  python agent.py verify   --out outputs/run_local            # check the hash-chained trace and approvals log

Nothing here sends email, writes to a CRM or calls an enrichment vendor. `--as-of` pins the clock so the
synthetic sample (exported 2026-11-18) is not refused as stale when you try it later.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from abm import approval
from abm.audit import verify
from abm.ingest import InputError
from abm.llm import get_client
from abm.pipeline import ROOT, load_config, run
from abm.util import parse_dt, sha256_file

SAMPLE_AS_OF = "2026-11-18T09:00:00Z"


def _now(args) -> datetime:
    if args.as_of:
        dt = parse_dt(args.as_of)
        if dt is None:
            sys.exit(f"could not parse --as-of {args.as_of}")
        return dt
    return datetime.now(timezone.utc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "show", "approve", "release", "verify"])
    ap.add_argument("--out", default="outputs/run_local")
    ap.add_argument("--accounts", default=str(ROOT / "sample_target_accounts.csv"))
    ap.add_argument("--contacts", default=str(ROOT / "sample_buying_committee.csv"))
    ap.add_argument("--signals", default=str(ROOT / "sample_account_signals.csv"))
    ap.add_argument("--exported-at", default=None, help="when the CSVs were exported (ISO). Default: sample_export_manifest.json")
    ap.add_argument("--research-mock", default=None, help="fill blank firmographics from a MOCK lookup file")
    ap.add_argument("--as-of", default=SAMPLE_AS_OF, help="clock for the run/approval (default pins the sample date; pass '' for now)")
    ap.add_argument("--no-model", action="store_true", help="templates only even if ANTHROPIC_API_KEY is set")
    ap.add_argument("--sha256", default="")
    ap.add_argument("--approver", default="")
    args = ap.parse_args(argv)
    now, out = _now(args), Path(args.out)
    cfg = load_config(ROOT / "config")

    if args.command == "run":
        exported = args.exported_at or json.loads((ROOT / "sample_export_manifest.json").read_text())["exported_at"]
        client = None if args.no_model else get_client()
        try:
            r = run(args.accounts, args.contacts, args.signals, out, now, exported, client=client, research_mock=args.research_mock)
        except InputError as exc:
            print(f"input error: {exc}")
            return 2
        print(r["summary"]["markdown"])
        print(f"bundle sha256: {r['manifest']['artifacts']['campaign_bundle.json']['sha256']}")
        print(f"mode: {'model ' + client.name if client else 'offline templates (no ANTHROPIC_API_KEY or --no-model)'}")
        return 0
    if args.command == "show":
        print((out / "run_summary.md").read_text())
        print(f"campaign_bundle.json sha256: {sha256_file(out / 'campaign_bundle.json')}")
        print("Review drafts_review.md, campaign_plan.json and review_queue.csv before approving.")
        return 0
    if args.command == "approve":
        try:
            rec = approval.approve(out, "campaign_bundle.json", args.sha256, args.approver, now, cfg["approvers"], cfg["policy"])
        except approval.ApprovalError as exc:
            print(f"refused: {exc}")
            return 1
        print(f"approved by {rec['approver_name']} until {rec['expires_at']}")
        return 0
    if args.command == "release":
        try:
            p = approval.release(out, "campaign_bundle.json", now, cfg["policy"])
        except approval.ApprovalError as exc:
            print(f"refused: {exc}")
            return 1
        print(f"released to {p.parent}. Next step is manual; see {p.name}.release.json")
        return 0
    ok_all = True
    for name in ("trace.jsonl", "approvals.jsonl"):
        if (out / name).exists():
            ok, why = verify(out / name)
            ok_all &= ok
            print(f"{name}: {why if ok else 'FAILED ' + why}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
