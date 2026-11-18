"""Enforced human approval. Adapted from my hubspot-admin-agent (which adapted it from email-marketing-agent).

Rules enforced in code (each has a test or failure-suite scenario):
  - Only artifacts marked approvable in manifest.json can be approved or released.
  - The approver must be listed in config/approvers.json for that artifact. Agent/service identities never approve.
  - The approver supplies the full SHA-256 of the bundle they reviewed. It must match the file on disk AND the hash the
    run generated. There is no flag or code path that approves without a hash.
  - A bundle lists the SHA-256 of every file reviewed together; editing any one voids the approval.
  - Runs built on a stale snapshot cannot be approved or released.
  - Approvals expire after approval_ttl_hours and are written to a hash-chained approvals.jsonl.
Release only copies files into released/. Nothing is sent and nothing is written to HubSpot, LinkedIn or any
other system: a person takes the released plan into those tools by hand.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .audit import AuditLog, verify
from .util import parse_dt, sha256_file

NEXT_STEPS = {
    "campaign_bundle.json": ("Manual: in HubSpot, create the proposed static lists from campaign_plan.json (contact ids), "
                             "add the suppression list as an exclusion, paste the approved drafts into the named sequences "
                             "or marketing email drafts, and upload the company domain lists to your ad platform. "
                             "Owners enrol contacts themselves. The agent performs no sends and no CRM writes."),
}


class ApprovalError(Exception):
    pass


def _manifest(run_dir: Path) -> dict:
    p = run_dir / "manifest.json"
    if not p.exists():
        raise ApprovalError("no manifest.json in run directory")
    return json.loads(p.read_text())


def snapshot_age_hours(manifest: dict, now: datetime) -> float | None:
    exported = parse_dt(manifest.get("exported_at"))
    return None if exported is None else round((now - exported).total_seconds() / 3600, 1)


def check_bundle(run_dir: Path, artifact: str):
    b = json.loads((run_dir / artifact).read_text())
    for name, h in b["components"].items():
        p = run_dir / name
        if not p.exists() or sha256_file(p) != h:
            raise ApprovalError(f"bundle component {name} changed or is missing; approval is void, re-run the agent")


def approve(run_dir, artifact: str, sha256: str, approver_id: str, now: datetime, approvers: dict, policy: dict) -> dict:
    run_dir = Path(run_dir)
    m = _manifest(run_dir)
    art = m["artifacts"].get(artifact)
    if not art or not art.get("approvable"):
        raise ApprovalError(f"{artifact} is not an approvable artifact")
    if (approver_id or "").strip().lower() in {b.lower() for b in approvers.get("blocked_identities", [])}:
        raise ApprovalError(f"'{approver_id}' is an agent/service identity and can never approve")
    who = approvers.get("approvers", {}).get(approver_id)
    if not who:
        raise ApprovalError(f"unknown approver '{approver_id}'")
    if artifact not in who["artifacts"]:
        raise ApprovalError(f"approver '{approver_id}' may not approve {artifact}")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ApprovalError("approval needs the full 64-character SHA-256 shown by `agent.py show`")
    current = sha256_file(run_dir / artifact)
    if sha256 != current:
        raise ApprovalError("hash does not match the file on disk; review the current file and use its hash")
    if current != art["sha256"]:
        raise ApprovalError("file differs from what this run generated; re-run the agent instead of editing outputs")
    check_bundle(run_dir, artifact)
    if m.get("stale"):
        raise ApprovalError(f"run was built on stale data ({m.get('stale_reason')}); re-export from HubSpot and re-run")
    age = snapshot_age_hours(m, now)
    if age is None or age > policy["snapshot_max_age_hours"]:
        raise ApprovalError(f"snapshot is {age} hours old (limit {policy['snapshot_max_age_hours']}); re-export and re-run")
    log = AuditLog(run_dir / "approvals.jsonl", clock=lambda: now)
    return log.append({"event": "approved", "artifact": artifact, "sha256": sha256, "approver": approver_id,
                       "approver_name": who["name"], "run_id": m["run_id"],
                       "expires_at": (now + timedelta(hours=policy["approval_ttl_hours"])).strftime("%Y-%m-%dT%H:%M:%SZ")})


def latest_approval(run_dir: Path, artifact: str) -> dict:
    ap = run_dir / "approvals.jsonl"
    if not ap.exists():
        raise ApprovalError(f"{artifact} has not been approved")
    ok, why = verify(ap)
    if not ok:
        raise ApprovalError(f"approvals log failed verification: {why}")
    recs = [json.loads(l) for l in ap.read_text().splitlines() if l.strip()]
    mine = [r for r in recs if r.get("artifact") == artifact and r.get("event") == "approved"]
    if not mine:
        raise ApprovalError(f"{artifact} has not been approved")
    return mine[-1]


def release(run_dir, artifact: str, now: datetime, policy: dict) -> Path:
    run_dir = Path(run_dir)
    m = _manifest(run_dir)
    art = m["artifacts"].get(artifact)
    if not art or not art.get("approvable"):
        raise ApprovalError(f"{artifact} is not a releasable artifact")
    last = latest_approval(run_dir, artifact)
    current = sha256_file(run_dir / artifact)
    if current != last["sha256"]:
        raise ApprovalError("file changed after approval (hash mismatch); approval is void")
    check_bundle(run_dir, artifact)
    if now > parse_dt(last["expires_at"]):
        raise ApprovalError("approval expired; review and approve again")
    age = snapshot_age_hours(m, now)
    if age is None or age > policy["snapshot_max_age_hours"]:
        raise ApprovalError(f"snapshot is now {age} hours old; re-export and re-run before releasing")
    outdir = run_dir / "released"
    outdir.mkdir(exist_ok=True)
    files = [artifact] + list(json.loads((run_dir / artifact).read_text())["components"])
    for f in files:
        shutil.copyfile(run_dir / f, outdir / f)
        if sha256_file(outdir / f) != sha256_file(run_dir / f):
            raise ApprovalError("copy verification failed")
    (outdir / f"{artifact}.release.json").write_text(json.dumps({
        "artifact": artifact, "sha256": current, "files": files, "approved_by": last["approver_name"],
        "approved_at": last["ts"], "released_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "next_step": NEXT_STEPS.get(artifact, "Manual step in your own tools. The agent performs no CRM writes.")}, indent=2) + "\n")
    AuditLog(run_dir / "approvals.jsonl", clock=lambda: now).append(
        {"event": "released", "artifact": artifact, "sha256": current, "run_id": m["run_id"]})
    return outdir / artifact
