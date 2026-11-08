"""Run the pretrained ClimateNet (CGNet) AR detector and the IVT baseline over one ERA5 year, cropped to Neuquen.

Usage: python run_climatenet.py --year 2023 [--hours 00,06,12,18] --model-dir model/ --repo-dir ClimateNet/ --out out/
       python run_climatenet.py --year 2023 --baseline-only --out out/      (no weights, no torch)

Reads ERA5 from the public ARCO-ERA5 Zarr (anonymous), at the same UTC steps BARD uses:

  ClimateNet field   ARCO-ERA5 variable                 units
  TMQ                total_column_water_vapour          kg m-2
  U850 / V850        u/v_component_of_wind at 850 hPa    m s-1
  PSL                mean_sea_level_pressure            Pa
  baseline           viwve, viwvn (vertical integral of eastward/northward water vapour flux)  kg m-1 s-1

The four model fields are regridded (bilinear, 0.25 deg ERA5 -> 768 x 1152 grid, lat ascending, lon 0..360),
normalised with the config.json statistics, classified in CPU batches, and the AR class (id 2) is cropped to the
Neuquen box. Outputs: climatenet_neuquen_<year>.nc and ivt_threshold_neuquen_<year>.nc (``ar_mask`` uint8 on
time/lat/lon; the baseline also has ``ivt``). torch is imported only when the model runs.
"""

from __future__ import annotations

import argparse
import json
import calendar
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from climatenet_core import (  # noqa: E402
    AR_CLASS,
    FIELDS,
    IVT_THRESHOLD,
    NEUQUEN_BOX,
    crop_box,
    ivt_baseline,
    model_grid,
    normalize_fields,
    regrid_bilinear,
    STATS,
)

ARCO_STORE = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
ARCO_SOURCE = "ERA5 (Copernicus Climate Change Service) via ARCO-ERA5 (Google Cloud public dataset), CC-BY 4.0"
# key -> (ARCO variable, pressure level or None)
MODEL_SOURCE = {
    "TMQ": ("total_column_water_vapour", None),
    "U850": ("u_component_of_wind", 850),
    "V850": ("v_component_of_wind", 850),
    "PSL": ("mean_sea_level_pressure", None),
}
BASELINE_SOURCE = {
    "viwve": ("vertical_integral_of_eastward_water_vapour_flux", None),
    "viwvn": ("vertical_integral_of_northward_water_vapour_flux", None),
}
TIME_UNITS = "hours since 1900-01-01 00:00:00"


def step_times(year: int, hours: list[str]) -> np.ndarray:
    """Every UTC step of ``year`` at ``hours`` (same stamps as tools/teca/fetch_era5_ivt.py)."""
    stamps = [
        f"{year}-{month:02d}-{day:02d}T{h}:00"
        for month in range(1, 13)
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
        for h in hours
    ]
    return np.array(stamps, dtype="datetime64[ns]")


def build_mask_dataset(times, lat, lon, mask, attrs: dict, extra: dict | None = None):
    """Dataset with ``ar_mask`` (uint8, time/lat/lon) plus optional extra float variables ``{name: (array, attrs)}``."""
    import xarray as xr

    data = {"ar_mask": (("time", "lat", "lon"), np.asarray(mask).astype(np.uint8))}
    ds = xr.Dataset(data, coords={"time": np.asarray(times), "lat": lat, "lon": lon})
    for name, (values, var_attrs) in (extra or {}).items():
        ds[name] = (("time", "lat", "lon"), np.asarray(values, dtype=np.float32))
        ds[name].attrs = var_attrs
    ds["ar_mask"].attrs = {"long_name": "atmospheric river mask (1 = AR)", "flag_values": "0 1"}
    ds["lat"].attrs = {"units": "degrees_north", "standard_name": "latitude"}
    ds["lon"].attrs = {"units": "degrees_east", "standard_name": "longitude"}
    ds.attrs = {"Conventions": "CF-1.8", "source": ARCO_SOURCE, **attrs}
    return ds


def write_mask_dataset(ds, path: Path) -> None:
    encoding = {
        "time": {"units": TIME_UNITS, "calendar": "standard", "dtype": "float64"},
        "ar_mask": {"zlib": True, "complevel": 4, "dtype": "uint8"},
    }
    for name in ds.data_vars:
        if name != "ar_mask":
            encoding[name] = {"zlib": True, "complevel": 4, "dtype": "float32"}
    ds.to_netcdf(path, encoding=encoding)


def open_arco():
    import xarray as xr

    return xr.open_zarr(
        ARCO_STORE, consolidated=True, chunks=None, storage_options={"token": "anon"}
    )


def read_step(ds, t, sources: dict) -> dict[str, np.ndarray]:
    """One global (lat, lon) field per source key at time ``t``. Retries transient errors."""
    out = {}
    for key, (var, level) in sources.items():
        for attempt in range(1, 4):
            try:
                da = ds[var].sel(time=t)
                out[key] = (da.sel(level=level) if level is not None else da).values.astype(
                    np.float32
                )
                break
            except Exception as exc:
                print(f"{var} {t} attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
                if attempt == 3:
                    raise
                time.sleep(20 * attempt)
    return out


def load_model(repo_dir: Path, weights: Path):
    """CGNetModule from the ClimateNet checkout on CPU (its high-level CGNet class hard-codes .cuda())."""
    import torch

    sys.path.insert(0, str(repo_dir))
    from climatenet.models import CGNetModule

    from climatenet_core import check_cgnet_state, extract_state_dict

    model = CGNetModule(classes=3, channels=len(FIELDS))
    state = extract_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    try:
        check_cgnet_state(state, set(model.state_dict()), len(FIELDS))
    except ValueError as exc:
        raise SystemExit(f"{weights}: {exc}") from None
    model.load_state_dict(state)
    return model.eval()


def model_inputs(model_dir: Path):
    """Normalisation stats and AR class id from model_dir/config.json (published with the weights); the repo's
    config.json values (climatenet_core.STATS, AR_CLASS) only when no config came with the weights."""
    from climatenet_core import model_inputs_from_config

    cfg_path = model_dir / "config.json"
    if not cfg_path.exists():
        print("no config.json next to the weights: using the repo config.json statistics", flush=True)
        return STATS, AR_CLASS
    try:
        stats, ar_class = model_inputs_from_config(json.loads(cfg_path.read_text()))
    except ValueError as exc:
        raise SystemExit(f"{cfg_path}: {exc}") from None
    print(f"normalisation from {cfg_path}: {stats}; AR class {ar_class}", flush=True)
    return stats, ar_class


def predict_classes(model, x: np.ndarray) -> np.ndarray:
    """Argmax class (uint8, time/lat/lon) of a normalised (time, variable, lat, lon) batch."""
    import torch

    with torch.no_grad():
        logits = model(torch.from_numpy(x))
        return torch.softmax(logits, 1).argmax(1).numpy().astype(np.uint8)


def run(args) -> int:
    hours = [h.strip().zfill(2) for h in args.hours.split(",") if h.strip()]
    times = step_times(args.year, hours)
    if args.max_steps:
        times = times[: args.max_steps]
    args.out.mkdir(parents=True, exist_ok=True)
    ds = open_arco()
    if "level" not in ds.coords or 850 not in ds["level"].values:
        raise SystemExit("ARCO store has no 850 hPa level")
    dst_lat, dst_lon = model_grid(args.nlat, args.nlon)
    model = (
        None if args.baseline_only else load_model(args.repo_dir, args.model_dir / "weights.pth")
    )
    stats, ar_class = (STATS, AR_CLASS) if args.baseline_only else model_inputs(args.model_dir)
    sources = dict(BASELINE_SOURCE) if args.baseline_only else {**MODEL_SOURCE, **BASELINE_SOURCE}

    cn_masks, ivt_masks, ivts = [], [], []
    cn_grid = ivt_grid = None
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(times), args.batch):
            batch = times[start : start + args.batch]
            steps = list(pool.map(lambda t: read_step(ds, t, sources), batch))
            lat = ds["latitude"].values
            lon = ds["longitude"].values
            ivt, hit = ivt_baseline(
                np.stack([s["viwve"] for s in steps]),
                np.stack([s["viwvn"] for s in steps]),
                args.ivt_threshold,
            )
            ivt_c, ivt_lat, ivt_lon = crop_box(ivt, lat, lon, args.area)
            hit_c, _, _ = crop_box(hit, lat, lon, args.area)
            ivt_grid = (ivt_lat, ivt_lon)
            ivts.append(ivt_c)
            ivt_masks.append(hit_c)
            if model is not None:
                fields = {
                    k: regrid_bilinear(np.stack([s[k] for s in steps]), lat, lon, dst_lat, dst_lon)
                    for k in MODEL_SOURCE
                }
                cls = predict_classes(model, normalize_fields(fields, stats))
                ar_c, cn_lat, cn_lon = crop_box(cls == ar_class, dst_lat, dst_lon, args.area)
                cn_grid = (cn_lat, cn_lon)
                cn_masks.append(ar_c)
            done = start + len(batch)
            print(f"{done}/{len(times)} steps, {time.time() - t0:.0f}s", flush=True)

    common = {
        "year": args.year,
        "hours": ",".join(hours),
        "crop_area": ",".join(f"{v:g}" for v in args.area),
    }
    base = build_mask_dataset(
        times, *ivt_grid, np.concatenate(ivt_masks),
        {
            **common,
            "title": "IVT threshold baseline (IVT >= threshold)",
            "ivt_threshold_kg_m-1_s-1": args.ivt_threshold,
            "method": "IVT = hypot(viwve, viwvn) on the ERA5 0.25 deg grid; AR where IVT >= threshold",
        },
        {"ivt": (np.concatenate(ivts), {"long_name": "IVT magnitude", "units": "kg m-1 s-1"})},
    )  # fmt: skip
    write_mask_dataset(base, args.out / f"ivt_threshold_neuquen_{args.year}.nc")
    print(f"wrote ivt_threshold_neuquen_{args.year}.nc ({len(times)} steps)", flush=True)
    if model is not None:
        import json

        source = (
            json.loads((args.model_dir / "source.json").read_text())
            if (args.model_dir / "source.json").exists()
            else {}
        )
        cn = build_mask_dataset(
            times, *cn_grid, np.concatenate(cn_masks),
            {
                **common,
                "title": "ClimateNet (CGNet) AR class cropped to Neuquen",
                "method": "CGNet, ERA5 TMQ/U850/V850/PSL bilinear to the model grid, config.json normalisation, argmax class 2",
                "model_repo": "https://github.com/andregraubner/ClimateNet",
                "model_commit": args.model_commit,
                "weights_url": source.get("weights_url", "sin verificar"),
                "weights_sha256": source.get("sha256", "sin verificar"),
                "model_grid": f"{args.nlat}x{args.nlon}, lat ascending -90..90, lon 0..360",
            },
        )  # fmt: skip
        write_mask_dataset(cn, args.out / f"climatenet_neuquen_{args.year}.nc")
        print(f"wrote climatenet_neuquen_{args.year}.nc ({len(times)} steps)", flush=True)
    return 0


def _parse_area(text: str) -> list[float]:
    north, west, south, east = (float(x) for x in text.split(","))
    return [north, west, south, east]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--hours", default="00,06,12,18")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--model-dir", type=Path, default=Path("model"), help="dir with weights.pth (+ source.json)"
    )
    p.add_argument(
        "--repo-dir",
        type=Path,
        default=Path("ClimateNet"),
        help="checkout of andregraubner/ClimateNet",
    )
    p.add_argument("--model-commit", default="474bb96a76198ad1ff0551126c46a28a61a1b553")
    p.add_argument(
        "--baseline-only", action="store_true", help="skip the model (no weights or torch needed)"
    )
    p.add_argument("--area", type=_parse_area, default=list(NEUQUEN_BOX), metavar="N,W,S,E")
    p.add_argument("--ivt-threshold", type=float, default=IVT_THRESHOLD)
    p.add_argument("--nlat", type=int, default=768)
    p.add_argument("--nlon", type=int, default=1152)
    p.add_argument("--batch", type=int, default=8, help="steps per CPU inference batch")
    p.add_argument("--workers", type=int, default=8, help="parallel ARCO reads")
    p.add_argument("--max-steps", type=int, default=0, help="only the first N steps (smoke test)")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
