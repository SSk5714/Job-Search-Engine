"""Acceptance criterion 13: the app is usable without knowing its internals.

The simple app: Jobs (matching jobs with CV, cover letter, apply link), Search monitor, Applied.
Runs against a live stack started with test jobs enabled (development mode). Skipped unless
JOBPILOT_E2E_BASE_URL is set, e.g.
  JOBPILOT_E2E_BASE_URL=http://localhost:3000 JOBPILOT_E2E_PASSWORD=... pytest tests/e2e
"""

import os

import pytest

BASE = os.environ.get("JOBPILOT_E2E_BASE_URL")
pytestmark = pytest.mark.skipif(not BASE, reason="set JOBPILOT_E2E_BASE_URL to run browser tests")


@pytest.fixture(autouse=True)
def clean_tables():  # override the DB fixture: e2e talks to the live stack only
    yield


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    shots = os.environ.get("JOBPILOT_E2E_SHOTS")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        pg.shots = shots  # type: ignore[attr-defined]
        yield pg
        browser.close()


def shot(page, name):
    if page.shots:
        page.screenshot(path=os.path.join(page.shots, f"{name}.png"), full_page=True)


def test_walkthrough(page):
    page.goto(f"{BASE}/login")
    page.get_by_label("Username").fill(os.environ.get("JOBPILOT_E2E_USER", "shubham"))
    page.get_by_label("Password").fill(os.environ["JOBPILOT_E2E_PASSWORD"])
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{BASE}/")
    page.get_by_role("heading", name="Jobs for you").wait_for()
    page.get_by_text("No matching jobs yet").wait_for()
    shot(page, "01-jobs-empty")

    # Profile: name and a few skills verified (only verified facts are used)
    page.get_by_role("link", name="Profile & settings").click()
    page.get_by_role("heading", name="Candidate profile").wait_for()
    name_row = page.locator(".row", has=page.locator("input[value='full_name']")).first
    name_row.get_by_label("Value").fill("Alex Example")
    for skill in ("Java", "Kotlin", "Android", "Gradle"):
        row = page.locator(".row", has=page.locator(f"input[value='{skill}']")).first
        row.get_by_label("Context").select_option("professional")
    page.get_by_role("button", name="Save changes").click()
    page.get_by_text("Saved as a new profile version").wait_for()
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Verify all").click()
    page.get_by_text("verified. Regenerate").wait_for()
    shot(page, "02-profile")

    # Search monitor: set keywords, search now, see the result
    page.get_by_role("link", name="Search monitor").click()
    page.get_by_role("heading", name="Search monitor").wait_for()
    page.get_by_label("Keywords (comma separated)").fill("Android, Java, Kotlin")
    page.get_by_role("button", name="Save", exact=True).click()
    page.get_by_text("Saved. The next search uses these settings.").wait_for()
    page.get_by_role("button", name="Search now").click()
    page.locator(".badge", has_text="completed").first.wait_for(timeout=60000)
    page.get_by_label("How often").select_option("weekdays")
    page.get_by_label("At (Berlin time)").fill("07:30")
    page.get_by_role("button", name="Save schedule").click()
    page.get_by_text("Weekdays at 07:30 (Europe/Berlin)").wait_for()
    shot(page, "03-monitor")

    # Jobs: matching jobs with description, link, CV and letter, apply
    page.get_by_role("link", name="Jobs", exact=True).click()
    card = page.locator("article.card").first
    card.wait_for()
    title = card.locator("h2").inner_text()
    assert card.get_by_role("link", name="Job listing ↗").get_attribute("href").startswith("http")
    card.get_by_role("button", name="Create CV & cover letter").click()
    card.get_by_role("link", name="CV (PDF)").wait_for(timeout=60000)
    shot(page, "04-jobs")
    with page.expect_download() as dl:
        card.get_by_role("link", name="Cover letter (PDF)").click()
    assert dl.value.suggested_filename.endswith(".pdf")
    assert card.get_by_role("link", name="Apply ↗").get_attribute("target") == "_blank"
    page.once("dialog", lambda d: d.accept())
    card.get_by_role("button", name="I applied ✓").click()
    page.get_by_role("heading", name=title).wait_for(state="detached")

    # Applied: the job, its link, the documents sent, and a status
    page.get_by_role("link", name="Applied").click()
    page.get_by_role("heading", name="Applied").wait_for()
    row = page.locator("tr", has_text=title)
    row.get_by_role("link", name="Job listing ↗").wait_for()
    row.get_by_role("link", name="CV sent").wait_for()
    row.get_by_role("combobox").select_option("interview")
    page.wait_for_timeout(500)
    page.reload()
    assert page.locator("tr", has_text=title).get_by_role("combobox").input_value() == "interview"
    shot(page, "05-applied")
