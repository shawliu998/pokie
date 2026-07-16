"""Worker process entrypoints for DB-backed jobs and schedules."""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from connectors.factory import SourceConnectorFactory, create_connector_factory
from services.worker.app.adapter_wiring import load_domain_adapter
from services.worker.app.contracts import ResearchRunState
from services.worker.app.jobs.collection import ConnectorCollectionJob
from services.worker.app.jobs.import_finalization import (
    ImportFinalizationHandledError,
    ImportFinalizationJob,
)
from services.worker.app.jobs.source_validation import SourceValidationJob
from services.worker.app.pipelines.digests import deterministic_id
from services.worker.app.pipelines.model_research import (
    DeepSeekResearchRunner,
    ModelProviderError,
)
from services.worker.app.pipelines.research import DeterministicResearchRunner
from services.worker.app.schedules.scheduler import RepositoryCollectionScheduler
from services.worker.app.storage import MemoryObjectStore

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glint-worker")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("health")
    for name in ("once", "poll"):
        command = subcommands.add_parser(name)
        command.add_argument(
            "--kind",
            choices=(
                "all",
                "import-finalization",
                "research-run",
                "source-validation",
                "collection-schedule",
            ),
            default="all",
        )
        command.add_argument(
            "--worker-id", default=os.environ.get("GLINT_WORKER_ID", "glint-worker")
        )
        command.add_argument(
            "--lease-seconds",
            type=int,
            default=int(os.environ.get("GLINT_WORKER_LEASE_SECONDS", "120")),
        )
        command.add_argument(
            "--interval-seconds",
            type=float,
            default=float(os.environ.get("GLINT_WORKER_POLL_INTERVAL_SECONDS", "2.0")),
        )
        command.add_argument("--max-iterations", type=int, default=1 if name == "once" else 0)
    args = parser.parse_args(argv)
    if args.command == "health":
        return 0

    domain = load_domain_adapter()
    object_store = _load_object_store()
    connector_factory = _load_connector_factory()
    max_iterations = args.max_iterations
    iterations = 0
    while True:
        iterations += 1
        did_work = run_once(
            domain=domain,
            object_store=object_store,
            connector_factory=connector_factory,
            worker_id=args.worker_id,
            lease_for=timedelta(seconds=args.lease_seconds),
            kind=args.kind,
        )
        if args.command == "once" or (max_iterations and iterations >= max_iterations):
            return 0
        if not did_work:
            time.sleep(args.interval_seconds)


def run_once(
    *,
    domain: Any,
    object_store: Any,
    connector_factory: SourceConnectorFactory,
    worker_id: str,
    lease_for: timedelta,
    kind: str = "all",
) -> bool:
    if kind in {"all", "import-finalization"} and _guarded_once(
        _run_import_finalization_once,
        domain,
        object_store,
        worker_id,
        lease_for,
    ):
        return True
    if kind in {"all", "research-run"} and _guarded_once(
        _run_research_once, domain, worker_id, lease_for
    ):
        return True
    if kind in {"all", "source-validation"} and _guarded_once(
        _run_source_validation_once,
        domain,
        connector_factory,
        worker_id,
        lease_for,
    ):
        return True
    return kind in {"all", "collection-schedule"} and _guarded_once(
        _run_collection_once,
        domain,
        connector_factory,
        worker_id,
        lease_for,
    )


def _run_import_finalization_once(
    domain: Any, object_store: Any, worker_id: str, lease_for: timedelta
) -> bool:
    command = domain.claim_next_import_finalization_command(worker_id, lease_for)
    if command is None:
        return False
    ImportFinalizationJob(domain, object_store, lease_for=lease_for).run(command)
    return True


def _run_research_once(domain: Any, worker_id: str, lease_for: timedelta) -> bool:
    claim = domain.claim_next_research_run_command(worker_id, lease_for)
    if claim is None:
        return False
    versions = domain.get_content_versions_for_research_run(claim.run_id)
    run = domain.get_research_run(claim.run_id)
    if run.provider == "deepseek":
        try:
            runner = DeepSeekResearchRunner.from_env(domain)
        except ModelProviderError:
            trace_id = deterministic_id(
                "model-config-failure", run.id, run.run_input_manifest_digest
            )
            domain.append_run_event(
                run.id,
                "task.failed",
                {
                    "task_id": deterministic_id("task", run.id, "bounded_model_research"),
                    "task_type": "bounded_model_research",
                    "status": "failed",
                    "safe_summary": "Model provider configuration is unavailable or invalid.",
                },
                trace_id,
            )
            domain.transition_research_run(run.id, ResearchRunState.FAILED, claim.worker_attempt_id)
            return True
    else:
        runner = DeterministicResearchRunner(domain)
    runner.run(claim.run_id, versions, claim.worker_attempt_id, lease_for)
    return True


def _run_source_validation_once(
    domain: Any, connector_factory: SourceConnectorFactory, worker_id: str, lease_for: timedelta
) -> bool:
    claim = domain.claim_next_source_validation_job(worker_id, lease_for)
    if claim is None:
        return False
    try:
        SourceValidationJob(domain, connector_factory, lease_for).run(claim)
    except Exception as exc:
        LOGGER.warning(
            "source validation job failed before terminal state",
            extra={
                "error_class": exc.__class__.__name__,
                "failure_code": getattr(exc, "code", None),
                "job_id": getattr(claim, "job_id", None),
                "source_connection_id": getattr(claim, "source_connection_id", None),
            },
        )
        raise
    return True


def _run_collection_once(
    domain: Any, connector_factory: SourceConnectorFactory, worker_id: str, lease_for: timedelta
) -> bool:
    scheduler = RepositoryCollectionScheduler(domain, worker_id, int(lease_for.total_seconds()))
    claim = scheduler.claim_one(datetime.now(tz=UTC))
    if claim is None:
        return False
    command = claim.command
    try:
        scheduler.heartbeat(claim.schedule_id, claim.lease_token, datetime.now(tz=UTC))
        source = domain.get_source_connection(command.source_connection_id)
        connector = connector_factory.create(source, command.connector_config or {})
        result = ConnectorCollectionJob(
            domain,
            connector,
            sleeper=time.sleep,
            heartbeat=lambda now: scheduler.heartbeat(claim.schedule_id, claim.lease_token, now),
        ).run(command)
        success = result.state in {"succeeded", "partial_success"}
        next_run_at = (
            _next_collection_run_at(command, result) if success else _failure_next_run_at(result)
        )
        scheduler.complete(
            claim.schedule_id, claim.lease_token, success, next_run_at, datetime.now(tz=UTC)
        )
    except Exception as exc:
        LOGGER.warning(
            "collection schedule processing failed before terminal job state",
            extra={
                "error_class": exc.__class__.__name__,
                "failure_code": getattr(exc, "code", None),
                "schedule_id": claim.schedule_id,
                "source_connection_id": command.source_connection_id,
            },
        )
        scheduler.complete(claim.schedule_id, claim.lease_token, False, None, datetime.now(tz=UTC))
        return True
    return True


def _guarded_once(function: Any, *args: Any) -> bool:
    try:
        return bool(function(*args))
    except ImportFinalizationHandledError as exc:
        LOGGER.warning(
            "import finalization command failed after durable state update",
            extra={"failure_code": exc.failure_code, "retryable": exc.retryable},
        )
        return True
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code in {"JOB_ALREADY_CLAIMED", "JOB_LEASE_EXPIRED", "VERSION_CONFLICT"}:
            return False
        if exc.__class__.__name__ == "ProductionAdapterError" and "lease" in str(exc).lower():
            return False
        raise


def _next_collection_run_at(command: Any, result: Any) -> datetime:
    retry_after = getattr(result, "retry_after_seconds", None)
    if retry_after:
        return datetime.now(tz=UTC) + timedelta(seconds=retry_after)
    return command.scheduled_for + timedelta(seconds=command.cadence_seconds or 3600)


def _failure_next_run_at(result: Any) -> datetime | None:
    retry_after = getattr(result, "retry_after_seconds", None)
    if retry_after:
        return datetime.now(tz=UTC) + timedelta(seconds=retry_after)
    return None


def _load_object_store() -> Any:
    mode = os.environ.get("GLINT_WORKER_MODE", "production")
    if mode in {"test", "dev"} and not (
        os.environ.get("GLINT_WORKER_OBJECT_STORE") or os.environ.get("GLINT_API_OBJECT_STORE")
    ):
        return MemoryObjectStore()
    module = importlib.import_module("services.worker.app.repositories.sqlalchemy_adapter")
    return module.create_object_store()


def _load_connector_factory() -> SourceConnectorFactory:
    factory_path = os.environ.get("GLINT_CONNECTOR_FACTORY")
    if not factory_path:
        return create_connector_factory()
    module_name, sep, factory_name = factory_path.partition(":")
    if not sep:
        raise RuntimeError("GLINT_CONNECTOR_FACTORY must be module.path:factory")
    module = importlib.import_module(module_name)
    return getattr(module, factory_name)()


if __name__ == "__main__":
    raise SystemExit(main())
