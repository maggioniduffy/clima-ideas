"""Append-only registry of frozen predictions (F6.4).

Storage is a single JSON Lines file: one record per line, appended and fsynced. It is the simplest robust
choice here: appending never rewrites earlier bytes (Parquet files are immutable and would need one
partition per append plus a manifest to chain them), it is human-readable and diffable in git, and
volumes are tiny (a few records per day). Each record carries ``seq`` and ``prev_hash`` and its own
``record_hash`` = SHA-256 of the canonical JSON of every other field, so editing, deleting or reordering
any record makes ``verify()`` raise. Truncating the *tail* leaves a valid chain: keep the head hash that
``verify()`` returns (e.g. in the run log) to detect that too.

The public API is only ``append``, ``read`` and ``verify``. Scores are not stored here: F6.5 reads the
registry and keeps its scores elsewhere.

Issue time rules. ``issued_at`` is stamped from the injectable ``clock``, never taken from the caller.
The caller's ``issue_date`` must lie within ``ISSUE_TOLERANCE`` (5 minutes) of the clock, in either
direction: slightly earlier absorbs scheduling delay; anything earlier is backdating, anything later is
pre-dating, and both are rejected. Duplicates are keyed by (model_version, variable, region, lead_days,
UTC issue day).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ISSUE_TOLERANCE = timedelta(minutes=5)
_ZERO_HASH = "0" * 64
_HEX64 = r"^[0-9a-f]{64}$"
_PERIOD = r"^\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}$"


class RegistryError(Exception):
    """Base class for registry errors."""


class InvalidPredictionError(RegistryError):
    """The draft breaks an issue-date rule."""


class DuplicatePredictionError(RegistryError):
    """A record with the same (model version, variable, region, lead, issue date) exists."""


class RegistryTamperError(RegistryError):
    """The file was edited, truncated mid-chain, reordered or is corrupt."""


class InputSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    latency_hours: float = Field(ge=0)  # age of the latest datum used, at issue time


class PredictionDraft(BaseModel):
    """What the caller supplies; the registry adds ``issued_at``, ``seq`` and the hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_date: datetime  # tz-aware; checked against the registry clock
    variable: str = Field(min_length=1)
    region: str = Field(min_length=1)  # region or station id
    lead_days: int = Field(ge=0)
    valid_date: date
    kind: Literal["probability", "value"]
    value: float
    interval_low: float
    interval_high: float
    interval_level: float = Field(default=0.9, gt=0, lt=1)
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    training_period: str = Field(pattern=_PERIOD)
    inputs: list[InputSource] = Field(min_length=1)
    inputs_sha256: str = Field(pattern=_HEX64)
    # Free-form JSON payload (quantiles, climatological probability, threshold...). Optional, so older
    # records without it still validate and verify (the hash covers whatever keys are on disk).
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("issue_date")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("issue_date must be timezone-aware (UTC)")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def _check(self) -> PredictionDraft:
        if not self.interval_low <= self.interval_high:
            raise ValueError("interval_low must be <= interval_high")
        if self.kind == "probability" and not all(
            0 <= x <= 1 for x in (self.value, self.interval_low, self.interval_high)
        ):
            raise ValueError("probabilities and their interval must be in [0, 1]")
        return self


class PredictionRecord(PredictionDraft):
    issued_at: datetime
    seq: int = Field(ge=0)
    prev_hash: str = Field(pattern=_HEX64)
    record_hash: str = Field(pattern=_HEX64)


def hash_inputs(inputs: Any) -> str:
    """SHA-256 of the canonical JSON of the inputs descriptor (file hashes, dates, versions)."""
    return hashlib.sha256(_canonical(inputs)).hexdigest()


def compute_record_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({k: v for k, v in record.items() if k != "record_hash"})
    ).hexdigest()


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _key(r: PredictionDraft | PredictionRecord, issued: datetime) -> tuple:
    return (r.model_version, r.variable, r.region, r.lead_days, issued.date())


class PredictionRegistry:
    def __init__(self, path: Path, clock: Callable[[], datetime] = _utc_now) -> None:
        self.path = Path(path)
        self._clock = clock

    def now(self) -> datetime:
        """The registry clock, UTC."""
        return self._clock().astimezone(UTC)

    def read(self) -> list[PredictionRecord]:
        """All records in order. Does not verify the chain; call ``verify()`` for that."""
        return [PredictionRecord.model_validate(raw) for raw in self._raw()]

    def verify(self) -> str | None:
        """Check every link and hash; return the head hash (None if empty) or raise RegistryTamperError."""
        prev = _ZERO_HASH
        for i, raw in enumerate(self._raw()):
            if raw.get("seq") != i:
                raise RegistryTamperError(f"record {i}: sequence broken (got {raw.get('seq')!r})")
            if raw.get("prev_hash") != prev:
                raise RegistryTamperError(
                    f"record {i}: prev_hash does not match the previous record"
                )
            if raw.get("record_hash") != compute_record_hash(raw):
                raise RegistryTamperError(f"record {i}: record_hash mismatch (edited)")
            prev = raw["record_hash"]
        return None if prev == _ZERO_HASH else prev

    def append(self, draft: PredictionDraft) -> PredictionRecord:
        now = self._clock().astimezone(UTC)
        if draft.issue_date < now - ISSUE_TOLERANCE:
            raise InvalidPredictionError(
                f"issue_date {draft.issue_date:%Y-%m-%dT%H:%MZ} is in the past"
            )
        if draft.issue_date > now + ISSUE_TOLERANCE:
            raise InvalidPredictionError(
                f"issue_date {draft.issue_date:%Y-%m-%dT%H:%MZ} is in the future"
            )
        if draft.valid_date < now.date():
            raise InvalidPredictionError("valid_date is before the issue date")
        if draft.valid_date != now.date() + timedelta(days=draft.lead_days):
            raise InvalidPredictionError("valid_date does not match issue date + lead_days")

        head = self.verify()  # refuse to extend a tampered chain
        existing = self.read()
        if any(_key(r, r.issued_at) == _key(draft, now) for r in existing):
            raise DuplicatePredictionError(
                f"already issued: {draft.model_version}/{draft.variable}/{draft.region}/"
                f"lead {draft.lead_days}/{now.date()}"
            )
        body = draft.model_dump(mode="json")
        body.update(
            issued_at=now.isoformat(timespec="seconds"),
            seq=len(existing),
            prev_hash=head or _ZERO_HASH,
        )
        body["record_hash"] = compute_record_hash(body)
        record = PredictionRecord.model_validate(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return record

    def _raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                obj = json.loads(line)
            except ValueError as e:
                raise RegistryTamperError(f"line {n}: not valid JSON") from e
            if not isinstance(obj, dict):
                raise RegistryTamperError(f"line {n}: not an object")
            out.append(obj)
        return out
