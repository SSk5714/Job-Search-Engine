"""Acceptance criterion 13: the UI is usable without knowing agent internals.

Runs against a live stack. Skipped unless JOBPILOT_E2E_BASE_URL is set, e.g.
  JOBPILOT_E2E_BASE_URL=http://localhost:3000 JOBPILOT_E2E_USER=shubham JOBPILOT_E2E_PASSWORD=... pytest tests/e2e
The target database should be freshly migrated (it creates real records).
"""

import os

import httpx
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

    # Phase 3: add and verify a name, then generate documents for the approved job
    name_row = page.locator(".row", has=page.locator("input[value='full_name']")).first
    name_row.get_by_label("Value").fill("Alex Example")
    page.get_by_role("button", name="Save changes").click()
    page.get_by_text("Saved as a new profile version").wait_for()
    name_row = page.locator(".row", has=page.locator("input[value='full_name']")).first
    name_row.get_by_role("button", name="Verify").click()
    name_row.get_by_role("button", name="Verified").wait_for()

    page.get_by_role("link", name="Application Review").click()
    page.get_by_role("button", name="Generate CV and cover letter").click()
    page.get_by_role("heading", name="CV · v1").wait_for(timeout=30000)
    page.get_by_role("heading", name="Cover letter · v1").wait_for()
    assert page.locator(".badge", has_text="Verified").count() == 2
    page.locator(".badge", has_text="Documents ready").first.wait_for()
    shot(page, "09-application-review")

    # Editing a sentence creates a new verified version
    first_summary = page.get_by_label("Summary text").first
    if first_summary.count():
        first_summary.fill("I would be glad to discuss the role.")
        page.get_by_role("button", name="Save as new version").first.click()
        page.get_by_role("heading", name="CV · v2").wait_for()
    with page.expect_download() as dl:
        page.get_by_role("link", name="PDF").first.click()
    assert dl.value.suggested_filename.endswith(".pdf")

    # Phase 4: prepare the form on the mock portal, answer what needs you, approve, submit
    portal = os.environ.get("JOBPILOT_E2E_PORTAL", "http://127.0.0.1:8100")
    httpx.post(f"{portal}/reset")
    page.get_by_label("Application page").fill(f"{portal}/apply/standard")
    page.get_by_role("button", name="Prepare form").click()
    page.get_by_role("heading", name="Final review").wait_for(timeout=60000)
    shot(page, "10-form-prepared")
    email = page.get_by_label("Email address *")
    email.fill("alex@example.org")
    email.press("Enter")
    page.get_by_text("your answer").first.wait_for()
    page.get_by_role("button", name="Tick it").click()
    page.get_by_role("button", name="Leave unticked").wait_for()
    for _ in range(20):  # leave every optional question empty
        buttons = page.get_by_role("button", name="Leave empty")
        if buttons.count() == 0:
            break
        buttons.first.click()
        page.wait_for_timeout(300)
    approve = page.get_by_role("button", name="Approve these exact documents and answers")
    approve.wait_for()
    page.get_by_text("Still to answer").wait_for(state="detached")
    assert approve.is_enabled(), page.locator(".warnbox").all_inner_texts()
    approve.click()
    page.get_by_text("Approved", exact=False).first.wait_for()
    shot(page, "11-approved")
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Submit application now").click()
    page.locator(".badge", has_text="Submitted").first.wait_for(timeout=60000)
    shot(page, "12-submitted")
    received = httpx.get(f"{portal}/submissions").json()
    assert len(received) == 1 and received[0]["first_name"] == "Alex" and received[0]["privacy"] == "accepted"

    # Phase 5: the submission and the approval request show up as notifications
    page.get_by_role("link", name="Notifications").click()
    page.get_by_role("heading", name="Notifications").wait_for()
    page.get_by_role("tab", name="Updates").click()
    page.get_by_text("Application sent:").first.wait_for()
    page.get_by_text("Ready for your approval:").first.wait_for()
    shot(page, "13-notifications")

    # Phase 5: schedule the search to run by itself
    page.get_by_role("link", name="Job Discovery").click()
    page.get_by_role("heading", name="Schedule").wait_for()
    page.get_by_label("How often").select_option("weekdays")
    page.get_by_label("At (Berlin time)").fill("07:30")
    page.get_by_role("button", name="Save schedule").click()
    page.get_by_text("Weekdays at 07:30 (Europe/Berlin)").wait_for()
    page.get_by_text("next run").wait_for()
    shot(page, "14-schedule")

    # Phase 5: health shows the scheduler and the independent monitor
    page.get_by_role("link", name="Settings & Health").click()
    page.get_by_role("heading", name="Notifications").wait_for()
    page.get_by_role("heading", name="Service health").wait_for()
    if os.environ.get("JOBPILOT_E2E_EXPECT_MONITOR"):
        page.get_by_text("System monitor · ok").wait_for(timeout=90000)
        page.get_by_text("Scheduler · ok").wait_for()
    shot(page, "15-health")
