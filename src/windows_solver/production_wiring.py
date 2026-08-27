"""Structural guard for critical production-adapter capability wiring."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Mapping


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
            "checkpoint_committed",
            "diagnostic_session",
        },
    },
    "run_native_promoted_admission": {
        "admit_retained_promoted_checkpoint": {
            "queue_ordinal",
            "independent_review_receipt",
            "calibration_receipt",
            "layer1_guard",
            "terminal_record_committed",
            "record_reducer",
        },
    },
}

_PROMOTED_SURVEY_REQUIRED_CALLS = {
    "_commit_promoted_raw_calculation": {
        "retain_promoted_raw_calculation",
    },
    "run_promoted_survey": {
        "_commit_promoted_raw_calculation",
        "_commit_promoted_outcome",
        "retain_promoted_background",
        "_resumed_promoted_exterior_outcome",
        "_resumed_promoted_horizon_outcome",
        "_validate_promoted_scheduler_preflight",
    },
    "_commit_promoted_outcome": {
        "_validate_promoted_scheduler_preflight",
    },
}
_RESUME_NUMERICAL_CALLS = frozenset(
    {
        "backend_factory",
        "fixed_root_survey_batch",
        "horizon_runner",
        "promoted_horizon_runner",
        "root_seal_lookup",
    }
)


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


def _function_map(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _call_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    return [node for node in ast.walk(function) if isinstance(node, ast.Call)]


def _call_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        name
        for call in _call_nodes(function)
        for name in (_call_name(call),)
        if name is not None
    }


def _promoted_ownership_failures(
    runtime_functions: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
    survey_path: Path,
) -> list[str]:
    """Prove the static ownership seams that protect a live promoted pass."""

    survey_tree = ast.parse(
        survey_path.read_text(encoding="utf-8"), filename=str(survey_path)
    )
    survey_functions = _function_map(survey_tree)
    failures: list[str] = []
    for function_name, required_calls in _PROMOTED_SURVEY_REQUIRED_CALLS.items():
        function = survey_functions.get(function_name)
        if function is None:
            failures.append(f"missing promoted ownership adapter {function_name}")
            continue
        names = _call_names(function)
        missing = required_calls - names
        if missing:
            failures.append(
                f"{function_name} lacks promoted ownership calls {sorted(missing)}"
            )

    raw_commit = survey_functions.get("_commit_promoted_raw_calculation")
    final_commit = survey_functions.get("_commit_promoted_outcome")
    scheduler = survey_functions.get("run_promoted_survey")
    if raw_commit is not None and final_commit is not None and scheduler is not None:
        raw_lines = [
            call.lineno
            for call in _call_nodes(scheduler)
            if _call_name(call) == "_commit_promoted_raw_calculation"
        ]
        final_lines = [
            call.lineno
            for call in _call_nodes(scheduler)
            if _call_name(call) == "_commit_promoted_outcome"
        ]
        if not raw_lines or not final_lines or min(raw_lines) >= min(final_lines):
            failures.append(
                "promoted scheduler does not source-order raw checkpoint before final retention"
            )

    for function_name in (
        "_resumed_promoted_exterior_outcome",
        "_resumed_promoted_horizon_outcome",
    ):
        function = survey_functions.get(function_name)
        if function is None:
            failures.append(f"missing retained-result reducer {function_name}")
            continue
        numerical = _call_names(function) & _RESUME_NUMERICAL_CALLS
        if numerical:
            failures.append(
                f"{function_name} can reopen numerical work: {sorted(numerical)}"
            )

    exterior = survey_functions.get("_run_promoted_exterior_queue_entry")
    if exterior is None:
        failures.append("missing promoted exterior acquisition adapter")
    else:
        forbidden = _call_names(exterior) & {
            "produced_record_builder",
            "build_fixed_root_screening_record",
            "add_numerical_record",
            "record_evidence",
            "terminal_record_committed",
        }
        if forbidden:
            failures.append(
                "promoted exterior acquisition can reach terminal ownership: "
                f"{sorted(forbidden)}"
            )

    if scheduler is not None:
        forbidden = _call_names(scheduler) & {
            "produced_record_builder",
            "build_fixed_root_screening_record",
            "record_evidence",
            "terminal_record_committed",
        }
        if forbidden:
            failures.append(
                "promoted scheduler can reach terminal ownership: "
                f"{sorted(forbidden)}"
            )

    native_promoted = runtime_functions.get("run_native_promoted_pass")
    if native_promoted is None:
        failures.append("missing native promoted calculation adapter")
    else:
        names = _call_names(native_promoted)
        forbidden = names & {
            "build_fixed_root_screening_record",
            "terminal_record_committed",
        }
        if forbidden:
            failures.append(
                "native promoted calculation can reach terminal ownership: "
                f"{sorted(forbidden)}"
            )
        mode_names = {
            node.attr
            for node in ast.walk(native_promoted)
            if isinstance(node, ast.Attribute)
        }
        if "CALCULATE_AND_ADMIT" not in mode_names:
            failures.append(
                "native promoted calculation does not reject alternate admission authority"
            )

    horizon_acquire = runtime_functions.get("_promoted_horizon_outcome")
    horizon_reduce = runtime_functions.get("_reduce_retained_horizon_for_admission")
    if horizon_acquire is None:
        failures.append("missing promoted horizon acquisition adapter")
    elif "build_schema11_horizon_record" in _call_names(horizon_acquire):
        failures.append("promoted horizon acquisition can construct a terminal record")
    if horizon_reduce is None:
        failures.append("missing retained horizon admission reducer")
    elif "build_schema11_horizon_record" not in _call_names(horizon_reduce):
        failures.append("retained horizon admission does not own terminal construction")

    admission = runtime_functions.get("run_native_promoted_admission")
    if admission is not None:
        numerical = _call_names(admission) & {
            "NativeCampaignStageBackend",
            "fixed_root_survey_batch",
            "_julia_precision_backend_for",
        }
        if numerical:
            failures.append(
                "promoted admission can reach numerical work: "
                f"{sorted(numerical)}"
            )
    return failures


def validate_production_wiring(path: Path | None = None) -> dict[str, object]:
    runtime = path or Path(__file__).with_name("campaign_runtime.py")
    tree = ast.parse(runtime.read_text(encoding="utf-8"), filename=str(runtime))
    functions = _function_map(tree)
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

    failures.extend(
        _promoted_ownership_failures(
            functions, runtime.with_name("campaign_survey.py")
        )
    )

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
