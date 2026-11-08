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


def _frames_client(tmp_path: Path, with_index: bool = True) -> TestClient:
    manifest = {**MANIFEST, "id": "fr", "kind": "events", "files": ["a.json"]}
    if with_index:
        manifest["files"].append("frames/index.json")
    d = tmp_path / "fr"
    (d / "frames").mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "a.json").write_text("[]", encoding="utf-8")
    (d / "frames" / "index.json").write_text("{}", encoding="utf-8")
    (d / "frames" / "AR-2000-001.bin").write_bytes(b"\x00\x00\x80\x3f")
    (d / "secret.bin").write_bytes(b"x")
    return TestClient(create_app(tmp_path))


def test_frames_served_as_binary(tmp_path: Path) -> None:
    r = _frames_client(tmp_path).get("/layers/fr/frames/AR-2000-001")
    assert r.status_code == 200
    assert r.content == b"\x00\x00\x80\x3f"
    assert r.headers["content-type"] == "application/octet-stream"


def test_frames_missing_or_bad_id_404(tmp_path: Path) -> None:
    c = _frames_client(tmp_path)
    assert c.get("/layers/fr/frames/AR-1999-001").status_code == 404
    assert c.get("/layers/fr/frames/..%2Fsecret").status_code == 404
    assert c.get("/layers/nope/frames/AR-2000-001").status_code == 404


def test_frames_404_without_index_in_manifest(tmp_path: Path) -> None:
    c = _frames_client(tmp_path, with_index=False)
    assert c.get("/layers/fr/frames/AR-2000-001").status_code == 404
