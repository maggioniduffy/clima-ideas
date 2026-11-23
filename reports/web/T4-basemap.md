# T4 basemap: CARTO terms check

- Date: 2026-11-23
- Tiles: `https://{a-d}.basemaps.cartocdn.com/{light_all|dark_all}/{z}/{x}/{y}@2x.png` (OpenStreetMap data, CARTO styles).
- Terms pages tried with curl through the agent proxy: https://carto.com/basemaps, https://carto.com/attributions,
  https://carto.com/legal/ . All refused by the proxy (CONNECT 403, host not allowed): nothing read.
- Result: CARTO's terms of use for this use (free basemaps, volume limits, commercial use) are **sin verificar**.
  URLs to read by hand: https://carto.com/basemaps and https://carto.com/attributions .
- Applied regardless: attribution "© OpenStreetMap contributors © CARTO" always visible in the map card, with links to
  https://www.openstreetmap.org/copyright and https://carto.com/attributions .
- e2e routes the tile hosts to `web/e2e/fixtures/tile.png` (`web/e2e/fixtures/test.ts`); no test reaches the network.
