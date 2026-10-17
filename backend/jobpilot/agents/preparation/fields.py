"""Form-field classification and value mapping.

Rules run in order; sensitive and legal categories come first so a question
like "Do you have a work permit? Please confirm" is never mistaken for a
harmless checkbox. Values come only from verified profile facts. Sensitive and
legal fields are NEVER proposed: you answer them yourself."""

import re
from dataclasses import dataclass, field

from jobpilot.documents.factbook import FactBook

# (category, pattern, sensitivity)
RULES: list[tuple[str, str, str]] = [
    ("disability", r"disab|behinder|handicap|accommodation", "sensitive"),
    ("diversity", r"gender|geschlecht|ethnic|race\b|veteran|pronoun|religio|nationalit|staatsangeh|citizenship|"
                  r"date of birth|geburtsdatum|\bage\b|marital|familienstand|photo|foto", "sensitive"),
    ("work_authorization", r"work permit|work authori|arbeitserlaubnis|aufenthalt|residence permit|right to work|"
                           r"eligible to work|legally (authori|allowed)|blue card|visa(?!.*sponsor)", "legal"),
    ("sponsorship", r"sponsor", "legal"),
    ("salary", r"salary|gehalt|compensation|pay expectation|vergütung|remuneration|income", "sensitive"),
    ("notice_period", r"notice period|kündigungsfrist|earliest start|start date|eintritts|available from|"
                      r"verfügbar ab|availability date|when can you start", "sensitive"),
    ("criminal", r"criminal|conviction|vorstrafe|führungszeugnis|background check", "legal"),
    ("consent", r"agree|consent|privacy|datenschutz|terms|einwillig|declar|certify|truthful|wahrheitsgem|"
                r"talent pool|keep my data", "legal"),
    ("cv", r"\bcv\b|resume|résumé|lebenslauf|curriculum", "normal"),
    ("cover_letter", r"cover letter|anschreiben|motivation letter|motivationsschreiben|letter of motivation",
     "normal"),
    ("first_name", r"first name|vorname|given name|forename", "normal"),
    ("last_name", r"last name|nachname|surname|family name", "normal"),
    ("full_name", r"^\s*(full )?name\s*\*?\s*$|vollständiger name|your name", "normal"),
    ("email", r"e-?mail", "normal"),
    ("phone", r"phone|telefon|mobile|handy|mobil", "normal"),
    ("city", r"\bcity\b|\bstadt\b|wohnort|\blocation\b|\bort\b", "normal"),
    ("country", r"country|\bland\b", "normal"),
    ("linkedin", r"linkedin", "normal"),
    ("website", r"github|website|portfolio|homepage|personal site", "normal"),
    ("german_level", r"german|deutsch", "normal"),
    ("english_level", r"english|englisch", "normal"),
    ("motivation", r"why do you|why are you|motivation|warum|what makes you|tell us about", "normal"),
    ("referral", r"how did you hear|wie sind sie|where did you (find|hear)|source|referr|empfehl", "normal"),
]
COMPILED = [(c, re.compile(p, re.I), s) for c, p, s in RULES]
PROTECTED = {"disability", "diversity", "work_authorization", "sponsorship", "salary", "notice_period",
             "criminal", "consent"}
FILE_CATEGORIES = {"cv", "cover_letter"}
AUTO_FILL_THRESHOLD = 0.9


@dataclass
class FieldSpec:
    key: str
    label: str
    kind: str  # text | email | tel | url | number | date | textarea | select | radio | checkbox | file
    selector: str
    required: bool = False
    options: list[dict] = field(default_factory=list)  # [{value, label, selector?}]
    position: int = 0


@dataclass
class Proposal:
    category: str
    sensitivity: str
    value: str | None
    source: str | None  # fact:<id> | document:cv | document:cover_letter | None
    confidence: float
    needs_manual: bool
    hint: str | None = None  # shown to you; never filled automatically


def classify(spec: FieldSpec) -> tuple[str, str]:
    text = f"{spec.label} {spec.key}".replace("_", " ")
    for category, pattern, sensitivity in COMPILED:
        if pattern.search(text):
            if category in FILE_CATEGORIES and spec.kind not in ("file", "textarea"):
                continue
            return category, sensitivity
    if spec.kind == "file":
        return "attachment_other", "normal"
    return "unknown", "normal"


def _pick_option(options: list[dict], wanted: str) -> str | None:
    """Exact-token match only; anything fuzzier is left to you."""
    w = wanted.strip().lower()
    for o in options:
        if o.get("label", "").strip().lower() == w or str(o.get("value", "")).strip().lower() == w:
            return str(o.get("value") or o.get("label"))
    return None


def _cefr(text: str) -> str | None:
    m = re.search(r"\b([ABC][12])\b", text or "", re.I)
    return m.group(1).upper() if m else None


def propose(spec: FieldSpec, category: str, sensitivity: str, book: FactBook,
            letter_text: str | None, ready_docs: set[str]) -> Proposal:
    def fact(cat: str, key: str):
        return book.one(cat, key)

    if category in PROTECTED or sensitivity != "normal":
        hint = None
        if category == "work_authorization" and (f := fact("eligibility", "work_authorization")):
            hint = f"Your verified profile says: {f.value}"
        elif category == "sponsorship" and (f := fact("eligibility", "sponsorship_required")):
            hint = f"Your verified profile says: {f.value}"
        elif category == "notice_period" and (f := fact("eligibility", "availability")):
            hint = f"Your verified profile says: {f.value}"
        return Proposal(category, sensitivity or "sensitive", None, None, 0.0, True, hint)

    def make(value: str | None, source: str | None, conf: float) -> Proposal:
        if value is None:
            return Proposal(category, sensitivity, None, None, 0.0, True)
        return Proposal(category, sensitivity, value, source, conf, conf < AUTO_FILL_THRESHOLD)

    name = fact("contact", "full_name")
    if category in FILE_CATEGORIES and spec.kind == "file":
        return make(f"document:{category}", f"document:{category}", 1.0) if category in ready_docs else make(None, None, 0)
    if category == "cover_letter" and spec.kind == "textarea":
        return make(letter_text, "document:cover_letter", 0.8) if letter_text else make(None, None, 0)
    if category == "motivation":
        return make(letter_text, "document:cover_letter", 0.6) if letter_text else make(None, None, 0)
    if category in ("first_name", "last_name", "full_name") and name:
        parts = name.value.split()
        value = {"first_name": parts[0], "last_name": parts[-1], "full_name": name.value}[category]
        return make(value, f"fact:{name.id}", 0.95 if len(parts) > 1 or category == "full_name" else 0.5)
    simple = {"email": ("contact", "email"), "phone": ("contact", "phone"), "linkedin": ("contact", "linkedin"),
              "website": ("contact", "github")}
    if category in simple and (f := fact(*simple[category])):
        return make(f.value, f"fact:{f.id}", 0.95)
    if category in ("city", "country") and (f := fact("location", "current")):
        parts = [p.strip() for p in f.value.split(",")]
        value = parts[0] if category == "city" else parts[-1]
        if spec.kind == "select":
            opt = _pick_option(spec.options, value)
            return make(opt, f"fact:{f.id}", 0.95) if opt else make(None, None, 0)
        return make(value, f"fact:{f.id}", 0.95 if len(parts) > 1 or category == "city" else 0.6)
    if category in ("german_level", "english_level"):
        f = fact("language", "german" if category == "german_level" else "english")
        if not f:
            return make(None, None, 0)
        level = _cefr(f.value)
        if spec.kind in ("select", "radio"):
            opt = _pick_option(spec.options, level) if level else None
            return make(opt, f"fact:{f.id}", 0.9) if opt else make(None, None, 0)
        return make(f.value, f"fact:{f.id}", 0.85)
    return make(None, None, 0)
