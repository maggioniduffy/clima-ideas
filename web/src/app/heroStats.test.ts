import { es } from "../i18n/es";
import { heroStats } from "./heroStats";

test("no input gives no numbers", () => {
  expect(heroStats({})).toEqual([]);
});

test("events layer gives shown and total", () => {
  expect(heroStats({ events: { shown: 12, total: 40 } })).toEqual([
    { id: "events-shown", value: 12, caption: es.hero.eventsShown },
    { id: "events-total", value: 40, caption: es.hero.eventsTotal },
  ]);
});

test("points layers use the station caption only for flood stations and skip empty lists", () => {
  expect(heroStats({ points: { count: 7, station: true } })[0].caption).toBe(es.hero.stations);
  expect(heroStats({ points: { count: 7, station: false } })[0].caption).toBe(es.hero.points);
  expect(heroStats({ points: { count: 0, station: false } })).toEqual([]);
});

test("catchments count is kept even when 0 and never more than 3 numbers", () => {
  expect(heroStats({ catchments: 0 })).toEqual([{ id: "catchments", value: 0, caption: es.hero.catchments }]);
  expect(heroStats({ events: { shown: 1, total: 2 }, points: { count: 3, station: false }, catchments: 4 })).toHaveLength(3);
});
