from jobpilot.db import models as m
from jobpilot.db.session import SessionLocal
from jobpilot.monitor import service

from tests.conftest import run_mock_search, verify_facts


def _ai_call(agent: str, cost: float, tin=1000, tout=200):
    with SessionLocal() as db:
        ar = m.AgentRun(agent=agent, subject="x", status="succeeded")
        db.add(ar)
        db.flush()
        db.add(m.TaskAttempt(agent_run_id=ar.id, attempt_no=1, status="succeeded", ai_tokens_in=tin,
                             ai_tokens_out=tout, ai_cost_usd=cost))
        db.commit()


def test_usage_adds_up_cost_tokens_runs_and_funnel(api):
    verify_facts(api)
    run_mock_search(api)
    _ai_call("matching", 0.10)
    _ai_call("matching", 0.05)
    _ai_call("documents", 0.20, tin=3000, tout=1500)
    u = api.get("/usage?days=7").json()
    assert u["ai"]["total_cost_usd"] == 0.35 and u["ai"]["today_cost_usd"] == 0.35
    by_agent = {a["agent"]: a for a in u["ai"]["per_agent"]}
    assert by_agent["matching"]["calls"] == 2 and by_agent["documents"]["tokens_out"] == 1500
    assert u["ai"]["per_agent"][0]["agent"] == "documents"  # most expensive first
    assert u["ai"]["budget_used_pct"] == 35.0  # default budget $1/day
    assert u["searches"]["runs"] == {"completed": 1} and u["searches"]["new_jobs"] == 8  # 7 open + 1 closed listing
    assert u["applications"]["funnel"]["classified"] == 7


def test_budget_alert_when_most_of_the_daily_budget_is_spent(api):
    _ai_call("matching", 0.85)
    service.run_once()
    a = next(a for a in api.get("/alerts").json() if a["alert_key"] == "mon:ai-budget")
    assert a["severity"] == "info" and "rule-based" in a["remediation"]
    _ai_call("matching", 0.20)
    service.run_once()
    a = next(a for a in api.get("/alerts").json() if a["alert_key"] == "mon:ai-budget")
    assert a["severity"] == "warning" and "used up" in a["title"]
