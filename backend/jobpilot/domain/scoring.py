"""Deterministic scoring model `rules-v0`.

Phase 1 placeholder for the matching agent: keyword rules, no AI. It uses ONLY
verified profile facts, applies hard eligibility rules separately from the score,
and records evidence for every point it awards. Phase 2 replaces the judgment
parts with Claude while keeping this arithmetic and these eligibility rules.
"""

import re
from dataclasses import dataclass, field

DEFAULT_WEIGHTS = {"technical": 30, "experience": 25, "track": 20, "language": 10, "location": 15}
THRESHOLDS = {"apply": 75, "review": 55}

TECH_VOCAB = [
    "java", "kotlin", "c++", "python", "android", "aosp", "jni", "aidl", "hal", "camera2", "camerax",
    "spring boot", "spring mvc", "spring", "rest", "jpa", "hibernate", "mysql", "postgresql", "sql",
    "maven", "gradle", "docker", "kubernetes", "aws", "linux", "embedded", "autosar", "qt", "react",
    "typescript", "javascript", "go", "rust", "git", "jetpack compose", "c#", ".net",
]

TRACK_KEYWORDS = {
    "D": ["werkstudent", "working student", "intern", "internship", "praktikum", "praktikant", "graduate programme",
          "trainee", "thesis", "abschlussarbeit"],
    "C": ["embedded", "automotive", "c++", "hal", "infotainment", "firmware"],
    "A": ["android", "kotlin", "mobile", "aosp"],
    "B": ["java", "backend", "spring", "graduate software", "entry-level software", "software engineer"],
}

STUDENT_WORDS = ["werkstudent", "working student", "intern", "internship", "praktikum", "praktikant", "student",
                 "thesis", "abschlussarbeit"]
JUNIOR_WORDS = ["junior", "graduate", "entry", "entry-level", "berufseinsteiger", "einsteiger", "trainee"]
SENIOR_WORDS = ["senior", "lead", "principal", "staff", "head of", "architect"]
WORK_AUTH_PATTERNS = [
    r"eu citizen", r"unrestricted work (permit|authori[sz]ation)", r"uneingeschränkte arbeitserlaubnis",
    r"right to work", r"no (visa )?sponsorship",
]
GERMAN_REQ = re.compile(r"(german|deutsch)[^.\n]{0,40}(c1|c2|b2|fluent|fließend|verhandlungssicher|sehr gut)", re.I)
GERMAN_ANY = re.compile(r"\b(german|deutsch(kenntnisse)?)\b", re.I)
CEFR = ["a1", "a2", "b1", "b2", "c1", "c2", "native"]
EU_COUNTRIES = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
                "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "CH", "NO"}


@dataclass
class ProfileView:
    """Only verified facts, flattened for scoring."""

    version_id: str
    skills: dict[str, str]  # skill lowercased -> fact id
    eligibility: dict[str, tuple[str, str]]  # key -> (value, fact id)
    languages: dict[str, tuple[str, str]]  # language -> (level, fact id)
    unverified_count: int = 0
    other_fact_ids: list[str] = field(default_factory=list)  # verified education/employment/project facts
    facts_for_ai: list[dict] = field(default_factory=list)  # verified facts as {id, category, key, value, context}


@dataclass
class Result:
    score: int
    breakdown: dict
    track: str
    seniority: str
    recommendation: str
    eligibility: dict
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: str
    evidence: list[dict] = field(default_factory=list)


def _has(text: str, word: str) -> bool:
    if word in ("c++", "c#", ".net"):
        return word in text
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


def extract_skills(text: str) -> list[str]:
    t = text.lower()
    found = [w for w in TECH_VOCAB if _has(t, w)]
    # "spring boot" implies "spring"; keep the specific one only
    if "spring boot" in found or "spring mvc" in found:
        found = [w for w in found if w != "spring"]
    return found


def detect_seniority(title: str, description: str) -> str:
    t = title.lower()
    if any(_has(t, w) for w in STUDENT_WORDS):
        return "student"
    if any(_has(t, w) for w in SENIOR_WORDS):
        return "senior"
    if any(_has(t, w) for w in JUNIOR_WORDS):
        return "junior"
    d = description.lower()
    years = re.search(r"(\d+)\+?\s*(years|jahre)", d)
    if years:
        n = int(years.group(1))
        return "junior" if n <= 2 else ("mid" if n <= 4 else "senior")
    return "unknown"


def detect_track(title: str, description: str) -> str:
    t = f"{title} {description[:400]}".lower()
    for track in ("D", "C", "A", "B"):
        if any(_has(t, k) for k in TRACK_KEYWORDS[track]):
            return track
    return "other"


def detect_languages(description: str) -> list[dict]:
    reqs = []
    m = GERMAN_REQ.search(description)
    if m:
        word = m.group(2).lower()
        level = word.upper() if word in ("b2", "c1", "c2") else "fluent"
        reqs.append({"language": "german", "level": level, "mandatory": True})
    elif GERMAN_ANY.search(description):
        reqs.append({"language": "german", "level": "unspecified", "mandatory": False})
    if re.search(r"\benglish\b|\benglisch\b", description, re.I):
        reqs.append({"language": "english", "level": "unspecified", "mandatory": False})
    return reqs


def _quote(text: str, needle: str, width: int = 60) -> str:
    i = text.lower().find(needle.lower())
    if i < 0:
        return needle
    start = max(0, i - width // 2)
    return text[start : start + width].replace("\n", " ").strip()


@dataclass
class Extraction:
    """What a matcher read from a posting. Scores are computed from this by code."""

    track: str
    seniority: str
    required_skills: list[str]
    matched: dict[str, tuple[str, str]]  # skill -> (verified fact id, quote from the job)
    language_reqs: list[dict]
    requirements: list[dict] = field(default_factory=list)  # {text, category, status, fact_id, job_quote}
    summary: str = ""
    matcher: str = "rules"


SENIORITY_SHARE = {"junior": 1.0, "intern": 0.6, "student": 0.6, "unknown": 0.5, "mid": 0.45, "senior": 0.0}


def rules_extract(job: dict, profile: ProfileView) -> Extraction:
    """`rules-v0`: keyword extraction, no AI."""
    desc = job.get("description_text") or ""
    title = job.get("title") or ""
    full = f"{title}\n{desc}"
    required = job.get("skills") or extract_skills(full)
    return Extraction(
        track=detect_track(title, desc),
        seniority=job.get("seniority") or detect_seniority(title, desc),
        required_skills=required,
        matched={s: (profile.skills[s], _quote(full, s)) for s in required if s in profile.skills},
        language_reqs=job.get("language_reqs") or detect_languages(desc),
    )


def _cefr(level: str) -> int | None:
    level = (level or "").lower().strip()
    return CEFR.index(level) if level in CEFR else None


def score_extraction(ex: Extraction, job: dict, profile: ProfileView, weights: dict | None = None,
                     thresholds: dict | None = None, preferred_countries: list[str] | None = None) -> Result:
    """Deterministic arithmetic and hard eligibility rules, shared by every matcher."""
    w = weights or DEFAULT_WEIGHTS
    th = thresholds or THRESHOLDS
    desc = job.get("description_text") or ""
    evidence: list[dict] = []
    uncertain: list[str] = []
    failed: list[str] = []

    # Technical skills: share of required skills backed by a verified fact
    required = list(dict.fromkeys(ex.required_skills))
    matched = [s for s in required if s in ex.matched]
    missing = [s for s in required if s not in ex.matched]
    tech = round(w["technical"] * len(matched) / len(required)) if required else 0
    for s in matched:
        fact_id, quote = ex.matched[s]
        evidence.append({"criterion": "technical", "job_quote": quote, "fact_id": fact_id, "skill": s})
    if not required:
        uncertain.append("No recognizable technical skills in the description")

    seniority = ex.seniority if ex.seniority in SENIORITY_SHARE else "unknown"
    exp = round(w["experience"] * SENIORITY_SHARE[seniority])
    evidence.append({"criterion": "experience", "job_quote": job.get("title") or "", "fact_id": None})

    track = ex.track if ex.track in ("A", "B", "C", "D", "other") else "other"
    trk = w["track"] if track in ("A", "B", "C", "D") else round(w["track"] * 0.25)

    lang = w["language"]
    for req in ex.language_reqs:
        if not req.get("mandatory"):
            continue
        name = req["language"].lower()
        have = profile.languages.get(name)
        need = _cefr(req.get("level", "")) if _cefr(req.get("level", "")) is not None else _cefr("c1")
        if have is None:
            lang = min(lang, round(w["language"] * 0.5))
            uncertain.append(f"{name.title()} ({req.get('level', 'level unspecified')}) required; "
                             "your level is not verified")
        elif _cefr(have[0]) is not None and _cefr(have[0]) < need:
            lang = 0
            failed.append(f"{name.title()} ({req.get('level')}) required; verified level is {have[0]}")
        else:
            evidence.append({"criterion": "language", "job_quote": _quote(desc, name), "fact_id": have[1]})

    country = (job.get("country") or "").upper()
    prefs = [c.upper() for c in (preferred_countries or ["DE"])]
    if job.get("work_mode") == "remote" and country in EU_COUNTRIES:
        loc = w["location"]
    elif country and country == prefs[0]:
        loc = w["location"]
    elif country in prefs or country in EU_COUNTRIES:
        loc = round(w["location"] * 0.66)
    else:
        loc = round(w["location"] * 0.2)
        if not country:
            uncertain.append("Country unknown")

    # Hard eligibility rules (separate from the score)
    if seniority in ("student", "intern") or track == "D":
        enrol = profile.eligibility.get("enrolment_status")
        if enrol is None or not enrol[0]:
            uncertain.append("Student position: your enrolment status is not verified")
        elif enrol[0].lower() not in ("enrolled", "immatrikuliert"):
            failed.append(f"Student position requires enrolment; verified status is '{enrol[0]}'")
    mentions_auth = any(re.search(p, desc, re.I) for p in WORK_AUTH_PATTERNS) or any(
        r.get("category") == "work_authorization" for r in ex.requirements)
    if mentions_auth and not (profile.eligibility.get("work_authorization") or ("", ""))[0]:
        uncertain.append("Listing mentions work-authorization limits; yours is not verified")
    verified_ids = set(profile.skills.values()) | {v[1] for v in profile.eligibility.values()} | {
        v[1] for v in profile.languages.values()} | set(profile.other_fact_ids)
    for r in ex.requirements:
        text = r.get("text", "")[:200]
        if r.get("status") == "not_met" and r.get("fact_id") in verified_ids:
            failed.append(f"Mandatory requirement not met: {text}")
        elif r.get("status") != "met" and r.get("category") in ("education", "experience", "other", "skill"):
            uncertain.append(f"Check requirement: {text}")
        elif r.get("status") == "met" and r.get("fact_id") in verified_ids:
            evidence.append({"criterion": "requirement", "job_quote": r.get("job_quote", ""), "fact_id": r["fact_id"]})
    if seniority == "senior":
        uncertain.append("Senior role: asks for more experience than your verified profile shows")

    breakdown = {"technical": tech, "experience": exp, "track": trk, "language": lang, "location": loc}
    score = int(sum(breakdown.values()))
    uncertain = list(dict.fromkeys(uncertain))
    failed = list(dict.fromkeys(failed))

    if failed:
        rec = "reject"
    elif seniority == "senior":
        rec = "low_priority"
    elif score >= th["apply"]:
        rec = "review" if uncertain else "apply"
    elif score >= th["review"]:
        rec = "review"
    else:
        rec = "low_priority"

    label = "Claude-assisted" if ex.matcher == "claude" else "Rule-based"
    parts = [f"{label} score {score}/100 (track {track}, {seniority})."]
    if ex.summary:
        parts.append(ex.summary.strip())
    if matched:
        parts.append(f"Matches verified skills: {', '.join(matched)}.")
    if missing:
        parts.append(f"Not in your verified skills: {', '.join(missing)}.")
    if profile.unverified_count:
        parts.append(f"{profile.unverified_count} unverified profile facts were ignored.")

    return Result(score=score, breakdown=breakdown, track=track, seniority=seniority, recommendation=rec,
                  eligibility={"failed": failed, "uncertain": uncertain}, matched_skills=matched,
                  missing_skills=missing, explanation=" ".join(parts), evidence=evidence)


def score_job(job: dict, profile: ProfileView, weights: dict | None = None,
              preferred_countries: list[str] | None = None, thresholds: dict | None = None) -> Result:
    """Rule-based matcher end to end (`rules-v0`)."""
    return score_extraction(rules_extract(job, profile), job, profile, weights, thresholds, preferred_countries)
