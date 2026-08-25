"""Postmortem and diagnostic-artifact contracts independent of campaign policy."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import traceback
from typing import Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from .contracts import canonical_json_bytes
from .structural_diagnostics import StructuralDiagnosticSession


POSTMORTEM_SCHEMA = "windows-solver.campaign-postmortem/1"
ARTIFACT_MANIFEST_SCHEMA = "windows-solver.diagnostic-artifact-manifest/1"


def _json_copy(value: object) -> object:
    import json

    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exception_chain(error: BaseException) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        result.append({
            "exception_type": type(current).__name__,
            "message": str(current),
        })
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return result


class CampaignPostmortemBuilder:
    """Collect diagnostic facts without deciding any scientific state transition."""

    def __init__(self, session: StructuralDiagnosticSession) -> None:
        if not isinstance(session, StructuralDiagnosticSession):
            raise ValueError("postmortem requires a structural diagnostic session")
        self.session = session
        self._primary_failure: dict[str, object] | None = None
        self._checkpoint: dict[str, object] = {"path": str(session.checkpoint_path)}
        self._scheduler: dict[str, object] = {}
        self._providers: dict[str, object] = {}
        self._campaign: dict[str, object] = {
            "campaign_id": session.campaign_id,
            "selection_id": session.selection_id,
        }
        self._source: dict[str, object] = {}
        self._counts: dict[str, object] = {}
        self._queue_summary: dict[str, object] = {}
        self._repetition_monitor: dict[str, object] = {}
        self._collection_failure: dict[str, object] | None = None

    def capture_exception(
        self,
        error: BaseException,
        *,
        failure_code: str,
        failure_class: str,
        disposition: str,
        fingerprint_sha256: str | None,
    ) -> "CampaignPostmortemBuilder":
        if not isinstance(error, BaseException):
            raise ValueError("postmortem exception is invalid")
        self._primary_failure = {
            "exception_type": type(error).__name__,
            "exception_message": str(error),
            "traceback": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ),
            "chain": _exception_chain(error),
            "failure_code": failure_code,
            "failure_class": failure_class,
            "disposition": disposition,
            "fingerprint_sha256": fingerprint_sha256,
        }
        return self

    def capture_checkpoint(self, value: Mapping[str, object]) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem checkpoint must be an object")
        self._checkpoint = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_scheduler(self, value: Mapping[str, object]) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem scheduler must be an object")
        self._scheduler = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_provider_summaries(
        self, value: Mapping[str, object]
    ) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem providers must be an object")
        self._providers = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_campaign(self, value: Mapping[str, object]) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem campaign must be an object")
        self._campaign = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_source(self, value: Mapping[str, object]) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem source must be an object")
        self._source = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_counts(self, value: Mapping[str, object]) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem counts must be an object")
        self._counts = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_queue_summary(self, value: Mapping[str, object]) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem queue summary must be an object")
        self._queue_summary = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_repetition_monitor(
        self, value: Mapping[str, object]
    ) -> "CampaignPostmortemBuilder":
        if not isinstance(value, Mapping):
            raise ValueError("postmortem repetition monitor must be an object")
        self._repetition_monitor = _json_copy(dict(value))  # type: ignore[assignment]
        return self

    def capture_collection_failure(
        self, error: BaseException
    ) -> "CampaignPostmortemBuilder":
        self._collection_failure = {
            "exception_type": type(error).__name__,
            "message": str(error),
        }
        return self

    def _postmortem_mapping(self, terminal_classification: str) -> dict[str, object]:
        if not isinstance(terminal_classification, str) or not terminal_classification:
            raise ValueError("postmortem terminal classification is invalid")
        artifacts = {
            "structural_events": str(self.session.paths.structural_events),
            "postmortem": str(self.session.paths.postmortem),
            "artifact_manifest": str(self.session.paths.artifact_manifest),
            "bundle": str(self.session.paths.bundle),
        }
        return {
            "schema": POSTMORTEM_SCHEMA,
            "terminal_classification": terminal_classification,
            "primary_failure": self._primary_failure,
            "campaign": self._campaign,
            "source": self._source,
            "movement": self._scheduler,
            "checkpoint": self._checkpoint,
            "counts": self._counts,
            "queue_summary": self._queue_summary,
            "repetition_monitor": self._repetition_monitor,
            "root_provider": self._providers.get("root_provider", {}),
            "solved_leaf_store": self._providers.get("solved_leaf_store", {}),
            "background_store": self._providers.get("background_store", {}),
            "last_structural_events": list(self.session.final_events(100)),
            "artifacts": artifacts,
            "diagnostic_collection_failure": self._collection_failure,
            "written_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def write_atomic(self, terminal_classification: str) -> Path:
        self.session.append("POSTMORTEM_WRITE_STARTED", durable=True)
        _atomic_json(
            self.session.paths.postmortem,
            self._postmortem_mapping(terminal_classification),
        )
        self.session.set_artifact_paths(postmortem_path=self.session.paths.postmortem)
        self.session.append("POSTMORTEM_WRITTEN", durable=True)
        return self.session.paths.postmortem

    def build_manifest(
        self,
        *,
        required_artifacts: Mapping[str, str | os.PathLike[str] | Path],
        optional_artifacts: Mapping[str, str | os.PathLike[str] | Path],
    ) -> dict[str, object]:
        overlap = set(required_artifacts) & set(optional_artifacts)
        if overlap:
            raise ValueError("artifact cannot be both required and optional")
        artifacts: dict[str, dict[str, object]] = {}
        for required, items in ((True, required_artifacts), (False, optional_artifacts)):
            for logical_name, raw_path in items.items():
                if not isinstance(logical_name, str) or not logical_name:
                    raise ValueError("artifact logical name is invalid")
                path = Path(raw_path)
                exists = path.is_file()
                artifacts[logical_name] = {
                    "logical_name": logical_name,
                    "path": str(path),
                    "exists": exists,
                    "required": required,
                    "size": path.stat().st_size if exists else None,
                    "sha256": _sha256_path(path) if exists else None,
                    "collection_status": (
                        "COLLECTED"
                        if exists
                        else ("MISSING_REQUIRED" if required else "MISSING_OPTIONAL")
                    ),
                    "omission_reason": (
                        None if exists else "artifact path does not exist at collection"
                    ),
                }
        return {
            "schema": ARTIFACT_MANIFEST_SCHEMA,
            "session_id": self.session.session_id,
            "session_directory": str(self.session.paths.directory),
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "artifacts": artifacts,
        }

    def write_manifest_atomic(
        self,
        *,
        required_artifacts: Mapping[str, str | os.PathLike[str] | Path],
        optional_artifacts: Mapping[str, str | os.PathLike[str] | Path],
    ) -> Path:
        manifest = self.build_manifest(
            required_artifacts=required_artifacts,
            optional_artifacts=optional_artifacts,
        )
        _atomic_json(self.session.paths.artifact_manifest, manifest)
        return self.session.paths.artifact_manifest

    def build_bundle_best_effort(
        self,
        artifacts: Mapping[str, str | os.PathLike[str] | Path],
    ) -> tuple[Path | None, Mapping[str, object] | None]:
        """Collect supplied files without allowing collection errors to escape."""

        try:
            self.session.append("DIAGNOSTIC_BUNDLE_STARTED", durable=True)
            with ZipFile(self.session.paths.bundle, "w", compression=ZIP_DEFLATED) as archive:
                for logical_name, raw_path in artifacts.items():
                    path = Path(raw_path)
                    if path.is_file():
                        archive.write(path, arcname=f"{logical_name}/{path.name}")
            self.session.set_artifact_paths(bundle_path=self.session.paths.bundle)
            self.session.append("DIAGNOSTIC_BUNDLE_WRITTEN", durable=True)
            return self.session.paths.bundle, None
        except BaseException as error:
            self.capture_collection_failure(error)
            return None, {
                "exception_type": type(error).__name__,
                "message": str(error),
            }


__all__ = [
    "ARTIFACT_MANIFEST_SCHEMA",
    "POSTMORTEM_SCHEMA",
    "CampaignPostmortemBuilder",
]
