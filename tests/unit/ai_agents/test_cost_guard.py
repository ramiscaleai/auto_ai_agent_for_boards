"""Unit tests for ai_agents/cost_guard.py — per-task + daily caps, rollover, free-tier bypass."""
from datetime import date
from pathlib import Path

import pytest

from ai_agents.base import AgentResult
from ai_agents.cost_guard import CostGuard
from ai_agents.errors import BudgetExceededError


class _FakeAgent:
    def __init__(self, cost_tier: str, name: str = "fake") -> None:
        self.cost_tier = cost_tier
        self.name = name


def _result(cost_usd):
    return AgentResult(
        success=True, summary="", files_changed=[], output="",
        cost_usd=cost_usd, duration_s=1.0,
    )


def test_free_tier_bypasses_precheck(tmp_path: Path):
    guard = CostGuard(per_task_cap_usd=0.50, daily_cap_usd=5.00, state_path=tmp_path / "s.json")
    guard.precheck(_FakeAgent("free"))  # must not raise


def test_precheck_passes_when_under_daily_cap(tmp_path: Path):
    guard = CostGuard(per_task_cap_usd=10.00, daily_cap_usd=5.00, state_path=tmp_path / "s.json")
    guard.record(_result(1.00))
    guard.precheck(_FakeAgent("high"))  # 1.00 < 5.00 — OK


def test_precheck_raises_when_over_daily_cap(tmp_path: Path):
    guard = CostGuard(per_task_cap_usd=10.00, daily_cap_usd=5.00, state_path=tmp_path / "s.json")
    guard.record(_result(5.00))  # spend exactly at cap
    with pytest.raises(BudgetExceededError):
        guard.precheck(_FakeAgent("high"))


def test_record_is_no_op_for_none_cost(tmp_path: Path):
    state_path = tmp_path / "s.json"
    guard = CostGuard(per_task_cap_usd=0.50, daily_cap_usd=5.00, state_path=state_path)
    guard.record(_result(None))  # subscription tier — no cost
    assert not state_path.exists()  # nothing persisted


def test_per_task_cap_breach_raises_but_still_records(tmp_path: Path):
    state_path = tmp_path / "s.json"
    guard = CostGuard(per_task_cap_usd=0.50, daily_cap_usd=5.00, state_path=state_path)
    with pytest.raises(BudgetExceededError):
        guard.record(_result(0.75))
    # but the spend IS persisted
    guard2 = CostGuard(per_task_cap_usd=0.50, daily_cap_usd=5.00, state_path=state_path)
    assert guard2._today_spend() == pytest.approx(0.75)


def test_date_rollover_resets_daily_spend(tmp_path: Path, monkeypatch):
    state_path = tmp_path / "s.json"
    guard = CostGuard(per_task_cap_usd=0.50, daily_cap_usd=5.00, state_path=state_path)
    guard.record(_result(0.10))
    assert guard._today_spend() == pytest.approx(0.10)
    # Simulate "tomorrow" by patching the module-level _today_iso() function.
    import ai_agents.cost_guard as mod
    tomorrow = date.fromordinal(date.today().toordinal() + 1).isoformat()
    monkeypatch.setattr(mod, "_today_iso", lambda: tomorrow)
    assert guard._today_spend() == pytest.approx(0.0)


def test_rollover_preserves_yesterdays_data(tmp_path: Path, monkeypatch):
    """Rollover shows 0 for today but keeps yesterday's record intact on disk."""
    import json

    import ai_agents.cost_guard as mod
    state_path = tmp_path / "s.json"
    guard = CostGuard(per_task_cap_usd=0.50, daily_cap_usd=5.00, state_path=state_path)
    today_iso = date.today().isoformat()
    guard.record(_result(0.10))
    tomorrow = date.fromordinal(date.today().toordinal() + 1).isoformat()
    monkeypatch.setattr(mod, "_today_iso", lambda: tomorrow)
    assert guard._today_spend() == pytest.approx(0.0)
    on_disk = json.loads(state_path.read_text())
    assert on_disk[today_iso] == pytest.approx(0.10)           # yesterday's entry survives
    assert tomorrow not in on_disk                              # no write for tomorrow yet


def test_corrupt_state_file_resets_and_warns(tmp_path: Path, caplog):
    """A corrupted JSON file is treated as empty; a warning is logged."""
    state_path = tmp_path / "s.json"
    state_path.write_text("{not valid json")
    guard = CostGuard(per_task_cap_usd=0.50, daily_cap_usd=5.00, state_path=state_path)
    with caplog.at_level("WARNING", logger="ai_agents.cost_guard"):
        assert guard._today_spend() == pytest.approx(0.0)
    assert any("Unreadable spend state" in r.message for r in caplog.records)
