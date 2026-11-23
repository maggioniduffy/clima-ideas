"""Promotion and demotion of outlook states (F6.8, evidence gate in plan/06-forecast.md).

Every (variable, region, lead, frozen model_version) is "Experimental" until the user approves a promotion to
"Perspectiva de riesgo"; any state change is a record in an append-only JSON Lines log with the same SHA-256
chain as the prediction registry (``registry.compute_record_hash``; ``verify()`` raises ``RegistryTamperError``).

``promote`` is never called by the workflow: it needs ``approved_by`` and ``approved_on`` (criterion 6) and
refuses unless: hindcast gate passed for that region/lead (F5.8.json ``pass_raw`` and ``pass_contiguous``,
criteria 1-2), a full wet season May-Sept is over with >= 10 independent pooled events and a prospective BSS
estimate >= 0 (criterion 5), and every shorter lead is already promoted for that variable/region/version or is
promoted earlier in the same call (criterion 2).

``demote_auto`` (criterion 7) sends a promoted lead back to "Experimental" when its prospective skill vs.
climatology is < 0 or when its model_version is not in force any more; it also demotes every longer lead of the
same variable/region. Idempotent: a lead that is already "Experimental" gets no new record.

For ``p_dia_riesgo`` the lead is the GEFS lead (the scoring table's ``lead``). State is per model_version, so a
new version starts "Experimental" (criterion 7).
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from clima_nqn.forecast.registry import RegistryTamperError, compute_record_hash

EXPERIMENTAL = "Experimental"
OUTLOOK = "Perspectiva de riesgo"
STATES = (EXPERIMENTAL, OUTLOOK)
MIN_POOLED_EVENTS = 10
SEASON_START_MONTH, SEASON_END = (5, (9, 30))  # wet season May 1 - Sept 30
_ZERO_HASH = "0" * 64


class StatusError(Exception):
    """Base class for status-log errors."""


class PromotionRefused(StatusError):
    """A promotion criterion is not met; ``reasons`` lists every failure (in Spanish)."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _utc_now() -> datetime:
    return datetime.now(UTC)


def season_end(season: int) -> date:
    """Last day of the wet season of calendar year ``season`` (30 September)."""
    return date(season, *SEASON_END)


class StatusLog:
    def __init__(self, path: Path, clock: Callable[[], datetime] = _utc_now) -> None:
        self.path = Path(path)
        self._clock = clock

    def now(self) -> datetime:
        return self._clock().astimezone(UTC)

    def read(self) -> list[dict[str, Any]]:
        return self._raw()

    def verify(self) -> str | None:
        """Check seq, links and hashes; return the head hash (None if empty) or raise RegistryTamperError."""
        prev = _ZERO_HASH
        for i, raw in enumerate(self._raw()):
            if raw.get("seq") != i:
                raise RegistryTamperError(f"status {i}: sequence broken (got {raw.get('seq')!r})")
            if raw.get("prev_hash") != prev:
                raise RegistryTamperError(
                    f"status {i}: prev_hash does not match the previous record"
                )
            if raw.get("record_hash") != compute_record_hash(raw):
                raise RegistryTamperError(f"status {i}: record_hash mismatch (edited)")
            prev = raw["record_hash"]
        return None if prev == _ZERO_HASH else prev

    def append_many(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append state changes (dicts with the schema fields minus seq/at/hashes), all or nothing."""
        if not entries:
            return []
        head = self.verify()  # refuse to extend a tampered chain
        existing = self._raw()
        at = self.now().isoformat(timespec="seconds")
        out, lines, prev = [], [], head or _ZERO_HASH
        for i, e in enumerate(entries):
            if e["to_state"] not in STATES or e["from_state"] not in STATES:
                raise StatusError(f"estado no válido: {e['from_state']!r} -> {e['to_state']!r}")
            body = {**e, "seq": len(existing) + i, "at": at, "prev_hash": prev}
            body["record_hash"] = prev = compute_record_hash(body)
            out.append(body)
            lines.append(json.dumps(body, sort_keys=True, ensure_ascii=False) + "\n")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write("".join(lines))
            f.flush()
            os.fsync(f.fileno())
        return out

    def _raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                obj = json.loads(line)
            except ValueError as e:
                raise RegistryTamperError(f"line {n}: not valid JSON") from e
            if not isinstance(obj, dict):
                raise RegistryTamperError(f"line {n}: not an object")
            out.append(obj)
        return out


def _records(log: StatusLog | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return log.read() if isinstance(log, StatusLog) else list(log)


def _states(log: StatusLog | Iterable[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """Latest record per (variable, region, lead, model_version)."""
    last: dict[tuple, dict[str, Any]] = {}
    for r in _records(log):
        last[(r["variable"], r["region"], int(r["lead"]), r["model_version"])] = r
    return last


def current_state(
    log: StatusLog | Iterable[dict[str, Any]],
    variable: str,
    region: str,
    lead: int,
    model_version: str,
) -> str:
    """State of one frozen version; "Experimental" when it never changed (a new version starts there)."""
    rec = _states(log).get((variable, region, int(lead), model_version))
    return EXPERIMENTAL if rec is None else rec["to_state"]


def _finite(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and math.isfinite(x) else None


def _season_row(
    rows: Iterable[Mapping[str, Any]],
    model: str,
    variable: str,
    region: str,
    lead: int,
    season: int | None = None,
) -> Mapping[str, Any] | None:
    """Row of scores/latest.json ``seasons``: the given season, or the latest COMPLETE one when None."""
    best = None
    for r in rows:
        if (
            r.get("model") == model
            and r.get("variable") == variable
            and str(r.get("station")) == region
            and int(r.get("lead", -1)) == int(lead)
            and (r.get("season") == season if season is not None else r.get("complete"))
            and (best is None or r["season"] > best["season"])
        ):
            best = r
    return best


def promote(
    log: StatusLog,
    *,
    variable: str,
    region: str,
    leads: Iterable[int],
    model_version: str,
    approved_by: str,
    approved_on: date | None,
    f58: Mapping[str, Any],
    f58_sha: str,
    season_rows: Iterable[Mapping[str, Any]],
    season: int,
    n_events_pooled_override: int | None = None,
    model: str = "logistica",
) -> list[dict[str, Any]]:
    """Promote ``leads`` (ascending, all or nothing) to "Perspectiva de riesgo"; raise PromotionRefused."""
    reasons: list[str] = []
    if not (approved_by or "").strip():
        reasons.append("falta la aprobación del usuario (approved_by)")
    if approved_on is None:
        reasons.append("falta la fecha de aprobación (approved_on)")
    elif approved_on > log.now().date():
        reasons.append("approved_on está en el futuro")
    lead_list = sorted({int(x) for x in leads})
    if not lead_list:
        reasons.append("sin anticipaciones")
    if reasons:
        raise PromotionRefused(reasons)  # nothing else is examined without approval

    now = log.now()
    rows = list(season_rows)
    states = _states(log)
    done = {
        k[2]
        for k, v in states.items()
        if k[:2] == (variable, region) and k[3] == model_version and v["to_state"] == OUTLOOK
    }
    entries, promoted_now = [], set()
    for lead in lead_list:
        why: list[str] = []
        if lead in done:
            continue  # already promoted: nothing to do for this lead
        missing = [k for k in range(1, lead) if k not in done and k not in promoted_now]
        if missing:
            why.append(f"anticipación {lead}: faltan las más cortas {missing} (criterio 2)")
        h = (f58.get("regions") or {}).get(region, {}).get(str(lead))
        if not h or not (h.get("pass_raw") and h.get("pass_contiguous")):
            why.append(f"anticipación {lead}: no pasa el hindcast (criterio 1)")
        if season_end(season) >= now.date():
            why.append(f"la temporada {season} (mayo–septiembre) no terminó (criterio 5)")
        row = _season_row(rows, model, variable, region, lead, season)
        if row is None:
            why.append(f"anticipación {lead}: sin fila de la temporada {season} en scores")
        elif not row.get("complete"):
            why.append(f"la temporada {season} no figura completa en scores (criterio 5)")
        n_pooled = (
            n_events_pooled_override
            if n_events_pooled_override is not None
            else (row.get("n_events_pooled") if row else None)
        )
        if n_pooled is None or n_pooled < MIN_POOLED_EVENTS:
            why.append(
                f"eventos independientes agrupados {n_pooled} < {MIN_POOLED_EVENTS} (criterio 5)"
            )
        bss = _finite(row.get("skill")) if row else None
        if bss is None:
            why.append(f"anticipación {lead}: sin BSS prospectivo (criterio 5)")
        elif bss < 0:
            why.append(f"anticipación {lead}: BSS prospectivo {bss:.3f} < 0 (criterio 5)")
        if why:
            reasons += why
            continue
        promoted_now.add(lead)
        entries.append(
            {
                "variable": variable,
                "region": region,
                "lead": lead,
                "model_version": model_version,
                "from_state": states.get((variable, region, lead, model_version), {}).get(
                    "to_state", EXPERIMENTAL
                ),
                "to_state": OUTLOOK,
                "reason": "promoción aprobada: compuerta de evidencia (criterios 1-7)",
                "evidence": {
                    "hindcast": {
                        "pass_raw": True,
                        "pass_contiguous": True,
                        "status": h.get("status"),
                        "f58_sha256": f58_sha,
                    },
                    "prospective": {
                        "model": model,
                        "n": row.get("n") if row else None,
                        "n_events_pooled": n_pooled,
                        "n_events_pooled_override": n_events_pooled_override is not None,
                        "season": season,
                        "bss": bss,
                        "ci": [_finite(row.get("skill_ci_low")), _finite(row.get("skill_ci_high"))],
                    },
                },
                "approved_by": approved_by.strip(),
                "approved_on": approved_on.isoformat(),
            }
        )
    if reasons:
        raise PromotionRefused(reasons)
    return log.append_many(entries)


def demote_auto(
    log: StatusLog,
    season_rows: Iterable[Mapping[str, Any]],
    versions_in_force: Collection[str],
) -> list[dict[str, Any]]:
    """Automatic demotion (criterion 7). Returns the new records (empty when nothing changes)."""
    rows = list(season_rows)
    promoted = {k: v for k, v in _states(log).items() if v["to_state"] == OUTLOOK}
    seasons: dict[tuple, int] = {}
    trigger: dict[
        tuple, tuple[int, str]
    ] = {}  # (variable, region, version) -> (lowest lead, reason)
    for (variable, region, lead, version), rec in promoted.items():
        reason = None
        if version not in versions_in_force:
            reason = "cambio de versión del modelo o de sus entradas"
        else:
            model = (rec.get("evidence", {}).get("prospective") or {}).get("model", "logistica")
            row = _season_row(rows, model, variable, region, lead)  # latest complete season
            bss = _finite(row.get("skill")) if row else None
            if bss is not None and bss < 0:
                reason = f"BSS prospectivo {bss:.3f} < 0 en la temporada {row['season']}"
                seasons[(variable, region, version)] = int(row["season"])
        if reason:
            k = (variable, region, version)
            if k not in trigger or lead < trigger[k][0]:
                trigger[k] = (lead, f"anticipación {lead}: {reason}")
    entries = []
    for (variable, region, lead, version), _rec in sorted(promoted.items()):
        t = trigger.get((variable, region, version))
        if t is None or lead < t[0]:
            continue
        reason = t[1] if lead == t[0] else f"arrastrada por la anticipación {t[0]} ({t[1]})"
        entries.append(
            {
                "variable": variable,
                "region": region,
                "lead": lead,
                "model_version": version,
                "from_state": OUTLOOK,
                "to_state": EXPERIMENTAL,
                "reason": "descenso automático: " + reason,
                "evidence": {"prospective": {"season": seasons.get((variable, region, version))}},
                "approved_by": None,
                "approved_on": None,
            }
        )
    return log.append_many(entries)
