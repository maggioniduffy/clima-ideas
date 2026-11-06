"""Tests for the ERA5 IVT fetch script: ARCO subset, retries, backoff and raw-file cleanup (no network)."""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fetch_era5_ivt as fetch


@pytest.fixture
def sleeps(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


@pytest.fixture
def cds(monkeypatch):
    """Inject a fake cdsapi whose retrieve() always fails after leaving a partial file."""
    state = types.SimpleNamespace(requests=[])

    class Client:
        def retrieve(self, dataset, request, target):
            state.requests.append(target)
            Path(target).write_bytes(b"partial")
            raise RuntimeError("CDS hiccup")

    monkeypatch.setitem(sys.modules, "cdsapi", types.SimpleNamespace(Client=Client))
    return state


def test_backoff_sleeps_between_attempts_but_not_after_the_last(cds, sleeps, tmp_path):
    raw = tmp_path / "raw_2023-01.nc"
    with pytest.raises(RuntimeError):
        fetch._download_month(2023, 1, ["00"], raw, retries=3, retry_wait=60)
    assert len(cds.requests) == 3
    assert sleeps == [60, 120]


def test_stale_raw_files_are_deleted_at_start(cds, sleeps, tmp_path):
    (tmp_path / "ivt_2023-01.nc").write_bytes(b"done")
    (tmp_path / "raw_2023-02.nc").write_bytes(b"stale")
    unz = tmp_path / "raw_2023-03_unz"
    unz.mkdir()
    (unz / "x.nc").write_bytes(b"stale")

    assert fetch.main(["--year", "2023", "--months", "1", "--out", str(tmp_path), "--source", "cds"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ivt_2023-01.nc"]


def test_failed_month_leaves_no_raw_file_and_returns_1(cds, sleeps, tmp_path):
    argv = ["--year", "2023", "--months", "1", "--out", str(tmp_path), "--source", "cds", "--retries", "2", "--retry-wait", "5"]
    assert fetch.main(argv) == 1
    assert len(cds.requests) == 2
    assert sleeps == [5]
    assert list(tmp_path.glob("raw_*")) == []


def test_existing_targets_are_skipped(cds, sleeps, tmp_path):
    (tmp_path / "ivt_2023-01.nc").write_bytes(b"done")
    assert fetch.main(["--year", "2023", "--months", "1", "--out", str(tmp_path), "--source", "cds"]) == 0
    assert cds.requests == []
    assert (tmp_path / "ivt_2023-01.nc").read_bytes() == b"done"


def test_parse_months():
    assert fetch._parse_months("1,2,5-7") == [1, 2, 5, 6, 7]
    with pytest.raises(ValueError):
        fetch._parse_months("13")


QUEUE_FULL = (
    "400 Client Error: Bad Request for url: https://cds.climate.copernicus.eu/api/retrieve/v1/jobs/x/results\n"
    "The job has been rejected\nMaximum number queued requests for this dataset has been reached. "
    "Please configure your scripts to request data sequentially"
)


def _fake_cds(monkeypatch, outcomes):
    """Fake cdsapi whose retrieve() raises/returns the next entry of ``outcomes`` (None = success)."""
    calls: list[str] = []

    class Client:
        def retrieve(self, dataset, request, target):
            calls.append(target)
            Path(target).write_bytes(b"partial")
            outcome = outcomes(len(calls)) if callable(outcomes) else outcomes[len(calls) - 1]
            if outcome is not None:
                raise RuntimeError(outcome)

    monkeypatch.setitem(sys.modules, "cdsapi", types.SimpleNamespace(Client=Client))
    return calls


def test_full_queue_waits_without_spending_retries(monkeypatch, sleeps, tmp_path):
    calls = _fake_cds(monkeypatch, [QUEUE_FULL, QUEUE_FULL, None])
    raw = tmp_path / "raw_2023-01.nc"
    got = fetch._download_month(2023, 1, ["00"], raw, retries=1, retry_wait=60, queue_wait=300, queue_timeout=3600)
    assert got == raw
    assert len(calls) == 3
    assert sleeps == [300, 300]


def test_full_queue_gives_up_after_queue_timeout(monkeypatch, sleeps, tmp_path):
    calls = _fake_cds(monkeypatch, lambda n: QUEUE_FULL)
    argv = [
        "--year", "2023", "--months", "1", "--out", str(tmp_path), "--source", "cds",
        "--queue-wait", "10", "--queue-timeout", "20",
    ]
    assert fetch.main(argv) == 1
    assert sleeps == [10, 10]
    assert len(calls) == 3
    assert list(tmp_path.glob("raw_*")) == []


def test_downloads_are_sequential_by_default(monkeypatch, tmp_path):
    import threading

    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    class Client:
        def retrieve(self, dataset, request, target):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            threading.Event().wait(0.05)
            with lock:
                state["now"] -= 1
            raise RuntimeError("CDS hiccup")

    monkeypatch.setitem(sys.modules, "cdsapi", types.SimpleNamespace(Client=Client))
    argv = ["--year", "2023", "--months", "1-3", "--out", str(tmp_path), "--source", "cds", "--retries", "1"]
    assert fetch.main(argv) == 1
    assert state["peak"] == 1


def _fake_arco(monkeypatch):
    """Patch the store opener with a synthetic ARCO-like dataset: 0-360 lon, descending lat, hourly time."""
    import numpy as np
    import xarray as xr

    time_ = np.arange("2023-01-01T00", "2023-02-01T00", dtype="datetime64[h]").astype("datetime64[ns]")
    lat = np.arange(90, -90.1, -5.0)
    lon = np.arange(0, 360, 5.0)
    shape = (time_.size, lat.size, lon.size)
    u = np.full(shape, 3.0, dtype=np.float32)
    v = np.full(shape, 4.0, dtype=np.float32)
    ds = xr.Dataset(
        {
            "vertical_integral_of_eastward_water_vapour_flux": (("time", "latitude", "longitude"), u),
            "vertical_integral_of_northward_water_vapour_flux": (("time", "latitude", "longitude"), v),
        },
        coords={"time": time_, "latitude": lat, "longitude": lon},
    )
    state = types.SimpleNamespace(opened=0)

    def opener():
        state.opened += 1
        return ds

    monkeypatch.setattr(fetch, "_open_arco", opener)
    return state


def test_arco_writes_only_requested_hours_over_area_with_negative_lons(monkeypatch, tmp_path):
    import numpy as np
    import xarray as xr

    state = _fake_arco(monkeypatch)
    argv = ["--year", "2023", "--months", "1", "--hours", "00,12", "--out", str(tmp_path), "--source", "arco"]
    assert fetch.main(argv) == 0
    assert state.opened >= 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ivt_2023-01.nc"]
    with xr.open_dataset(tmp_path / "ivt_2023-01.nc") as out:
        assert out.sizes["time"] == 31 * 2
        assert sorted(set(out["time"].dt.hour.values.tolist())) == [0, 12]
        assert out["lat"].values.min() >= -60 and out["lat"].values.max() <= -15
        assert np.all(np.diff(out["lat"].values) > 0)
        assert out["lon"].values.min() >= -95 and out["lon"].values.max() <= -40
        assert np.all(np.diff(out["lon"].values) > 0)
        assert np.allclose(out["IVT"].values, 5.0)  # hypot(3, 4)
        assert "ARCO-ERA5" in out.attrs["source"]
        assert "CC-BY 4.0" in out.attrs["source"]


def test_arco_retries_transient_errors_with_linear_backoff(monkeypatch, sleeps, tmp_path):
    calls = []

    def opener():
        calls.append(1)
        raise OSError("GCS hiccup")

    monkeypatch.setattr(fetch, "_open_arco", opener)
    argv = ["--year", "2023", "--months", "1", "--out", str(tmp_path), "--retries", "3", "--retry-wait", "7"]
    assert fetch.main(argv) == 1
    assert len(calls) == 3
    assert sleeps == [7, 14]
    assert list(tmp_path.iterdir()) == []


def test_arco_skips_existing_targets(monkeypatch, tmp_path):
    state = _fake_arco(monkeypatch)
    (tmp_path / "ivt_2023-01.nc").write_bytes(b"done")
    assert fetch.main(["--year", "2023", "--months", "1", "--out", str(tmp_path)]) == 0
    assert state.opened == 0
    assert (tmp_path / "ivt_2023-01.nc").read_bytes() == b"done"


def test_cds_output_keeps_cds_source_attr(monkeypatch, tmp_path):
    import numpy as np
    import xarray as xr

    def retrieve_to(target):
        t = np.array(["2023-01-01T00"], dtype="datetime64[ns]")
        ds = xr.Dataset(
            {"viwve": (("valid_time", "latitude", "longitude"), np.full((1, 2, 2), 3.0, dtype=np.float32)),
             "viwvn": (("valid_time", "latitude", "longitude"), np.full((1, 2, 2), 4.0, dtype=np.float32))},
            coords={"valid_time": t, "latitude": [-20.0, -25.0], "longitude": [-70.0, -69.75]},
        )
        ds.to_netcdf(target)

    class Client:
        def retrieve(self, dataset, request, target):
            retrieve_to(target)

    monkeypatch.setitem(sys.modules, "cdsapi", types.SimpleNamespace(Client=Client))
    argv = ["--year", "2023", "--months", "1", "--out", str(tmp_path), "--source", "cds"]
    assert fetch.main(argv) == 0
    with xr.open_dataset(tmp_path / "ivt_2023-01.nc") as out:
        assert "ARCO" not in out.attrs["source"]
        assert "Copernicus" in out.attrs["source"]
        assert np.allclose(out["IVT"].values, 5.0)
