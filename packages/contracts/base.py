"""Strict primitives shared by every public Glint contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, field_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Digest = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^sha256:[A-Za-z0-9][A-Za-z0-9._:-]*$",
        min_length=8,
        max_length=256,
    ),
]
VersionString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        min_length=1,
        max_length=128,
    ),
]


class ContractModel(BaseModel):
    """Base for wire contracts: unknown fields never pass silently."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
    )

    @field_validator("*")
    @classmethod
    def require_utc_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            offset = value.utcoffset()
            if offset is None or offset.total_seconds() != 0:
                raise ValueError("timestamp must use the UTC offset")
            return value.astimezone(UTC)
        return value


class UTCModel(ContractModel):
    """Contract model whose declared timestamps are normalized by subclasses."""

    @staticmethod
    def require_utc(value: AwareDatetime) -> datetime:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must use the UTC offset")
        return value.astimezone(UTC)


class TimestampedModel(UTCModel):
    created_at: AwareDatetime
    updated_at: AwareDatetime

    _created_at_utc = field_validator("created_at")(UTCModel.require_utc)
    _updated_at_utc = field_validator("updated_at")(UTCModel.require_utc)


JsonObject = dict[str, Any]
