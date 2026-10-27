# clima-ideas

Ideas de proyectos sobre clima y eventos extremos en Argentina. **Borrador: nada está validado.**

Origen: análisis de [TECA](https://github.com/LBL-EESA/TECA) (Toolkit for Extreme Climate Analysis) y de
dónde podría servir fuera del proyecto `rionegro-basin-explorer`.

## Índice

1. [Agro: sequías, olas de calor y heladas](IDEAS.md#1-agro-sequías-olas-de-calor-y-heladas)
2. [Energía: bajo viento, baja radiación y calor extremo](IDEAS.md#2-energía-bajo-viento-baja-radiación-y-calor-extremo)
3. [Alerta temprana y planificación urbana](IDEAS.md#3-alerta-temprana-y-planificación-urbana)
4. [Climatologías para municipios y defensa civil](IDEAS.md#4-climatologías-para-municipios-y-defensa-civil)

## Investigación (búsqueda web de una pasada, 2026-10-26; fuentes sin verificar)

- [COMPETIDORES.md](COMPETIDORES.md): competidores y herramientas existentes por idea
- [HELADAS_OLAS_CALOR_Y_LICENCIAS.md](HELADAS_OLAS_CALOR_Y_LICENCIAS.md): heladas, olas de calor y licencias de datos
- [LLUVIAS_INUNDACIONES.md](LLUVIAS_INUNDACIONES.md): lluvias extremas, tormentas e inundaciones en zonas no agrícolas
- [NEUQUEN.md](NEUQUEN.md): caso Neuquén y Alto Valle

## Diseño

- [inspiracion/](inspiracion/README.md): referencias visuales para el visor

## Reglas de trabajo

- No se inventan cifras, clientes ni mercados: lo no verificado se marca "sin verificar".
- Todo dato modelado indica fuente y período.
- Revisar la licencia de cada fuente de datos y de TECA antes de usarlos (GitHub muestra la de TECA como
  "desconocida"; leer `LICENSE` y `LICENSE.md` del repo).
- TECA solo si el volumen de datos lo justifica; para una región y pocos años, xarray alcanza.
