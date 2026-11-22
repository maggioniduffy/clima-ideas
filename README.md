F5.1 hindcast forecasts (plan/05-hindcast.md), built by .github/workflows/hindcast-forecasts.yml
run 44976687235. Models: gefs-reforecast ifs aifs. Not code; can be deleted after use.
Files: <model>.zarr (variable precip_mm: case, lead, member, lat, lon; mm per 24 h lead window;
lat -41..-36, lon -71.5..-68; `status` marks ok / not published / error per entry; attrs hold
source, license, period, lead convention and counts) and cases.parquet (event and control days;
rule, seed and counts in the Parquet metadata).
Lead L = forecast hours (24(L-1), 24L] of the 00 UTC run; valid_date = init_date + L - 1.
Sources: NOAA GEFSv12 reforecast (noaa-gefs-retrospective, NODD: open, attribution requested, no
NOAA endorsement implied); ECMWF open data IFS and AIFS via the AWS mirror (CC-BY-4.0 + ECMWF
Terms of Use, https://www.ecmwf.int/en/forecasts/datasets/open-data). Catalog: branch
data/f23-ar-events (F1.3, ERA5 + TECA BARD).

aifs.zarr replaced on 2026-11-22 by a local rerun of the fixed code (units read from each GRIB message:
aifs-single publishes tp in kg m-2, older aifs/ in m; reduced Gaussian O320 runs of 2024-02-29..2024-03 are
interpolated to the 0.25° grid). 253 ok, 7 not published, 0 errors.
