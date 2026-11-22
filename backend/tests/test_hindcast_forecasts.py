"""F5.1: hindcast forecast ingest, all offline (fake fetchers and mock HTTP transport)."""

import json

import httpx
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.stages.hindcast import cases as cases_mod
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import store

# first lines of a real GEFSv12 reforecast .idx (2005-01-01 00 UTC, c00; checked 2026-11-22)
IDX = """\
1:0:d=2005010100:APCP:surface:0-3 hour acc fcst:ENS=low-res ctl
2:465975:d=2005010100:APCP:surface:0-6 hour acc fcst:ENS=low-res ctl
3:1022780:d=2005010100:APCP:surface:6-9 hour acc fcst:ENS=low-res ctl
4:1457115:d=2005010100:APCP:surface:6-12 hour acc fcst:ENS=low-res ctl
5:1737852:d=2005010100:APCP:surface:12-15 hour acc fcst:ENS=low-res ctl
6:1980698:d=2005010100:APCP:surface:12-18 hour acc fcst:ENS=low-res ctl
7:2272913:d=2005010100:APCP:surface:18-21 hour acc fcst:ENS=low-res ctl
8:2722351:d=2005010100:APCP:surface:18-24 hour acc fcst:ENS=low-res ctl
9:3014158:d=2005010100:APCP:surface:24-27 hour acc fcst:ENS=low-res ctl
10:3261087:d=2005010100:APCP:surface:24-30 hour acc fcst:ENS=low-res ctl
11:3552399:d=2005010100:APCP:surface:30-33 hour acc fcst:ENS=low-res ctl
12:3797826:d=2005010100:APCP:surface:30-36 hour acc fcst:ENS=low-res ctl
13:4088697:d=2005010100:APCP:surface:36-39 hour acc fcst:ENS=low-res ctl
14:4547806:d=2005010100:APCP:surface:36-42 hour acc fcst:ENS=low-res ctl
15:4844690:d=2005010100:APCP:surface:42-45 hour acc fcst:ENS=low-res ctl
16:5301316:d=2005010100:APCP:surface:42-48 hour acc fcst:ENS=low-res ctl
17:5592764:d=2005010100:APCP:surface:48-51 hour acc fcst:ENS=low-res ctl
18:6043151:d=2005010100:APCP:surface:48-54 hour acc fcst:ENS=low-res ctl
"""


def make_events(n_per_year: int = 6, years=range(2000, 2026), seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for y in years:
        for k in range(n_per_year):
            day = pd.Timestamp(f"{y}-01-02") + pd.Timedelta(days=int(rng.integers(0, 360)))
            start = day + pd.Timedelta(hours=int(rng.integers(0, 4)) * 6)
            rows.append(
                {
                    "event_id": f"AR-{y}-{k + 1:03d}",
                    "start": start,
                    "end": start + pd.Timedelta(hours=18),
                    "ivt_max": 500.0 + 10 * k,
                    "ivt_max_time": start + pd.Timedelta(hours=7),
                }
            )
    return pd.DataFrame(rows)


# --- cases ---------------------------------------------------------------------------------------


def test_control_rule():
    ev = make_events()
    cases = cases_mod.build_cases(ev, seed=7)
    events = cases[cases["kind"] == "event"]
    ctl = cases[cases["kind"] == "control"]
    assert len(events) == len(ev)
    assert list(events["valid_date"]) == sorted(events["valid_date"])
    banned = cases_mod.forbidden_days(ev)
    assert not set(ctl["valid_date"]) & banned  # no AR event within +-3 days
    assert ctl["valid_date"].is_unique
    assert not set(ctl["valid_date"]) & set(events["valid_date"])
    assert ctl["event_id"].isna().all() and events["event_id"].notna().all()
    assert cases["case_id"].is_unique
    # one control per event case of each pool, in the same calendar month, inside the pool period
    for pool in cases_mod.POOLS:
        e, c = (
            d[(d["valid_date"] >= pool.first) & (d["valid_date"] <= pool.last)]
            for d in (events, ctl)
        )
        assert len(e) == len(c)
        assert sorted(e["valid_date"].dt.month) == sorted(c["valid_date"].dt.month)
    assert (
        ctl["valid_date"].dt.year.between(2000, 2019)
        | ctl["valid_date"].dt.year.between(2023, 2025)
    ).all()
    assert (ctl["valid_date"] >= "2000-01-02").all()
    assert cases["month"].eq(cases["valid_date"].dt.month).all()


def test_forbidden_days_widens_by_three_days():
    ev = pd.DataFrame(
        {"start": [pd.Timestamp("2010-05-10 06:00")], "end": [pd.Timestamp("2010-05-11 00:00")]}
    )
    days = cases_mod.forbidden_days(ev)
    assert pd.Timestamp("2010-05-07") in days  # 05-10 06:00 - 3 d = 05-07 06:00 touches day 05-07
    assert pd.Timestamp("2010-05-06") not in days
    assert pd.Timestamp("2010-05-13") in days  # end 05-11 00:00 + 3 d = 05-14 00:00 exclusive
    assert pd.Timestamp("2010-05-14") not in days


def test_cases_seeded_and_counts(tmp_path):
    ev = make_events()
    a, b = cases_mod.build_cases(ev, seed=3), cases_mod.build_cases(ev, seed=3)
    pd.testing.assert_frame_equal(a, b)
    assert not a["valid_date"].equals(cases_mod.build_cases(ev, seed=4)["valid_date"])
    out = tmp_path / "cases.parquet"
    counts = cases_mod.write_cases(a, out, seed=3, source="x")
    meta = pq.read_schema(out).metadata
    assert json.loads(meta[b"counts"]) == counts
    assert meta[b"seed"] == b"3" and b"+-3 days" in meta[b"rule"]
    assert counts["events"] == len(ev) and counts["controls"] == int((a["kind"] == "control").sum())
    assert list(pd.read_parquet(out).columns) == cases_mod.COLUMNS


# --- lead / init / bucket arithmetic -------------------------------------------------------------


def test_init_and_lead_convention():
    assert fc.init_date("2010-03-15", 1) == pd.Timestamp("2010-03-15")
    assert fc.init_date("2010-03-15", 5) == pd.Timestamp("2010-03-11")
    # valid_date = init + lead - 1, same as ops/ingest
    for lead in fc.LEADS:
        assert fc.init_date("2010-03-15", lead) + pd.Timedelta(days=lead - 1) == pd.Timestamp(
            "2010-03-15"
        )


def test_gefs_buckets_against_idx():
    assert fc.gefs_bucket_steps(1) == [(0, 6), (6, 12), (12, 18), (18, 24)]
    assert fc.gefs_bucket_steps(2) == [(24, 30), (30, 36), (36, 42), (42, 48)]
    msgs = fc.parse_apcp_idx(IDX)
    assert len(msgs) == 18 and msgs[1] == fc.IdxMessage(465975, 1022779, 0, 6)
    got = fc.gefs_lead_ranges(msgs, 1)
    assert [(m.start_h, m.end_h) for m in got] == fc.gefs_bucket_steps(1)
    assert [m.start for m in got] == [465975, 1457115, 1980698, 2722351]
    assert [m.end for m in got] == [1022779, 1737851, 2272912, 3014157]  # next line offset - 1
    lead2 = fc.gefs_lead_ranges(msgs, 2)
    assert [m.start for m in lead2] == [3261087, 3797826, 4547806, 5301316]
    assert lead2[-1].end == 5592763
    with pytest.raises(ValueError, match="no 6 h buckets"):
        fc.gefs_lead_ranges(msgs, 3)  # the fixture stops at 54 h
    assert fc.parse_apcp_idx(IDX)[-1].end is None  # last line: read to EOF


def test_gefs_url():
    assert fc.gefs_url(pd.Timestamp("2005-01-01"), "p04").endswith(
        "/GEFSv12/reforecast/2005/2005010100/p04/Days:1-10/apcp_sfc_2005010100_p04.grib2"
    )


def test_ecmwf_steps_dirs_and_daily():
    assert fc.ecmwf_steps(1) == (0, 24) and fc.ecmwf_steps(10) == (216, 240)
    prev, nxt = np.full((2, 2), 5.0), np.array([[6.0, 4.9], [5.0, 9.0]])
    np.testing.assert_allclose(fc.ecmwf_daily(prev, nxt), [[1.0, 0.0], [0.0, 4.0]])  # clipped at 0
    np.testing.assert_allclose(fc.ecmwf_daily(None, nxt), nxt)
    assert fc.ecmwf_dirs("ifs", "2023-02-01")[0] == "0p4-beta/oper"
    assert fc.ecmwf_dirs("ifs", "2024-06-01") == ["ifs/0p25/oper"]
    assert fc.ecmwf_dirs("aifs", "2024-06-01")[0] == "aifs/0p25/oper"
    assert fc.ecmwf_dirs("aifs", "2025-06-01")[0] == "aifs-single/0p25/oper"
    url = fc.ecmwf_file(pd.Timestamp("2025-06-01"), "ifs/0p25/oper", 48)
    assert url.endswith("/20250601/00z/ifs/0p25/oper/20250601000000-48h-oper-fc")
    index = (
        '{"param": "gh", "levtype": "pl", "step": "48", "_offset": 0, "_length": 10}\n'
        '{"param": "tp", "levtype": "sfc", "step": "24", "_offset": 10, "_length": 7}\n'
        '{"param": "tp", "levtype": "sfc", "step": "48", "_offset": 17, "_length": 9}\n'
    )
    assert fc.tp_range(index, 48) == (17, 9) and fc.tp_range(index, 72) is None


def test_model_periods_and_eligibility():
    cases = cases_mod.build_cases(make_events(), seed=1)
    g = fc.eligible_cases(cases, fc.MODELS["gefs-reforecast"])
    assert g["valid_date"].between("2000-01-02", "2019-12-31").all() and len(g) > 0
    a = fc.eligible_cases(cases, fc.MODELS["aifs"])
    assert (a["valid_date"] >= "2024-02-29").all()
    assert fc.MODELS["gefs-reforecast"].members == ("c00", "p01", "p02", "p03", "p04")


# --- crop / grid ---------------------------------------------------------------------------------


def _field(step: float, lat0=-45.0, lat1=-32.0, lon0=-75.0, lon1=-64.0) -> xr.DataArray:
    lat, lon = np.arange(lat0, lat1 + 1e-6, step), np.arange(lon0, lon1 + 1e-6, step)
    vals = lat[:, None] * 0.0 + lon[None, :] + 100.0  # increases with lon: linear, easy to check
    return xr.DataArray(vals, dims=("lat", "lon"), coords={"lat": lat, "lon": lon})


def test_target_grid_shape_and_regrid():
    assert (len(fc.LAT), len(fc.LON)) == (21, 15)
    assert fc.LAT[0] == -41 and fc.LAT[-1] == -36 and fc.LON[0] == -71.5 and fc.LON[-1] == -68
    exact = fc.to_target_grid(_field(0.25))
    assert exact.shape == (21, 15) and exact.dtype == np.float32
    np.testing.assert_allclose(exact[0], fc.LON + 100.0, atol=1e-4)
    coarse = fc.to_target_grid(_field(0.4, lat0=-45.2, lat1=-32.0, lon0=-75.2, lon1=-64.0))
    assert coarse.shape == (21, 15)
    np.testing.assert_allclose(
        coarse[3], fc.LON + 100.0, atol=1e-3
    )  # bilinear keeps a linear field


# --- fake fetcher, shards, combine ---------------------------------------------------------------


class FakeFetcher:
    def __init__(self, missing=(), fail=()):
        self.calls = []
        self.missing, self.fail = set(missing), set(fail)

    def fetch(self, model, init, lead, member):
        self.calls.append((model, init, lead, member))
        key = (init.strftime("%Y%m%d"), lead)
        if key in self.missing:
            return None
        if key in self.fail:
            raise fc.FetchError("boom")
        seed = int(init.strftime("%Y%m%d")) * 100 + lead * 10 + fc.GEFS_MEMBERS.index(member) % 5
        rng = np.random.default_rng(seed)
        return rng.random((len(fc.LAT), len(fc.LON)), dtype=np.float32)


@pytest.fixture
def cases():
    return fc.eligible_cases(
        cases_mod.build_cases(make_events(4, range(2005, 2012)), 5), fc.MODELS["gefs-reforecast"]
    )


SPEC = fc.MODELS["gefs-reforecast"]
LEADS3 = (1, 5, 10)


def test_shard_split_covers_all_cases_once(cases):
    ids = list(cases["case_id"])
    for n in (1, 3, 8, len(ids) + 5):
        parts = [fc.split_shard(ids, i, n) for i in range(1, n + 1)]
        assert sorted(p for part in parts for p in part) == sorted(ids)
    assert fc.parse_shard("3/8") == (3, 8)
    for bad in ("0/8", "9/8", "x"):
        with pytest.raises(ValueError):
            fc.parse_shard(bad)


def test_store_shape_crop_and_values(tmp_path, cases):
    sub = cases.iloc[:3].reset_index(drop=True)
    path = tmp_path / "m.zarr"
    res = store.fetch_shard(
        SPEC, sub, FakeFetcher(), path, LEADS3, workers=4, log_fn=lambda m: None
    )
    assert res["n_ok"] == 3 * 3 * 5 and res["n_missing"] == 0 and res["n_pending"] == 0
    ds = store.read_store(path)
    assert ds["precip_mm"].dims == ("case", "lead", "member", "lat", "lon")
    assert ds["precip_mm"].shape == (3, 3, 5, 21, 15) and ds["precip_mm"].dtype == np.float32
    assert (np.diff(ds["lat"]) > 0).all() and (np.diff(ds["lon"]) > 0).all()
    assert float(ds["lat"].min()) == -41 and float(ds["lon"].max()) == -68
    assert set(ds["kind"].values) <= {"event", "control"}
    assert ds["init_date"].dims == ("case", "lead")
    for ci in range(3):
        v = pd.Timestamp(ds["valid_date"].values[ci])
        for li, lead in enumerate(LEADS3):
            assert pd.Timestamp(ds["init_date"].values[ci, li]) == v - pd.Timedelta(days=lead - 1)
    for key in ("source", "license", "period", "lead_convention", "created_by"):
        assert ds.attrs[key]
    assert "CC-BY" in fc.MODELS["ifs"].license and "NODD" in SPEC.license


def test_missing_file_is_nan_and_counted(tmp_path, cases):
    sub = cases.iloc[:2].reset_index(drop=True)
    gone = sub["valid_date"].iloc[0].strftime("%Y%m%d"), 1
    path = tmp_path / "m.zarr"
    res = store.fetch_shard(
        SPEC, sub, FakeFetcher(missing=[gone]), path, LEADS3, 2, log_fn=lambda m: None
    )
    assert res["n_missing"] == 5  # all five members of that init
    ds = store.read_store(path)
    assert ds.attrs["n_missing"] == 5
    assert np.isnan(ds["precip_mm"].values[0, 0]).all()
    assert np.isfinite(ds["precip_mm"].values[0, 1]).all()
    assert (ds["status"].values[0, 0] == fc.STATUS_MISSING).all()


def test_resume_is_idempotent_and_retries_errors(tmp_path, cases):
    sub = cases.iloc[:4].reset_index(drop=True)
    path = tmp_path / "m.zarr"
    bad = fc.init_date(sub["valid_date"].iloc[1], 5).strftime("%Y%m%d"), 5
    first = FakeFetcher(fail=[bad])
    r1 = store.fetch_shard(SPEC, sub, first, path, LEADS3, 4, batch_cases=2, log_fn=lambda m: None)
    assert r1["n_error"] == 5 and len(first.calls) == 4 * 3 * 5
    again = FakeFetcher()
    r2 = store.fetch_shard(SPEC, sub, again, path, LEADS3, 4, log_fn=lambda m: None)
    assert (
        len(again.calls) == 5 and r2["n_error"] == 0 and r2["n_ok"] == 4 * 3 * 5
    )  # only the failed lead
    third = FakeFetcher()
    store.fetch_shard(SPEC, sub, third, path, LEADS3, 4, log_fn=lambda m: None)
    assert third.calls == []
    full = store.read_store(path)
    ref_path = tmp_path / "ref.zarr"
    store.fetch_shard(SPEC, sub, FakeFetcher(), ref_path, LEADS3, 4, log_fn=lambda m: None)
    xr.testing.assert_identical(full, store.read_store(ref_path))


def test_resume_rejects_other_layout(tmp_path, cases):
    path = tmp_path / "m.zarr"
    store.fetch_shard(SPEC, cases.iloc[:2], FakeFetcher(), path, LEADS3, 2, log_fn=lambda m: None)
    with pytest.raises(ValueError, match="different"):
        store.fetch_shard(
            SPEC, cases.iloc[:3], FakeFetcher(), path, LEADS3, 2, log_fn=lambda m: None
        )


def test_combine_equals_unsharded(tmp_path, cases):
    sub = cases.iloc[:11].reset_index(drop=True)
    gone = fc.init_date(sub["valid_date"].iloc[4], 10).strftime("%Y%m%d"), 10
    sharded, whole = tmp_path / "sharded", tmp_path / "whole"
    n = 3
    for i in range(1, n + 1):
        mine = sub.iloc[i - 1 :: n].reset_index(drop=True)
        store.fetch_shard(
            SPEC, mine, FakeFetcher(missing=[gone]), store.shard_path(sharded, SPEC.name, i, n),
            LEADS3, 4, log_fn=lambda m: None,
        )  # fmt: skip
    store.fetch_shard(
        SPEC, sub, FakeFetcher(missing=[gone]), store.shard_path(whole, SPEC.name, 1, 1),
        LEADS3, 4, log_fn=lambda m: None,
    )  # fmt: skip
    merged = store.combine_shards(SPEC, sharded, tmp_path / "out" / "m.zarr", run_id="42")
    single = store.combine_shards(SPEC, whole, tmp_path / "out1" / "m.zarr")
    xr.testing.assert_equal(merged.drop_vars("status"), single.drop_vars("status"))
    xr.testing.assert_equal(merged["status"], single["status"])
    assert merged.attrs["n_shards"] == 3 and merged.attrs["run_id"] == "42"
    assert merged.attrs["n_missing"] == single.attrs["n_missing"] == 5
    assert sorted(merged["case"].values) == sorted(sub["case_id"])
    reread = store.read_store(tmp_path / "out" / "m.zarr")
    xr.testing.assert_identical(reread, merged)
    # a missing shard is refused
    (store.shard_path(sharded, SPEC.name, 2, n)).rename(tmp_path / "gone.zarr")
    with pytest.raises(ValueError, match="missing shards"):
        store.combine_shards(SPEC, sharded, tmp_path / "x.zarr")


# --- HTTP layer ----------------------------------------------------------------------------------


def _fetcher(handler, retries=3):
    f = fc.HttpFetcher(retries=retries, backoff=0.0, sleep=lambda s: None)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    return f


def test_http_retries_then_succeeds_and_404_is_none():
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("missing"):
            return httpx.Response(404)
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200, content=b"ok")

    f = _fetcher(handler)
    assert f._get("https://x/y") == b"ok" and calls["n"] == 3
    assert f._get("https://x/missing") is None
    assert f.bytes > 0


def test_http_gives_up_with_fetch_error():
    f = _fetcher(lambda request: httpx.Response(500), retries=2)
    with pytest.raises(fc.FetchError):
        f._get("https://x/y")


def test_gefs_fetch_uses_only_bucket_ranges(monkeypatch):
    ranges = []

    def handler(request):
        if request.url.path.endswith(".idx"):
            return httpx.Response(200, text=IDX)
        ranges.append(request.headers["Range"])
        return httpx.Response(206, content=b"GRIB")

    monkeypatch.setattr(
        fc, "grib_fields",
        lambda blob, area: [({"stepRange": f"{len(ranges) * 0}"}, _field(0.25))],
    )  # fmt: skip
    f = _fetcher(handler)
    with pytest.raises(RuntimeError, match="want 0-6"):  # stepRange check guards the bucket choice
        f._fetch_gefs(pd.Timestamp("2005-01-01"), 1, "c00")
    assert ranges == ["bytes=465975-1022779"]


def test_gefs_fetch_sums_four_buckets(monkeypatch):
    ranges = []

    def handler(request):
        if request.url.path.endswith(".idx"):
            return httpx.Response(200, text=IDX)
        ranges.append(request.headers["Range"])
        return httpx.Response(206, content=b"GRIB")

    order = iter(["0-6", "6-12", "12-18", "18-24"])
    monkeypatch.setattr(
        fc, "grib_fields", lambda blob, area: [({"stepRange": next(order)}, _field(0.25) * 0 + 2.5)]
    )
    f = _fetcher(handler)
    out = f._fetch_gefs(pd.Timestamp("2005-01-01"), 1, "c00")
    assert out.shape == (21, 15) and np.allclose(out, 10.0)
    assert ranges == [
        "bytes=465975-1022779",
        "bytes=1457115-1737851",
        "bytes=1980698-2272912",
        "bytes=2722351-3014157",
    ]


def test_gefs_missing_idx_is_none():
    f = _fetcher(lambda request: httpx.Response(404))
    assert f.fetch("gefs-reforecast", pd.Timestamp("2005-01-01"), 1, "c00") is None


def test_ecmwf_fetch_difference_and_dir_fallback(monkeypatch):
    seen = []

    def handler(request):
        url = str(request.url)
        seen.append(url)
        if "/0p25/oper/" in url:  # not published there: fall back to the next directory
            return httpx.Response(404)
        if url.endswith(".index"):
            step = int(url.rsplit("-", 3)[1].rstrip("h"))
            rec = {
                "param": "tp",
                "levtype": "sfc",
                "step": str(step),
                "_offset": 100,
                "_length": 50,
            }
            return httpx.Response(200, text=json.dumps(rec) + "\n")
        assert request.headers["Range"] == "bytes=100-149"
        return httpx.Response(206, content=b"GRIB")

    cum = iter([0.020, 0.012])  # metres at step 48, then at step 24
    monkeypatch.setattr(
        fc, "grib_fields", lambda blob, area: [({"units": "m"}, _field(0.25) * 0 + next(cum))]
    )
    f = _fetcher(handler)
    out = f.fetch("ifs", pd.Timestamp("2023-03-01"), 2, "oper")
    assert np.allclose(out, 8.0, atol=1e-3)  # (0.020 - 0.012) m = 8 mm
    assert any("/0p4-beta/oper/" in u for u in seen)


# --- CLI -----------------------------------------------------------------------------------------


def test_cli_cases_and_bad_args(tmp_path):
    ev = make_events()
    events = tmp_path / "events.parquet"
    ev.to_parquet(events)
    runner = CliRunner()
    out = tmp_path / "cases.parquet"
    res = runner.invoke(
        app, ["hindcast", "cases", "--events", str(events), "--out", str(out), "--seed", "9"]
    )
    assert res.exit_code == 0, res.output
    assert len(pd.read_parquet(out)) > len(ev)
    res = runner.invoke(
        app, ["hindcast", "fetch", "--model", "nope", "--cases", str(out), "--out", str(tmp_path)]
    )
    assert res.exit_code != 0
    res = runner.invoke(
        app,
        [
            "hindcast",
            "fetch",
            "--model",
            "ifs",
            "--cases",
            str(out),
            "--out",
            str(tmp_path),
            "--shard",
            "9/8",
        ],
    )
    assert res.exit_code != 0


# --- units, sanity guard ---------------------------------------------------------------------------


def test_tp_unit_from_message_not_model():
    metres, kgm2 = _field(0.25) * 0 + 0.008, _field(0.25) * 0 + 8.0
    np.testing.assert_allclose(fc.tp_mm({"units": "m"}, metres), 8.0)
    np.testing.assert_allclose(fc.tp_mm({"units": "kg m**-2"}, kgm2), 8.0)
    with pytest.raises(ValueError, match="unknown tp unit"):
        fc.tp_mm({"units": "furlong"}, metres)


def test_box_mean_guard_marks_error(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="implausible"):
        fc.check_box_mean(np.full((21, 15), 3000.0), "x")
    fc.check_box_mean(np.full((21, 15), 40.0), "x")

    def handler(request):
        url = str(request.url)
        if url.endswith(".index"):
            rec = {
                "param": "tp",
                "levtype": "sfc",
                "step": url.rsplit("-", 3)[1][:-1],
                "_offset": 0,
                "_length": 4,
            }
            return httpx.Response(200, text=json.dumps(rec) + "\n")
        return httpx.Response(206, content=b"GRIB")

    monkeypatch.setattr(
        fc, "grib_fields", lambda blob, area: [({"units": "m"}, _field(0.25) * 0 + 5.0)]
    )
    f = _fetcher(handler)  # 5 "m" -> 5000 mm: the guard rejects it, fetch_shard records status 2
    with pytest.raises(ValueError, match="implausible"):
        f.fetch("aifs", pd.Timestamp("2025-06-01"), 1, "oper")
    cases_ = pd.DataFrame(
        {
            "case_id": ["a"],
            "kind": ["event"],
            "event_id": ["a"],
            "valid_date": [pd.Timestamp("2025-06-01")],
        }
    )
    path = tmp_path / "g.zarr"
    res = store.fetch_shard(fc.MODELS["aifs"], cases_, f, path, (1,), 1, log_fn=lambda m: None)
    assert res["n_error"] == 1 and res["n_ok"] == 0
