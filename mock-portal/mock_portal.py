"""Mock employer application portal for tests and demos. Never a real site.

Run:  uvicorn mock_portal:app --port 8100   (from this folder)
Forms:
  /apply/standard   typical application form (contact, files, salary, permit, consent, diversity)
  /apply/captcha    same form behind a CAPTCHA widget
  /apply/login      sign-in wall
  /apply/ambiguous  accepts the POST but shows no clear confirmation
  /apply/error      POST fails with HTTP 500
  /apply/offsite    tries to redirect the browser to another host
Inspect what was received: GET /submissions   Reset: POST /reset
"""

import itertools

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Mock application portal")
SUBMISSIONS: list[dict] = []
_ref = itertools.count(1001)

FORM = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Apply – {title}</title></head>
<body><h1>Apply for Android Developer</h1>{extra}
<form id="apply" method="post" action="/apply/{variant}" enctype="multipart/form-data">
  <label for="first_name">First name *</label><input id="first_name" name="first_name" required>
  <label for="last_name">Last name *</label><input id="last_name" name="last_name" required>
  <label for="email">Email address *</label><input id="email" name="email" type="email" required>
  <label for="phone">Phone number</label><input id="phone" name="phone" type="tel">
  <label for="city">Current location (city)</label><input id="city" name="city">
  <label for="linkedin">LinkedIn profile</label><input id="linkedin" name="linkedin" type="url">
  <label for="resume">CV / Resume (PDF) *</label><input id="resume" name="resume" type="file" accept=".pdf" required>
  <label for="cover">Cover letter</label><input id="cover" name="cover" type="file" accept=".pdf">
  <label for="salary">Salary expectation (EUR per year)</label><input id="salary" name="salary">
  <label for="start">Earliest start date</label><input id="start" name="start" type="date">
  <label for="permit">Do you have a valid work permit for Germany?</label>
  <select id="permit" name="permit"><option value="">Please choose</option><option value="yes">Yes</option>
    <option value="no">No</option></select>
  <fieldset><legend>Will you require visa sponsorship?</legend>
    <input type="radio" id="sp_yes" name="sponsorship" value="yes"><label for="sp_yes">Yes</label>
    <input type="radio" id="sp_no" name="sponsorship" value="no"><label for="sp_no">No</label></fieldset>
  <label for="german">German language level</label>
  <select id="german" name="german"><option value="">Please choose</option><option>None</option><option>A1</option>
    <option>A2</option><option>B1</option><option>B2</option><option>C1</option><option>C2</option></select>
  <label for="source">How did you hear about us?</label>
  <select id="source" name="source"><option value="">Please choose</option><option>Job board</option>
    <option>Company website</option><option>Friend</option></select>
  <label for="motivation">Why do you want to join us?</label><textarea id="motivation" name="motivation"></textarea>
  <label for="gender">Gender (optional)</label>
  <select id="gender" name="gender"><option value="">Prefer not to say</option><option>Female</option>
    <option>Male</option><option>Diverse</option></select>
  <input type="checkbox" id="privacy" name="privacy" value="accepted" required>
  <label for="privacy">I agree to the processing of my data according to the privacy policy *</label>
  <button type="submit">Submit application</button>
</form></body></html>"""

CAPTCHA = '<iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor?k=test" width="300" height="80"></iframe>'
OFFSITE = '<script>setTimeout(function(){ window.location.href = "https://tracker.invalid/collect"; }, 50);</script>'


@app.get("/apply/{variant}", response_class=HTMLResponse)
def form(variant: str):
    if variant == "login":
        return HTMLResponse("""<!doctype html><html><body><h1>Sign in to apply</h1><form method="post" action="/login">
          <label for="u">Email</label><input id="u" name="u"><label for="p">Password</label>
          <input id="p" name="p" type="password"><button type="submit">Sign in</button></form></body></html>""")
    extra = {"captcha": CAPTCHA, "offsite": OFFSITE}.get(variant, "")
    return HTMLResponse(FORM.format(title=variant, extra=extra, variant=variant))


@app.post("/apply/{variant}")
async def submit(variant: str, request: Request):
    form = await request.form()
    record = {"variant": variant}
    for k, v in form.multi_items():
        record[k] = {"filename": v.filename, "size": len(await v.read())} if hasattr(v, "filename") else v
    SUBMISSIONS.append(record)
    if variant == "error":
        return HTMLResponse("<html><body><h1>Something went wrong</h1><p>Error 500</p></body></html>", status_code=500)
    if variant == "ambiguous":
        return HTMLResponse("<html><body><h1>Processing</h1><p>We are processing your request.</p></body></html>")
    ref = f"MP-{next(_ref)}"
    return HTMLResponse(f"<html><body><h1>Thank you for your application!</h1>"
                        f"<p>Your application has been received. Reference: {ref}</p></body></html>")


@app.get("/submissions")
def submissions():
    return JSONResponse(SUBMISSIONS)


@app.post("/reset")
def reset():
    SUBMISSIONS.clear()
    return {"ok": True}
