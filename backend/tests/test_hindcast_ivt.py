"""F5.10: forecast IVT from pressure levels, ivt store, ERA5 ivt and the IVT vs. precip verification.

All offline: fake fetchers, a patched GRIB decoder and an ARCO-like fake store.
"""

import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.stages.hindcast import cases as cases_mod
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import observe, store
from clima_nqn.stages.hindcast import verify_ivt as vi

SPEC = fc.MODELS["gefs-reforecast"]
C00 = store.with_members(SPEC, ("c00",))
G = fc.G

# --- ivt_from_levels / steps -------------------------------------------------------------------


def test_ivt_from_levels_constant_fields_hand_value():
    levels = fc.IVT_LEVELS
    q = np.full((8, 2, 3), 0.004)
    u = np.full((8, 2, 3), 6.0)
    v = np.full((8, 2, 3), 8.0)
    got = fc.ivt_from_levels(q, u, v, levels)
    want = 0.004 * 10.0 * (100000 - 30000) / G  # q |V| dp / g, |V| = 10
    assert got.dtype == np.float32 and got.shape == (2, 3)
    np.testing.assert_allclose(got, want, rtol=1e-6)
    assert abs(want - 285.52) < 0.01  # 0.004 * 10 * 70000 / 9.80665
    qu, qv = fc.ivt_vector(q, u, v, levels)
    np.testing.assert_allclose(qu, 0.004 * 6.0 * 70000 / G, rtol=1e-9)
    np.testing.assert_allclose(qv, 0.004 * 8.0 * 70000 / G, rtol=1e-9)


def test_ivt_trapezoid_and_level_order_independent():
    # q*u linear in p: trapezoid is exact; reversed level order gives the same positive integral
    levels = np.array(fc.IVT_LEVELS, dtype=float)
    q = np.ones((8, 1))
    u = (levels / 1000.0)[:, None]  # u = p / 1000 hPa
    v = np.zeros((8, 1))
    got = fc.ivt_from_levels(q, u, v, levels)
    p0, p1 = 30000.0, 100000.0
    np.testing.assert_allclose(got, (p1**2 - p0**2) / 2 / 100000.0 / G, rtol=1e-5)
    rev = fc.ivt_from_levels(q[::-1], u[::-1], v[::-1], levels[::-1])
    np.testing.assert_allclose(rev, got)


@pytest.mark.parametrize(
    ("lead", "steps"), [(1, [6, 12, 18, 24]), (2, [30, 36, 42, 48]), (10, [222, 228, 234, 240])]
)
def test_ivt_steps_for_lead(lead, steps):
    assert fc.ivt_steps(lead) == steps


# --- idx parsing and file families -------------------------------------------------------------

BASE_LEVELS = (1000, 975, 950, 925, 900, 850, 800)  # *_pres
ABV_LEVELS = (700, 600, 500, 400, 300, 250, 200, 150, 100)  # *_pres_abv700mb
SIZE = 100


def make_idx(var: str, levels, steps=range(3, 31, 3)) -> str:
    """Real layout (checked 2026-11-22): step-major, levels in file order, then the next step."""
    lines, off = [], 0
    for st in steps:
        for lv in levels:
            lines.append(
                f"{len(lines) + 1}:{off}:d=2010070100:{var}:{lv} mb:{st} hour fcst:ENS=low-res ctl"
            )
            off += SIZE
    return "\n".join(lines) + "\n"


def test_parse_pres_idx_and_select_across_families():
    text = make_idx("SPFH", BASE_LEVELS)
    fields = fc.parse_pres_idx(text)
    assert len(fields) == 10 * len(BASE_LEVELS)
    assert fields[0] == fc.IdxField("SPFH", 1000, 3, 0, SIZE - 1)
    assert fields[-1].end is None
    assert fc.parse_pres_idx("1:0:d=2010070100:APCP:surface:0-3 hour acc fcst:x\n") == []
    assert fc.parse_pres_idx("1:0:d=2010070100:TMP:850 mb:3 hour fcst:x\n") == []  # not q/u/v
    low = fc.select_ivt_fields(fields, "SPFH", False, 1)
    assert {(f.level, f.step) for f in low} == {
        (lv, st) for lv in (1000, 925, 850) for st in (6, 12, 18, 24)
    }
    assert [f.start for f in low] == sorted(f.start for f in low)
    high = fc.select_ivt_fields(fc.parse_pres_idx(make_idx("UGRD", ABV_LEVELS)), "UGRD", True, 1)
    assert {(f.level, f.step) for f in high} == {
        (lv, st) for lv in (700, 600, 500, 400, 300) for st in (6, 12, 18, 24)
    }
    assert len(low) + len(high) == 8 * 4  # 32 messages per variable, 96 per entry
    with pytest.raises(ValueError, match="no messages"):
        fc.select_ivt_fields(fields, "SPFH", False, 2)  # the fixture stops at 30 h


def test_family_and_url_and_merge():
    assert fc.ivt_family("SPFH", 1000) == "spfh_pres" and fc.ivt_family("SPFH", 850) == "spfh_pres"
    assert fc.ivt_family("UGRD", 700) == "ugrd_pres_abv700mb"
    assert fc.ivt_family("VGRD", 300) == "vgrd_pres_abv700mb"
    url = fc.gefs_ivt_url(pd.Timestamp("2010-07-01"), "c00", "spfh_pres_abv700mb")
    assert url.endswith(
        "/GEFSv12/reforecast/2010/2010070100/c00/Days:1-10/spfh_pres_abv700mb_2010070100_c00.grib2"
    )
    high = fc.select_ivt_fields(fc.parse_pres_idx(make_idx("SPFH", ABV_LEVELS)), "SPFH", True, 1)
    merged = fc.merge_ranges(high)
    # 700..300 are byte-adjacent per step: one request per step instead of five
    assert len(merged) == 4 and all(len(g) == 5 for _, _, g in merged)
    assert merged[0][0] == high[0].start
    low = fc.select_ivt_fields(fc.parse_pres_idx(make_idx("SPFH", BASE_LEVELS)), "SPFH", False, 1)
    assert len(fc.merge_ranges(low)) == len(low)  # 1000, 925, 850 are not adjacent


def test_fetch_ivt_selects_messages_and_integrates(monkeypatch):
    """HttpFetcher.fetch_ivt with fake idx/ranges/decoder: right messages, right integral."""
    idx = {}
    for var in fc.IVT_VARS:
        idx[fc.ivt_family(var, 1000)] = make_idx(var, BASE_LEVELS, range(3, 49, 3))
        idx[fc.ivt_family(var, 300)] = make_idx(var, ABV_LEVELS, range(3, 49, 3))
    fetcher = fc.HttpFetcher(grid=fc.F51_GRID)
    asked = []

    def fake_text_url(url):
        name = url.rsplit("/", 1)[1]
        return idx[name.split("_2010070100")[0]]

    def fake_get(url, byte_range=None):
        family = url.rsplit("/", 1)[1].split("_2010070100")[0]
        lo, hi = byte_range
        asked.append((family, lo, hi))
        fields = fc.parse_pres_idx(idx[family])
        hit = [f for f in fields if lo <= f.start and (hi is None or f.start <= hi)]
        return ";".join(f"{f.var}|{f.level}|{f.step}" for f in hit).encode()

    def fake_grib_fields(blob, area):
        out = []
        for tok in blob.decode().split(";"):
            var, _lv, st = tok.split("|")
            val = {"SPFH": 0.004, "UGRD": 6.0, "VGRD": 8.0}[var]
            field = xr.DataArray(
                np.full((len(fc.F51_GRID.lat), len(fc.F51_GRID.lon)), val),
                dims=("lat", "lon"),
                coords={"lat": fc.F51_GRID.lat, "lon": fc.F51_GRID.lon},
            )
            out.append(({"shortName": fc.IVT_SHORT[var], "step": int(st)}, field))
        return out

    monkeypatch.setattr(fetcher, "_text", lambda url: fake_text_url(url))
    monkeypatch.setattr(fetcher, "_get", fake_get)
    monkeypatch.setattr(fc, "grib_fields", fake_grib_fields)
    arr = fetcher.fetch_ivt(pd.Timestamp("2010-07-01"), 2, "c00")
    assert arr.shape == (21, 15) and arr.dtype == np.float32
    np.testing.assert_allclose(arr, 0.004 * 10.0 * 70000 / G, rtol=1e-5)
    # 3 variables x (3 isolated levels + 1 merged group) x 4 steps = 48 byte-range reads
    assert len(asked) == 3 * 4 * 4
    # nothing outside steps 30, 36, 42, 48 is requested
    ranges = {(f, lo) for f, lo, _ in asked}
    for family, lo in ranges:
        [hit] = [f for f in fc.parse_pres_idx(idx[family]) if f.start == lo]
        assert hit.step in (30, 36, 42, 48)


# --- store -------------------------------------------------------------------------------------


class IvtFetcher:
    def __init__(self, missing=(), fail=()):
        self.calls = []
        self.missing, self.fail = set(missing), set(fail)

    def fetch_ivt(self, init, lead, member):
        self.calls.append((init, lead, member))
        key = (init.strftime("%Y%m%d"), lead)
        if key in self.missing:
            return None
        if key in self.fail:
            raise fc.FetchError("boom")
        seed = int(init.strftime("%Y%m%d")) * 10 + lead
        return (np.random.default_rng(seed).random((21, 15)) * 500).astype(np.float32)

    def fetch(self, *a, **k):  # must not be used for ivt
        raise AssertionError("precip fetch called")


def make_cases(n: int = 8) -> pd.DataFrame:
    valid = pd.Timestamp("2010-03-01") + pd.to_timedelta(np.arange(n) * 7, "D")
    return pd.DataFrame(
        {
            "case_id": [f"C{i:02d}" for i in range(n)],
            "kind": ["event", "control"] * (n // 2),
            "event_id": ["E"] * n,
            "valid_date": valid,
        }
    )


def test_ivt_store_round_trip_resume_and_combine(tmp_path):
    cases = make_cases(8)
    leads = (1, 5)
    for i in (1, 2):
        path = store.shard_path(tmp_path, SPEC.name, i, 2, "ivt")
        assert path.name == f"gefs-reforecast-ivt.shard-{i}-of-2.zarr"
        res = store.fetch_shard(
            C00, cases.iloc[i - 1 :: 2].reset_index(drop=True), IvtFetcher(), path, leads, 2,
            log_fn=lambda m: None, variable="ivt",
        )  # fmt: skip
        assert res["n_ok"] == 4 * 2 * 1 and res["n_pending"] == 0
    ds = store.read_store(path)
    assert "ivt" in ds and "precip_mm" not in ds
    assert ds["ivt"].dims == ("case", "lead", "member", "lat", "lon")
    assert ds["ivt"].dtype == np.float32 and ds["ivt"].attrs["units"] == "kg m-1 s-1"
    assert list(ds["member"].values) == ["c00"]
    assert ds.attrs["variable"] == "ivt" and ds.attrs["levels_hpa"] == list(fc.IVT_LEVELS)
    assert "24(L-1)+6" in ds.attrs["steps"] and ds.attrs["members"] == ["c00"]
    assert "SPFH" in ds.attrs["source"] and "NODD" in ds.attrs["license"]
    # resuming does not refetch; a different variable on the same path is refused
    again = IvtFetcher()
    store.fetch_shard(C00, cases.iloc[1::2].reset_index(drop=True), again, path, leads, 2,
                      log_fn=lambda m: None, variable="ivt")  # fmt: skip
    assert again.calls == []
    with pytest.raises(ValueError, match="holds ivt"):
        store.fetch_shard(C00, cases.iloc[1::2].reset_index(drop=True), IvtFetcher(), path, leads,
                          2, log_fn=lambda m: None)  # fmt: skip
    out = tmp_path / "gefs-reforecast-ivt.zarr"
    comb = store.combine_shards(C00, tmp_path, out, variable="ivt")
    assert comb.attrs["n_shards"] == 2 and comb.attrs["n_ok"] == 8 * 2
    assert list(comb["case"].values) == list(cases["case_id"])  # ordered by valid date
    ref = IvtFetcher().fetch_ivt(pd.Timestamp(comb["init_date"].values[0, 0]), 1, "c00")
    np.testing.assert_array_equal(comb["ivt"].values[0, 0, 0], ref)
    # the precip combine finds no precip shards next to the ivt ones
    with pytest.raises(FileNotFoundError):
        store.combine_shards(SPEC, tmp_path, tmp_path / "x.zarr")


def test_ivt_store_missing_and_error_status(tmp_path):
    cases = make_cases(4)
    gone = fc.init_date(cases["valid_date"].iloc[0], 1).strftime("%Y%m%d"), 1
    bad = fc.init_date(cases["valid_date"].iloc[1], 5).strftime("%Y%m%d"), 5
    res = store.fetch_shard(
        C00, cases, IvtFetcher(missing=[gone], fail=[bad]), tmp_path / "s.zarr", (1, 5), 2,
        log_fn=lambda m: None, variable="ivt",
    )  # fmt: skip
    assert res["n_missing"] == 1 and res["n_error"] == 1 and res["n_ok"] == 6
    ds = store.read_store(tmp_path / "s.zarr")
    assert np.isnan(ds["ivt"].values[0, 0]).all()


def test_with_members_validation():
    assert store.with_members(SPEC, None) is SPEC
    assert store.with_members(SPEC, ("c00", "p02")).members == ("c00", "p02")
    with pytest.raises(ValueError, match="members"):
        store.with_members(SPEC, ("c00", "p09"))
    with pytest.raises(ValueError, match="variable"):
        store.variable_info("wind")


def test_check_ivt_guard():
    fc.check_ivt(np.full((2, 2), 400.0, dtype=np.float32), "x")
    with pytest.raises(ValueError, match="implausible"):
        fc.check_ivt(np.full((2, 2), 9e4, dtype=np.float32), "x")
    with pytest.raises(ValueError, match="implausible"):
        fc.check_ivt(np.array([[np.nan, 1.0]], dtype=np.float32), "x")


# --- observe -----------------------------------------------------------------------------------


def fake_arco_ivt(stop: str = "2026-06-30"):
    """ARCO-like store: viwve = 3 h, viwvn = 4 h (h = hour index from 2020-01-01), tp = h * 1e-3 m."""
    times = pd.date_range("2020-01-01", "2020-01-10", freq="h")
    lat = np.arange(-30.0, -45.0 - 1e-6, -0.25)
    lon = np.arange(280.0, 300.0 + 1e-6, 0.25)
    h = np.arange(len(times), dtype="float32")[:, None, None]
    shape = (len(times), len(lat), len(lon))
    dims = ("time", "latitude", "longitude")
    mk = lambda a: (dims, np.broadcast_to(a, shape).copy())
    return xr.Dataset(
        {
            "vertical_integral_of_eastward_water_vapour_flux": mk(3.0 * h),
            "vertical_integral_of_northward_water_vapour_flux": mk(4.0 * h),
            "total_precipitation": mk(h * 1e-3),
        },
        coords={"time": times, "latitude": lat, "longitude": lon},
        attrs={"valid_time_stop": stop},
    )


def test_observed_ivt_uses_the_four_forecast_hours():
    ds = observe.observed_days(
        ["2020-01-03", "2020-01-05"], opener=fake_arco_ivt, workers=4, retries=1,
        variables=("ivt",),
    )  # fmt: skip
    assert list(ds.data_vars) == ["ivt"] and ds["ivt"].dtype == np.float32
    assert ds["ivt"].shape == (2, 21, 15) and ds["ivt"].attrs["units"] == "kg m-1 s-1"
    # 2020-01-03 00 UTC is hour index 48: hours 54, 60, 66, 72, |Q| = 5 h -> mean 5 * 63
    np.testing.assert_allclose(ds["ivt"].sel(date="2020-01-03").values, 5 * 63.0, rtol=1e-6)
    np.testing.assert_allclose(ds["ivt"].sel(date="2020-01-05").values, 5 * 111.0, rtol=1e-6)
    assert "06:00" in ds.attrs["ivt_window"] and "eastward_water_vapour" in ds.attrs["variables"]


def test_observed_ivt_magnitude_of_constant_components_and_tp_together():
    raw = fake_arco_ivt()
    raw["vertical_integral_of_eastward_water_vapour_flux"][:] = 300.0
    raw["vertical_integral_of_northward_water_vapour_flux"][:] = -400.0
    ds = observe.observed_days(
        ["2020-01-03"], opener=lambda: raw, workers=4, retries=1, variables=("tp", "ivt")
    )
    np.testing.assert_allclose(ds["ivt"].values, 500.0, rtol=1e-6)  # |(300, -400)|
    assert np.allclose(ds["precip_mm"].sel(date="2020-01-03").values, 1452.0)  # tp path unchanged
    assert set(ds.data_vars) == {"precip_mm", "ivt"}
    only_tp = observe.observed_days(["2020-01-03"], opener=lambda: raw, retries=1)
    assert set(only_tp.data_vars) == {"precip_mm"} and "ivt_window" not in only_tp.attrs
    with pytest.raises(ValueError, match="variables"):
        observe.observed_days(["2020-01-03"], opener=lambda: raw, retries=1, variables=("xx",))


# --- verify_ivt --------------------------------------------------------------------------------

LEADS = (1, 2, 3)


def synth(n: int = 60, seed: int = 0, ivt_noise: float = 0.0, precip_noise: float = 0.0):
    """Stores and obs: events have a strong, controls a weak signal; forecasts = obs + noise."""
    rng = np.random.default_rng(seed)
    cases = make_cases(n)
    cases["valid_date"] = pd.Timestamp("2005-01-01") + pd.to_timedelta(np.arange(n) * 10, "D")
    is_ev = (cases["kind"] == "event").to_numpy()
    strength = np.where(is_ev, rng.uniform(250, 600, n), rng.uniform(10, 150, n))
    shape = np.linspace(0.8, 1.0, 21)[:, None] * np.linspace(0.9, 1.0, 15)[None, :]  # (lat, lon)

    def field(vals):
        return vals[:, None, None] * shape[None]

    obs = xr.Dataset(
        {
            "ivt": (("date", "lat", "lon"), field(strength).astype("float32")),
            "precip_mm": (("date", "lat", "lon"), field(strength / 50).astype("float32")),
        },
        coords={
            "date": cases["valid_date"].to_numpy().astype("datetime64[ns]"),
            "lat": fc.LAT,
            "lon": fc.LON,
        },
        attrs={"source": "ERA5 fake", "window": "w", "ivt_window": "iw", "era5t": False},
    )
    spec5 = store.with_members(SPEC, ("c00", "p01"))
    ivt_ds = store.empty_store(C00, cases, LEADS, variable="ivt")
    pre_ds = store.empty_store(spec5, cases, LEADS)
    for li in range(len(LEADS)):
        ivt_vals = strength * np.exp(rng.normal(0, ivt_noise, n)) if ivt_noise else strength
        pre_vals = strength / 50 * np.exp(rng.normal(0, 1, n) * precip_noise)
        if precip_noise >= 5:  # pure noise
            pre_vals = rng.uniform(0.1, 20, n)
        ivt_ds["ivt"].values[:, li, 0] = field(ivt_vals)
        pre_ds["precip_mm"].values[:, li, 0] = field(pre_vals)
        pre_ds["precip_mm"].values[:, li, 1] = 999.0  # p01 garbage: c00 only must be used
    ivt_ds["status"].values[:] = 0
    pre_ds["status"].values[:] = 0
    ivt_ds.attrs = store.model_attrs(C00, ivt_ds)
    pre_ds.attrs = store.model_attrs(spec5, pre_ds)
    return ivt_ds, pre_ds, obs, cases


def val(df, variable, lead, kind, metric):
    s = df[
        (df["variable"] == variable) & (df["lead"] == lead) & (df["kind"] == kind)
        & (df["metric"] == metric)
    ]  # fmt: skip
    assert len(s) == 1, (variable, lead, kind, metric)
    return s.iloc[0]


def test_perfect_forecast_gives_auc_and_spearman_one():
    ivt_ds, pre_ds, obs, _ = synth()
    df, meta = vi.verify_ivt(ivt_ds, pre_ds, obs, n_boot=50)
    for q in vi.QUANTITIES:
        for lead in LEADS:
            assert val(df, q, lead, "all", "auc")["value"] == 1.0
            assert val(df, q, lead, "all", "spearman")["value"] == pytest.approx(1.0)
            assert val(df, q, lead, "event", "spearman")["value"] == pytest.approx(1.0)
            assert val(df, q, lead, "all", "crpss_rank")["value"] == pytest.approx(1.0)
    r = val(df, "ivt_max", 1, "all", "auc")
    assert r["lo"] == 1.0 and r["hi"] == 1.0 and r["n"] == 60
    assert meta["member"] == "c00" and meta["n_event"] == 30 and meta["n_control"] == 30
    hz = vi.horizons(df)
    assert hz["ivt_max"] == {"auc": 3, "spearman": 3, "both": 3}
    # identical forecasts: the paired difference is exactly zero
    assert val(df, "ivt_max-precip", 2, "all", "d_auc")["value"] == pytest.approx(0.0)
    assert val(df, "ivt_max-precip", 2, "all", "d_spearman")["value"] == pytest.approx(0.0)


def test_paired_difference_sign_and_shared_resamples():
    ivt_ds, pre_ds, obs, _ = synth(n=80, seed=3, precip_noise=9)  # precip forecast is noise
    df, _ = vi.verify_ivt(ivt_ds, pre_ds, obs, n_boot=200, seed=0)
    for lead in LEADS:
        d_auc = val(df, "ivt_max-precip", lead, "all", "d_auc")
        a, b = val(df, "ivt_max", lead, "all", "auc"), val(df, "precip", lead, "all", "auc")
        assert d_auc["value"] == pytest.approx(a["value"] - b["value"])
        assert d_auc["value"] > 0.2 and d_auc["lo"] > 0  # IVT beats noise
        d_sp = val(df, "ivt_max-precip", lead, "all", "d_spearman")
        assert d_sp["value"] > 0.3 and d_sp["lo"] > 0
        assert b["lo"] < 0.5 < b["hi"] or b["lo"] < 0.6  # the noise AUC CI sits near 0.5
    # swapping the roles flips the sign: precip perfect, IVT noise
    ivt2, pre2, obs2, _ = synth(n=80, seed=3)
    ivt2["ivt"].values[:] = np.random.default_rng(1).uniform(1, 600, ivt2["ivt"].shape)
    df2, _ = vi.verify_ivt(ivt2, pre2, obs2, n_boot=100)
    assert val(df2, "ivt_max-precip", 1, "all", "d_auc")["value"] < -0.1
    assert val(df2, "ivt_max-precip", 1, "all", "d_auc")["hi"] < 0
    hz = vi.horizons(df)
    assert hz["ivt_max"]["both"] == 3 and hz["precip"]["both"] < 3


def test_verify_ivt_is_deterministic_and_skips_nan_cases():
    ivt_ds, pre_ds, obs, _ = synth(n=40)
    ivt_ds["status"].values[0, 0, 0] = fc.STATUS_MISSING  # one case drops out of lead 1 only
    a, _ = vi.verify_ivt(ivt_ds, pre_ds, obs, n_boot=30, seed=5)
    b, _ = vi.verify_ivt(ivt_ds, pre_ds, obs, n_boot=30, seed=5)
    pd.testing.assert_frame_equal(a, b)
    assert (
        val(a, "all", 1, "all", "n")["value"] == 39 and val(a, "all", 2, "all", "n")["value"] == 40
    )
    with pytest.raises(ValueError, match="member"):
        vi.verify_ivt(ivt_ds, pre_ds, obs, n_boot=10, member="p07")
    with pytest.raises(ValueError, match="obs needs"):
        vi.verify_ivt(ivt_ds, pre_ds, obs[["precip_mm"]], n_boot=10)


def test_render_md_sections_and_cli(tmp_path):
    ivt_ds, pre_ds, obs, _ = synth(n=40, seed=2, ivt_noise=0.3)
    df, meta = vi.verify_ivt(ivt_ds, pre_ds, obs, n_boot=40)
    md = vi.render_md(df, vi.horizons(df), meta)
    for head in (
        "## Veredicto", "## Fuente y alcance", "## Regla fijada antes de correr", "## Advertencias",
    ):  # fmt: skip
        assert head in md
    assert "<!-- veredicto: lo escribe Opus -->" in md
    for text in ("AUC IVT [IC]", "AUC lluvia [IC]", "Dif. AUC", "CRPSS-rango IVT", "catálogo F1.3",
                 "columna completa", "no un sistema de alerta"):  # fmt: skip
        assert text in md, text
    assert md.count("| 1 |") >= 2
    # CLI end to end on zarr inputs
    store.write_store(ivt_ds, tmp_path / "gefs-reforecast-ivt.zarr")
    store.write_store(pre_ds, tmp_path / "gefs-reforecast.zarr")
    observe.write_obs(obs, tmp_path / "obs.zarr")
    res = CliRunner().invoke(
        app,
        ["hindcast", "verify-ivt", "--ivt", str(tmp_path / "gefs-reforecast-ivt.zarr"),
         "--precip", str(tmp_path / "gefs-reforecast.zarr"), "--obs", str(tmp_path / "obs.zarr"),
         "--out", str(tmp_path / "rep"), "--n-boot", "20"],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    payload = json.loads((tmp_path / "rep" / "F5.10.json").read_text())
    assert set(payload) == {"records", "horizons", "meta"} and payload["records"]
    assert "## Veredicto" in (tmp_path / "rep" / "F5.10.md").read_text()


def test_cli_fetch_validates_variable_and_members(tmp_path):
    cases = tmp_path / "c.parquet"
    cases_mod.write_cases(cases_mod.all_days_cases("2010-07-01", "2010-07-03"), cases, 0)
    base = ["hindcast", "fetch", "--cases", str(cases), "--out", str(tmp_path / "o")]
    run = CliRunner().invoke
    assert run(app, [*base, "--model", "ifs", "--variable", "ivt"]).exit_code != 0
    assert run(app, [*base, "--model", "gefs-reforecast", "--variable", "wind"]).exit_code != 0
    assert run(app, [*base, "--model", "gefs-reforecast", "--variable", "ivt",
                     "--members", "c00,zz"]).exit_code != 0  # fmt: skip
    res = run(app, ["hindcast", "combine", "--model", "gefs-reforecast", "--variable", "ivt",
                    "--in", str(tmp_path), "--out", str(tmp_path / "x")])  # fmt: skip
    assert res.exit_code != 0 and "gefs-reforecast-ivt shards" in res.output.replace("\n", " ")
