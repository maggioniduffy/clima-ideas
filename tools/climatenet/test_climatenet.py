"""Tests for the ClimateNet helpers with tiny synthetic arrays (no network, no torch)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).parent))
import climatenet_core as core
import fetch_weights
import run_climatenet

# --- regridding ----------------------------------------------------------------------------


def test_regrid_latitude_orientation_descending_source_to_ascending_target():
    src_lat = np.array([90.0, 30.0, -30.0, -90.0])  # ERA5 order
    src_lon = np.array([0.0, 90.0, 180.0, 270.0])
    field = np.broadcast_to(src_lat[:, None], (4, 4)).copy()  # value = latitude
    dst_lat = np.array([-90.0, -60.0, 0.0, 60.0, 90.0])  # ascending, as the model grid
    out = core.regrid_bilinear(field, src_lat, src_lon, dst_lat, src_lon)
    assert out.shape == (5, 4)
    np.testing.assert_allclose(out[:, 0], dst_lat, atol=1e-4)


def test_regrid_longitude_wraps_around_the_seam():
    src_lat = np.array([-10.0, 10.0])
    src_lon = np.array([0.0, 90.0, 180.0, 270.0])
    field = np.broadcast_to(src_lon, (2, 4)).copy()  # value = longitude
    out = core.regrid_bilinear(
        field, src_lat, src_lon, np.array([0.0]), np.array([45.0, 315.0, 359.0])
    )
    # 315 sits halfway between 270 (value 270) and 360 == 0 (value 0)
    np.testing.assert_allclose(out[0], [45.0, 135.0, 270.0 * (1 / 90)], atol=1e-3)


def test_regrid_accepts_negative_longitudes_and_keeps_extra_leading_dims():
    src_lat = np.array([-10.0, 10.0])
    src_lon = np.array([-180.0, -90.0, 0.0, 90.0])
    field = np.stack([np.broadcast_to(src_lon % 360, (2, 4)), np.zeros((2, 4))]).astype(np.float32)
    out = core.regrid_bilinear(
        field, src_lat, src_lon, np.array([0.0]), np.array([0.0, 90.0, 180.0])
    )
    assert out.shape == (2, 1, 3)
    np.testing.assert_allclose(out[0, 0], [0.0, 90.0, 180.0], atol=1e-4)
    assert not out[1].any()


def test_regrid_latitude_outside_source_takes_edge_row():
    src_lat = np.array([-10.0, 10.0])
    field = np.array([[1.0, 1.0], [3.0, 3.0]])
    out = core.regrid_bilinear(
        field, src_lat, np.array([0.0, 180.0]), np.array([-90.0, 90.0]), np.array([0.0])
    )
    np.testing.assert_allclose(out[:, 0], [1.0, 3.0])


def test_model_grid_shape_and_orientation():
    lat, lon = core.model_grid()
    assert (lat.size, lon.size) == (768, 1152)
    assert lat[0] == -90 and lat[-1] == 90 and np.all(np.diff(lat) > 0)
    assert lon[0] == 0 and lon[-1] < 360


# --- normalization -------------------------------------------------------------------------


def test_normalize_known_values_and_channel_order():
    fields = {
        k: np.full((2, 3, 4), core.STATS[k]["mean"] + core.STATS[k]["std"]) for k in core.FIELDS
    }
    fields["PSL"] = np.full((2, 3, 4), core.STATS["PSL"]["mean"])  # exactly the mean -> 0
    out = core.normalize_fields(fields)
    assert out.shape == (2, 4, 3, 4) and out.dtype == np.float32
    np.testing.assert_allclose(out[:, :3], 1.0, atol=1e-4)
    np.testing.assert_allclose(out[:, 3], 0.0, atol=1e-4)
    # channel order is TMQ, U850, V850, PSL
    only_u = {k: np.full((1, 1, 1), core.STATS[k]["mean"]) for k in core.FIELDS}
    only_u["U850"] = np.full((1, 1, 1), core.STATS["U850"]["mean"] + 2 * core.STATS["U850"]["std"])
    np.testing.assert_allclose(core.normalize_fields(only_u)[0, :, 0, 0], [0, 2, 0, 0], atol=1e-4)


def test_normalize_missing_field_raises():
    with pytest.raises(KeyError):
        core.normalize_fields({"TMQ": np.zeros((1, 1, 1))})


def test_stats_match_repo_config_values():
    assert core.FIELDS == ("TMQ", "U850", "V850", "PSL")
    assert core.STATS["PSL"] == {"mean": 100814.414, "std": 1461.2227}


# --- crop ----------------------------------------------------------------------------------


def test_crop_box_to_neuquen_sorts_and_normalizes_longitude():
    lat = np.arange(-30.0, -46.0, -1.0)  # descending -30 .. -45
    lon = np.arange(280.0, 300.0, 1.0)  # 280..299 -> -80..-61
    lon2d, lat2d = np.meshgrid(lon, lat)
    arr = lat2d * 1000 + lon2d  # encodes both coordinates
    out, clat, clon = core.crop_box(arr, lat, lon)
    assert clat.min() == -43 and clat.max() == -34 and np.all(np.diff(clat) > 0)
    assert clon.min() == -74 and clon.max() == -66 and np.all(np.diff(clon) > 0)
    assert out.shape == (10, 9)
    assert out[0, 0] == -43 * 1000 + 286  # lat -43, lon 286 == -74
    assert out[-1, -1] == -34 * 1000 + 294


def test_crop_box_keeps_leading_dims_and_rejects_empty():
    lat = np.arange(-50.0, -30.0)
    lon = np.arange(-80.0, -60.0)
    out, _, _ = core.crop_box(np.zeros((3, lat.size, lon.size)), lat, lon)
    assert out.shape == (3, 10, 9)
    with pytest.raises(ValueError):
        core.crop_box(np.zeros((2, 2)), np.array([10.0, 20.0]), np.array([0.0, 1.0]))


# --- baseline ------------------------------------------------------------------------------


def test_ivt_baseline_threshold_is_inclusive_and_uses_magnitude():
    u = np.array([[250.0, 150.0, 0.0, np.nan]], dtype=np.float32)
    v = np.array([[0.0, 200.0, 249.9, 100.0]], dtype=np.float32)  # |(150, 200)| == 250
    ivt, hit = core.ivt_baseline(u, v)
    assert ivt.dtype == np.float32
    np.testing.assert_allclose(ivt[0, :3], [250.0, 250.0, 249.9], rtol=1e-6)
    assert hit.tolist() == [[True, True, False, False]]
    assert core.IVT_THRESHOLD == 250.0


# --- run helpers ---------------------------------------------------------------------------


def test_step_times_matches_bard_steps():
    t = run_climatenet.step_times(2024, ["00", "06", "12", "18"])
    assert t.size == 366 * 4
    assert str(t[0]) == "2024-01-01T00:00:00.000000000" and str(t[-1]).startswith(
        "2024-12-31T18:00"
    )
    assert run_climatenet.step_times(2023, ["00", "12"]).size == 365 * 2


def test_mask_dataset_roundtrip(tmp_path):
    times = np.array(["2023-01-01T00:00", "2023-01-01T06:00"], dtype="datetime64[ns]")
    lat, lon = np.array([-40.0, -39.0]), np.array([-70.0, -69.0, -68.0])
    mask = np.zeros((2, 2, 3), dtype=bool)
    mask[1, 0, 2] = True
    ds = run_climatenet.build_mask_dataset(
        times, lat, lon, mask, {"year": 2023}, {"ivt": (np.ones((2, 2, 3)), {})}
    )
    path = tmp_path / "m.nc"
    run_climatenet.write_mask_dataset(ds, path)
    with xr.open_dataset(path) as back:
        assert back["ar_mask"].dtype == np.uint8
        assert back["ar_mask"].dims == ("time", "lat", "lon")
        assert int(back["ar_mask"].sum()) == 1 and int(back["ar_mask"][1, 0, 2]) == 1
        assert back["ivt"].dtype == np.float32
        assert back.attrs["year"] == 2023 and "ARCO-ERA5" in back.attrs["source"]
        assert back["time"].values.tolist() == times.tolist()


# --- weights index parsing -----------------------------------------------------------------

INDEX = """<html><body><a href="?C=N">Name</a><a href="/project/">Parent</a>
<a href="model/weights.pth">weights.pth</a><a href="config.json">config.json</a><a href="notes.txt">n</a></body></html>"""


def test_find_links_and_pick_weights():
    links = fetch_weights.find_links(INDEX, "https://example.org/project/ClimateNet/")
    assert "https://example.org/project/ClimateNet/model/weights.pth" in links
    assert fetch_weights.pick_weights(links).endswith("/model/weights.pth")


def test_pick_weights_none_or_ambiguous():
    with pytest.raises(ValueError, match="no weights"):
        fetch_weights.pick_weights(["https://x/a.txt"])
    two = ["https://x/a.pth", "https://x/b.pth"]
    with pytest.raises(ValueError, match="several"):
        fetch_weights.pick_weights(two)
    assert fetch_weights.pick_weights(two, "b.pth") == "https://x/b.pth"
