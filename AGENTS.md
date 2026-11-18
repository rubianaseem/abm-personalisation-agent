# AGENTS.md

Instructions for Codex CLI, Cursor agents, Grok and any other coding assistant working in this repo. Claude Code reads CLAUDE.md, which has the same rules.

What this repo is: an offline ABM personalisation agent. It tiers target accounts, builds cited evidence packs, decides each buying-committee contact, drafts persona-aware copy, validates every draft, and packages a campaign plan that a named person approves by SHA-256. It performs no sends and no CRM writes.

Do
- Keep every hard control deterministic and covered by a unit test or failure-suite scenario.
- Add eval cases for every rule change in a new versioned case file and report before and after numbers from `python run_evals.py`.
- Keep sample data synthetic, labelled, and on `.example` domains.
- Label anything mocked as mocked in code comments and docs.

Do not
- Add a send, enrolment, CRM write, ad-platform call, Clay or enrichment call, or an auto-approve flag.
- Let a model choose contacts, tiers, exclusions or product claims.
- Pass notes or snippets to a model before `untrusted.screen`, or write emails or free text to the trace.
- Edit `evals/cases_v1.json` labels. Print or log secrets. Add emojis.

Commands
```bash
python run_demo.py
python run_evals.py
python -m unittest discover -s tests -t .
python -m evals.failure_suite
```
