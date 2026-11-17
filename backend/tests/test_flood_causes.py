import itertools
import json

import numpy as np
import pandas as pd
import pytest
import shapely
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import basins as basins_io
from clima_nqn.io import flow, forcing, snow
from clima_nqn.stages.ar import catalog as ar_catalog
from clima_nqn.stages.flood import causes, extremes

PERIOD = (pd.Timestamp("1999-01-01"), pd.Timestamp("2001-12-31"))

PLAIN = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "COLUMNS": "200",
}  # plain, unwrapped help on any runner (CI forces colour)


def make_events(rows):
    """Catalog frame; ``rows`` = (id, start, end[, deg0l_mean, deg0l_max])."""
    recs = []
    for r in rows:
        recs.append(
            {
                "event_id": r[0],
                "start": pd.Timestamp(r[1]),
                "end": pd.Timestamp(r[2]),
                "deg0l_mean": r[3] if len(r) > 3 else np.nan,
                "deg0l_max": r[4] if len(r) > 4 else np.nan,
            }
        )
    cols = ["event_id", "start", "end", "deg0l_mean", "deg0l_max"]
    return pd.DataFrame(recs, columns=cols)


def write_catalog(path, rows, period):
    ev = make_events(rows)
    full = pd.DataFrame({c: pd.Series(dtype=float) for c in ar_catalog.COLUMNS})
    full = full.astype({"event_id": object, "ivt_max_time": "datetime64[ns]", "enso_phase": object})
    for c in ev.columns:
        full[c] = ev[c]
    for c in ("start", "end"):
        full[c] = pd.to_datetime(full[c])
    full["enso_phase"] = full["enso_phase"].astype(object)
    full.attrs.update(
        period=f"{period[0]:%Y-%m-%d}/{period[1]:%Y-%m-%d}",
        threshold=0.67,
        max_gap_steps=0,
        polygon=[[0, 0]],
    )
    ar_catalog.write_catalog(full, path)
    return path


def daily(start, end, value=10.0, peaks=(), nan_between=None):
    dates = pd.date_range(start, end, freq="D", name="date")
    q = pd.Series(value, index=dates, dtype=float)
    for d, v in peaks:
        q.loc[pd.Timestamp(d)] = v
    if nan_between:
        q.loc[nan_between[0] : nan_between[1]] = np.nan
    return pd.DataFrame({"date": dates, "q_m3s": q.to_numpy()})


# --- AR window rule ------------------------------------------------------------------------------

E1 = make_events([("E1", "2000-03-08 06:00", "2000-03-10 12:00", 3000.0, 3500.0)])


def test_catalog_is_read_with_its_period(tmp_path):
    path = write_catalog(
        tmp_path / "ev.parquet", [("AR-2000-001", "2000-03-08 06:00", "2000-03-10 12:00")], PERIOD
    )
    events, period = causes.load_catalog(path)
    assert period == PERIOD
    assert len(events) == 1


def test_peak_three_days_after_the_last_day_matches_at_w3_not_w2():
    peak = pd.Timestamp("2000-03-13")  # event last day is 03-10
    assert len(causes.matching_events(E1, peak, 3)) == 1
    assert len(causes.matching_events(E1, peak, 2)) == 0


def test_event_that_starts_after_the_peak_does_not_match():
    assert len(causes.matching_events(E1, pd.Timestamp("2000-03-07"), 7)) == 0
    assert len(causes.matching_events(E1, pd.Timestamp("2000-03-08"), 0)) == 1  # active that day


def test_event_ending_at_midnight_is_not_active_that_day():
    ev = make_events([("E", "2000-03-08 06:00", "2000-03-10 00:00")])  # end is exclusive
    assert len(causes.matching_events(ev, pd.Timestamp("2000-03-10"), 0)) == 0
    assert len(causes.matching_events(ev, pd.Timestamp("2000-03-09"), 0)) == 1


# --- sensitivity and chance baseline --------------------------------------------------------------

PEAKS = [
    pd.Timestamp(d) for d in ("2000-03-10", "2000-03-12", "2000-03-13", "2000-03-18", "2000-03-05")
]


def test_sensitivity_shares_are_expected_and_never_decrease():
    rows = causes.sensitivity(PEAKS, E1, PERIOD, n_perm=200, seed=1)
    assert [r["w"] for r in rows] == list(range(8))
    shares = [r["share"] for r in rows]
    assert shares == pytest.approx([0.2, 0.2, 0.4, 0.6, 0.6, 0.6, 0.6, 0.6])
    assert [r["n_ar"] for r in rows] == [1, 1, 2, 3, 3, 3, 3, 3]
    assert all(b >= a for a, b in itertools.pairwise(shares))
    assert all(0 <= r["chance"] <= 1 and 0 < r["p"] <= 1 for r in rows)


def test_chance_share_is_one_when_every_day_has_an_ar_and_zero_when_none():
    always = make_events([("A", "1998-12-01", "2002-02-01")])
    rows = causes.sensitivity(PEAKS, always, PERIOD, n_perm=100, seed=1)
    assert all(r["chance"] == 1.0 and r["share"] == 1.0 for r in rows)
    none = make_events([])
    rows = causes.sensitivity(PEAKS, none, PERIOD, n_perm=100, seed=1)
    assert all(r["chance"] == 0.0 and r["share"] == 0.0 for r in rows)


def test_chance_is_reproducible_with_a_fixed_seed():
    a = causes.sensitivity(PEAKS, E1, PERIOD, n_perm=300, seed=7)
    b = causes.sensitivity(PEAKS, E1, PERIOD, n_perm=300, seed=7)
    assert a == b


def test_chance_draws_stay_in_the_flood_calendar_month():
    # AR only in March of any year -> floods in March are far above chance of a July flood
    ev = make_events([(f"M{y}", f"{y}-03-01", f"{y}-04-01") for y in (1999, 2000, 2001)])
    mar = [pd.Timestamp("2000-03-15")]
    jul = [pd.Timestamp("2000-07-15")]
    assert causes.sensitivity(mar, ev, PERIOD, n_perm=200, seed=3)[3]["chance"] == 1.0
    assert causes.sensitivity(jul, ev, PERIOD, n_perm=200, seed=3)[3]["chance"] == 0.0


# --- floods ---------------------------------------------------------------------------------------


def test_floods_exclude_outside_catalog_period_and_incomplete_years():
    parts = []
    for y in range(1996, 2004):  # hydro years 1996..2003
        kw = {"peaks": [(f"{y}-07-15", 100.0 + y)]}
        if y == 2000:  # incomplete: not enough valid days
            kw["nan_between"] = ("2000-05-01", "2000-12-31")
        parts.append(daily(f"{y}-04-01", f"{y + 1}-03-31", **kw))
    df = pd.concat(parts, ignore_index=True)
    out = causes.select_floods(df, 4, PERIOD)
    assert sorted(out["hydro_year"]) == [1999, 2001]  # 2000 incomplete; 1996-98 and 2002-03 outside
    assert out["date"].min() >= PERIOD[0] and out["date"].max() <= PERIOD[1]


def test_flood_too_close_to_the_period_start_is_excluded():
    # peak 3 days after the catalog start: the w = 7 window would reach before it
    parts = [daily("1998-04-01", "1999-03-31", peaks=[("1999-01-04", 500.0)])]
    out = causes.select_floods(pd.concat(parts, ignore_index=True), 4, PERIOD)
    assert out.empty


# --- snow and labels ------------------------------------------------------------------------------


def cells(date_values, station=12004, peak="2000-03-10"):
    rows = []
    for date, vals in date_values.items():
        for i, v in enumerate(vals):
            rows.append(
                {"station_id": station, "peak": pd.Timestamp(peak), "date": pd.Timestamp(date),
                 "lat": -37.0 - i * 0.25, "lon": -70.5, "swe_m": v}
            )  # fmt: skip
    return pd.DataFrame(rows)


def test_snow_metrics_cover_fraction_and_means():
    snow_df = cells({"2000-03-07": [0.02, 0.02, 0.0, 0.0], "2000-03-10": [0.0, 0.01, 0.0, 0.0]})
    m = causes.snow_metrics(snow_df, 12004, pd.Timestamp("2000-03-10"), 3)
    assert m["status"] == "ok"
    assert m["cover_frac"] == pytest.approx(0.5)
    assert m["swe_start_mm"] == pytest.approx(10.0)
    assert m["swe_peak_mm"] == pytest.approx(2.5)


def test_snow_metrics_cell_at_exactly_10_mm_counts_as_covered():
    snow_df = cells({"2000-03-07": [0.01, 0.0], "2000-03-10": [0.0, 0.0]})
    assert causes.snow_metrics(snow_df, 12004, pd.Timestamp("2000-03-10"), 3)["cover_frac"] == 0.5


def test_snow_metrics_missing_day_or_station_is_sin_dato():
    snow_df = cells({"2000-03-10": [0.01]})  # window start day absent
    assert (
        causes.snow_metrics(snow_df, 12004, pd.Timestamp("2000-03-10"), 3)["status"] == "sin dato"
    )
    assert (
        causes.snow_metrics(snow_df, 12010, pd.Timestamp("2000-03-10"), 0)["status"] == "sin dato"
    )
    assert causes.snow_metrics(None, 12004, pd.Timestamp("2000-03-10"), 3)["status"] == "sin dato"


def snow_state(cover, start, peak):
    return {"status": "ok", "cover_frac": cover, "swe_start_mm": start, "swe_peak_mm": peak}


def test_four_labels():
    melting = snow_state(0.5, 30.0, 10.0)
    assert causes.classify(True, melting)[0] == "río atmosférico + lluvia sobre nieve probable"
    assert causes.classify(True, snow_state(0.1, 30.0, 10.0))[0] == "río atmosférico"  # cover < 0.2
    assert causes.classify(True, snow_state(0.5, 10.0, 30.0))[0] == "río atmosférico"  # SWE grew
    assert causes.classify(True, snow_state(0.5, 30.0, 30.0))[0] == "río atmosférico"  # not lower
    assert causes.classify(False, melting)[0] == "deshielo sin río atmosférico"
    assert causes.classify(False, snow_state(0.1, 30.0, 10.0))[0] == "sin causa identificada"
    assert (
        causes.classify(False, snow_state(0.2, 30.0, 10.0))[0] == "deshielo sin río atmosférico"
    )  # >= 0.2


def test_missing_snow_uses_the_ar_part_only_and_is_flagged():
    sd = {"status": "sin dato"}
    assert causes.classify(True, sd) == ("río atmosférico", True)
    assert causes.classify(False, sd) == ("sin causa identificada", True)
    assert causes.classify(True, snow_state(0.5, 30.0, 10.0))[1] is False


# --- end to end -----------------------------------------------------------------------------------


def write_world(tmp_path, with_gev_json=True):
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir()
    stations = []
    rng = np.random.default_rng(5)
    for sid, first, n in ((12004, 1985, 32), (12012, 1990, 25)):
        parts = []
        for k in range(n):
            y = first + k
            parts.append(
                daily(
                    f"{y}-04-01",
                    f"{y + 1}-03-31",
                    peaks=[(f"{y}-07-15", 100.0 + 20 * rng.random() + k)],
                )
            )
        df = pd.concat(parts, ignore_index=True)
        df.attrs.update({"source": flow.SOURCE, "url": flow.SNIH_URL, "fetched": "2026-11-09"})
        flow.write_flow(df, flow_dir / f"{sid}.parquet")
        stations.append(
            {
                "id": sid,
                "name": f"S{sid}",
                "river": "R",
                "area_km2": None,
                "hydro_year_start_month": 4,
            }
        )
    (flow_dir / "stations.json").write_text(
        json.dumps({"fetched": "2026-11-09", "stations": stations})
    )
    gev_dir = tmp_path / "gev"
    gev_dir.mkdir()
    fit = {"loc": 110.0, "scale": 20.0, "shape_c_scipy": -0.1, "shape_xi": 0.1}
    if with_gev_json:
        (gev_dir / "12004.json").write_text(json.dumps({"gev": fit}))
    # AR on the 13-15 July of the even years 1990..2010
    rows = [
        (f"AR-{y}", f"{y}-07-13 00:00", f"{y}-07-16 00:00", 3100.0, 3600.0)
        for y in range(1990, 2011, 2)
    ]
    catalog = write_catalog(
        tmp_path / "events.parquet", rows, (pd.Timestamp("1990-01-01"), pd.Timestamp("2010-12-31"))
    )
    return flow_dir, gev_dir, catalog, fit


def melting_store():
    """High, falling SWE everywhere: the two snow conditions hold for every flood window."""
    times = pd.date_range("1989-12-01", "2011-01-31", freq="D")
    lats = np.arange(-30.0, -45.01, -0.25)
    lons = np.arange(270.0, 300.01, 0.25)
    # inside a month (flood windows never cross the 15th..25th of July) SWE falls with the day
    swe = 0.060 - 0.0015 * times.day.to_numpy()
    data = np.broadcast_to(swe[:, None, None], (len(times), len(lats), len(lons)))
    return xr.Dataset(
        {"snow_depth": (("time", "latitude", "longitude"), data.astype("float32"),
                        {"units": "m of water equivalent"})},
        coords={"time": times, "latitude": lats, "longitude": lons},
    )  # fmt: skip


def run_causes(tmp_path, snow_path, flow_dir, gev_dir, catalog, extra=()):
    out, report = tmp_path / "causes.json", tmp_path / "F2.3.md"
    res = CliRunner().invoke(
        app,
        ["flow", "causes", "--flow-dir", str(flow_dir), "--gev-dir", str(gev_dir), "--catalog", str(catalog),
         "--snow", str(snow_path), "--out", str(out), "--report", str(report), "--n-perm", "200",
         "--station", "12004", "--station", "12012", *extra],
    )  # fmt: skip
    return res, out, report


def test_cli_causes_without_snow_file_labels_by_ar_only_and_flags_it(tmp_path):
    flow_dir, gev_dir, catalog, _ = write_world(tmp_path)
    res, out, report = run_causes(
        tmp_path, tmp_path / "missing.parquet", flow_dir, gev_dir, catalog
    )
    assert res.exit_code == 0, res.output
    data = json.loads(out.read_text())
    by_id = {s["station_id"]: s for s in data["stations"]}
    floods = by_id[12004]["floods"]
    assert {f["label"] for f in floods} <= {"río atmosférico", "sin causa identificada"}
    assert all(f["snow"]["status"] == "sin dato" and f["snow_missing"] for f in floods)
    text = report.read_text()
    assert "sin dato" in text


def test_cli_causes_report_json_labels_and_statements(tmp_path):
    flow_dir, gev_dir, catalog, fit = write_world(tmp_path)
    snow_path = tmp_path / "snow.parquet"
    store = melting_store()
    floods = causes.collect_floods(
        flow_dir, [12004, 12012], (pd.Timestamp("1990-01-01"), pd.Timestamp("2010-12-31"))
    )
    windows = [(sid, d) for sid, df in floods.items() for d in df["date"]]
    snow.fetch_snow(windows, snow_path, opener=lambda: store, retry_wait=0, workers=2)

    res, out, report = run_causes(tmp_path, snow_path, flow_dir, gev_dir, catalog)
    assert res.exit_code == 0, res.output
    data = json.loads(out.read_text())
    by_id = {s["station_id"]: s for s in data["stations"]}
    s = by_id[12004]
    labels = [f["label"] for f in s["floods"]]
    # AR in even years, snow condition true everywhere
    assert set(labels) == {
        "río atmosférico + lluvia sobre nieve probable",
        "deshielo sin río atmosférico",
    }
    for f in s["floods"]:
        has_ar = int(f["date"][:4]) % 2 == 0
        assert (f["label"].startswith("río atmosférico")) == has_ar
        assert (f["deg0l_mean_m"] is not None) == has_ar  # isotherm reported next to the label
        assert f["snow"]["status"] == "ok" and not f["snow_missing"]
    assert sum(s["label_counts"].values()) == s["n_floods"] == len(s["floods"])
    # GEV period from the JSON of F2.2 when present
    top = max(s["floods"], key=lambda f: f["q_m3s"])
    assert top["gev_T"] == pytest.approx(extremes.gev_return_period(top["q_m3s"], fit))
    # sensitivity w = 0..7 with the chance baseline
    assert [r["w"] for r in s["sensitivity"]] == list(range(8))
    shares = [r["share"] for r in s["sensitivity"]]
    assert shares == sorted(shares)
    # the other station has no GEV JSON: recomputed, and flagged as a short record
    assert by_id[12012]["short_record"] is True and by_id[12004]["short_record"] is False
    assert data["meta"]["catalog_period"] == "1990-01-01/2010-12-31"
    text = report.read_text()
    assert "cuenca aproximada por un rectángulo, sin verificar" in text
    assert "ERA5-Land" in text and "0,25°" in text and "CC-BY 4.0" in text
    assert "registro corto" in text
    assert "ni un sistema de alerta" in text
    assert "cuenca aproximada por un rectángulo, sin verificar" in json.dumps(
        data, ensure_ascii=False
    )


def test_cli_causes_prints_the_snih_consultation_date_per_station(tmp_path):
    flow_dir, gev_dir, catalog, _ = write_world(tmp_path)
    res, out, report = run_causes(tmp_path, tmp_path / "none.parquet", flow_dir, gev_dir, catalog)
    assert res.exit_code == 0, res.output
    by_id = {s["station_id"]: s for s in json.loads(out.read_text())["stations"]}
    assert all(s["fetched"] == "2026-11-09" for s in by_id.values())
    assert by_id[12004]["period"].startswith("1985-04-01/")
    text = report.read_text()
    assert text.count("última consulta: 2026-11-09") == 2  # one per station
    assert "Período con datos: 1985-04-01/" in text


def test_cli_causes_station_without_an_upstream_box_is_a_clean_error_and_writes_nothing(tmp_path):
    flow_dir, gev_dir, catalog, _ = write_world(tmp_path)
    res, out, report = run_causes(
        tmp_path,
        tmp_path / "none.parquet",
        flow_dir,
        gev_dir,
        catalog,
        extra=("--station", "11803"),
    )
    assert res.exit_code != 0
    assert "11803" in res.output and "12004" in res.output and "12010" in res.output
    assert not out.exists() and not report.exists()


def test_cli_snow_fetch_station_without_a_box_is_a_clean_error(tmp_path):
    flow_dir, _, catalog, _ = write_world(tmp_path)
    res = CliRunner().invoke(
        app,
        ["flow", "snow-fetch", "--flow-dir", str(flow_dir), "--catalog", str(catalog),
         "--out", str(tmp_path / "s.parquet"), "--station", "11803"],
    )  # fmt: skip
    assert res.exit_code != 0 and "11803" in res.output
    assert not (tmp_path / "s.parquet").exists()


def test_cli_causes_missing_catalog_is_a_clean_error(tmp_path):
    flow_dir, gev_dir, _, _ = write_world(tmp_path)
    res, _, _ = run_causes(
        tmp_path, tmp_path / "s.parquet", flow_dir, gev_dir, tmp_path / "no.parquet"
    )
    assert res.exit_code != 0 and "catalog" in res.output.lower()


def test_cli_flow_causes_help_lists_options():
    res = CliRunner().invoke(app, ["flow", "causes", "--help"], env=PLAIN)
    assert res.exit_code == 0
    for opt in ("--flow-dir", "--gev-dir", "--catalog", "--snow", "--out", "--report", "--n-perm"):
        assert opt in res.output


def test_existing_flow_gev_help_unchanged():
    res = CliRunner().invoke(app, ["flow", "gev", "--help"], env=PLAIN)
    assert res.exit_code == 0 and "--flow-dir" in res.output and "--station" in res.output
    assert "--catalog" not in res.output and "--snow" not in res.output


# --- basins: weighted snow, sensitivity by w, basin forcing, comparison ---------------------------


def wcells(date_values, weights, station=12004, peak="2000-03-10"):
    """Like ``cells`` plus a weight column ``w`` (one weight per cell)."""
    df = cells(date_values, station, peak)
    df["w"] = [weights[i] for d, vals in date_values.items() for i in range(len(vals))]
    return df


def test_weighted_snow_metrics_hand_computed():
    # start: swe 20, 5, 12, NaN mm with weights 1, 3, 2, 4 -> NaN cell is dropped
    # covered (>= 10 mm): cells 1 and 3 -> (1 + 2) / (1 + 3 + 2) = 0.5
    # mean start = (20*1 + 5*3 + 12*2) / 6 = 59 / 6; peak: 0, 4, 2 mm with the same weights
    df = wcells(
        {"2000-03-07": [0.020, 0.005, 0.012, np.nan], "2000-03-10": [0.0, 0.004, 0.002, 0.050]},
        [1.0, 3.0, 2.0, 4.0],
    )
    m = causes.snow_metrics(df, 12004, pd.Timestamp("2000-03-10"), 3)
    assert m["status"] == "ok" and m["n_cells"] == 3
    assert m["cover_frac"] == pytest.approx(0.5)
    assert m["swe_start_mm"] == pytest.approx(59 / 6)
    # peak mean uses its own non-NaN cells (all four): (0*1 + 4*3 + 2*2 + 50*4) / 10
    assert m["swe_peak_mm"] == pytest.approx(21.6)


def test_weighted_with_equal_weights_matches_the_unweighted_rule():
    vals = {"2000-03-07": [0.02, 0.02, 0.0, 0.0], "2000-03-10": [0.0, 0.01, 0.0, 0.0]}
    a = causes.snow_metrics(cells(vals), 12004, pd.Timestamp("2000-03-10"), 3)
    b = causes.snow_metrics(wcells(vals, [0.7] * 4), 12004, pd.Timestamp("2000-03-10"), 3)
    for k in ("cover_frac", "swe_start_mm", "swe_peak_mm", "n_cells"):
        assert a[k] == pytest.approx(b[k])


def test_unweighted_rule_is_kept_without_w_column():
    df = cells({"2000-03-07": [0.02, 0.0], "2000-03-10": [0.0, 0.0]})
    assert "w" not in df.columns
    m = causes.snow_metrics(df, 12004, pd.Timestamp("2000-03-10"), 3)
    assert m["cover_frac"] == 0.5 and m["swe_start_mm"] == pytest.approx(10.0)


def test_label_sensitivity_counts_ar_and_snow_at_each_w():
    peak = pd.Timestamp("2000-03-10")
    # an event active on 2000-03-08 only: AR at w >= 2. Snow: at w = 0..7 start day = peak - w.
    events = make_events([("AR-1", "2000-03-08 00:00", "2000-03-09 00:00", 3000.0, 3500.0)])
    days = {}
    for w in range(8):
        days[(peak - pd.Timedelta(days=w)).strftime("%Y-%m-%d")] = [0.030, 0.030]
    days["2000-03-10"] = [0.010, 0.010]  # peak: lower than 30 mm on every start day
    df = cells(days)
    out = causes.label_sensitivity([peak], events, df, 12004)
    assert sorted(out) == list(range(8))
    ar_snow, _ar, snow_only, none = causes.LABELS
    for w in range(8):
        counts = out[w]
        assert sum(counts.values()) == 1
        if w == 0:  # no AR, peak day equals start day: SWE not lower -> nothing
            assert counts[none] == 1
        elif w == 1:  # no AR, SWE falls from 30 to 10 mm: melting without AR
            assert counts[snow_only] == 1
        else:
            assert counts[ar_snow] == 1
    # the primary w agrees with the label of the flood
    assert out[causes.W_PRIMARY][ar_snow] == 1


def test_basin_forcing_window_sum_mean_max_and_missing_days():
    peak = pd.Timestamp("2000-03-10")
    days = pd.date_range("2000-03-06", "2000-03-10")
    frame = pd.DataFrame(
        {
            "station_id": 12004,
            "date": days,
            "precip_mm": [1.0, 2.0, 3.0, 4.0, 5.0],
            "deg0l_m": [3000.0, 3100.0, 3200.0, 3400.0, 3300.0],
        }
    )
    got = causes.basin_forcing(frame, 12004, peak)  # [03-07, 03-10]
    assert got["basin_precip_mm"] == pytest.approx(14.0)
    assert got["basin_deg0l_mean_m"] == pytest.approx(3250.0)
    assert got["basin_deg0l_max_m"] == pytest.approx(3400.0)
    assert causes.basin_forcing(frame, 12010, peak) == dict.fromkeys(got)  # other station
    gap = frame[frame["date"] != "2000-03-08"]
    assert causes.basin_forcing(gap, 12004, peak) == dict.fromkeys(got)
    nan = frame.copy()
    nan.loc[nan["date"] == "2000-03-09", "deg0l_m"] = np.nan  # precip still complete
    part = causes.basin_forcing(nan, 12004, peak)
    assert part["basin_deg0l_mean_m"] is None and part["basin_precip_mm"] == pytest.approx(14.0)
    assert causes.basin_forcing(None, 12004, peak)["basin_precip_mm"] is None


def _flood(date, q, label, ar=True, cover=0.5, start=30.0, peak=10.0, events=("E1",)):
    return {
        "date": date,
        "q_m3s": q,
        "ar": ar,
        "events": list(events),
        "label": label,
        "snow": {"status": "ok", "cover_frac": cover, "swe_start_mm": start, "swe_peak_mm": peak},
    }


def _station(sid, floods, sens=None):
    counts = {lab: sum(f["label"] == lab for f in floods) for lab in causes.LABELS}
    return {
        "station_id": sid,
        "name": f"S{sid}",
        "n_floods": len(floods),
        "floods": floods,
        "label_counts": counts,
        "sensitivity": sens or [{"w": 0, "n": len(floods), "n_ar": 1, "share": 0.5, "p": 0.1}],
    }


def test_compare_counts_changes_key_flood_and_ar_identity():
    ar_snow, ar_only = causes.LABELS[0], causes.LABELS[1]
    box = {
        "stations": [
            _station(
                12004,
                [
                    _flood("2023-06-26", 11895.0, ar_snow),
                    _flood("2010-07-01", 900.0, ar_snow),
                    _flood("2005-07-01", 800.0, ar_only, cover=0.1),
                ],
            ),
            _station(12012, [_flood("2001-07-01", 50.0, ar_only, cover=0.1)]),
        ]
    }
    basin = json.loads(json.dumps(box))
    basin["stations"][0]["floods"][1].update(label=ar_only)
    basin["stations"][0]["floods"][1]["snow"].update(cover_frac=0.15, swe_peak_mm=40.0)
    basin["stations"][0]["label_counts"] = {
        lab: sum(f["label"] == lab for f in basin["stations"][0]["floods"]) for lab in causes.LABELS
    }
    res = causes.compare(box, basin)
    s04, s12 = res["stations"]
    assert s04["n_changed"] == 1 and s04["changed"][0]["date"] == "2010-07-01"
    assert (
        s04["changed"][0]["box"]["label"] == ar_snow
        and s04["changed"][0]["basin"]["label"] == ar_only
    )
    assert s04["changed"][0]["basin"]["cover_frac"] == 0.15
    assert s04["label_counts"]["box"][ar_snow] == 2 and s04["label_counts"]["basin"][ar_snow] == 1
    assert s04["ar_identical"] is True and res["all_ar_identical"] is True
    assert s04["key_flood"]["date"] == "2023-06-26" and s04["key_flood"]["changed"] is False
    assert s12["n_changed"] == 0 and s12["key_flood"] is None and not s12["key_flood_expected"]
    assert res["reading_changed"] is True  # AR + snow share moved at 12004
    md = causes.build_comparison(res)
    assert "2010-07-01" in md and "2023-06-26" in md and "idénticos" in md

    # an AR flag that differs breaks ar_identical; so does a different sensitivity table
    basin["stations"][0]["floods"][2]["ar"] = False
    assert causes.compare(box, basin)["stations"][0]["ar_identical"] is False
    other = json.loads(json.dumps(box))
    other["stations"][1]["sensitivity"][0]["p"] = 0.2
    again = causes.compare(box, other)
    assert again["stations"][1]["ar_identical"] is False and again["all_ar_identical"] is False
    same = causes.compare(box, json.loads(json.dumps(box)))
    assert same["reading_changed"] is False and same["stations"][0]["n_changed"] == 0


def test_validate_stations_accepts_basin_stations_only_when_basins_given():
    with pytest.raises(ValueError, match="box"):
        causes.validate_stations([11803])
    assert causes.validate_stations([11803], basins=[11803, 12004]) == [11803]
    with pytest.raises(ValueError, match="basin"):
        causes.validate_stations([12010], basins=[12004])


def _basins_geojson(path):
    def feat(sid, poly):
        return {
            "type": "Feature",
            "properties": {"station_id": sid, "area_km2": 1234.5},
            "geometry": shapely.geometry.mapping(poly),
        }

    doc = {
        "type": "FeatureCollection",
        "source": "HydroBASINS",
        "features": [
            feat(12004, shapely.box(-70.9, -37.6, -70.3, -37.1)),
            feat(12012, shapely.box(-70.6, -36.9, -70.2, -36.7)),
        ],
    }
    path.write_text(json.dumps(doc))
    return path


def test_cli_causes_on_basins_with_forcing_and_comparison(tmp_path):
    flow_dir, gev_dir, catalog, _ = write_world(tmp_path)
    period = (pd.Timestamp("1990-01-01"), pd.Timestamp("2010-12-31"))
    floods = causes.collect_floods(flow_dir, [12004, 12012], period)
    windows = [(sid, d) for sid, df in floods.items() for d in df["date"]]
    store = melting_store()
    box_snow, basin_snow = tmp_path / "box.parquet", tmp_path / "basin.parquet"
    snow.fetch_snow(windows, box_snow, opener=lambda: store, retry_wait=0, workers=2)
    gj = _basins_geojson(tmp_path / "basins.geojson")
    geoms = basins_io.read_geojson(gj)
    snow.fetch_snow(
        windows, basin_snow, basins=geoms, opener=lambda: store, retry_wait=0, workers=2
    )
    days = pd.date_range("1989-12-01", "2011-01-31")
    frame = pd.concat(
        [
            pd.DataFrame(
                {"station_id": sid, "date": days, "precip_mm": 2.0, "deg0l_m": 3000.0 + sid % 7}
            )
            for sid in (12004, 12012)
        ]
    )
    frame_path = tmp_path / "forcing-basins.parquet"
    frame.to_parquet(frame_path)

    res, box_json, _ = run_causes(tmp_path, box_snow, flow_dir, gev_dir, catalog)
    assert res.exit_code == 0, res.output
    out, report = tmp_path / "causes-basins.json", tmp_path / "F2.3-basins.md"
    res = CliRunner().invoke(
        app,
        ["flow", "causes", "--flow-dir", str(flow_dir), "--gev-dir", str(gev_dir), "--catalog", str(catalog),
         "--snow", str(basin_snow), "--out", str(out), "--report", str(report), "--n-perm", "200",
         "--station", "12004", "--station", "12012", "--basins", str(gj), "--forcing", str(frame_path),
         "--compare-with", str(box_json)],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    data = json.loads(out.read_text())
    s = {x["station_id"]: x for x in data["stations"]}[12004]
    assert s["basin"]["kind"] == "hydrobasins" and s["basin"]["area_km2"] == 1234.5
    assert "box" not in s and s["basin"]["digest"] == forcing.basin_digest(geoms[12004])
    f = s["floods"][0]
    assert (
        f["basin_precip_mm"] == pytest.approx(8.0) and f["basin_deg0l_max_m"] == 3000.0 + 12004 % 7
    )
    assert set(s["label_sensitivity"]) == {str(w) for w in range(8)}
    cmp = data["comparison"]
    assert cmp["all_ar_identical"] is True and cmp["reading_changed"] is False  # uniform snow
    text = report.read_text()
    assert (
        "cuenca delineada de HydroBASINS nivel 12 (Lehner & Grill 2013) aguas arriba del polígono"
        in text
    )
    assert "cos(lat)" in text and "rectángulo" not in text.split("## Comparación")[0]
    assert "Sensibilidad de las etiquetas a w" in text and "## Comparación" in text
    assert "Lluvia cuenca" in text

    # a box snow file is refused with --basins, and a basin snow file without it
    bad = CliRunner().invoke(
        app,
        ["flow", "causes", "--flow-dir", str(flow_dir), "--gev-dir", str(gev_dir), "--catalog", str(catalog),
         "--snow", str(box_snow), "--out", str(out), "--report", str(report), "--basins", str(gj),
         "--station", "12004"],
    )  # fmt: skip
    assert bad.exit_code != 0
    res, _, _ = run_causes(tmp_path, basin_snow, flow_dir, gev_dir, catalog)
    assert res.exit_code != 0
