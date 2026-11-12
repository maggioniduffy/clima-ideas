import itertools
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import flow, snow
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
