"""Durable CollectionSchedule management contracts."""

from __future__ import annotations

from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ..base import ContractModel, JsonObject, NonEmptyString
from ..enums import DataAuthenticity, MisfirePolicy, OverlapPolicy
from .common import MutableResource


def _iana_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA time zone") from exc
    return value


class CollectionScheduleCreateRequest(ContractModel):
    workspace_id: UUID
    source_connection_id: UUID
    watchlist_id: UUID
    query_json: JsonObject
    cadence_seconds: int = Field(ge=1, le=31_536_000)
    timezone: NonEmptyString
    misfire_policy: MisfirePolicy
    catch_up: bool
    overlap_policy: OverlapPolicy
    next_run_at: AwareDatetime
    enabled: bool = True

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _iana_timezone(value)


class CollectionScheduleUpdateRequest(ContractModel):
    query_json: JsonObject | None = None
    cadence_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    timezone: NonEmptyString | None = None
    misfire_policy: MisfirePolicy | None = None
    catch_up: bool | None = None
    overlap_policy: OverlapPolicy | None = None
    next_run_at: AwareDatetime | None = None
    enabled: bool | None = None
    expected_row_version: int = Field(ge=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _iana_timezone(value)

    @model_validator(mode="after")
    def require_change(self) -> CollectionScheduleUpdateRequest:
        changed = {
            field
            for field in self.model_fields_set - {"expected_row_version"}
            if getattr(self, field) is not None
        }
        if not changed:
            raise ValueError("schedule update must change at least one field")
        return self


class CollectionScheduleResponse(MutableResource):
    source_connection_id: UUID
    watchlist_id: UUID
    query_json: JsonObject
    cadence_seconds: int = Field(ge=1, le=31_536_000)
    timezone: NonEmptyString
    misfire_policy: MisfirePolicy
    catch_up: bool
    overlap_policy: OverlapPolicy
    next_run_at: AwareDatetime
    enabled: bool
    lease_held: bool
    lease_expires_at: AwareDatetime | None = None
    heartbeat_at: AwareDatetime | None = None
    data_authenticity: DataAuthenticity

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _iana_timezone(value)

    @model_validator(mode="after")
    def validate_lease_projection(self) -> CollectionScheduleResponse:
        if self.lease_held and self.lease_expires_at is None:
            raise ValueError("held lease requires lease_expires_at")
        if not self.lease_held and self.lease_expires_at is not None:
            raise ValueError("unheld lease must not expose lease_expires_at")
        return self
