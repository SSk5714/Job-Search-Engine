"""Source adapters against recorded responses (no live network)."""

import httpx
import pytest

from jobpilot.agents.discovery import http as source_http
from jobpilot.agents.discovery.adapters import resolve_url
from jobpilot.agents.discovery.adapters.ba_jobsuche import BAJobsucheAdapter
from jobpilot.agents.discovery.adapters.base import AdapterConfigError
from jobpilot.agents.discovery.adapters.greenhouse import GreenhouseAdapter
from jobpilot.agents.discovery.adapters.lever import LeverAdapter
from jobpilot.agents.discovery.adapters.personio import PersonioAdapter
from jobpilot.agents.discovery.http import SourceHTTPError
from jobpilot.agents.discovery.text import html_to_text
from jobpilot.schemas.agents import SearchFilters

ANY_AGE = SearchFilters(countries=["DE"], max_age_days=None)


def test_greenhouse_normalizes_and_filters(fake_sources):
    jobs = GreenhouseAdapter().fetch(ANY_AGE, {"boards": ["examplemobility"]})
    titles = {j.title for j in jobs}
    assert titles == {"Junior Android Engineer (Kotlin)", "Backend Developer Java / Spring Boot"}
    android = next(j for j in jobs if "Android" in j.title)
    assert android.country == "DE" and android.city == "Berlin"
    assert android.external_id == "gh:examplemobility:7001001"
    assert "Kotlin" in android.description_text and "<" not in android.description_text
    assert "alert(1)" not in android.description_text  # scripts dropped
    remote = next(j for j in jobs if "Spring" in j.title)
    assert remote.work_mode == "remote"


def test_greenhouse_requires_board_configuration(fake_sources):
    with pytest.raises(AdapterConfigError):
        GreenhouseAdapter().fetch(ANY_AGE, {})


def test_greenhouse_availability(fake_sources):
    a = GreenhouseAdapter()
    assert a.check_available("u", "gh:examplemobility:7001001") is True
    fake_sources.gh_open.discard("7001001")
    assert a.check_available("u", "gh:examplemobility:7001001") is False


def test_lever_eu_region_salary_and_lists(fake_sources):
    jobs = LeverAdapter().fetch(ANY_AGE, {"sites": ["exampleauto"], "region": "eu",
                                          "names": {"exampleauto": "Example Auto SE"}})
    assert [j.title for j in jobs] == ["Junior Android Automotive Engineer"]
    j = jobs[0]
    assert j.company == "Example Auto SE" and j.country == "DE" and j.work_mode == "hybrid"
    assert (j.salary_min, j.salary_max, j.currency) == (52000, 62000, "EUR")
    assert "AIDL, JNI" in j.description_text and "German B2" in j.description_text
    assert any("api.eu.lever.co" in c for c in fake_sources.calls)


def test_personio_xml_feed(fake_sources):
    jobs = PersonioAdapter().fetch(ANY_AGE, {"companies": ["example-embedded"]})
    assert [j.title for j in jobs] == ["Werkstudent Embedded Software (m/w/d)"]
    j = jobs[0]
    assert j.company == "Example Embedded GmbH" and j.city == "Chemnitz" and j.country == "DE"
    assert "C++ on Linux" in j.description_text and "Immatrikulation" in j.description_text
    assert str(j.url) == "https://example-embedded.jobs.personio.de/job/1500001"


def test_personio_rejects_entity_expansion_attacks(fake_sources):
    bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>' \
           b"<workzag-jobs><position><name>&lol2;</name></position></workzag-jobs>"
    fake_sources.overrides["https://evil.jobs.personio.de"] = [httpx.Response(200, content=bomb)]
    with pytest.raises(Exception) as e:
        PersonioAdapter().fetch(ANY_AGE, {"companies": ["evil"]})
    assert "Entities" in type(e.value).__name__ or "forbidden" in str(e.value).lower()


def test_ba_search_detail_and_api_key(fake_sources):
    jobs = BAJobsucheAdapter().fetch(SearchFilters(countries=["DE"], keywords=["Android"], max_age_days=30),
                                     {"max_pages": 1})
    assert len(jobs) == 2
    android = next(j for j in jobs if "Android" in j.title)
    assert android.country == "DE" and android.city == "Chemnitz"
    assert str(android.url) == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1001234567-S"
    assert "Kotlin" in android.description_text
    java = next(j for j in jobs if "Java" in j.title)
    assert str(java.url).startswith("https://karriere.beispiel-data.example")
    search_call = next(c for c in fake_sources.calls if "/pc/v4/jobs?" in c)
    assert "was=Android" in search_call and "veroeffentlichtseit=30" in search_call


def test_ba_skips_detail_for_known_jobs(fake_sources):
    BAJobsucheAdapter().fetch(SearchFilters(countries=["DE"], keywords=["Android"]),
                              {"max_pages": 1, "_known_external_ids": ["ba:10001-1001234567-S",
                                                                       "ba:10001-1001234568-S"]})
    assert not any("jobdetails" in c for c in fake_sources.calls)


def test_ba_only_searches_germany(fake_sources):
    assert BAJobsucheAdapter().fetch(SearchFilters(countries=["NL"]), {}) == []
    assert fake_sources.calls == []


def test_retry_on_429_then_success(fake_sources):
    fake_sources.overrides["https://boards-api.greenhouse.io"] = [httpx.Response(429, headers={"Retry-After": "1"})]
    jobs = GreenhouseAdapter().fetch(ANY_AGE, {"boards": ["examplemobility"]})
    assert len(jobs) == 2
    assert len([c for c in fake_sources.calls if "greenhouse" in c]) == 2


def test_persistent_server_error_is_bounded(fake_sources):
    fake_sources.overrides["https://boards-api.greenhouse.io"] = [httpx.Response(503) for _ in range(5)]
    with pytest.raises(SourceHTTPError) as e:
        GreenhouseAdapter().fetch(ANY_AGE, {"boards": ["examplemobility"]})
    assert e.value.code == "server_error"
    assert len(fake_sources.calls) == 3  # 1 try + 2 retries, then stop


def test_forbidden_is_not_retried(fake_sources):
    fake_sources.overrides["https://boards-api.greenhouse.io"] = [httpx.Response(403)]
    with pytest.raises(SourceHTTPError) as e:
        GreenhouseAdapter().fetch(ANY_AGE, {"boards": ["examplemobility"]})
    assert e.value.code == "forbidden" and len(fake_sources.calls) == 1


def test_requests_identify_themselves(fake_sources):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return fake_sources.handler(request)

    source_http.set_transport(httpx.MockTransport(handler))
    GreenhouseAdapter().fetch(ANY_AGE, {"boards": ["examplemobility"]})
    assert seen["ua"].startswith("JobPilotEurope/")


@pytest.mark.parametrize("url,code,has_ref", [
    ("https://job-boards.greenhouse.io/examplemobility/jobs/7001001", "greenhouse", True),
    ("https://boards.greenhouse.io/acme/jobs/123?gh_src=x", "greenhouse", True),
    ("https://jobs.eu.lever.co/exampleauto/3f9c1a2e-1111-4a2b-9c3d-000000000001", "lever", True),
    ("https://acme.jobs.personio.de/job/1500001?language=en", "personio", True),
    ("https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1001234567-S", "ba_jobsuche", True),
    ("https://www.linkedin.com/jobs/view/4012345678", "linkedin", False),
    ("https://www.stepstone.de/stellenangebote--Android-Entwickler--123.html", "stepstone", False),
    ("https://de.indeed.com/viewjob?jk=abc", "indeed", False),
    ("https://careers.some-company.example/job/1", "manual", False),
])
def test_url_resolution(url, code, has_ref):
    got_code, ref = resolve_url(url)
    assert got_code == code and (ref is not None) == has_ref


def test_html_to_text_keeps_structure_and_drops_markup():
    out = html_to_text("<p>Hello&nbsp;<b>world</b></p><ul><li>One</li><li>Two</li></ul><style>x{}</style>")
    assert out == "Hello world\n\n- One\n- Two"


def test_ba_falls_back_to_the_other_search_version_when_refused(fake_sources):
    base = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
    fake_sources.overrides[base] = [httpx.Response(403)] * 10  # the old version is refused
    adapter = BAJobsucheAdapter()
    jobs = adapter.fetch(SearchFilters(countries=["DE"], keywords=["Android", "Java"]), {"max_pages": 1})
    assert len(jobs) == 2
    v4 = [c for c in fake_sources.calls if "/pc/v4/jobs?" in c]
    v6 = [c for c in fake_sources.calls if "/pc/v6/jobs?" in c]
    assert len(v4) == 1 and len(v6) >= 2  # after the first refusal every search goes straight to v6


def test_ba_reports_forbidden_when_every_version_is_refused(fake_sources):
    from jobpilot.agents.discovery.http import SourceHTTPError

    for v in ("v4", "v6", "v4/app"):
        fake_sources.overrides[f"https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/{v}/jobs"] = \
            [httpx.Response(403)] * 5
    with pytest.raises(SourceHTTPError) as e:
        BAJobsucheAdapter().fetch(SearchFilters(countries=["DE"], keywords=["Android"]), {"max_pages": 1})
    assert e.value.code == "forbidden" and "also tried /pc/v4/jobs" in str(e.value)


def test_ba_unknown_answer_format_is_an_error_not_zero_jobs(fake_sources):
    from jobpilot.agents.discovery.http import SourceHTTPError

    for v in ("v4", "v6", "v4/app"):
        fake_sources.overrides[f"https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/{v}/jobs"] = \
            [httpx.Response(200, json={"results": []})] * 5
    with pytest.raises(SourceHTTPError) as e:
        BAJobsucheAdapter().fetch(SearchFilters(countries=["DE"], keywords=["Android"]), {"max_pages": 1})
    assert e.value.code == "unexpected_format" and "results" in str(e.value)


def test_ba_skips_a_version_with_an_unknown_format(fake_sources):
    base = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
    fake_sources.overrides[base] = [httpx.Response(200, json={"results": []})] * 10
    jobs = BAJobsucheAdapter().fetch(SearchFilters(countries=["DE"], keywords=["Android"]), {"max_pages": 1})
    assert len(jobs) == 2


def test_ba_empty_result_is_zero_jobs(fake_sources):
    base = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
    fake_sources.overrides[base] = [httpx.Response(200, json={"maxErgebnisse": 0})] * 10
    assert BAJobsucheAdapter().fetch(SearchFilters(countries=["DE"], keywords=["Android"]), {"max_pages": 1}) == []


# --- searching properly: Bundesagentur v6 answers, distance, details, kinds of position, companies ---

BA = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
V6_ANSWER = {"stellenangebote": [
    {"referenznummer": "10001-2000000001-S", "titel": "Softwareentwickler Java (m/w/d)",
     "arbeitsorte": [{"adresse": {"ort": "Zwickau", "plz": "08056", "region": "Sachsen"}}],
     "firma": "Auto Werk Sachsen GmbH", "aktuelleVeroeffentlichungsdatum": "2026-10-16"}], "maxErgebnisse": 1}


def test_ba_reads_the_v6_answer_format(fake_sources):
    fake_sources.overrides[f"{BA}/v4/jobs"] = [httpx.Response(403)] * 10
    fake_sources.overrides[f"{BA}/v6/jobs"] = [httpx.Response(200, json=V6_ANSWER)] * 10
    jobs = BAJobsucheAdapter().fetch(SearchFilters(keywords=["Java"], cities=["Chemnitz"], max_age_days=None),
                                     {"max_pages": 1})
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.title, j.company, j.city, j.external_id) == (
        "Softwareentwickler Java (m/w/d)", "Auto Werk Sachsen GmbH", "Zwickau", "ba:10001-2000000001-S")


def test_ba_keeps_jobs_in_nearby_towns(fake_sources):
    """Zwickau is inside the 50 km around Chemnitz; the API decided that, the text of the city must not undo it."""
    fake_sources.overrides[f"{BA}/v4/jobs"] = [httpx.Response(200, json=V6_ANSWER)] * 10
    jobs = BAJobsucheAdapter().fetch(SearchFilters(keywords=["Java"], cities=["Chemnitz"], max_age_days=None),
                                     {"max_pages": 1})
    assert [j.city for j in jobs] == ["Zwickau"]


def test_ba_refused_details_keep_the_job(fake_sources):
    for v in ("v4", "v3"):
        fake_sources.overrides[f"{BA}/{v}/jobdetails"] = [httpx.Response(403)] * 10
    jobs = BAJobsucheAdapter().fetch(SearchFilters(keywords=["Android"], max_age_days=None), {"max_pages": 1})
    assert len(jobs) == 2 and all(j.description_text for j in jobs)
    assert sum("/jobdetails/" in c for c in fake_sources.calls) == 2  # each version asked once, then skipped


def test_ba_searches_each_kind_of_position(fake_sources):
    BAJobsucheAdapter().fetch(SearchFilters(keywords=["Java"], job_types=["werkstudent", "praktikum", "job"],
                                            max_age_days=None), {"max_pages": 1})
    searches = [httpx.URL(c).params for c in fake_sources.calls if "/pc/v4/jobs?" in c]
    got = {(p["was"], p.get("angebotsart")) for p in searches}
    assert got == {("Werkstudent Java", None), ("Java", "34"), ("Java", "1")}


def test_ba_company_search_keeps_only_that_employer(fake_sources):
    answer = {"stellenangebote": [
        {"refnr": "10001-3000000001-S", "titel": "Werkstudent IT", "arbeitgeber": "Bayerische Motoren Werke Aktiengesellschaft",
         "arbeitsort": {"ort": "Leipzig"}, "aktuelleVeroeffentlichungsdatum": "2026-10-16"},
        {"refnr": "10001-3000000002-S", "titel": "Werkstudent Einkauf", "arbeitgeber": "Andere Firma GmbH",
         "arbeitsort": {"ort": "Leipzig"}, "aktuelleVeroeffentlichungsdatum": "2026-10-16"}], "maxErgebnisse": 2}
    fake_sources.overrides[f"{BA}/v4/jobs?was=Werkstudent&page"] = [httpx.Response(200, json=answer)] * 3
    jobs = BAJobsucheAdapter().fetch(SearchFilters(keywords=["Android"], companies=["BMW"], job_types=["werkstudent"],
                                                   max_age_days=None), {"max_pages": 1})
    company_calls = [httpx.URL(c).params for c in fake_sources.calls if "arbeitgeber=" in c]
    assert company_calls and company_calls[0]["arbeitgeber"] == "Bayerische Motoren Werke"
    assert [j.company for j in jobs if j.title == "Werkstudent IT"] == ["Bayerische Motoren Werke Aktiengesellschaft"]
    assert not any(j.company == "Andere Firma GmbH" for j in jobs)


def test_company_names_and_kinds_of_position():
    from jobpilot.agents.discovery.adapters.base import company_matches, job_type

    assert company_matches("Bayerische Motoren Werke AG", ["BMW"]) == "BMW"
    assert company_matches("BMW Group", ["BMW"]) == "BMW"
    assert company_matches("Mercedes-Benz AG", ["Mercedes-Benz"]) == "Mercedes-Benz"
    assert company_matches("Robert Bosch GmbH", ["Bosch"]) == "Bosch"
    assert company_matches("BMWK Bundesministerium", ["BMW"]) is None
    assert company_matches("Porsche Leipzig GmbH", ["Siemens", "Porsche"]) == "Porsche"
    assert job_type("Werkstudent (w/m/d) Softwareentwicklung") == "werkstudent"
    assert job_type("Pflichtpraktikum Embedded") == "praktikum"
    assert job_type("Masterarbeit: Android Security") == "abschlussarbeit"
    assert job_type("Internship Software Engineering") == "praktikum"
    assert job_type("Java Entwickler") == "job"


def test_city_filter_applies_with_keywords_too():
    from jobpilot.agents.discovery.adapters.base import relevant
    from jobpilot.schemas.agents import RawJob

    job = RawJob(url="https://x.de/1", company="A", title="Java Developer", city="Munich", country="DE")
    assert not relevant(job, SearchFilters(keywords=["Java"], cities=["Berlin"], max_age_days=None))
    assert relevant(job, SearchFilters(keywords=["Java"], cities=["Munich"], max_age_days=None))


def test_arbeitnow_filters_words_kinds_and_companies(fake_sources):
    from jobpilot.agents.discovery.adapters.arbeitnow import ArbeitnowAdapter

    jobs = ArbeitnowAdapter().fetch(SearchFilters(keywords=["Android", "Java"], max_age_days=None), {})
    assert {j.title for j in jobs} == {"Werkstudent Android Entwicklung (w/m/div.)", "Java Backend Developer"}
    students = ArbeitnowAdapter().fetch(SearchFilters(keywords=["Android"], job_types=["werkstudent", "praktikum"],
                                                      companies=["BMW"], max_age_days=None), {})
    # the Bosch student job matches the words; the BMW internship is in by company, whatever the subject
    assert {j.company for j in students} == {"Robert Bosch GmbH", "Bayerische Motoren Werke Aktiengesellschaft"}
    assert all("<" not in j.description_text for j in jobs)


def test_adzuna_needs_a_key_and_keeps_it_out_of_errors(fake_sources, monkeypatch):
    from jobpilot.agents.discovery.adapters.adzuna import AdzunaAdapter
    from jobpilot.agents.discovery.adapters.base import AdapterConfigError
    from jobpilot.config import get_settings

    with pytest.raises(AdapterConfigError):
        AdzunaAdapter().fetch(SearchFilters(keywords=["Java"]), {})
    monkeypatch.setattr(get_settings(), "adzuna_app_id", "id1")
    monkeypatch.setattr(get_settings(), "adzuna_app_key", "secret-key-123")
    jobs = AdzunaAdapter().fetch(SearchFilters(keywords=["Java"], cities=["Chemnitz"], max_age_days=None), {})
    assert [(j.title, j.city, j.salary_min) for j in jobs] == [("Java Entwickler (m/w/d)", "Chemnitz", None)]
    mb = AdzunaAdapter().fetch(SearchFilters(keywords=["Java"], companies=["Mercedes-Benz"], job_types=["werkstudent"],
                                             max_age_days=None), {})
    assert [j.company for j in mb] == ["Mercedes-Benz AG"]
    fake_sources.overrides["https://api.adzuna.com"] = [httpx.Response(500)] * 5
    from jobpilot.agents.discovery.http import SourceHTTPError
    with pytest.raises(SourceHTTPError) as e:
        AdzunaAdapter().fetch(SearchFilters(keywords=["Java"], max_age_days=None), {})
    assert "secret-key-123" not in str(e.value)
