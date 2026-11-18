"""Load and normalise the three input files: target accounts, buying-committee contacts and account signals.

The files are CRM / spreadsheet exports, so they are messy on purpose: duplicate accounts under `www.` or
upper-case domains, employee counts like "1,200" or "1k-5k", duplicate contacts with conflicting opt-out
flags, undated or future-dated signals. Normalisation is deterministic and every repair is recorded as a
data-quality note. Nothing here guesses a missing value.
"""
from __future__ import annotations

import re
from datetime import datetime

from .util import parse_dt, read_csv, truthy

ACCOUNT_COLUMNS = {"account_id", "company_name", "domain", "industry", "employees", "country", "relationship",
                   "open_deal_stage", "journey_stage", "target_list", "parent_domain"}
CONTACT_COLUMNS = {"contact_id", "email", "first_name", "last_name", "job_title", "company_domain",
                   "email_opt_out", "hard_bounced", "lawful_basis", "notes"}
SIGNAL_COLUMNS = {"signal_id", "domain", "signal_type", "value", "text", "observed_at", "source_field", "source_url"}

EMAIL_RE = re.compile(r"^[\w.+-]+@([\w-]+\.)+[a-z]{2,}$", re.I)
RELATIONSHIP_RANK = {"competitor": 5, "customer": 4, "partner": 3, "prospect": 1, "": 0}
STAGES = {"unaware", "aware", "engaged"}


class InputError(Exception):
    pass


def require_columns(rows: list[dict], needed: set[str], name: str) -> None:
    if not rows:
        raise InputError(f"{name}: file has no rows")
    missing = needed - set(rows[0].keys())
    if missing:
        raise InputError(f"{name}: missing required columns {sorted(missing)}")


def norm_domain(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = v.split("/")[0]
    if v.startswith("www."):
        v = v[4:]
    return v if "." in v else ""


def parse_employees(value: str) -> int | None:
    """'1,200' -> 1200, '1k-5k' -> 1000 (lower bound), '250+' -> 250, '' -> None."""
    v = (value or "").strip().lower().replace(",", "").replace(" ", "")
    if not v:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)(k)?", v)
    if not m:
        return None
    n = float(m.group(1)) * (1000 if m.group(2) else 1)
    return int(n)


def load_accounts(rows: list[dict], notes: list[dict]) -> dict[str, dict]:
    require_columns(rows, ACCOUNT_COLUMNS, "accounts")
    out: dict[str, dict] = {}
    for r in rows:
        dom = norm_domain(r.get("domain", ""))
        rel = (r.get("relationship") or "").strip().lower()
        stage = (r.get("journey_stage") or "").strip().lower()
        acc = {
            "account_id": (r.get("account_id") or "").strip(),
            "company_name": (r.get("company_name") or "").strip(),
            "domain": dom,
            "industry": (r.get("industry") or "").strip().lower(),
            "employees": parse_employees(r.get("employees", "")),
            "country": (r.get("country") or "").strip().upper(),
            "relationship": rel if rel in RELATIONSHIP_RANK else "",
            "open_deal_stage": (r.get("open_deal_stage") or "").strip(),
            "journey_stage": stage if stage in STAGES else "unaware",
            "target_list": bool(truthy(r.get("target_list"))),
            "parent_domain": norm_domain(r.get("parent_domain", "")),
            "source_rows": [(r.get("account_id") or "").strip()],
        }
        if stage and stage not in STAGES:
            notes.append({"subject": acc["account_id"], "note": f"unknown journey_stage '{stage}', treated as unaware"})
        key = dom or f"nodomain:{acc['account_id']}"
        if key in out:
            prev = out[key]
            notes.append({"subject": acc["account_id"], "note": f"duplicate of {prev['account_id']} on domain; merged"})
            prev["source_rows"].append(acc["account_id"])
            # most restrictive relationship wins; open deal wins; blanks are filled, never overwritten
            if RELATIONSHIP_RANK[acc["relationship"]] > RELATIONSHIP_RANK[prev["relationship"]]:
                prev["relationship"] = acc["relationship"]
            for f in ("company_name", "industry", "country", "open_deal_stage", "parent_domain"):
                if not prev[f] and acc[f]:
                    prev[f] = acc[f]
            if prev["employees"] is None:
                prev["employees"] = acc["employees"]
            prev["target_list"] = prev["target_list"] or acc["target_list"]
            continue
        out[key] = acc
    return out


def load_contacts(rows: list[dict], notes: list[dict]) -> dict[str, dict]:
    require_columns(rows, CONTACT_COLUMNS, "contacts")
    out: dict[str, dict] = {}
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        c = {
            "contact_id": (r.get("contact_id") or "").strip(),
            "email": email,
            "email_valid": bool(EMAIL_RE.match(email)),
            "first_name": (r.get("first_name") or "").strip(),
            "last_name": (r.get("last_name") or "").strip(),
            "job_title": (r.get("job_title") or "").strip(),
            "company_domain": norm_domain(r.get("company_domain", "")),
            "email_opt_out": bool(truthy(r.get("email_opt_out"))),
            "hard_bounced": bool(truthy(r.get("hard_bounced"))),
            "lawful_basis": (r.get("lawful_basis") or "").strip().lower().replace(" ", "_"),
            "notes": (r.get("notes") or "").strip(),
            "source_rows": [(r.get("contact_id") or "").strip()],
        }
        key = email or f"noemail:{c['contact_id']}"
        if key in out:
            prev = out[key]
            notes.append({"subject": c["contact_id"], "note": f"duplicate of {prev['contact_id']} on email; merged with most restrictive flags"})
            prev["source_rows"].append(c["contact_id"])
            prev["email_opt_out"] = prev["email_opt_out"] or c["email_opt_out"]
            prev["hard_bounced"] = prev["hard_bounced"] or c["hard_bounced"]
            prev["notes"] = " | ".join(x for x in (prev["notes"], c["notes"]) if x)
            for f in ("first_name", "last_name", "job_title", "company_domain", "lawful_basis"):
                if not prev[f] and c[f]:
                    prev[f] = c[f]
            continue
        out[key] = c
    return out


def load_signals(rows: list[dict], notes: list[dict]) -> list[dict]:
    require_columns(rows, SIGNAL_COLUMNS, "signals")
    out, seen = [], {}
    for r in rows:
        s = {
            "signal_id": (r.get("signal_id") or "").strip(),
            "domain": norm_domain(r.get("domain", "")),
            "signal_type": (r.get("signal_type") or "").strip().lower(),
            "value": (r.get("value") or "").strip(),
            "text": (r.get("text") or "").strip(),
            "observed_at": parse_dt(r.get("observed_at")),
            "observed_raw": (r.get("observed_at") or "").strip(),
            "source_field": (r.get("source_field") or "").strip(),
            "source_url": (r.get("source_url") or "").strip(),
        }
        key = (s["domain"], s["signal_type"], s["value"].lower(), s["text"].lower())
        if key in seen:
            prev = seen[key]
            notes.append({"subject": s["signal_id"], "note": f"duplicate of {prev['signal_id']}; kept the newer observation"})
            if s["observed_at"] and (not prev["observed_at"] or s["observed_at"] > prev["observed_at"]):
                prev.update({k: s[k] for k in ("observed_at", "observed_raw", "signal_id", "source_url")})
            continue
        seen[key] = s
        out.append(s)
    return out


def load_all(accounts_path, contacts_path, signals_path) -> tuple[dict, dict, list, list]:
    notes: list[dict] = []
    accounts = load_accounts(read_csv(accounts_path), notes)
    contacts = load_contacts(read_csv(contacts_path), notes)
    signals = load_signals(read_csv(signals_path), notes)
    return accounts, contacts, signals, notes


def as_of_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")
