"""F6.4: append-only registry of frozen predictions."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from clima_nqn.forecast.registry import (
    DuplicatePredictionError,
    InputSource,
    InvalidPredictionError,
    PredictionDraft,
    PredictionRegistry,
    RegistryTamperError,
    hash_inputs,
)

NOW = datetime(2027, 6, 10, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def draft(**over) -> PredictionDraft:
    base = {
        "issue_date": NOW,
        "variable": "streamflow_exceed_p90",
        "region": "12004",
        "lead_days": 3,
        "valid_date": date(2027, 6, 13),
        "kind": "probability",
        "value": 0.3,
        "interval_low": 0.1,
        "interval_high": 0.5,
        "model_name": "climatology",
        "model_version": "v1",
        "training_period": "2000-01-01/2020-12-31",
        "inputs": [InputSource(name="era5t", latency_hours=120.0)],
        "inputs_sha256": hash_inputs({"era5t": "2027-06-05"}),
    }
    base.update(over)
    return PredictionDraft(**base)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def reg(tmp_path: Path, clock: Clock) -> PredictionRegistry:
    return PredictionRegistry(tmp_path / "registry.jsonl", clock=clock)


def test_round_trip(reg: PredictionRegistry) -> None:
    a = reg.append(draft())
    b = reg.append(draft(lead_days=4, valid_date=date(2027, 6, 14)))
    records = reg.read()
    assert records == [a, b]
    assert (a.seq, b.seq) == (0, 1)
    assert b.prev_hash == a.record_hash
    assert a.issued_at == NOW
    assert a.inputs[0].latency_hours == 120.0
    assert reg.verify() == b.record_hash


def test_empty_registry(reg: PredictionRegistry) -> None:
    assert reg.read() == []
    assert reg.verify() is None


def test_edit_detected(reg: PredictionRegistry) -> None:
    reg.append(draft())
    reg.append(draft(lead_days=4, valid_date=date(2027, 6, 14)))
    lines = reg.path.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["value"] = 0.9
    lines[0] = json.dumps(rec)
    reg.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(RegistryTamperError):
        reg.verify()


def test_rehashed_edit_breaks_chain(reg: PredictionRegistry) -> None:
    """Editing a record and recomputing its own hash still breaks the next record's link."""
    from clima_nqn.forecast.registry import compute_record_hash

    reg.append(draft())
    reg.append(draft(lead_days=4, valid_date=date(2027, 6, 14)))
    lines = reg.path.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["value"] = 0.9
    rec["record_hash"] = compute_record_hash(rec)
    lines[0] = json.dumps(rec)
    reg.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(RegistryTamperError):
        reg.verify()


def test_deleted_record_detected(reg: PredictionRegistry) -> None:
    for lead in (1, 2, 3):
        reg.append(draft(lead_days=lead, valid_date=NOW.date() + timedelta(days=lead)))
    lines = reg.path.read_text().splitlines()
    reg.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(RegistryTamperError):
        reg.verify()


def test_append_refuses_tampered_file(reg: PredictionRegistry) -> None:
    reg.append(draft())
    rec = json.loads(reg.path.read_text())
    rec["region"] = "other"
    reg.path.write_text(json.dumps(rec) + "\n")
    with pytest.raises(RegistryTamperError):
        reg.append(draft(lead_days=4, valid_date=date(2027, 6, 14)))


def test_no_mutating_api(reg: PredictionRegistry) -> None:
    public = {n for n in dir(reg) if not n.startswith("_")}
    assert public == {"append", "read", "verify", "path"}


def test_past_issue_date_rejected(reg: PredictionRegistry) -> None:
    with pytest.raises(InvalidPredictionError, match="past"):
        reg.append(draft(issue_date=NOW - timedelta(days=1), valid_date=date(2027, 6, 12)))
    assert reg.read() == []


def test_small_tolerance_allowed(reg: PredictionRegistry) -> None:
    rec = reg.append(draft(issue_date=NOW - timedelta(seconds=30)))
    assert rec.issued_at == NOW  # stamped by the registry's clock, not the caller


def test_future_issue_date_rejected(reg: PredictionRegistry) -> None:
    with pytest.raises(InvalidPredictionError):
        reg.append(draft(issue_date=NOW + timedelta(days=1), valid_date=date(2027, 6, 14)))


def test_naive_issue_date_rejected() -> None:
    with pytest.raises(ValueError):
        draft(issue_date=datetime(2027, 6, 10, 12, 0))


def test_valid_before_issue_rejected(reg: PredictionRegistry) -> None:
    with pytest.raises(InvalidPredictionError, match="valid_date"):
        reg.append(draft(valid_date=date(2027, 6, 9)))


def test_valid_date_must_match_lead(reg: PredictionRegistry) -> None:
    with pytest.raises(InvalidPredictionError, match="lead"):
        reg.append(draft(valid_date=date(2027, 6, 20)))


def test_duplicate_rejected(reg: PredictionRegistry, clock: Clock) -> None:
    reg.append(draft())
    clock.now = NOW + timedelta(hours=3)  # same UTC issue date
    with pytest.raises(DuplicatePredictionError):
        reg.append(draft(issue_date=clock.now, value=0.4))
    assert len(reg.read()) == 1


def test_same_key_other_version_or_day_allowed(reg: PredictionRegistry, clock: Clock) -> None:
    reg.append(draft())
    reg.append(draft(model_version="v2"))
    reg.append(draft(region="other"))
    clock.now = NOW + timedelta(days=1)
    reg.append(draft(issue_date=clock.now, valid_date=date(2027, 6, 14)))
    assert len(reg.read()) == 4


def test_probability_range_and_interval(reg: PredictionRegistry) -> None:
    with pytest.raises(ValueError):
        draft(value=1.5)
    with pytest.raises(ValueError):
        draft(interval_low=0.6, interval_high=0.5)
    with pytest.raises(ValueError):
        draft(inputs_sha256="abc")


def test_hash_inputs_is_stable() -> None:
    assert hash_inputs({"a": 1, "b": 2}) == hash_inputs({"b": 2, "a": 1})
    assert hash_inputs({"a": 1}) != hash_inputs({"a": 2})
    assert len(hash_inputs({})) == 64
