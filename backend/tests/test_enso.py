import pandas as pd
import pytest

from clima_nqn.io.enso import (
    ONI_URL,
    build_enso,
    classify_phase,
    fetch_oni,
    parse_oni,
    read_enso,
    write_enso,
)

SNIPPET = """SEAS  YR   TOTAL   ANOM
 DJF 1950   24.55  -1.53
 JFM 1950   25.06  -1.34
 NDJ 1950   24.50  -0.97
 DJF 1951   24.60  -0.82
"""


def test_classify_phase_thresholds_inclusive():
    oni = pd.Series([0.5, -0.5, 0.49, -0.49, 0.0, 1.2, -1.3])
    assert classify_phase(oni).tolist() == [
        "nino",
        "nina",
        "neutral",
        "neutral",
        "neutral",
        "nino",
        "nina",
    ]


def test_parse_oni_central_month_and_values():
    df = parse_oni(SNIPPET)
    assert list(df.columns) == ["date", "oni"]
    assert df["date"].tolist() == [
        pd.Timestamp("1950-01-01"),
        pd.Timestamp("1950-02-01"),
        pd.Timestamp("1950-12-01"),
        pd.Timestamp("1951-01-01"),
    ]
    assert df["oni"].tolist() == [-1.53, -1.34, -0.97, -0.82]


def test_build_and_parquet_roundtrip(tmp_path):
    df = build_enso(SNIPPET)
    assert list(df.columns) == ["date", "oni", "phase"]
    assert df["phase"].tolist() == ["nina", "nina", "nina", "nina"]
    path = write_enso(df, tmp_path / "enso" / "oni_monthly.parquet")
    back = read_enso(path)
    pd.testing.assert_frame_equal(back, df, check_dtype=False)
    assert back["phase"].tolist() == df["phase"].tolist()
    assert back.attrs["source"] == "NOAA CPC ONI"
    assert back.attrs["url"] == ONI_URL


@pytest.mark.slow
def test_fetch_real_oni_starts_1950():
    df = parse_oni(fetch_oni())
    assert df["date"].iloc[0] == pd.Timestamp("1950-01-01")
