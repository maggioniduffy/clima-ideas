# T4 basemap: CARTO terms check

- Date: 2026-11-23.
- First check: carto.com was blocked by the build environment's proxy; terms "sin verificar".
- Live check after deploy (same day): the unkeyed tiles `https://{a-d}.basemaps.cartocdn.com/{style}/…` answer 200 but
  every tile is an "API KEY REQUIRED" image. Read https://carto.com/basemaps and the machine-readable offer at
  https://dashboard.basemaps.carto.com/v1/plans (terms version 2026-09-29, https://carto.com/legal/basemap-terms/):
  - an API key is required on every `basemaps.cartocdn.com` URL (`?key=<key>`); a person requests it with an e-mail at
    https://carto.com/basemaps/apikey/ (no API issues keys); keys can be restricted to websites;
  - free up to 5,000,000 tile requests a month for non-commercial use (personal projects, research, teaching,
    non-profits); 1,000,000 for commercial use;
  - attribution required: "© OpenStreetMap contributors, © CARTO", link https://carto.com/attributions/ .
  - The full legal text at https://carto.com/legal/basemap-terms/ was not read: **sin verificar** beyond the summary above.
- Applied: raster URL `https://basemaps.cartocdn.com/rastertiles/{light_all|dark_all}/{z}/{x}/{y}@2x.png?key=<key>`
  (both styles checked: 200 image/png). The key comes from the build variable `VITE_CARTO_KEY` (deploy secret
  `CARTO_BASEMAPS_KEY`); without it the viewer draws no basemap instead of the "API KEY REQUIRED" tiles.
- Attribution "© OpenStreetMap contributors © CARTO" always visible in the map card, with links.
- e2e runs the dev server with a fixture key and routes `basemaps.cartocdn.com` to `web/e2e/fixtures/tile.png`.
