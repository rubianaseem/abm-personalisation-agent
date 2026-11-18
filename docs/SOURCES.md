# Sources

Read on 18 Nov 2026. Quotes in the README are copied from these pages or posts. No code or text was reused from any of them.

| Source | What I took from it | How this repo differs |
|---|---|---|
| [Jason Lemkin on X](https://x.com/jasonlk/status/2109289938692784499) (11 Oct 2026) | Review every early AI SDR email; reviews catch the hallucinated feature claim | Product claims can only be approved text, verbatim, enforced in code |
| [@kadenc4_s on X](https://x.com/kadenc4_s/status/2117369219792658636) (2 Nov 2026) | Emails addressed to the wrong company; a check on empty merge fields fixed it | Other account names anywhere in a draft block it; empty greetings and placeholders block it |
| [@adugbovictory on X](https://x.com/adugbovictory/status/2112223577869009104) (19 Oct 2026) | A locked claims list for AI outreach | `brand_rules.json` approved claims with ids |
| [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) | Indirect injection through websites and files | Research notes and snippets are screened, quarantined, never shown, and checked again on output |
| [Claude docs: reduce hallucinations](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations) | Ground claims in quotes; retract a claim without a supporting quote; restrict to provided documents | Quote-grounding check per sentence; template fallback instead of retraction |
| [guerrilla2799/abm-and-scale-os](https://github.com/guerrilla2799/abm-and-scale-os) (MIT, description only) | ABM as a set of Claude Code skills | One evaluated pipeline with gates and a baseline |
| [tzockoll-creator/AccountBasedResearch](https://github.com/tzockoll-creator/AccountBasedResearch) (MIT, description only) | Company signals mapped to persona talking points | Signals must be fresh and cited; persona decides the hook order |

My own repos reused here: approval and audit code adapted from [hubspot-admin-agent](https://github.com/rubianaseem/hubspot-admin-agent) and [email-marketing-agent](https://github.com/rubianaseem/email-marketing-agent); trace shape from [agent-decision-log](https://github.com/rubianaseem/agent-decision-log); eval approach from [gtm-agent-eval-harness](https://github.com/rubianaseem/gtm-agent-eval-harness).
