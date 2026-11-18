# Architecture

```text
 sample_target_accounts.csv   sample_buying_committee.csv   sample_account_signals.csv
            |                            |                            |
            v                            v                            v
 ingest.py: normalise domains, parse employee bands, merge duplicates (most restrictive flags win), data-quality notes
            |
            +--> research_mock.py (optional, MOCKED): fill blank employees/industry, retries + Retry-After, checkpoint/resume
            |
            v
 evidence.py: per-account pack. Expire STALE / UNDATED / FUTURE_DATED, QUARANTINE instruction-like text, assign E ids
            |
            v
 tiering.py: exclusions (competitor, customer + family, open deal, partner, missing data) -> fit + intent -> tier -> 1:1 cap
            |
            v
 contacts.py: one action per contact (suppress / hold / review / program list / draft) -> per-account cap by persona priority
            |
            v
 drafting.py: persona hook order + stage CTA -> template draft      (optional) Claude via llm.py with retry/backoff
            |                                                             |
            +-------------------------> validate.py <---------------------+
                                        hard checks: fail -> template fallback, failing template -> blocked
                                        soft check: model words beyond the quote -> READ_CLOSELY in review queue
            |
            v
 plan.py: campaign_plan.json (proposed lists, suppression list, sequence assignments, ad domain lists, landing pages)
          review_queue.csv
            |
            v
 pipeline.py: drafts.json, evidence_packs.json, campaign_bundle.json (SHA-256 of 4 files), manifest.json, trace.jsonl
            |
            v
 approval.py: named approver + full SHA-256 + fresh snapshot -> approvals.jsonl (hash-chained, 24h TTL) -> release/ (local copy)
            |
            v
 A person builds lists and sequences in HubSpot and uploads ad lists. The agent writes nothing outside its output folder.
```

## AI vs deterministic

| Step | Who decides | Why |
|---|---|---|
| Exclusions, tiers, caps | Rules in `config/policy.json` | Money, consent and account ownership must be explainable and repeatable |
| Contact actions | Rules | Suppression is a legal and reputational control |
| Evidence freshness, quarantine | Rules | A model can't be trusted to judge text that may be attacking it |
| Email wording | Template, or Claude inside validator limits | Judgement on tone is where a model helps |
| Product claims | `brand_rules.json` approved claims, verbatim | Claims are a brand and legal decision |
| Release | A named human with the hash | Approval binds to exactly what was reviewed |

## Data contracts

**Evidence item** (`evidence_packs.json`, per account domain):
`id` (E1..), `signal_id`, `signal_type`, `value` (redacted, 160 chars), `text` (free-text types only, redacted, 400 chars), `observed_at`, `age_days`, `source_field`, `source_url`, `template_hook`. Excluded signals are listed with `signal_id` and `reason` only; quarantined text is never copied.

**Draft** (`drafts.json`): `draft_id` (`email:<domain>:<contact_id>`, `ad:<domain>`, `ad:cluster:<industry>`, `landing:<domain>`), `asset`, `tier`, `persona`, `stage`, `subject` or `headline`, `sentences[]` of `{kind: greeting|claim|cta|signoff|headline, text, cites[]}`, `source` (template or model name), `personalisation` (account_signal, persona_only, account_name, industry_cluster), `validation {errors, model_errors, warnings}`.

**Campaign plan** (`campaign_plan.json`, schema `abm_campaign_plan.v1`): `run_id`, `policy_version`, `status: proposed`, `writes_performed: false`, `accounts[]` with decision, fit, intent, reasons, evidence ids and fields filled by the mock lookup, `proposed_hubspot_static_lists[]` (contact ids), `proposed_suppression_list`, `proposed_sequence_assignments[]` (contact id, sequence, draft id, draft SHA-256, "enrolled by account owner, manually"), `proposed_ad_company_lists` (tier domains and exclusions), `proposed_landing_pages`, `draft_hashes`. No emails.

**Trace record** (`trace.jsonl`): a subset of the decision.v1 shape from my [agent-decision-log](https://github.com/rubianaseem/agent-decision-log): `decision_id` (UUIDv5 of run, step, subject, decision), `run_id`, `step` (research, signal, evidence, tier, contact, model, draft), `subject` (domain, or a salted pseudonym for contacts), `decision`, `reasons`, `agent_version`, `policy_version`, `prompt_version`, `model`, `seq`, `prev_hash`, `hash`. No emails and no free text. To load into a warehouse, map these onto the full decision.v1 contract in that repo.

**Bundle** (`campaign_bundle.json`): `run_id` and `components` = SHA-256 of `campaign_plan.json`, `drafts.json`, `evidence_packs.json`, `review_queue.csv`. Approval binds to the bundle file's own SHA-256.

## Idempotency and recovery

- `run_id` is derived from the input file hashes, the policy and the as-of time, so the same inputs give byte-identical plans and the same bundle hash.
- The mock lookup checkpoints after every domain (atomic file replace). After a crash, the next run reads finished domains from the checkpoint and only looks up the rest.
- Model calls retry with exponential backoff and jitter and honour Retry-After. After the budget is spent the template is used and the trace says why.

## Where it sits in my portfolio

This is roadmap item 11 and the drafting layer the planned campaign-preflight-orchestrator would reuse (status: proposed, not built). It reuses the approval gate and audit chain from [hubspot-admin-agent](https://github.com/rubianaseem/hubspot-admin-agent) and [email-marketing-agent](https://github.com/rubianaseem/email-marketing-agent), the trace shape from agent-decision-log, the eval approach (frozen versioned cases, a held-out split, Wilson intervals, a simple baseline) from [gtm-agent-eval-harness](https://github.com/rubianaseem/gtm-agent-eval-harness), and the parent/subsidiary idea from [account-hierarchy-agent](https://github.com/rubianaseem/account-hierarchy-agent).
