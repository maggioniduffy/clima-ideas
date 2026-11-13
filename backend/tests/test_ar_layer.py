import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.layers.manifest import load_manifest
from clima_nqn.stages.ar import catalog, layer

FILES = ["events.json", "events.parquet", "frames/index.json", "frames/footprints.bin"]
LAT = np.array([-40.0, -39.75, -39.5])
LON = np.array([-71.0, -70.75, -70.5, -70.25])


def make_store(tmp_path, year, start, hours):
    times = pd.date_range(start, periods=hours, freq="h")
    t = np.arange(hours, dtype="float32")[:, None, None]
    shape = (hours, len(LAT), len(LON))
    # viwve = 3 * (hour index), viwvn = 4 * (hour index) -> |IVT| = 5 * hour index (3-4-5)
    ds = xr.Dataset(
        {
            "viwve": (("time", "lat", "lon"), np.broadcast_to(3 * t, shape).astype("float32")),
            "viwvn": (("time", "lat", "lon"), np.broadcast_to(4 * t, shape).astype("float32")),
            "tp": (("time", "lat", "lon"), np.zeros(shape, dtype="float32")),
            "deg0l": (("time", "lat", "lon"), np.full(shape, 2500, dtype="float32")),
        },
        coords={"time": times, "lat": LAT, "lon": LON},
    )
    ds.to_zarr(tmp_path / f"{year}.zarr", mode="w", consolidated=False)


def make_catalog(tmp_path):
    df = pd.DataFrame(
        {
            "event_id": ["AR-2000-001", "AR-2000-002", "AR-2000-003"],
            "start": pd.to_datetime(["2000-01-01 06:00", "2000-01-02 00:00", "2001-06-01 00:00"]),
            "end": pd.to_datetime(["2000-01-01 12:00", "2000-01-02 12:00", "2001-06-01 06:00"]),
            "duration_h": [6.0, 12.0, 6.0],
            "n_steps": [1, 2, 1],
            "prob_max": [0.8, 0.9, 0.7],
            "area_frac_max": [0.5, 1.0, 0.2],
            "ivt_max": [25.0, 55.0, np.nan],
            "ivt_max_time": pd.to_datetime(["2000-01-01 11:00", "2000-01-02 11:00", pd.NaT]),
            "ivt_max_lat": [-39.5, -39.5, np.nan],
            "ivt_max_lon": [-70.5, -70.5, np.nan],
            "deg0l_max": [2500.0, 2500.0, np.nan],
            "deg0l_mean": [2500.0, 2500.0, np.nan],
            "tp_sum_mm": [0.0, 0.0, np.nan],
            "enso_phase": ["Niña", None, None],
        }
    )[catalog.COLUMNS]
    df.attrs.update(period="2000-01-01/2001-12-31")
    return catalog.write_catalog(df, tmp_path / "interim" / "events.parquet")


@pytest.fixture
def published(tmp_path):
    (tmp_path / "era5").mkdir()
    make_store(tmp_path / "era5", 2000, "2000-01-01", 72)
    events = make_catalog(tmp_path)
    out_dir, index = layer.build_layer(events, tmp_path / "era5", tmp_path / "processed")
    return out_dir, index


def test_ivt_magnitude_is_hypot():
    ds = xr.Dataset(
        {
            "viwve": (("time", "lat", "lon"), [[[3.0]]]),
            "viwvn": (("time", "lat", "lon"), [[[4.0]]]),
        },
        coords={"time": [pd.Timestamp("2000-01-01")], "lat": [0.0], "lon": [0.0]},
    )
    assert float(layer.ivt_magnitude(ds)[0, 0, 0]) == 5.0


def test_manifest_is_valid_and_lists_files(published):
    out_dir, _ = published
    m = load_manifest(out_dir / "manifest.json")
    assert (m.id, m.kind, m.title) == ("ar-events", "events", "Ríos atmosféricos")
    assert m.source == "ERA5 (Copernicus) vía ARCO-ERA5 + TECA BARD"
    assert m.license == "CC BY 4.0"
    assert m.period == "2000-01-01/2001-12-31"
    assert m.files == FILES
    for f in m.files:
        assert (out_dir / f).is_file()


def test_events_json_rows(published):
    out_dir, _ = published
    rows = json.loads((out_dir / "events.json").read_text(encoding="utf-8"))
    assert [r["event_id"] for r in rows] == ["AR-2000-001", "AR-2000-002", "AR-2000-003"]
    assert rows[0]["start"] == "2000-01-01T06:00:00Z"
    assert rows[0]["ivt_max_time"] == "2000-01-01T11:00:00Z"
    assert rows[0]["enso_phase"] == "Niña"
    assert rows[2]["ivt_max"] is None and rows[2]["ivt_max_time"] is None


def test_frames_values_and_index(published):
    out_dir, index = published
    assert index["units"] == "kg m-1 s-1"
    assert index["grid"] == {
        "ny": 3, "nx": 4, "lat_min": -40.0, "lat_max": -39.5,
        "lon_min": -71.0, "lon_max": -70.25, "origin": "south-west",
    }  # fmt: skip
    # event 1: [06:00, 12:00) -> 6 hourly frames, hour index 6..11 -> |IVT| = 30..55
    ev = index["events"]["AR-2000-001"]
    assert ev["n_frames"] == 6 and ev["start"] == "2000-01-01T06:00:00Z"
    assert (ev["vmin"], ev["vmax"]) == (30.0, 55.0)
    raw = np.fromfile(out_dir / "frames" / "AR-2000-001.bin", dtype="<f4")
    frames = raw.reshape(6, 3, 4)
    np.testing.assert_allclose(frames[:, 0, 0], [30, 35, 40, 45, 50, 55])
    assert (out_dir / "frames" / "AR-2000-001.bin").stat().st_size == 6 * 3 * 4 * 4
    assert index["events"]["AR-2000-002"]["n_frames"] == 12
    # no ERA5 store for 2001: event without frames, still in events.json
    assert "AR-2000-003" not in index["events"]
    assert (
        json.loads((out_dir / "frames" / "index.json").read_text())["events"].keys()
        == index["events"].keys()
    )


def test_footprints_are_per_cell_max_of_each_event(published):
    out_dir, index = published
    fp = index["footprints"]
    # events with frames only, in index order; shape is [n_events, ny, nx] on the frames grid
    assert fp["file"] == "frames/footprints.bin"
    assert fp["events"] == list(index["events"]) == ["AR-2000-001", "AR-2000-002"]
    assert fp["shape"] == [2, 3, 4]
    assert json.loads((out_dir / "frames" / "index.json").read_text())["footprints"] == fp
    raw = np.fromfile(out_dir / fp["file"], dtype="<f4")
    assert raw.size == 2 * 3 * 4
    foot = raw.reshape(fp["shape"])
    for i, eid in enumerate(fp["events"]):
        n = index["events"][eid]["n_frames"]
        frames = np.fromfile(out_dir / "frames" / f"{eid}.bin", dtype="<f4").reshape(n, 3, 4)
        np.testing.assert_array_equal(foot[i], frames.max(axis=0))
    # event 1 hours 6..11 -> max 55; event 2 hours 24..35 -> max 175
    assert foot[0].max() == 55.0 and foot[1].max() == 175.0


def test_footprint_ignores_nan_hours_and_keeps_all_nan_cells():
    frames = np.array([[[np.nan, np.nan], [1.0, 5.0]], [[np.nan, 3.0], [4.0, np.nan]]], dtype="<f4")
    out = layer.event_footprint(frames)
    assert out.dtype == np.dtype("<f4")
    assert np.isnan(out[0, 0]) and out[0, 1] == 3.0 and out[1, 0] == 4.0 and out[1, 1] == 5.0


def test_existing_outputs_unchanged_by_footprints(published):
    out_dir, index = published
    # frames stay as they were: same files, same index fields (footprints is only an extra key)
    assert sorted(p.name for p in (out_dir / "frames").iterdir()) == [
        "AR-2000-001.bin", "AR-2000-002.bin", "footprints.bin", "index.json",
    ]  # fmt: skip
    base = {k: v for k, v in index.items() if k != "footprints"}
    assert list(base) == ["units", "variable", "dtype", "layout", "step_hours", "grid", "events"]
    assert list(base["events"]["AR-2000-001"]) == ["start", "n_frames", "vmin", "vmax"]
    assert (out_dir / "frames" / "AR-2000-001.bin").stat().st_size == 6 * 3 * 4 * 4


def test_missing_hours_are_nan():
    ivt = xr.DataArray(
        np.ones((2, 1, 1), dtype="float32"),
        dims=("time", "lat", "lon"),
        coords={
            "time": pd.to_datetime(["2000-01-01 00:00", "2000-01-01 02:00"]),
            "lat": [0.0],
            "lon": [0.0],
        },
    )
    f = layer.event_frames(ivt, "2000-01-01 00:00", "2000-01-01 03:00")
    assert f.shape == (3, 1, 1) and np.isnan(f[1]).all() and f.dtype == np.dtype("<f4")


def test_cli_layer(tmp_path):
    (tmp_path / "era5").mkdir()
    make_store(tmp_path / "era5", 2000, "2000-01-01", 72)
    events = make_catalog(tmp_path)
    res = CliRunner().invoke(
        app,
        ["ar", "layer", "--events", str(events), "--era5-dir", str(tmp_path / "era5"),
         "--out", str(tmp_path / "proc")],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    assert "2 events with frames, 18 hourly frames" in res.output
    assert (tmp_path / "proc" / "ar-events" / "manifest.json").is_file()


def test_enso_report_is_copied_and_listed(tmp_path):
    (tmp_path / "era5").mkdir()
    make_store(tmp_path / "era5", 2000, "2000-01-01", 72)
    events = make_catalog(tmp_path)
    report = tmp_path / "F1.8.json"
    report.write_text('{"meta": {}, "results": {"rows": []}}', encoding="utf-8")
    out_dir, _ = layer.build_layer(events, tmp_path / "era5", tmp_path / "processed", report)
    m = load_manifest(out_dir / "manifest.json")
    assert m.files == [*FILES, "enso.json"]
    assert (out_dir / "enso.json").read_text(encoding="utf-8") == report.read_text(encoding="utf-8")


def test_layer_without_enso_report_has_no_enso_file(published):
    out_dir, _ = published
    assert not (out_dir / "enso.json").exists()
    assert "enso.json" not in load_manifest(out_dir / "manifest.json").files


def test_cli_layer_enso_report_option(tmp_path):
    (tmp_path / "era5").mkdir()
    make_store(tmp_path / "era5", 2000, "2000-01-01", 72)
    events = make_catalog(tmp_path)
    report = tmp_path / "F1.8.json"
    report.write_text("{}", encoding="utf-8")
    base = ["ar", "layer", "--events", str(events), "--era5-dir", str(tmp_path / "era5")]
    res = CliRunner().invoke(
        app, [*base, "--out", str(tmp_path / "a"), "--enso-report", str(report)]
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "a" / "ar-events" / "enso.json").is_file()
    # a missing report is skipped, not an error
    res = CliRunner().invoke(
        app, [*base, "--out", str(tmp_path / "b"), "--enso-report", str(tmp_path / "nope.json")]
    )
    assert res.exit_code == 0, res.output
    assert not (tmp_path / "b" / "ar-events" / "enso.json").exists()


def test_extremes_report_is_copied_and_listed(tmp_path):
    (tmp_path / "era5").mkdir()
    make_store(tmp_path / "era5", 2000, "2000-01-01", 72)
    events = make_catalog(tmp_path)
    report = tmp_path / "F1.9.json"
    report.write_text('{"meta": {}, "variants": {}, "robust": {}}', encoding="utf-8")
    out_dir, _ = layer.build_layer(
        events, tmp_path / "era5", tmp_path / "processed", extremes_report=report
    )
    m = load_manifest(out_dir / "manifest.json")
    assert m.files == [*FILES, "enso-extremes.json"]
    assert (out_dir / "enso-extremes.json").read_text(encoding="utf-8") == report.read_text(
        encoding="utf-8"
    )


def test_layer_without_extremes_report_has_no_extremes_file(published):
    out_dir, _ = published
    assert not (out_dir / "enso-extremes.json").exists()
    assert "enso-extremes.json" not in load_manifest(out_dir / "manifest.json").files


def test_cli_layer_extremes_report_option(tmp_path):
    (tmp_path / "era5").mkdir()
    make_store(tmp_path / "era5", 2000, "2000-01-01", 72)
    events = make_catalog(tmp_path)
    report = tmp_path / "F1.9.json"
    report.write_text("{}", encoding="utf-8")
    base = ["ar", "layer", "--events", str(events), "--era5-dir", str(tmp_path / "era5")]
    res = CliRunner().invoke(
        app, [*base, "--out", str(tmp_path / "a"), "--extremes-report", str(report)]
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "a" / "ar-events" / "enso-extremes.json").is_file()
    res = CliRunner().invoke(
        app, [*base, "--out", str(tmp_path / "b"), "--extremes-report", str(tmp_path / "nope.json")]
    )
    assert res.exit_code == 0, res.output
    assert not (tmp_path / "b" / "ar-events" / "enso-extremes.json").exists()


def test_rebuild_keeps_existing_responses_file(tmp_path):
    (tmp_path / "era5").mkdir()
    make_store(tmp_path / "era5", 2000, "2000-01-01", 72)
    events = make_catalog(tmp_path)
    out_dir, _ = layer.build_layer(events, tmp_path / "era5", tmp_path / "processed")
    assert "responses.json" not in load_manifest(out_dir / "manifest.json").files
    (out_dir / "responses.json").write_text("{}", encoding="utf-8")
    out_dir, _ = layer.build_layer(events, tmp_path / "era5", tmp_path / "processed")
    assert load_manifest(out_dir / "manifest.json").files == [*FILES, "responses.json"]
