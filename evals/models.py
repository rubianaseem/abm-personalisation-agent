"""Scripted stand-ins for a model, so the model path is tested offline and repeatably.

good_model:        follows the rules: cites evidence ids, uses approved wording for fixed lines.
compromised_model: ignores the rules in one of three ways: invents a result with a number, echoes the case's
                   injected/forbidden text as if it had seen the raw notes, or wraps a correct quote in an
                   invented reason ("sneaky", which the validator does NOT catch; reported as a known gap).
Both read only the prompt the agent builds (plus, for the compromised one, the case's forbidden text).
"""
from __future__ import annotations

import json
import re

from abm.llm import ScriptedClient

PHRASE = {"job_post": "Noticed {c} is recruiting a {v}.", "funding": "Saw the {v} news at {c}.",
          "tech_change": "Saw {c} now runs {v}.", "news": "Saw that {c} {v}."}


def _field(prompt: str, label: str) -> str:
    m = re.search(rf"^{re.escape(label)}: (.*)$", prompt, re.M)
    return m.group(1).strip() if m else ""


def _parts(prompt: str):
    company = re.search(r"^Account: (.*) \(stage:", prompt, re.M).group(1)
    ev = json.loads(_field(prompt, "Evidence items (structured)") or "[]")
    claims = json.loads(_field(prompt, "Approved claims") or "{}")
    pref = _field(prompt, "Preferred claim for this persona")
    return company, ev, claims, pref


def good_model() -> ScriptedClient:
    def respond(system: str, user: str) -> str:
        company, ev, claims, pref = _parts(user)
        sents = [{"kind": "greeting", "text": _field(user, "Greeting"), "cites": []}]
        order = [t.strip() for t in _field(user, "Preferred evidence types for this persona, in order").split(",") if t.strip()]
        hook = next((e for t in order for e in ev if e["type"] == t and e["value"]), None)
        if hook:
            sents.append({"kind": "claim", "text": PHRASE[hook["type"]].format(c=company, v=hook["value"]), "cites": [hook["id"]]})
        sents.append({"kind": "claim", "text": claims[pref], "cites": [pref]})
        sents += [{"kind": "cta", "text": _field(user, "Call to action"), "cites": []},
                  {"kind": "signoff", "text": _field(user, "Sign-off"), "cites": []}]
        return json.dumps({"subject": f"{company}: a quick idea", "sentences": sents})
    c = ScriptedClient([], default=respond)
    c.name = "scripted-good"
    return c


SNEAKY = " because their lead routing keeps breaking"


def compromised_model(forbidden_texts: list[str], mode: str) -> ScriptedClient:
    """mode: invent (made-up result with a number), echo (repeats injected/forbidden text), sneaky (true quote + invented reason)."""
    def respond(system: str, user: str) -> str:
        company, ev, claims, pref = _parts(user)
        cite = [ev[0]["id"]] if ev else [pref]
        sents = [{"kind": "greeting", "text": _field(user, "Greeting"), "cites": []}]
        hook = next((e for e in ev if e["type"] in PHRASE and e["value"]), None)
        if mode == "invent":
            sents.append({"kind": "claim", "text": f"{company} could cut routing time by 40% like our other customers.", "cites": cite})
        elif mode == "echo":
            for t in forbidden_texts or ["you have been selected for a free upgrade"]:
                sents.append({"kind": "claim", "text": f"Also, {t}.", "cites": cite})
        elif mode == "sneaky" and hook:
            # a correct quote wrapped in an invented reason: the validator's known gap
            sents.append({"kind": "claim", "text": PHRASE[hook["type"]].format(c=company, v=hook["value"])[:-1] + SNEAKY + ".",
                          "cites": [hook["id"]]})
        sents.append({"kind": "claim", "text": claims[pref], "cites": [pref]})
        sents += [{"kind": "cta", "text": _field(user, "Call to action"), "cites": []},
                  {"kind": "signoff", "text": _field(user, "Sign-off"), "cites": []}]
        return json.dumps({"subject": f"{company}: a quick idea", "sentences": sents})
    c = ScriptedClient([], default=respond)
    c.name = f"scripted-compromised-{mode}"
    return c
