"""Downstream manifest-only processing helpers."""

from __future__ import annotations

from services.worker.app.contracts import (
    ManifestProcessingCommand,
    NonTerminalImportError,
    WorkerDomainAdapter,
)
from services.worker.app.pipelines.signals import (
    SignalDetectionConfig,
    SignalDetectionResult,
    detect_signal,
)


def run_manifest_signal_pipeline(
    domain: WorkerDomainAdapter,
    command: ManifestProcessingCommand,
    signal_config: SignalDetectionConfig,
) -> SignalDetectionResult:
    """Run dedupe/signal from a terminal ImportManifest ID only."""

    manifest = domain.get_terminal_manifest(command.import_manifest_id)
    if manifest.workspace_id != command.workspace_id:
        raise NonTerminalImportError("manifest workspace mismatch")
    versions = domain.get_content_versions_for_manifest(manifest.id)
    result = detect_signal(versions, signal_config)
    if result.signal is not None:
        domain.create_signal(result.signal)
    return result
