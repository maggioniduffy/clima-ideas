# ClimateNet (CGNet) vs BARD, con baseline de IVT (F1.7)

Workflow manual `.github/workflows/climatenet.yml`: un job de CPU por año corre el detector preentrenado ClimateNet y
la línea base IVT ≥ 250 kg m-1 s-1 sobre ERA5 (ARCO-ERA5), recorta a Neuquén (`-34,-74,-43,-66`) y sube
`climatenet-neuquen-<año>`; el job final compara con `bard-neuquen-<año>` (`clima_nqn.stages.ar.compare`) y sube
`climatenet-compare` (F1.7.md / F1.7.json). Procedencia del modelo y lo que sigue sin verificar: `reports/01/F1.7.md`.

```sh
gh workflow run climatenet.yml -f years=2023 -f bard_run_id=42437931768
```

## Campos (ARCO-ERA5 → entrada de ClimateNet)

| Campo del modelo | Variable ARCO | Unidad |
|---|---|---|
| TMQ | `total_column_water_vapour` | kg m-2 |
| U850, V850 | `u_component_of_wind`, `v_component_of_wind` en 850 hPa | m s-1 |
| PSL | `mean_sea_level_pressure` | Pa |
| baseline | `viwve`, `viwvn` (flujo vertical integrado de vapor, este/norte): IVT = módulo | kg m-1 s-1 |

Pasos: los mismos de BARD (`--hours 00,06,12,18`). Regrillado bilinear de 0,25° (721 x 1440) a 768 x 1152
(latitud ascendente, longitud 0..360; sin verificar que sea la grilla de entrenamiento), normalización con las
estadísticas de `config.json` del repo, inferencia en CPU por lotes, clase 2 = río atmosférico. Salida:
`climatenet_neuquen_<año>.nc` (`ar_mask` uint8, time/lat/lon, grilla del modelo recortada) y
`ivt_threshold_neuquen_<año>.nc` (`ar_mask` + `ivt`, grilla ERA5 0,25°).

## Línea base

IVT ≥ 250 kg m-1 s-1 es el umbral clásico de la literatura de ríos atmosféricos (p. ej. Ralph et al.; cifra de
memoria, sin verificar acá). Es el "baseline simple" que va al lado del modelo ML.

## Archivos

- `climatenet_core.py`: regrillado, normalización, recorte y baseline (solo numpy).
- `run_climatenet.py`: lectura ARCO, inferencia (torch se importa recién al correr el modelo), escritura.
  `--baseline-only` corre solo la línea base, sin pesos ni torch.
- `fetch_weights.py`: baja los pesos desde un enlace directo o un índice HTML y registra URL y sha256.
- `requirements.txt`: dependencias con torch CPU. Tests: `uv run --with pytest --with numpy --with xarray --with netcdf4 pytest tools/climatenet`.
