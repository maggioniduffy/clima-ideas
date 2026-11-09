import json

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from clima_nqn.io import dem, era5
from clima_nqn.layers.manifest import LayerManifest


def _tile(values: np.ndarray, west: float, north: float, nodata=-32767.0) -> MemoryFile:
    """Synthetic 1x1 degree GeoTIFF whose pixels are `values`."""
    h, w = values.shape
    mem = MemoryFile()
    with mem.open(
        driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:4326",
        transform=from_origin(west, north, 1.0 / w, 1.0 / h), nodata=nodata,
    ) as ds:  # fmt: skip
        ds.write(values.astype("float32"), 1)
    return mem


def test_tile_name_southern_western_hemisphere():
    assert dem.tile_name(-38, -70) == "Copernicus_DSM_COG_10_S38_00_W070_00_DEM"
    assert dem.tile_name(5, 7) == "Copernicus_DSM_COG_10_N05_00_E007_00_DEM"


def test_tile_url():
    url = dem.tile_url(-38, -70)
    assert url == (
        "https://copernicus-dem-30m.s3.amazonaws.com/"
        "Copernicus_DSM_COG_10_S38_00_W070_00_DEM/Copernicus_DSM_COG_10_S38_00_W070_00_DEM.tif"
    )


def test_tiles_for_bbox_covers_edges():
    tiles = dem.tiles_for_bbox((-71.95, -41.1, -68.0, -36.0))
    assert len(tiles) == 4 * 6
    assert (-42, -72) in tiles and (-37, -69) in tiles
    assert (-36, -72) not in tiles and (-42, -68) not in tiles


def test_default_bbox_is_the_era5_rectangle():
    north, west, south, east = era5.NEUQUEN_BOX
    assert dem.NEUQUEN_BBOX == (west, south, east, north)
    assert len(dem.tiles_for_bbox(dem.NEUQUEN_BBOX)) == 72


def test_default_step_gives_an_integer_sample_count_per_tile_and_a_bounded_point_count():
    assert round(1 / dem.DEFAULT_STEP) == 66 and abs(1 / dem.DEFAULT_STEP - 66) < 1e-9
    assert 250_000 <= 72 * 66**2 <= 400_000


def test_decimate_known_values_and_nodata_dropped():
    # 4x4 raster over lon 0..1, lat 0..1 (north=1); step 0.5 -> 2x2 blocks averaged.
    vals = np.array(
        [[10, 10, 20, 20], [10, 10, 20, 20], [30, 30, -32767, -32767], [30, 30, -32767, -32767]]
    )
    with _tile(vals, 0.0, 1.0).open() as ds:
        pts = dem.decimate_tile(ds, step=0.5)
    assert pts.dtype == np.float32 and pts.shape == (3, 3)  # one all-nodata block dropped
    got = {(round(float(x), 3), round(float(y), 3)): float(z) for x, y, z in pts}
    assert got == {(0.25, 0.75): 10.0, (0.75, 0.75): 20.0, (0.25, 0.25): 30.0}


def test_clip_to_bbox():
    pts = np.array([[0.1, 0.1, 1], [0.9, 0.9, 2]], dtype=np.float32)
    out = dem.clip_bbox(pts, (0.0, 0.0, 0.5, 0.5))
    assert out.shape == (1, 3) and out[0, 2] == 1


def test_write_relief_bytes_manifest_and_meta(tmp_path):
    pts = np.array([[-70.0, -38.0, 500.0], [-69.5, -37.5, 1500.0]], dtype=np.float32)
    out = dem.write_relief(pts, tmp_path, bbox=(-72.0, -42.0, -68.0, -36.0), step=0.005)
    raw = (tmp_path / "relief.bin").read_bytes()
    assert len(raw) == len(pts) * 12
    assert np.frombuffer(raw, dtype="<f4").reshape(-1, 3).tolist() == pts.tolist()
    manifest = LayerManifest.model_validate_json((tmp_path / "manifest.json").read_text())
    assert manifest.id == "relief" and manifest.kind == "points"
    assert manifest.files == ["relief.bin", "relief.meta.json"]
    meta = json.loads((tmp_path / "relief.meta.json").read_text())
    assert meta["count"] == 2 and meta["stride"] == 3
    assert meta["elev_min"] == 500.0 and meta["elev_max"] == 1500.0 and meta["step"] == 0.005
    assert out == tmp_path / "relief.bin"


def test_write_relief_rejects_oversize(tmp_path):
    with pytest.raises(ValueError, match="15 MB"):
        dem.write_relief(np.zeros((1_300_000, 3), dtype=np.float32), tmp_path, (0, 0, 1, 1), 0.01)


def test_build_relief_from_tiles(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    name = dem.tile_name(-38, -70)
    (raw / f"{name}.tif").write_bytes(_tile(np.full((20, 20), 100.0), -70.0, -37.0).read())
    box = [(-70.5, -38.5), (-68.5, -38.5), (-68.5, -36.5), (-70.5, -36.5)]  # whole bbox kept
    out = dem.build_relief(
        raw, tmp_path / "out", bbox=(-70.0, -38.0, -69.0, -37.0), step=0.25, clip_ring=box
    )
    pts = np.fromfile(out, dtype="<f4").reshape(-1, 3)
    assert pts.shape == (16, 3) and set(pts[:, 2]) == {100.0}


def test_build_relief_has_no_polygon_clip_by_default(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / f"{dem.tile_name(-38, -70)}.tif").write_bytes(
        _tile(np.full((20, 20), 100.0), -70.0, -37.0).read()
    )
    out = dem.build_relief(raw, tmp_path / "out", bbox=(-70.0, -38.0, -69.0, -37.0), step=0.25)
    assert np.fromfile(out, dtype="<f4").reshape(-1, 3).shape == (16, 3)


def test_build_relief_skips_tiles_marked_absent_but_rejects_other_missing_tiles(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / f"{dem.tile_name(-38, -70)}.tif").write_bytes(
        _tile(np.full((20, 20), 100.0), -70.0, -37.0).read()
    )
    bbox = (-71.0, -38.0, -69.0, -37.0)  # west neighbour tile (-38, -71) is not there
    with pytest.raises(FileNotFoundError, match="missing tile"):
        dem.build_relief(raw, tmp_path / "out", bbox=bbox, step=0.25)
    (raw / f"{dem.tile_name(-38, -71)}.404").touch()
    out = dem.build_relief(raw, tmp_path / "out", bbox=bbox, step=0.25)
    assert np.fromfile(out, dtype="<f4").reshape(-1, 3).shape == (16, 3)


def test_fetch_tiles_marks_404_tiles_and_does_not_retry_them(tmp_path, monkeypatch):
    seen = []
    tif = _tile(np.full((4, 4), 7.0), -70.0, -37.0).read()

    def handler(request):
        seen.append(request.url.path)
        return (
            httpx.Response(200, content=tif) if "W070" in request.url.path else httpx.Response(404)
        )

    real = httpx.Client
    monkeypatch.setattr(
        dem.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    bbox = (-71.0, -38.0, -69.0, -37.0)  # tiles W071 (404) and W070 (200)
    paths = dem.fetch_tiles(bbox=bbox, dest=tmp_path)
    assert [p.name for p in paths] == [f"{dem.tile_name(-38, -70)}.tif"]
    assert (tmp_path / f"{dem.tile_name(-38, -71)}.404").exists()
    n = len(seen)
    assert [p.name for p in dem.fetch_tiles(bbox=bbox, dest=tmp_path)] == [paths[0].name]
    assert len(seen) == n  # nothing requested again


def test_clip_polygon_keeps_only_points_inside_ring():
    ring = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 1.0), (0.0, 4.0)]  # notch at the top
    pts = np.array([[1, 1, 5], [2, 3, 6], [5, 1, 7], [3, 1, 8], [-1, -1, 9]], dtype=np.float32)
    out = dem.clip_polygon(pts, ring)
    assert out[:, 2].tolist() == [5.0, 8.0]
    assert dem.clip_polygon(np.empty((0, 3), dtype=np.float32), ring).shape == (0, 3)


def test_build_relief_clips_to_ring(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    name = dem.tile_name(-38, -70)
    (raw / f"{name}.tif").write_bytes(_tile(np.full((20, 20), 100.0), -70.0, -37.0).read())
    west_half = [(-70.0, -38.0), (-69.5, -38.0), (-69.5, -37.0), (-70.0, -37.0)]
    out = dem.build_relief(
        raw, tmp_path / "out", bbox=(-70.0, -38.0, -69.0, -37.0), step=0.25, clip_ring=west_half
    )
    pts = np.fromfile(out, dtype="<f4").reshape(-1, 3)
    assert pts.shape == (8, 3) and pts[:, 0].max() < -69.5


@pytest.mark.slow
def test_tile_exists_on_aws():
    import httpx

    r = httpx.head(dem.tile_url(-38, -70), timeout=30)
    assert r.status_code == 200


def test_rasterio_available():
    assert rasterio.__version__
