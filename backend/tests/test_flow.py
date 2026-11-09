import json
from datetime import date
from itertools import pairwise

import httpx
import numpy as np
import pandas as pd
import pytest

from clima_nqn.io import flow


def med(ms, value, qual=" ", validated=True):
    return {
        "FechaHora": f"/Date({ms})/",
        "Medicion": value,
        "Calificador": qual,
        "Validado": validated,
    }


# 2023-07-01 local midnight (UTC-3) = 03:00 UTC
JUL1 = 1688180400000
DAY = 86_400_000


def test_parse_snih_date_is_local_calendar_date():
    assert flow.parse_snih_date("/Date(1688180400000)/") == date(2023, 7, 1)
    # Alta of Paso de Indios: negative epoch, 1945-01-01 local
    assert flow.parse_snih_date("/Date(-788907600000)/") == date(1945, 1, 1)


def test_build_flow_dedup_nan_and_gap_rows():
    raw = [
        med(JUL1, 10.5, "A"),
        med(JUL1, 99.0),  # duplicate date, dropped (first kept)
        med(JUL1 + DAY, "x"),  # non numeric
        med(JUL1 + 2 * DAY, -3.0),  # negative
        med(JUL1 + 5 * DAY, 7.0, " ", False),  # gap of 2 days in between
    ]
    df = flow.build_flow(raw, flow.STATIONS[0], fetched=date(2026, 11, 9))
    assert list(df.columns) == ["date", "q_m3s", "qualifier", "validated"]
    assert pd.api.types.is_datetime64_dtype(df["date"])
    assert df["q_m3s"].dtype == float
    assert df["validated"].dtype == bool
    assert len(df) == 6
    assert df["date"].tolist() == list(pd.date_range("2023-07-01", periods=6))
    assert df["q_m3s"].iloc[0] == 10.5
    assert df["q_m3s"].iloc[1:5].isna().all()
    assert df["q_m3s"].iloc[5] == 7.0
    assert df["qualifier"].iloc[0] == "A"
    assert df["qualifier"].iloc[5] == ""
    assert df["validated"].tolist() == [True, True, True, False, False, False]
    assert df.attrs["duplicates_dropped"] == 1
    assert df.attrs["source"] == flow.SOURCE
    assert df.attrs["station_id"] == 12004
    assert df.attrs["station_name"] == "Paso de Indios"
    assert df.attrs["river"] == "Neuquén"
    assert df.attrs["fetched"] == "2026-11-09"
    assert df.attrs["url"] == flow.SNIH_URL


def test_parquet_roundtrip_keeps_attrs(tmp_path):
    df = flow.build_flow([med(JUL1, 1.0)], flow.STATIONS[0], fetched=date(2026, 11, 9))
    path = flow.write_flow(df, tmp_path / "12004.parquet")
    back = flow.read_flow(path)
    assert back.attrs["source"] == flow.SOURCE
    assert back.attrs["station_id"] == 12004
    assert back["q_m3s"].tolist() == [1.0]


def test_gap_stats_longest_gap_and_valid_pct():
    q = [1.0, np.nan, np.nan, np.nan, 2.0, np.nan, 3.0, 4.0]
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=8), "q_m3s": q})
    stats = flow.gap_stats(df)
    assert stats["valid_days"] == 4
    assert stats["total_days"] == 8
    assert stats["valid_pct"] == pytest.approx(50.0)
    assert stats["longest_gap_days"] == 3
    assert stats["longest_gap_start"] == date(2020, 1, 2)
    assert stats["longest_gap_end"] == date(2020, 1, 4)


def test_gap_stats_no_gap():
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=3), "q_m3s": [1.0, 2.0, 3.0]})
    stats = flow.gap_stats(df)
    assert stats["longest_gap_days"] == 0
    assert stats["longest_gap_start"] is None


def _year_frame(valid_days: int) -> pd.DataFrame:
    # Hydrological year 2023 = 2023-04-01..2024-03-31 (366 days, leap)
    dates = pd.date_range("2023-04-01", "2024-03-31")
    q = np.full(len(dates), np.nan)
    q[:valid_days] = 5.0
    return pd.DataFrame({"date": dates, "q_m3s": q})


@pytest.mark.parametrize("valid, complete", [(329, False), (330, True)])
def test_hydro_year_completeness_threshold(valid, complete):
    table = flow.hydro_year_completeness(_year_frame(valid), start_month=4)
    assert table["hydro_year"].tolist() == [2023]
    assert table["valid_days"].tolist() == [valid]
    assert table["complete"].tolist() == [complete]


def test_hydro_year_label_is_start_year():
    dates = pd.date_range("2024-01-01", "2024-06-30")
    df = pd.DataFrame({"date": dates, "q_m3s": 1.0})
    table = flow.hydro_year_completeness(df, start_month=4)
    # Jan-Mar 2024 belong to hydro year 2023, Apr-Jun 2024 to 2024
    assert table["hydro_year"].tolist() == [2023, 2024]
    assert table["valid_days"].tolist() == [91, 91]
    assert table["complete"].tolist() == [False, False]


def test_year_windows_cover_without_overlap_or_holes():
    end = date(2026, 11, 9)
    windows = flow.year_windows(1945, end, years=10)
    assert windows[0][0] == date(1945, 1, 1)
    assert windows[-1][1] == end
    for (_, prev_end), (nxt_start, _) in pairwise(windows):
        assert (nxt_start - prev_end).days == 1
    assert all(s <= e for s, e in windows)
    assert len(windows) == 9


def test_year_windows_start_after_end_is_single_short_window():
    assert flow.year_windows(2026, date(2026, 3, 1)) == [(date(2026, 1, 1), date(2026, 3, 1))]


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_window_ok_and_request_body():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"d": {"RespuestaOK": "True", "MsgErr": "", "Mediciones": [med(JUL1, 1.0)]}},
        )

    with _client(handler) as client:
        rows = flow.fetch_window(client, 12004, date(2023, 7, 1), date(2023, 7, 5), retries=1)
    assert rows == [med(JUL1, 1.0)]
    assert seen["body"] == {
        "fechaDesde": "2023-07-01",
        "fechaHasta": "2023-07-05",
        "estacion": 12004,
        "codigo": 101,
        "validados": True,
    }


def test_fetch_window_respuesta_not_ok_raises_with_message():
    def handler(request):
        return httpx.Response(
            200, json={"d": {"RespuestaOK": "False", "MsgErr": "boom", "Mediciones": []}}
        )

    with _client(handler) as client, pytest.raises(RuntimeError, match="boom") as exc:
        flow.fetch_window(client, 12004, date(2023, 7, 1), date(2023, 7, 5), retries=1, sleep=0)
    assert "2023-07-01" in str(exc.value)


def test_fetch_window_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"d": {"RespuestaOK": "True", "Mediciones": []}})

    with _client(handler) as client:
        assert flow.fetch_window(client, 1, date(2020, 1, 1), date(2020, 1, 2), sleep=0) == []
    assert calls["n"] == 3


def test_parse_stations_negates_coords_and_area_sentinel():
    rows = [
        {
            "Codigo": 12004, "Descripcion": "Paso de Indios", "Rio": "Neuquén",
            "Latitud": 38.5, "Longitud": 69.4, "Area": 30843, "Cota": 498.0,
            "MesHidrologico": 4, "Alta": "/Date(-788907600000)/",
        },
        {
            "Codigo": 12013, "Descripcion": "x", "Rio": "Neuquén", "Latitud": 37.0,
            "Longitud": 70.0, "Area": -999, "Cota": 1.0, "MesHidrologico": 4,
            "Alta": "/Date(0)/",
        },
        {"Codigo": 99999, "Descripcion": "other", "Latitud": 1, "Longitud": 1, "Area": 0},
    ]  # fmt: skip
    meta = flow.parse_stations(rows)
    assert set(meta) == {12004, 12013}
    assert meta[12004]["lat"] == -38.5
    assert meta[12004]["lon"] == -69.4
    assert meta[12004]["area_km2"] == 30843
    assert meta[12004]["hydro_year_start_month"] == 4
    assert meta[12004]["alta_year"] == 1945
    assert meta[12013]["area_km2"] is None
    assert flow.area_or_none(0) is None


def test_stations_constant_has_regulated_note():
    ids = {s["id"] for s in flow.STATIONS}
    assert ids == {12004, 12013, 12010, 12012, 11804, 11803}
    notes = {s["id"]: s["note"] for s in flow.STATIONS}
    assert "Alicurá" in notes[11804] and "sin verificar" in notes[11804]
    assert "Alicurá" in notes[11803]
    assert notes[12004] == ""


@pytest.mark.slow
def test_fetch_real_five_day_window():
    with httpx.Client(timeout=60) as client:
        rows = flow.fetch_window(client, 12004, date(2023, 7, 1), date(2023, 7, 5))
    assert len(rows) == 5


def test_ingest_and_report_with_empty_station(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    rows = [
        {
            "Codigo": sid, "Descripcion": "x", "Rio": "r", "Latitud": 38.0, "Longitud": 69.0,
            "Area": -999, "MesHidrologico": 4, "Alta": "/Date(0)/",
        }
        for sid in (12004, 12013)
    ]  # fmt: skip
    (raw_dir / "stations.json").write_text(json.dumps({"fetched": "2026-11-09", "stations": rows}))
    (raw_dir / "12004.json").write_text(json.dumps([med(JUL1, 1.0), med(JUL1 + 3 * DAY, 2.0)]))
    (raw_dir / "12013.json").write_text("[]")
    frames, meta = flow.ingest_flow(raw_dir, tmp_path / "out")
    assert list(frames) == [12004]
    assert (tmp_path / "out" / "12004.parquet").exists()
    assert meta[12004]["first_date"] == "2023-07-01"
    assert meta[12004]["last_date"] == "2023-07-04"
    assert meta[12004]["area_km2"] is None
    assert meta[12013]["first_date"] is None
    out = json.loads((tmp_path / "out" / "stations.json").read_text())
    assert out["fetched"] == "2026-11-09"
    report = flow.build_report(frames, meta)
    assert "Sin datos" in report and "12013" in report
    assert "supuesto" in report and "2026-11-09" in report


def test_partial_fetch_keeps_other_stations_metadata(tmp_path, monkeypatch):
    def station_row(sid):
        return {
            "Codigo": sid,
            "Descripcion": f"S{sid}",
            "Rio": "R",
            "Latitud": 38.0,
            "Longitud": 69.0,
            "Area": 100,
            "Cota": 0,
            "MesHidrologico": 4,
            "Alta": "/Date(0)/",
            "Baja": "/Date(0)/",
        }

    monkeypatch.setattr(
        flow, "fetch_stations", lambda client: [station_row(12004), station_row(12010)]
    )
    monkeypatch.setattr(flow, "fetch_station_series", lambda *a, **k: [])
    flow.fetch_flow(tmp_path, stations=[12004, 12010], today=date(2026, 1, 1), sleep=0)
    flow.fetch_flow(tmp_path, stations=[12004], today=date(2026, 2, 1), sleep=0)
    payload = json.loads((tmp_path / "stations.json").read_text())
    assert sorted(r["Codigo"] for r in payload["stations"]) == [12004, 12010]
    assert payload["fetched_by_station"] == {"12004": "2026-02-01", "12010": "2026-01-01"}
