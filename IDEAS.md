# Ideas

Estado: borrador. Cada idea tiene los mismos campos. Los datos candidatos son hipótesis: verificar
disponibilidad, resolución y licencia antes de usarlos.

## Tarea global pendiente

- [ ] **Buscar competidores y herramientas actuales similares.** Para cada idea: productos comerciales y
      gratuitos, servicios del SMN, INA, CIMA y de organismos internacionales, librerías open source. Anotar qué
      cubren, precio y licencia, y qué hueco queda. Cada hallazgo con su URL; lo no verificado, "sin verificar".

---

## 1. Agro: sequías, olas de calor y heladas

- **Problema:** falta de un catálogo histórico de eventos agroclimáticos en la región pampeana, con frecuencia
  por zona, útil para seguros paramétricos.
- **Eventos a detectar:** sequías (déficit de precipitación o humedad de suelo), olas de calor, heladas.
- **Datos candidatos:** ERA5 / ERA5-Land, CHIRPS, estaciones del SMN (licencias a verificar).
- **Herramienta:** xarray primero. TECA solo si se trabaja con muchos modelos o años a gran resolución.
- **Posible usuario:** aseguradoras, cooperativas, consultoras agro (sin verificar).
- **Riesgos:** reanálisis con sesgo local; heladas dependen de la topografía fina; definiciones de evento
  discutibles.
- **Primer paso:** un solo índice (p. ej. días con mínima < 0 °C) sobre una provincia y 30 años, comparado
  con estaciones.
- [ ] Buscar competidores / herramientas similares

## 2. Energía: bajo viento, baja radiación y calor extremo

- **Problema:** cuantificar cuándo y cuánto caen la generación eólica y solar y cuándo sube la demanda por
  calor.
- **Eventos a detectar:** períodos de viento bajo, de radiación baja, y olas de calor.
- **Datos candidatos:** ERA5 (viento a 100 m, radiación), otros reanálisis regionales (a verificar).
- **Herramienta:** xarray; TECA solo para detección de eventos a gran escala.
- **Posible usuario:** generadores, comercializadores, operadores del mercado eléctrico (sin verificar).
- **Riesgos:** ERA5 no reemplaza mediciones en parque; sin datos de generación o demanda reales no hay
  vínculo causal.
- **Primer paso:** catálogo de eventos de viento bajo sobre una zona de parques, 20 años.
- [ ] Buscar competidores / herramientas similares

## 3. Alerta temprana y planificación urbana

- **Problema:** relacionar tormentas severas, sudestadas y lluvias extremas con inundaciones urbanas en
  Buenos Aires, Rosario y Córdoba.
- **Eventos a detectar:** lluvias intensas, ciclogénesis y sudestadas, sistemas convectivos.
- **Datos candidatos:** ERA5, IMERG, CHIRPS, mareógrafos y estaciones (a verificar).
- **Herramienta:** xarray para lluvia; TECA sirve para ciclones extratropicales. Los sistemas convectivos
  requerirían un detector propio.
- **Posible usuario:** municipios, defensa civil, planificación (sin verificar).
- **Riesgos:** la resolución de reanálisis no captura convección local; una alerta real exige operación
  continua y responsabilidad.
- **Primer paso:** catálogo retrospectivo de eventos para una ciudad, contrastado con eventos conocidos.
- [ ] Buscar competidores / herramientas similares

## 4. Climatologías para municipios y defensa civil

- **Problema:** responder "qué tan raro fue este evento y cada cuánto se repite".
- **Eventos a detectar:** extremos de precipitación y temperatura; períodos de retorno.
- **Datos candidatos:** series largas de estaciones y reanálisis (a verificar).
- **Herramienta:** estadística de extremos en Python (no requiere TECA).
- **Posible usuario:** municipios, defensa civil (sin verificar).
- **Riesgos:** series cortas o con huecos; incertidumbre de los períodos de retorno; comunicar rangos, no
  un valor único.
- **Primer paso:** una ciudad, una variable, con intervalo de confianza.
- [ ] Buscar competidores / herramientas similares
