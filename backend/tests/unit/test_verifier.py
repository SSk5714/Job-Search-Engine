"""The fact checker: what passes, what is flagged and why."""

import pytest

from jobpilot.documents.factbook import Fact, FactBook, months_between
from jobpilot.documents.schema import Claim
from jobpilot.documents.verify import Verifier


@pytest.fixture
def book():
    b = FactBook(version_id="v")
    for f in [
        Fact("f-kotlin", "skill", None, "kotlin", "Kotlin", "professional"),
        Fact("f-spring", "skill", None, "spring boot", "Spring Boot", "learning"),
        Fact("f-aosp", "skill", None, "aosp", "AOSP", "professional"),
        Fact("f-resp", "employment", "acme", "responsibility",
             "Built custom system services using Binder IPC and AIDL on Android 12"),
        Fact("f-title", "employment", "acme", "first_title", "Associate Software Engineer"),
        Fact("f-promo", "employment", "acme", "promoted_to", "Software Engineer"),
        Fact("derived:acme:duration", "employment", "acme", "duration", "10 months", derived=True),
        Fact("f-de", "language", None, "german", "A2 in progress"),
        Fact("f-avail", "eligibility", None, "availability", "Part-time up to 20 hours per week"),
        Fact("f-name", "contact", None, "full_name", "Alex Example"),
    ]:
        b.facts[f.id] = f
    return b


def check(book, text, ids, job=None):
    return Verifier(book, job).check(Claim(text=text, fact_ids=ids))


def test_supported_claim_passes(book):
    assert check(book, "Built custom system services using Binder IPC and AIDL on Android 12.", ["f-resp"]) == []


def test_skill_not_in_cited_facts_is_flagged(book):
    r = check(book, "Built system services in Kotlin and Docker.", ["f-resp", "f-kotlin"])
    assert any("'docker'" in x for x in r) and not any("'kotlin'" in x for x in r)


def test_rounded_up_duration_is_flagged(book):
    assert check(book, "Engineer with 10 months of experience.", ["f-title", "derived:acme:duration"]) == []
    r = check(book, "Engineer with 1 year of experience.", ["f-title"])
    assert any("'1'" in x for x in r)


def test_unknown_fact_ids_are_flagged(book):
    assert "cites facts that are not verified in your profile" in check(book, "Hello there.", ["nope"])


def test_language_claim_needs_language_fact(book):
    assert any("language" in x for x in check(book, "I speak fluent German.", ["f-title"]))
    r = check(book, "My German is at A2 level, in progress.", ["f-de"])
    assert not any("language ability" in x for x in r)


def test_availability_needs_eligibility_fact(book):
    assert any("availability" in x for x in check(book, "I can start immediately and work full-time.", []))
    assert check(book, "Availability: part-time up to 20 hours per week.", ["f-avail"]) == []


def test_promotion_needs_promotion_fact(book):
    assert any("promotion" in x for x in check(book, "I was promoted quickly.", ["f-title"]))
    assert not any("promotion" in x for x in check(book, "Promoted to Software Engineer.", ["f-promo"]))


def test_seniority_words_need_support(book):
    assert any("'senior'" in x for x in check(book, "Senior Android engineer.", ["f-title", "f-aosp"]))


def test_learning_skill_cannot_be_sold_as_experience(book):
    r = check(book, "Experienced Spring Boot developer.", ["f-spring"])
    assert any("learning" in x for x in r)
    assert check(book, "Currently learning Spring Boot.", ["f-spring"]) == []


def test_uncited_experience_statement_is_flagged(book):
    assert any("cites no facts" in x for x in check(book, "I have extensive experience in teams.", []))
    assert check(book, "I would be glad to discuss how I can contribute.", []) == []


def test_job_title_and_company_may_be_named(book):
    job = {"title": "Senior Android Developer", "company": "Docker GmbH"}
    assert check(book, "I am applying for the position of Senior Android Developer at Docker GmbH.", [], job) == []


def test_common_words_are_not_mistaken_for_skills(book):
    assert check(book, "I would like to go further and rest assured I will learn.", []) == []


def test_month_arithmetic():
    assert months_between("2024-10", "2025-08") == 10
    assert months_between("2024-10", None) is None


def test_native_code_is_not_a_language_claim(book):
    r = check(book, "Built custom system services using Binder IPC and AIDL on Android 12.", ["f-resp"])
    assert r == []
    assert any("language" in x for x in check(book, "I am a native speaker of Marathi.", []))


def test_country_names_are_not_language_claims(book):
    assert check(book, "Studying at Chemnitz University of Technology, Germany.", []) == []
    assert check(book, "Based in Chemnitz, Deutschland.", []) == []
    assert any("language" in x for x in check(book, "I speak German at B1.", []))
