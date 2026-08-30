"""Structural guard for critical production-adapter capability wiring."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from .contracts import canonical_json_bytes


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
            "diagnostic_session",
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
        "reduce_promoted_exterior_from_checkpoint",
        "reduce_promoted_horizon_from_checkpoint",
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
_PROMOTED_RUNTIME_IDENTITY_FILES = (
    "binary64_layer_lock.py",
    "campaign_failures.py",
    "campaign_policy.py",
    "campaign_runtime.py",
    "campaign_survey.py",
    "data/fixed_root_reliability_projection_authority_v1.json",
    "fixed_root_reliability.py",
    "julia_response_backend.py",
    "operation_control.py",
    "promoted_artifacts.py",
    "promoted_admission.py",
    "promoted_control_authority.py",
    "production_wiring.py",
    "response_engine.py",
    "response_batches.py",
    "root_readout_cache.py",
    "structural_diagnostics.py",
)

_REAL_INNER_HORIZON_POLICY_IDENTITY = (
    "cause-aware-real-inner-fixed-root-exterior-endpoint-recovery/v2"
)
_REAL_INNER_HORIZON_SCHEDULE = (
    "-10", "-25", "-50", "-75", "-100", "-150", "-225", "-337.5",
    "-400",
)


def promoted_runtime_identity_sha256() -> str:
    """Bind failure-resume authority to the Python sources being executed."""

    root = Path(__file__).parent
    source_sha256s = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in _PROMOTED_RUNTIME_IDENTITY_FILES
    }
    return hashlib.sha256(canonical_json_bytes(source_sha256s)).hexdigest()


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


def _julia_callable_source(source: str, name: str) -> str | None:
    """Return one column-zero Julia callable definition.

    Worker production owners are deliberately declared as top-level named
    functions.  Restricting extraction to that callable boundary avoids
    accepting a helper name merely because it occurs in a comment, docstring,
    or unrelated branch.
    """

    match = re.search(rf"(?m)^function\s+{re.escape(name)}\s*\(", source)
    if match is None:
        return None
    following = re.search(r"(?m)^function\s+[A-Za-z_]", source[match.end():])
    end = len(source) if following is None else match.end() + following.start()
    return source[match.start():end]


def _julia_callable_calls(source: str) -> list[str]:
    without_comments = re.sub(r"(?m)#.*$", "", source)
    return re.findall(r"\b([A-Za-z_][A-Za-z0-9_!.]*)\s*\(", without_comments)


def _real_inner_fixed_root_wiring_failures(root: Path) -> list[str]:
    worker_path = root / "data" / "julia" / "m02_worker.jl"
    backend_path = root / "julia_response_backend.py"
    worker = worker_path.read_text(encoding="utf-8")
    backend_tree = ast.parse(
        backend_path.read_text(encoding="utf-8"), filename=str(backend_path)
    )
    failures: list[str] = []

    assignments = {
        target.id: node.value
        for node in backend_tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    try:
        identity = ast.literal_eval(
            assignments["FIXED_ROOT_ENDPOINT_RECOVERY_POLICY_IDENTITY"]
        )
        geometry_rule = ast.literal_eval(
            assignments["FIXED_ROOT_HORIZON_GEOMETRY_RULE"]
        )
        schedule = ast.literal_eval(
            assignments["FIXED_ROOT_HORIZON_GEOMETRY_SCHEDULE"]
        )
        base_order = ast.literal_eval(
            assignments["FIXED_ROOT_ENDPOINT_BASE_ORDER"]
        )
        maximum_order = ast.literal_eval(
            assignments["FIXED_ROOT_ENDPOINT_MAXIMUM_ORDER"]
        )
    except (KeyError, ValueError, TypeError):
        failures.append("fixed-root real-inner policy constants are not literal")
    else:
        if identity != _REAL_INNER_HORIZON_POLICY_IDENTITY:
            failures.append("fixed-root endpoint policy is not real-inner")
        if geometry_rule != "bounded-real-inner-tortoise-depth/v1":
            failures.append("fixed-root horizon geometry rule is not real-inner")
        if tuple(schedule) != _REAL_INNER_HORIZON_SCHEDULE:
            failures.append("fixed-root real-inner horizon schedule is not exact")
        if (base_order, maximum_order) != (28, 112):
            failures.append("fixed-root real-inner endpoint orders are not exact")

    owner = _julia_callable_source(
        worker, "recover_fixed_root_real_inner_horizon_endpoint"
    )
    orchestrator = _julia_callable_source(
        worker, "recover_fixed_root_exterior_endpoints"
    )
    determinant = _julia_callable_source(worker, "evaluate_exterior_determinant")
    if owner is None:
        failures.append("missing real-inner fixed-root horizon recovery owner")
    else:
        owner_calls = set(_julia_callable_calls(owner))
        required = {
            "contour_builder",
            "geometry_builder",
            "candidate_builder",
            "endpoint_preparer",
            "limitation_classifier",
            "real_inner_horizon_endpoint_receipt",
        }
        missing = required - owner_calls
        if missing:
            failures.append(
                f"real-inner fixed-root owner lacks calls {sorted(missing)}"
            )
        for binding in (
            "contour_builder=build_worker_real_inner_horizon_contour",
            "geometry_builder=CF.horizon_endpoint_geometry_candidates",
            "candidate_builder=CF.horizon_endpoint_candidates",
            "endpoint_preparer=CF.prepare_real_inner_horizon_endpoint",
            "limitation_classifier=real_inner_horizon_ingoing_limitation",
        ):
            if binding not in owner:
                failures.append(
                    f"real-inner fixed-root owner default moved: {binding}"
                )
        first_gate = owner.find("factored_homogeneous_rhs_counter[] == 0")
        first_contour = owner.find("contour_builder(")
        if (
            first_gate < 0
            or first_contour < 0
            or first_gate > first_contour
            or owner.count("factored_homogeneous_rhs_counter[] == 0") < 4
        ):
            failures.append(
                "real-inner fixed-root owner lacks its pre-homogeneous work gates"
            )
        forbidden = owner_calls & {
            "build_worker_contour_context",
            "CF.prepare_factored_horizon_ingoing",
            "CF.solve_factored_horizon_branch_to_match",
        }
        if forbidden:
            failures.append(
                f"real-inner fixed-root admission owner bypasses its gate: {sorted(forbidden)}"
            )
    if orchestrator is None:
        failures.append("missing fixed-root exterior endpoint orchestrator")
    else:
        calls = set(_julia_callable_calls(orchestrator))
        if "recover_fixed_root_real_inner_horizon_endpoint" not in calls:
            failures.append("fixed-root exterior route bypasses the real-inner owner")
        if re.search(
            r"horizon_recovery\s*=\s*CF\.recover_single_factored_endpoint",
            orchestrator,
        ):
            failures.append("fixed-root exterior route retains generic horizon recovery")
        forbidden = calls & {
            "build_worker_contour_context",
            "CF.prepare_factored_horizon_ingoing",
            "CF.recover_single_factored_endpoint.horizon",
        }
        if forbidden:
            failures.append(
                f"fixed-root exterior route retains joined Xin calls {sorted(forbidden)}"
            )
    if determinant is None:
        failures.append("missing exterior determinant owner")
    else:
        calls = _julia_callable_calls(determinant)
        required = {
            "recover_fixed_root_exterior_endpoints",
            "assert_real_inner_exterior_preparations_ready",
            "CF.solve_factored_horizon_branch_to_match",
            "reconstruct_real_inner_horizon_match_state",
        }
        missing = required - set(calls)
        if missing:
            failures.append(
                f"exterior determinant lacks real-inner calls {sorted(missing)}"
            )
        if required.issubset(set(calls)):
            gate = calls.index("assert_real_inner_exterior_preparations_ready")
            solve = calls.index("CF.solve_factored_horizon_branch_to_match")
            if gate >= solve:
                failures.append("exterior homogeneous work precedes endpoint admission")
    policy_validator = _julia_callable_source(
        worker, "validate_fixed_root_endpoint_recovery_policy"
    )
    fixed_root_scope = "\n".join(
        item for item in (owner, orchestrator, policy_validator) if item is not None
    )
    if any(
        value in fixed_root_scope for value in ("-5000", "-10000", "-20000")
    ):
        failures.append("worker retains legacy joined-contour horizon geometry")
    return failures


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
        "reduce_promoted_exterior_from_checkpoint",
        "reduce_promoted_horizon_from_checkpoint",
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
        terminal = _call_names(function) & {
            "add_numerical_record",
            "build_fixed_root_screening_record",
            "build_schema11_horizon_record",
            "record_evidence",
            "terminal_record_committed",
        }
        if terminal:
            failures.append(
                f"{function_name} can reach terminal ownership: {sorted(terminal)}"
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
    failures.extend(_real_inner_fixed_root_wiring_failures(runtime.parent))

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


__all__ = ["promoted_runtime_identity_sha256", "validate_production_wiring"]
