# Geographic references

- `neuquen-province.geojson`: outline of Neuquén province. Source: Natural Earth 1:10m Admin 1 - States, Provinces
  (`ne_10m_admin_1_states_provinces`, feature `ARG-1276`), from
  https://github.com/nvkelso/natural-earth-vector. License: public domain (https://www.naturalearthdata.com/about/terms-of-use/).
  Only change: coordinates rounded to 3 decimals. Scale 1:10m, so the outline is approximate (kilometers).
- `neuquen-province-buffer-10km.geojson`: the province outline above buffered by 10 km (round joins, true distance in a
  local equal-area projection, simplified at 100 m, 3 decimals). Derived, not a source: regenerate with
  `uv run scripts/buffer_province.py` from the repo root (shapely, via inline script metadata). The viewer clips the IVT
  raster and the relief to it (province + 10 km band). Approximate, sin verificar.
