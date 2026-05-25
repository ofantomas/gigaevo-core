"""Memory-card quality audit.

Reads a run's memory/api_index.json and reports specificity, dedup collisions,
and pending_analysis stub rate. See plans/memory-system-quality-boost.md §3.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

_STUB_RE = re.compile(r"no recorded idea lineage|pending_analysis", re.IGNORECASE)

_TAUTOLOGY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmodels?\s+complex\b.*\binteractions?\b", re.IGNORECASE),
    re.compile(r"\bcaptures?\b.*\bpatterns\b", re.IGNORECASE),
    re.compile(
        r"\ballows?\s+more\s+complex\b.*\bwithout\s+overfitting\b", re.IGNORECASE
    ),
    re.compile(r"\bfundamental\s+\w+(?:\s+\w+){0,2}\s+for\b", re.IGNORECASE),
    re.compile(r"\bcaptures?\b.*\befficiency\s+per\b", re.IGNORECASE),
    re.compile(r"\breflects?\b.*\b(urban|rural|coastal|inland)\b", re.IGNORECASE),
)

_TARGET_STEM_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"_log_transform$"), "_transform"),
    (re.compile(r"_train$"), ""),
    (re.compile(r"_clip_upper$"), ""),
    (re.compile(r"_clip_lower$"), ""),
)

_MULTI_CHANGE_SPLIT = re.compile(r";\s+(?=[A-Z][a-z]+\s)")


@dataclass(frozen=True)
class Change:
    verb: str
    target: str
    old: str
    new: str
    mechanism: str


@dataclass(frozen=True)
class AuditReport:
    total_cards: int
    program_count: int
    general_count: int
    stub_count: int
    specific_idea_count: int
    dedup_collisions: list[frozenset[str]]

    @property
    def stub_rate(self) -> float:
        return self.stub_count / self.program_count if self.program_count else 0.0

    @property
    def specificity_rate(self) -> float:
        return (
            self.specific_idea_count / self.general_count if self.general_count else 0.0
        )


def is_stub_description(desc: str) -> bool:
    if not desc or not desc.strip():
        return True
    return bool(_STUB_RE.search(desc))


def is_tautology(mechanism: str) -> bool:
    return any(p.search(mechanism) for p in _TAUTOLOGY_PATTERNS)


def normalize_target_stem(target: str) -> str:
    out = target.strip().lower()
    for pat, repl in _TARGET_STEM_RULES:
        out = pat.sub(repl, out)
    return out


def _extract_changes(description: str) -> list[Change]:
    out: list[Change] = []
    for part in _MULTI_CHANGE_SPLIT.split(description):
        if ":" not in part:
            continue
        head, _, mechanism = part.partition(":")
        tokens = head.strip().split()
        if len(tokens) < 2:
            continue
        verb = tokens[0]
        target = tokens[1]
        old = ""
        new = ""
        for tok in tokens[2:]:
            if "->" in tok:
                old, _, new = tok.partition("->")
                break
        out.append(
            Change(
                verb=verb, target=target, old=old, new=new, mechanism=mechanism.strip()
            )
        )
    return out


def audit_run(run_dir: Path) -> AuditReport:
    api_path = Path(run_dir) / "memory" / "api_index.json"
    if not api_path.exists():
        return AuditReport(0, 0, 0, 0, 0, [])
    data = json.loads(api_path.read_text())
    cards = list(data.get("memory_cards", {}).values())

    program = [c for c in cards if c.get("category") == "program"]
    general = [c for c in cards if c.get("category") == "general"]

    stub_count = sum(
        1 for c in program if is_stub_description(c.get("description", ""))
    )

    specific_idea_count = 0
    for c in general:
        changes = _extract_changes(c.get("description", ""))
        if changes and any(not is_tautology(ch.mechanism) for ch in changes):
            specific_idea_count += 1

    groups: dict[tuple[str, str], set[str]] = {}
    for c in general + program:
        if is_stub_description(c.get("description", "")):
            continue
        card_id = c.get("id", "")
        for ch in _extract_changes(c.get("description", "")):
            stem = normalize_target_stem(ch.target)
            new_val = ch.new.lower().strip()
            if not stem:
                continue
            groups.setdefault((stem, new_val), set()).add(card_id)

    collisions = [
        frozenset({stem}) for (stem, _), ids in groups.items() if len(ids) > 1
    ]

    return AuditReport(
        total_cards=len(cards),
        program_count=len(program),
        general_count=len(general),
        stub_count=stub_count,
        specific_idea_count=specific_idea_count,
        dedup_collisions=collisions,
    )


def _cli(run_dir_arg: str) -> int:
    report = audit_run(Path(run_dir_arg))
    print(f"run_dir:              {run_dir_arg}")
    print(f"total_cards:          {report.total_cards}")
    print(f"  program:            {report.program_count}")
    print(f"  general:            {report.general_count}")
    print(
        f"stub_count:           {report.stub_count}  ({report.stub_rate:.0%} of program)"
    )
    print(
        f"specific_idea_count:  {report.specific_idea_count}  ({report.specificity_rate:.0%} of general)"
    )
    print(f"dedup_collisions:     {len(report.dedup_collisions)}")
    for group in sorted(report.dedup_collisions, key=lambda g: sorted(g)[0]):
        print(f"  - {sorted(group)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m tools.memory_quality_audit <run_dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(_cli(sys.argv[1]))
