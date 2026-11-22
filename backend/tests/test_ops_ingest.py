"""F6.1b: idempotent operational ingest, all with fake fetchers (no network)."""

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import flow, snow
from clima_nqn.ops import ingest
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import riskday

RUN = pd.Timestamp("2026-11-22")
SIDS = sorted(snow.UPSTREAM_BOXES)


def ms(day: str) -> str:
    """SNIH `/Date(ms)/` of local midnight (UTC-3) of ``day``."""
    t = pd.Timestamp(day) + pd.Timedelta(hours=3)
    return f"/Date({int(t.value // 1_000_000)})/"


def fake_flow(station_id, start, stop):
    days = pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=5), RUN + pd.Timedelta(days=3))
    return [  # includes days outside the asked window and on/after RUN
        {
            "FechaHora": ms(f"{d:%Y-%m-%d}"),
            "Medicion": 100.0 + i,
            "Calificador": "",
            "Validado": True,
        }
        for i, d in enumerate(days)
    ]


ONI_TEXT = """SEAS  YR   TOTAL   ANOM
 JJA 2026   26.0   0.10
 JAS 2026   26.1   0.30
 ASO 2026   26.2   0.50
 SON 2026   26.3   0.70
 OND 2026   26.4   0.90
"""


def grid(value=1.0):
    lat = np.arange(-40.0, -35.0, 0.25)
    lon = np.arange(-72.0, -69.0, 0.25)
    return xr.DataArray(np.full((len(lat), len(lon)), value), dims=("lat", "lon"),
                        coords={"lat": lat, "lon": lon})  # fmt: skip


def fake_era5t(start, stop, area):
    times = pd.date_range(start, stop, freq="h")
    lat, lon = grid()["lat"].values, grid()["lon"].values
    vals = np.full((len(times), len(lat), len(lon)), 0.001 / 24)  # 1 mm per 24 h, in m/hour
    return xr.DataArray(vals, dims=("time", "lat", "lon"),
                        coords={"time": times, "lat": lat, "lon": lon})  # fmt: skip


def fake_ecmwf(init, steps, area):
    # cumulative tp in m: 2 mm on day 1, 3 mm on day 2, ... (lead d gives d+1 mm)
    cum = np.cumsum([d + 1 for d in range(1, 11)]) / 1000.0
    return {s: grid(cum[s // 24 - 1]) for s in steps}


def fake_gefs(init, member, step, area):
    return grid(1.0 if member == "geavg" else 2.0)  # mm per 6 h bucket


def wide_field(value=1.0, margin=True):
    """Constant field on the wide grid (plus the decoding margin for GEFS)."""
    n, w, s_, e = fc._margin_area(fc.WIDE_GRID.area) if margin else fc.WIDE_GRID.area
    lat = np.round(np.arange(s_, n + 1e-6, 0.25), 4)
    lon = np.round(np.arange(w, e + 1e-6, 0.25), 4)
    return xr.DataArray(np.full((len(lat), len(lon)), float(value)), dims=("lat", "lon"),
                        coords={"lat": lat, "lon": lon})  # fmt: skip


def fake_gefs25(init, member, step, area):
    return wide_field(1.0 + fc.GEFS_MEMBERS.index(member))  # mm per 6 h bucket: 1..5


def fake_era5t_regions(start, stop, area):
    times = pd.date_range(start, stop, freq="h")
    f = wide_field(0.002 / 24, margin=False)  # 2 mm per day, in m per hour
    vals = np.broadcast_to(f.values, (len(times), *f.shape)).copy()
    return xr.DataArray(vals, dims=("time", "lat", "lon"),
                        coords={"time": times, "lat": f["lat"].values, "lon": f["lon"].values})  # fmt: skip


FETCHERS = {
    "flow": fake_flow,
    "oni": lambda: ONI_TEXT,
    "era5t": fake_era5t,
    "ecmwf": fake_ecmwf,
    "gefs": fake_gefs,
    "gefs_regions": fake_gefs25,
    "era5t_regions": fake_era5t_regions,
}
CLOCK = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def run(root, **kw):
    kw.setdefault("fetchers", FETCHERS)
    kw.setdefault("now", lambda: CLOCK)
    return ingest.run_ingest(RUN, root, **kw)


def test_all_sources_ok_with_metadata_and_manifest(tmp_path):
    res = run(tmp_path)
    assert {k: v["status"] for k, v in res.items()} == dict.fromkeys(ingest.SOURCES, "ok")
    for name in ingest.SOURCES:
        path = tmp_path / name / "2026-11-22.parquet"
        df = pd.read_parquet(path)
        assert {"available_on", "fetched_at"} <= set(df.columns)
        assert (df["available_on"] == RUN).all()
        meta = pq.read_schema(path).metadata
        assert {b"source", b"license", b"units"} <= set(meta)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["flow"]["newest_value_date"] == "2026-11-21"
    assert manifest["flow"]["lag_days"] == 1
    assert manifest["oni"]["newest_value_date"] == "2026-09-01"  # ASO, central Sep
    assert manifest["ecmwf"]["newest_value_date"] == "2026-12-01"  # lead 10
    assert manifest["gefs"]["status"] == "ok"


def test_rerun_is_skipped_and_bytes_unchanged_force_rewrites(tmp_path):
    run(tmp_path)
    paths = [tmp_path / n / "2026-11-22.parquet" for n in ingest.SOURCES]
    before = [p.read_bytes() for p in paths]
    res = run(tmp_path)
    assert {v["status"] for v in res.values()} == {"skipped"}
    assert before == [p.read_bytes() for p in paths]
    assert res["flow"]["newest_value_date"] == "2026-11-21"  # kept from the stored file

    later = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)
    res = run(tmp_path, force=True, now=lambda: later)
    assert {v["status"] for v in res.values()} == {"ok"}
    assert before != [p.read_bytes() for p in paths]
    assert (pd.read_parquet(paths[0])["fetched_at"] == pd.Timestamp(later)).all()


def test_skipped_does_not_call_fetcher(tmp_path):
    run(tmp_path, sources=["oni"])

    def boom():
        raise AssertionError("fetcher called")

    res = run(tmp_path, sources=["oni"], fetchers={"oni": boom})
    assert res["oni"]["status"] == "skipped"


def test_atomic_write_crash_leaves_no_target(tmp_path, monkeypatch):
    real = pq.write_table

    def crash(table, where, *a, **k):
        real(table, where)
        with open(where, "r+b") as fh:
            fh.truncate(10)  # partial file on disk
        raise OSError("disk full")

    monkeypatch.setattr(ingest.pq, "write_table", crash)
    res = run(tmp_path, sources=["oni"])
    assert res["oni"]["status"] == "failed" and "disk full" in res["oni"]["error"]
    assert not (tmp_path / "oni" / "2026-11-22.parquet").exists()
    assert list((tmp_path / "oni").glob("*")) == []  # temp file cleaned up


def test_atomic_write_keeps_previous_file_on_force_crash(tmp_path, monkeypatch):
    run(tmp_path, sources=["oni"])
    target = tmp_path / "oni" / "2026-11-22.parquet"
    before = target.read_bytes()
    monkeypatch.setattr(
        ingest.pq, "write_table", lambda *a, **k: (_ for _ in ()).throw(OSError("x"))
    )
    res = run(tmp_path, sources=["oni"], force=True)
    assert res["oni"]["status"] == "failed"
    assert target.read_bytes() == before


def test_no_rows_after_date(tmp_path):
    run(tmp_path)
    flow_df = pd.read_parquet(tmp_path / "flow" / "2026-11-22.parquet")
    assert flow_df["date"].max() == RUN - pd.Timedelta(days=1)
    assert flow_df["date"].min() == RUN - pd.Timedelta(days=60)
    assert sorted(flow_df["station_id"].unique()) == sorted(s["id"] for s in flow.STATIONS)
    oni_df = pd.read_parquet(tmp_path / "oni" / "2026-11-22.parquet")
    assert oni_df["date"].max() == pd.Timestamp("2026-09-01")  # OND (Nov) not yet published
    assert (oni_df["nominal_publication"] <= RUN).all()
    era = pd.read_parquet(tmp_path / "era5t" / "2026-11-22.parquet")
    assert era["date"].max() == RUN - pd.Timedelta(days=1)
    assert era["date"].min() == RUN - pd.Timedelta(days=14)
    for name in ("ecmwf", "gefs"):
        df = pd.read_parquet(tmp_path / name / "2026-11-22.parquet")
        assert (df["init_date"] <= RUN).all() and (df["available_on"] <= RUN).all()


def test_leak_guard_rejects_future_rows():
    df = pd.DataFrame({"date": [RUN], "available_on": [RUN]})
    with pytest.raises(ValueError, match="not before"):
        ingest.check_no_leak(df, "flow", RUN)
    df = pd.DataFrame({"init_date": [RUN + pd.Timedelta(days=1)], "available_on": [RUN]})
    with pytest.raises(ValueError, match="init_date"):
        ingest.check_no_leak(df, "ecmwf", RUN)


def test_failing_source_does_not_block_others(tmp_path):
    def broken(*a, **k):
        raise RuntimeError("SNIH down")

    res = run(tmp_path, fetchers={**FETCHERS, "flow": broken})
    assert res["flow"]["status"] == "failed" and "SNIH down" in res["flow"]["error"]
    assert all(res[n]["status"] == "ok" for n in ingest.SOURCES if n != "flow")
    assert not (tmp_path / "flow" / "2026-11-22.parquet").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["flow"]["status"] == "failed" and manifest["oni"]["status"] == "ok"


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown sources"):
        run(tmp_path, sources=["nope"])


def test_cli_exit_code_only_nonzero_if_all_fail(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setitem(ingest.ADAPTERS, "oni", fail)
    monkeypatch.setitem(
        ingest.ADAPTERS,
        "flow",
        lambda run_date, now=None, **k: ingest.ingest_flow(run_date, fetcher=fake_flow, now=now),
    )
    runner = CliRunner()
    base = ["ops", "ingest", "--date", "2026-11-22", "--root", str(tmp_path)]
    one_ok = runner.invoke(app, [*base, "--sources", "oni,flow"])
    assert one_ok.exit_code == 0, one_ok.output
    assert "oni: failed" in one_ok.output and "flow: ok" in one_ok.output
    all_bad = runner.invoke(app, [*base, "--sources", "oni", "--force"])
    assert all_bad.exit_code == 1


def test_daily_from_cumulative_steps():
    cum = {24: 2.0, 48: 5.0, 72: 5.0, 96: 4.9999}
    out = ingest.daily_from_cumulative(cum, [24, 48, 72, 96])
    assert out == {1: 2.0, 2: 3.0, 3: 0.0, 4: 0.0}  # no negative noise
    with pytest.raises(ValueError):
        ingest.daily_from_cumulative({24: 1.0, 72: 2.0}, [24, 72])


def test_ecmwf_daily_values_and_valid_dates(tmp_path):
    df = ingest.ingest_ecmwf(RUN, fetcher=fake_ecmwf, now=CLOCK)
    s = df[df["station_id"] == SIDS[0]].set_index("lead_day")
    assert np.allclose(s["precip_mm"], [d + 1 for d in range(1, 11)])  # 2, 3, ..., 11 mm
    assert s.loc[1, "valid_date"] == RUN and s.loc[10, "valid_date"] == RUN + pd.Timedelta(days=9)
    assert (df["init_date"] == RUN).all()


def test_ecmwf_falls_back_to_previous_run(tmp_path):
    asked = []

    def fetcher(init, steps, area):
        asked.append(pd.Timestamp(init))
        if pd.Timestamp(init) == RUN:
            raise ingest.NotAvailable("not yet")
        return fake_ecmwf(init, steps, area)

    df = ingest.ingest_ecmwf(RUN, fetcher=fetcher, now=CLOCK)
    assert asked == [RUN, RUN - pd.Timedelta(days=1)]
    assert (df["init_date"] == RUN - pd.Timedelta(days=1)).all()
    assert (df["available_on"] == RUN).all()


def test_gefs_buckets_sum_to_daily_per_member():
    df = ingest.ingest_gefs(RUN, fetcher=fake_gefs, now=CLOCK)
    assert set(df["member"]) == {"geavg", "gec00"}
    assert len(df) == 2 * 3 * 10
    mean = df[(df["member"] == "geavg") & (df["lead_day"] == 4)]["precip_mm"]
    ctl = df[(df["member"] == "gec00") & (df["lead_day"] == 4)]["precip_mm"]
    assert np.allclose(mean, 4.0) and np.allclose(ctl, 8.0)  # 4 buckets x 1 mm / 2 mm
    with pytest.raises(ValueError, match="missing"):
        ingest.daily_from_buckets({6: 1.0, 12: 1.0}, 1)


def test_parse_gefs_idx():
    idx = "68:100:d=2026112100:TMP:2 m above ground:ens mean\n69:250:d=2026112100:APCP:surface:0-6 hour acc fcst:x\n70:400:d=2026112100:RH:2 m:x\n"
    assert ingest.parse_gefs_idx(idx) == (250, 399)
    assert ingest.parse_gefs_idx("1:0:d=1:TMP:2 m:x\n") is None


def test_box_mean_weights_by_cos_lat_and_cell_centres():
    box = (-38.0, -36.0, -71.0, -70.0)  # south, north, west, east
    lat = np.array([-38.0, -37.0, -36.0, -35.0])  # last row outside the box
    lon = np.array([-71.5, -71.0, -70.5, -70.0, -69.5])  # first and last columns outside
    vals = np.zeros((4, 5))
    vals[0, 1:4] = 10.0
    vals[1, 1:4] = 20.0
    vals[2, 1:4] = 30.0
    vals[3, :] = 999.0
    vals[:, [0, 4]] = 999.0
    da = xr.DataArray(vals, dims=("lat", "lon"), coords={"lat": lat, "lon": lon})
    w = np.cos(np.radians([-38.0, -37.0, -36.0]))
    expected = (w * np.array([10.0, 20.0, 30.0])).sum() / w.sum()
    got = ingest.box_means(da, {1: box})[1]
    assert got == pytest.approx(expected)
    assert got != pytest.approx(20.0)  # not the plain mean


def test_era5t_daily_sum_uses_era5_day_convention():
    df = ingest.ingest_era5t(RUN, fetcher=fake_era5t, now=CLOCK)
    assert np.allclose(df["precip_mm"], 1.0)  # 24 x (1/24) mm per day
    assert len(df) == 3 * 14


def test_era5t_drops_incomplete_days():
    def short(start, stop, area):
        return fake_era5t(start, stop - pd.Timedelta(hours=5), area)  # last day misses hours

    df = ingest.ingest_era5t(RUN, fetcher=short, now=CLOCK)
    assert df["date"].max() == RUN - pd.Timedelta(days=2)


def test_grib_roundtrip_decode_and_crop():
    eccodes = pytest.importorskip("eccodes")
    h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    for k, v in {"Ni": 8, "Nj": 6, "latitudeOfFirstGridPointInDegrees": -35.0,
                 "latitudeOfLastGridPointInDegrees": -40.0, "longitudeOfFirstGridPointInDegrees": 286.0,
                 "longitudeOfLastGridPointInDegrees": 293.0, "iDirectionIncrementInDegrees": 1.0,
                 "jDirectionIncrementInDegrees": 1.0, "step": 24}.items():  # fmt: skip
        eccodes.codes_set(h, k, v)
    eccodes.codes_set(h, "shortName", "tp")
    eccodes.codes_set_values(h, np.arange(48, dtype=float))
    blob = eccodes.codes_get_message(h)
    eccodes.codes_release(h)
    [(keys, da)] = ingest.grib_fields(blob, (-37.0, -73.0, -39.0, -70.0))
    assert keys["shortName"] == "tp" and keys["step"] == 24
    assert da["lat"].values.tolist() == [-39.0, -38.0, -37.0]
    assert da["lon"].values.tolist() == [-73.0, -72.0, -71.0, -70.0]
    # source row 2 = lat -37 (index 2), lon 287 -> -73 (column 1): value 2*8+1 = 17
    assert float(da.sel(lat=-37.0, lon=-73.0)) == 17.0


# --- F6.3: regional GEFS 0.25 and ERA5T -----------------------------------------------------------


def test_gefs25_url_and_idx_span():
    url = ingest.gefs25_url(RUN.date(), "p01", 240)
    assert url.endswith("/gefs.20261122/00/atmos/pgrb2sp25/gep01.t00z.pgrb2s.0p25.f240")
    idx = (
        "17:900:d=2026112200:CPOFP:surface:12 hour fcst:ENS=+1\n"
        "18:1000:d=2026112200:APCP:surface:6-12 hour acc fcst:ENS=+1\n"
        "19:1500:d=2026112200:CSNOW:surface:6-12 hour ave fcst:ENS=+1\n"
    )
    assert ingest.parse_gefs_idx(idx, span=(6, 12)) == (1000, 1499)
    assert (
        ingest.parse_gefs_idx(idx, span=(0, 12)) is None
    )  # accumulation from 0 is not a 6 h bucket


def test_gefs_regions_schema_members_leads_and_daily_sum():
    df = ingest.ingest_gefs_regions(RUN, fetcher=fake_gefs25, now=CLOCK)
    assert list(df.columns) == [
        "init_date", "lead", "valid_date", "member", "region", "tp_mm", "available_on", "fetched_at",
    ]  # fmt: skip
    assert set(df["member"]) == set(fc.GEFS_MEMBERS) and set(df["region"]) == set(riskday.REGIONS)
    assert sorted(df["lead"].unique()) == list(range(1, 11)) and df["lead"].dtype.kind == "i"
    assert len(df) == 5 * 3 * 10
    one = df[(df["member"] == "p03") & (df["lead"] == 4) & (df["region"] == "confluencia")]
    assert one["tp_mm"].iloc[0] == pytest.approx(4 * 4.0)  # p03 = 4 mm per bucket x 4 buckets
    assert one["valid_date"].iloc[0] == RUN + pd.Timedelta(days=3)
    assert (df["init_date"] == RUN).all() and (df["available_on"] == RUN).all()


def test_gefs_regions_daily_uses_the_right_buckets():
    seen = {}

    def fetcher(init, member, step, area):
        seen.setdefault(member, []).append(step)
        return wide_field(float(step))  # bucket value = its end step

    df = ingest.ingest_gefs_regions(RUN, fetcher=fetcher, members=("c00",), now=CLOCK)
    assert sorted(seen["c00"]) == list(range(6, 241, 6))
    got = df[(df["lead"] == 2) & (df["region"] == "confluencia")]["tp_mm"].iloc[0]
    assert got == pytest.approx(30 + 36 + 42 + 48)  # buckets ending f030, f036, f042, f048


def test_gefs_regions_missing_member_keeps_others_and_logs(tmp_path):
    def fetcher(init, member, step, area):
        if member == "p02":
            raise ingest.NotAvailable("p02 absent")
        if member == "p04" and step == 60:  # one step of lead 3 (hours 48-72)
            raise ingest.NotAvailable("p04 f060 absent")
        return fake_gefs25(init, member, step, area)

    res = run(tmp_path, sources=["gefs_regions"], fetchers={"gefs_regions": fetcher})
    assert res["gefs_regions"]["status"] == "ok"
    df = pd.read_parquet(tmp_path / "gefs_regions" / "2026-11-22.parquet")
    assert set(df["member"]) == {"c00", "p01", "p03", "p04"}
    p04 = df[df["member"] == "p04"]
    assert 3 not in set(p04["lead"]) and len(p04) == 9 * 3  # dropped, not zero
    detail = json.loads((tmp_path / "manifest.json").read_text())["gefs_regions"]["detail"]
    assert "p02" in detail["missing_steps"] and detail["missing_steps"]["p04"] == [60]
    assert detail["members_present"] == ["c00", "p01", "p03", "p04"]


def test_gefs_regions_falls_back_when_run_incomplete():
    def fetcher(init, member, step, area):
        if pd.Timestamp(init) == RUN and step > 120:  # newest run still being published
            raise ingest.NotAvailable("not yet")
        return fake_gefs25(init, member, step, area)

    df = ingest.ingest_gefs_regions(RUN, fetcher=fetcher, now=CLOCK)
    assert (df["init_date"] == RUN - pd.Timedelta(days=1)).all()
    assert (df["available_on"] == RUN).all()

    def never(init, member, step, area):
        raise ingest.NotAvailable("no")

    with pytest.raises(ingest.NotAvailable):
        ingest.ingest_gefs_regions(RUN, fetcher=never, now=CLOCK)


def test_wide_region_means_equal_riskday_region_means():
    grid = fc.WIDE_GRID
    lat2d, lon2d = np.meshgrid(grid.lat, grid.lon, indexing="ij")
    vals = 5.0 + np.sin(lat2d) * 3 + np.cos(lon2d * 2)
    vals[3, 4] = np.nan
    field = xr.DataArray(vals, dims=("lat", "lon"), coords={"lat": grid.lat, "lon": grid.lon})
    masks = riskday.regions(grid.lat, grid.lon)
    expected = riskday.region_means(field, masks)
    got = ingest.wide_region_means(field, masks)
    assert set(got) == set(riskday.REGIONS)
    for name in masks:
        assert got[name] == pytest.approx(float(expected[name]), rel=1e-6)
        w = np.cos(np.radians(lat2d))[masks[name] & ~np.isnan(vals)]
        manual = (vals[masks[name] & ~np.isnan(vals)] * w).sum() / w.sum()
        assert got[name] == pytest.approx(manual, rel=1e-5)
    assert len({round(v, 6) for v in got.values()}) == 3  # regions differ


def test_era5t_regions_daily_window_and_drops_empty_days(tmp_path):
    df = ingest.ingest_era5t_regions(RUN, fetcher=fake_era5t_regions, now=CLOCK)
    assert list(df.columns) == ["date", "region", "tp_mm", "available_on", "fetched_at"]
    assert np.allclose(df["tp_mm"], 2.0) and len(df) == 3 * 14
    assert set(df["region"]) == set(riskday.REGIONS)
    assert df["date"].min() == RUN - pd.Timedelta(days=14)
    assert df["date"].max() == RUN - pd.Timedelta(days=1)

    empty_day = RUN - pd.Timedelta(days=5)

    def with_gap(start, stop, area):
        da = fake_era5t_regions(start, stop, area)
        t = pd.DatetimeIndex(da["time"].values)
        gap = (t > empty_day) & (t <= empty_day + pd.Timedelta(days=1))  # hours D 01..D+1 00
        vals = da.values.copy()
        vals[gap] = np.nan
        return da.copy(data=vals)

    df = ingest.ingest_era5t_regions(RUN, fetcher=with_gap, now=CLOCK)
    assert empty_day not in set(df["date"]) and len(df) == 3 * 13
    assert not df["tp_mm"].isna().any()


def test_new_sources_idempotent_and_no_leak(tmp_path):
    names = ["gefs_regions", "era5t_regions"]
    first = run(tmp_path, sources=names)
    assert {v["status"] for v in first.values()} == {"ok"}
    paths = [tmp_path / n / "2026-11-22.parquet" for n in names]
    before = [p.read_bytes() for p in paths]

    def boom(*a, **k):
        raise AssertionError("fetcher called")

    second = run(tmp_path, sources=names, fetchers={n: boom for n in names})
    assert {v["status"] for v in second.values()} == {"skipped"}
    assert before == [p.read_bytes() for p in paths]
    assert second["gefs_regions"]["detail"] == first["gefs_regions"]["detail"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["era5t_regions"]["newest_value_date"] == "2026-11-21"
    assert manifest["gefs_regions"]["newest_value_date"] == "2026-12-01"
    meta = pq.read_schema(paths[0]).metadata
    assert b"pgrb2sp25" in meta[b"source"] and b"NODD" in meta[b"license"]

    bad = pd.DataFrame({"init_date": [RUN + pd.Timedelta(days=1)], "available_on": [RUN]})
    with pytest.raises(ValueError, match="init_date"):
        ingest.check_no_leak(bad, "gefs_regions", RUN)
    bad = pd.DataFrame({"date": [RUN], "available_on": [RUN]})
    with pytest.raises(ValueError, match="not before"):
        ingest.check_no_leak(bad, "era5t_regions", RUN)
