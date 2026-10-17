"""Plain dict views of models for API responses (kept explicit so nothing
sensitive is returned by accident)."""

from jobpilot.db import models as m


def fact(f: m.ProfileFact) -> dict:
    return {"id": f.id, "category": f.category, "key": f.key, "value": f.value, "context": f.context,
            "verified": f.verified, "source_note": f.source_note}


def evaluation(e: m.JobMatchEvaluation | None) -> dict | None:
    if e is None:
        return None
    return {"id": e.id, "score": e.score, "breakdown": e.breakdown, "weights": e.weights, "track": e.track,
            "seniority": e.seniority, "recommendation": e.recommendation, "eligibility": e.eligibility,
            "matched_skills": e.matched_skills, "missing_skills": e.missing_skills,
            "explanation": e.explanation, "evidence": e.evidence, "model_version": e.model_version,
            "profile_version_id": e.profile_version_id, "created_at": e.created_at}


def job(j: m.Job, ev: m.JobMatchEvaluation | None = None, app: m.Application | None = None,
        detail: bool = False) -> dict:
    out = {
        "id": j.id, "company": j.company, "title": j.title, "country": j.country, "city": j.city,
        "location_text": j.location_text, "work_mode": j.work_mode, "employment_type": j.employment_type,
        "seniority": j.seniority, "skills": j.skills, "language_reqs": j.language_reqs,
        "salary_min": float(j.salary_min) if j.salary_min is not None else None,
        "salary_max": float(j.salary_max) if j.salary_max is not None else None,
        "currency": j.currency, "published_at": j.published_at, "retrieved_at": j.retrieved_at,
        "availability": j.availability, "url": j.url, "source": j.source.code, "source_name": j.source.name,
        "duplicate_of_id": j.duplicate_of_id,
        "evaluation": evaluation(ev),
        "application": {"id": app.id, "state": app.state, "state_version": app.state_version,
                        "decision": app.decision} if app else None,
    }
    if detail:
        out["description_text"] = j.description_text
    return out


def application_row(a: m.Application, score: int | None) -> dict:
    j = a.job
    return {"id": a.id, "job_id": j.id, "company": j.company, "role": j.title, "country": j.country,
            "city": j.city, "score": score, "state": a.state, "state_version": a.state_version,
            "decision": a.decision, "applied_on": a.submitted_at, "last_action": a.last_action,
            "last_action_at": a.last_action_at, "next_follow_up": a.next_follow_up, "outcome": a.outcome,
            "source_url": j.url, "discovered_at": a.created_at}


def history(h: m.ApplicationStateHistory) -> dict:
    return {"from_state": h.from_state, "to_state": h.to_state, "actor": h.actor, "reason": h.reason, "at": h.at}


def run(r: m.SearchRun) -> dict:
    return {"id": r.id, "config_id": r.config_id, "trigger": r.trigger, "status": r.status,
            "started_at": r.started_at, "finished_at": r.finished_at, "summary": r.summary}


def source(s: m.JobSource) -> dict:
    if s.access_mode == "mock":
        label = "Mock"
    elif s.access_mode == "manual":
        label = "Manual"
    elif s.implemented:
        label = "Automated"
    else:
        label = "Planned"
    return {"code": s.code, "name": s.name, "access_mode": s.access_mode, "implemented": s.implemented,
            "enabled": s.enabled, "label": label, "notes": s.notes}
