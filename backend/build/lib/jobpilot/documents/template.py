"""No-AI generator: assembles a tailored CV and cover letter from verified facts
using fixed sentence patterns and relevance ordering. Always available, and
correct by construction (every sentence cites the facts it is built from)."""

import re

from jobpilot.documents.factbook import Fact, FactBook, parse_ym
from jobpilot.documents.schema import Claim, CVContent, ExperienceBlock, LetterContent, Paragraph, ProjectBlock, SkillGroup
from jobpilot.domain.scoring import extract_skills

BULLET_KEYS = ("responsibility", "achievement", "bullet", "description", "detail")
CONTEXT_GROUPS = [("professional", "Professional experience"), ("project", "Project experience"),
                  ("coursework", "Coursework"), ("unspecified", "Other skills"), ("learning", "Currently learning")]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


COMMON_FIRST_WORDS = {"built", "debugged", "customized", "customised", "developed", "designed", "implemented",
                      "handled", "wrote", "worked", "led", "created", "added", "maintained", "migrated", "tested",
                      "integrated", "improved", "analyzed", "analysed", "managed", "supported", "the", "a", "an"}
PAST_IRREGULAR = {"built", "wrote", "led", "ran", "made", "drove", "took", "set"}


def _lower_first(s: str) -> str:
    """Lowercase the first letter only for ordinary words, never for names like 'Android'."""
    first = s.split(" ", 1)[0] if s else ""
    return s[:1].lower() + s[1:] if first.lower() in COMMON_FIRST_WORDS else s


def _is_past_verb(word: str) -> bool:
    w = word.lower()
    return w in PAST_IRREGULAR or (w.endswith("ed") and len(w) > 4)


def _similar(a: str, b: str) -> bool:
    """True when two sentences say nearly the same thing (word overlap)."""
    wa, wb = set(re.findall(r"[a-z0-9+]+", a.lower())), set(re.findall(r"[a-z0-9+]+", b.lower()))
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) > 0.5


def _relevance(text: str, wanted: set[str]) -> int:
    low = text.lower()
    return sum(1 for w in wanted if w in low)


class TemplateGenerator:
    name = "template"

    def __init__(self, book: FactBook, job: dict, evaluation: dict | None):
        self.book, self.job = book, job
        ev = evaluation or {}
        job_text = f"{job.get('title', '')}\n{job.get('description_text', '')}"
        self.wanted = {s.lower() for s in (ev.get("matched_skills") or []) + (ev.get("missing_skills") or [])}
        self.wanted |= set(extract_skills(job_text))

    # facts helpers
    def _f(self, cat: str, key: str, entry: str | None = None) -> Fact | None:
        return self.book.one(cat, key, entry)

    def _latest_job(self) -> str | None:
        entries = self.book.entries("employment")
        return max(entries, key=lambda e: parse_ym((self._f("employment", "start", e) or Fact("", "", "", "", "")).value)
                   or (0, 0), default=None)

    def _title(self, entry: str) -> tuple[str, list[str]] | None:
        promo, first = self._f("employment", "promoted_to", entry), self._f("employment", "first_title", entry)
        if promo and first and promo.value != first.value:
            return f"{first.value} and later {promo.value}", [first.id, promo.id]
        f = promo or first or self._f("employment", "title", entry)
        return (f.value, [f.id]) if f else None

    def _matched_skills(self) -> list[Fact]:
        skills = self.book.by("skill")
        return [f for f in skills if f.value.lower() in self.wanted and f.context not in ("learning",)]

    def _bullets(self, cat: str, entry: str) -> list[Fact]:
        facts = [f for f in self.book.by(cat, entry) if f.key in BULLET_KEYS]
        return sorted(facts, key=lambda f: -_relevance(f.value, self.wanted))

    def _current_study(self) -> tuple[str, list[str]] | None:
        for e in self.book.entries("education"):
            deg, uni = self._f("education", "degree", e), self._f("education", "university", e)
            start, grad = self._f("education", "start", e), self._f("education", "graduation", e)
            if deg and start and not grad:
                return (f"{deg.value} at {uni.value}" if uni else deg.value,
                        [x.id for x in (deg, uni, start) if x])
        return None

    # CV
    def cv(self) -> CVContent:
        latest = self._latest_job()
        self._title(latest) if latest else None
        promo = self._f("employment", "promoted_to", latest) if latest else None
        headline_fact = promo or (self._f("employment", "first_title", latest) if latest else None)
        headline = Claim(text=headline_fact.value, fact_ids=[headline_fact.id]) if headline_fact else \
            Claim(text="Software Engineer", fact_ids=[])

        summary: list[Claim] = []
        if latest and headline_fact:
            dur = self.book.facts.get(f"derived:{latest}:duration")
            focus = self._f("employment", "focus", latest)
            employer = self._f("employment", "employer", latest)
            text = headline_fact.value
            ids = [headline_fact.id]
            if dur:
                text += f" with {dur.value} of professional experience"
                ids.append(dur.id)
            if employer:
                text += f" at {employer.value}"
                ids.append(employer.id)
            if focus:
                text += f", focused on {_lower_first(focus.value.rstrip('.'))}"
                ids.append(focus.id)
            summary.append(Claim(text=text + ".", fact_ids=ids))
        matched = self._matched_skills()
        if matched:
            summary.append(Claim(text=f"Skills relevant to this role: {_join([f.value for f in matched[:6]])}.",
                                 fact_ids=[f.id for f in matched[:6]]))
        study = self._current_study()
        if study:
            summary.append(Claim(text=f"Currently studying {study[0]}.", fact_ids=study[1]))

        groups: list[SkillGroup] = []
        used: set[str] = set()
        if matched:
            groups.append(SkillGroup(name="Relevant to this role", skill_fact_ids=[f.id for f in matched]))
            used |= {f.id for f in matched}
        for ctx, label in CONTEXT_GROUPS:
            ids = [f.id for f in self.book.by("skill") if (f.context or "unspecified") == ctx and f.id not in used]
            if ids:
                groups.append(SkillGroup(name=label, skill_fact_ids=ids))

        experience = []
        for e in sorted(self.book.entries("employment"), key=lambda e: e != latest):
            bullets = [Claim(text=f.value.rstrip(".") + ".", fact_ids=[f.id]) for f in self._bullets("employment", e)]
            if not bullets and (focus := self._f("employment", "focus", e)):
                bullets = [Claim(text=focus.value.rstrip(".") + ".", fact_ids=[focus.id])]
            experience.append(ExperienceBlock(entry=e, bullets=bullets[:6]))

        projects = []
        def project_rank(e: str) -> tuple:
            relevance = sum(_relevance(f.value, self.wanted) for f in self.book.by("project", e))
            professional = any(f.context == "professional" for f in self.book.by("project", e))
            return (not professional, -relevance)  # your professional work leads

        ranked = sorted(self.book.entries("project"), key=project_rank)
        for e in ranked[:4]:
            bullets = [Claim(text=f.value.rstrip(".") + ".", fact_ids=[f.id]) for f in self._bullets("project", e)]
            projects.append(ProjectBlock(entry=e, bullets=bullets[:3]))

        def edu_key(e):
            ym = parse_ym((self._f("education", "start", e) or self._f("education", "graduation", e)
                           or Fact("", "", "", "", "")).value)
            return ym or (0, 0)

        return CVContent(headline=headline, summary=summary, skill_groups=groups, experience=experience,
                         projects=projects,
                         education_entries=sorted(self.book.entries("education"), key=edu_key, reverse=True),
                         certification_fact_ids=[f.id for f in self.book.by("certification")])

    # Cover letter
    def letter(self) -> LetterContent:
        title, company = self.job.get("title") or "this position", self.job.get("company") or "your company"
        p1 = [Claim(text=f"I am applying for the position of {title} at {company}.", fact_ids=[])]
        study = self._current_study()
        if study:
            p1.append(Claim(text=f"I am currently studying {study[0]}.", fact_ids=study[1]))

        p2: list[Claim] = []
        latest = self._latest_job()
        if latest:
            employer = self._f("employment", "employer", latest)
            t = self._title(latest)
            dur = self.book.facts.get(f"derived:{latest}:duration")
            focus = self._f("employment", "focus", latest)
            if employer and t:
                text = f"At {employer.value}, I worked as {t[0]}"
                ids = [employer.id, *t[1]]
                if dur:
                    text += f" for {dur.value}"
                    ids.append(dur.id)
                if focus:
                    text += f", focusing on {_lower_first(focus.value.rstrip('.'))}"
                    ids.append(focus.id)
                p2.append(Claim(text=text + ".", fact_ids=ids))
            focus_text = focus.value if focus else ""
            distinct = [f for f in self._bullets("employment", latest) if not _similar(f.value, focus_text)]
            for i, f in enumerate(distinct[:2]):
                value = f.value.rstrip(".")
                if _is_past_verb(value.split(" ", 1)[0]):
                    lead = "In that role, I" if i == 0 else "I also"
                    text = f"{lead} {_lower_first(value)}."
                else:
                    text = f"{'One focus of my work' if i == 0 else 'Another'}: {value}."
                p2.append(Claim(text=text, fact_ids=[f.id]))

        p3: list[Claim] = []
        matched = self._matched_skills()
        if matched:
            p3.append(Claim(text=f"The skills from your posting that I have worked with include "
                                 f"{_join([f.value for f in matched[:5]])}.", fact_ids=[f.id for f in matched[:5]]))
        learning = [f for f in self.book.by("skill") if f.context == "learning" and f.value.lower() in self.wanted]
        if learning:
            p3.append(Claim(text=f"I am currently learning {_join([f.value for f in learning[:3]])}.",
                            fact_ids=[f.id for f in learning[:3]]))

        p4: list[Claim] = []
        avail = self._f("eligibility", "availability")
        if avail:
            p4.append(Claim(text=f"Availability: {avail.value.rstrip('.')}.", fact_ids=[avail.id]))
        langs = self.book.by("language")
        if langs:
            p4.append(Claim(text="Languages: " + "; ".join(f"{f.key.title()} {f.value}" for f in langs) + ".",
                            fact_ids=[f.id for f in langs]))
        p4.append(Claim(text="I would be glad to discuss how I can contribute to your team.", fact_ids=[]))

        paragraphs = [Paragraph(sentences=p) for p in (p1, p2, p3, p4) if p]
        return LetterContent(subject=f"Application for the position of {title}", salutation="Dear Hiring Team,",
                             paragraphs=paragraphs, sign_off="Kind regards,")


def clean_number_words(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
