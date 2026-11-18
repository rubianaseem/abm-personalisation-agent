# Setup

Everything runs locally on Python 3.10+ with the standard library. All sample data is synthetic (fictional companies on `.example` domains).

## 1. Virtual environment and sample run

```bash
git clone https://github.com/rubianaseem/abm-personalisation-agent.git
cd abm-personalisation-agent
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # nothing to install; kept for habit
python run_demo.py                   # writes outputs/sample_run/ and outputs/demo_transcript.txt
python run_evals.py                  # writes evals/report.md and evals/results.json, then runs the failure suite
python -m unittest discover -s tests -t .
python -m evals.failure_suite        # failure suite on its own
```

## 2. Step by step with the CLI

```bash
python agent.py run --out outputs/run_local --research-mock sample_firmographics_mock.json
python agent.py show --out outputs/run_local          # summary and the bundle SHA-256
# read outputs/run_local/drafts_review.md, campaign_plan.json and review_queue.csv
python agent.py approve --out outputs/run_local --approver maya.campaigns --sha256 <full hash from show>
python agent.py release --out outputs/run_local
python agent.py verify --out outputs/run_local        # checks trace.jsonl and approvals.jsonl hash chains
```

`--as-of` defaults to 2026-11-18T09:00:00Z so the sample export (dated that morning) is not refused as stale. For your own data, pass `--as-of ""` to use the real clock and `--exported-at` with the time you exported.

## 3. Optional Claude drafting

```bash
pip install -r requirements-claude.txt
export ANTHROPIC_API_KEY=...         # your own key, from your shell; never commit it
python agent.py run --out outputs/run_claude
```

Only email drafts for `DRAFT_EMAIL` contacts go to the model. The prompt holds the screened evidence pack (free text wrapped as data), the approved claims, and the exact greeting, call to action and sign-off. Output is parsed as JSON and validated. Anything that fails is replaced by the template draft and listed in `review_queue.csv` as `MODEL_FALLBACK`. Use `--no-model` to force templates. Retries use exponential backoff with jitter and honour Retry-After.

## 4. Using your own data

The agent reads three CSVs. Column names must match (extra columns are ignored):

- **Target accounts** (HubSpot company export or a Salesforce account report): `account_id, company_name, domain, industry, employees, country, relationship, open_deal_stage, journey_stage, target_list, parent_domain`. Map your "Type" or lifecycle field to `relationship` (prospect, customer, competitor, partner). `open_deal_stage` is the stage of any open deal on the company. `journey_stage` is unaware, aware or engaged.
- **Buying committee** (contact export filtered to those companies): `contact_id, email, first_name, last_name, job_title, company_domain, email_opt_out, hard_bounced, lawful_basis, notes`. In HubSpot, `email_opt_out` maps to "Unsubscribed from all email" and `hard_bounced` to a bounce property such as "Email hard bounce reason" (convert it to yes or no first). Use your own recorded lawful basis field.
- **Signals**: `signal_id, domain, signal_type, value, text, observed_at, source_field, source_url`. Types: funding, job_post, intent_surge, tech_change, news, website_visit, research_note, website_snippet. A Clay table export, an intent-tool export or a jobs feed can be reshaped into this file. This repo never calls Clay or any vendor.

Then edit `config/`: `policy.json` (ICP, fit points, tiers, signal ages, caps), `brand_rules.json` (approved claims, banned phrases, allowed links, limits), `personas.json` (title rules, hook order, stage calls to action), `campaign_brief.json` and `approvers.json`. Set `ABM_TRACE_SALT` to a secret value before running on real contacts.

## 5. Extending it with a coding agent

`CLAUDE.md` (Claude Code) and `AGENTS.md` (Cursor, Codex CLI, Grok and others) hold the hard rules. A good prompt:

> Add a `job_change` signal type with a 60-day max age. Add a cases_v2 builder with three cases for it, a unit test, and report before and after numbers from `python run_evals.py`. Do not edit cases_v1.

Ask the agent to run the three test commands and paste the numbers. Reject any change that adds a send, a CRM write, an auto-approve path or lets a model pick contacts, tiers or product claims.

## 6. Troubleshooting

- `input error: accounts: missing required columns` - rename your export headers to match section 4.
- `refused: snapshot is ... hours old` - re-export and re-run; approvals only work on fresh data.
- `refused: hash does not match` - copy the full 64-character hash from `agent.py show`, and do not edit output files; re-run instead.
- `cases_v1.json does not match cases_v1.sha256` - v1 labels are frozen. Add a new versioned case file.
- Every email shows `MODEL_FALLBACK` - check `trace.jsonl` for `llm_error` records (rate limits, auth, or validation codes).
