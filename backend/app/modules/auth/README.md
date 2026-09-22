# Authentication integration

todo-002 implements the API contract in [CONTRACTS](../../../../docs/CONTRACTS.md).

## Browser flow

1. GET `/api/v1/auth/csrf` with same-origin credentials; keep the returned CSRF token in memory.
2. Send every POST/PATCH/PUT/DELETE with `X-CSRF-Token` and the browser Cookie. The browser supplies Origin or Referer; either must match the public origin.
3. Register returns a user summary and does not log in. Login returns `{user, csrf_token}`; replace the previous CSRF token.
4. GET `/api/v1/auth/me` restores identity. POST logout returns 204. Fetch csrf again after logout.
5. 401 means unauthenticated/invalid credentials; 403 means CSRF or role denial; 404 hides inaccessible resources; 409 means duplicate username/last-admin conflict; 422 is invalid input; 429 means login throttled.

`qa_session` and `qa_prelogin` are HttpOnly, SameSite=Lax, host-only cookies; Secure in production. Auth/admin responses use Cache-Control: no-store. Sessions last 24 hours without renewal; prelogin cookies last 10 minutes. Only session token SHA256 hashes are persisted. Disabling users revokes their sessions; re-enabling does not restore them. Role checks read the current database role.

Username normalization is Unicode NFKC, trim and casefold; length 3–50 after normalization. Passwords are 12–128 characters; display names are trimmed, 1–100 characters. Register rejects extra fields including role. PATCH accepts a nonempty subset of display_name/role/is_active; null and string booleans are rejected. User summaries contain exactly id, username, display_name, role, is_active, created_at.

Validation errors retain `details: [{location: [...], code: "..."}]` and the Chinese message 请求参数无效; input values are never echoed.

## First administrator

Run in backend after migration:

```text
uv run python -m app.modules.auth.bootstrap_admin
```

Enter username and two hidden password prompts. For a managed secret pipeline, `--stdin-password` reads one password line from stdin after the username prompt. Never put a password into shell arguments/history. If hidden input is unavailable, interactive mode fails closed. There is no default administrator/password; an active administrator prevents repeated bootstrap. Existing usernames are never silently promoted. Bootstrap and user edits serialize via a PostgreSQL transaction advisory lock so concurrent operations cannot remove the last active administrator.

## Resource dependencies for 005/009/010

```python
from typing import Annotated
from fastapi import Depends
from app.modules.auth.schemas import Actor
from app.modules.auth.service import current_actor
from app.modules.auth.permissions import (
    require_roles,
    require_knowledge_access,
    require_conversation_access,
)

# In a route, use actor: Annotated[Actor, Depends(current_actor)].
# Read resource fields/membership from the database, never request body role/owner flags.
require_roles(actor, "admin")
require_knowledge_access(
    actor, visibility=kb.visibility, is_member=membership_exists, is_active=kb.is_active
)
require_conversation_access(
    actor, owner_id=conversation.user_id, assigned_agent_id=conversation.assigned_agent_id
)
```

Missing and inaccessible resources return the same 404 envelope; callers handle missing rows before the helper. The helpers authorize reads; resource modules still enforce write roles, handoff state and list/query filtering. A bare agent role never grants access to all conversations or restricted knowledge.

## Configuration and operating limits

- Production requires `PUBLIC_ORIGIN=https://your-host` (origin only) and a SESSION_SECRET of at least 32 characters. Development may leave PUBLIC_ORIGIN unset; Vite preserves the browser Host by default.
- All unsafe `/api/v1/` requests use the same CSRF guard, including multipart uploads and future SSE POST endpoints. GET handlers never change business data; csrf GET only issues a prelogin cookie.
- LOGIN_ACCOUNT_LIMIT=5 failed attempts per IP+normalized username; LOGIN_IP_LIMIT=30 total attempts per IP; LOGIN_WINDOW_SECONDS=300; LOGIN_MAX_ENTRIES=10000. Pending requests reserve account capacity, so concurrent attempts cannot exceed it. Saturation returns 429 without evicting live restrictions; expired windows are pruned on traffic.
- Limits are per API process, reset on restart and require shared storage before multiple workers/replicas. Use one API process for this foundation.
- The application ignores X-Forwarded-For itself. Development uses `--no-proxy-headers`. Production must explicitly configure the ASGI server's trusted proxy addresses; never use wildcard trust. PUBLIC_ORIGIN is independent of the proxy's internal Host.
- Password hashing uses Argon2id. Database/audit writes are synchronous in request transactions; logs exclude request bodies/cookies. Audit captures auth.register/login/logout/bootstrap and user.update. Expired sessions are removed during successful login.
- Public HTTPS browser behavior belongs to todo-016/017; todo-002 verifies production cookie attributes and origin enforcement with integration tests.

References: [argon2-cffi API](https://argon2-cffi.readthedocs.io/en/25.1.0/api.html), [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
