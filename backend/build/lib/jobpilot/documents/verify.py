"""Deterministic factual verification of document claims.

A claim passes only if everything checkable in its text is backed by the facts it
cites: skills, numbers and dates, language levels, work-authorization statements,
seniority words and promotions. Text that names the target job or company is
allowed. Claims that cite nothing may only be courtesy sentences.
"""

import re

from jobpilot.documents.factbook import FactBook
from jobpilot.documents.schema import Claim, CVContent, LetterContent
from jobpilot.domain.scoring import extract_skills

LANGUAGE_RE = re.compile(r"\b(german|english|deutsch|englisch|ielts|toefl|goethe|telc|testdaf|"
                         r"[abc][12]|fluent|native (?:speaker|language|level|proficiency)|mother tongue|bilingual)\b",
                         re.I)
AUTH_RE = re.compile(r"(work permit|work authori[sz]|visa|residence permit|sponsor|eligible to work|right to work|"
                     r"part[- ]time|full[- ]time|hours (a|per) week|available (from|to start|immediately)|"
                     r"can start|start (immediately|as soon)|enrol+ed|immatrikul)", re.I)
TITLE_RE = re.compile(r"\b(senior|lead|principal|staff engineer|manager|head of|architect|expert|team lead)\b", re.I)
PROMO_RE = re.compile(r"\bpromot", re.I)
EXPERIENCE_RE = re.compile(r"\b(experience[d]?|years?|months?|worked|built|developed|designed|led|skilled|"
                           r"proficient|expertise|knowledge of|familiar with)\b", re.I)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
LEARNING_CONTEXTS = {"learning", "coursework"}
STRONG_RE = re.compile(r"\b(experienced|expert|extensive|professional experience|years of)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


class Verifier:
    def __init__(self, book: FactBook, job: dict | None = None):
        self.book = book
        job = job or {}
        self.job_terms = [t for t in (job.get("title"), job.get("company")) if t]
        self.profile_skills = {f.value.lower(): f for f in book.by("skill")}

    def _strip_job_terms(self, text: str) -> str:
        for t in self.job_terms:
            text = re.sub(re.escape(t), " ", text, flags=re.I)
        return text

    def check(self, claim: Claim) -> list[str]:
        reasons: list[str] = []
        unknown = [i for i in claim.fact_ids if i not in self.book.facts]
        if unknown:
            reasons.append("cites facts that are not verified in your profile")
        cited = [self.book.facts[i] for i in claim.fact_ids if i in self.book.facts]
        cited_text = _norm(" ".join(f"{f.key.replace('_', ' ')} {f.value} {f.entry or ''}" for f in cited))
        text = self._strip_job_terms(claim.text)
        low = _norm(text)

        skills = set(extract_skills(low)) | {s for s in self.profile_skills
                                              if re.search(rf"(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])", low)}
        # Words that are also ordinary English only count in their technical spelling.
        if "go" in skills and not re.search(r"\bGo(lang)?\b", text):
            skills.discard("go")
        if "rest" in skills and not re.search(r"\bREST(ful)?\b", text):
            skills.discard("rest")
        for s in sorted(skills):
            if s not in cited_text:
                reasons.append(f"mentions '{s}' without citing a fact that contains it")
            elif STRONG_RE.search(low):
                fact = self.profile_skills.get(s)
                if fact and fact.context in LEARNING_CONTEXTS and fact.id in claim.fact_ids:
                    reasons.append(f"presents '{s}' as strong experience, but your profile lists it as {fact.context}")

        for n in NUMBER_RE.findall(low):
            if n not in cited_text:
                reasons.append(f"uses the number '{n}', which is not in the cited facts")

        if LANGUAGE_RE.search(low) and not any(f.category == "language" for f in cited):
            reasons.append("states a language ability without citing a verified language fact")
        if AUTH_RE.search(low) and not any(f.category == "eligibility" for f in cited):
            reasons.append("states availability or work authorization without citing a verified eligibility fact")
        for t in TITLE_RE.findall(low):
            if t.lower() not in cited_text:
                reasons.append(f"uses '{t}', which no cited fact supports")
        if PROMO_RE.search(low) and not any(f.key in ("promoted_to", "promotion_date") for f in cited):
            reasons.append("mentions a promotion without citing the verified promotion fact")
        if not claim.fact_ids and EXPERIENCE_RE.search(low):
            reasons.append("describes your experience but cites no facts")
        return list(dict.fromkeys(reasons))

    def _claims(self, items: list[tuple[str, Claim]]) -> dict:
        results = []
        for where, claim in items:
            reasons = self.check(claim)
            results.append({"where": where, "text": claim.text, "fact_ids": claim.fact_ids,
                            "status": "unsupported" if reasons else "ok", "reasons": reasons})
        unsupported = [r for r in results if r["status"] == "unsupported"]
        return {"claims": results, "unsupported_claims": [r["text"] for r in unsupported],
                "checked": len(results), "passed": len(results) - len(unsupported)}

    def cv(self, c: CVContent) -> dict:
        items = [("headline", c.headline)] + [("summary", x) for x in c.summary]
        for blk in c.experience:
            items += [(f"experience:{blk.entry}", b) for b in blk.bullets]
        for blk in c.projects:
            items += [(f"project:{blk.entry}", b) for b in blk.bullets]
        report = self._claims(items)
        problems = []
        for g in c.skill_groups:
            for fid in g.skill_fact_ids:
                f = self.book.facts.get(fid)
                if f is None or f.category != "skill":
                    problems.append(f"skill group '{g.name}' lists a fact that is not a verified skill")
        for blk in c.experience:
            if not self.book.by("employment", blk.entry):
                problems.append(f"experience entry '{blk.entry}' has no verified facts")
        for blk in c.projects:
            if not self.book.by("project", blk.entry):
                problems.append(f"project '{blk.entry}' has no verified facts")
        for e in c.education_entries:
            if not self.book.by("education", e):
                problems.append(f"education entry '{e}' has no verified facts")
        for fid in c.certification_fact_ids:
            f = self.book.facts.get(fid)
            if f is None or f.category != "certification":
                problems.append("a listed certification is not a verified certification fact")
        if not self.book.one("contact", "full_name"):
            problems.append("your full name is not filled in and verified (Settings → Contact)")
        report["structure_problems"] = list(dict.fromkeys(problems))
        report["unsupported_claims"] += report["structure_problems"]
        return report

    def letter(self, c: LetterContent) -> dict:
        items = []
        for i, p in enumerate(c.paragraphs):
            items += [(f"paragraph:{i + 1}", s) for s in p.sentences]
        report = self._claims(items)
        problems = []
        if not self.book.one("contact", "full_name"):
            problems.append("your full name is not filled in and verified (Settings → Contact)")
        for label, text in (("subject", c.subject), ("salutation", c.salutation), ("sign-off", c.sign_off)):
            r = self.check(Claim(text=text, fact_ids=[]))
            if r:
                problems.append(f"{label}: {r[0]}")
        report["structure_problems"] = problems
        report["unsupported_claims"] += problems
        return report
