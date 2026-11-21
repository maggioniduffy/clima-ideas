import pandas as pd
import pytest

from clima_nqn.stages.stations import qc as sq


def groups(rows: list[tuple]) -> pd.DataFrame:
    """rows: (time, period_h, depth_mm, condition, quality, report_type, slot)."""
    cols = ["time", "period_h", "depth_mm", "condition", "quality", "report_type", "slot"]
    df = pd.DataFrame(rows, columns=cols)
    df["time"] = pd.to_datetime(df["time"])
    return df[["time", "report_type", "slot", "period_h", "depth_mm", "condition", "quality"]]


def reasons(df: pd.DataFrame) -> list[str]:
    return [str(r) for r in df["reason"]]


def test_valid_row_kept():
    out = sq.apply_qc(groups([("2020-01-01 12:00", 6, 3.0, "9", "1", "FM-12", 1)]))
    assert reasons(out) == ["ok"] and bool(out.loc[0, "valid"]) and out.loc[0, "value_mm"] == 3.0
    assert out.loc[0, "station"] == "877150-99999" and out.loc[0, "qc_flag"] == "1"


def test_invalid_flag_and_missing_value_are_flagged_not_dropped():
    out = sq.apply_qc(
        groups(
            [
                ("2020-01-01 06:00", 6, 3.0, "9", "2", "FM-12", 1),  # suspect
                ("2020-01-01 12:00", 6, 3.0, "9", "A", "FM-12", 1),  # letter flag
                ("2020-01-01 18:00", 6, None, "9", "1", "FM-12", 1),  # 9999
            ]
        )
    )
    assert reasons(out) == ["qc_flag", "qc_flag", "missing_value"]
    assert not out["valid"].any() and list(out["qc_flag"]) == ["2", "A", "1"]


def test_period_and_condition_rules():
    out = sq.apply_qc(
        groups(
            [
                ("2020-01-01 12:00", 3, 1.0, "9", "1", "FM-12", 1),
                ("2020-01-01 12:00", 6, 1.0, "1", "1", "FM-12", 2),
                ("2020-01-01 18:00", 6, 0.0, "2", "1", "FM-12", 1),  # trace kept
            ]
        )
    )
    assert reasons(out) == ["period_not_used", "condition_code", "ok"]


def test_duplicate_window_prefers_synop():
    out = sq.apply_qc(
        groups(
            [
                ("2020-01-01 12:00", 6, 5.0, "9", "1", "FM-15", 1),
                ("2020-01-01 12:00", 6, 5.0, "9", "1", "FM-12", 2),
                (
                    "2020-01-01 12:00",
                    24,
                    5.0,
                    "9",
                    "1",
                    "FM-12",
                    1,
                ),  # other period: not a duplicate
            ]
        )
    )
    assert reasons(out) == ["duplicate_window", "ok", "ok"]
    assert len(sq.valid_windows(out)) == 2


def test_implausible_and_inconsistent_p24():
    p6 = [("2020-01-02 06:00", 6, 1.0, "9", "1", "FM-12", 1)]
    rows = [
        ("2020-01-02 12:00", 24, 200.0, "9", "1", "FM-12", 1),  # > 150 mm
        ("2020-02-02 12:00", 24, 40.0, "9", "1", "FM-12", 1),  # p6 sum 4 -> inconsistent
        ("2020-03-02 12:00", 24, 10.0, "9", "1", "FM-12", 1),  # p6 sum 10 -> corroborated
        ("2020-04-02 12:00", 24, 10.0, "9", "1", "FM-12", 1),  # no p6 -> unchecked, stays valid
    ]
    p6 += [
        (f"2020-02-{d} {h:02d}:00", 6, 1.0, "9", "1", "FM-12", 1)
        for d, h in ((1, 18), (2, 0), (2, 6), (2, 12))
    ]
    p6 += [
        (f"2020-03-{d} {h:02d}:00", 6, 2.5, "9", "1", "FM-12", 1)
        for d, h in ((1, 18), (2, 0), (2, 6), (2, 12))
    ]
    out = sq.apply_qc(groups(rows + p6))
    p24 = out[out["period_h"] == 24].set_index("time")
    assert list(p24["reason"].astype(str)) == ["implausible", "inconsistent_p6", "ok", "ok"]
    assert list(p24["p24_check"]) == ["implausible", "inconsistent", "corroborated", "unchecked"]
    # screened=False keeps the two screened rows (F3.4 variant C), screened=True drops them
    n24 = lambda df: int((df["period_h"] == 24).sum())
    assert n24(sq.valid_windows(out)) == 2 and n24(sq.valid_windows(out, screened=False)) == 4


def test_gap_summary_counts():
    out = sq.apply_qc(
        groups(
            [
                ("2020-01-01 12:00", 6, 3.0, "9", "1", "FM-12", 1),  # valid day
                ("2020-01-01 18:00", 6, 1.0, "9", "2", "FM-12", 1),  # qc_flag same day
                ("2020-01-02 12:00", 24, 2.0, "9", "1", "FM-12", 1),  # valid p24 day
                ("2020-01-03 12:00", 6, 1.0, "9", "3", "FM-12", 1),  # discarded-only day
                ("2020-02-01 12:00", 6, 0.0, "2", "1", "FM-12", 1),  # valid, February
            ]
        )
    )
    gaps = sq.gap_summary(out, "2020-01-01", "2020-02-02")
    jan = gaps[(gaps["level"] == "month") & (gaps["month"] == 1)].iloc[0]
    assert (jan["days"], jan["days_valid_any"], jan["days_valid_p6"], jan["days_valid_p24"]) == (
        31,
        2,
        1,
        1,
    )
    assert (jan["days_discarded_only"], jan["days_missing"]) == (1, 29)
    assert (jan["n_ok"], jan["n_qc_flag"]) == (2, 2)
    feb = gaps[(gaps["level"] == "month") & (gaps["month"] == 2)].iloc[0]
    assert (feb["days"], feb["days_valid_any"], feb["days_missing"]) == (2, 1, 1)
    yr = gaps[gaps["level"] == "year"].iloc[0]
    assert (yr["days"], yr["days_valid_any"], yr["n_ok"]) == (33, 3, 3)


def test_day_with_only_unused_period_is_discarded_not_missing_only():
    out = sq.apply_qc(
        groups(
            [
                ("2020-01-01 12:00", 6, 3.0, "9", "1", "FM-12", 1),  # valid day
                (
                    "2020-01-02 12:00",
                    3,
                    1.0,
                    "9",
                    "1",
                    "FM-12",
                    1,
                ),  # only a 3 h group: period_not_used
            ]
        )
    )
    gaps = sq.gap_summary(out, "2020-01-01", "2020-01-03")
    jan = gaps[(gaps["level"] == "month") & (gaps["month"] == 1)].iloc[0]
    assert (jan["days_valid_any"], jan["days_discarded_only"], jan["days_missing"]) == (1, 1, 2)
    assert jan["n_period_not_used"] == 1


def test_build_with_empty_raw_dir_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="no ISD precipitation groups"):
        sq.build(tmp_path, years=[2020], out_dir=tmp_path / "out", download=False)
