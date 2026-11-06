import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clima_nqn.api.app import create_app

MANIFEST = {
    "id": "pts",
    "title": "T",
    "kind": "points",
    "source": "S",
    "period": "2000-01-01/2001-01-01",
    "license": "CC0",
    "updated_at": "2026-01-02T03:04:05Z",
    "files": ["a.json", "sub/b.bin"],
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    d = tmp_path / "pts"
    (d / "sub").mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    (d / "a.json").write_text('[{"id": 1}]', encoding="utf-8")
    (d / "sub" / "b.bin").write_bytes(b"\x00\x01\x02")
    (d / "secret.txt").write_text("nope", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    return TestClient(create_app(tmp_path))


def test_default_serves_first_file(client: TestClient) -> None:
    r = client.get("/layers/pts/data")
    assert r.status_code == 200
    assert r.json() == [{"id": 1}]
    assert r.headers["content-type"].startswith("application/json")


def test_file_param_selects_listed_file(client: TestClient) -> None:
    r = client.get("/layers/pts/data", params={"file": "sub/b.bin"})
    assert r.status_code == 200
    assert r.content == b"\x00\x01\x02"


def test_unlisted_file_404(client: TestClient) -> None:
    assert client.get("/layers/pts/data", params={"file": "secret.txt"}).status_code == 404
    assert client.get("/layers/pts/data", params={"file": "manifest.json"}).status_code == 404


@pytest.mark.parametrize(
    "bad", ["../outside.txt", "..%2Foutside.txt", "/etc/passwd", "sub/../secret.txt"]
)
def test_path_traversal_404(client: TestClient, bad: str) -> None:
    r = client.get(f"/layers/pts/data?file={bad}")
    assert r.status_code == 404


def test_unknown_layer_404(client: TestClient) -> None:
    assert client.get("/layers/nope/data").status_code == 404


def test_listed_but_missing_file_404(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "pts" / "a.json").unlink()
    assert client.get("/layers/pts/data").status_code == 404
