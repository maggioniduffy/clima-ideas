import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import snow

PLAIN = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "COLUMNS": "200",
}  # plain, unwrapped help on any runner (CI forces colour)


def make_store(first="2000-02-20", last="2000-03-20 23:00"):
    """ARCO-like ``snow_depth``: 0..360 longitudes, descending latitudes, hourly.

    The value is the day of the month in mm so a day can be read back from a cell.
    """
    lats = np.arange(-30.0, -45.01, -0.25)
    lons = np.arange(270.0, 300.01, 0.25)
    times = pd.date_range(first, last, freq="h")
    day_mm = (times.day.to_numpy() + times.hour.to_numpy() / 100.0) / 1000.0
    data = np.broadcast_to(day_mm[:, None, None], (len(times), len(lats), len(lons)))
    return xr.Dataset(
        {
            "snow_depth": (
                ("time", "latitude", "longitude"),
                data.astype("float32"),
                {"units": "m of water equivalent"},
            ),
            "temperature": (("time", "latitude", "longitude"), data.astype("float32")),
        },
        coords={"time": times, "latitude": lats, "longitude": lons},
    )


class Opener:
    def __init__(self, store=None, fail_first=0):
        self.store = store if store is not None else make_store()
        self.calls = 0
        self.fail_first = fail_first

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise OSError("transient")
        return self.store


KW = {"retry_wait": 0, "workers": 2}


def test_window_days_are_peak_minus_8_to_peak_plus_1():
    days = snow.window_days(pd.Timestamp("2000-03-10"))
    assert len(days) == 10
    assert days[0] == pd.Timestamp("2000-03-02") and days[-1] == pd.Timestamp("2000-03-11")


def test_fetch_writes_expected_days_box_units_and_attributes(tmp_path):
    out = tmp_path / "snow.parquet"
    path = snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, opener=Opener(), **KW)
    assert path == out
    df = pd.read_parquet(out)
    assert set(df.columns) >= {"station_id", "peak", "date", "lat", "lon", "swe_m"}
    assert set(df["station_id"]) == {12004}
    assert sorted(df["date"].unique()) == list(pd.date_range("2000-03-02", "2000-03-11"))
    south, north, west, east = snow.UPSTREAM_BOXES[12004]
    assert df["lat"].between(south, north).all() and df["lon"].between(west, east).all()
    assert df.groupby("date").size().eq(11 * 5).all()  # 0.25 degree cells in the box
    # one snapshot per day at 00 UTC: the fake encodes day-of-month (hour 0 -> no fraction)
    day3 = df[df["date"] == pd.Timestamp("2000-03-03")]
    assert day3["swe_m"].iloc[0] == pytest.approx(0.003)
    meta = {k.decode(): v.decode() for k, v in pq.read_schema(out).metadata.items()}
    assert "Copernicus" in meta["source"] and meta["license"] == "CC-BY 4.0"
    assert meta["units"] == "m of water equivalent" and "snow_depth" in meta["variable"]
    assert meta["period"] == "2000-03-02 to 2000-03-11"
    assert "ERA5-Land" in meta["note"]  # says it is not ERA5-Land


def test_fetch_skips_windows_already_stored(tmp_path):
    out = tmp_path / "snow.parquet"
    first = [(12004, pd.Timestamp("2000-03-10"))]
    snow.fetch_snow(first, out, opener=Opener(), **KW)
    before = pd.read_parquet(out)
    quiet = Opener(fail_first=99)  # any read would fail
    snow.fetch_snow(first, out, opener=quiet, **KW)
    assert quiet.calls == 0  # nothing pending: the store is not even opened
    both = first + [(12012, pd.Timestamp("2000-03-12"))]
    opener = Opener()
    snow.fetch_snow(both, out, opener=opener, **KW)
    after = pd.read_parquet(out)
    assert opener.calls >= 1
    assert set(after["station_id"]) == {12004, 12012}
    old = after[after["station_id"] == 12004].reset_index(drop=True)
    pd.testing.assert_frame_equal(old[before.columns], before.reset_index(drop=True))
    assert after[after["station_id"] == 12012]["date"].min() == pd.Timestamp("2000-03-04")
    assert snow.stored_windows(out) == {
        (12004, pd.Timestamp("2000-03-10")),
        (12012, pd.Timestamp("2000-03-12")),
    }


def test_fetch_retries_transient_open_errors(tmp_path):
    opener = Opener(fail_first=2)
    snow.fetch_snow(
        [(12010, pd.Timestamp("2000-03-10"))], tmp_path / "s.parquet", opener=opener, **KW
    )
    assert opener.calls == 3
    assert len(pd.read_parquet(tmp_path / "s.parquet")) > 0


def test_fetch_failure_keeps_what_was_stored(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, opener=Opener(), **KW)
    short = make_store(last="2000-03-05 23:00")  # the second window is not in the store
    with pytest.raises(Exception):  # noqa: B017 - any read error ends the run
        snow.fetch_snow(
            [(12004, pd.Timestamp("2000-03-10")), (12004, pd.Timestamp("2000-03-14"))],
            out,
            opener=Opener(short),
            retries=2,
            **KW,
        )
    assert snow.stored_windows(out) == {(12004, pd.Timestamp("2000-03-10"))}


def test_unknown_station_has_no_box(tmp_path):
    with pytest.raises(KeyError):
        snow.fetch_snow(
            [(99999, pd.Timestamp("2000-03-10"))], tmp_path / "s.parquet", opener=Opener(), **KW
        )


def test_flow_snow_fetch_help_lists_options():
    res = CliRunner().invoke(app, ["flow", "snow-fetch", "--help"], env=PLAIN)
    assert res.exit_code == 0
    for opt in ("--flow-dir", "--catalog", "--out", "--station"):
        assert opt in res.output
