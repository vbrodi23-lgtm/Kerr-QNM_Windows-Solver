from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import tempfile
import unittest

from windows_solver.artifacts import (
    ArtifactEnvelope,
    ArtifactStore,
    ArtifactVerificationError,
    computation_cache_key,
)
from windows_solver.contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    NumericalState,
    ScientificState,
    canonical_json_bytes,
)


EVIDENCE = EvidenceState(
    carrier=CarrierState.VALID,
    execution=ExecutionState.SUCCEEDED,
    numerical=NumericalState.ACCEPTED,
    scientific=ScientificState.UNRESOLVED,
)


def example_envelope() -> ArtifactEnvelope:
    return ArtifactEnvelope(
        schema_version=1,
        artifact_type="problem-contract",
        capability=Capability.PROBLEM_CONTRACT,
        provider={"provider_id": "p"},
        request={"theory_id": "t"},
        upstream_artifact_ids=(),
        payload={"value": 3},
        evidence=EVIDENCE,
    )


class ArtifactEnvelopeTests(unittest.TestCase):
    def test_identity_hashes_exact_canonical_scientific_content(self) -> None:
        expected_identity = (
            b'{"artifact_type":"problem-contract","capability":"problem-contract",'
            b'"evidence":{"carrier":"VALID","execution":"SUCCEEDED",'
            b'"numerical":"ACCEPTED","scientific":"UNRESOLVED"},'
            b'"payload":{"value":3},"provider":{"provider_id":"p"},'
            b'"request":{"theory_id":"t"},"schema_version":1,'
            b'"upstream_artifact_ids":[]}'
        )
        expected = hashlib.sha256(expected_identity).hexdigest()

        self.assertEqual(example_envelope().artifact_id, expected)


class ArtifactStoreTests(unittest.TestCase):
    def test_detects_payload_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            artifact_id = store.put_artifact(example_envelope())
            path = Path(directory, "artifacts", f"{artifact_id}.json")
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["payload"]["value"] = 4
            path.write_bytes(canonical_json_bytes(stored))

            with self.assertRaisesRegex(
                ArtifactVerificationError, "artifact content hash mismatch"
            ):
                store.verify_artifact(artifact_id)

    def test_rejects_duplicate_keys_in_artifact_and_cache_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            envelope = example_envelope()
            artifact_id = store.put_artifact(envelope)
            artifact_path = Path(
                directory, "artifacts", f"{artifact_id}.json"
            )
            artifact_json = artifact_path.read_text(encoding="utf-8")
            artifact_path.write_text(
                '{"schema_version":999,' + artifact_json[1:],
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ArtifactVerificationError, "artifact .* is unreadable"
            ):
                store.verify_artifact(artifact_id)

            artifact_path.write_bytes(canonical_json_bytes(envelope.to_mapping()))
            cache_key = computation_cache_key(
                envelope.capability,
                envelope.provider,
                envelope.request,
                envelope.upstream_artifact_ids,
            )
            store.bind_cache(cache_key, artifact_id)
            cache_path = Path(directory, "cache", f"{cache_key}.json")
            cache_json = cache_path.read_text(encoding="utf-8")
            cache_path.write_text(
                '{"artifact_id":"' + "0" * 64 + '",' + cache_json[1:],
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ArtifactVerificationError, "cache binding is invalid"
            ):
                store.lookup_cache(cache_key)

    def test_rejects_valid_artifact_bound_to_wrong_computation_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            envelope = example_envelope()
            artifact_id = store.put_artifact(envelope)
            wrong_key = computation_cache_key(
                envelope.capability,
                envelope.provider,
                {"theory_id": "different"},
                envelope.upstream_artifact_ids,
            )
            binding = Path(directory, "cache", f"{wrong_key}.json")
            binding.parent.mkdir(parents=True)
            binding.write_bytes(
                canonical_json_bytes(
                    {"cache_key": wrong_key, "artifact_id": artifact_id}
                )
            )

            with self.assertRaisesRegex(
                ArtifactVerificationError, "cache binding does not match artifact"
            ):
                store.lookup_cache(wrong_key)

    def test_cache_key_covers_capability_provider_and_upstream_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            envelope = example_envelope()
            artifact_id = store.put_artifact(envelope)
            variants = (
                (
                    Capability.SPECTRAL_CORE,
                    envelope.provider,
                    envelope.request,
                    envelope.upstream_artifact_ids,
                ),
                (
                    envelope.capability,
                    {"provider_id": "different"},
                    envelope.request,
                    envelope.upstream_artifact_ids,
                ),
                (
                    envelope.capability,
                    envelope.provider,
                    envelope.request,
                    ("0" * 64,),
                ),
            )
            for material in variants:
                with self.subTest(material=material):
                    wrong_key = computation_cache_key(*material)
                    binding = Path(directory, "cache", f"{wrong_key}.json")
                    binding.parent.mkdir(parents=True, exist_ok=True)
                    binding.write_bytes(
                        canonical_json_bytes(
                            {"cache_key": wrong_key, "artifact_id": artifact_id}
                        )
                    )
                    with self.assertRaisesRegex(
                        ArtifactVerificationError,
                        "cache binding does not match artifact",
                    ):
                        store.lookup_cache(wrong_key)

    def test_rejects_symlinked_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory, "store"))
            envelope = example_envelope()
            outside = Path(directory, "outside.json")
            outside.write_bytes(canonical_json_bytes(envelope.to_mapping()))
            artifact_path = (
                store.artifacts_directory / f"{envelope.artifact_id}.json"
            )
            artifact_path.parent.mkdir(parents=True)
            try:
                os.symlink(outside, artifact_path)
            except OSError:
                self.skipTest("file symlinks are unavailable")

            with self.assertRaisesRegex(
                ArtifactVerificationError, "artifact storage path is invalid"
            ):
                store.load_artifact(envelope.artifact_id)

    def test_rejects_extra_unsigned_evidence_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            artifact_id = store.put_artifact(example_envelope())
            path = Path(directory, "artifacts", f"{artifact_id}.json")
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["evidence"]["certified"] = True
            path.write_bytes(canonical_json_bytes(stored))

            with self.assertRaisesRegex(
                ArtifactVerificationError, "artifact evidence fields are invalid"
            ):
                store.verify_artifact(artifact_id)

    def test_rejects_path_traversal_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))

            with self.assertRaisesRegex(
                ArtifactVerificationError, "run identity is invalid"
            ):
                store.load_run_mapping("../outside")


if __name__ == "__main__":
    unittest.main()
