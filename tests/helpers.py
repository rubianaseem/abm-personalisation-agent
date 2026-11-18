from abm.pipeline import ROOT, load_config
from abm.util import parse_dt

CFG = load_config(ROOT / "config")
NOW = parse_dt("2026-11-18T09:00:00Z")


def account(**kw):
    a = {"account_id": "A1", "company_name": "Test Co", "domain": "testco.example", "industry": "software", "employees": 800,
         "country": "GB", "relationship": "prospect", "open_deal_stage": "", "journey_stage": "aware", "target_list": True,
         "parent_domain": "", "source_rows": ["A1"]}
    a.update(kw)
    return a


def contact(**kw):
    c = {"contact_id": "K1", "email": "ann@testco.example", "email_valid": True, "first_name": "Ann", "last_name": "Lee",
         "job_title": "RevOps Manager", "company_domain": "testco.example", "email_opt_out": False, "hard_bounced": False,
         "lawful_basis": "legitimate_interest", "notes": "", "source_rows": ["K1"]}
    c.update(kw)
    return c
