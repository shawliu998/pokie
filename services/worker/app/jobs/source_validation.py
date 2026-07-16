"""Worker consumer for API-enqueued source validation jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from connectors.factory import ConnectorFactoryError, SourceConnectorFactory
from connectors.shared.contracts import (
    ConnectorError,
    ConnectorInvalidCredential,
    ConnectorRateLimited,
    ConnectorStatus,
    ConnectorTimeout,
)
from services.worker.app.contracts import (
    SourceHealthStatus,
    SourceValidationClaim,
    WorkerDomainAdapter,
)


@dataclass(frozen=True, slots=True)
class SourceValidationJobResult:
    handled: bool
    source_status: str | None = None
    failure_code: str | None = None


class SourceValidationJob:
    def __init__(
        self,
        domain: WorkerDomainAdapter,
        connector_factory: SourceConnectorFactory,
        lease_for: timedelta,
    ) -> None:
        self.domain = domain
        self.connector_factory = connector_factory
        self.lease_for = lease_for

    def run(self, claim: SourceValidationClaim) -> SourceValidationJobResult:
        try:
            self.domain.heartbeat_source_validation_job(claim, self.lease_for)
            source = self.domain.get_source_connection(claim.source_connection_id)
            connector = self.connector_factory.create(source, claim.connector_config)
            self.domain.heartbeat_source_validation_job(claim, self.lease_for)
            health = connector.health()
            source_status = _source_status_for_connector(health.status)
            failure_code = _health_failure_code(health.status, health.details)
            self.domain.complete_source_validation_job(
                claim,
                source_status,
                failure_code,
                _safe_reason(health.details.get("error") or health.details.get("reason")),
            )
            return SourceValidationJobResult(True, source_status, failure_code)
        except ConnectorInvalidCredential as exc:
            self.domain.complete_source_validation_job(
                claim,
                SourceHealthStatus.AUTH_REQUIRED.value,
                exc.__class__.__name__,
                "connector credential validation failed",
            )
            return SourceValidationJobResult(
                True, SourceHealthStatus.AUTH_REQUIRED.value, exc.__class__.__name__
            )
        except ConnectorRateLimited as exc:
            self.domain.complete_source_validation_job(
                claim,
                SourceHealthStatus.DEGRADED.value,
                exc.__class__.__name__,
                "connector validation was rate limited",
            )
            return SourceValidationJobResult(
                True, SourceHealthStatus.DEGRADED.value, exc.__class__.__name__
            )
        except ConnectorTimeout as exc:
            self.domain.complete_source_validation_job(
                claim,
                SourceHealthStatus.DEGRADED.value,
                exc.__class__.__name__,
                "connector validation timed out",
            )
            return SourceValidationJobResult(
                True, SourceHealthStatus.DEGRADED.value, exc.__class__.__name__
            )
        except ConnectorError as exc:
            source_status = _source_status_for_connector(exc.status)
            self.domain.complete_source_validation_job(
                claim,
                source_status,
                exc.__class__.__name__,
                "connector validation failed",
            )
            return SourceValidationJobResult(True, source_status, exc.__class__.__name__)
        except ConnectorFactoryError as exc:
            self.domain.fail_source_validation_job(
                claim,
                exc.__class__.__name__,
                "connector validation could not be configured",
            )
            return SourceValidationJobResult(
                True, SourceHealthStatus.FAILED.value, exc.__class__.__name__
            )
        except Exception as exc:
            self.domain.fail_source_validation_job(
                claim,
                exc.__class__.__name__,
                "source validation worker failed",
            )
            return SourceValidationJobResult(
                True, SourceHealthStatus.FAILED.value, exc.__class__.__name__
            )


def _source_status_for_connector(status: ConnectorStatus) -> str:
    if status == ConnectorStatus.HEALTHY:
        return SourceHealthStatus.HEALTHY.value
    if status == ConnectorStatus.AUTH_REQUIRED:
        return SourceHealthStatus.AUTH_REQUIRED.value
    if status in {ConnectorStatus.DEGRADED, ConnectorStatus.RATE_LIMITED}:
        return SourceHealthStatus.DEGRADED.value
    return SourceHealthStatus.FAILED.value


def _health_failure_code(status: ConnectorStatus, details: dict[str, Any]) -> str | None:
    if status == ConnectorStatus.HEALTHY:
        return None
    value = details.get("failure_code") or details.get("error") or status.value
    return str(value)[:80]


def _safe_reason(value: object) -> str | None:
    if value is None:
        return None
    return str(value)[:2000]
