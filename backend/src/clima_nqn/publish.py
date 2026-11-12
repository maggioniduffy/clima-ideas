"""Publish processed layers to Cloudflare R2 (S3 API) as a static mirror of the FastAPI routes."""

import json
import logging
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clima_nqn.layers.manifest import MANIFEST_NAME, LayerManifest, discover_layers

logger = logging.getLogger(__name__)

FRAMES_INDEX = "frames/index.json"  # same rule as api/app.py get_layer_frames
_FRAME_ID = re.compile(r"^[A-Za-z0-9_-]+$")
INDEX_NAME = "layers.json"
INDEX_CACHE = "public, max-age=300"
DATA_CACHE = "public, max-age=86400"
ENV_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")

_CONTENT_TYPES = {".json": "application/json", ".geojson": "application/geo+json"}


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
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def index_json(index: list[LayerManifest]) -> bytes:
    """Same JSON as `GET /layers` (pydantic JSON mode, list of manifests)."""
    return json.dumps([m.model_dump(mode="json") for m in index]).encode("utf-8")


def build_index(root: Path) -> list[LayerManifest]:
    return discover_layers(root)


def plan_uploads(root: Path, prefix: str = "") -> list[Upload]:
    root = Path(root)
    pre = prefix.strip("/") + "/" if prefix.strip("/") else ""
    index = build_index(root)
    uploads = [Upload(pre + INDEX_NAME, "application/json", INDEX_CACHE, data=index_json(index))]
    for m in index:
        folder = root / m.id
        uploads.append(
            Upload(
                f"{pre}{m.id}/{MANIFEST_NAME}",
                "application/json",
                INDEX_CACHE,
                path=folder / MANIFEST_NAME,
            )
        )
        rels = list(m.files)
        for f in m.files:
            if not (folder / f).is_file():
                logger.warning("layer %s lists missing file %s; skipped", m.id, f)
        if FRAMES_INDEX in m.files:
            rels += [
                f"frames/{p.name}"
                for p in sorted((folder / "frames").glob("*.bin"))
                if _FRAME_ID.fullmatch(p.stem)
            ]
        for rel in dict.fromkeys(rels):
            if (folder / rel).is_file():
                uploads.append(
                    Upload(
                        f"{pre}{m.id}/{rel}",
                        content_type(rel),
                        DATA_CACHE,
                        path=folder / rel,
                    )
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
    # The index goes last so a failed run never lists layers whose files are not uploaded yet.
    uploads = uploads[1:] + uploads[:1]
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
