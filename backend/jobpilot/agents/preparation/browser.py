"""Isolated Playwright sessions for application forms.

Every session is a fresh browser context (no cookies, no storage) that is closed
afterwards. Top-level navigation is limited to the application's own host;
file:, data: and private-network addresses are blocked; downloads are off.
Preparation fills and screenshots but never clicks submit. Submission replays
an approved plan and reports the outcome without guessing."""

import ipaddress
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from jobpilot.agents.preparation.fields import FieldSpec
from jobpilot.config import get_settings

log = logging.getLogger("jobpilot.browser")

EXTRACT_JS = r"""
() => {
  const forms = Array.from(document.forms);
  const root = forms.sort((a, b) => b.elements.length - a.elements.length)[0] || document;
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  const labelOf = (el) => {
    if (el.id) { const l = document.querySelector(`label[for="${esc(el.id)}"]`); if (l) return l.innerText; }
    const wrap = el.closest('label'); if (wrap) return wrap.innerText;
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const lb = el.getAttribute('aria-labelledby');
    if (lb) return lb.split(' ').map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    return el.placeholder || el.name || '';
  };
  const sel = (el) => el.id ? `#${esc(el.id)}` : `[name="${el.name}"]`;
  const out = []; const radios = {}; let pos = 0;
  for (const el of root.querySelectorAll('input, select, textarea')) {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image', 'password', 'search'].includes(type)) continue;
    if (el.disabled) continue;
    if (type === 'radio') {
      const g = radios[el.name] || (radios[el.name] = { key: el.name, kind: 'radio', options: [], required: false,
        selector: `[name="${el.name}"]`, position: pos++,
        label: (el.closest('fieldset') && el.closest('fieldset').querySelector('legend'))
               ? el.closest('fieldset').querySelector('legend').innerText : el.name });
      g.options.push({ value: el.value, label: labelOf(el).trim(), selector: sel(el) });
      g.required = g.required || el.required;
      continue;
    }
    const kind = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : type;
    const f = { key: el.name || el.id || `field_${pos}`, label: labelOf(el).trim(), kind, selector: sel(el),
                required: !!el.required, position: pos++, options: [] };
    if (kind === 'select') f.options = Array.from(el.options).filter(o => o.value !== '')
        .map(o => ({ value: o.value, label: o.text.trim() }));
    out.push(f);
  }
  return out.concat(Object.values(radios)).sort((a, b) => a.position - b.position);
}
"""

CAPTCHA_SELECTOR = ("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='challenges.cloudflare'], "
                    ".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]")
SUCCESS_RE = re.compile(r"thank you for (your )?appl|application (has been )?(received|submitted)|successfully "
                        r"(submitted|applied)|vielen dank für (ihre|deine) bewerbung|bewerbung (ist )?eingegangen|"
                        r"wir haben (ihre|deine) bewerbung erhalten", re.I)
REFERENCE_RE = re.compile(r"(reference|referenz|application id|bewerbungs-?nr)[^A-Za-z0-9]{0,5}([A-Z0-9][A-Z0-9-]{3,})",
                          re.I)
TRUTHY = {"checked", "true", "yes", "accepted", "on", "1"}


class BrowserBlocked(Exception):
    """Navigation left the permitted host, or the page needs a human (CAPTCHA, sign-in)."""


def _private(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False


@dataclass
class SessionLog:
    allowed_host: str
    blocked: list[str] = field(default_factory=list)


@contextmanager
def isolated_page(start_url: str):
    """A fresh, locked-down browser context bound to the start URL's host."""
    s = get_settings()
    parts = urlsplit(start_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BrowserBlocked("Only http(s) application pages can be opened")
    host = parts.hostname.lower()
    if _private(host) and not s.browser_allow_private_hosts:
        raise BrowserBlocked("Private or local network addresses are not allowed")
    log_ = SessionLog(allowed_host=host)

    def guard(route, request):
        u = urlsplit(request.url)
        h = (u.hostname or "").lower()
        if u.scheme not in ("http", "https", "blob", "data") or (u.scheme == "data" and request.is_navigation_request()):
            log_.blocked.append(request.url[:200])
            return route.abort()
        if u.scheme in ("http", "https") and _private(h) and not (s.browser_allow_private_hosts and h == host):
            log_.blocked.append(request.url[:200])
            return route.abort()
        if request.is_navigation_request() and request.frame.parent_frame is None and h != host:
            log_.blocked.append(request.url[:200])
            return route.abort()
        return route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=s.browser_headless)
        context = browser.new_context(accept_downloads=False, java_script_enabled=True, locale="en-GB",
                                      user_agent=s.http_user_agent + " (application preparation)")
        context.set_default_timeout(s.browser_timeout_s * 1000)
        context.route("**/*", guard)
        page = context.new_page()
        try:
            yield page, log_
        finally:
            context.close()  # cookies, storage and cache are discarded with the context
            browser.close()


def _human_needed(page) -> str | None:
    if page.locator(CAPTCHA_SELECTOR).count():
        return "captcha"
    if page.locator("input[type=password]").count():
        return "login"
    return None


@dataclass
class Snapshot:
    fields: list[FieldSpec]
    human_needed: str | None
    final_url: str
    blocked: list[str]
    screenshot: Path | None


def inspect_form(url: str, screenshot_to: Path, fill: dict[str, tuple[str, str]] | None = None,
                 files: dict[str, Path] | None = None) -> Snapshot:
    """Open the form, extract fields, optionally fill safe values, screenshot. Never submits."""
    with isolated_page(url) as (page, log_):
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(300)  # let late scripts run (and get blocked if they navigate away)
        need = _human_needed(page)
        specs: list[FieldSpec] = []
        if not need:
            specs = [FieldSpec(**raw) for raw in page.evaluate(EXTRACT_JS)]
            by_key = {f.key: f for f in specs}
            for key, (kind, value) in (fill or {}).items():
                spec = by_key.get(key)
                if spec:
                    _set(page, spec, value, files or {})
        screenshot_to.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_to), full_page=True)
        return Snapshot(specs, need, page.url, list(log_.blocked), screenshot_to)


def _set(page, spec: FieldSpec, value: str, files: dict[str, Path]) -> None:
    if spec.kind == "file":
        path = files.get(value)
        if path:
            page.set_input_files(spec.selector, str(path))
    elif spec.kind == "select":
        page.select_option(spec.selector, value=value)
    elif spec.kind == "radio":
        opt = next((o for o in spec.options if str(o.get("value")) == value), None)
        if opt:
            page.check(opt["selector"])
    elif spec.kind == "checkbox":
        if value.lower() in TRUTHY:
            page.check(spec.selector)
    else:
        page.fill(spec.selector, value)


def _value_matches(page, spec: FieldSpec, value: str) -> bool:
    if spec.kind in ("file",):
        return page.eval_on_selector(spec.selector, "el => el.files.length") > 0
    if spec.kind == "radio":
        opt = next((o for o in spec.options if str(o.get("value")) == value), None)
        return bool(opt) and page.is_checked(opt["selector"])
    if spec.kind == "checkbox":
        return page.is_checked(spec.selector) == (value.lower() in TRUTHY)
    return page.input_value(spec.selector) == value


@dataclass
class SubmitResult:
    status: str  # succeeded | failed | unknown
    detail: str
    reference: str | None
    final_url: str
    blocked: list[str]
    screenshot: Path | None
    clicked: bool


def submit_plan(url: str, plan: list[tuple[FieldSpec, str]], files: dict[str, Path], evidence: Path) -> SubmitResult:
    """Replay the approved values, check they landed, click submit once, classify the outcome."""
    clicked = False
    try:
        with isolated_page(url) as (page, log_):
            page.goto(url, wait_until="domcontentloaded")
            need = _human_needed(page)
            if need:
                return SubmitResult("failed", f"The page now requires a {need}; nothing was sent", None, page.url,
                                    list(log_.blocked), None, False)
            for spec, value in plan:
                _set(page, spec, value, files)
            wrong = [spec.key for spec, value in plan if not _value_matches(page, spec, value)]
            if wrong:
                return SubmitResult("failed", f"Fields did not accept the approved values: {', '.join(wrong)}; "
                                    "nothing was sent", None, page.url, list(log_.blocked), None, False)
            button = page.locator("form button[type=submit], form input[type=submit], form button:not([type])").first
            if not button.count():
                return SubmitResult("failed", "No submit button found; nothing was sent", None, page.url,
                                    list(log_.blocked), None, False)
            before = page.url
            clicked = True
            try:
                with page.expect_navigation(wait_until="domcontentloaded",
                                            timeout=get_settings().browser_timeout_s * 1000):
                    button.click()
                navigated = True
            except PWTimeout:
                navigated = False
            evidence.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(evidence), full_page=True)
            text = page.inner_text("body")[:5000]
            if not navigated and page.url == before and page.locator(":invalid").count():
                return SubmitResult("failed", "The form rejected the input (validation errors); nothing was sent",
                                    None, page.url, list(log_.blocked), evidence, False)
            if SUCCESS_RE.search(text):
                ref = REFERENCE_RE.search(text)
                return SubmitResult("succeeded", "Confirmation shown by the portal", ref.group(2) if ref else None,
                                    page.url, list(log_.blocked), evidence, True)
            return SubmitResult("unknown", "No clear confirmation after submitting. Check the portal or your email "
                                "before trying again.", None, page.url, list(log_.blocked), evidence, True)
    except (PWError, BrowserBlocked) as e:
        return SubmitResult("unknown" if clicked else "failed",
                            ("Browser error after clicking submit: " if clicked else "Browser error before submitting: ")
                            + str(e)[:300], None, url, [], None, clicked)
