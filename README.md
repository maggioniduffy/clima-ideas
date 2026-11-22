F5.5 ERA5 analogs of the F1.3 events (plan/05-hindcast.md), built by .github/workflows/hindcast-analogs.yml
run 45068915267. Not code; can be deleted after use.
Files: era5-ivt-daily.zarr (daily mean of the 00/06/12/18 UTC viwve, viwvn, kg m-1 s-1, box N -34 W -74
S -43 E -66 at 0.25 deg), analogs.parquet (one row per event x analog or baseline day, with distance, the
F1.3 event touched, daily box-max IVT and regional rain from IMERG and ERA5), analogs.json (the same by
event, with the summary; input of the layer hindcast-analogs), F5.5.md and F5.5.json (report).
Source: ERA5 (Copernicus Climate Change Service) via ARCO-ERA5 (Google Cloud public dataset), CC-BY 4.0;
IMERG Final Run V07 (NASA GES DISC), CC BY 4.0. Period: library 1980-01-01..2025-12-31 (the last
year holds what ARCO has); rain from IMERG 2000-06-01..2025-09-30 and ERA5 2000-01-01..2019-12-31, "no data"
outside them. Events: branch data/f23-ar-events (F1.3).
