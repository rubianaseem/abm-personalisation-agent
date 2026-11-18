"""Boundary for untrusted free text: account research notes, website snippets and contact notes.

Research notes are pasted by whoever did the research, and website snippets are scraped from pages anyone can edit.
Both are data, never instructions. Before any of that text is used:
  1. injection_markers(): text that reads like instructions to a model or a writer is QUARANTINED.
     Quarantined text never reaches a prompt, a draft, the trace or any output file except as a count.
  2. Text that passes is redacted (emails, phone numbers, links), truncated and wrapped as data (wrap_untrusted).
Pattern lists are a first layer, not a guarantee. The held-out eval cases show paraphrases that get past them,
which is why the output validator (validate.py) independently checks drafts for leaked text, links and claims.
Adapted from my hubspot-admin-agent.
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above|earlier|your) (instructions|rules|prompts?|guidelines)",
    r"disregard (the |all |any )?(previous|prior|above|system|rules|instructions|brand)",
    r"\bsystem prompt\b", r"(^|\n)\s*system\s*:", r"\bassistant\s*:",
    r"\byou are now\b", r"\bact as\b", r"\bnew instructions?\b",
    r"\b(note|message|instruction)s? (to|for) (the |any )?(ai|assistant|model|llm|bot|agent|copywriter)\b",
    r"\b(ai|llm|model|assistant|agent)s? (must|should) (say|write|mention|include|add|state)\b",
    r"\b(approve|auto-?approve|bypass|override|skip)\b.*\b(approval|review|guardrails?|checks?|gate)\b",
    r"<\s*/?\s*(system|assistant|instructions?|untrusted[^>]*)\s*>",
    r"\bBEGIN (ADMIN|SYSTEM|PROMPT)\b", r"\bexfiltrat", r"\bapi[_ ]?key\b", r"\baccess token\b",
    r"\b(send|forward|email) (the |your |all )?(contact list|contacts|list|data|emails?) to\b",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL_IN_TEXT = re.compile(r"https?://\S+|www\.\S+", re.I)
PHONE_IN_TEXT = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d")


def injection_markers(text: str) -> list[str]:
    return [p.pattern for p in _INJ if p.search(text or "")]


def redact(text: str) -> str:
    text = EMAIL_IN_TEXT.sub("[email]", text or "")
    text = PHONE_IN_TEXT.sub("[phone]", text)
    return URL_IN_TEXT.sub("[link]", text)


def screen(text: str, limit: int = 400) -> dict:
    """Classify one piece of free text. Returns status: empty | clean | quarantined."""
    t = (text or "").strip()
    if not t:
        return {"status": "empty", "markers": [], "safe_text": ""}
    inj = injection_markers(t)
    if inj:
        return {"status": "quarantined", "markers": inj, "safe_text": ""}
    return {"status": "clean", "markers": [], "safe_text": redact(t)[:limit]}


def wrap_untrusted(label: str, text: str) -> str:
    """Wrap screened text so the prompt treats it as quoted data, never as instructions."""
    cleaned = text.replace("<", "(").replace(">", ")")
    return f"<untrusted_{label}>\n{cleaned}\n</untrusted_{label}>"
