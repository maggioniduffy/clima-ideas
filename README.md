Forecast registry and operational inputs (plan/06-forecast.md), written by
.github/workflows/forecast-daily.yml. Append-only: never rewrite or force-push this branch.
- registry/predictions.jsonl: frozen predictions (F6.4, SHA-256 hash chain); registry/head.txt: head hash.
- training/flow: SNIH daily flow snapshot used to fit the baselines (frozen; its hash is in the model version).
- operational/<source>/<date>.parquet + manifest.json: daily input snapshots (F6.1).
- observed/flow: latest SNIH refresh used for scoring; scores/latest.{json,md}: skill table (F6.5).
Sources: SNIH (SIPH) Red Hidrológica Nacional; NOAA CPC ONI; ERA5T (Copernicus C3S, CC-BY 4.0, ARCO-ERA5);
ECMWF open data (CC-BY 4.0); NOAA GEFS (NODD open data, attribution requested). Not an official warning.
