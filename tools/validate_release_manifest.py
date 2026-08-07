#!/usr/bin/env python3
"""Validate the authenticated release-domain manifest and provider ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from windows_solver.builtin import default_registry
from windows_solver.release_manifest import (
    RELEASE_MANIFEST_SHA256,
    load_release_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        help="optional manifest path; the authenticated packaged manifest is the default",
    )
    arguments = parser.parse_args(argv)
    try:
        manifest = load_release_manifest(
            arguments.manifest,
            registry=default_registry(),
        )
    except (OSError, ValueError) as error:
        print(f"release manifest invalid: {error}", file=sys.stderr)
        return 1

    mapping = manifest.to_mapping()
    claims = mapping["claims"]
    receipts = mapping["source_receipts"]
    print(
        json.dumps(
            {
                "available_receipt_count": sum(
                    receipt["status"] == "available" for receipt in receipts
                ),
                "claim_count": len(claims),
                "manifest_id": mapping["manifest_id"],
                "manifest_sha256": (
                    RELEASE_MANIFEST_SHA256
                    if arguments.manifest is None
                    else "external-file-not-package-bound"
                ),
                "missing_receipt_count": sum(
                    receipt["status"] == "missing" for receipt in receipts
                ),
                "provider_ids": sorted(
                    record["active_provider_id"]
                    for record in mapping["capabilities"].values()
                    if record["active_provider_id"] is not None
                ),
                "status": "valid",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
