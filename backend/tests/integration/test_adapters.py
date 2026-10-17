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
