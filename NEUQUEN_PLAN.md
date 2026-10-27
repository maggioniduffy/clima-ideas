# Plan: lluvias extremas, crecidas y aluviones en la provincia de Neuquén

Estado: borrador (2026-10-26). Objetivo: aprender y ganar experiencia, sin fin comercial. Recorre de la
atmósfera al suelo: ríos atmosféricos, crecidas, convección, aluviones y predicción. Los datos y fechas marcados
"sin verificar" deben confirmarse antes de usarlos. Antecedentes en `NEUQUEN.md` y `LLUVIAS_INUNDACIONES.md`.

## Zonas

| Zona | Qué causa el daño | Ejemplos |
|---|---|---|
| **Cordillera** (San Martín de los Andes, Villa La Angostura, Aluminé, norte neuquino) | Temporales frontales y ríos atmosféricos del Pacífico, lluvia sobre nieve, flujos de detritos | Crecidas de los ríos Neuquén y Limay; aluviones en Chos Malal y Andacollo (sin verificar) |
| **Meseta y monte** (Añelo, Rincón de los Sauces, Rutas 5 y 7) | Tormentas convectivas cortas sobre suelo arcilloso o desnudo | Alud en la Ruta 5, Añelo 2023 (ver `NEUQUEN.md`) |
| **Confluencia** (Neuquén capital, Plottier, Centenario) | Convección, escorrentía de bardas e infraestructura urbana | Temporal de abril de 2014 |

La cordillera aporta casi toda el agua de los ríos; por eso el plan empieza ahí.

## Etapas

### 1. Ríos atmosféricos en la cordillera

- **Pregunta:** ¿cuántos ríos atmosféricos llegan a la cordillera neuquina por año y cuánta de la lluvia extrema
  explican?
- **Datos:** ERA5 1980–hoy (transporte integrado de vapor IVT, precipitación, isoterma de 0 °C). Licencia
  CC BY 4.0 desde julio de 2025; confirmar texto oficial.
- **Herramientas:** TECA BARD para detectar ríos atmosféricos; xarray para cruzar con la lluvia. Aquí TECA sí se
  justifica (muchos años, detección de eventos a escala sinóptica).
- **Aprendizaje:** meteorología sinóptica, efecto orográfico, lluvia sobre nieve, detección de eventos.
- **Primer entregable:** catálogo de ríos atmosféricos que tocan la cordillera neuquina (fecha, duración, IVT
  máximo, isoterma de 0 °C) y la fracción de los días de lluvia extrema que coincide con uno. Contrastar con la
  literatura sobre ríos atmosféricos en los Andes.

### 2. Crecidas de ríos

- **Pregunta:** ¿qué tan raras fueron las crecidas grandes y qué parte se explica por ríos atmosféricos o por
  lluvia sobre nieve?
- **Datos:** caudales de los ríos Neuquén, Limay, Agrio y Curi Leuvú. Candidatos: BDHI (Base de Datos
  Hidrológica Integrada) y AIC. Acceso, resolución y licencia sin verificar.
- **Herramientas:** pandas, scipy o `pyextremes` (máximos anuales, GEV).
- **Aprendizaje:** hidrología de cuencas grandes; cómo las presas (El Chocón, Portezuelo Grande) alteran la serie
  natural.
- **Primer entregable:** períodos de retorno de caudal máximo para una estación de aforo aguas arriba de las presas
  (por ejemplo, río Neuquén en Chos Malal, sin verificar), con intervalo de confianza, y sus crecidas mayores
  etiquetadas con el catálogo de la etapa 1.

### 3. Convección en la meseta y la Confluencia

- **Pregunta:** ¿cada cuánto se repite una lluvia como la de abril de 2014, y cuánto la subestiman los productos
  globales?
- **Datos:** IMERG cada 30 min (2000–hoy), estación Neuquén Aero del SMN, estaciones de la AIC (Plottier) y otras.
  Resolución horaria y licencias sin verificar.
- **Herramientas:** xarray, `pyextremes`; curvas IDF (intensidad, duración, frecuencia).
- **Aprendizaje:** estadística de extremos; límites de los datos satelitales frente a la convección. Aquí TECA no
  sirve: contraste con la etapa 1.
- **Primer entregable:** curva IDF de Neuquén capital con estación e IMERG lado a lado, y el sesgo de IMERG en
  los eventos conocidos.

### 4. Aluviones: susceptibilidad y un caso a fondo

- **Pregunta:** ¿dónde se concentra el agua sobre rutas y localidades, y con qué lluvia?
- **Datos:** modelo de elevación Copernicus GLO-30, mapas de suelo y cobertura (fuentes sin verificar), lluvias de
  diseño de las etapas 2 y 3.
- **Herramientas:** pysheds o WhiteboxTools para cuencas; método SCS-CN para escorrentía; HEC-RAS 2D (gratuito)
  para la simulación.
- **Aprendizaje:** hidrología de cuencas chicas e hidráulica 2D; esta es la parte de prevención.
- **Primer entregable:** mapa de cuencas chicas que desaguan sobre las Rutas 5 y 7 y sobre los barrios bajo las
  bardas, ordenadas por caudal pico estimado. Después, una simulación HEC-RAS de un cañadón comparada con un evento
  conocido.

### 5. Predicción retrospectiva

- **Pregunta:** ¿los pronósticos veían venir los eventos de las etapas 1 y 3, y con cuántos días de anticipación?
- **Datos:** reforecasts de GEFS (AWS Open Data), datos abiertos de ECMWF para eventos recientes; condiciones de
  ERA5 (agua precipitable, CAPE, convergencia). Licencias a confirmar.
- **Herramientas:** xarray; scikit-learn para un clasificador simple de "día de riesgo".
- **Aprendizaje:** verificación de pronósticos, predictibilidad, clases desbalanceadas (los eventos son pocos).
- **Primer entregable:** acierto del pronóstico según días de anticipación, para ríos atmosféricos y para
  convección. Se espera que los ríos atmosféricos se pronostiquen con días de anticipación y la convección casi no;
  hay que medirlo. No es un sistema de alerta: una alerta real exige operación continua y responsabilidad.

## Machine learning

Regla: usar ML solo donde sobran datos (series largas, globales o sintéticos) y compararlo siempre con un
baseline simple. El límite general del plan es que hay muy pocos eventos extremos para etiquetar.

### Modelos justificados por etapa

| Etapa | Modelo | Por qué se justifica | Baseline | Prioridad |
|---|---|---|---|---|
| 2. Crecidas | LSTM de caudal diario (forzantes ERA5, incluida la isoterma de 0 °C) | ~40 años de caudal diario; se puede preentrenar en cuencas andinas de CAMELS-CL y ajustar en Neuquén | GR4J y persistencia | Alta: el primero a encarar |
| 4. Aluviones | Emulador de HEC-RAS 2D (U-Net o red de grafos) | Datos sintéticos: cientos de simulaciones con lluvias distintas, sin escasez de eventos | La simulación HEC-RAS misma (precisión) | Alta, después del caso HEC-RAS |
| 1. Ríos atmosféricos | Detector DL preentrenado (por ejemplo, ClimateNet) sobre ERA5 | Comparación, no reemplazo: mide cuánto depende el catálogo del método | TECA BARD | Media |
| 5. Predicción | Clasificador de "día de riesgo" (gradient boosting, por ejemplo LightGBM) | Variables de ERA5 abundantes, aunque las etiquetas sean pocas | Climatología y regresión logística | Media; evaluar con Brier y PR-AUC, no con exactitud |
| 5. Predicción | Modelos de IA preentrenados (ECMWF AIFS), sin entrenar | Pronósticos abiertos; enseña dónde fallan con extremos | ECMWF IFS | Media |

### Descartados o postergados

- **Aprendizaje por refuerzo para operar embalses** (Cerros Colorados, Portezuelo Grande): requiere un simulador
  propio y las reglas reales de operación no son públicas (sin verificar). Ejercicio aislado, al final o fuera.
- **Susceptibilidad de aluviones con ML:** no hay inventario georreferenciado de aluviones (sin verificar). Usar
  primero el método físico de la etapa 4.
- **Downscaling de IMERG con DL:** pocas estaciones horarias para entrenar y validar. Rinde más una corrección de
  sesgo por cuantiles (quantile mapping).
- **Nowcasting con radar:** depende de que exista y sea accesible un radar del SINARAME que cubra la zona
  (sin verificar).

### Features opcionales

- **Análogos de cada evento:** los días de ERA5 más parecidos y qué pasó en ellos (paso previo a ML).
- **Ficha de crecida:** pronóstico LSTM de los próximos días para los ríos Neuquén y Limay, con incertidumbre,
  contra lo observado.
- **Escenarios de aluvión:** elegir un período de retorno y ver la mancha del emulador para un cañadón.
- **Tablero de verificación:** acierto de IFS, AIFS y GEFS en los eventos neuquinos según días de anticipación.
- **Capa de ríos atmosféricos** en `rionegro-basin-explorer`: trayectoria e intensidad por evento, sincronizada
  con el caudal.

## Orden y riesgos

- **Orden:** 1 → 2 → 3 → 4 → 5. La etapa 1 solo necesita datos globales y libres, así que puede empezar ya.
- **Riesgo principal:** los datos locales (caudales y lluvia horaria). Averiguar su acceso en paralelo a la etapa 1.
- **Opcional:** sumar cada entregable como capa del proyecto `rionegro-basin-explorer`.

## Pendiente

- [ ] Instalar TECA y correr BARD sobre un año de ERA5 como prueba
- [ ] Acceso, resolución y licencia de caudales: BDHI y AIC
- [ ] Lluvia horaria o subhoraria de SMN (Neuquén Aero) y AIC: ¿existe y cómo se pide?
- [ ] Fechas y magnitudes confirmadas de crecidas y aluviones en la cordillera y el norte neuquino
- [ ] Literatura sobre ríos atmosféricos en los Andes y sobre aluviones en Neuquén
- [ ] Mapas de suelo y cobertura para el método SCS-CN
- [ ] Confirmar licencias de ERA5, IMERG, GEFS y ECMWF open data
- [ ] CAMELS-CL: acceso y licencia para preentrenar el LSTM
- [ ] Licencia y acceso a los pronósticos abiertos de ECMWF AIFS
- [ ] ¿Existe un inventario de aluviones de Neuquén y un radar del SINARAME que cubra la provincia?
