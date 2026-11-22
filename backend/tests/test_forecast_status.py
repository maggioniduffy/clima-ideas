"""F6.8: promotion and automatic demotion of outlook states."""

from datetime import UTC, date, datetime

import pytest

from clima_nqn.forecast.registry import RegistryTamperError
from clima_nqn.forecast.status import (
    EXPERIMENTAL,
    OUTLOOK,
    PromotionRefused,
    StatusLog,
    current_state,
    demote_auto,
    promote,
)

NOW = datetime(2027, 10, 15, 12, 0, tzinfo=UTC)  # after the 2027 season
VAR, REG, VER = "p_dia_riesgo", "cordillera_norte", "riskday-log-v1-abcd1234"


def f58(passing=(1, 2, 3)):
    return {
        "regions": {
            REG: {
                str(k): {"pass_raw": k in passing, "pass_contiguous": k in passing, "status": "x"}
                for k in range(1, 11)
            }
        }
    }


def rows(skill=0.2, leads=(1, 2, 3)):
    return [
        {
            "model": "logistica",
            "variable": VAR,
            "station": REG,
            "lead": k,
            "n": 100,
            "skill": skill,
            "skill_ci_low": skill - 0.1,
            "skill_ci_high": skill + 0.1,
        }
        for k in leads
    ]


def call(log, leads=(1,), **over):
    kw = {
        "variable": VAR,
        "region": REG,
        "leads": leads,
        "model_version": VER,
        "approved_by": "usuario",
        "approved_on": date(2027, 10, 15),
        "f58": f58(),
        "f58_sha": "a" * 64,
        "score_rows": rows(),
        "n_events_pooled": 12,
        "season": 2027,
    }
    kw.update(over)
    return promote(log, **kw)


@pytest.fixture
def log(tmp_path):
    return StatusLog(tmp_path / "status" / "outlook.jsonl", clock=lambda: NOW)


def test_default_experimental(log):
    assert current_state(log, VAR, REG, 1, VER) == EXPERIMENTAL


def test_promotes_in_order_with_evidence(log):
    recs = call(log, leads=(1, 2, 3))
    assert [r["lead"] for r in recs] == [1, 2, 3]
    assert current_state(log, VAR, REG, 3, VER) == OUTLOOK
    ev = recs[0]["evidence"]
    assert ev["hindcast"]["f58_sha256"] == "a" * 64 and ev["prospective"]["n_events_pooled"] == 12
    assert recs[0]["approved_by"] == "usuario" and recs[0]["approved_on"] == "2027-10-15"
    assert log.verify() == recs[-1]["record_hash"]


@pytest.mark.parametrize(
    "over", [{"approved_by": ""}, {"approved_by": "  "}, {"approved_on": None}]
)
def test_no_promotion_without_approval(log, over):
    with pytest.raises(PromotionRefused):
        call(log, **over)
    assert log.read() == []


def test_no_promotion_with_skipped_leads(log):
    with pytest.raises(PromotionRefused, match="más cortas"):
        call(log, leads=(2,))
    with pytest.raises(PromotionRefused, match="más cortas"):
        call(log, leads=(1, 3))
    assert log.read() == []  # all or nothing


def test_contiguity_uses_already_promoted(log):
    call(log, leads=(1,))
    call(log, leads=(2,))
    assert current_state(log, VAR, REG, 2, VER) == OUTLOOK


def test_no_promotion_before_full_season(tmp_path):
    early = StatusLog(tmp_path / "s.jsonl", clock=lambda: datetime(2027, 8, 1, tzinfo=UTC))
    with pytest.raises(PromotionRefused, match="no terminó"):
        call(early, approved_on=date(2027, 8, 1))


def test_no_promotion_with_few_events(log):
    with pytest.raises(PromotionRefused, match="eventos"):
        call(log, n_events_pooled=9)
    with pytest.raises(PromotionRefused, match="eventos"):
        call(log, n_events_pooled=None)


def test_no_promotion_with_negative_bss(log):
    with pytest.raises(PromotionRefused, match="BSS"):
        call(log, score_rows=rows(skill=-0.01))
    with pytest.raises(PromotionRefused, match="sin BSS"):
        call(log, score_rows=[])


def test_no_promotion_without_hindcast_pass(log):
    with pytest.raises(PromotionRefused, match="hindcast"):
        call(log, f58=f58(passing=()))


def test_demote_on_negative_season_bss(log):
    call(log, leads=(1,))
    done = demote_auto(log, rows(skill=-0.05), {VER})
    assert [r["lead"] for r in done] == [1]
    assert done[0]["to_state"] == EXPERIMENTAL and done[0]["approved_by"] is None
    assert current_state(log, VAR, REG, 1, VER) == EXPERIMENTAL


def test_no_demotion_when_fine(log):
    call(log, leads=(1, 2))
    assert demote_auto(log, rows(), {VER}) == []


def test_demote_on_version_change_and_new_version_is_experimental(log):
    call(log, leads=(1, 2))
    done = demote_auto(log, rows(), {"riskday-log-v1-ffff0000"})
    assert len(done) == 2 and "versión" in done[0]["reason"]
    assert current_state(log, VAR, REG, 1, "riskday-log-v1-ffff0000") == EXPERIMENTAL


def test_demoting_lead_drags_longer_leads(log):
    call(log, leads=(1, 2, 3))
    bad = rows()
    bad[1]["skill"] = -0.1  # lead 2 only
    done = demote_auto(log, bad, {VER})
    assert [r["lead"] for r in done] == [2, 3]
    assert "arrastrada" in done[1]["reason"]
    assert current_state(log, VAR, REG, 1, VER) == OUTLOOK


def test_demote_is_idempotent(log):
    call(log, leads=(1, 2))
    assert len(demote_auto(log, rows(skill=-1), {VER})) == 2
    n = len(log.read())
    assert demote_auto(log, rows(skill=-1), {VER}) == []
    assert len(log.read()) == n


def test_tamper_detected(log):
    call(log, leads=(1, 2))
    log.verify()
    text = log.path.read_text(encoding="utf-8")
    log.path.write_text(text.replace("usuario", "otro"), encoding="utf-8")
    with pytest.raises(RegistryTamperError):
        log.verify()
    with pytest.raises(RegistryTamperError):
        call(log, leads=(3,))  # refuses to extend a tampered chain
    lines = text.splitlines()
    log.path.write_text("\n".join(lines[::-1]) + "\n", encoding="utf-8")
    with pytest.raises(RegistryTamperError):
        log.verify()
