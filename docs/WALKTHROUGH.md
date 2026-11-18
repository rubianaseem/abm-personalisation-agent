# Walk through it line by line

Five pieces carry the safety of this agent: how evidence expires, the order of exclusions, the order of contact checks, quote-grounding, and the model fallback. The approval gate (`abm/approval.py`) is described in docs/ARCHITECTURE.md.

## 1. Evidence expires (`abm/evidence.py`, `build_pack`)

```python
elif s["observed_at"] is None:
    reason = "UNDATED"
elif s["observed_at"] > now:
    reason = "FUTURE_DATED"
elif (now - s["observed_at"]).days > max_age[st]:
    reason = "STALE"
```

- `observed_at` was parsed in `ingest.py`. If it could not be parsed it is `None`, and an undated signal can't prove it is current, so it is dropped rather than guessed.
- A date after `now` is a data error (a planned round, a typo). Dropped.
- `max_age[st]` comes from `signal_max_age_days` in `config/policy.json`, per signal type. A job post goes stale after 45 days, a funding round after 180.
- Before these checks, `screen()` runs on the value and the text. If either reads like instructions ("ignore previous instructions", "note to the AI") the signal is `QUARANTINED_INJECTION` and its text is never copied anywhere.
- Survivors are sorted newest first and numbered `E1, E2, ...`. Those ids are what drafts must cite.

## 2. Exclusions before scores (`abm/tiering.py`, `decide`)

```python
if account["relationship"] == "competitor":
    return {"decision": "EXCLUDE_COMPETITOR", ...}
if account["relationship"] == "customer":
    return {"decision": "EXCLUDE_CUSTOMER", ...}
fam = customer_family(account, customer_domains)
```

- The function returns early. A competitor with three fresh signals never reaches the scoring lines, so no weighting mistake can promote it.
- `customer_family` checks `parent_domain` and subdomains (`eu.globex.example` belongs to `globex.example`). It can't see a subsidiary on an unrelated domain with no parent set; held-out case H03 shows that miss.
- Open deals are held for their owner. "Closed Lost" is in `open_deal_closed_stages`, so a lost deal does not block a new play.
- Only then: fit points plus intent points (distinct fresh intent types, capped at 3) pick the tier. `apply_tier1_cap` demotes the weakest 1:1 accounts when there are more than `max_tier1_accounts`.

## 3. Contact checks, most restrictive first (`abm/contacts.py`, `decide_contact`)

```python
if c["email_opt_out"]:
    return {**base, "action": "SUPPRESS_OPT_OUT", "reason": "EMAIL_OPT_OUT_FLAG"}
...
hit = next((p for p in policy["note_optout_phrases"] if p in notes_l), None)
```

- Contact-level suppression runs before the account's decision is inherited. An opted-out person at a competitor is recorded as an opt-out, the stronger fact.
- `next(...)` returns the first opt-out phrase found in the notes, or `None`. The phrase list is English only (held-out H01 and H04 show the cost).
- Duplicates were merged in `ingest.py` with `or` on the flags, so one "yes" anywhere wins.
- Lawful basis must be one of `email_lawful_bases_allowed`. A blank basis is a hold, not a guess.

## 4. Quote-grounding (`abm/validate.py`)

```python
def _quoted(item: dict, sentence: str) -> bool:
    sl = _norm(sentence)
    if item["value"] and _norm(item["value"]) in sl:
        return True
    return bool(item["text"]) and bool(_shingles(item["text"], 5) & _shingles(sentence, 5))
```

- `_norm` lower-cases and collapses spaces, so "Series B (GBP 30M)" matches regardless of spacing.
- For free-text evidence, `_shingles(text, 5)` is the set of every 5-word run. Sharing one run with the sentence counts as a quote.

```python
e_cites = [c for c in cites if c.startswith("E")]
if not e_cites and s["text"] not in [ctx["claims"][c] for c in cites]:
    errs.append("CLAIM_NOT_VERBATIM")
if e_cites and not any(_quoted(ev_by_id[c], s["text"]) for c in e_cites):
    errs.append("EVIDENCE_NOT_QUOTED")
```

- A sentence citing only brand claims must be one of those claims, word for word. That is how "teams like yours cut routing errors by 63 percent" fails even though it cites C1.
- A sentence citing evidence must actually contain it. Citing E1 and then saying something else fails.
- Further checks then look for numbers and capitalised names that are not in the cited text, other account names, PII, links, injection markers and quarantined text.

## 5. The model can only lose (`abm/drafting.py`, `draft_email`)

```python
model_errors = validate_draft(cand, ctx)
if not model_errors:
    cand["validation"] = {"errors": [], "model_errors": [], "warnings": soft_warnings(cand, ctx)}
    return cand
errs = validate_draft(tmpl, ctx)
tmpl["validation"] = {"errors": errs, "model_errors": model_errors, "warnings": []}
return tmpl
```

- The template draft is built first, always. The model is an upgrade attempt, never a dependency.
- A model draft is returned only with zero errors. Otherwise the template is returned and the model's errors travel with it into `review_queue.csv` as `MODEL_FALLBACK`.
- `soft_warnings` counts words beyond the quoted evidence. Three or more means `READ_CLOSELY`: the draft is allowed, but a reviewer is told to check every reason it gives.
- `call_with_retry` (in `llm.py`) returns `None` after its retry budget, and `None` becomes `MODEL_UNAVAILABLE`. A 429 storm never stops the run.

## Try it

```bash
python -m unittest tests.test_contacts_drafts -v
python agent.py run --out outputs/run_local && less outputs/run_local/review_queue.csv
```
