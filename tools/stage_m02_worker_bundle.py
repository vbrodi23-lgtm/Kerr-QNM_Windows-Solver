"""Stage the immutable M02 worker contract used by bootstrap and CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from windows_solver.contracts import canonical_json_bytes


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bootstrap_object_bytes(value: dict[str, object]) -> bytes:
    """Match ``ConvertTo-Json -Compress`` over bootstrap's ordered contract."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def _install_immutable(source: Path, destination: Path) -> None:
    expected = _sha256(source)
    if destination.is_file():
        if _sha256(destination) != expected:
            raise ValueError(f"immutable worker resource is corrupted: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        if _sha256(temporary) != expected:
            raise ValueError(f"staged worker resource hash moved: {source}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def stage_worker_bundle(repository: Path, runtime_root: Path) -> dict[str, object]:
    data_root = repository / "src" / "windows_solver" / "data"
    worker = data_root / "julia" / "m02_worker.jl"
    fixed_root_authority = (
        data_root / "fixed_root_reliability_projection_authority_v1.json"
    )
    promoted_calibration = (
        data_root / "promoted_control_empirical_calibration_v1.json"
    )
    contract = {
        "schema_version": 1,
        "worker_sha256": _sha256(worker),
        "fixed_root_authority_sha256": _sha256(fixed_root_authority),
        "promoted_calibration_sha256": _sha256(promoted_calibration),
    }
    contract_sha256 = hashlib.sha256(_bootstrap_object_bytes(contract)).hexdigest()
    worker_id = f"m02-worker-{contract_sha256[:24]}"
    destination = runtime_root / "m02-workers" / worker_id
    for source in (fixed_root_authority, promoted_calibration, worker):
        _install_immutable(source, destination / source.name)
    receipt = {
        "schema": "windows-solver.m02-worker-bundle/1",
        "worker_contract_id": worker_id,
        "worker_contract_sha256": contract_sha256,
        "worker_contract": contract,
        "worker_path": str((destination / worker.name).resolve()),
        "resource_paths": {
            source.name: str((destination / source.name).resolve())
            for source in (fixed_root_authority, promoted_calibration)
        },
    }
    return {**receipt, "receipt_sha256": hashlib.sha256(
        canonical_json_bytes(receipt)
    ).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    receipt = stage_worker_bundle(repository, arguments.runtime_root.resolve())
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_bytes(canonical_json_bytes(receipt) + b"\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
