import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from abm import approval
from abm.audit import verify
from abm.pipeline import ROOT, run
from tests.helpers import CFG, NOW

CSV = [ROOT / "sample_target_accounts.csv", ROOT / "sample_buying_committee.csv", ROOT / "sample_account_signals.csv"]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.r = run(*CSV, self.tmp, NOW, "2026-11-18T08:30:00Z", research_mock=ROOT / "sample_firmographics_mock.json",
                     sleep=lambda s: None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sample_decisions(self):
        decs = {a["domain"]: a["decision"] for a in self.r["plan"]["accounts"]}
        self.assertEqual(decs["ferrous.example"], "EXCLUDE_COMPETITOR")
        self.assertEqual(decs["meridianlabs.example"], "EXCLUDE_CUSTOMER")
        self.assertEqual(decs["northpeak.example"], "TIER_2")  # demoted by the tier-1 cap
        self.assertEqual(decs["halcyon.example"], "TIER_3")    # employees filled by the mock lookup

    def test_plan_is_proposal_only(self):
        p = self.r["plan"]
        self.assertFalse(p["writes_performed"])
        self.assertEqual(p["status"], "proposed")
        blob = json.dumps(p)
        self.assertNotIn("@", blob)

    def test_suppressed_never_in_lists_or_sequences(self):
        p = self.r["plan"]
        sup = set(p["proposed_suppression_list"]["contact_ids"])
        listed = {c for l in p["proposed_hubspot_static_lists"] for c in l["contact_ids"]}
        seq = {s["contact_id"] for s in p["proposed_sequence_assignments"]}
        self.assertFalse(sup & (listed | seq))
        self.assertTrue({"C002", "C010", "C015", "C020"} <= sup)

    def test_every_draft_cites_and_passes(self):
        for d in self.r["result"]["drafts"]:
            self.assertEqual(d["validation"]["errors"], [], d["draft_id"])
            for s in d["sentences"]:
                if s["kind"] == "claim":
                    self.assertTrue(s["cites"])

    def test_trace_verifies_and_is_pseudonymised(self):
        ok, _ = verify(self.tmp / "trace.jsonl")
        self.assertTrue(ok)
        self.assertNotIn("@", (self.tmp / "trace.jsonl").read_text())

    def test_approval_release_cycle(self):
        h = self.r["manifest"]["artifacts"]["campaign_bundle.json"]["sha256"]
        with self.assertRaises(approval.ApprovalError):
            approval.approve(self.tmp, "campaign_bundle.json", h[:20], "maya.campaigns", NOW, CFG["approvers"], CFG["policy"])
        with self.assertRaises(approval.ApprovalError):
            approval.release(self.tmp, "campaign_bundle.json", NOW, CFG["policy"])
        approval.approve(self.tmp, "campaign_bundle.json", h, "maya.campaigns", NOW, CFG["approvers"], CFG["policy"])
        out = approval.release(self.tmp, "campaign_bundle.json", NOW + timedelta(minutes=1), CFG["policy"])
        self.assertTrue(out.exists())
        self.assertTrue(verify(self.tmp / "approvals.jsonl")[0])

    def test_rerun_is_identical(self):
        h1 = self.r["manifest"]["artifacts"]["campaign_bundle.json"]["sha256"]
        r2 = run(*CSV, self.tmp, NOW, "2026-11-18T08:30:00Z", research_mock=ROOT / "sample_firmographics_mock.json", sleep=lambda s: None)
        self.assertEqual(h1, r2["manifest"]["artifacts"]["campaign_bundle.json"]["sha256"])


class EvalSetTests(unittest.TestCase):
    def test_cases_frozen_and_balanced(self):
        import hashlib
        p = ROOT / "evals" / "cases_v1.json"
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), (ROOT / "evals" / "cases_v1.sha256").read_text().split()[0])
        cases = json.loads(p.read_text())["cases"]
        splits = {c["split"] for c in cases}
        self.assertEqual(splits, {"designed", "edge", "adversarial", "heldout"})
        self.assertTrue(30 <= len(cases) <= 60)

    def test_agent_beats_baseline_on_designed_cases(self):
        from evals.baseline import run_baseline
        from evals.harness import aggregate, grade, run_agent
        cases = [c for c in json.loads((ROOT / "evals" / "cases_v1.json").read_text())["cases"] if c["split"] != "heldout"]
        agent = aggregate([grade(c, run_agent(c, CFG, NOW), CFG, NOW) for c in cases])
        base = aggregate([grade(c, run_baseline(c, CFG["brand"], CFG["personas"], CFG["brief"]), CFG, NOW) for c in cases])
        self.assertEqual(agent["passed"], len(cases))
        self.assertEqual(agent["injection_leaks"] + agent["protected_violations"], 0)
        self.assertGreater(base["protected_violations"], 0)
