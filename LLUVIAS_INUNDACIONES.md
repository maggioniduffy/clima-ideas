# Lluvias extraordinarias, tormentas e inundaciones (zonas no agrícolas)

Búsqueda web de una pasada (2026-10-26). Lo no confirmado en la fuente oficial está marcado "sin verificar".

## Hipótesis a contrastar

Las zonas muy agrícolas ya están medidas por las aseguradoras (sequía, granizo). Las zonas **no agrícolas**
(ciudades, comercios, viviendas, infraestructura) no, y allí las lluvias extremas son un fenómeno más recurrente.
Un proveedor de datos y análisis podría cubrir ese hueco.

## 1. ¿Hay hueco de cobertura? (señales a favor)

- **Hogares y comercios:** según una abogada citada por Diario Judicial, la mayoría de las pólizas excluye
  expresamente la inundación y solo cubre roturas de cañerías o filtraciones accidentales
  ([Diario Judicial](https://www.diariojudicial.com/news-100119-que-cubren-en-caso-de-inundaciones-los-seguros-en-argentina)).
  ADECUA sostiene que sin el adicional HVCT (huracán, vendaval, ciclón, tornado) la inundación no está cubierta
  ([Al Día Argentina](https://aldiaargentina.microjuris.com/2014/10/30/los-seguros-cubren-los-danos-a-las-casas-y-automoviles-causados-por-las-inundaciones/), 2014).
- **Autos:** las condiciones generales uniformes de la SSN (2011) incluyen la inundación
  ([El Sol](https://www.elsol.com.ar/de-revista/que-cubren-los-seguros-de-autos-frente-a-las-inundaciones/)).
- **Penetración baja:** no está extendido asegurar el hogar (Diario Judicial). Un dato viejo de incendio, sin
  valor actual: ~75,8 % de inmuebles sin cobertura ([Mercado](https://mercado.com.ar/revista/2015-octubre-no1172/profesionalizacion-en-la-busqueda-de-oportunidades/), 2015).
- **Postura del sector:** el presidente de la AACS atribuyó la falta de cobertura a deficiencias de infraestructura
  (desagües pluviales) y vio necesario crear nuevas coberturas.
- **Demanda de modelos:** Aon Impact Forecasting dijo que crece la demanda de modelos de inundación en Brasil,
  Argentina y Chile, y que los modelos regionales sufren por pocos eventos históricos y pocos datos
  ([Aon](https://aon.mediaroom.com/Impact-Forecasting-launches-Mexican-flood-model-with-latest-regional-hazard-data),
  [Coverager](https://coverager.com/aon-expands-open-catastrophe-modelling-in-latin-america/)).

**Faltan** cifras recientes de penetración y de pérdidas aseguradas por inundación en Argentina. Pedirlas a la
SSN y a la AACS.

## 2. ¿Es más recurrente? (evidencia disponible)

- **Eventos extremos conocidos:** La Plata, 2 de abril de 2013, más de 400 mm en ~4 h y 89 muertes según fuentes
  de prensa y académicas ([SEDICI](https://sedici.unlp.edu.ar/bitstream/handle/10915/195444/Documento_completo.pdf?sequence=1)).
  También Bahía Blanca (sin fecha en los resultados; verificar).
- **Tendencia:** hay aumento de precipitación anual en la mayoría de las estaciones del sudeste de Sudamérica,
  atribuible a la estación cálida. Un especialista del CONICET dice que hay más eventos de lluvia intensa
  ([La Voz](https://grupoclarin-la-voz-prod.cdn.arcpublishing.com/ciudadanos/especialistas-alertan-sobre-lluvias-cada-vez-mas-intensas-y-frecuentes-cordoba-no-esta-exenta)),
  pero es una opinión, no una cuantificación. Un estudio del nordeste argentino analiza intensidad de lluvia
  1970–2019 (caso local) ([UNNE](https://revistas.unne.edu.ar/index.php/geo/article/download/4481/4385)).
- **Datos escasos:** un trabajo de La Plata advierte escasez de datos de lluvia y caudal para validar modelos.

**Lectura:** "más recurrente" es plausible pero **no está demostrado** por lo que encontré. No hay un catálogo
nacional de eventos ni un estudio cuantitativo de frecuencia de extremos. Eso es, a la vez, una oportunidad
(nadie lo publicó) y un riesgo (los datos para hacerlo son escasos).

## 3. Tormentas severas y granizo

- Córdoba: tormentas con granizo gigante al oeste de la ciudad, con récord de 17,5 cm en Carlos Paz en 2018;
  las Sierras influyen en la formación ([UNC](https://rdu.unc.edu.ar/handle/11086/14055)).
- Mendoza: el granizo es amenaza agrícola principal; hay un trabajo del INTA que estima pérdidas con denuncias de
  siniestros, sin cifras en el resumen ([RIMF](https://ojs.econ.uba.ar/index.php/RIMF/article/view/2339)).
- No hay mapas de riesgo de granizo actualizados ni datos recientes de siniestros en los resultados.

## 4. Competidores y actores

- **Pronóstico y alerta (público):** Prevenir (SMN + INA + JICA, 2022), INA, Mendoza, Santa Fe
  (ver `COMPETIDORES.md`). Operan sobre pronóstico, no sobre análisis de riesgo para seguros.
- **Modelos de catástrofes:** Aon Impact Forecasting (con modelos de ERN por Oasis; los hallados son de terremoto)
  y Guy Carpenter (modelo de inundación de Brasil). **No cubrí** Verisk, Moody's RMS, Jupiter Intelligence ni
  Cloud to Street; si alguno ya modela inundación urbana en Argentina, es competidor directo.

## 5. Datos y licencias

| Dato | Uso | Licencia |
|---|---|---|
| ERA5 | Lluvia horaria, contexto sinóptico (grilla ~25–30 km; suaviza lluvias convectivas) | CC BY 4.0 desde julio de 2025; confirmar texto oficial |
| IMERG (NASA GPM) | Lluvia satelital cada 30 min, ~10 km | NASA la declara de libre uso; el producto diario "late" figura CC BY 4.0 en el registro de AWS; confirmar en GES DISC |
| CHIRPS | Lluvia diaria, ~5 km | Conflicto sin resolver (ver `HELADAS_OLAS_CALOR_Y_LICENCIAS.md`) |
| Estaciones SMN/INA | Lluvia puntual | Condiciones comerciales sin verificar |

Fuentes: [Earth Engine IMERG](https://developers.google.com/earth-engine/datasets/catalog/NASA_GPM_L3_IMERG_V07),
[AWS Open Data](https://registry.opendata.aws/nasa-gpm3imergdl).

**Riesgo técnico:** la lluvia que causa inundaciones urbanas es corta y local. Los productos globales la
subestiman. Sin estaciones o radar, un catálogo con ERA5 o IMERG sirve para frecuencia regional, no para
daños en una calle concreta.

## Conclusión provisoria

- La hipótesis **tiene apoyo parcial**: hay hueco de cobertura en hogares y comercios y hay demanda declarada de
  modelos de inundación. Falta evidencia de que sea más recurrente.
- El ángulo más defendible de datos y análisis: **catálogo de lluvias extremas por ciudad con períodos de
  retorno** (cruza con la idea 4, climatologías municipales), validado contra estaciones.
- Mostrarlo a una aseguradora o corredor antes de construir más.

## Pendiente

- [ ] Cifras de penetración y pérdidas por inundación: pedirlas a la SSN y a la AACS
- [ ] Verisk, Moody's RMS, Jupiter Intelligence, Cloud to Street: ¿modelan inundación en Argentina?
- [ ] Series de lluvia diaria largas y homogéneas del SMN para ciudades (Buenos Aires, Rosario, Córdoba)
- [ ] Confirmar licencia de IMERG (GES DISC) y de ERA5
- [ ] Estudios cuantitativos de tendencia de extremos (índices tipo Rx1day, R95p) en la región pampeana
- [ ] Granizo: mapas de riesgo y siniestros recientes (SSN, INTA, SMN, Bolsa de Comercio de Córdoba)
