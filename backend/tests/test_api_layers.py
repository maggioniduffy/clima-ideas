import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clima_nqn.api.app import create_app

BASE = {
    "title": "T",
    "kind": "series",
    "source": "S",
    "period": "2000-01-01/2001-01-01",
    "license": "CC0",
    "updated_at": "2026-01-02T03:04:05Z",
    "files": ["a.parquet"],
}


def _write(root: Path, folder: str, data: dict) -> None:
    d = root / folder
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    _write(tmp_path, "good-a", {**BASE, "id": "good-a"})
    _write(tmp_path, "good-b", {**BASE, "id": "good-b"})
    _write(tmp_path, "bad", {**BASE, "id": "bad", "kind": "nope"})
    _write(tmp_path, "mismatch", {**BASE, "id": "other"})
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "manifest.json").write_text("{", encoding="utf-8")
    return TestClient(create_app(tmp_path))


def test_health_still_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_layers_skips_invalid(client: TestClient) -> None:
    r = client.get("/layers")
    assert r.status_code == 200
    assert sorted(m["id"] for m in r.json()) == ["good-a", "good-b"]


def test_get_layer(client: TestClient) -> None:
    r = client.get("/layers/good-a")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "good-a"
    assert body["files"] == ["a.parquet"]


@pytest.mark.parametrize("layer_id", ["missing", "bad", "mismatch", "..%2Fx"])
def test_unknown_or_invalid_id_404(client: TestClient, layer_id: str) -> None:
    assert client.get(f"/layers/{layer_id}").status_code == 404


def test_missing_root_lists_empty(tmp_path: Path) -> None:
    c = TestClient(create_app(tmp_path / "nope"))
    assert c.get("/layers").json() == []
