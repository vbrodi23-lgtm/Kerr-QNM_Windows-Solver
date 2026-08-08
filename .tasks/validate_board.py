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
    "M01": range(1, 6), "M02": (*range(6, 12), *range(69, 79)), "M03": range(12, 18),
    "M04": range(18, 24), "M05": range(24, 30), "M06": range(30, 37),
    "M07": range(37, 42), "M08": range(42, 48), "M09": range(48, 54),
    "M10": range(54, 59), "M11": range(59, 64), "M12": range(64, 69),
}


def _priority_rank(body: str) -> int | None:
    """Return the board ordering rank encoded in a task's canonical tag line."""

    match = TAG_RE.search(body)
    return int(match.group(1)[1:]) if match else None


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
    dependencies: dict[int, set[int]] = defaultdict(set)

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
                dependency = int(dep)
                edges[dependency].add(number)
                dependencies[number].add(dependency)

    next_id = config.get("nextId")
    if not isinstance(next_id, int) or next_id < 2:
        errors.append("nextId must be an integer greater than TASK-001")
        expected_ids: set[int] = set()
    else:
        expected_ids = set(range(1, next_id))
    actual_ids = set(all_tasks)
    if actual_ids != expected_ids:
        errors.append(
            "task IDs must be contiguous through the configured nextId: "
            f"missing={sorted(expected_ids-actual_ids)}, "
            f"extra={sorted(actual_ids-expected_ids)}"
        )
    next_tasks = by_state.get("Next", [])
    in_progress = by_state.get("In Progress", [])
    done = set(by_state.get("Done", []))
    if len(in_progress) > 1:
        errors.append("at most one task may be In Progress")

    def dependency_ready(number: int) -> bool:
        return dependencies[number].issubset(done)

    pending = actual_ids - done - set(by_state.get("Rejected", []))
    ready = {number for number in pending if dependency_ready(number)}
    priority_by_task = {
        number: _priority_rank(body) for number, (_, _, body) in all_tasks.items()
    }

    def scheduling_key(number: int) -> tuple[int, int]:
        priority = priority_by_task[number]
        fallback_priority = len(config["priorities"])
        return (priority if priority is not None else fallback_priority, number)

    selected_ready = min(ready, key=scheduling_key) if ready else None
    highest_ready_priority = (
        scheduling_key(selected_ready)[0] if selected_ready is not None else None
    )
    if in_progress:
        active = in_progress[0]
        if not dependency_ready(active):
            errors.append(f"TASK-{active:03d} is not dependency-ready")
        if (
            highest_ready_priority is not None
            and priority_by_task[active] != highest_ready_priority
        ):
            errors.append("In Progress task must have the highest ready priority")
        if next_tasks:
            errors.append("Next must be empty while a task is In Progress")
    elif ready:
        if len(next_tasks) != 1:
            errors.append("exactly one dependency-ready task must be Next when idle")
        else:
            candidate = next_tasks[0]
            if candidate not in ready:
                errors.append(f"TASK-{candidate:03d} is not dependency-ready")
            elif candidate != selected_ready:
                errors.append(
                    f"TASK-{selected_ready:03d} must be the sole Next task "
                    "(lowest task ID at the highest ready priority)"
                )
    elif next_tasks:
        errors.append("Next must be empty when no pending task is dependency-ready")

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
        f"{len(actual_ids)} unique tasks, 12 milestones, {len(done)} Done, "
        f"{len(next_tasks)} Next, {len(in_progress)} In Progress, "
        "acyclic dependencies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
