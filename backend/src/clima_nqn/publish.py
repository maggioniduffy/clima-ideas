"""Publish processed layers to Cloudflare R2 (S3 API) as a static mirror of the FastAPI routes."""

import json
import logging
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clima_nqn.layers.manifest import MANIFEST_NAME, LayerManifest, discover_layers, load_layer

logger = logging.getLogger(__name__)

FRAMES_INDEX = "frames/index.json"  # same rule as api/app.py get_layer_frames
_FRAME_ID = re.compile(r"^[A-Za-z0-9_-]+$")
INDEX_NAME = "layers.json"
INDEX_CACHE = "public, max-age=300"
DATA_CACHE = "public, max-age=86400"
ENV_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")

_CONTENT_TYPES = {".json": "application/json", ".geojson": "application/geo+json"}
# Python's built-in table only: the global ``mimetypes`` also reads the host's /etc/mime.types, so the
# same file got a different Content-Type on machines whose system table knows it (e.g. .parquet).
_MIME = mimetypes.MimeTypes(filenames=())


@dataclass(frozen=True)
class Upload:
    key: str
    content_type: str
    cache_control: str
    path: Path | None = None
    data: bytes | None = None

    @property
    def body(self) -> bytes:
        return self.data if self.data is not None else self.path.read_bytes()  # type: ignore[union-attr]

    @property
    def size(self) -> int:
        return len(self.data) if self.data is not None else self.path.stat().st_size  # type: ignore[union-attr]


def content_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in _CONTENT_TYPES:
        return _CONTENT_TYPES[suffix]
    guessed, _ = _MIME.guess_type(name)
    return guessed or "application/octet-stream"


def index_json(index: list[LayerManifest]) -> bytes:
    """Same JSON as `GET /layers` (pydantic JSON mode, list of manifests)."""
    return json.dumps([m.model_dump(mode="json") for m in index]).encode("utf-8")


def _layer_files(root: Path, m: LayerManifest) -> list[str]:
    """Relative paths to upload for one layer: listed files plus frames (same rule as the API)."""
    folder = root / m.id
    rels = list(m.files)
    if FRAMES_INDEX in m.files:
        rels += [
            f"frames/{p.name}"
            for p in sorted((folder / "frames").glob("*.bin"))
            if _FRAME_ID.fullmatch(p.stem)
        ]
    return list(dict.fromkeys(rels))


def build_index(root: Path) -> list[LayerManifest]:
    """Valid layers whose listed files all exist; incomplete layers are logged and left out."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"data root not found: {root}")
    index = []
    for m in discover_layers(root):
        missing = [f for f in m.files if not (root / m.id / f).is_file()]
        if missing:
            logger.warning("layer %s skipped: listed files missing: %s", m.id, ", ".join(missing))
            continue
        index.append(m)
    return index


def plan_uploads(root: Path, prefix: str = "") -> list[Upload]:
    """Upload order: each layer's data, then its manifest; `layers.json` last.

    A failed run then never exposes a manifest or index entry whose objects are not uploaded yet.
    """
    root = Path(root)
    pre = prefix.strip("/") + "/" if prefix.strip("/") else ""
    index = build_index(root)
    uploads: list[Upload] = []
    for m in index:
        folder = root / m.id
        for rel in _layer_files(root, m):
            uploads.append(
                Upload(f"{pre}{m.id}/{rel}", content_type(rel), DATA_CACHE, path=folder / rel)
            )
        uploads.append(
            Upload(
                f"{pre}{m.id}/{MANIFEST_NAME}",
                "application/json",
                INDEX_CACHE,
                path=folder / MANIFEST_NAME,
            )
        )
    uploads.append(
        Upload(pre + INDEX_NAME, "application/json", INDEX_CACHE, data=index_json(index))
    )
    return uploads


def resolve_credentials(env: Mapping[str, str]) -> dict[str, str]:
    """Return the four R2 settings; raise ValueError naming (never showing) missing variables."""
    missing = [v for v in ENV_VARS if not env.get(v)]
    if missing:
        raise ValueError("missing environment variables: " + ", ".join(missing))
    return {v: env[v] for v in ENV_VARS}


def make_client(account_id: str, access_key_id: str, secret_access_key: str) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def publish_layers(root: Path, client: Any, bucket: str, prefix: str = "") -> tuple[int, int]:
    """Upload every planned object; returns (objects, total bytes)."""
    total = 0
    uploads = plan_uploads(root, prefix)
    for u in uploads:
        body = u.body
        client.put_object(
            Bucket=bucket,
            Key=u.key,
            Body=body,
            ContentType=u.content_type,
            CacheControl=u.cache_control,
        )
        total += len(body)
    return len(uploads), total


class PublishError(Exception):
    """A publish step was refused (nothing, or nothing further, was uploaded)."""


def plan_layer_uploads(root: Path, layer_id: str, prefix: str = "") -> list[Upload]:
    """One layer's data files, then its manifest (no index). Raises PublishError if it is not publishable."""
    root = Path(root)
    pre = prefix.strip("/") + "/" if prefix.strip("/") else ""
    m = load_layer(root, layer_id)
    if m is None:
        raise PublishError(f"layer {layer_id!r} not found or invalid under {root}")
    missing = [f for f in m.files if not (root / m.id / f).is_file()]
    if missing:
        raise PublishError(f"layer {layer_id} lists missing files: {', '.join(missing)}")
    folder = root / m.id
    uploads = [
        Upload(f"{pre}{m.id}/{rel}", content_type(rel), DATA_CACHE, path=folder / rel)
        for rel in _layer_files(root, m)
    ]
    uploads.append(
        Upload(
            f"{pre}{m.id}/{MANIFEST_NAME}",
            "application/json",
            INDEX_CACHE,
            path=folder / MANIFEST_NAME,
        )
    )
    return uploads


def read_live_index(client: Any, bucket: str, prefix: str = "") -> list[dict]:
    """The live ``layers.json``; any failure to read or parse it raises PublishError."""
    pre = prefix.strip("/") + "/" if prefix.strip("/") else ""
    try:
        obj = client.get_object(Bucket=bucket, Key=pre + INDEX_NAME)
        index = json.loads(obj["Body"].read())
    except Exception as exc:
        raise PublishError(f"cannot read the live {INDEX_NAME}: {type(exc).__name__}") from exc
    if not isinstance(index, list) or not all(isinstance(e, dict) and "id" in e for e in index):
        raise PublishError(f"the live {INDEX_NAME} is not a list of layer manifests")
    return index


def publish_one_layer(
    root: Path, layer_id: str, client: Any, bucket: str, prefix: str = ""
) -> tuple[int, int]:
    """Upload only ``layer_id`` and merge its entry into the live ``layers.json`` (never rebuilds the index).

    The live index is read first and the run is refused if it cannot be read, so a daily job that only
    owns one layer can never wipe the catalog. Other entries are kept as they are; the list stays sorted by id.
    """
    uploads = plan_layer_uploads(root, layer_id, prefix)
    live = read_live_index(client, bucket, prefix)
    entry = load_layer(Path(root), layer_id).model_dump(mode="json")  # type: ignore[union-attr]
    merged = sorted([e for e in live if e["id"] != layer_id] + [entry], key=lambda e: e["id"])
    pre = prefix.strip("/") + "/" if prefix.strip("/") else ""
    uploads.append(
        Upload(
            pre + INDEX_NAME,
            "application/json",
            INDEX_CACHE,
            data=json.dumps(merged).encode("utf-8"),
        )
    )
    total = 0
    for u in uploads:
        body = u.body
        client.put_object(
            Bucket=bucket,
            Key=u.key,
            Body=body,
            ContentType=u.content_type,
            CacheControl=u.cache_control,
        )
        total += len(body)
    return len(uploads), total
