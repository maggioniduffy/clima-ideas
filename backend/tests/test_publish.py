import json
import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clima_nqn import cli
from clima_nqn.layers.manifest import discover_layers
from clima_nqn.publish import build_index, plan_uploads, publish_layers, resolve_credentials

BASE = {
    "title": "T",
    "kind": "series",
    "source": "S",
    "period": "2000-01-01/2001-01-01",
    "license": "CC0",
    "updated_at": "2026-01-02T03:04:05Z",
    "files": ["a.parquet"],
}
ENV = {
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key-id",
    "R2_SECRET_ACCESS_KEY": "s3cret-value",
    "R2_BUCKET": "bkt",
}


def _layer(root: Path, name: str, files: list[str], **extra: object) -> Path:
    d = root / name
    d.mkdir(parents=True)
    data = {**BASE, "id": name, "files": files, **extra}
    (d / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return d


class FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    a = _layer(tmp_path, "b-layer", ["data.geojson"])
    (a / "data.geojson").write_text("{}", encoding="utf-8")
    (a / "unlisted.txt").write_text("x", encoding="utf-8")
    inc = _layer(tmp_path, "incomplete", ["data.geojson", "missing.json"])
    (inc / "data.geojson").write_text("{}", encoding="utf-8")
    z = _layer(tmp_path, "a-layer", ["a.parquet", "frames/index.json"])
    (z / "a.parquet").write_bytes(b"PAR1")
    (z / "frames").mkdir()
    (z / "frames" / "index.json").write_text("{}", encoding="utf-8")
    (z / "frames" / "ev-1.bin").write_bytes(b"\x00\x01")
    (z / "frames" / "bad.name.bin").write_bytes(b"no")
    nf = _layer(tmp_path, "no-frames", ["a.parquet"])
    (nf / "a.parquet").write_bytes(b"PAR1")
    (nf / "frames").mkdir()
    (nf / "frames" / "ev-1.bin").write_bytes(b"\x00")
    _layer(tmp_path, "bad", ["a.parquet"], kind="nope")
    _layer(tmp_path, "mismatch", ["a.parquet"], id="other")
    return tmp_path


def _by_key(root: Path, prefix: str = "") -> dict:
    return {u.key: u for u in plan_uploads(root, prefix)}


def test_index_matches_valid_manifests_sorted(tree: Path) -> None:
    index = build_index(tree)
    assert [m.id for m in index] == ["a-layer", "b-layer", "no-frames"]
    # `incomplete` is a valid manifest but lists a missing file: left out of the index.
    assert [m.id for m in discover_layers(tree)] == [
        "a-layer",
        "b-layer",
        "incomplete",
        "no-frames",
    ]


def test_plan_keys_only_listed_files_and_valid_layers(tree: Path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        keys = sorted(_by_key(tree))
    assert keys == [
        "a-layer/a.parquet",
        "a-layer/frames/ev-1.bin",
        "a-layer/frames/index.json",
        "a-layer/manifest.json",
        "b-layer/data.geojson",
        "b-layer/manifest.json",
        "layers.json",
        "no-frames/a.parquet",
        "no-frames/manifest.json",
    ]
    assert "missing.json" in caplog.text


def test_upload_order_data_then_manifest_index_last(tree: Path) -> None:
    keys = [u.key for u in plan_uploads(tree)]
    assert keys[-1] == "layers.json"
    for layer in ("a-layer", "b-layer", "no-frames"):
        own = [i for i, k in enumerate(keys) if k.startswith(layer + "/")]
        assert keys[own[-1]] == f"{layer}/manifest.json"


def test_missing_root_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        plan_uploads(tmp_path / "nope")


def test_layers_json_body_is_api_shape(tree: Path) -> None:
    body = json.loads(_by_key(tree)["layers.json"].body)
    assert body == [m.model_dump(mode="json") for m in build_index(tree)]


def test_content_type_and_cache_control(tree: Path) -> None:
    up = _by_key(tree)
    assert up["layers.json"].content_type == "application/json"
    assert up["layers.json"].cache_control == "public, max-age=300"
    assert up["a-layer/manifest.json"].cache_control == "public, max-age=300"
    assert up["b-layer/data.geojson"].content_type == "application/geo+json"
    assert up["b-layer/data.geojson"].cache_control == "public, max-age=86400"
    assert up["a-layer/frames/index.json"].content_type == "application/json"
    assert up["a-layer/frames/ev-1.bin"].content_type == "application/octet-stream"
    assert up["a-layer/a.parquet"].content_type == "application/octet-stream"
    assert up["a-layer/a.parquet"].cache_control == "public, max-age=86400"


def test_prefix_applied(tree: Path) -> None:
    keys = set(_by_key(tree, "v1"))
    assert "v1/layers.json" in keys and "v1/a-layer/manifest.json" in keys
    assert all(k.startswith("v1/") for k in keys)


def test_publish_puts_expected_objects(tree: Path) -> None:
    s3 = FakeS3()
    n, total = publish_layers(tree, s3, "bkt")
    assert n == len(s3.calls) == 9 and total > 0
    assert s3.calls[-1]["Key"] == "layers.json"
    call = next(c for c in s3.calls if c["Key"] == "a-layer/a.parquet")
    assert call["Bucket"] == "bkt"
    assert call["Body"] == b"PAR1"
    assert call["ContentType"] == "application/octet-stream"
    assert call["CacheControl"] == "public, max-age=86400"


def test_resolve_credentials_names_missing_without_values() -> None:
    with pytest.raises(ValueError) as e:
        resolve_credentials({"R2_ACCOUNT_ID": "acct", "R2_BUCKET": "bkt"})
    assert "R2_ACCESS_KEY_ID" in str(e.value) and "R2_SECRET_ACCESS_KEY" in str(e.value)
    assert "acct" not in str(e.value)


def test_cli_dry_run_never_builds_client(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ENV:
        monkeypatch.delenv(k, raising=False)

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("client must not be built")

    monkeypatch.setattr(cli, "make_client", boom)
    r = CliRunner().invoke(cli.app, ["publish", "--dry-run", "--root", str(tree), "--prefix", "p"])
    assert r.exit_code == 0, r.output
    assert "p/layers.json" in r.output
    assert "application/geo+json" in r.output
    assert "9 objects" in r.output


def test_cli_missing_env_exits_1(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("R2_BUCKET", "bkt")
    monkeypatch.setattr(cli, "make_client", lambda *_a, **_k: pytest.fail("no client"))
    r = CliRunner().invoke(cli.app, ["publish", "--root", str(tree)])
    assert r.exit_code == 1
    assert "R2_ACCOUNT_ID" in r.stderr and "R2_ACCESS_KEY_ID" in r.stderr
    assert "R2_BUCKET" not in r.stderr


def test_cli_missing_root_exits_1_before_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "make_client", lambda *_a, **_k: pytest.fail("no client"))
    for args in (["--dry-run"], []):
        r = CliRunner().invoke(cli.app, ["publish", "--root", str(tmp_path / "nope"), *args])
        assert r.exit_code == 1
        assert "data root not found" in r.stderr


def test_cli_real_run_uses_fake_client(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    s3 = FakeS3()
    monkeypatch.setattr(cli, "make_client", lambda *_a, **_k: s3)
    r = CliRunner().invoke(cli.app, ["publish", "--root", str(tree)])
    assert r.exit_code == 0, r.output
    assert {c["Key"] for c in s3.calls} == set(_by_key(tree))
    assert "9 objects" in r.output
    assert ENV["R2_SECRET_ACCESS_KEY"] not in r.output
