#!/usr/bin/env python3
"""Validate structural invariants of the Kerr Solver TaskPlanner board."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK_RE = re.compile(r"^## (TASK-(\d{3})): (.+)$", re.MULTILINE)
DEP_RE = re.compile(r"^- \*\*Blocked by:\*\* (.+)$", re.MULTILINE)
TAG_RE = re.compile(r"^\*\*Priority:\*\* (P[0-4]) \| \*\*Tags:\*\* ([^\n]+)$", re.MULTILINE)
REQUIRED_SECTIONS = ("### Objective", "### Acceptance Criteria", "### Dependencies", "### Evidence Output", "### Verification", "### Review Focus", "### Plan")
EXPECTED_RANGES = {
    "M01": range(1, 6), "M02": range(6, 12), "M03": range(12, 18),
    "M04": range(18, 24), "M05": range(24, 30), "M06": range(30, 37),
    "M07": range(37, 42), "M08": range(42, 48), "M09": range(48, 54),
    "M10": range(54, 59), "M11": range(59, 64), "M12": range(64, 69),
}


def sections(text: str) -> list[tuple[str, int, str, str]]:
    matches = list(TASK_RE.finditer(text))
    return [
        (match.group(1), int(match.group(2)), match.group(3),
         text[match.start():(matches[index + 1].start() if index + 1 < len(matches) else len(text))])
        for index, match in enumerate(matches)
    ]


def main() -> int:
    errors: list[str] = []
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if config.get("version") != 2:
        errors.append("config schema version must be 2")
    if config.get("taskplannerVersion") != "2.1.1":
        errors.append("TaskPlanner version must be 2.1.1")

    all_tasks: dict[int, tuple[str, str, str]] = {}
    by_state: dict[str, list[int]] = {}
    edges: dict[int, set[int]] = defaultdict(set)

    for state, filename in config["states"].items():
        path = ROOT / filename
        if not path.is_file():
            errors.append(f"missing state file: {filename}")
            continue
        parsed = sections(path.read_text(encoding="utf-8"))
        by_state[state] = [number for _, number, _, _ in parsed]
        for task_id, number, title, body in parsed:
            if number in all_tasks:
                errors.append(f"duplicate task ID: {task_id}")
            all_tasks[number] = (state, title, body)
            if not TAG_RE.search(body):
                errors.append(f"{task_id} lacks canonical priority/tags line")
            for heading in REQUIRED_SECTIONS:
                if heading not in body:
                    errors.append(f"{task_id} lacks {heading}")
            dep_match = DEP_RE.search(body)
            if not dep_match:
                errors.append(f"{task_id} lacks Blocked by line")
                continue
            for dep in re.findall(r"TASK-(\d{3})", dep_match.group(1)):
                edges[int(dep)].add(number)

    expected_ids = set(range(1, 69))
    actual_ids = set(all_tasks)
    if actual_ids != expected_ids:
        errors.append(f"task IDs differ from TASK-001–TASK-068: missing={sorted(expected_ids-actual_ids)}, extra={sorted(actual_ids-expected_ids)}")
    if config.get("nextId") != 69:
        errors.append("nextId must be 69")
    next_tasks = by_state.get("Next", [])
    in_progress = by_state.get("In Progress", [])
    done = sorted(by_state.get("Done", []))
    if len(in_progress) > 1:
        errors.append("at most one task may be In Progress")
    expected_done = list(range(1, len(done) + 1))
    if done != expected_done:
        errors.append("Done tasks must form one contiguous prefix from TASK-001")
    current = len(done) + 1
    if in_progress:
        if in_progress != [current]:
            errors.append(f"TASK-{current:03d} must be the sole In Progress task")
        if next_tasks:
            errors.append("Next must be empty while a task is In Progress")
    elif current <= max(expected_ids):
        if next_tasks != [current]:
            errors.append(f"TASK-{current:03d} must be the sole Next task")
    elif next_tasks:
        errors.append("Next must be empty when every task is Done")

    for milestone, numbers in EXPECTED_RANGES.items():
        for number in numbers:
            if number not in all_tasks:
                continue
            tag_match = TAG_RE.search(all_tasks[number][2])
            tags = [tag.strip() for tag in tag_match.group(2).split(",")] if tag_match else []
            if milestone not in tags:
                errors.append(f"TASK-{number:03d} must carry milestone tag {milestone}")

    for source, destinations in edges.items():
        if source not in all_tasks:
            errors.append(f"dependency references missing TASK-{source:03d}")
        for destination in destinations:
            if source >= destination:
                errors.append(f"TASK-{destination:03d} depends on non-earlier TASK-{source:03d}")

    indegree = {number: 0 for number in all_tasks}
    for destinations in edges.values():
        for destination in destinations:
            indegree[destination] += 1
    queue = deque(sorted(number for number, degree in indegree.items() if degree == 0))
    visited = []
    while queue:
        node = queue.popleft()
        visited.append(node)
        for destination in sorted(edges.get(node, ())):
            indegree[destination] -= 1
            if indegree[destination] == 0:
                queue.append(destination)
    if len(visited) != len(all_tasks):
        errors.append("task dependency graph contains a cycle")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "TaskPlanner board valid: "
        f"68 unique tasks, 12 milestones, {len(done)} Done, "
        f"{len(next_tasks)} Next, {len(in_progress)} In Progress, "
        "acyclic dependencies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
