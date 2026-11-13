import json
import zipfile

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from clima_nqn.io import camels_cl

GAUGES = ["1001001", "1020002", "1021001"]
DATES = pd.date_range("1979-12-30", periods=8, freq="D")


def _wide_text(gauges, dates, values, padded_header=False):
    ids = [f" {g}" if padded_header else g for g in gauges]
    lines = ["\t".join(['"gauge_id"', *[f'"{g}"' for g in ids]])]
    for i, d in enumerate(dates):
        cells = []
        for v in values[i]:
            cells.append('" "' if v is None else f'"{v}"')
        lines.append("\t".join([f'"{d:%Y-%m-%d}"', *cells]))
    return "\n".join(lines) + "\n"


def _write_zip(path, inner, text):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(inner, text)


def make_zips(tmp_path, overrides=None):
    """A tiny CAMELS-CL package in the real format (quoted TSV, ' ' = missing)."""
    dates = DATES
    base = {
        "precip_mm": lambda i, j: round(1.0 + i + j, 3),
        "tmin_c": lambda i, j: -2.0 + j,
        "tmax_c": lambda i, j: 8.0 + j,
        "tmean_c": lambda i, j: 3.0 + j,
        "pet_mm": lambda i, j: 0.5 + 0.1 * i,
        "q_mm": lambda i, j: round(0.2 * (j + 1) + 0.01 * i, 3),
    }
    overrides = overrides or {}
    for var, (zname, inner) in camels_cl.ZIP_FILES.items():
        if var == "attributes":
            continue
        fn = base[var]
        vals = [[fn(i, j) for j in range(len(GAUGES))] for i in range(len(dates))]
        vals = overrides.get(var, lambda v: v)(vals)
        _write_zip(tmp_path / zname, inner, _wide_text(GAUGES, dates, vals))
    attrs = {
        "gauge_id": [f" {g}" for g in GAUGES],
        "gauge_name": ["Rio A", "Rio B", "Rio C"],
        "gauge_lat": ["-18.0769", "-18.1936", "-18.5833"],
        "gauge_lon": ["-69.1961", "-69.2458", "-69.0467"],
        "record_period_start": ["1976-07-21", "1964-12-07", "1963-04-11"],
        "n_obs": [" 7288", "15899", "12043"],
        "area": ["   49.71186", "  376.10009", " 3277.98091"],
        "elev_mean": ["4842.4493", "4777.2262", "4493.8555"],
    }
    lines = [f'"{k}"\t' + "\t".join(f'"{x}"' for x in v) for k, v in attrs.items()]
    _write_zip(tmp_path / camels_cl.ZIP_FILES["attributes"][0], "1_CAMELScl_attributes.txt",
               "\n".join(lines) + "\n")  # fmt: skip
    return tmp_path


def test_read_wide_values_nan_and_ids(tmp_path):
    vals = [[1.5, None, 3.0], [2.5, 0.0, None]]
    _write_zip(tmp_path / "x.zip", "x.txt", _wide_text(GAUGES, DATES[:2], vals, padded_header=True))
    wide = camels_cl.read_wide(tmp_path / "x.zip")
    assert list(wide.columns) == GAUGES  # ids stripped
    assert isinstance(wide.index, pd.DatetimeIndex)
    assert wide.loc[DATES[0], "1001001"] == 1.5
    assert np.isnan(wide.loc[DATES[0], "1020002"])
    assert wide.loc[DATES[1], "1020002"] == 0.0
    assert np.isnan(wide.loc[DATES[1], "1021001"])
    assert wide.dtypes.map(lambda t: t == np.float64).all()


def test_read_attributes_transposed_and_stripped(tmp_path):
    make_zips(tmp_path)
    attrs = camels_cl.read_attributes(tmp_path / camels_cl.ZIP_FILES["attributes"][0])
    assert list(attrs.index) == GAUGES
    row = attrs.loc["1001001"]
    assert row["name"] == "Rio A"
    assert row["lat"] == pytest.approx(-18.0769)
    assert row["area_km2"] == pytest.approx(49.71186)
    assert row["elev_mean_m"] == pytest.approx(4842.4493)
    assert row["n_obs"] == 7288


def test_build_camels_tidy_table_and_metadata(tmp_path):
    zdir = tmp_path / "zip"
    zdir.mkdir()
    make_zips(zdir)
    out = tmp_path / "camels.parquet"
    df, _attrs = camels_cl.build_camels(zdir, out)
    assert list(df.columns) == camels_cl.COLUMNS
    # the 1979 dates are before the forcing period start and dropped
    assert df["date"].min() == pd.Timestamp("1980-01-01")
    assert len(df) == len(GAUGES) * (len(DATES) - 2)
    one = df[(df["gauge_id"] == "1020002") & (df["date"] == "1980-01-02")].iloc[0]
    assert one["precip_mm"] == pytest.approx(1.0 + 3 + 1)
    assert one["q_mm"] == pytest.approx(0.4 + 0.03)
    assert one["tmean_c"] == pytest.approx(4.0)
    meta = pq.read_schema(out).metadata
    text = meta[b"source"].decode()
    assert "Alvarez-Garreton" in text and "10.1594/PANGAEA.894885" in text
    assert meta[b"license"].decode() == "CC-BY-4.0"
    assert "CR2MET" in meta[b"forcing"].decode()
    assert "ERA5" in meta[b"forcing_note"].decode()
    static = json.loads(out.with_suffix(".static.json").read_text())
    assert static["basins"]["1001001"]["area_km2"] == pytest.approx(49.71186)
    df2, attrs2 = camels_cl.read_camels(out)
    pd.testing.assert_frame_equal(df, df2)
    assert list(attrs2.index) == GAUGES


def test_build_camels_missing_values_stay_nan(tmp_path):
    def blank(v):
        v[3][1] = None
        return v

    zdir = tmp_path / "zip"
    zdir.mkdir()
    make_zips(zdir, {"q_mm": blank})
    df, _ = camels_cl.build_camels(zdir, tmp_path / "c.parquet")
    row = df[(df["gauge_id"] == "1020002") & (df["date"] == DATES[3])].iloc[0]
    assert np.isnan(row["q_mm"]) and not np.isnan(row["precip_mm"])


def test_unit_check_fails_loudly_on_kelvin(tmp_path):
    zdir = tmp_path / "zip"
    zdir.mkdir()
    make_zips(zdir, {"tmean_c": lambda v: [[x + 273.15 for x in r] for r in v]})
    with pytest.raises(ValueError, match="tmean_c"):
        camels_cl.build_camels(zdir, tmp_path / "c.parquet")


def test_unit_check_fails_on_negative_precip():
    df = pd.DataFrame(
        {
            "gauge_id": ["a"],
            "date": [pd.Timestamp("2000-01-01")],
            "precip_mm": [-3.0],
            "tmin_c": [0.0],
            "tmax_c": [5.0],
            "tmean_c": [2.0],
            "pet_mm": [1.0],
            "q_mm": [1.0],
        }
    )
    with pytest.raises(ValueError, match="precip_mm"):
        camels_cl.check_units(df)


def test_select_basins_needs_ten_years_of_valid_flow():
    dates = pd.date_range("1980-01-01", periods=11 * 365, freq="D")
    rows = []
    for gid, n_valid in (("long", 11 * 365), ("short", 9 * 365), ("gappy", 11 * 365)):
        d = pd.DataFrame({"gauge_id": gid, "date": dates})
        for c in ("precip_mm", "tmin_c", "tmax_c", "tmean_c", "pet_mm"):
            d[c] = 1.0
        d["q_mm"] = 1.0
        d.loc[n_valid:, "q_mm"] = np.nan
        if gid == "gappy":  # forcing missing half of the time: valid pairs fall below 10 years
            d.loc[::2, "precip_mm"] = np.nan
        rows.append(d)
    df = pd.concat(rows, ignore_index=True)
    assert camels_cl.select_basins(df, min_years=10) == ["long"]
