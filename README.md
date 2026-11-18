# ABM Personalisation Agent

**Turns a target account list and buying committee into tiered ABM plays with persona-aware email, ad and landing-page drafts. Every account fact cites the signal it came from, protected contacts never get a draft, and a named person approves the plan by SHA-256. It never sends and never writes to a CRM.**

Built by Rubia Naseem, GTM Engineer (12+ yrs CRM/RevOps, HubSpot & Salesforce).

Status: implemented and tested locally on synthetic data. Not integrated with a live CRM or ad platform.

## The problem

"AI personalisation at scale" often means a model reads whatever research is attached to an account and writes something confident. Operators describe what goes wrong:

- "You'll catch the pricing aggression. The weird tone shift. The hallucinated feature claim." ([Jason Lemkin on X](https://x.com/jasonlk/status/2109289938692784499), on reviewing AI SDR emails)
- "Leads got emails addressed to the wrong company. Nobody noticed for 9 days." ([@kadenc4_s on X](https://x.com/kadenc4_s/status/2117369219792658636))

Research notes and website snippets are also an attack surface. OWASP: "Indirect prompt injections occur when an LLM accepts input from external sources, such as websites or files" ([OWASP LLM01:2025](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)). Anthropic's guidance for grounded writing is blunt: "If it can’t find a quote, it must retract the claim" ([Claude docs, reduce hallucinations](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)). I built the pipeline around that rule.

## What it does

- **Tiers accounts deterministically**: competitor, customer (including subsidiaries by parent or subdomain), open deal and partner exclusions run first. Then fit points plus fresh-intent points give 1:1, 1:few or 1:many, with a cap on 1:1 capacity.
- **Builds an evidence pack per account** from supplied signals only. Stale, undated and future-dated signals expire. Text that reads like instructions is quarantined and never reaches a prompt, draft or trace.
- **Decides each buying-committee contact** with one reason code: opt-out, bounce, opt-out in notes, missing lawful basis, personal or mismatched email, unmapped title, per-account cap.
- **Drafts by persona and stage**: a champion hears about the ops hire, a buyer about the funding round. Each claim sentence cites an evidence id or an approved brand claim. Templates run offline; Claude is optional.
- **Validates every draft**: quote-grounding, verbatim brand claims, banned phrases, other accounts named, PII, links, injection leaks, placeholders and length. A failing model draft falls back to the template.
- **Packages a campaign plan** (HubSpot list, suppression list, sequence and ad-audience proposals) for hash-bound approval.

## Where each step runs

1. **GitHub** stores the code and the synthetic sample data.
2. **Your terminal** (Mac Terminal or the Cursor terminal) runs `agent.py` on CSV exports. No API key needed.
3. **Optional Claude** runs through the same code if `ANTHROPIC_API_KEY` is set. Output that fails validation is replaced by the template.
4. **You review** `drafts_review.md`, `campaign_plan.json` and `review_queue.csv`, approve the bundle by its hash, then build the lists and sequences in HubSpot and upload the domain lists to your ad platform yourself.
5. **The agent performs no writes**: no sends, no CRM or ad-platform calls, no Clay or enrichment calls. Firmographic gaps are filled from a local mock.

## Quick start

```bash
git clone https://github.com/rubianaseem/abm-personalisation-agent.git
cd abm-personalisation-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # standard library only
python run_demo.py                # full flow on synthetic data
python run_evals.py               # 46-case eval set + failure suite
python -m unittest discover -s tests -t .
```

## Example output (from outputs/demo_transcript.txt)

```text
Accounts: EXCLUDE_COMPETITOR 1, EXCLUDE_CUSTOMER 2, HOLD_OPEN_DEAL 1, ... TIER_1 3, TIER_2 2, TIER_3 2
Signals excluded: FUTURE_DATED 1, QUARANTINED_INJECTION 2, STALE 1, UNDATED 1; orphan signals 1
- (claim) Congratulations to the Brightwave Analytics team on the Series B (GBP 30M). [E3]
- (claim) Lumen Pipeline shows which signal moved each account into a sales queue. [C2]
model drafts rejected and replaced by templates: 9 of 9
refused (draft edited after approval, on a copy): bundle component drafts.json changed or is missing
```

On 46 versioned synthetic cases, the agent passed 41 (0.891, 95% CI 0.77-0.95) and a mail-merge baseline passed 6 (0.13). Drafts for protected contacts: 4 vs 18. Injected text in drafts: 0 vs 5. Unsupported claim sentences: 0 vs 8. All five misses are held-out cases written after the rules froze (paraphrased and German opt-outs, a customer subsidiary on its own domain, a French title, a churned customer). A scripted model that wraps a true quote in an invented reason passed the hard checks 22 times; all 22 were flagged for close review. Failure suite: 25 of 25. Details in [docs/EVALS.md](docs/EVALS.md).

## Guardrails and human in the loop

- Approval is enforced in code: a named approver, the full SHA-256 of a bundle covering the plan, drafts, evidence and review queue, and a 24-hour expiry. Edits void it. Stale exports are refused. Agent identities can't approve. There is no auto-approve flag.
- A model never decides who is contacted, which tier an account gets or what our product claims.
- Release copies files locally. Owners enrol contacts in HubSpot themselves.

Learn the key code line by line in [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

## More

[SETUP.md](SETUP.md) | [Architecture](docs/ARCHITECTURE.md) | [Evals](docs/EVALS.md) | [Details, costs, stack swaps and production gaps](docs/DETAILS.md) | [Sources](docs/SOURCES.md) | Related: [agent-decision-log](https://github.com/rubianaseem/agent-decision-log), [gtm-agent-eval-harness](https://github.com/rubianaseem/gtm-agent-eval-harness), [email-marketing-agent](https://github.com/rubianaseem/email-marketing-agent), [account-hierarchy-agent](https://github.com/rubianaseem/account-hierarchy-agent)
