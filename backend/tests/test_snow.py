import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import shapely
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import forcing, snow

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


BOX_A = (-38.8, -36.2, -71.2, -70.0)
BOX_B = (-38.0, -37.0, -71.0, -70.5)


def _file_bytes(path):
    return path.read_bytes()


def test_metadata_round_trips_the_boxes_actually_used(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow(
        [(12004, pd.Timestamp("2000-03-10"))], out, boxes={12004: BOX_B}, opener=Opener(), **KW
    )
    assert snow.read_metadata(out)["boxes"] == {12004: BOX_B}
    df = pd.read_parquet(out)
    assert df["lat"].between(BOX_B[0], BOX_B[1]).all()


def test_same_boxes_resume_as_before(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow(
        [(12004, pd.Timestamp("2000-03-10"))], out, boxes={12004: BOX_B}, opener=Opener(), **KW
    )
    snow.fetch_snow(
        [(12004, pd.Timestamp("2000-03-10")), (12004, pd.Timestamp("2000-03-14"))],
        out,
        boxes={12004: BOX_B},
        opener=Opener(),
        **KW,
    )
    assert len(snow.stored_windows(out)) == 2


def test_different_box_for_a_stored_station_is_refused_and_file_unchanged(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, opener=Opener(), **KW)
    before = _file_bytes(out)
    with pytest.raises(ValueError, match="12004") as exc:
        snow.fetch_snow(
            [(12004, pd.Timestamp("2000-03-14"))],
            out,
            boxes={12004: BOX_B},
            opener=Opener(),
            **KW,
        )
    assert "new output file" in str(exc.value)
    assert _file_bytes(out) == before


def test_new_station_with_other_boxes_can_be_appended(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, opener=Opener(), **KW)
    snow.fetch_snow(
        [(12012, pd.Timestamp("2000-03-12"))], out, boxes={12012: BOX_B}, opener=Opener(), **KW
    )
    stored = snow.read_metadata(out)["boxes"]
    assert stored[12004] == snow.UPSTREAM_BOXES[12004] and stored[12012] == BOX_B


def test_file_without_stored_boxes_is_refused_for_appending(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, opener=Opener(), **KW)
    table = pq.read_table(out)
    meta = {k: v for k, v in table.schema.metadata.items() if k != b"boxes"}
    pq.write_table(table.replace_schema_metadata(meta), out)
    assert "boxes" not in snow.read_metadata(out)
    before = _file_bytes(out)
    with pytest.raises(ValueError, match="unknown"):
        snow.fetch_snow([(12004, pd.Timestamp("2000-03-14"))], out, opener=Opener(), **KW)
    assert _file_bytes(out) == before


def test_legacy_boxes_repr_is_still_read(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, opener=Opener(), **KW)
    table = pq.read_table(out)
    meta = {**table.schema.metadata, b"boxes": b"{12004: [-38.8, -36.2, -71.2, -70.0]}"}
    pq.write_table(table.replace_schema_metadata(meta), out)
    assert snow.read_metadata(out)["boxes"] == {12004: BOX_A}


def test_flow_snow_fetch_help_lists_options():
    res = CliRunner().invoke(app, ["flow", "snow-fetch", "--help"], env=PLAIN)
    assert res.exit_code == 0
    for opt in ("--flow-dir", "--catalog", "--out", "--station"):
        assert opt in res.output


# --- basins (HydroBASINS polygons) -------------------------------------------------------------------

POLY_A = shapely.box(-70.9, -37.6, -70.3, -37.1)
POLY_B = shapely.box(-70.8, -37.5, -70.4, -37.2)


def _expected_weights(geom):
    lats = np.arange(-30.0, -45.01, -0.25)
    lons = np.arange(270.0, 300.01, 0.25)
    lon180 = ((lons + 180.0) % 360.0) - 180.0
    ilat, ilon, w = forcing.cell_weights(lats, lon180, geom)
    out = {}
    for a, i in enumerate(ilat):
        for b, j in enumerate(ilon):
            if w[a, b] > 0:
                out[(float(lats[i]), float(lon180[j]))] = float(w[a, b])
    return out


def test_fetch_on_a_polygon_keeps_positive_weight_cells_and_writes_w(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow(
        [(12004, pd.Timestamp("2000-03-10"))], out, basins={12004: POLY_A}, opener=Opener(), **KW
    )
    df = pd.read_parquet(out)
    assert df["w"].dtype == np.float32 and (df["w"] > 0).all()
    expected = _expected_weights(POLY_A)
    day = df[df["date"] == pd.Timestamp("2000-03-03")]
    assert len(day) == len(expected) and len(df) == 10 * len(expected)
    got = {(float(a), float(b)): float(w) for a, b, w in zip(day["lat"], day["lon"], day["w"])}
    assert got.keys() == expected.keys()
    for k, v in expected.items():
        assert got[k] == pytest.approx(v, rel=1e-5)
    assert day["swe_m"].iloc[0] == pytest.approx(0.003)  # same day encoding as on a box
    meta = {k.decode(): v.decode() for k, v in pq.read_schema(out).metadata.items()}
    assert meta["geometry"] == "hydrobasins" and "boxes" not in meta
    assert "rectángulos" not in meta["note"] and "HydroBASINS" in meta["note"]
    assert snow.read_metadata(out)["basins"] == {12004: forcing.basin_digest(POLY_A)}


def test_box_path_has_no_w_column_and_no_basin_metadata(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, opener=Opener(), **KW)
    assert "w" not in pd.read_parquet(out).columns
    meta = snow.read_metadata(out)
    assert "basins" not in meta and "geometry" not in meta and "boxes" in meta


def test_same_basin_resumes_but_other_polygon_or_geometry_kind_is_refused(tmp_path):
    out = tmp_path / "s.parquet"
    kw = {"opener": Opener(), **KW}
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, basins={12004: POLY_A}, **kw)
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-14"))], out, basins={12004: POLY_A}, **kw)
    assert len(snow.stored_windows(out)) == 2
    before = _file_bytes(out)
    later = [(12004, pd.Timestamp("2000-03-18"))]
    with pytest.raises(ValueError, match="differs"):
        snow.fetch_snow(later, out, basins={12004: POLY_B}, **kw)
    with pytest.raises(ValueError, match="stored as a basin"):
        snow.fetch_snow(later, out, **kw)  # a box for a station stored as a basin
    assert _file_bytes(out) == before
    boxed = tmp_path / "b.parquet"
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], boxed, **kw)
    with pytest.raises(ValueError, match="stored as a box"):
        snow.fetch_snow(later, boxed, basins={12004: POLY_A}, **kw)


def test_basin_file_without_digests_is_refused_for_appending(tmp_path):
    out = tmp_path / "s.parquet"
    snow.fetch_snow(
        [(12004, pd.Timestamp("2000-03-10"))], out, basins={12004: POLY_A}, opener=Opener(), **KW
    )
    table = pq.read_table(out)
    meta = {k: v for k, v in table.schema.metadata.items() if k != b"basins"}
    pq.write_table(table.replace_schema_metadata(meta), out)
    with pytest.raises(ValueError, match="unknown"):
        snow.fetch_snow(
            [(12004, pd.Timestamp("2000-03-14"))],
            out,
            basins={12004: POLY_A},
            opener=Opener(),
            **KW,
        )


def test_basin_and_box_stations_can_share_a_file(tmp_path):
    out = tmp_path / "s.parquet"
    kw = {"opener": Opener(), **KW}
    snow.fetch_snow([(12004, pd.Timestamp("2000-03-10"))], out, basins={12004: POLY_A}, **kw)
    snow.fetch_snow([(12012, pd.Timestamp("2000-03-12"))], out, **kw)
    meta = snow.read_metadata(out)
    assert set(meta["basins"]) == {12004} and set(meta["boxes"]) == {12012}
    assert "mixed" in meta["geometry"]


def test_flow_snow_fetch_help_lists_basins_option():
    res = CliRunner().invoke(app, ["flow", "snow-fetch", "--help"], env=PLAIN)
    assert "--basins" in res.output
