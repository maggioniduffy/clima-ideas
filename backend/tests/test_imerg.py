from concurrent.futures import Future
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn import cli
from clima_nqn.io import imerg


def write_granule(path: Path, stamp: pd.Timestamp, value: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = xr.Dataset(
        {"precipitation": (("time", "lon", "lat"), np.full((1, 30, 25), value))},
        coords={
            "time": [stamp],
            "lon": np.arange(-69.95, -66.95, 0.1),
            "lat": np.arange(-39.95, -37.45, 0.1),
        },
    )
    ds.precipitation.attrs["units"] = "mm/hr"
    # like Harmony output: variable in group "Grid", time encoded with IMERG's julian calendar
    ds.time.encoding.update(units="seconds since 1970-01-01 00:00:00", calendar="julian")
    ds.to_netcdf(path, engine="netcdf4", group="Grid")
    return path


@pytest.fixture
def one_day(monkeypatch):
    original = imerg.expected_times

    def short(year, month):
        return original(year, month)[:48]

    monkeypatch.setattr(imerg, "expected_times", short)
    return short


def test_merge_transposes_sorts_axes_and_uses_float32(tmp_path):
    times = [pd.Timestamp("2014-04-01T00:30"), pd.Timestamp("2014-04-01T00:00")]
    paths = [write_granule(tmp_path / f"{i}.nc4", t, i) for i, t in enumerate(times)]
    ds = imerg.merge_granules(paths)
    assert ds.precipitation.dims == ("time", "lat", "lon")
    assert ds.precipitation.dtype == np.float32
    assert ds.lat.values[0] < ds.lat.values[-1]
    assert ds.lon.values[0] < ds.lon.values[-1]
    assert pd.DatetimeIndex(ds.time.values).is_monotonic_increasing


def test_check_complete_names_missing_and_duplicate_times():
    stamps = imerg.expected_times(2014, 4)[:3]
    ds = xr.Dataset({"precipitation": ("time", [1.0, 2.0])}, coords={"time": stamps[:2]})
    with pytest.raises(ValueError, match="2014-04-01 01:00:00"):
        imerg.check_complete(ds, 2014, 4)
    dup = xr.concat([ds.isel(time=[0]), ds.isel(time=[0])], dim="time")
    with pytest.raises(ValueError, match="duplicate"):
        imerg.check_complete(dup, 2014, 4)


class FakeClient:
    def __init__(self, raw_dir):
        self.raw_dir = raw_dir
        self.states = iter(["running", "paused", "successful"])
        self.resumes = 0
        self.calls = 0

    def submit(self, request):
        self.calls += 1
        return "job"

    def status(self, job):
        return {"status": next(self.states), "message": ""}

    def resume(self, job):
        self.resumes += 1

    def download_all(self, job, directory):
        def futures():
            for i, stamp in enumerate(imerg.expected_times(2014, 4)):
                future = Future()
                future.set_result(write_granule(Path(directory) / f"{i}.nc4", stamp))
                yield future

        return futures()


def test_fetch_month_resumes_downloads_and_skips_complete(tmp_path, monkeypatch, one_day):
    client = FakeClient(tmp_path / "raw")
    monkeypatch.setattr(imerg, "time", type("T", (), {"sleep": staticmethod(lambda _: None)}))
    result = imerg.fetch_month(2014, 4, tmp_path / "out", client=client)
    assert result == tmp_path / "out/2014-04.zarr"
    assert client.resumes == 1
    assert not list((tmp_path / "out").glob("*.tmp"))
    assert not (tmp_path / "out/2014-04-raw").exists()
    imerg.fetch_month(2014, 4, tmp_path / "out", client=client)
    assert client.calls == 1


def test_fetch_month_failed_job_raises(tmp_path, monkeypatch):
    class Failed(FakeClient):
        def __init__(self):
            self.calls = 0

        def status(self, job):
            return {"status": "failed", "message": "boom"}

    with pytest.raises(RuntimeError, match="failed"):
        imerg.fetch_month(2014, 4, tmp_path, client=Failed())


def test_combine_records_provenance_period_and_missing_months(tmp_path, monkeypatch):
    original = imerg.expected_times
    monkeypatch.setattr(imerg, "expected_times", lambda y, m: original(y, m)[:1])
    for month in (1, 3):
        ds = xr.Dataset(
            {"precipitation": (("time", "lat", "lon"), np.ones((1, 2, 2), dtype="f4"))},
            coords={"time": original(2020, month)[:1], "lat": [-39, -38], "lon": [-69, -68]},
        )
        ds.to_zarr(tmp_path / f"2020-{month:02d}.zarr", mode="w")
    path = imerg.combine(tmp_path, tmp_path / "all.zarr")
    result = xr.open_zarr(path)
    assert result.attrs["source"] == imerg.SOURCE
    assert result.attrs["license"] == imerg.LICENSE
    assert result.attrs["period"] == "2020-01-01T00:00:00/2020-03-01T00:00:00"
    assert result.precipitation.attrs["units"] == "mm/h"
    assert result.attrs["missing_months"]
    assert pd.DatetimeIndex(result.time.values).is_monotonic_increasing


def test_cli_fetch_and_combine(tmp_path, monkeypatch, one_day):
    monkeypatch.setattr(
        imerg, "fetch_month", lambda y, m, out, **kw: Path(out) / f"{y}-{m:02d}.zarr"
    )
    monkeypatch.setattr(imerg, "combine", lambda src, out: Path(out))
    runner = CliRunner()
    fetched = runner.invoke(
        cli.app, ["imerg", "fetch", "--year", "2014", "--months", "4", "--out", str(tmp_path)]
    )
    combined = runner.invoke(
        cli.app,
        ["imerg", "combine", "--src", str(tmp_path), "--out", str(tmp_path / "combined.zarr")],
    )
    assert fetched.exit_code == 0, fetched.output
    assert combined.exit_code == 0, combined.output


def test_build_request_uses_box_variable_and_skip_preview():
    from datetime import datetime

    req = imerg.build_request(datetime(2014, 4, 1), datetime(2014, 4, 30, 23, 59, 59))
    assert req.collection.id == imerg.COLLECTION_ID
    assert req.variables == [imerg.VARIABLE]
    assert req.skip_preview is True
    assert (req.spatial.w, req.spatial.s, req.spatial.e, req.spatial.n) == imerg.BBOX
    assert req.is_valid()
