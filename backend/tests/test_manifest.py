import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clima_nqn.layers.manifest import LayerManifest, load_manifest

VALID = {
    "id": "ar-events",
    "title": "Ríos atmosféricos",
    "kind": "events",
    "source": "ERA5 (Copernicus)",
    "period": "1980-01-01/2025-12-31",
    "license": "CC BY 4.0",
    "updated_at": "2026-01-02T03:04:05Z",
    "files": ["events.parquet"],
}


def test_valid_manifest_loads(tmp_path: Path) -> None:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(VALID), encoding="utf-8")
    m = load_manifest(p)
    assert isinstance(m, LayerManifest)
    assert m.id == "ar-events"
    assert m.kind == "events"
    assert m.files == ["events.parquet"]
    assert m.updated_at.year == 2026


@pytest.mark.parametrize(
    "key,value",
    [
        ("kind", "weird"),
        ("period", "1980/2025"),
        ("period", "2025-12-31/1980-01-01"),
        ("period", "1980-13-01/1990-01-01"),
        ("files", []),
        ("files", ["../secret.parquet"]),
        ("files", ["a/../b.parquet"]),
        ("files", ["/etc/passwd"]),
        ("id", "Bad_ID"),
        ("id", ""),
        ("title", ""),
        ("source", ""),
        ("license", ""),
        ("updated_at", "not-a-date"),
    ],
)
def test_invalid_values_rejected(key: str, value: object) -> None:
    data = copy.deepcopy(VALID)
    data[key] = value
    with pytest.raises(ValidationError):
        LayerManifest.model_validate(data)


@pytest.mark.parametrize("key", list(VALID))
def test_missing_field_rejected(key: str) -> None:
    data = {k: v for k, v in VALID.items() if k != key}
    with pytest.raises(ValidationError):
        LayerManifest.model_validate(data)


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        LayerManifest.model_validate({**VALID, "extra": 1})
