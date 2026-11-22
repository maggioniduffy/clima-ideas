F5.3 all-days GEFS reforecast (plan/05-hindcast.md), built by .github/workflows/hindcast-alldays.yml
run 45058723043. Not code; can be deleted after use.
Files: gefs-reforecast.zarr (variable precip_mm: case, lead, member, lat, lon; mm per 24 h lead
window; members c00 p01..p04; wide grid lat -41.25..-36, lon -72..-67.5 at 0.25 deg; `status`
marks ok / not published / error per entry; attrs hold source, license, period, grid, lead
convention and counts) and cases.parquet (one case per valid day, kind "all", ids ALL-YYYYMMDD).
Lead L = forecast hours (24(L-1), 24L] of the 00 UTC run; valid_date = init_date + L - 1.
Source: NOAA GEFSv12 reforecast (noaa-gefs-retrospective, NODD: open, attribution requested, no
NOAA endorsement implied).
