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


def test_merge_reads_granules_under_the_hdf5_lock(tmp_path, monkeypatch):
    # --parallel merges several months at once; HDF5 reads must take turns (SIGBUS in the 2008 Actions run)
    path = write_granule(tmp_path / "g.nc4", pd.Timestamp("2014-04-01T00:00"))
    original = xr.open_dataset
    held = []

    def spy(*args, **kwargs):
        held.append(imerg._HDF5_LOCK.locked())
        return original(*args, **kwargs)

    monkeypatch.setattr(imerg.xr, "open_dataset", spy)
    imerg.merge_granules([path])
    assert held == [True]
    assert not imerg._HDF5_LOCK.locked()


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
        if not hasattr(request, "collection"):  # job lookup by label: nothing to reuse
            return {"jobs": []}
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


def test_cli_fetch_runs_months_in_parallel_and_reports_failures(tmp_path, monkeypatch):
    import threading

    lock, active, peak, seen = threading.Lock(), [0], [0], []
    barrier = threading.Barrier(3, timeout=5)

    def fake(y, m, out, **kw):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            seen.append((y, m))
        if m <= 3:
            barrier.wait()  # only passes if three months run at the same time
        with lock:
            active[0] -= 1
        if m == 5:
            raise RuntimeError("boom")
        return Path(out) / f"{y}-{m:02d}.zarr"

    monkeypatch.setattr(imerg, "fetch_month", fake)
    result = CliRunner().invoke(
        cli.app,
        [
            "imerg",
            "fetch",
            "--year",
            "2014",
            "--months",
            "1-6",
            "--parallel",
            "3",
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert sorted(seen) == [(2014, m) for m in range(1, 7)]
    assert peak[0] >= 3
    assert "2014-05 failed: boom" in result.output


class CancelClient(FakeClient):
    def __init__(self, states, fail_download=False):
        super().__init__(None)
        self.states = iter(states)
        self.cancelled = []
        self.fail_download = fail_download

    def cancel(self, job):
        self.cancelled.append(job)

    def download_all(self, job, directory):
        if self.fail_download:
            raise OSError("download broke")
        return super().download_all(job, directory)


def test_fetch_month_deadline_leaves_job_running_and_raises(tmp_path):
    client = CancelClient(["running"] * 5)
    deadline = imerg.time.monotonic() - 1
    with pytest.raises(TimeoutError, match="job still running, left for the next run"):
        imerg.fetch_month(2014, 4, tmp_path, client=client, deadline=deadline)
    assert client.cancelled == []


def test_find_job_picks_newest_active_or_successful_and_tolerates_errors():
    class Jobs:
        def __init__(self, data):
            self.data, self.requests = data, []

        def submit(self, request):
            self.requests.append(request)
            if isinstance(self.data, Exception):
                raise self.data
            return self.data

    jobs = [
        {"jobID": "old", "status": "running", "createdAt": "2026-11-16T10:00:00Z"},
        {"jobID": "failed", "status": "failed", "createdAt": "2026-11-17T10:00:00Z"},
        {"jobID": "new", "status": "successful", "createdAt": "2026-11-17T09:00:00Z"},
    ]
    client = Jobs({"jobs": jobs})
    assert imerg.find_job(client, "lbl") == "new"
    assert client.requests[0].labels == ["lbl"]
    assert imerg.find_job(Jobs({"jobs": [jobs[1]]}), "lbl") is None
    assert imerg.find_job(Jobs("job"), "lbl") is None
    assert imerg.find_job(Jobs(RuntimeError("down")), "lbl") is None


def test_fetch_month_reuses_job_found_by_month_label(tmp_path, one_day):
    class Reuse(CancelClient):
        def submit(self, request):
            if hasattr(request, "collection"):
                raise AssertionError("must not submit a new request")
            assert request.labels == [imerg.month_label(2014, 4)]
            return {
                "jobs": [{"jobID": "old", "status": "running", "createdAt": "2026-11-17T00:00:00Z"}]
            }

    client = Reuse(["running", "successful"])
    assert imerg.fetch_month(2014, 4, tmp_path, client=client, log_every=0)
    assert client.cancelled == []

    class Done(Reuse):
        def submit(self, request):
            data = super().submit(request)
            data["jobs"][0]["status"] = "successful"
            return data

    # a successful job from an earlier run is also reused
    shutil_target = tmp_path / "2014-04.zarr"
    import shutil

    shutil.rmtree(shutil_target)
    assert imerg.fetch_month(2014, 4, tmp_path, client=Done(["successful"]), log_every=0)


def test_fetch_month_download_error_cancels_job_unless_successful(tmp_path):
    client = CancelClient(["running", "successful"], fail_download=True)
    # the job finished, so there is nothing to cancel on a download error
    with pytest.raises(OSError, match="download broke"):
        imerg.fetch_month(2014, 4, tmp_path, client=client, log_every=0)
    assert client.cancelled == []

    # an error while still polling (e.g. Ctrl-C) cancels the orphan job
    class Boom(CancelClient):
        def status(self, job):
            raise KeyboardInterrupt

    boom = Boom([])
    with pytest.raises(KeyboardInterrupt):
        imerg.fetch_month(2014, 4, tmp_path, client=boom)
    assert boom.cancelled == ["job"]


def test_fetch_month_success_does_not_cancel_and_logs_progress(tmp_path, one_day, capsys):
    client = CancelClient(["running", "successful"])
    imerg.fetch_month(2014, 4, tmp_path, client=client, log_every=0)
    assert client.cancelled == []
    out = capsys.readouterr().out
    assert "2014-04: harmony job job submitted" in out
    assert "2014-04: harmony job job running" in out
    assert "downloaded 48 granules" in out


def test_cancel_running_pages_and_cancels_only_active_jobs():
    pages = {
        1: [{"jobID": f"a{i}", "status": "running"} for i in range(100)],
        2: [
            {"jobID": "p", "status": "paused"},
            {"jobID": "ok", "status": "successful"},
            {"jobID": "bad", "status": "failed"},
            {"jobID": "acc", "status": "accepted"},
        ],
    }

    class Jobs:
        def __init__(self):
            self.requests, self.cancelled = [], []

        def submit(self, request):
            self.requests.append(request)
            return {"jobs": pages[request.page]}

        def cancel(self, job):
            if job == "a3":
                raise RuntimeError("already gone")
            self.cancelled.append(job)

    client = Jobs()
    result = imerg.cancel_running(client, "lbl")
    assert [r.page for r in client.requests] == [1, 2]
    assert all(r.labels == ["lbl"] for r in client.requests)
    assert result == client.cancelled
    assert len(result) == 101 and "a3" not in result
    assert {"p", "acc"} <= set(result) and not {"ok", "bad"} & set(result)


def test_build_request_carries_label():
    from datetime import datetime

    start, stop = datetime(2014, 4, 1), datetime(2014, 4, 30, 23, 59, 59)
    assert imerg.build_request(start, stop).labels == [imerg.HARMONY_LABEL]
    tag = imerg.month_label(2014, 4)
    assert tag == "clima-nqn-imerg-2014-04"
    assert imerg.build_request(start, stop, tag).labels == [imerg.HARMONY_LABEL, tag]


def test_cancel_running_keep_skips_kept_months_and_cancels_older_duplicates():
    base = imerg.HARMONY_LABEL
    jobs = [
        {
            "jobID": "k-old",
            "status": "running",
            "labels": [base, f"{base}-2014-04"],
            "createdAt": "2026-11-16",
        },
        {
            "jobID": "k-new",
            "status": "running",
            "labels": [base, f"{base}-2014-04"],
            "createdAt": "2026-11-17",
        },
        {
            "jobID": "other",
            "status": "running",
            "labels": [base, f"{base}-2014-05"],
            "createdAt": "2026-11-17",
        },
        {"jobID": "legacy", "status": "accepted", "labels": [base]},
        {"jobID": "done", "status": "successful", "labels": [base, f"{base}-2014-04"]},
    ]

    class Jobs:
        def __init__(self):
            self.cancelled = []

        def submit(self, request):
            return {"jobs": jobs}

        def cancel(self, job):
            self.cancelled.append(job)

    client = Jobs()
    result = imerg.cancel_running(client, base, keep=[f"{base}-2014-04"])
    assert sorted(result) == ["k-old", "legacy", "other"]


def test_cli_fetch_deadline_skips_unstarted_months(tmp_path, monkeypatch):
    calls = []

    def fake(y, m, out, **kw):
        calls.append((m, kw["deadline"]))
        return Path(out) / f"{y}-{m:02d}.zarr"

    monkeypatch.setattr(imerg, "fetch_month", fake)
    base = ["imerg", "fetch", "--year", "2014", "--months", "1-2", "--parallel", "1"]
    base += ["--out", str(tmp_path)]
    expired = CliRunner().invoke(cli.app, [*base, "--deadline-min", "-1"])
    assert expired.exit_code == 1
    assert calls == []
    assert "2014-01 failed" in expired.output and "months failed" in expired.output
    ok = CliRunner().invoke(cli.app, [*base, "--deadline-min", "30"])
    assert ok.exit_code == 0, ok.output
    assert [m for m, _ in calls] == [1, 2] and all(d is not None for _, d in calls)
