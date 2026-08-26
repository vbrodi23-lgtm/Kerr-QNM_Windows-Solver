"""Structural guard for critical production-adapter capability wiring."""

from __future__ import annotations

import ast
import json
from pathlib import Path


_CAPABILITY_SUFFIXES = ("_lookup", "_resolver", "_store", "_provider")
_REQUIRED_CALLS = {
    "run_native_binary64_pass": {
        "run_binary64_survey": {
            "root_seal_lookup",
            "native_backend_factory",
            "provisional_stage_committed",
            "equivalence_receipt_lookup",
            "determinant_error_store",
            "background_evidence_store",
            "solved_leaf_store",
            "terminal_record_committed",
            "checkpoint_committed",
            "diagnostic_session",
        },
    },
    "run_native_promoted_pass": {
        "run_promoted_survey": {
            "root_seal_lookup",
            "layer1_guard",
            "locked_routes_by_ordinal",
            "promoted_preflights_by_ordinal",
            "layer1_lock_receipt_sha256",
            "root_seal_publish",
            "backend_factory",
            "determinant_error_store",
            "solved_leaf_store",
            "terminal_record_committed",
            "checkpoint_committed",
            "diagnostic_session",
        },
    },
    "run_native_promoted_admission": {
        "admit_retained_promoted_checkpoint": {
            "queue_ordinal",
            "independent_review_receipt",
            "expected_authority_sha256",
            "layer1_guard",
            "terminal_record_committed",
        },
    },
}


def _call_name(call: ast.Call) -> str | None:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _obvious_placeholder(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant):
        return value.value is None or value.value is False
    return (
        isinstance(value, ast.Lambda)
        and isinstance(value.body, ast.Constant)
        and (value.body.value is None or value.body.value is False)
    )


def validate_production_wiring(path: Path | None = None) -> dict[str, object]:
    runtime = path or Path(__file__).with_name("campaign_runtime.py")
    tree = ast.parse(runtime.read_text(encoding="utf-8"), filename=str(runtime))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    failures: list[str] = []
    checked_dependencies = 0
    for function_name, required_calls in _REQUIRED_CALLS.items():
        function = functions.get(function_name)
        if function is None:
            failures.append(f"missing production adapter {function_name}")
            continue
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
        for call_name, required_keywords in required_calls.items():
            matches = [call for call in calls if _call_name(call) == call_name]
            if len(matches) != 1:
                failures.append(
                    f"{function_name} must call {call_name} exactly once"
                )
                continue
            supplied = {
                keyword.arg: keyword.value
                for keyword in matches[0].keywords
                if keyword.arg is not None
            }
            missing = required_keywords - set(supplied)
            if missing:
                failures.append(
                    f"{function_name}->{call_name} lacks {sorted(missing)}"
                )
            for name in required_keywords & set(supplied):
                checked_dependencies += 1
                if _obvious_placeholder(supplied[name]):
                    failures.append(
                        f"{function_name}->{call_name}.{name} is a placeholder"
                    )
            for name, value in supplied.items():
                if name.endswith(_CAPABILITY_SUFFIXES) and _obvious_placeholder(value):
                    failures.append(
                        f"{function_name}->{call_name}.{name} disables a capability"
                    )

    binary_backend = functions.get("_binary64_backend")
    if binary_backend is None:
        failures.append("missing binary64 production backend")
    else:
        call_names = {
            name
            for call in ast.walk(binary_backend)
            if isinstance(call, ast.Call)
            for name in (_call_name(call),)
            if name is not None
        }
        if "load_generated_gsn_cache" not in call_names:
            failures.append("binary64 backend does not use load-only GSN resources")
        forbidden = call_names & {
            "ensure_generated_gsn_cache",
            "run",
            "Popen",
            "check_call",
            "check_output",
        }
        if forbidden:
            failures.append(
                f"binary64 backend can reach producer/process calls: {sorted(forbidden)}"
            )

    report_owner = functions.get("_refresh_runtime_reports")
    if report_owner is None:
        failures.append("missing schema-11 report refresh owner")
    else:
        names = {
            node.id for node in ast.walk(report_owner) if isinstance(node, ast.Name)
        }
        for required in (
            "write_schema11_projective",
            "write_schema11_triage",
            "refresh_schema11_reports",
        ):
            if required not in names:
                failures.append(f"report refresh does not reach {required}")

    if failures:
        raise RuntimeError("production wiring validation failed: " + "; ".join(failures))
    return {
        "schema": "windows-solver.production-wiring-check/1",
        "runtime_path": str(runtime),
        "checked_dependencies": checked_dependencies,
        "status": "CONNECTED",
    }


def main() -> int:
    print(json.dumps(validate_production_wiring(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["validate_production_wiring"]
