#!/usr/bin/env python3
"""Build the canonical redacted PR74 live-checkpoint handover fixture.

The source is the archived operator checkpoint identified in the adjacent
manifest.  This tool removes machine-private paths and re-authenticates every
checkpoint container affected by that redaction.  It never changes numerical
values, queue order, retained work, or scientific identities.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import lzma
from pathlib import Path
from typing import Any, Mapping

from windows_solver.campaign_policy import (
    promotion_source_fingerprint_sha256,
    validate_schema11_checkpoint,
)
from windows_solver.contracts import canonical_json_bytes


SOURCE_SHA256 = "35dab16bd0f29a6bb05509f5bda4dac73996c6afd67205b609d4dc44fc5063f2"
SOURCE_ROOT = (
    r"C:\Users\vbrod\Downloads\Kerr-QNM_Windows-Solver-main"
    r"\Kerr-QNM_Windows-Solver-main"
)
RUNTIME_ROOT = r"C:\Users\vbrod\AppData\Local\Kerr-QNM_Windows-Solver\runtime-1"
SOURCE_ROOT_TOKEN = "$PR74_SOURCE_ROOT"
RUNTIME_ROOT_TOKEN = "$PR74_RUNTIME_ROOT"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_mapping(value: Mapping[str, object], digest_field: str) -> str:
    return _sha256_bytes(canonical_json_bytes({
        key: item for key, item in value.items() if key != digest_field
    }))


def _redact_strings(value: Any, counts: dict[str, int]) -> Any:
    if isinstance(value, dict):
        return {key: _redact_strings(item, counts) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_strings(item, counts) for item in value]
    if not isinstance(value, str):
        return value
    redacted = value
    for source, token, label in (
        (SOURCE_ROOT, SOURCE_ROOT_TOKEN, "source_root"),
        (RUNTIME_ROOT, RUNTIME_ROOT_TOKEN, "runtime_root"),
    ):
        occurrences = redacted.count(source)
        if occurrences:
            counts[label] += occurrences
            redacted = redacted.replace(source, token)
    return redacted


def _reauthenticate_calculation_artifact(artifact: dict[str, Any]) -> None:
    component_stage = artifact.get("component_stage")
    if isinstance(component_stage, dict) and "stage_sha256" in component_stage:
        component_stage["stage_sha256"] = _sha256_mapping(
            component_stage, "stage_sha256"
        )
        if "component_stage_sha256" in artifact:
            artifact["component_stage_sha256"] = component_stage["stage_sha256"]
    if "calculation_sha256" in artifact:
        artifact["calculation_sha256"] = _sha256_mapping(
            artifact, "calculation_sha256"
        )


def _reauthenticate_stage(
    stage: dict[str, Any],
    *,
    source_fingerprint_sha256: str,
    source_stage_sha256: str | None,
) -> None:
    chain = stage.get("calculation_chain")
    expected_source: str | None = None
    if isinstance(chain, list):
        for predecessor in chain:
            if not isinstance(predecessor, dict):
                raise ValueError("archived promoted chain is invalid")
            predecessor["source_fingerprint_sha256"] = source_fingerprint_sha256
            predecessor["predecessor_stage_sha256"] = source_stage_sha256
            predecessor["source_calculation_stage_sha256"] = expected_source
            artifact = predecessor.get("calculation_artifact")
            if isinstance(artifact, dict):
                _reauthenticate_calculation_artifact(artifact)
            predecessor["stage_sha256"] = _sha256_mapping(
                predecessor, "stage_sha256"
            )
            expected_source = predecessor["stage_sha256"]
    stage["source_fingerprint_sha256"] = source_fingerprint_sha256
    stage["predecessor_stage_sha256"] = source_stage_sha256
    stage["source_calculation_stage_sha256"] = expected_source
    artifact = stage.get("calculation_artifact")
    if isinstance(artifact, dict):
        _reauthenticate_calculation_artifact(artifact)
    stage["stage_sha256"] = _sha256_mapping(stage, "stage_sha256")


def redact_checkpoint(source: Mapping[str, object]) -> tuple[dict[str, Any], dict[str, int]]:
    counts = {"source_root": 0, "runtime_root": 0}
    checkpoint = _redact_strings(copy.deepcopy(dict(source)), counts)
    entries = checkpoint["promotion_queue"]["entries"]

    for entry in entries:
        provisional = entry.get("provisional_stage")
        if isinstance(provisional, dict):
            provisional["stage_sha256"] = _sha256_mapping(
                provisional, "stage_sha256"
            )
            entry["provisional_stage_sha256"] = provisional["stage_sha256"]
            entry["source_stage_sha256"] = provisional["stage_sha256"]
        entry["source_fingerprint_sha256"] = (
            promotion_source_fingerprint_sha256(entry)
        )

    stage_ledger = checkpoint["promoted_stage_ledger"]
    for ordinal_text, bucket in stage_ledger.items():
        ordinal = int(ordinal_text)
        entry = entries[ordinal]
        for stage in bucket.values():
            _reauthenticate_stage(
                stage,
                source_fingerprint_sha256=entry["source_fingerprint_sha256"],
                source_stage_sha256=entry["source_stage_sha256"],
            )
            entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
            redaction_receipt = {
                "schema": "windows-solver.fixture-redaction-receipt/1",
                "source_checkpoint_sha256": SOURCE_SHA256,
                "queue_ordinal": ordinal,
                "retained_promoted_stage_sha256": stage["stage_sha256"],
                "source_fingerprint_sha256": entry[
                    "source_fingerprint_sha256"
                ],
            }
            entry["disposition_receipt_sha256"] = _sha256_bytes(
                canonical_json_bytes(redaction_receipt)
            )

    for failure in checkpoint["system_failures"]:
        failure["receipt_sha256"] = _sha256_mapping(failure, "receipt_sha256")

    report = checkpoint.get("report_status_receipt")
    if isinstance(report, dict) and "receipt_sha256" in report:
        report["receipt_sha256"] = _sha256_mapping(report, "receipt_sha256")

    validated = validate_schema11_checkpoint(checkpoint)
    return validated, counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    if _sha256_bytes(source_bytes) != SOURCE_SHA256:
        raise SystemExit("source checkpoint digest does not match the PR74 archive")
    source = json.loads(source_bytes)
    redacted, counts = redact_checkpoint(source)
    redacted_bytes = canonical_json_bytes(redacted)
    compressed = lzma.compress(redacted_bytes, preset=9 | lzma.PRESET_EXTREME)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(compressed)
    manifest = {
        "schema": "windows-solver.pr74-checkpoint-fixture-manifest/1",
        "source_checkpoint_sha256": SOURCE_SHA256,
        "redacted_checkpoint_sha256": _sha256_bytes(redacted_bytes),
        "compressed_fixture_sha256": _sha256_bytes(compressed),
        "redaction_method": "token-replace-private-roots-and-reauthenticate/v1",
        "replacement_tokens": [SOURCE_ROOT_TOKEN, RUNTIME_ROOT_TOKEN],
        "replacement_counts": counts,
        "forensic_history": {
            "request_schema": "windows-solver.fixed-root-survey-batch/1",
            "authority": "FORENSIC_ONLY",
            "source_system_failure_receipt_sha256": source[
                "system_failures"
            ][0]["receipt_sha256"],
            "redacted_system_failure_receipt_sha256": redacted[
                "system_failures"
            ][0]["receipt_sha256"],
            "failed_queue_ordinal": 1,
        },
        "preserved_invariants": [
            "all numerical values",
            "all 212 Binary64 records and queue entries",
            "all scientific identities",
            "all root and promoted numerical evidence",
            "queue order and retained-work accounting",
        ],
    }
    args.manifest.write_bytes(canonical_json_bytes(manifest) + b"\n")


if __name__ == "__main__":
    main()
