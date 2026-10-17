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


def score_job(job: dict, profile: ProfileView, weights: dict | None = None,
              preferred_countries: list[str] | None = None) -> Result:
    w = weights or DEFAULT_WEIGHTS
    desc = job.get("description_text") or ""
    title = job.get("title") or ""
    full = f"{title}\n{desc}"
    evidence: list[dict] = []
    uncertain: list[str] = []
    failed: list[str] = []

    # Technical skills
    required = job.get("skills") or extract_skills(full)
    matched = [s for s in required if s in profile.skills]
    missing = [s for s in required if s not in profile.skills]
    tech = round(w["technical"] * len(matched) / len(required)) if required else 0
    for s in matched:
        evidence.append({"criterion": "technical", "job_quote": _quote(full, s), "fact_id": profile.skills[s]})
    if not required:
        uncertain.append("No recognizable technical skills in the description")

    # Experience / seniority (candidate: about 10 months professional experience)
    seniority = job.get("seniority") or detect_seniority(title, desc)
    exp_share = {"junior": 1.0, "student": 0.6, "unknown": 0.5, "mid": 0.45, "senior": 0.0}[seniority]
    exp = round(w["experience"] * exp_share)
    evidence.append({"criterion": "experience", "job_quote": title, "fact_id": None})

    # Track
    track = detect_track(title, desc)
    trk = w["track"] if track in ("A", "B", "C", "D") else round(w["track"] * 0.25)

    # Language
    lang_reqs = job.get("language_reqs") or detect_languages(desc)
    lang = w["language"]
    for req in lang_reqs:
        have = profile.languages.get(req["language"])
        if req.get("mandatory"):
            if have is None:
                lang = round(w["language"] * 0.5)
                uncertain.append(f"{req['language'].title()} ({req['level']}) required; your level is not verified")
            elif CEFR.index(have[0].lower()) < CEFR.index(req["level"].lower() if req["level"].lower() in CEFR
                                                               else "c1") if have[0].lower() in CEFR else False:
                lang = 0
                failed.append(f"{req['language'].title()} ({req['level']}) required; verified level is {have[0]}")
            else:
                evidence.append({"criterion": "language", "job_quote": _quote(desc, req["language"]),
                                 "fact_id": have[1]})

    # Location / arrangement
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
    if seniority == "student" or track == "D":
        enrol = profile.eligibility.get("enrolment_status")
        if enrol is None or not enrol[0]:
            uncertain.append("Student position: your enrolment status is not verified")
        elif enrol[0].lower() not in ("enrolled", "immatrikuliert"):
            failed.append(f"Student position requires enrolment; verified status is '{enrol[0]}'")
    if any(re.search(p, desc, re.I) for p in WORK_AUTH_PATTERNS):
        auth = profile.eligibility.get("work_authorization")
        if auth is None or not auth[0]:
            uncertain.append("Listing mentions work-authorization limits; yours is not verified")

    breakdown = {"technical": tech, "experience": exp, "track": trk, "language": lang, "location": loc}
    score = int(sum(breakdown.values()))

    if seniority == "senior":
        uncertain.append("Senior role: asks for more experience than your verified ~10 months")
    if failed:
        rec = "reject"
    elif seniority == "senior":
        rec = "low_priority"
    elif score >= THRESHOLDS["apply"]:
        rec = "review" if uncertain else "apply"
    elif score >= THRESHOLDS["review"]:
        rec = "review"
    else:
        rec = "low_priority"

    parts = [f"Rule-based score {score}/100 (track {track}, {seniority})."]
    if matched:
        parts.append(f"Matches verified skills: {', '.join(matched)}.")
    if missing:
        parts.append(f"Not in your verified skills: {', '.join(missing)}.")
    if profile.unverified_count:
        parts.append(f"{profile.unverified_count} unverified profile facts were ignored.")

    return Result(
        score=score,
        breakdown=breakdown,
        track=track,
        seniority=seniority,
        recommendation=rec,
        eligibility={"failed": failed, "uncertain": uncertain},
        matched_skills=matched,
        missing_skills=missing,
        explanation=" ".join(parts),
        evidence=evidence,
    )
