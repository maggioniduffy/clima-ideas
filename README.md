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
