F5.10 forecast IVT (plan/05-hindcast.md), built by .github/workflows/hindcast-ivt.yml
run 45061054798. Not code; can be deleted after use.
Files: gefs-reforecast-ivt.zarr (variable ivt: case, lead, member, lat, lon; kg m-1 s-1; member c00
only; lat -41..-36, lon -71.5..-68 at 0.25 deg; `status` marks ok / not published / error per
entry; attrs hold source, license, period, levels, steps and counts) and cases.parquet (the F5.1
event and control days, copied from branch data/f51-forecasts).
IVT = |Q|, Q = (1/g) integral of q (u, v) dp over 1000, 925, 850, 700, 600, 500, 400 and 300 hPa
(trapezoid in Pa, g = 9.80665). Lead L: mean of |Q| at forecast hours 24(L-1)+6, +12, +18 and
24L of the 00 UTC run; valid_date = init_date + L - 1.
Source: NOAA GEFSv12 reforecast (noaa-gefs-retrospective, SPFH/UGRD/VGRD pressure-level files;
NODD: open, attribution requested, no NOAA endorsement implied).
