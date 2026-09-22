# todo-002 implementation plan

> Execute inline with superpowers:executing-plans; use test-driven-development and one independent whole-branch review.

**Goal:** Deliver the already approved authentication, administration and resource authorization contract.

**Architecture:** FastAPI synchronous database sessions, PostgreSQL users and hashed opaque sessions, Argon2id password hashing. A signed short-lived prelogin cookie and session-bound HMAC CSRF token protect every unsafe API request. User roles are loaded on every request; PostgreSQL transaction advisory locking serializes administrator changes and bootstrap.

**Spec:** [todo-002](todo-002.md), [CONTRACTS](../CONTRACTS.md).

## Global constraints

- UUID IDs; UTC timestamps; user/agent/admin; self-registration creates user only.
- Username strip + Unicode NFKC + casefold, length 3–50; password 12–128; display name 1–100 after trim.
- Session lifetime 24 hours, no renewal; prelogin lifetime 10 minutes. HttpOnly, SameSite=Lax, Secure in production; no credentials in response/log/Git.
- Same-origin Origin or Referer required on unsafe /api/v1 requests; exact configured public origin (development fallback to request origin). No forwarded-header trust added by application.
- IP+normalized username: 5 failed attempts/300 seconds; IP total: 30/300 seconds. Bounded, locked in-process counters; reject saturation, never evict live restrictions.
- User A cannot read B conversations. Agent only own/assigned conversation; admin allowed. Inactive knowledge inaccessible; public authenticated or restricted member; admin may access active knowledge. Invisible resource returns 404.
- Existing environment and other worktrees remain isolated. Shared files edited under coordination lock.

## Review focus

1. Cross-user CSRF reuse and login/session fixation: tests reject copied tokens and revoke prior cookie on login/logout.
2. Concurrent administrator demotion/bootstrap: real independent transactions must leave one active admin.
3. Disabled/re-enabled users and role changes: revoke sessions on disable; read fresh role on every request.
4. Limiter concurrency/saturation/spoofed forwarding: reserve attempts atomically, bound memory, ignore untrusted X-Forwarded-For.
5. Validation errors and audit: no password, hash, session token or raw request in output.

## Task 1: Sessions and CSRF

Files: core/security.py; auth/models.py, schemas.py, service.py, router.py; migrations/versions/002_auth.py; main/config/migrations/env; tests/auth/conftest.py, test_sessions.py, test_csrf.py.
Consumes: Settings, get_db, Base, record_audit.
Produces: register/login/logout/me/csrf routes; User/AuthSession; current_user and Actor.
- [x] Write API tests first: 201 registration/user only, 200 login and cookie, replay after logout/expiry 401, missing/forged/cross-origin CSRF 403, valid multipart request succeeds.
- [x] Run uv run pytest tests/auth/test_sessions.py tests/auth/test_csrf.py -q; expect missing routes (404).
- [x] Add models/migration and Argon2 dependency; implement routes/security and global unsafe-API guard.
- [x] Run tests and full pytest; commit passing session deliverable.

## Task 2: Permissions, administration and bootstrap

Files: auth/permissions.py, bootstrap_admin.py; schemas/service/router; tests/auth/test_permissions.py, test_user_management.py, test_bootstrap.py.
Produces: require_roles, require_conversation_access, require_knowledge_access and admin endpoints.
- [x] Write failing role matrix, last-admin/concurrency, bootstrap hidden-input/repeat and session invalidation tests.
- [x] Run named tests; implement smallest authorization functions and serial admin transaction.
- [x] Run full pytest and migration checks; commit passing administration deliverable.

## Task 3: Login limiting, integration and review

Files: auth/limits.py; config/service/router; tests/auth/test_login_limits.py; auth README and CONTRACTS.
- [x] Write failing controllable-clock account/IP/concurrent/bounded-counter tests.
- [x] Implement configured fixed-window counters with thread lock; keep verification and failure registration atomic per limiter operation.
- [x] Run full unified node scripts/dev.mjs check and task checks; record actual evidence.
- [x] Independent security review, reproduce/fix important findings with tests, refresh checks for changed code.
- PR + ordinary squash under integration lock; separate status PR; verify origin/main done and sync clean main.
