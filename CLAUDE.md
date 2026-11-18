# CLAUDE.md

Claude Code reads this file. The same rules apply to every coding agent (see AGENTS.md).

This repo is an ABM personalisation agent that only writes local files. Keep it that way.

Hard rules
- Never add code that sends email, enrols a sequence, writes to a CRM or ad platform, or calls Clay or any enrichment API. `research_mock.py` is a mock and stays one.
- Never add an auto-approve flag or a path that releases an artifact without `approval.approve` being called with the full SHA-256 by a named approver. Agent and model identities stay in `blocked_identities`. The bundle must cover every file reviewed together.
- Tiering, exclusions, contact actions, evidence expiry and quarantine stay deterministic. A model may only write email wording, and only through `validate.validate_draft`. A failing model draft must fall back to the template.
- Product claims come only from `config/brand_rules.json`, verbatim.
- Research notes, website snippets and contact notes are untrusted. Screen with `untrusted.screen`. Never write emails, notes or quarantined text to `trace.jsonl`.
- Never read or print secrets. `ANTHROPIC_API_KEY` and `ABM_TRACE_SALT` come from the environment only.
- No emojis in code output or docs. README stays under 900 words.

Workflow
1. Change `config/*.json` or the rules.
2. Add cases in a new `evals/build_cases_v2.py` (never edit v1 labels; `cases_v1.sha256` enforces it) and a unit test.
3. Run `python run_evals.py` and `python -m unittest discover -s tests -t .`. Designed, edge and adversarial splits must stay at 100%, the failure suite at 100%. Report held-out numbers as they are.
4. Run `python run_demo.py` to refresh `outputs/`.

Map
- `ingest.py` loads and merges. `evidence.py` builds packs. `tiering.py` decides accounts. `contacts.py` decides contacts.
- `drafting.py` writes drafts (template, optional model). `validate.py` is the output gate. `llm.py` handles retries.
- `core.py` is the in-memory pipeline. `plan.py` builds the plan and review queue. `pipeline.py` writes files, bundle and trace.
- `approval.py` is the human gate. `audit.py` is the hash chain. `research_mock.py` is the mocked lookup.
