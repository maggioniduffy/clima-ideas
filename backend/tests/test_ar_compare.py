import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from clima_nqn.stages.ar import compare

# BARD-like grid: cell centers off the polygon edges (polygon lon -71.95..-70, lat -41.1..-36).
LAT = -42.75 + 0.5 * np.arange(17)
LON = -73.75 + 0.5 * np.arange(16)
IN_LAT, IN_LON = -38.25, -70.75  # inside the polygon
OUT_LAT, OUT_LON = -34.75, -66.25  # outside
# A finer, shifted grid for the ClimateNet-like file (different grid, as in the real run).
LAT2 = -42.9 + 0.25 * np.arange(34)
LON2 = -73.9 + 0.3125 * np.arange(25)


def times_for(year, n=8):
    return pd.date_range(f"{year}-01-01", periods=n, freq="6h")


def bard_ds(times, hit_steps, lat=IN_LAT, lon=IN_LON, prob=0.9):
    p = np.zeros((len(times), LAT.size, LON.size), dtype="float32")
    for i in hit_steps:
        p[i, np.flatnonzero(LAT == lat)[0], np.flatnonzero(LON == lon)[0]] = prob
    return xr.Dataset(
        {"ar_probability": (("time", "lat", "lon"), p)},
        coords={"time": times, "lat": LAT, "lon": LON},
    )


def mask_ds(times, hit_steps, lat, lon, lat_grid, lon_grid):
    """ar_mask with one cell flagged (nearest to lat, lon) at ``hit_steps``."""
    m = np.zeros((len(times), lat_grid.size, lon_grid.size), dtype="uint8")
    i, j = np.abs(lat_grid - lat).argmin(), np.abs(lon_grid - lon).argmin()
    for t in hit_steps:
        m[t, i, j] = 1
    return xr.Dataset(
        {"ar_mask": (("time", "lat", "lon"), m)},
        coords={"time": times, "lat": lat_grid, "lon": lon_grid},
    )


def write_all(
    tmp_path,
    year,
    bard_hits,
    cn_hits,
    ivt_hits,
    n=8,
    cn_cell=(IN_LAT, IN_LON),
    ivt_cell=(IN_LAT, IN_LON),
):
    times = times_for(year, n)
    dirs = {k: tmp_path / k / f"artifact-{year}" for k in ("bard", "cn", "ivt")}
    for d in dirs.values():
        d.mkdir(parents=True)
    bard_ds(times, bard_hits).to_netcdf(dirs["bard"] / f"bard_neuquen_{year}.nc")
    cn = mask_ds(times, cn_hits, *cn_cell, LAT2, LON2)
    cn.attrs = {
        "model_commit": "abc123",
        "weights_url": "https://example.org/w.pth",
        "model_repo": "r",
    }
    cn.to_netcdf(dirs["cn"] / f"climatenet_neuquen_{year}.nc")
    mask_ds(times, ivt_hits, *ivt_cell, LAT, LON).to_netcdf(
        dirs["ivt"] / f"ivt_threshold_neuquen_{year}.nc"
    )
    return tmp_path / "bard", tmp_path / "cn", tmp_path / "ivt"


# --- metrics -------------------------------------------------------------------------------


def test_contingency_counts():
    a = np.array([1, 1, 0, 0, 1], dtype=bool)
    b = np.array([1, 0, 1, 0, 1], dtype=bool)
    assert compare.contingency(a, b) == {"n11": 2, "n10": 1, "n01": 1, "n00": 1}


def test_perfect_agreement():
    f = np.array([1, 0, 1, 1, 0, 0], dtype=bool)
    m = compare.agreement(f, f)
    assert (m["hit_rate"], m["false_alarm_ratio"], m["kappa"], m["jaccard"]) == (1.0, 0.0, 1.0, 1.0)


def test_disjoint_agreement():
    a = np.array([1, 1, 0, 0], dtype=bool)
    b = np.array([0, 0, 1, 1], dtype=bool)
    m = compare.agreement(a, b)
    assert m["hit_rate"] == 0.0 and m["false_alarm_ratio"] == 1.0 and m["jaccard"] == 0.0
    assert m["kappa"] == pytest.approx(-1.0)


def test_kappa_known_value():
    # n11=20 n10=5 n01=10 n00=65: po=.85, pe=.25*.30+.75*.70=.60 -> kappa=.625
    a = np.array([1] * 25 + [0] * 75, dtype=bool)
    b = np.concatenate([np.ones(20), np.zeros(5), np.ones(10), np.zeros(65)]).astype(bool)
    m = compare.agreement(a, b)
    assert m["kappa"] == pytest.approx(0.625)
    assert m["hit_rate"] == pytest.approx(20 / 30)
    assert m["false_alarm_ratio"] == pytest.approx(5 / 25)
    assert m["jaccard"] == pytest.approx(20 / 35)


def test_degenerate_cases_are_nan_not_errors():
    none = np.zeros(5, dtype=bool)
    m = compare.agreement(none, none)
    assert np.isnan(m["kappa"]) and np.isnan(m["hit_rate"]) and np.isnan(m["jaccard"])


def test_cell_iou_known_values():
    a = np.zeros((3, 4), dtype=bool)
    b = np.zeros((3, 4), dtype=bool)
    a[0, :2] = True  # step 0: a = cells 0,1
    b[0, 1:3] = True  # b = cells 1,2 -> inter 1, union 3
    a[1, :] = b[1, :] = True  # step 1: identical, inter 4, union 4
    # step 2: nobody flags -> excluded
    iou = compare.cell_iou(a, b)
    assert iou["n_steps"] == 2
    assert iou["iou_pooled"] == pytest.approx(5 / 7)
    assert iou["iou_mean"] == pytest.approx((1 / 3 + 1) / 2)


def test_cell_iou_no_flagged_steps():
    z = np.zeros((2, 3), dtype=bool)
    assert compare.cell_iou(z, z)["n_steps"] == 0


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        compare.contingency(np.zeros(3, dtype=bool), np.zeros(4, dtype=bool))


def test_season_mapping_southern_hemisphere():
    t = pd.DatetimeIndex(["2023-01-15", "2023-04-01", "2023-07-31", "2023-10-01", "2023-12-31"])
    assert compare.season_of(t).tolist() == ["DJF", "MAM", "JJA", "SON", "DJF"]


# --- end to end on synthetic files ---------------------------------------------------------


def test_compare_dirs_perfect_agreement_across_grids(tmp_path):
    hits = [1, 4, 5]
    bard, cn, ivt = write_all(tmp_path, 2023, hits, hits, hits)
    results, meta = compare.compare_dirs(bard, cn, ivt)
    assert meta["years_used"] == [2023] and meta["n_steps"] == 8
    for pair in results["pairs"].values():
        m = pair["all"]
        assert (m["n11"], m["n10"], m["n01"], m["n00"]) == (3, 0, 0, 5)
        assert m["kappa"] == 1.0 and m["jaccard"] == 1.0
    # cell IoU: BARD flags one cell; the ivt baseline flags the same cell on the same grid
    assert results["pairs"]["ivt_vs_bard"]["all"]["iou_pooled"] == 1.0
    assert meta["model"]["model_commit"] == "abc123"


def test_compare_dirs_disjoint_and_outside_polygon(tmp_path):
    # ClimateNet flags other steps; the baseline flags the same steps but only outside the polygon -> never AR
    bard, cn, ivt = write_all(tmp_path, 2023, [0, 1], [2, 3], [0, 1], ivt_cell=(OUT_LAT, OUT_LON))
    results, _ = compare.compare_dirs(bard, cn, ivt)
    cn_bard = results["pairs"]["climatenet_vs_bard"]["all"]
    assert (cn_bard["n11"], cn_bard["n10"], cn_bard["n01"]) == (0, 2, 2)
    assert cn_bard["jaccard"] == 0.0 and cn_bard["hit_rate"] == 0.0
    assert results["methods"]["ivt"]["all"]["n_ar_steps"] == 0
    ivt_bard = results["pairs"]["ivt_vs_bard"]["all"]
    assert ivt_bard["n01"] == 2 and ivt_bard["n11"] == 0


def test_compare_dirs_uses_bard_threshold(tmp_path):
    bard, cn, ivt = write_all(tmp_path, 2023, [0], [0], [0])  # BARD prob 0.9
    low = compare.compare_dirs(bard, cn, ivt, threshold=0.5)[0]
    high = compare.compare_dirs(bard, cn, ivt, threshold=0.95)[0]
    assert low["methods"]["bard"]["all"]["n_ar_steps"] == 1
    assert high["methods"]["bard"]["all"]["n_ar_steps"] == 0


def test_compare_dirs_only_shared_years_and_seasons(tmp_path):
    a = write_all(tmp_path / "a", 2022, [0], [0], [0])
    b = write_all(tmp_path / "b", 2023, [1], [1], [1])
    # merge the two years into three dirs; add a year only BARD has
    for kind in range(3):
        (tmp_path / "all" / f"d{kind}").mkdir(parents=True)
        for src in (a[kind], b[kind]):
            for f in src.rglob("*.nc"):
                (tmp_path / "all" / f"d{kind}" / f.name).write_bytes(f.read_bytes())
    extra = tmp_path / "all" / "d0" / "bard_neuquen_2020.nc"
    extra.write_bytes((tmp_path / "all" / "d0" / "bard_neuquen_2022.nc").read_bytes())
    results, meta = compare.compare_dirs(*(tmp_path / "all" / f"d{k}" for k in range(3)))
    assert meta["years_used"] == [2022, 2023]
    assert meta["years_found"]["bard"] == [2020, 2022, 2023]
    assert results["methods"]["bard"]["DJF"]["n_steps"] == 16  # January steps
    assert results["methods"]["bard"]["JJA"]["n_steps"] == 0


def test_no_shared_year_raises(tmp_path):
    bard, _cn, ivt = write_all(tmp_path, 2023, [0], [0], [0])
    other = tmp_path / "empty"
    other.mkdir()
    with pytest.raises(ValueError, match="no year"):
        compare.compare_dirs(bard, other, ivt)


def test_run_writes_spanish_report_and_json(tmp_path):
    bard, cn, ivt = write_all(tmp_path, 2023, [1, 4], [1, 4], [1, 5])
    out = tmp_path / "out"
    compare.main(
        [
            "--bard-dir",
            str(bard),
            "--climatenet-dir",
            str(cn),
            "--ivt-dir",
            str(ivt),
            "--out-dir",
            str(out),
        ]
    )
    md = (out / "F1.7.md").read_text(encoding="utf-8")
    assert "# F1.7" in md and "Salvedades" in md and "sin verificar" in md and "CAM5" in md
    assert "https://example.org/w.pth" in md
    data = json.loads((out / "F1.7.json").read_text(encoding="utf-8"))
    assert data["meta"]["years_used"] == [2023]
    assert data["meta"]["model"]["model_commit"] == "abc123"
    assert data["results"]["pairs"]["climatenet_vs_bard"]["all"]["kappa"] == 1.0
    assert data["results"]["pairs"]["ivt_vs_bard"]["all"]["n10"] == 1
