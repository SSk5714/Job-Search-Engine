# Security

JobPilot is a single-user application that holds personal data (your profile, CVs, applications) and can submit
applications on your behalf. This page is the Phase 6 security review: what is protected, how, how it is tested,
and the known limits.

Report a problem privately to the repository owner rather than in a public issue.

## Threats and controls

| Threat | Control | Tested by |
| --- | --- | --- |
| Password guessing | Argon2id hashes; 5 failed sign-ins per username per 15 min, 50 across all usernames (spraying), then HTTP 429 | `test_failed_sign_ins_are_limited_per_username`, `test_password_spraying_across_usernames_is_limited`, smoke test |
| Username discovery | Unknown users cost the same Argon2 check and get the same error | `test_unknown_user_and_wrong_password_look_the_same` |
| Stolen or leftover session cookie | Signed (itsdangerous), HttpOnly, SameSite=Strict, Secure behind HTTPS, 12 h max age; each cookie carries a session version: sign-out and password change end every session | `test_sign_out_ends_the_session_everywhere`, `test_change_password` |
| Cross-site request forgery | SameSite=Strict plus a required `X-Requested-With` header on every write | `test_writes_need_the_csrf_header` |
| Weak deployment secrets | Production mode refuses to start with a placeholder or short secret key, or an admin password under 12 characters; compose requires `POSTGRES_PASSWORD` | `test_production_refuses_weak_settings` |
| Clickjacking, MIME sniffing, leaking via referrer or cache | API: CSP `default-src 'none'`, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `Cache-Control: no-store`. Web: CSP (same-origin only), same frame/sniff/referrer headers, no `X-Powered-By`; HSTS from Caddy | `test_security_headers_and_no_caching`, smoke test |
| Oversized requests | Bodies over 2 MB refused before parsing | `test_oversized_bodies_are_refused` |
| Unauthenticated access | Every route except `/auth/login` and `/health` requires a session | `test_everything_except_login_needs_a_session` |
| Path traversal to files | Documents and evidence are resolved inside the storage root only; backup archives are checked member by member, links refused | `test_evidence_and_documents_cannot_escape_storage`, `test_archive_with_path_traversal_is_refused` |
| Server-side request forgery | URL import fetches only API-backed job sources; the application browser blocks `file:`, `data:` and private/local addresses and stays on the application site's host | Phase 2 and Phase 4 tests |
| Automated submission mistakes | Approval bound to hashes of the exact documents and answers; one attempt per idempotency key; unclear outcomes stop the workflow | Phase 4 tests |
| Prompt injection via job postings | Claude only extracts; code scores. Fact ids and quotes not in your verified facts or the posting are discarded; documents are checked claim by claim | Phase 2 and Phase 3 tests |
| Personal data sent to third parties | Contact facts (name, email, phone, date of birth) are never sent to Claude; the API key stays on the server | `test_claude_fabrication_is_caught_then_fixed_by_editing` checks no contact fact appears in any Claude request (Phase 3) |
| Exposed internals | API docs off in production; PostgreSQL and Redis never published; API and web bound to `127.0.0.1` unless behind Caddy | compose config, smoke test |
| Vulnerable dependencies | `pip-audit` and `npm audit` in CI. Phase 6 upgraded Next.js 15.5.4 → 15.5.28 (critical React Server Components advisories), React 19.1.10, FastAPI 0.143.5 / Starlette 1.8.0 (14 advisories), and pinned patched postcss and sharp | CI `backend` and `frontend` jobs |
| Losing data | Daily verified backups with checksums, tested restore with a safety backup, monitor alert when backups are stale | `test_backup.py`, smoke test restore drill |
| Containers | Non-root user (uid 10001), no secrets in images, healthchecks | Dockerfile |

## Known limits

- **Single user.** There are no roles; whoever signs in can do everything.
- **Lockout can be triggered by others.** Anyone who can reach the sign-in page can block it for 15 minutes with
  wrong passwords. For a personal deployment that is the trade-off for stopping guessing; put the site behind a VPN
  or Caddy basic auth if that matters.
- **Rate limits are by username, not IP**, because behind the proxy every request comes from the same address;
  the IP is only logged.
- **The web CSP allows inline scripts** (Next.js needs them without per-request nonces). There is no user-generated
  HTML, and React escapes all text.
- **Backups are not encrypted by the application.** They live in a private volume (mode 700); encrypt the copies
  you take off the server.
- **Secrets live in `.env`.** Use the server's file permissions (`chmod 600 .env`).
- **No two-factor authentication.**
