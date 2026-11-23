"""Daily meteorological forcing per upstream basin for the streamflow models (F2.5).

Usage (from ``backend/``)::

    uv run clima-nqn flow forcing --era5-dir data/raw/era5/neuquen --t2m-dir data/raw/era5/t2m

Inputs are the local per-year ERA5 Zarr stores (``<dir>/<year>.zarr``, hourly, as written by
``era5 fetch``): ``tp`` and ``deg0l`` from the phase-1 run, ``t2m`` from a later ``--variables
2m_temperature`` run. Output is one long Parquet (``station_id``, ``date``, ``precip_mm``,
``deg0l_m``, ``tmean_c``, ``tmin_c``, ``tmax_c``, ``pet_mm``) plus a JSON of static basin attributes.

Box mean: each station box (``snow.UPSTREAM_BOXES``, approximate rectangles, sin verificar) is
averaged over the ERA5 grid cells whose centre lies inside it (edges inclusive, as
``era5._axis_selection``), weighted by cos(latitude).

Daily values are UTC days: ``precip_mm`` for day D sums the hourly ``tp`` of D 01:00 .. D+1 00:00
(``era5.TP_NOTE``; the last hour comes from the next year's store, and a day with fewer than 24
hours is NaN); ``deg0l_m`` and the temperatures use the 24 hours 00..23 of D. Temperatures are the
mean, min and max of the box-mean hourly series.

PET (mm/d) follows Oudin et al. (2005, J. Hydrol. 303, 290-306): ``PET = Re / (lambda rho) *
(T + 5) / 100`` if ``T + 5 > 0`` else 0, with ``T`` the daily mean temperature (degC), ``lambda =
2.45 MJ/kg``, ``rho = 1000 kg/m3`` (Re in MJ/m2/d divided by 2.45 is already mm/d) and ``Re`` the
extraterrestrial radiation from the box-centre latitude and day of year (Allen et al. 1998, FAO-56,
eq. 21).
"""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
import xarray as xr

from clima_nqn.io import basins as basins_io
from clima_nqn.io import dem, era5, flow, snow

DEFAULT_ERA5_DIR = era5.DEFAULT_OUT
DEFAULT_T2M_DIR = Path("data/raw/era5/t2m")
DEFAULT_OUT = flow.OUT_DIR / "forcing.parquet"
PHASE1_RUN_ID = "42437929137"
EARTH_RADIUS_KM = 6371.0088
HIGH_ELEVATION_M = 2000.0
DEM_STEP = 1 / 120  # degrees (~0.9 km); enough for basin-scale statistics
GSC = 0.0820  # solar constant, MJ m-2 min-1 (FAO-56)
LAMBDA_RHO = 2.45  # MJ/kg latent heat of vaporisation (rho = 1000 kg/m3 turns m/d into mm/d x 1000)
COLUMNS = ["station_id", "date", "precip_mm", "deg0l_m", "tmean_c", "tmin_c", "tmax_c", "pet_mm"]
UNITS = "precip_mm: mm/day; deg0l_m: m; tmean_c, tmin_c, tmax_c: degC; pet_mm: mm/day (Oudin et al. 2005)"
DAY_NOTE = "Days are UTC days; the SNIH flow days are local (UTC-3). The offset is not corrected, as in the flood-cause labelling."
BOX_AVERAGE_NOTE = (
    "Box mean over the ERA5 0.25 degree cells whose centre is inside the box (edges included), "
    "weighted by cos(latitude)."
)
BASIN_AVERAGE_NOTE = (
    "Basin mean over the ERA5 0.25 degree cells: weight = cos(latitude) x fraction of the cell "
    "(centred on the grid point, +-0.125 degrees) inside the basin polygon (planar fraction in degrees)."
)
BASIN_NOTE = "cuenca delineada de HydroBASINS nivel 12 (Lehner & Grill 2013) aguas arriba del polígono de la estación"
ERA5_CELL = 0.25  # degrees
STATIC_SUFFIX = ".static.json"

Box = snow.Box


# --- pure helpers ---------------------------------------------------------------------------


def extraterrestrial_radiation(lat_deg: float, doy: np.ndarray | int) -> np.ndarray:
    """Daily extraterrestrial radiation Re (MJ/m2/d), FAO-56 eq. 21 (Allen et al. 1998)."""
    doy = np.asarray(doy, dtype=float)
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * math.pi * doy / 365)
    delta = 0.409 * np.sin(2 * math.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-math.tan(phi) * np.tan(delta), -1.0, 1.0))
    return (
        24 * 60 / math.pi * GSC * dr
        * (ws * math.sin(phi) * np.sin(delta) + math.cos(phi) * np.cos(delta) * np.sin(ws))
    )  # fmt: skip


def oudin_pet(tmean_c: np.ndarray, lat_deg: float, doy: np.ndarray | int) -> np.ndarray:
    """Potential evapotranspiration (mm/d), Oudin et al. (2005); NaN where the temperature is NaN."""
    t = np.asarray(tmean_c, dtype=float)
    re = extraterrestrial_radiation(lat_deg, doy)
    pet = np.where(t + 5 > 0, re / LAMBDA_RHO * (t + 5) / 100, 0.0)
    return np.where(np.isnan(t), np.nan, pet)


def box_cells(lat: np.ndarray, lon: np.ndarray, box: Box) -> tuple[np.ndarray, np.ndarray]:
    """Indices of the cells with centre inside the box (edges included): ``(ilat, ilon)``."""
    south, north, west, east = box
    ilat = era5._axis_selection(np.asarray(lat), south, north)
    ilon = era5._axis_selection(np.asarray(lon), west, east)
    if len(ilat) == 0 or len(ilon) == 0:
        raise ValueError(f"no ERA5 cell has its centre inside the box {list(box)}")
    return ilat, ilon


def box_mean(da: xr.DataArray, box: Box) -> np.ndarray:
    """Hourly cos(lat)-weighted mean over the cells inside the box: a ``time`` series."""
    ilat, ilon = box_cells(da["lat"].values, da["lon"].values, box)
    values = np.asarray(da.isel(lat=ilat, lon=ilon).transpose("time", "lat", "lon").values, float)
    w = np.cos(np.radians(da["lat"].values[ilat]))[None, :, None] * np.ones((1, 1, len(ilon)))
    w = np.broadcast_to(w, values.shape)
    ok = ~np.isnan(values)
    num = np.where(ok, values * w, 0.0).sum(axis=(1, 2))
    den = np.where(ok, w, 0.0).sum(axis=(1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def cell_weights(
    lat: np.ndarray, lon: np.ndarray, geom, cell: float = ERA5_CELL
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ERA5 cell weights over a polygon: ``(ilat, ilon, w)`` of the cells with a positive weight.

    ``w = cos(lat) x`` the fraction of the cell (a square of side ``cell`` centred on the grid point)
    inside ``geom`` (planar intersection area in degrees / cell area). ``ilat`` and ``ilon`` are
    index arrays into the axes and ``w`` has shape ``(len(ilat), len(ilon))``.
    """
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    h = cell / 2
    minx, miny, maxx, maxy = geom.bounds
    ilat = np.flatnonzero((lat + h > miny) & (lat - h < maxy))
    ilon = np.flatnonzero((lon + h > minx) & (lon - h < maxx))
    if len(ilat) == 0 or len(ilon) == 0:
        raise ValueError("the polygon overlaps no ERA5 cell")
    glat, glon = np.meshgrid(lat[ilat], lon[ilon], indexing="ij")
    cells = shapely.box(glon - h, glat - h, glon + h, glat + h)
    frac = shapely.area(shapely.intersection(cells, geom)) / (cell * cell)
    w = np.cos(np.radians(glat)) * np.clip(frac, 0.0, 1.0)
    keep_lat, keep_lon = (w > 0).any(axis=1), (w > 0).any(axis=0)
    if not keep_lat.any():
        raise ValueError("the polygon overlaps no ERA5 cell")
    return ilat[keep_lat], ilon[keep_lon], w[np.ix_(keep_lat, keep_lon)]


def weighted_mean(da: xr.DataArray, ilat, ilon, w: np.ndarray) -> np.ndarray:
    """Hourly weighted mean over the selected cells (NaN cells are left out): a ``time`` series."""
    values = np.asarray(da.isel(lat=ilat, lon=ilon).transpose("time", "lat", "lon").values, float)
    wb = np.broadcast_to(w[None, :, :], values.shape)
    ok = ~np.isnan(values)
    num = np.where(ok, values * wb, 0.0).sum(axis=(1, 2))
    den = np.where(ok, wb, 0.0).sum(axis=(1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


class BoxRegion:
    """Rectangle averaged over the cells whose centre is inside it (the original behaviour)."""

    kind = "box"

    def __init__(self, box: Box):
        self.box = tuple(box)

    @property
    def lat_c(self) -> float:
        return (self.box[0] + self.box[1]) / 2

    def mean(self, da: xr.DataArray) -> np.ndarray:
        return box_mean(da, self.box)


class PolygonRegion:
    """Basin polygon averaged with ``cos(lat) x`` cell fraction weights (:func:`cell_weights`)."""

    kind = "hydrobasins"

    def __init__(self, geom):
        self.geom = geom
        self._cache: dict[tuple, tuple] = {}

    @property
    def lat_c(self) -> float:
        return float(self.geom.centroid.y)

    @property
    def bbox(self) -> Box:
        minx, miny, maxx, maxy = self.geom.bounds
        return (miny, maxy, minx, maxx)

    def weights(self, da: xr.DataArray) -> tuple:
        lat, lon = da["lat"].values, da["lon"].values
        key = (lat.tobytes(), lon.tobytes())
        if key not in self._cache:
            self._cache[key] = cell_weights(lat, lon, self.geom)
        return self._cache[key]

    def mean(self, da: xr.DataArray) -> np.ndarray:
        return weighted_mean(da, *self.weights(da))


Region = BoxRegion | PolygonRegion


def as_region(x) -> Region:
    """A box tuple becomes a :class:`BoxRegion`; a region is returned as it is."""
    return x if isinstance(x, BoxRegion | PolygonRegion) else BoxRegion(x)


def field_mean(da: xr.DataArray, region) -> float:
    """Mean of a 2-D (lat, lon) field over a region (e.g. ERA5 orography in m)."""
    r = as_region(region)
    out = r.mean(da.expand_dims(time=1).transpose("time", "lat", "lon"))
    return float(out[0])


def basin_digest(geom) -> str:
    """Short hash of a basin geometry (rounded to 5 decimals) to detect a changed polygon."""
    rounded = shapely.transform(geom, lambda c: np.round(c, basins_io.COORD_DECIMALS))
    return hashlib.sha1(shapely.to_wkb(rounded)).hexdigest()[:16]


def box_area_km2(box: Box) -> float:
    """Area of a lat/lon rectangle on a sphere (km2)."""
    south, north, west, east = box
    return float(
        EARTH_RADIUS_KM**2
        * math.radians(east - west)
        * (math.sin(math.radians(north)) - math.sin(math.radians(south)))
    )


def _daily(
    values: np.ndarray, times: pd.DatetimeIndex, how: str, shift_hours: int = 0
) -> pd.Series:
    """Aggregate an hourly series by UTC day (``shift_hours`` moves the hours before grouping).

    Days with fewer than 24 hours are NaN.
    """
    s = pd.Series(values, index=times - pd.Timedelta(hours=shift_hours))
    g = s.groupby(s.index.floor("D"))
    out = g.agg(how)
    out[g.count() < 24] = np.nan
    return out


# --- per-year computation -------------------------------------------------------------------


def _open(path: Path) -> xr.Dataset:
    return xr.open_zarr(path, consolidated=False)


def _year_times(era5_dir: Path, year: int) -> pd.DatetimeIndex:
    ds = _open(Path(era5_dir) / f"{year}.zarr")
    return pd.DatetimeIndex(ds["time"].values)


def _hourly(
    store_dir: Path, year: int, var: str, boxes: dict[int, Box | Region], extra_hour: bool
) -> tuple[pd.DatetimeIndex, dict[int, np.ndarray]]:
    """Box-mean hourly series of ``var`` for the year, plus (``extra_hour``) the next 00:00 if stored."""
    store_dir = Path(store_dir)
    parts = [_open(store_dir / f"{year}.zarr")[[var]]]
    nxt = store_dir / f"{year + 1}.zarr"
    if extra_hour and nxt.exists():
        later = _open(nxt)
        if var in later and later["time"].size:
            first = later.isel(time=slice(0, 1))[[var]]
            if pd.Timestamp(first["time"].values[0]) == pd.Timestamp(year + 1, 1, 1):
                parts.append(first)
    ds = xr.concat(parts, dim="time") if len(parts) > 1 else parts[0]
    times = pd.DatetimeIndex(ds["time"].values)
    return times, {sid: as_region(box).mean(ds[var]) for sid, box in boxes.items()}


def year_frame(
    year: int,
    era5_dir: Path,
    t2m_dir: Path | None,
    boxes: dict[int, Box | Region],
) -> tuple[pd.DataFrame, bool]:
    """Daily forcing of every station for one year, and whether temperature was available.

    Each value of ``boxes`` is a box tuple or a :class:`Region` (box or basin polygon).
    """
    era5_dir = Path(era5_dir)
    t_p, tp = _hourly(era5_dir, year, "tp", boxes, extra_hour=True)
    t_z, z = _hourly(era5_dir, year, "deg0l", boxes, extra_hour=False)
    have_t = False
    t_t, t2 = None, {}
    if t2m_dir is not None and (Path(t2m_dir) / f"{year}.zarr").exists():
        ds = _open(Path(t2m_dir) / f"{year}.zarr")
        if "t2m" in ds:
            t_t, t2 = _hourly(Path(t2m_dir), year, "t2m", boxes, extra_hour=False)
            have_t = True
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    frames = []
    for sid, box in boxes.items():
        precip = _daily(tp[sid] * 1000.0, t_p, "sum", shift_hours=1)
        df = pd.DataFrame({"date": days})
        df["precip_mm"] = precip.reindex(days).to_numpy()
        df["deg0l_m"] = _daily(z[sid], t_z, "mean").reindex(days).to_numpy()
        for col, how in (("tmean_c", "mean"), ("tmin_c", "min"), ("tmax_c", "max")):
            if have_t:
                df[col] = _daily(t2[sid] - 273.15, t_t, how).reindex(days).to_numpy()
            else:
                df[col] = np.nan
        lat_c = as_region(box).lat_c
        df["pet_mm"] = oudin_pet(df["tmean_c"].to_numpy(), lat_c, days.day_of_year.to_numpy())
        df.insert(0, "station_id", np.int32(sid))
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    # keep only days the ERA5 store actually covers (a partial last year)
    covered = pd.DatetimeIndex(t_z).floor("D").unique()
    out = out[out["date"].isin(covered)].reset_index(drop=True)
    return out[COLUMNS], have_t


# --- build ----------------------------------------------------------------------------------


def discover_years(era5_dir: Path | str) -> list[int]:
    """Years with a ``<year>.zarr`` store in the directory."""
    years = [int(p.stem) for p in Path(era5_dir).glob("*.zarr") if p.stem.isdigit()]
    return sorted(years)


def _year_done(
    stored: pd.DataFrame,
    year: int,
    sids: Iterable[int],
    ndays: int,
    t_avail: bool,
    next_avail: bool,
) -> bool:
    """Whether the stored rows of the year need no recomputation."""
    sub = stored[stored["date"].dt.year == year]
    for sid in sids:
        rows = sub[sub["station_id"] == sid]
        if len(rows) != ndays:
            return False
        if t_avail and rows["tmean_c"].isna().any():
            return False
        if next_avail and rows["precip_mm"].isna().any():
            return False
    return True


def _meta(
    df: pd.DataFrame,
    boxes: dict[int, Box],
    tp_run: str,
    t2m_run: str | None,
    basin_meta: dict[str, str] | None = None,
) -> dict[str, str]:
    meta = {
        "title": "Daily ERA5 forcing per upstream basin",
        "source": era5.SOURCE,
        "license": era5.LICENSE,
        "tp_deg0l_run_id": tp_run,
        "t2m_run_id": t2m_run or "unknown",
        "units": UNITS,
        "period": f"{df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}",
        "tp_note": era5.TP_NOTE,
        "box_average": BOX_AVERAGE_NOTE,
        "box_note": snow.BOX_NOTE,
        "day_note": DAY_NOTE,
        "pet": "Oudin et al. 2005 with FAO-56 eq. 21 extraterrestrial radiation; 0 where T + 5 <= 0",
        "boxes": json.dumps({str(k): list(v) for k, v in sorted(boxes.items())}),
    }
    if basin_meta:  # basin run: the "boxes" are the polygon bounding boxes
        meta.update(basin_meta)
    return meta


def _basin_meta(
    geoms: dict[int, object], source: str | None, stored: dict[int, str] | None = None
) -> dict[str, str]:
    digests = {**(stored or {}), **{str(k): basin_digest(g) for k, g in geoms.items()}}
    return {
        "region": "hydrobasins",
        "basin_source": source or basins_io.SOURCE,
        "basin_note": basins_io.NOTE,
        "basin_digests": json.dumps(dict(sorted(digests.items()))),
        "box_average": BASIN_AVERAGE_NOTE,
        "box_note": f"boxes are the bounding boxes of the basin polygons; {BASIN_NOTE}",
    }


def stored_digests(path: Path | str) -> dict[str, str] | None:
    """Basin digests recorded in a forcing Parquet, or ``None``."""
    import pyarrow.parquet as pq

    raw = (pq.read_schema(path).metadata or {}).get(b"basin_digests")
    return None if raw is None else json.loads(raw.decode())


def build_forcing(
    era5_dir: Path | str = DEFAULT_ERA5_DIR,
    out_path: Path | str = DEFAULT_OUT,
    t2m_dir: Path | str | None = None,
    t2m_run_id: str | None = None,
    stations: Iterable[int] | None = None,
    boxes: dict[int, Box] = snow.UPSTREAM_BOXES,
    years: Iterable[int] | None = None,
    year_fn: Callable = year_frame,
    progress=print,
    basins: dict[int, object] | None = None,
    basins_source: str | None = None,
) -> dict:
    """Write the forcing Parquet; returns ``{"path", "years", "computed", "missing_t2m_years"}``.

    With ``basins`` (``{station_id: polygon}``) the stations are averaged over the polygons with
    cell-fraction weights instead of the boxes (``boxes`` is then ignored): the file records
    ``region = hydrobasins`` and the polygon bounding boxes as its boxes, so write it to its own
    output file.

    A year already stored for every requested station is skipped, unless temperature or the next
    year's first hour became available since (then it is recomputed). The file is rewritten
    atomically after every year, so an interrupted run keeps what was done.
    """
    era5_dir, out_path = Path(era5_dir), Path(out_path)
    t2m_dir = None if t2m_dir is None else Path(t2m_dir)
    regions: dict[int, Region] | None = None
    if basins is not None:
        regions = {s: PolygonRegion(g) for s, g in basins.items()}
        boxes = {s: r.bbox for s, r in regions.items()}
    chosen = sorted(set(stations)) if stations is not None else sorted(boxes)
    unknown = [s for s in chosen if s not in boxes]
    if unknown:
        what = "basin polygon" if regions is not None else "upstream box"
        raise KeyError(f"no {what} for station(s) {unknown}; valid: {sorted(boxes)}")
    use = {s: boxes[s] for s in chosen}  # boxes as recorded in the file
    run = use if regions is None else {s: regions[s] for s in chosen}  # what year_fn receives
    all_years = sorted(set(years)) if years is not None else discover_years(era5_dir)
    if not all_years:
        raise FileNotFoundError(f"no <year>.zarr stores in {era5_dir}")

    stored = pd.read_parquet(out_path) if out_path.exists() else None
    if stored is not None:
        recorded = snow.stored_boxes(out_path) or {}
        for sid in set(chosen) & set(stored["station_id"].unique().tolist()):
            if sid not in recorded or tuple(recorded[sid]) != tuple(use[sid]):
                raise ValueError(
                    f"station {sid}: the box recorded in {out_path} differs from the requested one "
                    "(or is unknown). Write to a new output file (--out)."
                )
        if basins is not None:
            old = stored_digests(out_path) or {}
            for sid in set(chosen) & set(stored["station_id"].unique().tolist()):
                if old.get(str(sid)) != basin_digest(basins[sid]):
                    raise ValueError(
                        f"station {sid}: the basin polygon recorded in {out_path} differs from the "
                        "requested one (or is unknown). Write to a new output file (--out)."
                    )
    all_boxes = {**(snow.stored_boxes(out_path) or {} if stored is not None else {}), **use}

    computed, missing_t = [], []
    for year in all_years:
        t_avail = t2m_dir is not None and (t2m_dir / f"{year}.zarr").exists()
        next_avail = (era5_dir / f"{year + 1}.zarr").exists()
        ndays = len(_year_times(era5_dir, year).floor("D").unique())
        if stored is not None and _year_done(stored, year, chosen, ndays, t_avail, next_avail):
            progress(f"{year}: stored")
            if not _has_t(stored, year, chosen):
                missing_t.append(year)
            continue
        frame, have_t = year_fn(year, era5_dir, t2m_dir, run)
        if not have_t:
            missing_t.append(year)
        keep = (
            stored[~((stored["date"].dt.year == year) & stored["station_id"].isin(chosen))]
            if stored is not None
            else None
        )
        stored = frame if keep is None else pd.concat([keep, frame], ignore_index=True)
        stored = stored.sort_values(["station_id", "date"], ignore_index=True)
        stored["station_id"] = stored["station_id"].astype("int32")
        basin_meta = (
            None
            if basins is None
            else _basin_meta(
                {s: basins[s] for s in chosen},
                basins_source,
                stored_digests(out_path) if out_path.exists() else None,
            )
        )
        snow._write(
            stored,
            out_path,
            _meta(stored, {s: b for s, b in all_boxes.items() if s in set(stored["station_id"])},
                  PHASE1_RUN_ID, t2m_run_id, basin_meta),
        )  # fmt: skip
        computed.append(year)
        progress(f"{year}: computed" + ("" if have_t else " (no temperature)"))
    return {
        "path": out_path,
        "years": all_years,
        "computed": computed,
        "missing_t2m_years": sorted(missing_t),
    }


def _has_t(stored: pd.DataFrame, year: int, sids: Iterable[int]) -> bool:
    sub = stored[(stored["date"].dt.year == year) & stored["station_id"].isin(list(sids))]
    return bool(len(sub)) and not sub["tmean_c"].isna().all()


def read_forcing(path: Path | str) -> pd.DataFrame:
    """The long table written by :func:`build_forcing`."""
    return pd.read_parquet(path)


# --- static attributes ----------------------------------------------------------------------


def _dem_points(
    dem_dir: Path | str, box: Box, step: float, what: str, geom=None
) -> np.ndarray | None:
    """GLO-30 cells ``(lon, lat, elev)`` inside the box decimated to ``step`` degrees, or ``None``
    (with a warning) if a tile is missing or no cell falls inside the box. With ``geom`` (a basin
    polygon) only the cells inside the polygon are kept (``box`` is then its bounding box)."""
    import rasterio

    south, north, west, east = box
    chunks = []
    for lat, lon in dem.tiles_for_bbox((west, south, east, north)):
        if geom is not None and not shapely.intersects(
            geom, shapely.box(lon, lat, lon + 1, lat + 1)
        ):
            continue  # the polygon does not reach this tile of its bounding box
        path = Path(dem_dir) / f"{dem.tile_name(lat, lon)}.tif"
        if not path.exists():
            if dem._absent_marker(path).exists():
                continue
            warnings.warn(f"missing DEM tile {path}: {what} are NaN", stacklevel=3)
            return None
        with rasterio.open(path) as ds:
            chunks.append(dem.clip_bbox(dem.decimate_tile(ds, step), (west, south, east, north)))
    pts = np.concatenate(chunks) if chunks else np.empty((0, 3), dtype=np.float32)
    if geom is not None and len(pts):
        pts = pts[shapely.contains_xy(geom, pts[:, 0].astype(float), pts[:, 1].astype(float))]
    if len(pts) == 0:
        warnings.warn(
            f"no DEM cells inside the {'basin' if geom is not None else 'box'} {list(box)}",
            stacklevel=3,
        )
        return None
    return pts


def dem_stats(dem_dir: Path | str, box: Box, step: float = DEM_STEP, geom=None) -> dict[str, float]:
    """Mean/min/max elevation (m) and fraction of area above 2000 m over the box, from GLO-30.

    Cells are the DEM raster decimated to ``step`` degrees, weighted by cos(latitude). If a tile is
    missing the values are NaN and a warning is issued (the statistics would be biased).
    """
    nan = {"elev_mean_m": math.nan, "elev_min_m": math.nan, "elev_max_m": math.nan,
           "frac_above_2000m": math.nan}  # fmt: skip
    pts = _dem_points(dem_dir, box, step, "elevation statistics", geom)
    if pts is None:
        return nan
    w = np.cos(np.radians(pts[:, 1].astype(float)))
    elev = pts[:, 2].astype(float)
    return {
        "elev_mean_m": float(np.average(elev, weights=w)),
        "elev_min_m": float(elev.min()),
        "elev_max_m": float(elev.max()),
        "frac_above_2000m": float(np.average(elev > HIGH_ELEVATION_M, weights=w)),
    }


def weighted_quantiles(values: np.ndarray, weights: np.ndarray, probs: np.ndarray) -> np.ndarray:
    """Weighted quantiles (Hazen-type): the sorted value ``i`` sits at ``(cum_w_i - w_i / 2) / sum(w)``
    and quantiles are linearly interpolated, clamped to the minimum and the maximum."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    order = np.argsort(v, kind="stable")
    v, w = v[order], w[order]
    pos = (np.cumsum(w) - 0.5 * w) / w.sum()
    return np.interp(np.asarray(probs, dtype=float), pos, v)


def dem_hypsometry(dem_dir: Path | str, box: Box, step: float = DEM_STEP, geom=None) -> np.ndarray:
    """Hypsometric curve of the box: 101 elevations (m) at the 0, 1, ..., 100 % area quantiles.

    Same GLO-30 cells and cos(latitude) weights as :func:`dem_stats`. The box is an approximate
    rectangle, not the basin (sin verificar). NaN array and a warning if a tile is missing.
    """
    pts = _dem_points(dem_dir, box, step, "the hypsometric curve", geom)
    if pts is None:
        return np.full(101, np.nan)
    w = np.cos(np.radians(pts[:, 1].astype(float)))
    return weighted_quantiles(pts[:, 2].astype(float), w, np.linspace(0.0, 1.0, 101))


def static_path(out_path: Path | str) -> Path:
    out_path = Path(out_path)
    return out_path.with_name(out_path.stem + STATIC_SUFFIX)


def _hypso_json(dem_dir, box: Box, step: float, geom=None) -> list[float] | None:
    h = dem_hypsometry(dem_dir, box, step, geom)
    return None if np.isnan(h).any() else [float(v) for v in h]


def build_static(
    out_path: Path | str,
    dem_dir: Path | str = dem.RAW_DIR,
    stations: Iterable[int] | None = None,
    boxes: dict[int, Box] = snow.UPSTREAM_BOXES,
    step: float = DEM_STEP,
    basins: dict[int, object] | None = None,
    basins_source: str | None = None,
    orog: xr.DataArray | None = None,
) -> Path:
    """Write the static attributes JSON next to the Parquet (reuses stations already computed).

    With ``basins`` the attributes are those of the polygons: ``area_km2`` is the geodesic polygon
    area, the centroid is the polygon centroid, ``box`` its bounding box and the DEM statistics and
    ``hypso_m`` use only the GLO-30 cells inside the polygon. ``orog`` (optional, a 2-D ``lat`` x
    ``lon`` ERA5 orography DataArray in m) adds ``era5_orog_m``, the region mean with the forcing
    weights; without it a stored value is kept.
    """
    path = static_path(out_path)
    regions: dict[int, Region] = (
        {s: PolygonRegion(g) for s, g in basins.items()}
        if basins is not None
        else {s: BoxRegion(b) for s, b in boxes.items()}
    )
    chosen = sorted(set(stations)) if stations is not None else sorted(regions)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stored = dict(old.get("basins", {}))
    out = dict(stored)
    for sid in chosen:
        prev = stored.get(str(sid))
        reg = regions[sid]
        box = reg.bbox if basins is not None else reg.box
        geom = reg.geom if basins is not None else None
        digest = basin_digest(geom) if geom is not None else None
        same = (
            bool(prev)
            and prev["box"] == list(box)
            and prev.get("elev_mean_m") is not None
            and prev.get("basin_digest") == digest
        )
        orog_m = None if orog is None else field_mean(orog, reg)
        if same and prev.get("hypso_m") is not None:
            out[str(sid)] = prev if orog_m is None else {**prev, "era5_orog_m": orog_m}
            continue
        if same:  # keep every field (also unknown ones, e.g. era5_orog_m) and add the curve
            out[str(sid)] = {**prev, "hypso_m": _hypso_json(dem_dir, box, step, geom)}
            if orog_m is not None:
                out[str(sid)]["era5_orog_m"] = orog_m
            continue
        keep = (
            prev
            if prev and prev.get("box") == list(box) and prev.get("basin_digest") == digest
            else {}
        )
        entry = {
            **keep,
            "box": list(box),
            "area_km2": basins_io.area_km2(geom) if geom is not None else box_area_km2(box),
            "centroid_lat": float(geom.centroid.y) if geom is not None else (box[0] + box[1]) / 2,
            "centroid_lon": float(geom.centroid.x) if geom is not None else (box[2] + box[3]) / 2,
            **{
                k: (None if math.isnan(v) else v)
                for k, v in dem_stats(dem_dir, box, step, geom).items()
            },
            "hypso_m": _hypso_json(dem_dir, box, step, geom),
        }
        if geom is not None:
            entry["region"] = "hydrobasins"
            entry["basin_digest"] = digest
        if orog_m is not None:
            entry["era5_orog_m"] = orog_m
        out[str(sid)] = entry
    if basins is not None:
        doc = {
            "title": "Static attributes of the gauge basins (HydroBASINS)",
            "region": "hydrobasins",
            "source": f"{basins_source or basins_io.SOURCE}; elevation: {dem.SOURCE}; forcing: {era5.SOURCE}",
            "license": f"{era5.LICENSE} (ERA5); {dem.LICENSE}; HydroSHEDS licence (HydroBASINS)",
            "units": "area_km2: km2 (polygon, spherical equal-area); elev_*_m: m; hypso_m: 101 elevations "
            "(m) at the 0..100 % cos(lat)-weighted area quantiles of the polygon; frac_above_2000m: "
            "0..1; centroid: degrees (polygon centroid); box: polygon bounding box (S, N, W, E)",
            "box_note": BASIN_NOTE,
            "basin_note": basins_io.NOTE,
            "elevation_note": f"cos(lat)-weighted over the GLO-30 raster decimated to {step:.5f} degrees, "
            "cells inside the polygon",
            "basins": out,
        }
    else:
        doc = {
            "title": "Static attributes of the upstream basins",
            "source": f"{snow.BOX_NOTE}; elevation: {dem.SOURCE}; forcing: {era5.SOURCE}",
            "license": f"{era5.LICENSE} (ERA5); {dem.LICENSE}",
            "units": "area_km2: km2 (spherical rectangle); elev_*_m: m; hypso_m: 101 elevations (m) at the "
            "0..100 % cos(lat)-weighted area quantiles of the box; frac_above_2000m: 0..1; "
            "centroid: degrees (box centre)",
            "box_note": snow.BOX_NOTE,
            "elevation_note": f"cos(lat)-weighted over the GLO-30 raster decimated to {step:.5f} degrees",
            "basins": out,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    tmp.replace(path)
    return path
