# Competidores y herramientas existentes

Búsqueda web de una pasada (2026-10-26). Sirve para orientarse, no es un estudio de mercado. La mayoría de las
fuentes son notas de prensa o artículos; precios, licencias y estado actual **sin verificar** salvo que se diga lo contrario.

## 1. Agro: sequías, olas de calor y heladas (seguros paramétricos)

El mercado argentino de seguros paramétricos de sequía ya existe y usa índices satelitales.

| Actor | Qué ofrece | Fuente / nota |
|---|---|---|
| Sancor Seguros | "Sequía Max": índice satelital TDVI (vegetación + humedad superficial del suelo), datos cada 15 días, consulta en plataforma. Datos del Instituto Gulich | [Bichos de Campo](https://bichosdecampo.com/sancor-seguros-lanzo-una-novedosa-cobertura-para-la-sequia-que-se-basa-en-la-informacion-satelital-y-puede-ser-monitoreada-desde-el-celular) |
| Compañía de Seguros El Norte | Seguro paramétrico de sequía; dice ser la única autorizada por la SSN (afirmación de la propia empresa, sin verificar) | [Aire de Santa Fe](https://www.airedesantafe.com.ar/compania-seguros-el-norte-sa-presenta-una-forma-innovadora-proteger-los-cultivos-n171814) |
| S4 (González Venzano) | Mapas de riesgo en grilla de 20 x 20 km; reporta correlación 0,87 con la caída de rendimientos (fuente antigua) | [Bichos de Campo](https://bichosdecampo.com/la-evolucion-de-una-buena-idea-la-cobertura-para-sequia-de-s4-sera-ofrecida-directamente-por-algunas-companias-de-seguro) |
| CONAE | Publica índices de vegetación y déficit hídrico usados como base por aseguradoras | Mencionado en los resultados, sin enlace propio |
| SMN | Publica el Índice de Precipitación Estandarizado (SPI/IPE) mensual en escalas de 1 a 24 meses (según una nota periodística sin fecha) | [El Litoral](https://www.ellitoral.com/edicion-online/mapa-revelador_0_WGmj91hU1H.html); verificar en smn.gov.ar |
| EOS Data Analytics | Blog sobre seguros basados en índices | [EOS](https://eos.com/es/blog/seguros-parametricos/) |

**Evidencia técnica:** un estudio en IEEE JSTARS halló que el índice de humedad de suelo satelital SMADI detectó más
del 83 % de las emergencias agrícolas registradas en Argentina, mejor que SPI y SPEI
([ISPRS Annals](https://isprs-annals.copernicus.org/articles/IV-3-W2-2020/53/2020/)). Otro estudio de la UBA halló que
ISHi rindió mejor mensualmente en localidades húmedas y SPEI/SPI a escala trimestral
([Agronomía y Ambiente](https://nuevoagronomiayambiente.agro.uba.ar/index.php/AyA/en/article/view/116/103)).

**Hueco posible:** heladas y olas de calor casi no aparecen. Todo lo hallado es sequía. Un producto propio tendría
que competir con aseguradoras que ya tienen datos, regulación y distribución, así que el ángulo más realista es
datos o análisis para ellas, no un seguro.

## 2. Energía: bajo viento, baja radiación, calor extremo

| Herramienta | Qué es | Fuente / nota |
|---|---|---|
| Global Wind Atlas | Gratis, Banco Mundial/DTU, 250 m, ERA5 reducido con WAsP; para prefactibilidad, no para decisiones de inversión | [Atlas](https://atlas.co/data-sources/global-wind-atlas) |
| ERA5 | Reanálisis. Validaciones lo favorecen frente a MERRA-2 para potencia eólica, pero con variabilidad por sitio (hasta 15 puntos de factor de capacidad en un estudio de Polonia) | [arXiv](https://arxiv.org/pdf/2101.08741) |
| Renewables.ninja | Simulaciones horarias de viento y potencia por modelo de turbina; precisión no evaluada en los resultados | [arXiv](https://arxiv.org/pdf/2101.08741) |
| IRENA Global Atlas | Plataforma GIS abierta que integra Global Solar Atlas y Global Wind Atlas | [ESA SEF](https://sef.apex.esa.int/en/what-we-do/training/external-resources-renewable-energy-theme) |
| Solargis | **No cubierto por la búsqueda**; buscar aparte |  |

**Hueco posible:** estas herramientas dan recurso promedio. Un catálogo de **eventos** (rachas de viento bajo, olas de
calor) para el sistema eléctrico argentino no apareció, pero no se buscó con detalle. Sin datos reales de generación
y demanda no hay vínculo causal.

## 3. Alerta temprana y planificación urbana

| Actor | Qué ofrece | Fuente / nota |
|---|---|---|
| **Prevenir** (SMN + INA, con JICA) | Pronóstico hidrometeorológico hasta 12 h para inundaciones urbanas repentinas en Sarandí-Santo Domingo (Buenos Aires) y Suquía (Córdoba); portal web y app. Lanzado en 2022, previsto a 5 años, inversión japonesa de ~US$6,5 millones. **Estado actual sin verificar** | [Unidiversidad](https://www.unidiversidad.com.ar/como-funciona-prevenir-el-sistema-de-alerta-temprana-de-inundaciones-del-smn), [El Economista](https://eleconomista.com.ar/actualidad/lanzan-prevenir-sistema-alerta-temprana-inundaciones-zonas-urbanas-n54494) |
| INA | Alertas hidrológicas desde hace décadas (Centro Operativo de Alerta Hidrológico; sistema del Pilcomayo) | [ANCEFN](https://www.ancefn.org.ar/user/files/Agua_esp.pdf) |
| Mendoza | Sistema provincial en preparación (Gobierno, AEMSA, Irrigación, INA) | [El Sol](https://www.elsol.com.ar/mendoza/como-funcionara-el-nuevo-sistema-de-alerta-temprana-que-prepara-mendoza-por-el-super-nino/) |
| Santa Fe | Portal de alerta temprana de Protección Civil | [Santa Fe](https://www.santafe.gob.ar/proteccioncivil/alertatemprana) |

**Hueco posible:** ya hay organismos públicos con financiamiento y operación. Un actor privado tendría poco margen
en alerta operativa. Más viable: **análisis retrospectivos** o **planificación** (qué eventos pasaron, dónde). Las
fuentes advierten que la falta de lluvia confiable a escala fina limita el pronóstico y que alertas imprecisas
pierden credibilidad.

## 4. Climatologías para municipios y defensa civil

| Herramienta | Qué es | Fuente / nota |
|---|---|---|
| climextRemes | Paquete de R (BSD-3, con wrapper de Python) para valores y períodos de retorno, con incertidumbre | [CRAN](https://rdrr.io/cran/climextRemes) |
| Climpact (WMO) | Paquete de R de código abierto: índices de extremos a partir de temperatura y precipitación diarias; no centrado en períodos de retorno | [NDC Partnership](https://ndcpartnership.org/knowledge-portal/climate-toolbox/climpact) |
| xclim, CLIMDEX, tableros municipales | **No cubiertos por la búsqueda**; buscar aparte |  |

**Hueco posible:** las herramientas existentes son para especialistas. Un producto simple para municipios (en
español, con una ciudad y un rango de incertidumbre) no apareció, pero no se buscó adopción municipal.

## Pendiente de buscar

- [ ] Solargis y otros datos solares comerciales
- [ ] xclim, CLIMDEX y tableros climáticos para ciudades
- [ ] Estado actual de Prevenir (¿sigue operativo en 2026?) en la web oficial del SMN
- [ ] Heladas y olas de calor: ¿quién publica catálogos en Argentina?
- [ ] Precios y licencias de los datos del SMN, CONAE e INA
- [ ] Competidores en eventos energéticos (viento bajo, calor) para CAMMESA o generadores
