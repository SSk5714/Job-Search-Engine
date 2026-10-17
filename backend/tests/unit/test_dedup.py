import pytest

from jobpilot.domain.dedup import fingerprint, normalize_url


@pytest.mark.parametrize(
    "a,b",
    [
        ("https://example.com/jobs/1", "HTTP://WWW.Example.com/jobs/1/"),
        ("https://example.com/jobs/1", "https://example.com/jobs/1?utm_source=x&utm_medium=y"),
        ("https://example.com/jobs/1", "https://example.com/jobs/1#apply"),
        ("https://example.com/jobs/1?b=2&a=1", "https://example.com/jobs/1?a=1&b=2&gclid=abc"),
        ("https://example.com/jobs/1", "https://example.com:443//jobs//1"),
        ("https://example.com/jobs/1", "https://example.com/jobs/1?trk=public_jobs&refId=123"),
    ],
)
def test_url_variants_normalize_to_the_same_value(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_meaningful_query_parameters_are_kept():
    assert normalize_url("https://e.com/view?jobId=7") != normalize_url("https://e.com/view?jobId=8")


def test_different_ports_and_paths_stay_distinct():
    assert normalize_url("https://e.com:8443/a") != normalize_url("https://e.com/a")
    assert normalize_url("https://e.com/a") != normalize_url("https://e.com/b")


def test_fingerprint_ignores_legal_suffix_and_gender_tag():
    assert fingerprint("Saxonia Data AG", "Junior Java Backend Developer (m/w/d)", "Dresden") == fingerprint(
        "Saxonia Data", "Junior Java Backend Developer", "dresden"
    )


def test_fingerprint_differs_by_city():
    assert fingerprint("Acme", "Java Dev", "Berlin") != fingerprint("Acme", "Java Dev", "Munich")
