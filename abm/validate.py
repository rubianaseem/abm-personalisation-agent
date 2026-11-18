"""Output guardrails for every draft, whether a template or a model wrote it.

A draft is a list of typed sentences. Checks, in order:
  schema          - known kinds, non-empty text
  fixed lines     - greeting, call to action and sign-off must match the approved wording exactly
  quote-grounding - a claim citing evidence must quote the cited value word for word (or a 5-word run of
                    cited free text); a claim citing only brand claims must BE that approved claim, verbatim
  citations       - every claim sentence cites at least one evidence id (E*) from THIS account's pack or an
                    approved brand claim (C*); unknown ids fail
  product claims  - a sentence naming our product must be an approved claim, word for word
  grounding       - numbers and capitalised names in a claim sentence must appear in the text it cites
  brand           - banned phrases anywhere (subject included)
  cross-account   - no other account's name anywhere (the "emailed the wrong company" failure)
  PII             - no email addresses, phone numbers or other contacts' full names
  links           - only allow-listed URLs
  injection       - no instruction-like text and no 6-word run copied from quarantined source text
  placeholders    - no {{tokens}}, [First Name] or an empty greeting
  length          - subject characters, body words, ad and landing limits from brand_rules.json
A failing model draft is replaced by the template draft (which is validated too). Failing that, it goes to review.
"""
from __future__ import annotations

import re

from .untrusted import EMAIL_IN_TEXT, PHONE_IN_TEXT, URL_IN_TEXT, injection_markers

KINDS = {"greeting", "claim", "cta", "signoff", "headline"}
NUM_RE = re.compile(r"\d[\d.,]*\s?[a-zA-Z%]*")
CAP_RE = re.compile(r"\b[A-Z][a-zA-Z0-9&'-]+")
PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\[(first ?name|company|name|account)\]|<first_?name>", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _shingles(text: str, n: int = 6) -> set[str]:
    w = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def _word_in(name: str, text: str) -> bool:
    return bool(name) and re.search(r"(?<![\w-])" + re.escape(name.lower()) + r"(?![\w-])", text.lower()) is not None


def _quoted(item: dict, sentence: str) -> bool:
    """Quote-grounding: the sentence must carry the cited value word for word, or a 5-word run of the cited free text."""
    sl = _norm(sentence)
    if item["value"] and _norm(item["value"]) in sl:
        return True
    return bool(item["text"]) and bool(_shingles(item["text"], 5) & _shingles(sentence, 5))


def validate_draft(draft: dict, ctx: dict) -> list[str]:
    errs: list[str] = []
    brand, limits = ctx["brand"], ctx["brand"]["limits"]
    sents = draft.get("sentences")
    if not isinstance(sents, list) or not sents:
        return ["SCHEMA_NO_SENTENCES"]
    for s in sents:
        if not isinstance(s, dict) or s.get("kind") not in KINDS or not isinstance(s.get("text"), str) or not s["text"].strip():
            return ["SCHEMA_BAD_SENTENCE"]
        if not isinstance(s.get("cites", []), list) or not all(isinstance(c, str) for c in s.get("cites", [])):
            return ["SCHEMA_BAD_CITES"]
    header = draft.get("subject") or draft.get("headline") or ""
    full = " ".join([header] + [s["text"] for s in sents])
    low = full.lower()

    # fixed lines
    if draft["asset"] == "email":
        for s in sents:
            if s["kind"] == "greeting" and s["text"] not in ctx["allowed_greetings"]:
                errs.append("GREETING_NOT_APPROVED")
            if s["kind"] == "cta" and s["text"] != ctx["cta_text"]:
                errs.append("CTA_NOT_APPROVED")
            if s["kind"] == "signoff" and s["text"] != ctx["signoff"]:
                errs.append("SIGNOFF_NOT_APPROVED")
            if s["kind"] == "headline":
                errs.append("HEADLINE_IN_EMAIL")
        if not any(s["kind"] == "claim" for s in sents):
            errs.append("NO_CLAIM_SENTENCE")

    # citations + grounding
    known = {**{i["id"]: (i["value"] + " " + i["text"]) for i in ctx["evidence"]}, **ctx["claims"]}
    ev_by_id = {i["id"]: i for i in ctx["evidence"]}
    allowed_caps = {w.lower() for w in brand["common_capitalised_words"]}
    for tok in re.findall(r"[A-Za-z0-9&'-]+", " ".join([ctx["company_name"], ctx.get("first_name", ""),
                                                      brand["product_name"], ctx.get("industry_label", "")])):
        allowed_caps.add(tok.lower())
    for s in sents:
        if s["kind"] != "claim":
            continue
        cites = s.get("cites", [])
        if not cites:
            errs.append("CLAIM_WITHOUT_CITATION")
            continue
        bad = [c for c in cites if c not in known]
        if bad:
            errs.append(f"UNKNOWN_CITATION:{','.join(map(str, bad))}")
            continue
        if brand["product_name"].lower() in s["text"].lower() and s["text"] not in ctx["claims"].values():
            errs.append("PRODUCT_CLAIM_NOT_APPROVED")
        e_cites = [c for c in cites if c.startswith("E")]
        if not e_cites and s["text"] not in [ctx["claims"][c] for c in cites]:
            errs.append("CLAIM_NOT_VERBATIM")
        if e_cites and not any(_quoted(ev_by_id[c], s["text"]) for c in e_cites):
            errs.append("EVIDENCE_NOT_QUOTED")
        src = _norm(" ".join(known[c] for c in cites))
        for num in NUM_RE.findall(s["text"]):
            core = re.match(r"\d[\d.,]*", num).group(0).rstrip(".,")
            if core and core not in src:
                errs.append(f"UNGROUNDED_NUMBER:{core}")
        words = CAP_RE.findall(s["text"])
        for i, w in enumerate(words):
            if w.lower() in allowed_caps or s["text"].startswith(w) and i == 0:
                continue
            if w.lower() not in src:
                errs.append(f"UNGROUNDED_NAME:{w}")

    # brand
    for b in brand["banned_phrases"]:
        if b.lower() in low:
            errs.append(f"BANNED_PHRASE:{b}")
    # cross-account
    for name in ctx["other_company_names"]:
        if _word_in(name, full):
            errs.append("OTHER_ACCOUNT_NAMED")
            break
    # PII
    if EMAIL_IN_TEXT.search(full):
        errs.append("PII_EMAIL")
    if PHONE_IN_TEXT.search(full):
        errs.append("PII_PHONE")
    for name in ctx["other_person_names"]:
        if _word_in(name, full):
            errs.append("PII_OTHER_PERSON")
            break
    # links
    for url in URL_IN_TEXT.findall(full):
        if url.rstrip(".,)") not in brand["allowed_urls"]:
            errs.append("LINK_NOT_ALLOWED")
    # injection
    if injection_markers(full):
        errs.append("INJECTION_MARKER_IN_OUTPUT")
    q = set()
    for t in ctx["quarantined_texts"]:
        q |= _shingles(t)
    if q & _shingles(full):
        errs.append("QUARANTINED_TEXT_LEAK")
    # placeholders
    if PLACEHOLDER_RE.search(full) or re.search(r"\b(Hi|Hello)\s*,", full):
        errs.append("UNFILLED_PLACEHOLDER")
    # length
    if draft["asset"] == "email":
        if len(draft.get("subject", "")) > limits["email_subject_chars"] or not draft.get("subject"):
            errs.append("SUBJECT_LENGTH")
        if len(" ".join(s["text"] for s in sents).split()) > limits["email_body_words"]:
            errs.append("BODY_TOO_LONG")
    elif draft["asset"] == "ad":
        if len(draft.get("headline", "")) > limits["ad_headline_chars"]:
            errs.append("AD_HEADLINE_LENGTH")
        if len(" ".join(s["text"] for s in sents if s["kind"] == "claim")) > limits["ad_intro_chars"]:
            errs.append("AD_INTRO_LENGTH")
    elif draft["asset"] == "landing":
        if len(draft.get("headline", "")) > limits["landing_headline_chars"]:
            errs.append("LANDING_HEADLINE_LENGTH")
        if len(" ".join(s["text"] for s in sents if s["kind"] == "claim").split()) > limits["landing_subhead_words"]:
            errs.append("LANDING_SUBHEAD_LENGTH")
    return sorted(set(errs))


CONNECTIVES = set("""saw noticed the a an is at news now runs recruiting that on for to of and in i team congratulations
hiring role recently moved read recent your you we our with this it has have just""".split())


def soft_warnings(draft: dict, ctx: dict) -> list[str]:
    """Not a block: flags model sentences that add words beyond the quoted evidence, for a reviewer to read closely.

    A correct quote can be wrapped in an invented reason ("...because their routing keeps breaking"). The hard
    checks can't tell that from good copy, so model drafts with 3+ unexplained words per claim go to the review queue.
    """
    out = []
    ev = {i["id"]: i for i in ctx["evidence"]}
    allowed = set(re.findall(r"[a-z0-9']+", " ".join([ctx["company_name"], ctx.get("first_name", "")]).lower())) | CONNECTIVES
    for s in draft.get("sentences", []):
        cites = [c for c in s.get("cites", []) if c in ev]
        if s.get("kind") != "claim" or not cites:
            continue
        quoted = set(re.findall(r"[a-z0-9']+", " ".join(ev[c]["value"] + " " + ev[c]["text"] for c in cites).lower()))
        extra = [w for w in re.findall(r"[a-z0-9']+", s["text"].lower()) if w not in allowed and w not in quoted]
        if len(extra) >= 3:
            out.append(f"MODEL_UNQUOTED_WORDS:{len(extra)}")
    return out
