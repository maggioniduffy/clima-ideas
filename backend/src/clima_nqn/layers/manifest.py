"""Layer manifest contract (docs/architecture.md): `<root>/<layer_id>/manifest.json`."""

import logging
import re
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PERIOD = re.compile(r"^(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})$")


class LayerManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = Field(min_length=1)
    kind: Literal["events", "points", "raster-frames", "series", "polygons"]
    source: str = Field(min_length=1)
    period: str
    license: str = Field(min_length=1)
    updated_at: datetime
    files: list[str] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _SLUG.fullmatch(v):
            raise ValueError("id must be a slug: lowercase letters, digits and hyphens")
        return v

    @field_validator("period")
    @classmethod
    def _check_period(cls, v: str) -> str:
        m = _PERIOD.fullmatch(v)
        if not m:
            raise ValueError("period must be 'YYYY-MM-DD/YYYY-MM-DD'")
        start, end = (date.fromisoformat(g) for g in m.groups())
        if start > end:
            raise ValueError("period start must be <= end")
        return v

    @field_validator("files")
    @classmethod
    def _check_files(cls, v: list[str]) -> list[str]:
        for name in v:
            if not name or "\\" in name:
                raise ValueError(f"invalid file name: {name!r}")
            p = PurePosixPath(name)
            if p.is_absolute() or PureWindowsPath(name).is_absolute() or ".." in p.parts:
                raise ValueError(f"file must be a relative path without '..': {name!r}")
        return v


def load_manifest(path: Path) -> LayerManifest:
    return LayerManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_layer(root: Path, layer_id: str) -> LayerManifest | None:
    """Load `<root>/<layer_id>/manifest.json`; None if absent or invalid (logged)."""
    if not _SLUG.fullmatch(layer_id):
        return None
    path = Path(root) / layer_id / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        manifest = load_manifest(path)
    except (OSError, ValueError) as exc:  # ValidationError is a ValueError
        logger.warning("skipping invalid manifest %s: %s", path, exc)
        return None
    if manifest.id != layer_id:
        logger.warning("skipping %s: folder name %r != manifest id %r", path, layer_id, manifest.id)
        return None
    return manifest


def discover_layers(root: Path) -> list[LayerManifest]:
    root = Path(root)
    if not root.is_dir():
        return []
    layers = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / MANIFEST_NAME).is_file():
            m = load_layer(root, child.name)
            if m is not None:
                layers.append(m)
    return layers
