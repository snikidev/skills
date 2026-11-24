"""Action cards: say what is about to happen, how, with which credential."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

RO = "READ-ONLY"
WRITE = "WRITE"
LOCAL = "LOCAL ONLY"


@dataclass
class Card:
    title: str
    why: str
    transport: str
    target: str
    credential: str
    mode: str
    rollback: str = "nothing to roll back (read-only)"
    changes: list[str] = field(default_factory=list)
    step: Optional[str] = None          # e.g. "2/5"
    remaining: list[str] = field(default_factory=list)

    def render(self) -> str:
        bar = "━" * 4
        head = f"{bar} ACTION{(' ' + self.step) if self.step else ''}: {self.title} {bar}"
        lines = [
            head,
            f"What & why:  {self.why}",
            f"Transport:   {self.transport}",
            f"Endpoint/cmd:{' ' if self.target else ''}{self.target}",
            f"Credential:  {self.credential}",
            f"Mode:        {self.mode}",
            f"Rollback:    {self.rollback}",
        ]
        if self.changes:
            lines.append("Changes:")
            lines.extend(f"  {c}" for c in self.changes)
        if self.remaining:
            lines.append("Remaining after this:")
            lines.extend(f"  - {r}" for r in self.remaining)
        return "\n".join(lines)


def show(card: Card) -> None:
    print(card.render(), flush=True)


def plan_id(plan: Any) -> str:
    """Stable short id for a planned change. Execute must quote it back."""
    blob = json.dumps(plan, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]


def gate(plan: Any, execute: bool, given: Optional[str]) -> bool:
    """Return True if the write may proceed. Prints instructions otherwise."""
    pid = plan_id(plan)
    if not execute:
        print(f"\nDRY RUN - nothing changed. Plan id: {pid}")
        print("After the user explicitly says go, re-run the same command with:")
        print(f"  --execute --plan {pid}")
        return False
    if given != pid:
        print(f"\nREFUSED: plan id mismatch (given {given!r}, current {pid}).")
        print("The live state or the arguments changed since the dry run.")
        print("Run the dry run again, show the new card to the user, get a new go.")
        raise SystemExit(3)
    return True


def result(ok: bool, summary: str, details: Optional[list[str]] = None) -> None:
    mark = "RESULT: OK" if ok else "RESULT: FAILED"
    print(f"\n{mark} - {summary}")
    for d in details or []:
        print(f"  {d}")
