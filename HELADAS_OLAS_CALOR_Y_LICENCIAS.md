# Heladas, olas de calor y licencias de datos

Búsqueda web de una pasada (2026-10-26). Lo no confirmado en la fuente oficial está marcado "sin verificar".

## 1. Heladas: qué existe

No apareció un catálogo oficial único (INTA o SMN) con fechas medias de última helada para toda la región
pampeana. Lo que hay son estudios sueltos y notas:

| Fuente | Qué aporta |
|---|---|
| [Fernández Long et al., región pampeana, 1964–1993 (AGRIS/FAO)](https://agris.fao.org/search/en/records/6790c3be65d8e90e60b0f5b0) | El período de heladas se acortó en casi toda la región, salvo el sur de Buenos Aires |
| [Tesis de Lentini, FAUBA, ~60 años (Bichos de Campo)](https://bichosdecampo.com/el-clima-esta-loco-analizando-60-anos-las-primeras-heladas-llegan-cada-vez-mas-tarde-y-las-tardias-tambien-se-atrasan-varias-semanas/) | Última helada atrasada 10–20 días en el país; en la pampeana se adelantó (Tandil ~22 días). Mapas por publicar vía el Centro de Información Agroclimática y Ambiental de FAUBA |
| [Congreso Argentino de Agroinformática, Anguil, La Pampa](https://49jaiio.sadio.org.ar:443/pdfs/cai/CAI_07.pdf) | Menos heladas por año y última helada más temprana en períodos recientes |
| [UNLPam, Santa Rosa](https://ojs.unlpam.edu.ar/ojs/index.php/semiarida/article/download/9044/10285/42147) | Evalúa modelos climáticos para índices de heladas, 1977–2010 |
| INTA, Instituto de Clima y Agua | Pronóstico de heladas tardías basado en GFS, actualizado lunes y viernes (según una nota; sin verificar) |

**Lectura:** el tema está estudiado de forma académica y puntual, sin producto comercial a la vista. Eso apoya
que haya hueco, pero también puede significar que nadie lo pide. Hay que preguntarle a un comprador, no asumirlo.
Las tablas oficiales por estación hay que pedirlas al INTA y al SMN (sin verificar).

## 2. Olas de calor: qué existe

- **Definición del SMN:** al menos 3 días consecutivos con máxima y mínima por encima de umbrales regionales. Una
  presentación del SMN indica que los umbrales son el percentil 90 del semestre cálido (octubre–marzo) con datos
  1961–2010 ([IAI](https://www.iai.int/administrador/assets/images/ckfinder/files/SESSION%204%20-%20CASE%20STUDY.pdf)).
- **Tendencia (según el SMN, vía prensa):** de 20–40 olas de calor por año en los 60 a unas 80 por año en la
  última década ([El Litoral](https://www.ellitoral.com/informacion-general/temperaturas-extremas-provoca-olas-calor-duran_0_NM3JsCQrN5.html)).
  Esa cifra cuenta eventos a nivel de estación, así que verificar la definición antes de citarla.
- **Evento destacado:** enero de 2022, que el SMN calificó de sin precedentes y que cubrió el 72 % del territorio
  ([Noticias NQN](https://www.noticiasnqn.com.ar/amp/noticias/2022/11/08/268545-smn-se-registraron-olas-de-calor-sin-precedentes-y-un-invierno-ms-fro-de-lo-habitual-en-2022)).
- **No encontré** un catálogo público de eventos ni un estudio del CIMA. Habría que buscar publicaciones
  específicas (la búsqueda sugirió Rusticucci, Almeira y Suaya; sin verificar).

**Lectura:** hay una definición oficial reproducible (percentil 90, 3 días). Eso permite construir un catálogo
propio con ERA5 sin inventar criterios, y compararlo con el del SMN.

## 3. Licencias de datos

| Dato | Estado | Fuente |
|---|---|---|
| **ERA5** | CC BY 4.0 desde el 2 de julio de 2025 (Climate Data Store). CC BY permite uso comercial con atribución. Texto oficial: confirmar antes de vender | [Foro ECMWF](https://forum.ecmwf.int/t/cc-by-licence-to-replace-licence-to-use-copernicus-products-on-02-july-2025/13464), [Licencia ERA5](https://apps.ecmwf.int/datasets/licences/era5) |
| **CHIRPS** | Earth Engine lo declara dominio público, pero otra página lo describe "para investigación, educación y sin fines de lucro". Conflicto sin resolver | [Earth Engine](https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHG_CHIRPS_DAILY?hl=en); confirmar en chc.ucsb.edu/data |
| **SMN** | No encontré la licencia de uso comercial. Una disposición del SMN aclara que algunas series pueden pertenecer a terceros | [Disposición SMN](https://argentina.gob.ar/normativa/361173_disp25_pdf/archivo); consultar al organismo |

**Atribución ERA5:** ECMWF sugiere un aviso del tipo "ECMWF Reanalysis data (ERA5), © ECMWF, retrieved via the
Copernicus Climate Data Store. Licensed under CC-BY-4.0.", y "Modified from ECMWF products" si se modifica.

## Conclusión provisoria

- **ERA5 es la base más limpia:** licencia que, según lo hallado, permite uso comercial, cobertura global y
  atribución simple. CHIRPS y SMN requieren verificar antes de vender nada que dependa de ellos.
- **Heladas con ERA5 tiene un riesgo técnico:** la helada es un fenómeno local y de mínima temperatura cerca del
  suelo; la grilla de ERA5 (~25–30 km) puede suavizarla. Validar contra estaciones del SMN, y mejor con ERA5-Land
  (más fina; su cobertura y licencia confirmarlas).

## Pendiente

- [ ] Leer la licencia ERA5 en la página oficial y confirmar uso comercial
- [ ] Pedir al SMN las condiciones de uso comercial de sus series (smn@smn.gob.ar figura en la disposición)
- [ ] Confirmar la licencia de CHIRPS en chc.ucsb.edu/data
- [ ] Verificar licencia y resolución de ERA5-Land
- [ ] Buscar publicaciones de CIMA / Rusticucci sobre catálogos de olas de calor
- [ ] Pedir al INTA y a FAUBA los mapas y tablas de heladas
