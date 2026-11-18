# Details

## API cost assumptions (no account or billing access was used)

The default path makes no paid calls. With `ANTHROPIC_API_KEY` set, one model call is made per `DRAFT_EMAIL` contact (9 in the sample). Ads and landing heroes are templates.

Rough sizing, to check against your provider's current price page before relying on it:
- Prompt: about 600-900 input tokens (brief, evidence pack, approved claims, fixed lines). Output: capped at 600 tokens, typically 150-250.
- 500 contacts: about 500 calls, roughly 0.4M input and 0.1M output tokens, plus retries. Multiply by the per-token prices you pay.
- Fallbacks cost nothing extra: a rejected draft is replaced by the template, not regenerated.

I did not read any billing page, invoice or account usage for these figures.

## Stack swaps

| Piece here | Swap for | What changes |
|---|---|---|
| CSV exports | HubSpot CRM search API, Salesforce SOQL report | Write a read-only loader that outputs the same columns (`ingest.py` contracts) |
| `research_mock.py` | Clay table export, Apollo or ZoomInfo export, your own scraper | Replace `MockFirmographics.lookup`; keep fill-blanks-only and the checkpoint |
| Signals CSV | Intent tool export, jobs feed, news API | Map to the 8 signal types; keep `observed_at` and `source_field` |
| Anthropic client | Another model provider | Implement `complete(system, user)` in `llm.py`; the validator stays the same |
| `campaign_plan.json` lists | HubSpot static lists, Salesforce campaigns | A person creates them from contact ids, or a separate, approved writer does |
| Ad domain lists | LinkedIn matched audiences (company list upload) | Upload by hand after release |
| `trace.jsonl` | agent-decision-log spool to BigQuery | Map fields onto decision.v1 |

## Customise for your stack

- **ICP and tiers**: `config/policy.json`. Start with your own closed-won profile, then check how many accounts land in each tier before trusting the cut-offs.
- **Signal ages**: a job post goes stale faster than a funding round. Set `signal_max_age_days` per type with your SDR leads.
- **Brand**: `config/brand_rules.json`. Approved claims should come from product marketing and legal, word for word. Add competitor names and phrases legal has refused.
- **Personas**: `config/personas.json`. Title patterns run in order and the first match wins. Add local-language titles (the held-out set shows why).
- **Lawful basis**: the agent holds contacts without a recorded basis. It does not decide whether legitimate interests applies to a person; that is your documented assessment.

## How this runs today (and what production would add)

| Capability | Status |
|---|---|
| Deterministic tiering, exclusions, contact decisions, evidence expiry, quarantine | Implemented, tested locally (unit tests, 46-case eval) |
| Template drafts with citations and the validator | Implemented, tested locally |
| Claude drafting | Implemented; tested only with scripted test doubles. No live model run is in the eval numbers |
| Mock firmographic fill with retries, checkpoint, resume | Implemented, tested locally against a mock. Not integrated with a vendor |
| Hash-bound approval with TTL, release to local folder | Implemented, tested locally |
| HubSpot, Salesforce, LinkedIn or Clay integration | Not implemented (by design: proposals only) |
| Production use | Not production-proven. No real campaign has been run with it |

Production would add: a read-only CRM loader with pagination and rate limits; non-English opt-out detection and a reviewed phrase list; account hierarchy from a proper parent-child source; SSO-backed approver identity instead of a JSON file; a secrets manager; sampling of accepted model drafts for human scoring; live-model evals with the same cases; monitoring of fallback and READ_CLOSELY rates; and a separate, approved writer service if lists should ever be created automatically.

## Limitations

- Injection detection is pattern-based. Paraphrases get past it (held-out H02 was caught only because templates never use free text). The output validator is the second layer.
- Quote-grounding checks that a fact is quoted, not that the sentence around it is true. See the measured gap in docs/EVALS.md.
- Relationship values outside prospect/customer/competitor/partner are treated as blank.
