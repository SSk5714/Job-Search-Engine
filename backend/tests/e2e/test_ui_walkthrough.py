"""Acceptance criterion 13: the UI is usable without knowing agent internals.

Runs against a live stack. Skipped unless JOBPILOT_E2E_BASE_URL is set, e.g.
  JOBPILOT_E2E_BASE_URL=http://localhost:3000 JOBPILOT_E2E_USER=shubham JOBPILOT_E2E_PASSWORD=... pytest tests/e2e
The target database should be freshly migrated (it creates real records).
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
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
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
    page.get_by_role("heading", name="Today").wait_for()
    shot(page, "01-dashboard-empty")

    # Settings: set a skill context, save a new version, then verify a few skills
    page.get_by_role("link", name="Settings & Health").click()
    page.get_by_role("heading", name="Candidate profile").wait_for()
    for skill in ("Java", "Kotlin", "Android", "Gradle"):
        row = page.locator(".row", has=page.locator(f"input[value='{skill}']")).first
        row.get_by_label("Context").select_option("professional")
    page.get_by_role("button", name="Save changes").click()
    page.get_by_text("Saved as a new profile version").wait_for()
    for skill in ("Java", "Kotlin", "Android", "Gradle"):
        row = page.locator(".row", has=page.locator(f"input[value='{skill}']")).first
        row.get_by_role("button", name="Verify").click()
        row.get_by_role("button", name="Verified").wait_for()
    page.get_by_text("4 of").wait_for()
    shot(page, "02-settings")

    # Discovery: run the mock search and wait for completion
    page.get_by_role("link", name="Job Discovery").click()
    page.get_by_role("button", name="Run search").click()
    page.locator(".badge", has_text="completed").first.wait_for(timeout=30000)
    shot(page, "03-discovery")

    # Job Review: approve the top job
    page.get_by_role("link", name="Job Review").click()
    page.get_by_text("Scores use only verified profile facts").wait_for()
    first = page.locator("article.card").first
    title = first.locator("strong").first.inner_text()
    first.get_by_role("button", name="Details").click()
    first.get_by_text("Technical skills").wait_for()
    shot(page, "04-job-review")
    first.get_by_role("button", name="Approve for preparation").click()
    first.get_by_text("Approved for prep").wait_for()

    # Tracker: the approved job is listed with its history
    page.get_by_role("link", name="Tracker").click()
    page.get_by_role("cell", name=title).wait_for()
    page.get_by_role("cell", name=title).click()
    page.get_by_role("heading", name="History").wait_for()
    assert page.locator(".timeline li").count() == 3
    shot(page, "05-tracker")
    page.keyboard.press("Escape")
    page.locator(".drawer").wait_for(state="detached")

    # Dashboard reflects the run
    page.get_by_role("link", name="Dashboard").click()
    page.get_by_text("Last search completed").wait_for()
    shot(page, "06-dashboard")

    # Phase 2: add a LinkedIn job by hand (the page itself is never fetched)
    page.get_by_role("link", name="Job Review").click()
    page.get_by_role("button", name="Add job from URL").click()
    page.get_by_label("Job URL").fill("https://www.linkedin.com/jobs/view/4099999999")
    page.get_by_label("Job title").fill("Junior Kotlin Developer")
    page.get_by_label("Company").fill("Example Apps Leipzig GmbH")
    page.get_by_label("City").fill("Leipzig")
    page.get_by_label("Country (ISO)").fill("DE")
    page.get_by_label("Job description (paste)").fill("Kotlin and Android with Gradle. Junior role, English.")
    page.get_by_role("button", name="Add and score").click()
    page.get_by_text("Added: Junior Kotlin Developer").wait_for()
    page.get_by_text("Junior Kotlin Developer", exact=True).first.wait_for()
    shot(page, "07-import")

    # Phase 2: matching settings are visible and explain the matcher in use
    page.get_by_role("link", name="Settings & Health").click()
    page.get_by_role("heading", name="Matching").wait_for()
    page.get_by_text("Score weights (must total 100; now 100)").wait_for()
    shot(page, "08-matching-settings")
