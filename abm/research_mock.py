"""MOCKED firmographic lookup used to fill blank employee counts and industries. No network, no vendor.

Why it exists: real enrichment (Clay, Apollo, ZoomInfo, a website scraper) fails in boring ways: 429s with
Retry-After, timeouts, 5xx, partial batches, a crash half way through. This mock reproduces those so the retry,
checkpoint and resume code is tested. It only FILLS blanks; it never overwrites a CRM value, and every filled
field is labelled with its source so tiering reasons stay explainable.
This repo never calls Clay or any paid API. See docs/DETAILS.md for swapping in a real provider.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path


class ResearchError(Exception):
    def __init__(self, msg: str, retryable: bool, retry_after: float | None = None):
        super().__init__(msg)
        self.retryable, self.retry_after = retryable, retry_after


class MockFirmographics:
    """data: {domain: {employees, industry}}. failures: {domain: [ResearchError or 'crash', ...]} consumed per call."""

    def __init__(self, data: dict, failures: dict | None = None):
        self.data = data
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.calls: list[str] = []

    def lookup(self, domain: str) -> dict:
        self.calls.append(domain)
        queue = self.failures.get(domain)
        if queue:
            item = queue.pop(0)
            if item == "crash":
                raise KeyboardInterrupt("simulated crash")
            raise item
        if domain not in self.data:
            raise ResearchError("not_found", False)
        return dict(self.data[domain])


def load_mock(path: str | Path) -> MockFirmographics:
    return MockFirmographics(json.loads(Path(path).read_text())["companies"])


def fill_missing(accounts: dict, api, checkpoint_path: str | Path, *, attempts: int = 4, base_delay: float = 0.5,
                 sleep=time.sleep, log=None) -> dict:
    """Fill blank employees/industry. Idempotent: domains in the checkpoint are not looked up again on resume."""
    cp_path = Path(checkpoint_path)
    cp = json.loads(cp_path.read_text()) if cp_path.exists() else {"done": {}, "failed": {}}
    stats = {"looked_up": 0, "from_checkpoint": 0, "filled_fields": 0, "failed": 0, "retries": 0}
    for key in sorted(accounts):
        acc = accounts[key]
        dom = acc["domain"]
        if not dom or (acc["employees"] is not None and acc["industry"]):
            continue
        if dom in cp["done"]:
            result = cp["done"][dom]
            stats["from_checkpoint"] += 1
        elif dom in cp["failed"]:
            stats["failed"] += 1
            continue
        else:
            result = None
            for attempt in range(1, attempts + 1):
                try:
                    result = api.lookup(dom)
                    break
                except ResearchError as exc:
                    if log:
                        log({"event": "research_error", "domain": dom, "attempt": attempt, "error": str(exc)})
                    if not exc.retryable or attempt == attempts:
                        break
                    stats["retries"] += 1
                    delay = exc.retry_after if exc.retry_after else base_delay * 2 ** (attempt - 1)
                    sleep(delay + random.uniform(0, delay * 0.1))
            stats["looked_up"] += 1
            if result is None:
                cp["failed"][dom] = "lookup_failed"
                stats["failed"] += 1
                _save(cp_path, cp)
                continue
            cp["done"][dom] = result
            _save(cp_path, cp)  # checkpoint after every domain so a crash loses at most one lookup
        filled = acc.setdefault("filled_fields", {})
        if acc["employees"] is None and result.get("employees") is not None:
            acc["employees"] = int(result["employees"]); filled["employees"] = "mock_research"; stats["filled_fields"] += 1
        if not acc["industry"] and result.get("industry"):
            acc["industry"] = str(result["industry"]).lower(); filled["industry"] = "mock_research"; stats["filled_fields"] += 1
    return stats


def _save(path: Path, cp: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp, indent=2, sort_keys=True))
    tmp.replace(path)
