import gzip
from pathlib import Path

import pandas as pd

from clima_nqn.io import isd


def make_line(stamp: str, groups: str, report_type: str = "FM-12", tail: str = "") -> str:
    """Fixed-width ISD record: control section (60) + mandatory section (45), then ADD + groups."""
    head = "0000" + "877150" + "99999" + stamp  # stamp = YYYYMMDDHHMM
    head += "0" * (41 - len(head)) + report_type.ljust(5)
    head += "0" * (105 - len(head))
    return head + "ADD" + groups + tail


def grp(slot: int, period: int, tenths: int, cond: str, qc: str) -> str:
    return f"AA{slot}{period:02d}{tenths:04d}{cond}{qc}"


def test_parse_aa_groups_basic():
    line = make_line("201404071200", "AA106054031AA224118031AY161021")
    got = isd.parse_line(line)
    assert [(a.slot, a.period_h, a.depth_mm, a.condition, a.quality) for a in got] == [
        (1, 6, 54.0, "3", "1"),
        (2, 24, 118.0, "3", "1"),
    ]
    assert got[0].time == pd.Timestamp("2014-04-07 12:00")
    assert got[0].report_type == "FM-12"


def test_parse_missing_depth_and_period():
    got = isd.parse_line(make_line("200001010000", f"{grp(1, 6, 9999, '9', '1')}AA3{99}{9999}91"))
    assert got[0].depth_mm is None and got[0].period_h == 6
    assert got[1].depth_mm is None and got[1].period_h == -1  # period 99 = missing


def test_parse_ignores_sections_after_rem_and_lines_without_add():
    assert isd.parse_line(make_line("201404071200", "", tail="REMSYN AA124010011")) == []
    plain = make_line("201404071200", "")[:105] + "REMSYN"
    assert isd.parse_line(plain) == []
    assert isd.parse_line("") == []


def test_bad_qc_and_condition_are_dropped_by_admissible():
    lines = [
        make_line("201401011200", grp(1, 24, 120, "9", "1")),  # good
        make_line("201401021200", grp(1, 24, 120, "9", "2")),  # suspect
        make_line("201401031200", grp(1, 24, 120, "9", "3")),  # erroneous
        make_line("201401041200", grp(1, 24, 120, "9", "9")),  # missing flag
        make_line("201401051200", grp(1, 24, 9999, "9", "1")),  # missing depth
        make_line(
            "201401061200", grp(1, 24, 120, "1", "1")
        ),  # condition 1 (measurement impossible)
        make_line("201401071200", grp(1, 24, 0, "2", "1")),  # trace
        make_line("201401081200", grp(1, 24, 120, "9", "5")),  # passed all (NCEI source)
        make_line("201401091200", grp(1, 12, 120, "9", "1")),  # period 12 is not wanted
    ]
    groups = pd.DataFrame(a.__dict__ for a in isd.parse_lines(lines))
    kept = isd.admissible(groups)
    assert sorted(kept["time"].dt.day) == [1, 7, 8]
    assert kept.loc[kept["time"].dt.day == 7, "condition"].item() == "2"


def test_dedupe_prefers_synop_and_counts_disagreements():
    lines = [
        make_line("201401011200", grp(1, 24, 120, "9", "1"), report_type="SY-MT"),
        make_line("201401011200", grp(1, 24, 200, "9", "1"), report_type="FM-12"),
        make_line("201401021200", grp(1, 24, 300, "9", "1"), report_type="SY-MT"),
        make_line("201401021200", grp(1, 24, 300, "9", "1"), report_type="FM-15"),
    ]
    groups = pd.DataFrame(a.__dict__ for a in isd.parse_lines(lines))
    one, disagree = isd.dedupe_windows(isd.admissible(groups))
    assert len(one) == 2
    assert disagree == 1
    assert one.loc[one["time"].dt.day == 1, "depth_mm"].item() == 20.0


def test_read_file_and_download_cache(tmp_path: Path):
    path = tmp_path / "877150-99999-2014.gz"
    with gzip.open(path, "wt", encoding="ascii") as fh:
        fh.write(make_line("201404071200", "AA224118031") + "\n")
    assert [a.depth_mm for a in isd.read_file(path)] == [118.0]
    # cached file: download_year returns it without touching the network
    assert isd.download_year(2014, tmp_path) == path
