import pytest

from jobpilot.agents.preparation.fields import FieldSpec, classify, propose
from jobpilot.documents.factbook import Fact, FactBook


def spec(label, kind="text", key="f", options=None):
    return FieldSpec(key=key, label=label, kind=kind, selector=f"#{key}", options=options or [])


@pytest.mark.parametrize("label,kind,category,sensitivity", [
    ("Vorname", "text", "first_name", "normal"),
    ("Nachname *", "text", "last_name", "normal"),
    ("E-Mail-Adresse", "email", "email", "normal"),
    ("Lebenslauf hochladen", "file", "cv", "normal"),
    ("Anschreiben", "file", "cover_letter", "normal"),
    ("Gehaltsvorstellung (brutto/Jahr)", "text", "salary", "sensitive"),
    ("Kündigungsfrist", "text", "notice_period", "sensitive"),
    ("Frühester Eintrittstermin", "date", "notice_period", "sensitive"),
    ("Besitzen Sie eine Arbeitserlaubnis für Deutschland?", "select", "work_authorization", "legal"),
    ("Do you need a visa sponsorship?", "radio", "sponsorship", "legal"),
    ("Schwerbehinderung", "select", "disability", "sensitive"),
    ("Geburtsdatum", "date", "diversity", "sensitive"),
    ("Staatsangehörigkeit", "text", "diversity", "sensitive"),
    ("Ich habe die Datenschutzerklärung gelesen und stimme zu", "checkbox", "consent", "legal"),
    ("Please confirm you have the right to work in the EU", "checkbox", "work_authorization", "legal"),
    ("Are you willing to relocate?", "select", "unknown", "normal"),
    ("Deutschkenntnisse", "select", "german_level", "normal"),
    ("Wie sind Sie auf uns aufmerksam geworden?", "select", "referral", "normal"),
])
def test_classification(label, kind, category, sensitivity):
    assert classify(spec(label, kind)) == (category, sensitivity)


def test_cv_label_on_a_text_box_is_not_a_file():
    assert classify(spec("Link to your CV", "url"))[0] != "cv"


@pytest.fixture
def book():
    b = FactBook(version_id="v")
    for f in [Fact("n", "contact", None, "full_name", "Alex Q Example"),
              Fact("auth", "eligibility", None, "work_authorization", "Student residence permit, 140 full days"),
              Fact("de", "language", None, "german", "A2 in progress")]:
        b.facts[f.id] = f
    return b


def test_protected_fields_get_a_hint_but_no_value(book):
    p = propose(spec("Work permit?", "select"), "work_authorization", "legal", book, None, set())
    assert p.value is None and p.needs_manual and "140 full days" in p.hint


def test_names_and_language_mapping(book):
    assert propose(spec("Last name"), "last_name", "normal", book, None, set()).value == "Example"
    opts = [{"value": "a2", "label": "A2"}, {"value": "b1", "label": "B1"}]
    p = propose(spec("German", "select", options=opts), "german_level", "normal", book, None, set())
    assert p.value == "a2" and not p.needs_manual


def test_no_matching_option_is_left_to_you(book):
    opts = [{"value": "basic", "label": "Basic"}, {"value": "fluent", "label": "Fluent"}]
    p = propose(spec("German", "select", options=opts), "german_level", "normal", book, None, set())
    assert p.value is None and p.needs_manual


def test_files_only_when_document_is_verified(book):
    assert propose(spec("CV", "file"), "cv", "normal", book, None, set()).value is None
    assert propose(spec("CV", "file"), "cv", "normal", book, None, {"cv"}).value == "document:cv"
