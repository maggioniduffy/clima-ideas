import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from clima_nqn.layers.manifest import LayerManifest, discover_layers, load_layer

# <repo>/backend/src/clima_nqn/api/app.py -> parents[4] == <repo>
_FRAME_ID = re.compile(r"^[A-Za-z0-9_-]+$")
FRAMES_INDEX = "frames/index.json"

DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[4] / "data" / "processed"


def create_app(data_root: Path | None = None) -> FastAPI:
    root = Path(data_root or os.environ.get("CLIMA_NQN_DATA") or DEFAULT_DATA_ROOT)
    app = FastAPI(title="clima-nqn")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/layers")
    def list_layers() -> list[LayerManifest]:
        return discover_layers(root)

    @app.get("/layers/{layer_id}")
    def get_layer(layer_id: str) -> LayerManifest:
        manifest = load_layer(root, layer_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail=f"layer not found: {layer_id}")
        return manifest

    @app.get("/layers/{layer_id}/data")
    def get_layer_data(layer_id: str, file: str | None = None) -> FileResponse:
        manifest = load_layer(root, layer_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail=f"layer not found: {layer_id}")
        name = file if file is not None else manifest.files[0]
        # Only names listed verbatim in the manifest are served (blocks traversal).
        if name not in manifest.files:
            raise HTTPException(status_code=404, detail=f"file not in manifest: {name}")
        path = root / layer_id / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"file missing: {name}")
        return FileResponse(path)

    @app.get("/layers/{layer_id}/frames/{t}")
    def get_layer_frames(layer_id: str, t: str) -> FileResponse:
        """Binary Float32 frames of one frame set `t` (for ar-events: the event id)."""
        manifest = load_layer(root, layer_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail=f"layer not found: {layer_id}")
        # Only layers that publish a frames index serve frames; `t` is a plain id (no traversal).
        if FRAMES_INDEX not in manifest.files or not _FRAME_ID.fullmatch(t):
            raise HTTPException(status_code=404, detail=f"frames not found: {t}")
        path = root / layer_id / "frames" / f"{t}.bin"
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"frames not found: {t}")
        return FileResponse(path, media_type="application/octet-stream")

    return app


app = create_app()
